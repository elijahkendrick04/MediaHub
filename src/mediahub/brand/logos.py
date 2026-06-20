"""brand/logos.py — D1. Multi-logo storage + AI description.

The signup form lets the user drop any number of logo files (PNG, JPG,
SVG, WEBP, PDF, EPS, AI). This module owns:

  - on-disk storage layout under {DATA_DIR}/club_logos/<profile_id>/
  - a metadata record per logo that lives on ClubProfile.brand_logos
  - an optional AI vision pass that produces a short description +
    dominant colour palette so downstream image/motion generators can
    pick the right logo variant (mono vs full-colour, wordmark vs icon)
    without forcing the user to label each file manually

Each logo's metadata dict:

    {
      "logo_id":           "<uuid hex 12>",
      "original_filename": "navy-on-white.svg",
      "stored_path":       "club_logos/your-club/<uuid>.svg",  # relative to DATA_DIR
      "mime":              "image/svg+xml",
      "byte_size":         1234,
      "uploaded_at":       "2026-05-18T12:00:00+00:00",
      "label":             "navy on white",                   # user-editable
      "ai_description":    "Wordmark on transparent background. Suits dark UIs.",
      "ai_dominant_colours": ["#0a2540", "#f5f2e8"],
    }

No automatic logo *generation* happens here — the user uploads the
files they already have. Generation belongs to the motion / graphic
renderers downstream.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

# Register optional Pillow format plugins at import so the backdrop (and any
# other rasteriser here) can open the widest possible range of uploads — Apple
# HEIC/HEIF in particular, which a phone exports by default. Best-effort: if the
# plugin isn't installed those formats simply take the clean no-silhouette path
# (a transparent backdrop) rather than crashing. AVIF/TIFF/BMP/ICO/PSD/WEBP/GIF
# are already covered by modern Pillow itself.
try:  # pragma: no cover - depends on an optional dependency being present
    import pillow_heif as _pillow_heif

    _pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001 - any failure just means HEIC degrades cleanly
    pass

# Accepted file extensions. The user asked for "whatever format the
# club likes" so this list is intentionally broad — every common
# raster, vector, design-tool, and print format. The server validates
# by extension because some browsers (Safari especially) send empty
# MIME types for SVG / PDF / EPS / design-tool uploads.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Raster
        "png",
        "jpg",
        "jpeg",
        "webp",
        "gif",
        "bmp",
        "tiff",
        "tif",
        "heic",
        "heif",
        "avif",
        "ico",
        "jxl",
        "jp2",
        "ppm",
        # Vector
        "svg",
        "eps",
        "ai",
        "cdr",
        "wmf",
        "emf",
        # Document / multi-page
        "pdf",
        # Native design-tool files
        "psd",
        "indd",
        "sketch",
        "fig",
        "xd",
        "afdesign",
        "afphoto",
        # High-end / specialist
        "exr",
        "tga",
        "dng",
    }
)

# Per-file size cap. Logos are typically small; cap stops zip-bomb /
# disk-fill attacks while leaving headroom for high-res print files
# and native design-tool documents which can run 20-50 MB.
MAX_LOGO_BYTES = 50 * 1024 * 1024  # 50 MB

# The user explicitly asked "as many logos as the club likes". The
# cap here exists only to stop pathological abuse (e.g. an automated
# loop). 500 logos at 50 MB each is 25 GB per org which is well above
# any realistic operator concern.
MAX_LOGOS_PER_PROFILE = 500


def _data_dir() -> Path:
    base = os.environ.get("DATA_DIR")
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[1] / "data"


def logos_dir(profile_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
    if not safe:
        raise ValueError("profile_id required to resolve logos dir")
    d = _data_dir() / "club_logos" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


def _mime_for(ext: str) -> str:
    if ext == "svg":
        return "image/svg+xml"
    if ext in ("eps", "ai"):
        return "application/postscript"
    if ext == "pdf":
        return "application/pdf"
    guess, _ = mimetypes.guess_type("x." + ext)
    return guess or "application/octet-stream"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# AI vision pass — optional, gracefully no-ops without a vision model
# ---------------------------------------------------------------------------


def describe_logo_with_ai(file_bytes: bytes, mime: str) -> dict:
    """Ask the vision LLM to describe a logo. Returns ``{"description":
    str, "dominant_colours": list[str]}`` or empty dict on failure.

    The result feeds two consumers:
      1. brand.context._logos_prose — the AI sees which logo variants
         exist when picking imagery for a generated post.
      2. The signup-page thumbnail grid — short auto-label so the user
         doesn't have to type one for every variant.

    Never raises.
    """
    if not file_bytes:
        return {}
    try:
        from mediahub.media_ai import llm as _llm
    except Exception:
        return {}
    if not getattr(_llm, "is_available", lambda: False)():
        return {}
    # ``generate_vision`` is the real multimodal entry point (Gemini /
    # Anthropic). It takes local image PATHS, not raw bytes, so we stage
    # the upload to a NamedTemporaryFile with a suffix the providers
    # recognise, run vision, then always clean the temp file up.
    prompt = (
        "Describe this logo in one short sentence (<=140 chars), "
        "focusing on what makes it visually distinctive (icon "
        "vs wordmark, mono vs full-colour, light vs dark, what's "
        "suited to dark backgrounds vs light). Then list the 2-4 "
        "dominant hex colours. Return JSON with keys "
        "'description' and 'dominant_colours' (array of #rrggbb)."
    )
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get((mime or "").strip().lower(), ".png")
    raw: str
    tmp_path: Optional[str] = None
    try:
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp_path = tmp.name
            tmp.write(file_bytes)
            tmp.flush()
            tmp.close()
            raw = _llm.generate_vision([tmp_path], prompt, max_tokens=300)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    except Exception as e:
        log.debug("logo generate_vision failed: %s", e)
        return {}

    # ``generate_vision`` returns free text — pull the JSON object out.
    result = None
    try:
        from mediahub.media_ai.llm import _extract_json

        result = _extract_json(raw)
    except Exception:
        result = None
    if result is None:
        text = (raw or "").strip()
        fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            result = json.loads(text)
        except Exception:
            return {}
    if not isinstance(result, dict):
        return {}
    out: dict = {}
    desc = result.get("description")
    if isinstance(desc, str) and desc.strip():
        out["description"] = desc.strip()[:240]
    colours = result.get("dominant_colours")
    if isinstance(colours, list):
        valid: list[str] = []
        for c in colours:
            if not isinstance(c, str):
                continue
            cl = c.strip().lower()
            if not cl.startswith("#"):
                cl = "#" + cl
            if len(cl) == 4:
                cl = "#" + "".join(ch * 2 for ch in cl[1:])
            if re.match(r"^#[0-9a-f]{6}$", cl):
                valid.append(cl)
        if valid:
            out["dominant_colours"] = valid[:4]
    return out


# ---------------------------------------------------------------------------
# Storage operations
# ---------------------------------------------------------------------------


def store_logo(
    *,
    profile_id: str,
    filename: str,
    file_bytes: bytes,
    label: str = "",
    existing_logos: Optional[list[dict]] = None,
) -> dict:
    """Persist one logo to disk and return its metadata dict.

    Raises ``ValueError`` for size / extension / capacity issues so the
    web layer can surface a friendly status to the user.
    """
    if not profile_id:
        raise ValueError("profile_id required")
    if not filename:
        raise ValueError("filename required")
    if not file_bytes:
        raise ValueError("empty file")
    if len(file_bytes) > MAX_LOGO_BYTES:
        raise ValueError(f"file exceeds {MAX_LOGO_BYTES // (1024 * 1024)} MB limit")

    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"unsupported format '.{ext}' — accepted: " + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )
    if existing_logos and len(existing_logos) >= MAX_LOGOS_PER_PROFILE:
        raise ValueError(
            f"this profile already has {MAX_LOGOS_PER_PROFILE} logos — "
            "delete one before uploading another."
        )

    logo_id = uuid.uuid4().hex[:12]
    target = logos_dir(profile_id) / f"{logo_id}.{ext}"
    target.write_bytes(file_bytes)
    mime = _mime_for(ext)

    # Best-effort AI description — non-blocking on failure.
    ai = describe_logo_with_ai(file_bytes, mime)

    meta = {
        "logo_id": logo_id,
        "original_filename": filename[:240],
        "stored_path": str(target.relative_to(_data_dir())),
        "mime": mime,
        "byte_size": len(file_bytes),
        "uploaded_at": _now_iso(),
        "label": (label or "").strip()[:80],
        "ai_description": ai.get("description", ""),
        "ai_dominant_colours": ai.get("dominant_colours", []),
    }
    return meta


def delete_logo(profile_id: str, logo_id: str) -> bool:
    """Remove a logo's file from disk. Returns True if the file was
    deleted; False if it didn't exist. Never raises.
    """
    if not profile_id or not logo_id:
        return False
    try:
        d = logos_dir(profile_id)
    except Exception:
        return False
    # Try each accepted extension
    for ext in ALLOWED_EXTENSIONS:
        p = d / f"{logo_id}.{ext}"
        if p.exists():
            try:
                p.unlink()
                return True
            except Exception as e:
                log.debug("logo unlink failed for %s: %s", p, e)
                return False
    return False


def resolve_logo_path(profile_id: str, logo_id: str) -> Optional[Path]:
    """Resolve the on-disk path for a logo id. Used by the file-serving
    route. Returns None if the logo doesn't exist for that profile —
    crucial to avoid IDOR (a request for /logo/other-profile/X must
    not return the file).
    """
    if not profile_id or not logo_id:
        return None
    # Guard against traversal: logo_id must be a plain alphanumeric
    # token, not "../" or similar.
    if not re.match(r"^[a-zA-Z0-9_-]+$", logo_id):
        return None
    try:
        d = logos_dir(profile_id)
    except Exception:
        return None
    for ext in ALLOWED_EXTENSIONS:
        p = d / f"{logo_id}.{ext}"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Mirror an externally-hosted logo into first-party storage.
#
# Brand-DNA capture records the club's *website* logo as an external URL
# (``ClubProfile.brand_logo_url``) — it never downloads the bytes. That URL
# cannot be shown inside the app's own pages: the Content-Security-Policy pins
# ``img-src 'self'``, so a cross-origin <img> is blocked by the browser and
# renders as a broken-image icon (and many club sites hot-link-block or 403 a
# bare <img> anyway). This mirrors the bytes to our OWN origin once, cached by
# URL hash, so the sign-in picker / signed-in chrome / settings preview can
# serve the real logo first-party instead of a broken cross-origin link.
#
# Raster only, on purpose: auto-downloading a remote SVG and serving it from
# our origin would add a script-execution surface (SVGs can carry <script>).
# A club whose only logo is an SVG simply degrades to the initials tile — the
# deliberately-uploaded-logo path at /organisation/setup still renders SVG.
# SSRF-safe (host re-validated on every redirect hop), size-capped, content-
# type-validated. Never raises.
# ---------------------------------------------------------------------------

_MIRROR_MAX_BYTES = 8 * 1024 * 1024  # 8 MB — a web logo is far smaller
_MIRROR_TIMEOUT = 10  # seconds
_MIRROR_MAX_HOPS = 4
_MIRROR_UA = "MediaHubLogoMirror/1.0 (+https://mediahub.example/about)"

# Browser-renderable raster content-types we accept, mapped to the stored
# extension. Anything else (text/html error pages, SVG, octet-stream) is
# refused so a mirrored file is always a real image the picker can display.
_MIRROR_CT_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}
_MIRROR_EXTS: frozenset[str] = frozenset(_MIRROR_CT_EXT.values())


def _logo_cache_dir(profile_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
    if not safe:
        raise ValueError("profile_id required to resolve logo cache dir")
    d = _data_dir() / "club_logo_cache" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def mirror_external_logo(profile_id: str, url: str) -> Optional[Path]:
    """Download an external logo ``url`` into first-party cache; return the
    cached path (or ``None``).

    Idempotent — keyed on the URL hash, so a second call is a cheap disk hit
    with no network. SSRF-safe (http(s) only, host re-validated on every
    redirect hop), size-capped, raster-image-only. Never raises.
    """
    if not profile_id or not url:
        return None
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    try:
        cache_dir = _logo_cache_dir(profile_id)
    except Exception:
        return None
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    # Cache hit: any extension already written for this URL.
    for ext in _MIRROR_EXTS:
        p = cache_dir / f"{key}.{ext}"
        if p.exists():
            return p
    # Cache miss: fetch SSRF-safely, re-validating every redirect hop so a
    # public URL can never 302 the mirror onto a private/loopback address.
    try:
        import requests  # already a project dep
    except Exception:
        return None
    try:
        from mediahub.web_research.safe_fetch import is_url_safe
    except Exception:  # pragma: no cover - safe_fetch is a core module
        return None
    current = url
    for _ in range(_MIRROR_MAX_HOPS):
        if not is_url_safe(current):
            log.debug("logo mirror blocked (unsafe host): %s", current)
            return None
        try:
            r = requests.get(
                current,
                headers={"User-Agent": _MIRROR_UA, "Accept": "image/*,*/*;q=0.8"},
                timeout=_MIRROR_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except Exception as e:
            log.debug("logo mirror fetch failed for %s: %s", current, e)
            return None
        if r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("Location", "")
            if not nxt:
                return None
            current = urljoin(current, nxt)
            continue
        if r.status_code != 200:
            return None
        ct = (r.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        ext = _MIRROR_CT_EXT.get(ct)
        if not ext:
            # Server didn't send a usable image content-type — fall back to the
            # URL path's extension, but only if it's a format we accept.
            path_ext = _ext(urlparse(current).path)
            if path_ext == "jpeg":
                path_ext = "jpg"
            ext = path_ext if path_ext in _MIRROR_EXTS else None
        if not ext:
            log.debug("logo mirror refused non-image content (%r) for %s", ct, current)
            return None
        # Read with a hard size cap so a hostile/huge response can't fill disk.
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MIRROR_MAX_BYTES:
                    log.debug("logo mirror exceeded %d-byte cap for %s", _MIRROR_MAX_BYTES, current)
                    return None
                chunks.append(chunk)
        except Exception as e:
            log.debug("logo mirror read failed for %s: %s", current, e)
            return None
        data = b"".join(chunks)
        if not data:
            return None
        target = cache_dir / f"{key}.{ext}"
        try:
            target.write_bytes(data)
        except Exception as e:
            log.debug("logo mirror write failed for %s: %s", target, e)
            return None
        return target
    return None  # too many redirects


def mirror_content_type(path: Path) -> str:
    """Correct image content-type for a mirrored-logo path (extension-keyed).

    The serve route sets this explicitly because the response also carries
    ``X-Content-Type-Options: nosniff`` — a wrong/empty type would make the
    browser refuse to render the image.
    """
    by_ext = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "avif": "image/avif",
        "ico": "image/x-icon",
    }
    return by_ext.get(path.suffix.lstrip(".").lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# Background "logo wall" silhouette (signed-in chrome).
#
# The signed-in app paints a soft, brand-tinted wall of the org's logos behind
# every page (web.py `_layout`). Each mark is the logo's *silhouette*, recoloured
# to a single tint via a CSS mask — that's what makes the wall versatile across
# ANY colour combination: a black logo, a full-colour logo and a light
# "knockout" logo all read identically once tinted. For the mask to work it
# needs a clean ALPHA channel, so this turns any uploaded logo into a
# transparent silhouette:
#   - already-transparent logos keep their own alpha;
#   - opaque / flat-background logos (JPEG, white-background PNG) have that
#     background keyed out, so the mask paints only the artwork — never a block;
#   - SVGs are already clean vectors and pass straight through.
# The result is trimmed to the artwork and cached once under
# {DATA_DIR}/logo_variants/<profile_id>/<logo_id>_bg.png.
# ---------------------------------------------------------------------------

_BG_SILHOUETTE_MAX_DIM = 512


def _looks_like_svg(src: Path) -> bool:
    """Cheap sanity check that an .svg upload is actually SVG markup, so a corrupt
    or empty file isn't handed to the browser as a mask (a mask that fails to parse
    is treated as "no mask" → a solid ink block)."""
    try:
        return b"<svg" in src.read_bytes()[:2048].lower()
    except Exception:
        return False


def logo_bg_silhouette_path(profile_id: str, logo_id: str) -> Optional[Path]:
    """Clean-alpha PNG of a logo for the signed-in background wall.

    Returns a cached transparent silhouette (PNG) suitable for use as a CSS mask,
    or the raw file for a valid SVG (already a clean vector). Returns None whenever
    the source can't be found OR can't be turned into something a browser will
    paint — i.e. if we couldn't rasterise it, we don't trust it. The caller then
    serves a transparent pixel so the backdrop degrades cleanly for ANY upload
    (any format, corrupt file included). Safe to call per request — computed once,
    then served from cache.
    """
    src = resolve_logo_path(profile_id, logo_id)
    if not src:
        return None
    # SVGs are already clean transparent vectors; Pillow can't rasterise them
    # without an extra dependency, and they need no keying — pass a *valid* one
    # straight through.
    if src.suffix.lower() == ".svg":
        return src if _looks_like_svg(src) else None
    try:
        safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
        dst = _data_dir() / "logo_variants" / safe / f"{logo_id}_bg.png"
        if dst.exists():
            return dst
        _render_bg_silhouette(src, dst)
        if dst.exists():
            return dst
    except Exception as e:
        # Expected for unrenderable/corrupt uploads (PDF, EPS-without-gs, a truncated
        # file, …). The transparent-pixel fallback makes this non-actionable, and the
        # path is re-attempted per render, so keep it at debug — never spam WARNING.
        log.debug("bg silhouette unavailable for %s/%s: %s", profile_id, logo_id, e)
    # Couldn't rasterise to a clean PNG silhouette — return None so the caller
    # ships a transparent pixel rather than an un-paintable (or corrupt) file.
    return None


def _render_bg_silhouette(src: Path, dst: Path) -> None:
    """Write a trimmed, transparent-background PNG silhouette of ``src``.

    Uses the image's own alpha when it has one; otherwise keys out the flat
    background colour sampled from the border, so opaque logos still mask to
    just their artwork instead of a solid rectangle.
    """
    from PIL import Image
    import numpy as np

    with Image.open(src) as _im:
        # Downscale BEFORE the numpy work: a background mark is small, and this
        # bounds memory/CPU no matter how large the upload is.
        _im.thumbnail((_BG_SILHOUETTE_MAX_DIM, _BG_SILHOUETTE_MAX_DIM))
        im = _im.convert("RGBA")
    arr = np.asarray(im).astype(np.float32)  # H, W, 4
    alpha = arr[..., 3]
    # Treat the logo as "already transparent" only if a meaningful fraction of
    # pixels are actually see-through. A stray anti-aliased edge on an otherwise
    # opaque white-background PNG must NOT count as transparency, or it would
    # mask to a solid block — the exact failure we're guarding against.
    transparent_frac = float((alpha < 250.0).mean())
    if transparent_frac < 0.03:
        # Effectively opaque: derive alpha by keying out the flat background.
        # Sampling the 1px border ring and taking the median works for ANY
        # solid background colour (white, navy, brand-coloured tile, …), not
        # just white, and resists a logo element touching one edge.
        rgb = arr[..., :3]
        ring = np.concatenate([rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0)
        bg = np.median(ring, axis=0)
        dist = np.sqrt(((rgb - bg) ** 2).sum(axis=-1))
        # Soft matte: transparent within LO of the bg colour, opaque past HI.
        lo, hi = 26.0, 70.0
        arr[..., 3] = np.clip((dist - lo) / (hi - lo), 0.0, 1.0) * 255.0
    out = Image.fromarray(arr.astype(np.uint8), "RGBA")
    # Trim to the artwork using the alpha channel only (RGB stays non-zero
    # under keyed-out pixels). Logos often ship with generous padding.
    bbox = out.getchannel("A").getbbox()
    if bbox:
        out = out.crop(bbox)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG")


# ---------------------------------------------------------------------------
# Adaptive backdrop treatment
# A logo painted as a page watermark must sit at the SAME tasteful, identifiable
# presence whatever a club uploads — that consistency is what reads as
# "standardised and professional". We measure the silhouette and pick one of two
# modes:
#
#   * "image"    — the logo is COLOURFUL *and* light enough to read on the near-
#                  black page, so its colour carries its identity: we paint its
#                  real artwork, with a per-logo opacity (dense logos down, faint
#                  ones up) inside a TIGHT band so no club's mark dominates
#                  another's. Keeps brand colour while staying a faint watermark.
#   * "knockout" — the logo is MONOCHROME (black / navy / grey / white / a single
#                  ink), OR a DARK colourful logo whose real colour would paint as
#                  an invisible smudge on the near-black page (only its few bright
#                  accents showing, off to one side — unreadable as the logo). We
#                  paint its whole SHAPE in one light, faintly brand-tinted ink via
#                  a CSS mask: guaranteed to read on the near-black page and
#                  identifiable as the club's mark. SVGs (which we can't rasterise
#                  to measure here) also take this safe path.
#
# The blur is deliberately MODEST and tightly-banded so the mark always stays
# identifiable as the club's logo — soft-focus, never dissolved into an anonymous
# blob. Pure deterministic pixel maths (no AI, no per-logo hand-tuning), computed
# once and cached beside the silhouette — the colour-science discipline of
# theming/logo_chip.py. Colourfulness is the Hasler–Süsstrunk metric.
# ---------------------------------------------------------------------------

# Schema version for the cached treatment. BUMP this whenever the calibration
# below changes, so an already-cached *.treat.json (e.g. on the live deployment)
# recomputes with the new tuning instead of serving a stale, differently-tuned
# value — older entries lack the key and are ignored. This is what makes a
# recalibration actually reach every existing profile, not just fresh uploads.
_BG_TREAT_VERSION = 2
# Opacity auto-balance, held inside a TIGHT band so every club's mark sits at the
# same watermark-faint presence; the perceived-weight target keeps a dense logo
# from out-shouting a sparse one without letting the two drift far apart.
_BG_TREAT_W0 = 0.085  # target perceived weight on the near-black page
_BG_TREAT_OP_MIN, _BG_TREAT_OP_MAX = 0.30, 0.60
_BG_TREAT_COLOURFUL = 0.12  # Hasler–Süsstrunk: above this the logo is "colourful"
# …but only paint real artwork if the ink is light enough to actually read on the
# near-black page. A darker colourful logo (e.g. a navy crest) takes the knockout
# path so its whole shape shows as a light ghost, never an invisible dark smudge.
_BG_TREAT_DARK_FLOOR = 0.26
_BG_TREAT_KO_POP = 0.85  # a knockout ghost reads at a fixed light luminance
# Adaptive blur (display px): a MODEST, tight band so the mark always stays
# identifiable. A busier crest earns a little more blur (so its fine detail
# doesn't knife through the page) but stays readable; a simple mark sits at the
# low end. Keyed off the silhouette's alpha-edge density.
_BG_TREAT_BLUR_MIN, _BG_TREAT_BLUR_MAX = 10, 20
_BG_TREAT_BLUR_BASE, _BG_TREAT_BLUR_GAIN = 7.0, 380.0
# Knockout / unmeasurable fallback: a light ghost at a moderate watermark weight.
_BG_TREAT_NEUTRAL = {"mode": "knockout", "opacity": 0.5, "blur": 14}


def logo_bg_treatment(profile_id: str, logo_id: str) -> dict:
    """Per-logo backdrop treatment so ANY uploaded logo sits at the same tasteful
    watermark presence behind the page.

    Returns a small dict for inline CSS — ``mode`` ("image" or "knockout"),
    ``opacity``, an adaptive ``blur``, and the schema ``v``. Deterministic and
    cached beside the silhouette; returns the neutral knockout for SVGs (not
    rasterised here) or if analysis can't run.
    """
    return _treatment_for_silhouette(logo_bg_silhouette_path(profile_id, logo_id))


def _treatment_for_silhouette(sil: Optional[Path]) -> dict:
    """Core of logo_bg_treatment: derive the treatment from a prepared silhouette
    path (uploaded or mirrored). Cached beside the silhouette as ``*.treat.json``."""
    if not sil or sil.suffix.lower() == ".svg":
        return dict(_BG_TREAT_NEUTRAL)
    cache = sil.with_suffix(".treat.json")
    try:
        if cache.exists():
            cached = json.loads(cache.read_text())
            # Only trust a well-formed cache at the CURRENT schema version: a
            # finite opacity, a known mode, and a blur. Older builds could persist
            # a NaN opacity, a mode-less dict, a pre-adaptive-blur shape, or an
            # earlier calibration (no/old ``v``); ignore those and recompute rather
            # than feed a stale or bad value into the CSS.
            if (
                isinstance(cached, dict)
                and cached.get("v") == _BG_TREAT_VERSION
                and cached.get("mode") in ("image", "knockout")
            ):
                _cop = cached.get("opacity")
                if (
                    isinstance(_cop, (int, float))
                    and _cop == _cop  # finite, not NaN
                    and isinstance(cached.get("blur"), (int, float))
                ):
                    return cached
    except Exception:
        pass
    try:
        import numpy as np
        from PIL import Image

        with Image.open(sil) as _im:
            arr = np.asarray(_im.convert("RGBA")).astype(np.float32)
        alpha = arr[..., 3] / 255.0
        inked = alpha > 0.15
        if int(inked.sum()) < 10:
            return dict(_BG_TREAT_NEUTRAL)
        rgb = arr[..., :3] / 255.0
        ink_rgb = rgb[inked]
        lum_px = 0.2126 * ink_rgb[:, 0] + 0.7152 * ink_rgb[:, 1] + 0.0722 * ink_rgb[:, 2]
        mx = ink_rgb.max(-1)
        mn = ink_rgb.min(-1)
        sat_px = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
        h, w = alpha.shape
        box = float(max(h, w))  # background-size:contain → longer side fills the box
        coverage = float(inked.sum()) / (box * box)  # on-screen ink fraction of the box
        lum = float(lum_px.mean())
        sat = float(sat_px.mean())
        amean = float(alpha[inked].mean())
        # Hasler–Süsstrunk colourfulness over the inked pixels.
        rg = ink_rgb[:, 0] - ink_rgb[:, 1]
        yb = 0.5 * (ink_rgb[:, 0] + ink_rgb[:, 1]) - ink_rgb[:, 2]
        colourfulness = float(
            np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
        )
        # Shape busyness from the alpha-edge density → how much blur the crest needs
        # to read as a clean soft glow (a detailed badge with text needs far more
        # than a plain disc). Guard each axis: np.diff over a 1-px-thin silhouette
        # (an extreme line/wordmark crop) is empty and .mean() would be NaN.
        e0 = float(np.abs(np.diff(alpha, axis=0)).mean()) if alpha.shape[0] > 1 else 0.0
        e1 = float(np.abs(np.diff(alpha, axis=1)).mean()) if alpha.shape[1] > 1 else 0.0
        edges = e0 + e1
        # Never let a non-finite metric reach the CSS (it would void the filter /
        # opacity); fall back to the neutral knockout instead of caching a NaN. Run
        # this BEFORE int(round(blur)) so a NaN edge can never raise there either.
        if not bool(np.isfinite([coverage, lum, sat, amean, colourfulness, edges]).all()):
            return dict(_BG_TREAT_NEUTRAL)
        blur = int(
            round(
                min(
                    _BG_TREAT_BLUR_MAX,
                    max(_BG_TREAT_BLUR_MIN, _BG_TREAT_BLUR_BASE + _BG_TREAT_BLUR_GAIN * edges),
                )
            )
        )

        if colourfulness >= _BG_TREAT_COLOURFUL and lum >= _BG_TREAT_DARK_FLOOR:
            # Real artwork — colourful AND light enough to read on the dark page,
            # so its colour is its identity. Opacity keys off perceived weight
            # inside the tight band: a dense fill is held back, a faint mark
            # brought up, but the two never drift far apart.
            pop = max(lum, 0.55 * sat)
            weight = max(coverage * pop * amean, 1e-4)
            treat = {
                "mode": "image",
                "opacity": round(
                    min(_BG_TREAT_OP_MAX, max(_BG_TREAT_OP_MIN, _BG_TREAT_W0 / weight)), 3
                ),
                "blur": blur,
                "v": _BG_TREAT_VERSION,
            }
        else:
            # Monochrome, OR a dark colourful logo whose real colour wouldn't read
            # on the near-black page — paint the whole shape as a light ghost (CSS
            # knockout), so it's always visible and identifiable. Its on-screen
            # luminance is fixed, so opacity keys off coverage alone: a dense fill
            # is held back, a sparse line crest brought up.
            weight = max(coverage * _BG_TREAT_KO_POP * amean, 1e-4)
            treat = {
                "mode": "knockout",
                "opacity": round(
                    min(_BG_TREAT_OP_MAX, max(_BG_TREAT_OP_MIN, _BG_TREAT_W0 / weight)), 3
                ),
                "blur": blur,
                "v": _BG_TREAT_VERSION,
            }
        try:
            cache.write_text(json.dumps(treat))
        except Exception:
            pass
        return treat
    except Exception:
        log.warning("bg treatment failed for %s — neutral", sil, exc_info=True)
        return dict(_BG_TREAT_NEUTRAL)


def _mirror_cached_path(profile_id: str, url: str) -> Optional[Path]:
    """The already-downloaded mirror file for ``url`` (no network), or None."""
    if not profile_id or not url:
        return None
    try:
        cache_dir = _logo_cache_dir(profile_id)
    except Exception:
        return None
    key = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
    for ext in _MIRROR_EXTS:
        p = cache_dir / f"{key}.{ext}"
        if p.exists():
            return p
    return None


def mirror_bg_silhouette_path(
    profile_id: str, url: str, *, allow_fetch: bool = True
) -> Optional[Path]:
    """Clean-alpha silhouette of an org's WEBSITE-CAPTURED (mirrored) logo, for the
    signed-in backdrop — so it works for orgs that never uploaded a file, only had
    a logo detected from their site.

    Mirrors the same keying as ``logo_bg_silhouette_path``. ``allow_fetch=False``
    uses only an already-cached mirror (safe to call in the page-render path; it
    never makes a network request).
    """
    src = (
        mirror_external_logo(profile_id, url)
        if allow_fetch
        else _mirror_cached_path(profile_id, url)
    )
    if not src:
        return None
    if src.suffix.lower() == ".svg":
        return src if _looks_like_svg(src) else None
    try:
        safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
        key = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
        dst = _data_dir() / "logo_variants" / safe / f"mirror_{key}_bg.png"
        if dst.exists():
            return dst
        _render_bg_silhouette(src, dst)
        if dst.exists():
            return dst
    except Exception as e:
        log.debug("mirror bg silhouette unavailable for %s: %s", profile_id, e)
    return None


def mirror_bg_treatment(profile_id: str, url: str) -> dict:
    """Backdrop treatment for a mirrored website logo. Uses only an already-cached
    mirror (no network in the render path), so it returns the neutral knockout
    until the silhouette has been produced by the ``?bg=1`` serve route."""
    return _treatment_for_silhouette(mirror_bg_silhouette_path(profile_id, url, allow_fetch=False))


# ---------------------------------------------------------------------------
# Logo-chip backing tone (signed-in chrome: nav avatar, sign-in picker, settings)
#
# A logo displayed in the UI chrome sits on a small, consistent "chip" so every
# club's mark reads at the same size and weight (standardised + professional). For
# the logo to actually READ on that chip we pick the backing tone deterministically
# from the logo's own ink: a LIGHT logo (white/pale wordmark) needs a DARK chip; a
# dark or colourful logo sits on the LIGHT "paper" chip where the overwhelming
# majority of logos are designed to live. We choose whichever of the two house
# tones gives the logo the higher APCA contrast — reusing theming/contrast.py, the
# same colour-science the rest of the app trusts. Pure deterministic maths, cached
# beside the keyed silhouette as ``*.chip.json``. SVGs/unmeasurable default to the
# light paper chip (safe for the vast majority of marks).
# ---------------------------------------------------------------------------

_CHIP_TONE_VERSION = 1
_CHIP_PAPER = "#F5F2E8"  # house paper-cream — the light chip
_CHIP_INK = "#0A0B11"  # house paper-black — the dark chip


def _chip_tone_for_silhouette(sil: Optional[Path]) -> str:
    """Return ``"light"`` or ``"dark"`` — the chip backing the logo reads best on.

    Measured from the keyed silhouette's mean ink colour and decided by APCA
    contrast against the two house tones. Cached beside the silhouette. Defaults to
    ``"light"`` for SVGs (not rasterised here) or if analysis can't run."""
    if not sil or sil.suffix.lower() == ".svg":
        return "light"
    cache = sil.with_suffix(".chip.json")
    try:
        if cache.exists():
            cached = json.loads(cache.read_text())
            if (
                isinstance(cached, dict)
                and cached.get("v") == _CHIP_TONE_VERSION
                and cached.get("tone") in ("light", "dark")
            ):
                return cached["tone"]
    except Exception:
        pass
    try:
        import numpy as np
        from PIL import Image

        with Image.open(sil) as _im:
            arr = np.asarray(_im.convert("RGBA")).astype(np.float32)
        alpha = arr[..., 3] / 255.0
        inked = alpha > 0.15
        if int(inked.sum()) < 10:
            return "light"
        # Alpha-weighted mean ink colour → a single representative hex. Weighting by
        # alpha keeps soft anti-aliased edges from dragging the colour toward black.
        w = alpha[inked]
        ink = arr[..., :3][inked]
        mean_rgb = (ink * w[:, None]).sum(axis=0) / max(float(w.sum()), 1e-6)
        if not bool(np.isfinite(mean_rgb).all()):
            return "light"
        hexcol = "#%02x%02x%02x" % tuple(int(round(min(255.0, max(0.0, c)))) for c in mean_rgb)

        from mediahub.theming.contrast import apca

        # Pick the house tone the logo reads BEST against (higher |APCA Lc|). Ties
        # go to the light paper chip — the conventional home for a logo.
        lc_paper = abs(apca(hexcol, _CHIP_PAPER))
        lc_ink = abs(apca(hexcol, _CHIP_INK))
        tone = "dark" if lc_ink > lc_paper else "light"
        try:
            cache.write_text(json.dumps({"tone": tone, "v": _CHIP_TONE_VERSION}))
        except Exception:
            pass
        return tone
    except Exception:
        log.debug("chip tone unavailable for %s", sil, exc_info=True)
        return "light"


