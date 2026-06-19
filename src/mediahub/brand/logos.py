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


def logo_bg_silhouette_path(profile_id: str, logo_id: str) -> Optional[Path]:
    """Clean-alpha PNG of a logo for the signed-in background wall.

    Returns a cached transparent silhouette suitable for use as a CSS mask.
    Falls back to the raw logo path (SVGs, or if processing fails) and returns
    None only when the source logo can't be found. Safe to call per request —
    computed once, then served from cache.
    """
    src = resolve_logo_path(profile_id, logo_id)
    if not src:
        return None
    # SVGs are already clean transparent vectors; Pillow can't rasterise them
    # without an extra dependency, and they need no keying.
    if src.suffix.lower() == ".svg":
        return src
    try:
        safe = re.sub(r"[^a-z0-9._-]+", "_", (profile_id or "").lower().strip())
        dst = _data_dir() / "logo_variants" / safe / f"{logo_id}_bg.png"
        if dst.exists():
            return dst
        _render_bg_silhouette(src, dst)
        return dst if dst.exists() else src
    except Exception:
        log.warning(
            "bg silhouette failed for %s/%s — serving raw logo",
            profile_id,
            logo_id,
            exc_info=True,
        )
        return src


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
# A logo painted as a page watermark must sit at a consistent, tasteful presence
# whatever a club uploads. We measure the silhouette and pick one of two modes:
#
#   * "image"    — the logo is COLOURFUL (and so its colour carries its identity),
#                  so we paint its real artwork, with a per-logo opacity (heavy
#                  logos down, faint up), a brightness lift for dark ones, a
#                  desaturation for over-bright ones, and a halo. Keeps brand
#                  colour while never dazzling.
#   * "knockout" — the logo is MONOCHROME (black / navy / grey / white / a single
#                  ink) — colour carries no information and a brightness lift
#                  can't rescue a near-black fill (×factor of ~0 is still ~0). So
#                  we paint its SHAPE in one light, faintly brand-tinted ink via a
#                  CSS mask: guaranteed to read on the near-black page, and since
#                  the logo was already one colour, nothing is lost. SVGs (which
#                  we can't rasterise to measure here) also take this safe path.
#
# Pure deterministic pixel maths (no AI, no per-logo hand-tuning), computed once
# and cached beside the silhouette — the colour-science discipline of
# theming/logo_chip.py. Colourfulness is the Hasler–Süsstrunk metric.
# ---------------------------------------------------------------------------

_BG_TREAT_W0 = 0.085  # target perceived weight on the near-black page
_BG_TREAT_OP_MIN, _BG_TREAT_OP_MAX = 0.20, 0.88
_BG_TREAT_TARGET_LUM, _BG_TREAT_BR_MAX = 0.40, 1.8
_BG_TREAT_TARGET_SAT, _BG_TREAT_SAT_MIN = 0.42, 0.55
_BG_TREAT_COLOURFUL = 0.12  # Hasler–Süsstrunk: above this the logo is "colourful"
_BG_TREAT_KO_POP = 0.85  # a knockout ghost reads at a fixed light luminance
# Knockout / unmeasurable fallback: a light ghost at a moderate watermark weight.
_BG_TREAT_NEUTRAL = {"mode": "knockout", "opacity": 0.5}


def logo_bg_treatment(profile_id: str, logo_id: str) -> dict:
    """Per-logo backdrop treatment so ANY uploaded logo sits at the same tasteful
    watermark presence behind the page.

    Returns a small dict for inline CSS. Always carries ``mode`` ("image" or
    "knockout") and ``opacity``; "image" mode adds ``brightness``/``saturate``/
    ``halo``. Deterministic and cached beside the silhouette; returns the neutral
    knockout for SVGs (not rasterised here) or if analysis can't run.
    """
    sil = logo_bg_silhouette_path(profile_id, logo_id)
    if not sil or sil.suffix.lower() == ".svg":
        return dict(_BG_TREAT_NEUTRAL)
    cache = sil.with_suffix(".treat.json")
    try:
        if cache.exists():
            return json.loads(cache.read_text())
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

        if colourfulness >= _BG_TREAT_COLOURFUL:
            # Real artwork — its colour is its identity. Lift dark ones, calm
            # over-bright ones, halo so it separates from the near-black page.
            pop = max(lum, 0.55 * sat)
            weight = max(coverage * pop * amean, 1e-4)
            treat = {
                "mode": "image",
                "opacity": round(
                    min(_BG_TREAT_OP_MAX, max(_BG_TREAT_OP_MIN, _BG_TREAT_W0 / weight)), 3
                ),
                "brightness": round(
                    min(_BG_TREAT_BR_MAX, max(1.0, _BG_TREAT_TARGET_LUM / max(lum, 0.05))), 2
                ),
                "saturate": round(
                    min(1.0, max(_BG_TREAT_SAT_MIN, _BG_TREAT_TARGET_SAT / max(sat, 0.05))), 2
                ),
                "halo": round(min(0.30, max(0.10, 0.30 - 0.42 * lum)), 3),
            }
        else:
            # Monochrome — paint the shape as a light ghost (CSS knockout). Its
            # on-screen luminance is fixed, so opacity keys off coverage alone:
            # a dense fill is held back, a sparse line crest brought up.
            weight = max(coverage * _BG_TREAT_KO_POP * amean, 1e-4)
            treat = {
                "mode": "knockout",
                "opacity": round(
                    min(_BG_TREAT_OP_MAX, max(_BG_TREAT_OP_MIN, _BG_TREAT_W0 / weight)), 3
                ),
            }
        try:
            cache.write_text(json.dumps(treat))
        except Exception:
            pass
        return treat
    except Exception:
        log.warning("bg treatment failed for %s/%s — neutral", profile_id, logo_id, exc_info=True)
        return dict(_BG_TREAT_NEUTRAL)


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
    "describe_logo_with_ai",
]