def logo_chip_tone(profile_id: str, logo_id: str) -> str:
    """Backing tone (``"light"``/``"dark"``) for an UPLOADED logo's chrome chip."""
    return _chip_tone_for_silhouette(logo_bg_silhouette_path(profile_id, logo_id))


def mirror_chip_tone(profile_id: str, url: str) -> str:
    """Backing tone for a WEBSITE-CAPTURED logo's chrome chip. Uses only an
    already-cached mirror (no network in the render path), so it returns the light
    default until the silhouette is produced by the ``?bg=1`` serve route."""
    return _chip_tone_for_silhouette(mirror_bg_silhouette_path(profile_id, url, allow_fetch=False))


# A 1×1 fully-transparent PNG, lazily decoded once. The backdrop serve routes
# ship this (HTTP 200, image/png) whenever a logo can't be turned into a
# silhouette — so a CSS ``mask-image``/``background-image`` always *loads* and the
# element hides cleanly, instead of a 404. A failed mask is the dangerous case:
# CSS treats it as "no mask", which paints the knockout element's full ink
# rectangle. This transparent pixel is the last-resort guarantee that the backdrop
# is safe for ANY upload — any format, colour, shape, or size.
_TRANSPARENT_PNG: Optional[bytes] = None


def transparent_pixel_png() -> bytes:
    """Bytes of a 1×1 fully-transparent PNG (decoded once, then cached)."""
    global _TRANSPARENT_PNG
    if _TRANSPARENT_PNG is None:
        import base64

        _TRANSPARENT_PNG = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4"
            b"2mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
    return _TRANSPARENT_PNG


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_LOGO_BYTES",
    "MAX_LOGOS_PER_PROFILE",
    "logos_dir",
    "store_logo",
    "delete_logo",
    "resolve_logo_path",
    "mirror_external_logo",
    "mirror_content_type",
    "logo_bg_silhouette_path",
    "logo_bg_treatment",
    "mirror_bg_silhouette_path",
    "mirror_bg_treatment",
    "logo_chip_tone",
    "mirror_chip_tone",
    "transparent_pixel_png",
    "describe_logo_with_ai",
]
