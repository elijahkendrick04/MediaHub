"""Motion-graphic + short-form video output via Remotion.

Public API
----------
- ``render_story_card(card_payload, brand_kit, out_path, *, variation_seed=0,
                       duration_sec=6.0) -> Path``
- ``render_meet_reel(top_cards, brand_kit, out_path, *, meet_name="",
                     duration_sec=15.0) -> Path``

Both helpers shell out to ``src/mediahub/remotion/render.js`` via Node and
cache the resulting MP4 by a deterministic content hash. Cached outputs
live under ``DATA_DIR / "motion_cache" / <hash>.mp4``; cache hits avoid
the Node bundling/rendering cost entirely.

Design notes
------------
- Node is an optional dependency. ``node_available()`` exposes a fast
  check so the web layer can degrade gracefully if Node is missing.
- The variation seed from ``mediahub.creative_brief.generator`` is woven
  into the cache key and forwarded to the Remotion composition so the
  motion render of a given card stays visually identical across calls.
- Brand-kit ingest accepts either a ``BrandKit`` dataclass or a plain dict
  (so the renderer doesn't have to import the brand package).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
from dataclasses import is_dataclass, asdict
from pathlib import Path
from typing import Any, Callable, ContextManager, NamedTuple, Optional


from mediahub.visual.reel_engine import (
    ReelEngineUnavailable,
    select_reel_engine,
)

REMOTION_DIR = Path(__file__).resolve().parents[1] / "remotion"
RENDER_SCRIPT = REMOTION_DIR / "render.js"

# Composition ids declared in src/mediahub/remotion/src/Root.tsx
COMP_STORY = "StoryCard"
COMP_REEL = "MeetReel"

# Output formats (platform comprehensiveness): the canonical 9:16 story plus
# the 4:5 portrait feed cut, the 1:1 feed square and 16:9 landscape cuts.
# The TSX compositions lay out responsively from useVideoConfig(), so one
# composition serves every size. "story" is the default and keeps every
# pre-format cache key and output filename byte-identical.
MOTION_FORMATS: dict[str, tuple[int, int]] = {
    "story": (1080, 1920),
    "portrait": (1080, 1350),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
DEFAULT_MOTION_FORMAT = "story"

# Arbitrary-canvas geometry (any-canvas): beyond the 4 named presets a caller
# may request a validated custom ``(width, height)`` cut via a canonical
# ``"WxH"`` size token (route params ``?w=&h=`` or ``?size=WxH``; there is no
# env var). The TSX compositions are preset-free responsive, so one composition
# serves any size — no ``.tsx``/``.ts``/``.css`` edit, so ``renderer_generation()``
# is unchanged and every named-preset byte stays identical (presets never leave
# the dict path below). The bounds keep the encode honest: even luma dims
# (yuv420p / h264), a sane per-dimension range, and a bounded aspect. The
# MAX ceiling also keeps a 2x supersample intermediate (≤5120px) inside libx264.
MIN_CANVAS_DIM = 256  # per-dimension floor
MAX_CANVAS_DIM = 2560  # per-dimension ceiling (2x supersample intermediate stays < libx264 limit)
MIN_CANVAS_ASPECT = 0.25  # 1:4
MAX_CANVAS_ASPECT = 4.0  # 4:1
_SIZE_TOKEN_RE = re.compile(r"^(\d{2,4})x(\d{2,4})$")  # canonical "WxH", lowercase x


def validate_canvas_size(w: int, h: int) -> tuple[int, int]:
    """Validate an arbitrary motion canvas ``(w, h)`` — the ONE resolver.

    Raises ``ValueError`` (an honest config error, same contract as
    :func:`motion_format_size`) when either dimension is not an ``int``, is
    ``< MIN_CANVAS_DIM`` or ``> MAX_CANVAS_DIM``, is **odd** (yuv420p / h264 need
    even luma dims), or the aspect ``w/h`` is outside
    ``[MIN_CANVAS_ASPECT, MAX_CANVAS_ASPECT]``. Bools are rejected explicitly
    (``bool`` is an ``int`` subclass), mirroring ``_validate_fps`` and
    ``saliency._parse_ratio``. Returns ``(w, h)`` unchanged on success.

    This is the single validator both the route layer and
    :func:`motion_format_size` call, so a size the route accepted can never
    later raise inside a deep render helper.
    """
    if isinstance(w, bool) or isinstance(h, bool):
        raise ValueError(f"canvas dims must be int, not bool: {(w, h)!r}")
    if not isinstance(w, int) or not isinstance(h, int):
        raise ValueError(f"canvas dims must be int: {(w, h)!r}")
    for dim in (w, h):
        if dim < MIN_CANVAS_DIM or dim > MAX_CANVAS_DIM:
            raise ValueError(f"canvas dim {dim} out of range [{MIN_CANVAS_DIM}, {MAX_CANVAS_DIM}]")
        if dim % 2 != 0:
            raise ValueError(f"canvas dim {dim} must be even (yuv420p / h264)")
    aspect = w / h
    if aspect < MIN_CANVAS_ASPECT or aspect > MAX_CANVAS_ASPECT:
        raise ValueError(
            f"canvas aspect {aspect:.3f} out of range "
            f"[{MIN_CANVAS_ASPECT}, {MAX_CANVAS_ASPECT}]"
        )
    return w, h


def _parse_size_token(token: str) -> Optional[tuple[int, int]]:
    """Parse a canonical ``"WxH"`` size token → validated ``(w, h)``.

    Returns ``None`` on a regex miss (so ``motion_format_size`` can then raise
    its "unknown format" error); on a regex hit calls :func:`validate_canvas_size`,
    which RAISES ``ValueError`` on an out-of-bounds / odd / bad-aspect size. The
    single validator means the token this returns is always the fully-validated
    one — never an unvalidated size on one path and a validated one on another.
    """
    m = _SIZE_TOKEN_RE.match(str(token).strip().lower())
    if m is None:
        return None
    return validate_canvas_size(int(m.group(1)), int(m.group(2)))


def canonical_motion_format(w: int, h: int) -> str:
    """Normalise a validated ``(w, h)`` to a preset NAME or a ``"WxH"`` token.

    A client that reaches a preset's exact dims via ``?w=&h=`` collapses to the
    preset name (so it reuses the preset cache key + bare filename + byte-identical
    output rather than minting a duplicate ``"1080x1920"`` cut); any other size
    returns ``f"{w}x{h}"`` built from the **validated ints**. This is the route-layer
    normaliser that keeps preset byte-identity even when a caller uses geometry
    params. ``(w, h)`` is assumed already validated by :func:`validate_canvas_size`.
    """
    for name, dims in MOTION_FORMATS.items():
        if dims == (w, h):
            return name
    return f"{w}x{h}"


def motion_format_size(format_name: str) -> tuple[int, int]:
    """Resolve a motion format name to ``(width, height)``.

    Named presets (``story``/``portrait``/``square``/``landscape``) resolve via
    the ``MOTION_FORMATS`` dict — 100% unchanged. A non-preset key is then tried
    as a canonical arbitrary-canvas ``"WxH"`` token (route params ``?w=&h=`` /
    ``?size=WxH``); a valid token returns its validated ``(w, h)``. Anything else
    raises ``ValueError`` — an honest configuration error beats silently
    rendering the wrong aspect ratio.
    """
    key = (format_name or DEFAULT_MOTION_FORMAT).strip().lower()
    if key in MOTION_FORMATS:
        return MOTION_FORMATS[key]
    parsed = _parse_size_token(key)
    if parsed is not None:
        return parsed
    raise ValueError(f"unknown motion format {format_name!r}; valid: {sorted(MOTION_FORMATS)}")


def _data_dir() -> Path:
    """Resolve the DATA_DIR at call time so tests can monkeypatch it."""
    src_root = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _cache_dir() -> Path:
    d = _data_dir() / "motion_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- motion cache eviction (deep-review #71) -------------------------------
# The motion cache (DATA_DIR/motion_cache/<hash>.mp4 + sidecars) previously grew
# without bound: unlike the still-PNG cache (graphic_renderer/render_cache.py,
# capped at 512) it had no prune, so on a bounded Render persistent disk it
# trended to exhaustion — after which every render write failed. Mirror that
# LRU prune here: bound the number of cached MP4s, evicting the oldest by mtime
# and sweeping each evicted key's sidecars. Cache hits touch the MP4's mtime so
# hot entries survive the sweep.
_DEFAULT_MOTION_CACHE_MAX = 256


def _motion_cache_max() -> int:
    try:
        n = int(os.environ.get("MEDIAHUB_MOTION_CACHE_MAX", str(_DEFAULT_MOTION_CACHE_MAX)))
    except (TypeError, ValueError):
        return _DEFAULT_MOTION_CACHE_MAX
    return max(1, n)


def _touch_cache_hit(cached: Path) -> None:
    """Refresh a cached entry's mtime so the LRU prune keeps hot renders."""
    try:
        os.utime(cached, None)
    except OSError:
        pass


def _prune_motion_cache(d: Optional[Path] = None) -> None:
    """Bound the motion cache to ``_motion_cache_max()`` video slots, oldest first.

    Each evicted ``<hash>.<ext>`` takes its sidecars with it (the ``<hash>.json``
    manifest, ``<hash>.poster.png`` poster, ``<hash>.audio.json`` record). The
    ``props/`` subdir is keyed by output-stem, not cache-hash, so it is left
    alone. Best-effort: a prune failure must never fail a successful render.

    alpha-export: the glob unions the ``.mp4`` slots with the opt-in alpha
    ``.mov``/``.webm`` slots so a transparent-export cut still counts toward the
    cap and is swept with its sidecars — otherwise alpha slots would grow
    UNBOUNDED on the bounded Render disk. With zero alpha files present the union
    returns the identical ``.mp4`` set, so the DEFAULT prune stays byte-identical.
    """
    d = d or _cache_dir()
    cap = _motion_cache_max()
    try:
        # Skip in-flight atomic-render temp files (".<stem>.<pid>.<tid>.tmp.<ext>",
        # #73) — they are hidden dotfiles, whereas a real cache entry is a bare
        # 24-hex-char stem, so they must never count toward the cap or be evicted.
        # The dotfile exclusion also drops the alpha tmp files (".<stem>...tmp.mov"
        # / ".tmp.webm").
        entries = [
            p
            for ext in ("*.mp4", "*.mov", "*.webm")
            for p in d.glob(ext)
            if not p.name.startswith(".")
        ]
    except OSError:
        return
    if len(entries) <= cap:
        return
    try:
        entries.sort(key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in entries[: len(entries) - cap]:
        # Sweep the MP4 and every sidecar sharing its 24-hex-char stem.
        for sib in d.glob(f"{p.stem}.*"):
            try:
                sib.unlink()
            except OSError:
                pass


def node_available() -> bool:
    """Return True if a `node` binary is on PATH."""
    return shutil.which("node") is not None


def remotion_installed() -> bool:
    """Return True if the Remotion deps appear to be installed locally."""
    return (REMOTION_DIR / "node_modules" / "remotion").exists()


def _logo_to_data_uri(logo_svg: Optional[str]) -> str:
    """Return a base64 SVG data URI for an inline logo string, or "".

    Mirrors the static graphic renderer's _build_logo_block: only accepts
    raw SVG markup (must start with "<"), so callers can't accidentally
    inject a stale text mark and we don't have to fetch remote logos.
    """
    if not logo_svg or not isinstance(logo_svg, str):
        return ""
    s = logo_svg.strip()
    if not s.startswith("<"):
        return ""
    encoded = base64.b64encode(s.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _brand_logo_svg(brand_kit: Any) -> str:
    """Extract the brand's raw inline SVG markup (mirrors ``_brand_to_dict``'s
    source resolution), or ``""`` when the brand carries no SVG mark.

    Only ever returns raw ``<svg …>`` markup (never a ``data:`` URI or a stale
    text mark), so the decomposer below can parse the DOM the still renderer
    also draws — no remote fetch, no invented content.
    """
    if brand_kit is None:
        raw = ""
    elif isinstance(brand_kit, dict):
        raw = brand_kit.get("logo_svg") or brand_kit.get("logoSvg") or ""
    elif is_dataclass(brand_kit):
        raw = getattr(brand_kit, "logo_svg", "") or ""
    else:
        raw = getattr(brand_kit, "logo_svg", "") or getattr(brand_kit, "logoSvg", "") or ""
    raw = raw if isinstance(raw, str) else ""
    s = raw.strip()
    return s if s.startswith("<") else ""


def _decompose_logo_svg(logo_svg: Optional[str]) -> Optional[dict]:
    """Decompose an inline SVG logo into ordered per-path draw-on data, or
    ``None`` for an honest degrade to the static filled ``<img>``.

    Returns ``{"viewBox": str, "paths": [{"d", "len", "stroke"}, …]}`` where
    ``len`` is the deterministic polyline arc-length of the path (via
    :func:`mediahub.motion.paths.from_svg`, computed here so the browser never
    calls ``getTotalLength()``) and ``stroke`` is the path's OWN resolved
    fill-or-stroke colour (inherited from an ancestor when the path itself
    declares none) — never an invented hue.

    Degrades to ``None`` (→ the existing static ``<img>``) when:
      * the markup fails to parse,
      * it has NO ``<path>`` children (a pure ``<circle>``/``<rect>``/raster
        logo the trim-path can't animate), or
      * ANY path uses a command ``paths.from_svg`` does not model (A/S/T/…),
        since a partial draw-on of a mis-parsed path would be dishonest.

    Deterministic: ``xml.etree`` parse of a fixed string + the deterministic
    arc-length maths, identical every run. No LLM, no network.
    """
    if not logo_svg or not isinstance(logo_svg, str):
        return None
    s = logo_svg.strip()
    if not s.startswith("<"):
        return None

    import xml.etree.ElementTree as ET

    from mediahub.motion import paths as _paths

    try:
        root = ET.fromstring(s)
    except ET.ParseError:
        return None

    def _local(tag: Any) -> str:
        # Strip the "{namespace}" prefix ElementTree prepends.
        return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

    # viewBox verbatim, else derived from width/height, else give up (the TSX
    # needs a coordinate space for the paths).
    view_box = (root.get("viewBox") or root.get("viewbox") or "").strip()
    if not view_box:
        w = (root.get("width") or "").strip().rstrip("px").strip()
        h = (root.get("height") or "").strip().rstrip("px").strip()
        try:
            if w and h:
                view_box = f"0 0 {float(w):g} {float(h):g}"
        except ValueError:
            view_box = ""
    if not view_box:
        return None

    # Parent map so a path with no own fill/stroke can inherit the colour its
    # ancestor <g>/<svg> declared (the same colour the browser paints the img).
    parent = {child: p for p in root.iter() for child in p}

    def _inherited(el: Any, attr: str) -> str:
        cur: Any = el
        while cur is not None:
            v = (cur.get(attr) or "").strip()
            if v:
                return v
            cur = parent.get(cur)
        return ""

    def _stroke_for(el: Any) -> str:
        fill = _inherited(el, "fill")
        if fill and fill.lower() != "none":
            return fill
        stroke = _inherited(el, "stroke")
        if stroke and stroke.lower() != "none":
            return stroke
        # SVG's default paint is black; honest (the browser paints the same),
        # never an invented brand hue.
        return "#000000"

    out_paths: list[dict] = []
    for el in root.iter():
        if _local(el.tag) != "path":
            continue
        d = (el.get("d") or "").strip()
        if not d:
            continue
        try:
            mp = _paths.from_svg(d)
        except ValueError:
            # Unsupported command (A/S/T/…): honest degrade — never a partial
            # draw of a mis-parsed path.
            return None
        out_paths.append({"d": d, "len": round(mp.length, 3), "stroke": _stroke_for(el)})

    if not out_paths:
        return None
    return {"viewBox": view_box, "paths": out_paths}


def _brand_to_dict(brand_kit: Any) -> dict[str, str]:
    """Normalise a BrandKit dataclass / dict / object into the shape the
    Remotion compositions expect.

    Phase 1.6 Stage G: when ``brand_kit.profile_id`` resolves to a
    theme in the on-disk store, prefer the theme-store palette over
    the BrandKit's flat ``primary_colour``/``secondary_colour``/
    ``accent_colour`` fields. Motion videos consume the DARK scheme's
    roles (video-grade saturation; see palette_for_motion docstring).
    Falls back to the legacy path when no theme is on disk — every
    existing render keeps working.
    """
    if brand_kit is None:
        src: dict[str, Any] = {}
    elif isinstance(brand_kit, dict):
        src = brand_kit
    elif is_dataclass(brand_kit):
        src = asdict(brand_kit)
    else:
        src = {
            "profile_id": getattr(brand_kit, "profile_id", ""),
            "display_name": getattr(brand_kit, "display_name", ""),
            "short_name": getattr(brand_kit, "short_name", ""),
            "primary_colour": getattr(brand_kit, "primary_colour", ""),
            "secondary_colour": getattr(brand_kit, "secondary_colour", ""),
            "accent_colour": getattr(brand_kit, "accent_colour", ""),
            "logo_svg": getattr(brand_kit, "logo_svg", ""),
        }

    # Stage G's theme_store integration mapped motion to MD3's
    # dark.primary / dark.secondary_container / dark.tertiary roles.
    # In practice those are tonal-palette tokens designed for UI
    # surfaces (buttons, containers), not full-bleed brand colour
    # ground/surface fills — they produced washed-out low-contrast
    # output in production (live verification 2026-05-19 showed
    # pink-on-pink renders for a #FFD86E/#A30D2D/#000000 BrandKit).
    # We now prefer the BrandKit's flat primary/secondary/accent
    # fields (the same ones the static renderer's brief.palette
    # carries) and only fall back to the theme store when the
    # BrandKit is incomplete. This keeps motion and static visually
    # aligned and restores the punch the brand was designed for.
    theme_palette: Optional[dict[str, str]] = None
    pid = src.get("profile_id") or src.get("profileId")
    if pid:
        try:
            from mediahub.theming.theme_store import read_theme, palette_for_motion

            theme_json = read_theme(pid)
            if theme_json:
                theme_palette = palette_for_motion(theme_json)
        except Exception as e:
            # Don't fail the render — fall through to the BrandKit
            # palette — but surface the cause in logs so a broken
            # theme_store integration is visible.
            import logging as _log

            _log.getLogger(__name__).warning(
                "motion: theme_store lookup failed for profile_id=%r: %s",
                pid,
                e,
            )
            theme_palette = None

    brand_primary = src.get("primary_colour") or src.get("primary")
    brand_secondary = src.get("secondary_colour") or src.get("secondary")
    brand_accent = src.get("accent_colour") or src.get("accent")

    tp = theme_palette or {}
    primary = brand_primary or tp.get("primary") or "#0A2540"
    secondary = brand_secondary or tp.get("secondary") or "#000000"
    accent = brand_accent or tp.get("accent") or "#FFFFFF"

    # Exact explainability: report which source actually contributed the
    # roles used. "brand-kit" only when the kit supplied every role that a
    # source supplied at all, "theme-store" when the store supplied them all,
    # else "mixed" (e.g. an accent-only kit filled from the store). Built-in
    # fallback constants don't count as a source; an all-default palette
    # keeps the historic "brand-kit" label.
    contributed = {
        ("brand-kit" if flat else "theme-store" if themed else "")
        for flat, themed in (
            (brand_primary, tp.get("primary")),
            (brand_secondary, tp.get("secondary")),
            (brand_accent, tp.get("accent")),
        )
    } - {""}
    if contributed == {"theme-store"}:
        theme_source = "theme-store"
    elif contributed <= {"brand-kit"}:
        theme_source = "brand-kit"
    else:
        theme_source = "mixed"

    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "displayName": src.get("display_name") or src.get("displayName") or "",
        "shortName": src.get("short_name") or src.get("shortName") or "",
        "logoDataUri": _logo_to_data_uri(
            src.get("logo_svg") or src.get("logoSvg") or src.get("logoDataUri")
        ),
        "themeSource": theme_source,
    }


_PHOTO_MAX_EDGE = 1280
_PHOTO_MAX_BYTES = 12_000_000  # refuse to embed originals beyond this raw size


def _effective_asset_path(asset: Any, store: Any) -> Path:
    """The path the MP4 should read for ``asset`` — the materialised edit
    (enhance / crop / safeguarding blur) when a recipe is stored, else the
    original (M21 / PHOTOS-3). This is the same
    ``photo_edit.effective_image_path`` the still pipeline reads, so a face a
    volunteer blurred on the approved still can never ship unblurred in the
    video. Never raises; falls back to the raw path on any miss.
    """
    raw = Path(getattr(asset, "path", "") or "")
    try:
        from mediahub.media_library import photo_edit

        eff = Path(photo_edit.effective_image_path(asset, store))
        if str(eff) and eff.exists():
            return eff
    except Exception:
        pass
    return raw


def _photo_asset_for_brief(brief: Optional[dict]):
    """Resolve the photo a brief sourced to ``(asset, effective_path)``.

    Mirrors the sourcing rules of the still renderer: skips "no-photo"
    treatments, the synthetic ``_brand_logo_`` id, missing files, and
    oversized originals. The path is the EDIT-EFFECTIVE one (M21). Never
    raises; ``(None, None)`` on any miss.
    """
    b = brief if isinstance(brief, dict) else {}
    if not b or str(b.get("photo_treatment") or "") == "no-photo":
        return None, None
    asset_ids = [str(a) for a in (b.get("sourced_asset_ids") or []) if a and a != "_brand_logo_"]
    if not asset_ids:
        return None, None
    try:
        from mediahub.media_library.store import get_store

        store = get_store()
    except Exception:
        return None, None
    for aid in asset_ids:
        try:
            asset = store.get(aid)
        except Exception:
            continue
        if asset is None:
            continue
        p = _effective_asset_path(asset, store)
        try:
            if p.exists() and p.stat().st_size <= _PHOTO_MAX_BYTES:
                return asset, p
        except OSError:
            continue
    return None, None


def _photo_asset_path_for_brief(brief: Optional[dict]) -> Optional[Path]:
    """The on-disk path of the photo a brief sourced (edit-effective), or
    ``None``. Thin wrapper over :func:`_photo_asset_for_brief`."""
    return _photo_asset_for_brief(brief)[1]


def _photo_edit_signature_for_brief(brief: Optional[dict]) -> str:
    """The sourced asset's edit-recipe signature, or ``""`` when the asset
    carries no edit (M21). Folded into the motion cache key ONLY when a
    recipe exists, so unedited assets keep byte-identical keys while an
    edited photo re-renders instead of serving the stale pre-edit MP4.
    """
    asset, _ = _photo_asset_for_brief(brief)
    if asset is None:
        return ""
    try:
        from mediahub.media_library import photo_edit

        recipe = photo_edit.recipe_for_asset(asset)
        return "" if recipe.is_noop() else recipe.signature()
    except Exception:
        return ""


def _photo_data_uri_for_path(p: Optional[Path]) -> str:
    """Downscale + inline one photo file as a JPEG data URI, or ``""``.

    Applies ``ImageOps.exif_transpose`` first (M21) so a phone-portrait
    photo that displays upright on the still doesn't play sideways in the
    video. Never raises — a missing photo must never fail a motion render.
    """
    if p is None:
        return ""
    try:
        import base64
        import io

        from PIL import Image, ImageOps

        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im.thumbnail((_PHOTO_MAX_EDGE, _PHOTO_MAX_EDGE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _photo_data_uri_for_brief(brief: Optional[dict]) -> str:
    """Resolve the photo a brief sourced into an embeddable JPEG data URI.

    Remotion's headless Chromium only sees what the props carry, so the
    user's chosen photo is downscaled and inlined. Empty string on any
    miss (no brief, "no-photo" treatment, asset gone, decode failure) —
    a missing photo must never fail a motion render.
    """
    return _photo_data_uri_for_path(_photo_asset_path_for_brief(brief))


def _archetype_is_symmetric(brief: Optional[dict]) -> bool:
    """True when the brief's v2 archetype is a centred composition (E2).

    Mirrors the still renderer so the smart-crop scorer keeps the disc/medal
    spotlight cards dead-centre on both surfaces.
    """
    try:
        from mediahub.graphic_renderer.archetypes import is_symmetric

        b = brief if isinstance(brief, dict) else {}
        return is_symmetric(str(b.get("layout_template") or ""))
    except Exception:
        return False


def _photo_focus_for_brief(brief: Optional[dict], format_name: str = DEFAULT_MOTION_FORMAT) -> str:
    """Saliency ``object-position`` for the brief's photo, steered per cut.

    Reuses the still renderer's deterministic saliency maths so a face the
    still keeps in frame stays in frame on the video too — now resolved for
    the requested output cut. The 9:16 story, 4:5 portrait, 1:1 square and
    16:9 landscape crops of the same photo slide along different axes, so a
    subject framed for the tall story can sit off-centre in the wide
    landscape; computing the focus per format keeps it centred in each.
    ``""`` when the brief sourced no photo (the TSX then uses its own
    neutral default). The ``story`` default resolves to the 9:16 ratio, so a
    default-cut render is byte-identical to the pre-format behaviour.

    E2: a ``smart`` crop intent (director-set or the ``MEDIAHUB_SMART_CROP``
    operator default) routes through the smartcrop scorer so the video's
    focal point matches the still's smart crop; every other intent keeps the
    plain saliency focus, byte-identical.
    """
    p = _photo_asset_path_for_brief(brief)
    if p is None:
        return ""
    try:
        from mediahub.graphic_renderer.saliency import (
            focus_position_for_format,
            smart_focus_for_format,
        )

        b = brief if isinstance(brief, dict) else {}
        from mediahub.graphic_renderer.render import (
            _existing_cutout_for,
            effective_crop_intent,
        )

        if effective_crop_intent(str(b.get("crop_intent") or "")) == "smart" and _is_v2_archetype(
            str(b.get("layout_template") or "")
        ):
            mask = _existing_cutout_for(p, profile_id=str(b.get("profile_id") or "default"))
            pos = smart_focus_for_format(
                p, format_name, symmetric=_archetype_is_symmetric(b), mask_path=mask
            ).get("--mh-photo-pos", "")
            if pos:
                return pos
        return focus_position_for_format(p, format_name)
    except Exception:
        return ""


# Alpha cutouts are PNGs (heavier than the JPEG background photo) so the long
# edge is capped a touch tighter to keep the inlined data URI reasonable.
_CUTOUT_MAX_EDGE = 1100


def _cutout_cache_dir() -> Path:
    d = _cache_dir() / "cutouts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cutout_for_brief(brief: Optional[dict]) -> tuple[str, Optional[Path]]:
    """Resolve the brief's sourced photo into ``(alpha-cutout data URI, cut
    path)`` — the R1.9 foreground plane, now matte-gated (parity pass).

    The motion render's foreground cutout layer (``sprint/layers/cutout.tsx``)
    and the layered-depth archetype scenes composite the athlete with their
    background removed. The cut is produced by the same configured background
    remover the still renderer uses (``media_ai.providers.get_bg_remover``) and
    measured by the same M14 matte gate (``graphic_renderer.matte.assess_matte``)
    — so when the still rejected the matte and fell back to the original
    photograph, the motion render falls back identically instead of shipping a
    shredded silhouette the customer never approved. A rejection is persisted
    as a ``.rejected.json`` marker beside the would-be cut, so a bad matte is
    measured once, not re-matted every render.

    The accepted cut is cached as a PNG under ``motion_cache/cutouts/`` keyed
    by the source photo's identity, so the (~300 ms+) remover runs at most once
    per photo, then is downscaled and inlined — Remotion's headless Chromium
    only sees what the props carry.

    Honest by construction: only a *real* remover is used (``is_available()``),
    never rembg's passthrough alpha — and the matte gate would reject a
    passthrough rectangle anyway. ``("", None)`` on any miss (no brief,
    ``no-photo`` treatment, asset gone, no usable remover, gate rejection,
    decode or synthesis failure) — a missing or failed cutout must never fail
    a motion render; the TSX layer simply no-ops.

    The returned ``cut_path`` (the full-resolution alpha PNG) feeds the
    band_break placement maths (``render._band_top_fraction``) so both surfaces
    break the band at identical pixels.
    """
    src = _photo_asset_path_for_brief(brief)
    if src is None:
        return "", None
    try:
        import io

        from PIL import Image, ImageOps

        # Cache the alpha cut keyed by the source's identity (path/mtime/size)
        # so repeat renders of the same photo skip the remover entirely.
        # (M21: `src` is already the edit-effective, content-addressed path,
        # so an edited photo re-cuts instead of reusing the pre-edit alpha.)
        st = src.stat()
        key = hashlib.sha256(
            f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")
        ).hexdigest()[:24]
        cut_path = _cutout_cache_dir() / f"{key}.png"
        reject_marker = cut_path.with_name(cut_path.name + ".rejected.json")
        if reject_marker.exists():
            # A previous render measured this photo's matte and rejected it —
            # the still shipped the original photograph, so motion does too.
            return "", None
        if not (cut_path.exists() and cut_path.stat().st_size > 1000):
            from mediahub.media_ai.providers import get_bg_remover

            remover = get_bg_remover()
            # Only composite a genuine cut — a provider that can't actually
            # remove the background would passthrough the whole rectangle.
            if remover is None or not remover.is_available():
                return "", None
            remover.remove(str(src), str(cut_path))
            if not (cut_path.exists() and cut_path.stat().st_size > 1000):
                return "", None
            # M14 matte-gate parity: measure the produced matte with the SAME
            # pure image-maths gate the still runs before accepting it. Same
            # file → same verdict, so still and motion can never disagree on
            # whether a cutout was shippable.
            verdict = None
            try:
                from mediahub.graphic_renderer.matte import assess_matte

                verdict = assess_matte(cut_path)
            except Exception:
                verdict = None  # the gate itself must never sink a render
            if verdict is not None and not verdict.ok:
                with contextlib.suppress(OSError):
                    cut_path.unlink()
                with contextlib.suppress(OSError):
                    reject_marker.write_text(
                        json.dumps({"reason": verdict.reason, "metrics": verdict.metrics}),
                        encoding="utf-8",
                    )
                return "", None
        if not (cut_path.exists() and cut_path.stat().st_size > 1000):
            return "", None
        with Image.open(cut_path) as im:
            # Belt-and-braces EXIF normalisation (M21): remover output should
            # already be upright, but a passthrough of legacy EXIF must never
            # rotate the cutout against its own background photo.
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGBA")
            im.thumbnail((_CUTOUT_MAX_EDGE, _CUTOUT_MAX_EDGE))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return uri, cut_path
    except Exception:
        return "", None


def _cutout_data_uri_for_brief(brief: Optional[dict]) -> str:
    """The brief's matte-gated alpha-cutout data URI, or ``""`` (see
    :func:`_cutout_for_brief`)."""
    return _cutout_for_brief(brief)[0]


# The still hook's opt-in tokens for the G1.8 gradient-mesh ground (mirrors
# sprint_hooks/gradient_mesh_bg._TRIGGERS; parsed before any ":mode" suffix).
_MESH_TRIGGERS = frozenset({"gradient_mesh", "gradient-mesh", "mesh"})

# render-banding-dither: the still's standalone opt-in token for the ordered-
# dither debanding overlay (mirrors sprint_hooks/dither_bg._TRIGGERS). A base
# token, deliberately SEPARATE from the mesh ":mode" suffix so the two never
# collide on background_style's single suffix slot.
_DITHER_TRIGGERS = frozenset({"dither"})


def _dither_for_brief(brief: Optional[dict]) -> bool:
    """Whether the still opted into the ordered-dither debanding overlay.

    Parity by construction: parses ``background_style`` exactly like the still
    render hook (``sprint_hooks.dither_bg``) — the standalone ``"dither"`` base
    token — so a card's video debands the same big fill the approved still did.
    False (the default and every miss) keeps the card props byte-identical.
    """
    b = brief if isinstance(brief, dict) else {}
    raw = str(b.get("background_style") or "").strip().lower()
    if not raw:
        return False
    return raw.partition(":")[0] in _DITHER_TRIGGERS


def _mesh_bg_for_brief(brief: Optional[dict], brand_kit: Any, format_name: str) -> str:
    """The still's G1.8 gradient-mesh ground for this card as a CSS
    ``background-image`` value — or ``""`` when the brief didn't opt in.

    Parity by construction: rather than porting the mesh maths to TSX, the
    exact Python engine the still hook runs (``graphic_renderer.gradient_mesh``)
    builds the SVG here, with the same roles / seed / mode / intensity
    derivation (``sprint_hooks.gradient_mesh_bg``), so the video ground carries
    the same deterministic brand-role mesh the approved still painted — painted
    beneath every content layer like the still's ground override. ``""`` (no
    mesh, or any failure → the flat brand ground, the pre-mesh behaviour) keeps
    the card props and every cache key byte-identical.
    """
    b = brief if isinstance(brief, dict) else {}
    raw = str(b.get("background_style") or "").strip().lower()
    if not raw:
        return ""
    base, _, mode_hint = raw.partition(":")
    if base not in _MESH_TRIGGERS:
        return ""
    try:
        from mediahub.creative_brief.generator import CreativeBrief
        from mediahub.graphic_renderer.gradient_mesh import (
            MESH_MODES,
            MeshRoles,
            mesh_data_uri,
            mesh_mode_for_seed,
        )
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief
        from mediahub.graphic_renderer.sprint_hooks.gradient_mesh_bg import (
            _intensity_for,
            _seed_for,
        )

        cb = CreativeBrief.from_dict(b)
        if cb is None:
            return ""
        roles = MeshRoles.from_role_vars(resolved_role_vars_for_brief(cb, brand_kit))
        seed = _seed_for(cb)
        width, height = motion_format_size(format_name)
        mode = mode_hint if mode_hint in MESH_MODES else mesh_mode_for_seed(seed)
        return mesh_data_uri(
            roles, width, height, mode=mode, seed=seed, intensity=_intensity_for(cb)
        )
    except Exception:
        return ""


def _resolved_root_vars(brief: Optional[dict], brand_kit: Any) -> dict[str, str]:
    """The raw ``--mh-*`` vars the card's STILL graphic paints, for motion.

    Rehydrates the persisted brief and runs the still renderer's single role
    resolver (Tier A brand baseline → the director's APCA-gated colour-role
    assignment → medal tint). Empty dict on any miss. This is the one shared
    resolution pass; :func:`_motion_roles_from_vars` maps it onto the motion
    prop names, and the M10/M11 parity props (duotone shadow, stat-chip ink)
    read their exact hexes from it.
    """
    if not isinstance(brief, dict) or not brief:
        return {}
    try:
        from mediahub.creative_brief.generator import CreativeBrief
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

        b = CreativeBrief.from_dict(brief)
        if b is None:
            return {}
        return {str(k): str(v) for k, v in resolved_role_vars_for_brief(b, brand_kit).items()}
    except Exception:
        return {}


def _motion_roles_from_vars(root_vars: dict[str, str]) -> dict[str, str]:
    """The resolved ``--mh-*`` vars mapped onto the motion prop names. Empty
    dict on any miss — the TSX then falls back to its seed-permutation roles,
    exactly the pre-parity behaviour."""
    if not root_vars:
        return {}
    out = {
        "roleGround": str(root_vars.get("--mh-primary") or ""),
        "roleSurface": str(root_vars.get("--mh-surface") or ""),
        "roleAccent": str(root_vars.get("--mh-accent") or ""),
        "roleOnGround": str(root_vars.get("--mh-on-primary") or ""),
    }
    # C1 (Canva gap analysis): the tonal container / raised / accent-container
    # tokens ride the SAME resolver into the motion props so a scene can paint
    # the still's exact container layering. Each is forwarded only when resolved
    # (an empty value never enters the map), so a brief without them contributes
    # nothing new — keeping the brief-less seed-permutation fallback intact.
    for src, dst in (
        ("--mh-surface-container", "roleSurfaceContainer"),
        ("--mh-surface-raised", "roleSurfaceRaised"),
        ("--mh-accent-container", "roleAccentContainer"),
        ("--mh-on-accent-container", "roleOnAccentContainer"),
    ):
        value = str(root_vars.get(src) or "")
        if value:
            out[dst] = value
    # F9 (Canva gap analysis) — medal chrome parity: forward the resolved
    # specular ramp so the motion medal scene paints the same gradient-clipped
    # numeral / bevelled chip. Present only on a gate-passing medal card, so a
    # non-medal card keeps byte-identical props.
    ramp = str(root_vars.get("--mh-medal-ramp") or "")
    if ramp:
        out["roleMedalRamp"] = ramp
    numeral_ramp = str(root_vars.get("--mh-medal-numeral-ramp") or "")
    if numeral_ramp:
        out["roleMedalNumeralRamp"] = numeral_ramp
    return out


def _archetype_photo_mode(brief: Optional[dict]) -> str:
    """``"photo"`` / ``"cutout"`` / ``""`` — how this card's archetype consumes
    the athlete photo (STILLS-2 / M8), resolved exactly as the still does.

    ``archetypes.photo_mode(layout_template)`` is the source of truth — it is
    what decides which scene actually renders, and the still's render path
    derives its mode from the template the same way, so a stale persisted
    stamp (e.g. a brief whose archetype was later regenerated) can never make
    motion composite a cutout the still doesn't show. The persisted
    ``brief.photo_mode`` stamp is the fallback for briefs whose template can't
    be resolved here. ``""`` for v1 families / brief-less callers — the legacy
    cutout-compositing behaviour, byte-identical props.
    """
    b = brief if isinstance(brief, dict) else {}
    arch = str(b.get("layout_template") or "")
    if arch:
        try:
            from mediahub.graphic_renderer import archetypes as _archetypes

            if arch in _archetypes.list_archetypes():
                return _archetypes.photo_mode(arch)
        except Exception:
            pass
    mode = str(b.get("photo_mode") or "").strip().lower()
    return mode if mode in ("photo", "cutout") else ""


def _is_v2_archetype(name: str) -> bool:
    """True when ``name`` is a Gen-v2 archetype (the M10/M11/M12 parity props
    only apply to v2 renders, mirroring the still's fill path)."""
    if not name:
        return False
    try:
        from mediahub.graphic_renderer import archetypes as _archetypes

        return name in _archetypes.list_archetypes()
    except Exception:
        return False


def _overlap_accent_for_brief(brief: Optional[dict]) -> str:
    """The still's seeded overlap accent as ``"shape:rotation"`` (F7), or ``""``.

    Mirrors ``render._v2_overlap_accent``: only a decorated card (a NON-BARE
    style pack) with a stable card key gets one, seeded independently of the pack
    (salt='overlap'). Attached only when non-empty, so a bare/legacy card keeps
    byte-identical props. The motion side paints the same shape + rotation in the
    pack layer.
    """
    if not isinstance(brief, dict):
        return ""
    pack_id = str(brief.get("style_pack") or "").strip()
    if not pack_id:
        return ""
    key = str(brief.get("variation_signature") or brief.get("id") or "").strip()
    if not key:
        return ""
    try:
        from mediahub.graphic_renderer import style_packs as _sp

        pack = _sp.style_pack_from_id(pack_id)
        if pack is None or pack.is_bare:
            return ""
        picked = _sp.overlap_accent_for(key)
        if not picked:
            return ""
        return f"{picked[0]}:{picked[1]}"
    except Exception:
        return ""


def _texture_blend_for_brief(brief: Optional[dict]) -> str:
    """The still's seeded texture composite blend mode (blend-modes), or ``""``.

    Mirrors ``render._v2_style_pack_overlay``: only a card that opted into
    ``seeded_blend`` AND resolved a NON-BARE style pack AND carries a stable card
    key + a biased mood yields a blend, computed by the SAME
    ``style_packs.texture_blend_for``. Attached only when non-empty, so every
    other card keeps byte-identical props (and story cache key).
    """
    if not isinstance(brief, dict):
        return ""
    if not brief.get("seeded_blend"):
        return ""
    pack_id = str(brief.get("style_pack") or "").strip()
    if not pack_id:
        return ""
    key = str(brief.get("variation_signature") or brief.get("id") or "").strip()
    if not key:
        return ""
    try:
        from mediahub.graphic_renderer import style_packs as _sp

        pack = _sp.style_pack_from_id(pack_id)
        if pack is None or pack.is_bare:
            return ""
        return _sp.texture_blend_for(str(brief.get("mood") or ""), key, enabled=True)
    except Exception:
        return ""


# The v2 archetypes whose motion scenes paint the cutout as layered depth
# planes themselves (M12 twins). They take the decoration-scaled depth
# treatment and (band_break) the alpha-derived band placement props.
_LAYERED_CUTOUT_ARCHETYPES = frozenset({"poster_name_behind", "band_break"})


def _decoration_strength_of(brief: Optional[dict]) -> float:
    """The brief's decoration strength with the still's exact fallback
    semantics (``float(... or 0.5)`` — see render.py's M10/M12 call sites)."""
    b = brief if isinstance(brief, dict) else {}
    try:
        return float(b.get("decoration_strength") or 0.5)
    except (TypeError, ValueError):
        return 0.5


def _resolved_treatment_strength_of(brief: Optional[dict]) -> float:
    """The 0..1 strength that sizes a photo grade — the motion mirror of
    ``render._resolved_treatment_strength``. ``photo_treatment_intensity`` (0..1)
    wins when set; otherwise it falls back to ``decoration_strength`` (clamped),
    so a card without the new token sizes every grade byte-identically."""
    b = brief if isinstance(brief, dict) else {}
    raw = b.get("photo_treatment_intensity", -1.0)
    try:
        intensity = float(raw)
    except (TypeError, ValueError):
        intensity = -1.0
    if intensity >= 0.0:
        return max(0.0, min(1.0, intensity))
    return max(0.0, min(1.0, _decoration_strength_of(b)))


def _roughen_seed_for_brief(brief: Optional[dict]) -> int:
    """The feTurbulence integer seed for a roughen-edges card, derived from the
    card's shared ``variation_signature`` (salt='roughen') — byte-for-byte the
    same derivation as ``render._roughen_seed_for``, so still and motion draw the
    identical silhouette perturbation."""
    b = brief if isinstance(brief, dict) else {}
    sig = str(b.get("variation_signature") or b.get("id") or "").strip()
    if not sig:
        return 0
    try:
        from mediahub.graphic_renderer.style_packs import _seed_for as _rk_seed

        return _rk_seed(sig, salt="roughen") % 100000
    except Exception:
        return 0


def _pack_ground_focus_prop(
    brief: Optional[dict], photo_pos: str, has_photo: bool
) -> Optional[list[int]]:
    """The style pack's vignette/spotlight ground focus ``[fx, fy]`` (E6), or None.

    Mirrors the still's ``render._pack_ground_focus``: only the two
    subject-framing grounds recentre, and only when the card carries a photo —
    so every other card (and photo-less vignette/spotlight cards) keeps a
    byte-identical prop dict and the fixed ground centre. The fractions come
    from the SAME saliency focus the photo uses (``photoPos``), parsed by the
    still's own ``_parse_focus_pos`` so the two surfaces agree.
    """
    if not has_photo:
        return None
    b = brief if isinstance(brief, dict) else {}
    ground = (str(b.get("style_pack") or "").strip().split("-") or [""])[0]
    if ground not in ("vignette", "spotlight"):
        return None
    try:
        from mediahub.graphic_renderer.render import _parse_focus_pos

        fr = _parse_focus_pos(photo_pos)
    except Exception:
        return None
    if fr is None:
        return None
    return [round(fr[0]), round(fr[1])]


def _photo_treatment_mirror_props(
    brief: Optional[dict],
    root_vars: dict[str, str],
    has_photo: bool,
    *,
    has_cutout: bool = False,
    format_name: str = DEFAULT_MOTION_FORMAT,
) -> dict[str, Any]:
    """The exact-mirror photo-grade props for a v2 card (M10 + B5/C5 parity).

    duotone → ``duotoneShadow``/``duotoneHighlight``: the two ink hexes the
    still's SVG filter ramps between, computed by the SAME maths
    (``render.darken(--mh-primary, 0.30)`` shadow, resolved ``--mh-accent``
    highlight — medal tints included) so the TSX filter's tableValues are
    byte-identical to the still's ``_duotone_defs_svg``.

    halftone → ``halftoneTile``: the mask tile px from ``decoration_strength``
    (``round(14 + 18·clamp(s, 0, 1))`` — ``render._v2_photo_treatment_assets``).

    sticker → ``stickerInk``/``stickerRadius`` (B5): the resolved on-ground ink
    and the die-cut contour radius ``round(min(w,h)·(0.003 + 0.004·strength))``
    (``render._sticker_outline_css``). Emitted ONLY when a real cutout exists —
    the still's ``cutout_ok`` gate — since a full-bleed rectangle would paint a
    box halo. ``format_name`` sizes the radius against this cut's geometry.

    wash → ``washTint``/``washMix`` (C5): the deep brand tint
    (``render.darken(--mh-primary, 0.20)``) and the arithmetic mix fraction
    ``0.18 + 0.24·strength`` the still's ``_wash_defs_svg`` composites, so the
    motion side rebuilds the identical brand colour-wash filter.

    Attached ONLY for a v2 archetype with a sourced photo and one of these
    treatments — every other card's props (and cache key) stay byte-identical.
    """
    b = brief if isinstance(brief, dict) else {}
    if not has_photo or not root_vars:
        return {}
    if not _is_v2_archetype(str(b.get("layout_template") or "")):
        return {}
    treatment = str(b.get("photo_treatment") or "").strip().lower()
    if treatment == "duotone":
        try:
            from mediahub.graphic_renderer.render import darken

            shadow = darken(root_vars.get("--mh-primary", "#0A2540"), 0.30)
        except Exception:
            return {}
        return {
            "duotoneShadow": shadow,
            "duotoneHighlight": root_vars.get("--mh-accent", "#FFFFFF"),
        }
    if treatment == "halftone":
        strength = _resolved_treatment_strength_of(b)
        return {"halftoneTile": int(round(14 + 18 * max(0.0, min(1.0, strength))))}
    if treatment == "sticker":
        ink = root_vars.get("--mh-on-primary")
        if not ink or not has_cutout:
            return {}
        s = _resolved_treatment_strength_of(b)
        width, height = motion_format_size(format_name)
        radius = max(3, int(round(min(width, height) * (0.003 + 0.004 * s))))
        return {"stickerInk": str(ink), "stickerRadius": radius}
    if treatment == "wash":
        try:
            from mediahub.graphic_renderer.render import darken

            tint = darken(root_vars.get("--mh-primary", "#0A2540"), 0.20)
        except Exception:
            return {}
        s = _resolved_treatment_strength_of(b)
        return {"washTint": tint, "washMix": round(0.18 + 0.24 * s, 4)}
    # stylize-richer — three pure-SVG stylize looks. Each derives its param(s)
    # from the SAME resolved strength the still uses, so the TSX rebuilds the
    # identical held filter; attached ONLY on its own branch, so every other
    # card keeps a byte-identical prop dict. ``treatmentIntensity`` rides the
    # props (informational parity + it folds the tuning into the content hash).
    if treatment == "mosaic":
        s = _resolved_treatment_strength_of(b)
        return {"mosaicBlock": max(1, int(round(1 + 4 * s))), "treatmentIntensity": round(s, 4)}
    if treatment == "motion_tile":
        s = _resolved_treatment_strength_of(b)
        return {"motionTileGrid": 2 + int(round(2 * s)), "treatmentIntensity": round(s, 4)}
    if treatment == "roughen_edges":
        s = _resolved_treatment_strength_of(b)
        return {
            "roughenSeed": _roughen_seed_for_brief(b),
            "roughenScale": max(1, int(round(2 + 10 * s))),
            "treatmentIntensity": round(s, 4),
        }
    return {}


# blur-family — the develop-in focus blur enriches from the single isotropic
# gaussian into a deterministic {directional, radial, lens} family, but ONLY on
# a legacy-animated graded photo card (a sourced photograph with a graded
# treatment that did NOT resolve an exact still-mirror). The four graded
# treatments photo_filters.baseStackFor animates; the exact-mirror v2 cards
# (duotone/halftone/wash) keep their held SVG grade with no stacked intro blur.
_FOCUS_BLUR_TREATMENTS = frozenset({"duotone", "halftone", "vignette", "wash"})
_FOCUS_BLUR_STYLES = ("directional", "radial", "lens")
# The same two mood families photo_filters.applyMoodNuance buckets on.
_FOCUS_BLUR_ENERGETIC = ("electric", "kinetic", "snappy", "bold", "triumph", "celebratory")
_FOCUS_BLUR_CALM = ("calm", "composed", "weighty", "contemplative", "melancholic")


def _focus_blur_style(seed: int, mood: str) -> str:
    """The develop-in focus-blur family for a legacy-animated graded photo card.

    A pure function of (variation_seed, mood): energetic moods get a directional
    whip streak, calm moods a lens bokeh, and a neutral mood lets the seed pick
    so a pack of neutral cards still varies. Never returns "gaussian" — that is
    the absence default photo_filters.tsx renders when the prop is not attached.
    The specific SVG smear (directional axis, radial orientation, lens lift) is
    a frame-pure sub-choice inside the TSX; this only names the family.
    """
    m = (mood or "").lower()
    if any(w in m for w in _FOCUS_BLUR_ENERGETIC):
        return "directional"
    if any(w in m for w in _FOCUS_BLUR_CALM):
        return "lens"
    s = abs(int(seed or 0))
    frac = (((s * 2654435761) % 1000) + 1000) % 1000 / 1000
    return _FOCUS_BLUR_STYLES[int(frac * len(_FOCUS_BLUR_STYLES)) % len(_FOCUS_BLUR_STYLES)]


def _stat_chips_for_brief(brief: Optional[dict]) -> list[dict[str, str]]:
    """The card's secondary-stat chips for motion (M11 parity), as
    ``[{"label": ..., "value": ...}, ...]``.

    Exactly the still's selection (``render._stat_chips_html``): only the
    data-led archetypes, only keys verified present in ``hero_stat_options``,
    the hero line's own fact skipped, values label-trimmed, capped at 4.
    ``[]`` for everything else — the prop is then never attached.
    """
    b = brief if isinstance(brief, dict) else {}
    try:
        from mediahub.graphic_renderer.render import (
            _STAT_CHIP_ARCHETYPES,
            _STAT_CHIP_LABELS,
            _chip_value,
        )
    except Exception:
        return []
    if str(b.get("layout_template") or "") not in _STAT_CHIP_ARCHETYPES:
        return []
    keys = [k for k in (b.get("secondary_stats") or []) if k]
    opts = b.get("hero_stat_options") if isinstance(b.get("hero_stat_options"), dict) else {}
    layers = b.get("text_layers") if isinstance(b.get("text_layers"), dict) else {}
    hero_line = layers.get("hero_stat") or ""
    hero_key = next((k for k, v in opts.items() if v == hero_line), None)
    chips: list[dict[str, str]] = []
    for key in keys:
        if key == hero_key or key not in opts:
            continue
        label = _STAT_CHIP_LABELS.get(key)
        if not label:
            continue
        chips.append({"label": label, "value": _chip_value(key, str(opts[key]))})
        if len(chips) >= 4:
            break
    return chips


def _pb_bars_for_brief(brief: Optional[dict]) -> Optional[dict]:
    """The honest proportional PB-bar payload for motion (M11 parity), or None.

    Exactly the still's gate (``render._pb_bars_html``): only the bar-bearing
    archetypes, only when both the previous PB and the new time parse as race
    times with the new one faster. ``nowPct`` is the mathematically
    proportional width on the honest zero-based axis; the caption prepends the
    delta only when it isn't already the hero line.
    """
    b = brief if isinstance(brief, dict) else {}
    try:
        from mediahub.graphic_renderer.render import (
            _PB_BARS_ARCHETYPES,
            _parse_time_seconds,
        )
    except Exception:
        return None
    if str(b.get("layout_template") or "") not in _PB_BARS_ARCHETYPES:
        return None
    layers = b.get("text_layers") if isinstance(b.get("text_layers"), dict) else {}
    prev_str = str(layers.get("prev_pb_time") or "").strip()
    new_str = str(layers.get("result_value") or "").strip()
    prev_s = _parse_time_seconds(prev_str)
    new_s = _parse_time_seconds(new_str)
    if prev_s is None or new_s is None or prev_s <= 0 or new_s >= prev_s:
        return None
    new_pct = max(1.0, min(100.0, new_s / prev_s * 100.0))
    opts = b.get("hero_stat_options") if isinstance(b.get("hero_stat_options"), dict) else {}
    drop = opts.get("pb_delta") or f"−{prev_s - new_s:.2f}s"
    caption = (
        "bars proportional to real times"
        if str(drop) == str(layers.get("hero_stat") or "")
        else f"{drop} · bars proportional to real times"
    )
    return {"prev": prev_str, "now": new_str, "nowPct": round(new_pct, 1), "caption": caption}


def _photo_frame_shape_mirror_props(brief: Optional[dict]) -> dict:
    """E4 parity — the shaped photo frame the still painted, as motion props.

    Returns ``{}`` for ``rect`` / the lever absent / an archetype the still
    doesn't shape, so those cards keep a byte-identical prop dict (and cache
    key). Otherwise forwards the shape token plus the EXACT geometry the still
    computed from the same seeded card key (``render._photo_frame_shape_card_key``
    + ``graphic_renderer.photo_frame``): the ``border-radius`` string for
    ``arch``/``blob``, or the three ``feTurbulence``/``feDisplacementMap``
    numbers for ``torn_edge`` — so the motion scene renders the identical
    silhouette the reviewer approved on the still.
    """
    b = brief if isinstance(brief, dict) else {}
    archetype = str(b.get("layout_template") or "")
    try:
        from mediahub.graphic_renderer import photo_frame as _pf
        from mediahub.graphic_renderer.render import (
            _WINDOWED_SHAPE_ARCHETYPES,
            _photo_frame_shape_card_key,
        )
    except Exception:
        return {}
    shape = str(b.get("photo_frame_shape") or "").strip().lower()
    if archetype not in _WINDOWED_SHAPE_ARCHETYPES or shape in ("", "rect"):
        return {}
    if shape not in _pf.PHOTO_FRAME_SHAPES:
        return {}

    class _B:  # a tiny attr view so the still's key helper reads the dict brief
        content_item_id = str(b.get("content_item_id") or "")
        id = str(b.get("id") or "")
        text_layers = b.get("text_layers") if isinstance(b.get("text_layers"), dict) else {}

    card_key = _photo_frame_shape_card_key(_B(), archetype)
    props: dict = {"frameShape": shape}
    if shape == "torn_edge":
        freq, scale, seed = _pf.torn_params(card_key)
        props["frameTornFreq"] = float(freq)
        props["frameTornScale"] = float(scale)
        props["frameTornSeed"] = int(seed)
    else:
        props["frameRadius"] = _pf.frame_radius(shape, card_key)
    return props


def _stat_ink_for_brief(brief: Optional[dict], root_vars: dict[str, str]) -> str:
    """The resolved hex of the ink var the still's chip row / PB bars use for
    this archetype (``--mh-on-surface`` or ``--mh-on-primary``), or ``""``."""
    b = brief if isinstance(brief, dict) else {}
    try:
        from mediahub.graphic_renderer.render import (
            _PB_BARS_ARCHETYPES,
            _STAT_CHIP_ARCHETYPES,
        )
    except Exception:
        return ""
    arch = str(b.get("layout_template") or "")
    ink_var = _STAT_CHIP_ARCHETYPES.get(arch) or _PB_BARS_ARCHETYPES.get(arch) or ""
    return str(root_vars.get(ink_var) or "") if ink_var else ""


def _photo_crop_scale_for_brief(brief: Optional[dict], format_name: str) -> float:
    """The still's ``--mh-photo-scale`` crop-intent zoom for this card (M10),
    or ``0.0`` when the intent emits none.

    Runs the still's own deterministic translation of the director's crop
    intent (``render._crop_intent_vars`` — saliency/alpha-bbox maths, never
    taste) against the sourced photo, using a previously-gated cutout as the
    subject mask exactly like the still's photo-mode path. ``tight_portrait``
    and the E2 ``smart`` scorer (director-set or the ``MEDIAHUB_SMART_CROP``
    operator default, resolved via ``effective_crop_intent``) emit a punch-in
    scale; every other card returns 0.0 so the prop is never attached and cache
    keys stay byte-identical.
    """
    b = brief if isinstance(brief, dict) else {}
    if not _is_v2_archetype(str(b.get("layout_template") or "")):
        return 0.0
    p = _photo_asset_path_for_brief(b)
    if p is None:
        return 0.0
    try:
        from mediahub.graphic_renderer.render import (
            _crop_intent_vars,
            _existing_cutout_for,
            effective_crop_intent,
        )

        intent = effective_crop_intent(str(b.get("crop_intent") or ""))
        if not intent:
            return 0.0
        width, height = motion_format_size(format_name)
        mask = _existing_cutout_for(p, profile_id=str(b.get("profile_id") or "default"))
        intent_vars = _crop_intent_vars(
            intent, p, mask, width, height, symmetric=_archetype_is_symmetric(b)
        )
        scale = intent_vars.get("--mh-photo-scale", "")
        return float(scale) if scale else 0.0
    except Exception:
        return 0.0


# The archetypes whose motion scenes lay out MULTIPLE athlete panels (the
# relay quartet, the duo split, the triptych progression). Only these earn the
# extra photoSrcs lookup — everything else keeps the single-photo path.
_MULTI_PHOTO_ARCHETYPES = frozenset({"relay_collage", "duo_athlete_split", "triptych_progression"})


def _profile_id_of(brand_kit: Any) -> str:
    """The brand kit's profile id, tolerant of dataclass / dict / None."""
    if brand_kit is None:
        return ""
    if isinstance(brand_kit, dict):
        return str(brand_kit.get("profile_id") or brand_kit.get("profileId") or "")
    return str(getattr(brand_kit, "profile_id", "") or "")


def _relay_athlete_names(card: Any, ach: Any) -> list[str]:
    """The individual athlete names a relay/multi-athlete card carries.

    Reads an explicit list field when the payload has one, else splits a
    combined ``swimmer_name`` ("A, B & C") into its parts. Only ever returns
    names the card itself supplied — never guesses a lineup. Empty when the
    card names no individuals (e.g. "{club} relay").
    """
    import re as _re

    for src in (ach, card):
        if not isinstance(src, dict):
            continue
        for key in ("relay_swimmers", "relay_members", "swimmer_names", "athlete_names", "members"):
            v = src.get(key)
            if isinstance(v, (list, tuple)):
                names = [str(x).strip() for x in v if str(x).strip()]
                if names:
                    return names
    combined = ""
    for src in (ach, card):
        if isinstance(src, dict):
            combined = str(src.get("swimmer_name") or src.get("athlete_name") or "")
            if combined:
                break
    parts = [p.strip() for p in _re.split(r",|&|/|\band\b", combined) if p.strip()]
    return parts if len(parts) >= 2 else []


def _photo_srcs_for_card(card: Any, brief: Optional[dict], brand_kit: Any) -> list[str]:
    """Extra athlete photos for a multi-panel archetype, as data URIs (M20).

    Only for the relay/duo/triptych archetypes, and only when the card names
    individual athletes: each linked athlete's best photo is resolved by the
    deterministic media-library selector (``select_assets`` — fixed weights,
    no LLM), materialised through the edit-effective path, downscaled and
    inlined exactly like ``photoSrc``. Capped at 4 (a relay quartet), skips
    the card's primary photo, and returns ``[]`` on any miss — an empty list
    keeps the card's props (and cache key) byte-identical.
    """
    b = brief if isinstance(brief, dict) else {}
    if str(b.get("layout_template") or "") not in _MULTI_PHOTO_ARCHETYPES:
        return []
    ach = card.get("achievement") if isinstance(card, dict) else None
    names = _relay_athlete_names(card, ach if isinstance(ach, dict) else {})
    if not names:
        return []
    try:
        from mediahub.media_library.selector import select_assets
        from mediahub.media_library.store import get_store

        store = get_store()
        assets = store.list(profile_id=_profile_id_of(brand_kit) or None, limit=500)
    except Exception:
        return []
    if not assets:
        return []
    out: list[str] = []
    # Never duplicate the card's primary photo in a panel.
    primary_asset, _ = _photo_asset_for_brief(b)
    used: set[str] = {str(getattr(primary_asset, "id", "") or "")}
    for name in names[:4]:
        try:
            picks = select_assets(
                assets,
                role="hero_athlete",
                athlete_name=name,
                preferred_orientation="portrait",
                k=3,
            )
        except Exception:
            continue
        for pick in picks:
            aid = str(pick.get("asset_id") or "")
            if not aid or aid in used:
                continue
            try:
                asset = store.get(aid)
            except Exception:
                continue
            if asset is None:
                continue
            p = _effective_asset_path(asset, store)
            try:
                if not (p.exists() and p.stat().st_size <= _PHOTO_MAX_BYTES):
                    continue
            except OSError:
                continue
            uri = _photo_data_uri_for_path(p)
            if uri:
                out.append(uri)
                used.add(aid)
                break
    return out


def _footage_for_card(
    card: Any,
    brief: Optional[dict],
    brand_kit: Any,
    *,
    beat_seconds: float,
    speed_ramp: str = "",
) -> tuple[Optional[Any], str]:
    """Resolve this card's footage beat (M23) — ``(resolution, reason)``.

    Thin motion-side wrapper over :func:`mediahub.visual.footage.
    resolve_card_footage`: it supplies the card's already-resolved still photo
    (the brief's sourced asset) so the deterministic priority rule can score
    photo vs footage without re-resolving. Never raises; ``(None, "")`` on a
    quiet miss, ``(None, reason)`` when a candidate lost or failed — the
    caller records the reason in the render manifest and the photo path
    renders untouched.

    ``speed_ramp`` (opt-in, default ``""``) requests a baked decelerate-into-
    the-beat ramp on the resolved clip; ``""`` keeps the clip byte-identical.
    """
    try:
        from mediahub.visual import footage as _footage

        photo_asset, _ = _photo_asset_for_brief(brief)
        return _footage.resolve_card_footage(
            card,
            brief,
            brand_kit,
            beat_seconds=beat_seconds,
            photo_asset=photo_asset,
            speed_ramp=speed_ramp or None,
        )
    except Exception:
        return None, ""


def _brief_speed_ramp(brief: Optional[dict]) -> str:
    """The story card's opt-in footage speed-ramp kind, or ``""`` (off).

    A server-only creative axis read straight from the brief (``speed_ramp``);
    it never rides into the Remotion props — the ramp is baked into the trimmed
    clip on the server. Absent / blank keeps the footage beat byte-identical.
    Only a kind :func:`footage.speed_ramp_plan` recognises has any effect (an
    unknown value degrades honestly to the native trim).
    """
    b = brief if isinstance(brief, dict) else {}
    return str(b.get("speed_ramp") or "").strip()


# Entrance-stagger scale (adjustable-stagger): a deterministic mood-derived
# multiplier on the token-compiled entrance intents' importance stagger. Calm /
# measured moods loosen the separation (>1), high-energy moods tighten it (<1).
# Substring matching mirrors the TSX mood gating (pop.ts subdued set + the
# StoryCard accent-amp regex), so compound moods still resolve. Only drop_in /
# rise / pop route through entranceChannels, so only they consume it.
_STAGGER_LOOSER = ("calm", "stoic", "precise", "minimal", "composed", "weighty")
_STAGGER_TIGHTER = ("electric", "explosive", "fierce", "celebratory", "triumph")
_STAGGER_INTENTS = frozenset({"drop_in", "rise", "pop"})


def _entrance_stagger_scale(mood: str, motion_intent: str) -> float:
    """A deterministic entrance-stagger multiplier, or ``1.0`` for a neutral mood
    or a non-entrance intent (``1.0`` → the prop is omitted → byte-identical)."""
    if motion_intent not in _STAGGER_INTENTS:
        return 1.0
    m = (mood or "").lower()
    if any(k in m for k in _STAGGER_LOOSER):
        return 1.3
    if any(k in m for k in _STAGGER_TIGHTER):
        return 0.65
    return 1.0


# text-fx-richer — the CLOSED set of opt-in entrance text animators. This is the
# SOLE trusted producer of the tokens the TSX ``textAnimator`` enum accepts:
# Python only ever emits one of these four members (or omits the prop), so no
# operator string reaches the animator switch — a closed enum + a single trusted
# producer, never an expression language (invariant #6/#7). Order is fixed so
# the deterministic seed bucket below is stable across runs.
_TEXT_ANIMATORS: tuple[str, ...] = (
    "blur_reveal",
    "track_in",
    "wiggle_settle",
    "word_rise_blur",
)

_TEXT_FX_TRUTHY = {"1", "true", "yes", "on"}


def _text_fx_enabled() -> bool:
    """Master switch for the richer text animators (``MEDIAHUB_TEXT_FX``).

    Default OFF: unset / malformed / a non-truthy value returns ``False`` so no
    card carries a ``textAnimator`` prop and every existing cache key and
    rendered byte is unchanged (byte-identical default). Mirrors
    ``_motion_supersample``'s honest env parse — no DSP guessing."""
    return os.environ.get("MEDIAHUB_TEXT_FX", "").strip().lower() in _TEXT_FX_TRUTHY


def _text_animator_for(props: dict, variation_seed: Any) -> str:
    """Pick the opt-in entrance animator for a card, or ``""``.

    Returns ``""`` (no animator) unless the master switch is ON **and** the card
    is a type-carried intent card (kinetic_type / cascade — the surface the
    KineticLine per-glyph reveal owns) **and** it is on the SAME glyph gate that
    yields per-glyph mode (``seed % 2 == 1``, mirroring the ``textGranularity``
    gate). Gating on the glyph condition guarantees ``perGlyph`` is true wherever
    an animator attaches, so a per-glyph animator is never painted onto a
    word-mode card. The preset is picked from a DIFFERENT seed bucket
    (``(seed // 2) % 4``) than the granularity gate, so the two gates are
    independent and sibling cards vary. A pure integer bucket over the sanctioned
    ``variation_seed`` — no model inference, deterministic-engine boundary
    respected."""
    if not _text_fx_enabled():
        return ""
    if props.get("motionIntent") not in ("kinetic_type", "cascade"):
        return ""
    seed = int(variation_seed or 0)
    if seed % 2 != 1:
        return ""
    return _TEXT_ANIMATORS[(seed // 2) % len(_TEXT_ANIMATORS)]


def _card_to_props(
    card: dict,
    *,
    variation_seed: int = 0,
    brief: Optional[dict] = None,
    brand_kit: Any = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
    footage: Optional[Any] = None,
) -> dict[str, Any]:
    """Coerce one content-pack card payload into the StoryCard props shape.

    Accepts either a flat dict ({"swimmer_name": ..., "event": ...}) or the
    nested {"achievement": {...}} variant emitted by the recognition layer.

    When ``brief`` is supplied (the AI-directed CreativeBrief for this
    card, as a dict via ``brief.to_dict()``), the variation axes the
    director picked — layout family, typography pair, composition,
    background style, accent style, mood, photo treatment, motion intent —
    are forwarded to Remotion. The TypeScript StoryCard composition uses
    those axes to vary fonts, layout, animation programme, background
    pattern, and accent decoration, so a Gemini-directed run produces
    visually distinct motion for every card instead of just rotating
    palette roles.

    When ``brand_kit`` is also supplied, the card's resolved colour roles
    (the exact APCA-gated set the still graphic painted, medal tint
    included) ride along as ``roleGround``/``roleSurface``/``roleAccent``/
    ``roleOnGround`` so the motion render and the approved still can never
    disagree on colour. Empty strings keep the seed-permutation fallback.

    ``format_name`` is the output cut (story / portrait / square / landscape);
    it steers the saliency ``photoPos`` so the photo's focal point is resolved
    for that frame's aspect ratio. The ``story`` default keeps ``photoPos``
    byte-identical to the pre-format behaviour.

    ``footage`` (M23) is a pre-resolved
    :class:`mediahub.visual.footage.FootageResolution` for this card's beat —
    resolved by the caller via :func:`_footage_for_card` so the render path
    owns the cache/manifest folds. When present, ``videoSrc`` /
    ``videoStartSec`` / ``videoDurationSec`` attach and the crop-intent
    ``photoScale`` is withheld (the video has real motion; the photo-derived
    zoom must not double-apply). ``None`` — the default and every miss — keeps
    the prop dict byte-identical to the photo-only behaviour.
    """
    ach = card.get("achievement") if isinstance(card, dict) else None
    if not isinstance(ach, dict):
        ach = card or {}
    layers = card.get("text_layers") if isinstance(card, dict) else None
    if not isinstance(layers, dict):
        layers = {}
    raw_facts = ach.get("raw_facts") if isinstance(ach, dict) else None
    if not isinstance(raw_facts, dict):
        raw_facts = {}

    athlete = (
        layers.get("athlete_full_name")
        or ach.get("swimmer_name")
        or ach.get("athlete_name")
        or card.get("swimmer_name")
        or card.get("athlete_name")
        or ""
    )
    first = layers.get("athlete_first_name") or (athlete.split()[0] if athlete else "")
    surname = layers.get("athlete_surname") or (athlete.split()[-1] if athlete else "")
    event = (
        layers.get("event_name")
        or ach.get("event_name")
        or ach.get("event")
        or card.get("event")
        or card.get("event_name")
        or ""
    )
    result = (
        layers.get("result_value")
        or ach.get("result_time")
        or ach.get("time")
        or raw_facts.get("time_str")
        or raw_facts.get("result")
        or card.get("result_time")
        or card.get("time")
        or ""
    )
    label = (
        layers.get("achievement_label")
        or ach.get("achievement_label")
        or ach.get("type")
        or card.get("confidence_label")
        or "STRONG SWIM"
    )
    meet_name = layers.get("meet_name") or card.get("meet_name") or ach.get("meet_name") or ""
    place = layers.get("place") or ach.get("place") or raw_facts.get("place") or ""

    # Pull variation axes from the brief (when supplied). Every field
    # is optional — empty strings tell the TSX composition to fall
    # back to its variationSeed-driven defaults.
    b = brief if isinstance(brief, dict) else {}
    # Gen v2 (SEQ-4): forward the still graphic's archetype + measured
    # emphasis line so the motion render of a card visually matches its
    # still. ``layout_template`` carries a v2 archetype name when the v2
    # engine produced the brief (a v1 family name otherwise — the TSX
    # treats unknown names as "no archetype treatment").
    brief_layers = b.get("text_layers") if isinstance(b.get("text_layers"), dict) else {}
    root_vars = _resolved_root_vars(b, brand_kit)
    roles = _motion_roles_from_vars(root_vars)
    photo_srcs = _photo_srcs_for_card(card, b, brand_kit)
    # G1.8 mesh-ground parity: attached ONLY when the brief opted in, so every
    # other card's props (and cache key) stay byte-identical.
    mesh_bg = _mesh_bg_for_brief(b, brand_kit, format_name)
    # STILLS-2 / M8 photo-mode parity: a "photo"-mode archetype shows the
    # ORIGINAL photograph on the still (the template's scrims handle
    # legibility) — its motion render must not composite a cutout plane the
    # approved still never had. Cutout resolution (and the remover cost) is
    # skipped entirely; "cutout"/legacy keeps the R1.9 behaviour untouched.
    arch_name = str(b.get("layout_template") or "")
    photo_mode = _archetype_photo_mode(b)
    photo_uri = _photo_data_uri_for_brief(b)
    if photo_mode == "photo":
        cutout_uri, cutout_path = "", None
    else:
        cutout_uri, cutout_path = _cutout_for_brief(b)
    props = {
        "athleteFullName": str(athlete),
        "athleteFirstName": str(first),
        "athleteSurname": str(surname),
        "eventName": str(event),
        "resultValue": str(result),
        "achievementLabel": str(label).upper(),
        "meetName": str(meet_name),
        "place": str(place),
        "variationSeed": int(variation_seed or 0),
        "backgroundStyle": str(b.get("background_style") or ""),
        "composition": str(b.get("composition") or ""),
        "typographyPair": str(b.get("typography_pair") or ""),
        "accentStyle": str(b.get("accent_style") or ""),
        "mood": str(b.get("mood") or ""),
        "photoTreatment": str(b.get("photo_treatment") or ""),
        "photoSrc": photo_uri,
        "photoPos": _photo_focus_for_brief(b, format_name),
        # R1.9: the athlete cut out to alpha, composited by the cutout sprint
        # layer (or a layered-depth archetype scene) as a foreground plane.
        # "" = no prepared cut (no photo, no usable remover, matte-gate
        # rejection, or a "photo"-mode archetype) and the consumers no-op.
        "cutoutSrc": cutout_uri,
        "archetype": str(b.get("layout_template") or ""),
        # The still's style pack id (graphic_renderer.style_packs): the motion
        # render layers the same ground/texture/accent-geometry overlay so a
        # card's video carries the still's exact decorative treatment. Folds
        # into the cache key via the card payload; "" = the bare (undecorated)
        # card, byte-equivalent to the pre-pack render.
        "stylePack": str(b.get("style_pack") or ""),
        "heroStat": str(brief_layers.get("hero_stat") or ""),
        # The director's motion language for this card (design_spec
        # MOTION_INTENTS). "" = the composition's mood/seed default.
        "motionIntent": str(b.get("motion_intent") or ""),
        # Resolved still-parity colour roles ("" = seed-permutation fallback).
        "roleGround": roles.get("roleGround", ""),
        "roleSurface": roles.get("roleSurface", ""),
        "roleAccent": roles.get("roleAccent", ""),
        "roleOnGround": roles.get("roleOnGround", ""),
    }
    # C1 (Canva gap analysis): the resolved tonal-container roles ride into the
    # props so a motion scene can mirror the still's container layering. Attached
    # only when the resolver emitted them (every real brief with a parseable
    # palette), so a brief-less card keeps a byte-identical prop dict.
    for _role_key in (
        "roleSurfaceContainer",
        "roleSurfaceRaised",
        "roleAccentContainer",
        "roleOnAccentContainer",
    ):
        if roles.get(_role_key):
            props[_role_key] = roles[_role_key]
    # M20: extra linked-athlete photos for the multi-panel archetypes, only
    # attached when at least one resolved — an empty list never touches the
    # prop dict, so single-photo cards keep byte-identical cache keys.
    if photo_srcs:
        props["photoSrcs"] = photo_srcs
    if mesh_bg:
        props["meshBg"] = mesh_bg
    # render-banding-dither: the ordered-dither debanding overlay, attached ONLY
    # when the still opted in (background_style="dither"), so every other card's
    # props (and cache key) stay byte-identical (fold-only-when-present). The TSX
    # <Dither> layer paints the same static Bayer tile the still hook injects, so
    # the video debands the same big fill the approved still did.
    if _dither_for_brief(b):
        props["dither"] = True
    # adjustable-stagger: retune the token-compiled entrance stagger by mood
    # (calm moods loosen the separation, high-energy tighten it). Attached only
    # when it differs from the default AND the intent is one of the entrance
    # intents that consume it, so neutral / non-entrance cards keep byte-identical
    # props (and story cache keys) — no composition-revision bump.
    _stagger_scale = _entrance_stagger_scale(props.get("mood", ""), props.get("motionIntent", ""))
    if _stagger_scale != 1.0:
        props["staggerScale"] = _stagger_scale
    # per-glyph text reveal: the two type-carried intents (kinetic_type /
    # cascade) can render their headline one CHARACTER at a time instead of one
    # word at a time. Selection is a deterministic engine decision (a seed gate),
    # never a director/LLM field — half the seeds of those two intents opt in, so
    # sibling cards vary. Attached ONLY when it fires (fold-only-when-present), so
    # every other card keeps a byte-identical prop dict / cache key; the TSX reads
    # "word" by default and renders the byte-identical per-word DOM.
    if (
        props.get("motionIntent") in ("kinetic_type", "cascade")
        and int(variation_seed or 0) % 2 == 1
    ):
        props["textGranularity"] = "glyph"
    # text-fx-richer: the opt-in closed-enum entrance animator. Attached ONLY
    # when the master switch (MEDIAHUB_TEXT_FX) is on AND the card is on the same
    # glyph gate above (so perGlyph is guaranteed true and a per-glyph animator
    # never lands on a word-mode card). Fold-only-when-present — with the switch
    # off (the default) every card keeps a byte-identical prop dict / cache key /
    # rendered byte, exactly like the textGranularity / overlapAccent attaches.
    _text_animator = _text_animator_for(props, variation_seed)
    if _text_animator:
        props["textAnimator"] = _text_animator
    # F9 medal chrome (still parity): the resolved specular ramp, attached only
    # on a gate-passing medal card so non-medal cards keep byte-identical props.
    medal_ramp = roles.get("roleMedalRamp", "")
    if medal_ramp:
        props["roleMedalRamp"] = medal_ramp
    medal_numeral_ramp = roles.get("roleMedalNumeralRamp", "")
    if medal_numeral_ramp:
        props["roleMedalNumeralRamp"] = medal_numeral_ramp
    # F7 overlap accent (still parity): the seeded badge/tab/rule/tape the still
    # straddles across an anchor. Attached only for a decorated card, so a
    # bare/legacy card keeps byte-identical props (and cache key).
    overlap_accent = _overlap_accent_for_brief(b)
    if overlap_accent:
        props["overlapAccent"] = overlap_accent
    # blend-modes (still parity): the seeded, mood-biased texture composite blend
    # the still painted. Attached only when the brief opted in AND a blend
    # resolved, so every other card keeps byte-identical props (and cache key) —
    # no composition-revision bump (fold-only-when-present).
    texture_blend = _texture_blend_for_brief(b)
    if texture_blend:
        props["textureBlend"] = texture_blend
    # LEFTOVER-1 (UI 1.18 → motion): a manual crop persisted in the card's
    # inspector overrides wins over the saliency focus — the same
    # ``photo_pos`` value the still honours, validated by the still's own
    # sanitiser so no unvetted CSS ever reaches the composition. The
    # ``photoPosManual`` marker keeps the per-cut saliency re-resolve
    # (``_apply_format_photo_focus``) from clobbering a human's crop. Only
    # overridden cards attach it, so untouched cards stay byte-identical.
    insp = card.get("inspector_overrides") if isinstance(card, dict) else None
    manual_pos = ""
    if isinstance(insp, dict) and insp.get("photo_pos"):
        try:
            from mediahub.graphic_renderer.render import _sanitise_photo_pos

            manual_pos = _sanitise_photo_pos(str(insp.get("photo_pos") or ""))
        except Exception:
            manual_pos = ""
    if manual_pos and photo_uri:
        props["photoPos"] = manual_pos
        props["photoPosManual"] = True
    # M23: the card's resolved footage beat — the club's real race clip under
    # the same scrim/treatment stack the photo path paints. Attached ONLY when
    # the caller resolved a clip, so photo-only cards keep byte-identical
    # props (and cache keys).
    if footage is not None:
        props["videoSrc"] = str(footage.video_src)
        props["videoStartSec"] = float(footage.video_start_sec)
        props["videoDurationSec"] = float(footage.video_duration_sec)
    # Parity pass — every prop below is attached ONLY when it resolved, so a
    # card it doesn't apply to keeps a byte-identical prop dict (and cache key).
    if photo_mode == "photo" and photo_uri:
        # Tells the TSX photo/cutout layers this archetype shows the ORIGINAL
        # photograph (belt-and-braces beside the empty cutoutSrc).
        props["photoMode"] = "photo"
    # M10 crop-intent mirror: the still's --mh-photo-scale zoom, multiplied
    # into the photo layer's cinematic push-in (transform-origin = photoPos).
    # Withheld for a footage beat: the crop zoom is derived from the
    # photograph's saliency and must not double-apply to real video motion.
    crop_scale = 0.0 if footage is not None else _photo_crop_scale_for_brief(b, format_name)
    if crop_scale > 1.0:
        props["photoScale"] = crop_scale
    # M10 true-brand duotone / real halftone + B5 sticker contour + C5 brand
    # colour-wash parameters (exact still mirror). ``has_cutout`` gates the
    # sticker contour (the still's cutout_ok gate); ``format_name`` sizes its
    # radius against this cut's geometry.
    props.update(
        _photo_treatment_mirror_props(
            b,
            root_vars,
            bool(photo_uri),
            has_cutout=bool(cutout_uri),
            format_name=format_name,
        )
    )
    # blur-family: enrich the develop-in focus blur into a deterministic
    # {directional, radial, lens} family for a legacy-animated graded photo
    # card — a sourced photograph with a graded treatment that did NOT resolve
    # an exact still-mirror (v2 duotone/halftone/wash keep their held SVG grade
    # with no stacked intro blur; a footage beat plays real video, no develop-in
    # grade). Fold-only-when-present: attached ONLY here, so every photo-less /
    # cutout / clean / exact-mirror / footage / default card keeps a
    # byte-identical prop dict (and cache key). The style is picked Python-side
    # (pure fn of variation_seed + mood) and rendered by photo_filters.tsx; it
    # resolves to 0 on the held frame, so still<->motion parity is preserved.
    _pt = str(b.get("photo_treatment") or "").strip().lower()
    _exact_mirror = any(
        k in props for k in ("duotoneShadow", "duotoneHighlight", "halftoneTile", "washTint")
    )
    if photo_uri and footage is None and _pt in _FOCUS_BLUR_TREATMENTS and not _exact_mirror:
        props["focusBlurStyle"] = _focus_blur_style(
            int(variation_seed or 0), str(b.get("mood") or "")
        )
    # D8 (Canva gap analysis): the still's density/mood-coherent supporting weight
    # register (kicker/meta/data), mirrored so the reel's labels/meta/data carry
    # the same weights the still painted. Attached ONLY when the still spent the
    # register (a bold pack or a non-neutral mood); a standard/neutral card omits
    # it and keeps byte-identical props + cache key.
    try:
        from mediahub.graphic_renderer.autofit import weight_register_for as _weight_register_for

        _density = ((str(b.get("style_pack") or "")).strip().split("-") or [""])[-1]
        _wr = _weight_register_for(_density, str(b.get("mood") or ""))
        if _wr:
            props["wghtKicker"] = int(_wr["kicker"])
            props["wghtMeta"] = int(_wr["meta"])
            props["wghtData"] = int(_wr["data"])
    except Exception:
        pass
    # E4 shaped photo frame (arch / blob / torn_edge) — the exact seeded geometry
    # the still painted, so the reel's window silhouette matches its still. {}
    # for rect / other archetypes → byte-identical props + cache key.
    props.update(_photo_frame_shape_mirror_props(b))
    # E6 (Canva gap analysis): recentre the pack's vignette/spotlight ground on
    # the subject. Attached ONLY when the pack ground is vignette/spotlight AND
    # the card carries a photo — every other card keeps a byte-identical prop
    # dict (and cache key), and photo-less vignette/spotlight cards keep the
    # fixed centre exactly like the still.
    ground_focus = _pack_ground_focus_prop(b, props.get("photoPos", ""), bool(photo_uri))
    if ground_focus is not None:
        props["packGroundFocus"] = ground_focus
    # M11 data weight: secondary-stat chips + honest proportional PB bars for
    # the data-led archetypes, with the exact ink hex the still's bay uses.
    stat_chips = _stat_chips_for_brief(b)
    if stat_chips:
        props["statChips"] = stat_chips
    pb_bars = _pb_bars_for_brief(b)
    if pb_bars:
        props["pbBars"] = pb_bars
    if stat_chips or pb_bars:
        stat_ink = _stat_ink_for_brief(b, root_vars)
        if stat_ink:
            props["statInk"] = stat_ink
        if root_vars.get("--mh-outline"):
            # The still's hairline outline (a translucent on-colour) for the
            # chip boxes — passed, never re-derived, so no literal colour
            # lives in the TSX (brand-locked rule).
            props["roleOutline"] = str(root_vars["--mh-outline"])
    # M12 layered-depth twins: decoration strength for the role-coloured depth
    # filter (0.5 is the TSX default, so only a non-default value attaches),
    # poster_name_behind's surface-band ink, and band_break's alpha-derived
    # band placement — the SAME maths the still ran, so both surfaces break
    # at identical pixels.
    if arch_name in _LAYERED_CUTOUT_ARCHETYPES and cutout_uri:
        strength = _decoration_strength_of(b)
        if abs(strength - 0.5) > 1e-9:
            props["decorationStrength"] = round(strength, 4)
        if arch_name == "poster_name_behind" and root_vars.get("--mh-on-surface"):
            props["roleOnSurface"] = str(root_vars["--mh-on-surface"])
        if arch_name == "band_break" and root_vars.get("--mh-outline"):
            # The band's 2px border-bottom paints the still's outline var.
            props["roleOutline"] = str(root_vars["--mh-outline"])
        if arch_name == "band_break" and cutout_path is not None:
            try:
                from mediahub.graphic_renderer.render import _band_top_fraction

                width, height = motion_format_size(format_name)
                band_top = _band_top_fraction(cutout_path, width, height)
            except Exception:
                band_top = None
            if band_top is not None:
                props["bandTopPct"] = round(band_top * 100, 1)
                solid = max(0.0, min(0.97, (band_top + 0.015 - 0.14) / 0.86))
                fade = min(0.99, solid + 0.055)
                props["breakSolidPct"] = round(solid * 100, 1)
                props["breakFadePct"] = round(fade * 100, 1)
    return props


_RENDERER_GENERATION: Optional[str] = None


def renderer_generation() -> str:
    """A short content fingerprint of the Remotion renderer sources (deep-review
    #74). The per-composition revisions (STORY/REEL_COMPOSITION_REVISION) must be
    bumped BY HAND when a composition changes; a change to SHARED renderer code
    (``render.js``, ``Root.tsx``, shared components, ``fonts.ts``) or a Remotion
    version bump that nobody remembered to bump the revision for would otherwise
    keep serving a stale cached MP4. Folding this fingerprint into every cache key
    invalidates the cache automatically on ANY renderer-source change.

    Content-hashed (not mtime) so it is STABLE across redeploys of unchanged
    source — the persistent motion cache survives a redeploy that didn't touch the
    renderer. Memoised (computed once per process). Falls back to a fixed token if
    the sources can't be read, so a render never fails on fingerprinting.
    """
    global _RENDERER_GENERATION
    if _RENDERER_GENERATION is not None:
        return _RENDERER_GENERATION
    h = hashlib.sha256()
    try:
        files = [RENDER_SCRIPT, REMOTION_DIR / "package.json"]
        src_dir = REMOTION_DIR / "src"
        if src_dir.is_dir():
            files += sorted(
                p
                for p in src_dir.rglob("*")
                if p.is_file() and p.suffix in (".tsx", ".ts", ".js", ".css")
            )
        for p in files:
            try:
                h.update(p.relative_to(REMOTION_DIR).as_posix().encode("utf-8"))
                h.update(b"\0")
                h.update(p.read_bytes())
            except OSError:
                continue
        _RENDERER_GENERATION = h.hexdigest()[:12]
    except Exception:
        _RENDERER_GENERATION = "r0"
    return _RENDERER_GENERATION


def _content_hash(payload: dict, *, kind: str) -> str:
    """Stable hash for the cache key. Serialises with sort_keys so call-site
    ordering doesn't bust the cache. The renderer-source fingerprint (#74) is
    folded in here so it applies uniformly to every key — a renderer change busts
    the whole motion cache without any per-call-site edit."""
    blob = json.dumps(
        {"kind": kind, "_rgen": renderer_generation(), **payload},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _write_render_manifest(cached: Path, manifest: dict) -> None:
    """Persist the explainability record for one motion render.

    A small JSON sidecar next to the cached MP4 answering "why does this
    video look like this?" — archetype, motion intent, where the colours
    came from, the seed, format, and durations. Best-effort: a manifest
    failure must never fail (or follow) a successful render.
    """
    try:
        sidecar = cached.with_suffix(".json")
        sidecar.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def _publish_sidecar(cached: Path, out_path: Path) -> None:
    """Ship the explainability manifest with the MP4 it explains. Cache hits
    carry the sidecar from the original render; best-effort like the write."""
    try:
        src = cached.with_suffix(".json")
        dst = out_path.with_suffix(".json")
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
    except Exception:
        pass


def _card_manifest_axes(card_props: dict) -> dict:
    """The per-card explainability axes worth recording (no photo bytes)."""
    return {
        "archetype": card_props.get("archetype") or "",
        "style_pack": card_props.get("stylePack") or "",
        "overlap_accent": card_props.get("overlapAccent") or "",
        "texture_blend": card_props.get("textureBlend") or "",
        "motion_intent": card_props.get("motionIntent") or "",
        "text_granularity": card_props.get("textGranularity") or "word",
        "text_animator": card_props.get("textAnimator") or "",
        "accent_style": card_props.get("accentStyle") or "",
        "photo_treatment": card_props.get("photoTreatment") or "",
        "focus_blur_style": card_props.get("focusBlurStyle") or "gaussian",
        "background_style": card_props.get("backgroundStyle") or "",
        "mood": card_props.get("mood") or "",
        "variation_seed": card_props.get("variationSeed") or 0,
        "colour_source": "still-parity-roles"
        if card_props.get("roleGround")
        else "seed-permutation",
        "has_photo": bool(card_props.get("photoSrc")),
        "has_cutout": bool(card_props.get("cutoutSrc")),
        "has_footage": bool(card_props.get("videoSrc")),
        "photo_mode": card_props.get("photoMode") or "",
        "photo_focus": card_props.get("photoPos") or "",
        "frame_shape": card_props.get("frameShape") or "",
        "hero_stat": card_props.get("heroStat") or "",
        "stat_chips": len(card_props.get("statChips") or []),
        "has_pb_bars": bool(card_props.get("pbBars")),
        # per-effect-toggle: the decorative axes this render suppressed for an
        # A/B comparison. Empty on every shipped card (the review-only path is
        # the only writer), so a default manifest is unchanged in meaning.
        "effects_disabled": list(card_props.get("effectsDisabled") or []),
    }


# ---------------------------------------------------------------------------
# Audio + poster finishing (engine-agnostic; see visual/audio_mux.py)
# ---------------------------------------------------------------------------


def _card_mix_profile(card: Any, brief: Optional[dict] = None) -> Optional[str]:
    """The per-card audio-mix profile a card (or its brief) names, else None.

    Read straight from the payload — the mix balance (voice_lead / balanced /
    music_forward) is a deterministic production knob, not a creative AI
    judgement, so it is never inferred by a model. ``audio_mux`` validates the
    string; ``None`` lets the operator env default
    (``MEDIAHUB_REEL_MIX_PROFILE``) and then ``balanced`` decide. A card field
    wins over the brief's.
    """
    for src in (card, brief):
        if isinstance(src, dict):
            val = src.get("audio_mix_profile") or src.get("audioMixProfile")
            if val:
                return str(val)
    return None


# per-effect-toggle (REVIEW-ONLY A/B): the fixed allowlist of DECORATIVE axes a
# reviewer may suppress for a with/without comparison render. Deliberately
# excludes every legibility- / accessibility-critical layer — photo scrims and
# filters, and burn-in captions stay ALWAYS-ON — so no toggle can drop a text/bg
# pair below its APCA gate or remove a required scrim. Sorted, immutable.
EFFECT_TOGGLE_ALLOWLIST: tuple[str, ...] = (
    "accent",
    "background_pattern",
    "cutout",
    "mesh_bg",
    "motion_intent",
    "overlap_accent",
    "sprint_layers",
    "style_pack",
    "text_fx",
)


def _validate_effect_toggles(keys: Any) -> list[str]:
    """Filter an arbitrary iterable of effect keys to the sorted allowlist.

    Unknown keys are dropped; duplicates collapse. The result is a stable,
    sorted list so the same request always keys the same cache entry (and the
    order can never perturb the content hash). A non-iterable / empty input
    yields ``[]``. This is a deterministic production knob — no model inference —
    so it never crosses the deterministic-engine boundary.
    """
    if not keys or isinstance(keys, (str, bytes)):
        return []
    allowed = set(EFFECT_TOGGLE_ALLOWLIST)
    out = {str(k) for k in keys if str(k) in allowed}
    return sorted(out)


def _effect_toggles_for_brief(brief: Optional[dict]) -> list[str]:
    """The sorted decorative axes a brief asks to SUPPRESS, or ``[]``.

    Reads ``brief["effect_toggles"]`` — a plain ``{effect_key: bool}`` dict — and
    returns the allowlisted keys explicitly set falsey (validated + sorted via
    :func:`_validate_effect_toggles`). Keys set truthy, unknown keys, and an
    absent field all yield no suppression. Read straight from the payload (like
    ``_card_mix_profile``), never model-inferred.

    NOTE: this is consumed ONLY by the review-only A/B render path — it is never
    folded into a shipped card's props, so the still a shipped card mirrors stays
    in still<->motion parity. Toggling an effect changes the *comparison* render,
    not the card that gets exported for posting.
    """
    b = brief if isinstance(brief, dict) else {}
    toggles = b.get("effect_toggles")
    if not isinstance(toggles, dict):
        return []
    disabled = [k for k, v in toggles.items() if not v]
    return _validate_effect_toggles(disabled)


def _library_bed_for(content_key: str):
    """A bundled-library music bed for a render, or None (roadmap 1.8).

    Only when the operator opted in (``MEDIAHUB_REEL_MUSIC_LIBRARY``) *and* has
    supplied no licensed music directory of their own — their music always wins.
    The pick is the deterministic content-hash one (``AudioLibrary.pick``), not
    the AI selector: it must be cheap and stable because it feeds the cache key
    on every render (including cache hits). The AI mood-match is an explicit
    web-surface suggestion, not baked into the hot path. Best-effort: any failure
    returns None and the render stays on its prior (silent / operator-bed) path.
    """
    try:
        from mediahub.visual import audio_mux

        if not audio_mux.library_bed_enabled() or audio_mux.music_candidates():
            return None
        from mediahub.audio import load_library

        return load_library().pick(content_key, kind="music", commercial_only=True)
    except Exception:
        return None


def _story_audio_plan(card_props: dict, brand_dict: dict, *, mix_profile: Optional[str] = None):
    """The audio plan for one story render, or None for today's silent path.

    Built from the same props the composition displays (zero invention; see
    visual/narration.py). None when no audio source is configured — which
    also keeps the cache payload, and therefore every existing cache key,
    byte-identical to the pre-audio behaviour. The story line is one
    sentence; the mux's trim-to-video-length is the overrun guarantee.

    ``mix_profile`` is the per-card voice/music balance; it only changes the
    cache key when it is not the default ``balanced`` (see audio_mux).
    """
    try:
        from mediahub.visual import audio_mux, narration

        if not audio_mux.audio_active():
            return None
        script = ""
        if audio_mux.voice_active():
            script = narration.story_script(card_props, brand_dict)
        key = "story:{}:{}:{}".format(
            card_props.get("athleteFullName") or "",
            card_props.get("eventName") or "",
            card_props.get("resultValue") or "",
        )
        return audio_mux.build_audio_plan(
            script=script,
            content_key=key,
            mix_profile=mix_profile,
            library_track=_library_bed_for(key),
        )
    except Exception:
        return None


def _reel_audio_plan(
    cards_props: list[dict],
    brand_dict: dict,
    meet_name: str,
    *,
    duration_sec: float,
    mix_profile: Optional[str] = None,
    dub_language: str = "",
):
    """The audio plan for a reel render, or None for today's silent path.

    ``mix_profile`` is the reel's voice/music balance (the headline card's
    choice; see render_meet_reel) and only shifts the cache key off the
    default when it is not ``balanced``.

    ``dub_language`` (1.24): when set, the reel's verified narration is
    translated and re-voiced into that language (AI-dub), keeping the music bed.
    If the dub can't be done honestly (no provider, or no voice for the
    language) the narration is dropped rather than shipping the source language
    pretending to be the target — the music bed (if any) is kept, else the reel
    is silent. The dubbed plan folds into the cache key, so each language is a
    distinct render.

    Returns ``(plan, dub_error)`` — ``dub_error`` is the honest reason the dub
    was dropped (``""`` when it wasn't). It rides *alongside* the plan, never
    inside it, so it reaches the manifest without shifting any cache key.
    """
    try:
        from mediahub.visual import audio_mux, narration

        if not audio_mux.audio_active():
            return None, ""
        script = ""
        if audio_mux.voice_active():
            script = narration.reel_script(
                cards_props, brand_dict, meet_name, max_seconds=duration_sec
            )
        first = cards_props[0] if cards_props else {}
        key = "reel:{}:{}:{}".format(
            meet_name or "", len(cards_props), first.get("athleteFullName") or ""
        )
        plan = audio_mux.build_audio_plan(
            script=script,
            content_key=key,
            mix_profile=mix_profile,
            library_track=_library_bed_for(key),
        )
        dub_error = ""
        if plan and dub_language:
            from mediahub.visual import dub as _dub

            try:
                plan = _dub.dub_plan(plan, dub_language)
            except (_dub.DubUnavailable, _dub.ClaudeUnavailableError) as e:
                # Honest: couldn't dub → drop the narration (never ship the
                # source language as if it were the target), keep any music bed
                # — and record why for the manifest.
                dub_error = f"dub to {dub_language!r} dropped: {e}"
                plan = {k: v for k, v in plan.items() if k not in ("voice", "script")} or None
        return plan, dub_error
    except Exception:
        return None, ""


# ---------------------------------------------------------------------------
# Subtitle / caption burn-in (R1.3; see visual/subtitle_burn.py)
# ---------------------------------------------------------------------------

# The Remotion compositions and the FFmpeg engine both run at 30fps; the caption
# engine needs the cadence to turn millisecond SRT cues into frame windows.
MOTION_FPS = 30

# Curated, selectable output frame rates (fps-option). 30 stays the default and
# the byte-identical baseline; a non-default choice folds "fps" into the content
# cache key and appends --fps to the node command (fold-only-when-active), and
# compile.ts rescales its preset frame counts by fps/30 so entrances keep their
# wall-clock timing. The set is deliberately small — the film/broadcast/social
# rates the renderer is validated for.
ALLOWED_FPS = frozenset({24, 25, 30, 50, 60})


def _validate_fps(fps: int) -> int:
    """Return ``fps`` if it is one of :data:`ALLOWED_FPS`, else raise ``ValueError``.

    Rejects anything outside the curated set (``0``, ``48``, ``None``, floats,
    booleans) up front so a bad request fails loudly before any expensive
    photo-embed / render work rather than emitting an off-spec MP4.
    """
    if isinstance(fps, bool) or not isinstance(fps, int) or fps not in ALLOWED_FPS:
        raise ValueError(f"unsupported fps {fps!r}; choose one of {sorted(ALLOWED_FPS)}")
    return fps


def _fps_kw(fps: int) -> dict:
    """The ``fps=`` keyword to forward, empty at the default.

    Only non-default renders carry the kwarg downstream, so the default call
    signature — and every existing render mock / call assertion — is unchanged
    and the default render stays byte-identical.
    """
    return {"fps": int(fps)} if int(fps) != MOTION_FPS else {}


def _encode_kw(encode: Optional[dict]) -> dict:
    """The ``encode=`` keyword to forward, empty at the default (encode is None).

    bit-depth-gamut: only an active profile carries the kwarg downstream, so the
    default call signature — and every existing render mock / call assertion —
    is unchanged and the default render stays byte-identical (``_run_remotion``
    itself defaults ``encode=None``, so an absent kwarg == the OFF path)."""
    return {"encode": encode} if encode is not None else {}


_TRUTHY = {"1", "true", "yes", "on"}


def _subtitles_enabled() -> bool:
    """True when the operator opted into burned captions (``MEDIAHUB_SUBTITLES``).

    Captions paint the spoken narration on screen for muted autoplay, so they
    ride on top of the existing voiceover opt-in: a render only burns captions
    when a voice-narration plan exists for it too (the story path literally
    reads that voiceover's SRT).
    """
    return os.environ.get("MEDIAHUB_SUBTITLES", "").strip().lower() in _TRUTHY


def _caption_roles(card_dict: dict, brand_dict: dict) -> tuple[str, str, str]:
    """``(ground, onground, accent)`` for the caption colour, brand-filled.

    Prefers the card's resolved still-parity roles (already APCA-gated) and
    falls back to the brand palette so the caption is always legible on its
    own ground.
    """
    ground = str(card_dict.get("roleGround") or brand_dict.get("primary") or "")
    onground = str(card_dict.get("roleOnGround") or "")
    accent = str(card_dict.get("roleAccent") or brand_dict.get("accent") or "")
    return ground, onground, accent


def _story_caption_json(
    card_dict: dict, brand_dict: dict, audio_plan, *, duration_sec: float, fps: int = MOTION_FPS
) -> str:
    """The caption track for a story render as a JSON string, or ``""``.

    Reads the story narration's voiceover SRT (built from the same fact-only
    script the audio speaks). Returns ``""`` whenever captions are off or no
    voice plan exists, so the silent-path cache key stays byte-identical.
    """
    if not _subtitles_enabled() or not audio_plan:
        return ""
    script = str(audio_plan.get("script") or "").strip()
    voice = str(audio_plan.get("voice") or "")
    if not script or not voice:
        return ""
    try:
        from mediahub.visual import subtitle_burn

        ground, onground, accent = _caption_roles(card_dict, brand_dict)
        track = subtitle_burn.story_caption_track(
            script,
            voice=voice,
            duration_sec=duration_sec,
            fps=fps,
            ground=ground,
            onground=onground,
            accent=accent,
        )
        return subtitle_burn.track_json(track)
    except Exception:
        return ""


def _reel_caption_json(
    card_dict: dict, brand_dict: dict, *, beat_frames: int, fps: int = MOTION_FPS
) -> str:
    """Per-beat caption track for a reel card as a JSON string, or ``""``.

    The reel narrates one continuous script, so each beat is captioned from its
    own verified line (``narration.story_script`` with no club sign-off),
    distributed across the beat — no extra synthesis, fully deterministic.
    """
    try:
        from mediahub.visual import narration, subtitle_burn

        line = narration.story_script(card_dict, {})
        if not line.strip():
            return ""
        ground, onground, accent = _caption_roles(card_dict, brand_dict)
        track = subtitle_burn.text_caption_track(
            line,
            total_frames=beat_frames,
            fps=fps,
            ground=ground,
            onground=onground,
            accent=accent,
        )
        return subtitle_burn.track_json(track)
    except Exception:
        return ""


def _caption_manifest(caption_json: str) -> dict:
    """Explainability record for a story render's captions."""
    if not caption_json:
        return {"status": "off"}
    try:
        cues = len(json.loads(caption_json).get("cues", []))
    except Exception:
        cues = 0
    return {"status": "on", "cues": cues}


def _reel_caption_manifest(cards_props: list[dict]) -> dict:
    """Explainability record for a reel render's per-beat captions."""
    counts = [_caption_manifest(cp.get("captionsJson") or "").get("cues", 0) for cp in cards_props]
    return {"status": "on" if any(counts) else "off", "cues_per_card": counts}


def _audio_record_path(cached: Path) -> Path:
    """Sidecar recording whether the planned audio was attached to this MP4.

    A container probe can't answer that — Remotion's encoder emits a silent
    AAC track on every render, so "has an audio stream" does not mean "has
    the narration/music we planned". The record is written by the finishing
    pass itself and is the only thing trusted on a cache hit.
    """
    return Path(cached).with_suffix(".audio.json")


def _ensure_poster_sidecar(cached: Path, *, kind: str, duration_sec: float) -> str:
    """Guarantee a poster-frame PNG beside ``cached``; report where it came from.

    R1.29: the poster is normally captured *in-render* by ``remotion/render.js``
    — a Remotion ``renderStill`` that waits on the fonts ``delayRender`` hook, so
    the thumbnail is a frame-exact, real-font PNG straight from Chromium (no
    H.264 round-trip, no keyframe-seek approximation). When that sidecar is
    present and non-empty we keep it and **skip the post-hoc ffmpeg frame grab
    entirely** — the R1.29 win. We fall back to the ffmpeg extraction only when
    the in-render poster is absent or empty: the free ffmpeg reel engine (which
    never runs ``render.js``), a ``render.js`` poster-capture failure, or a video
    cached before R1.29 being re-finished on a cache hit.

    Returns the provenance for the explainability manifest — ``"in-render"`` /
    ``"ffmpeg"`` / ``""`` (no poster could be written). Never raises.
    """
    from mediahub.visual import audio_mux

    poster = audio_mux.poster_path_for(cached)
    try:
        if poster.exists() and poster.stat().st_size > 0:
            return "in-render"
    except OSError:
        pass
    ok = audio_mux.write_poster(
        cached, poster, at_sec=audio_mux.poster_time_for(kind, duration_sec)
    )
    return "ffmpeg" if ok else ""


def _finish_cached_video(
    cached: Path,
    *,
    kind: str,
    plan,
    duration_sec: float,
    n_cards: int = 0,
    rhythm: Optional[dict] = None,
    audio_notes: Optional[dict] = None,
) -> dict:
    """Idempotent finishing pass on the cached MP4: attach the planned audio
    (honest silent fallback on failure; retried on the next request) and
    ensure the poster-frame sidecar exists. Returns the manifest-ready
    audio record, carrying the poster's provenance under ``poster_source``
    (``"in-render"`` / ``"ffmpeg"`` / ``""``) for the render manifest.

    ``n_cards`` (reels only) yields the card-cut beat grid the music accents
    align to; stories have no internal cuts and leave it at 0. ``rhythm``
    (reels only, R1.12) moves that grid with the customised carve so accents
    land on the reel's real cuts. ``audio_notes`` are extra manifest-ready
    facts about the plan (e.g. a dropped dub's honest reason) merged into the
    record — never into the cache-keyed plan itself.

    R1.29: the poster is normally captured *in-render* by ``render.js`` (a
    Remotion ``renderStill`` that honours the fonts ``delayRender`` hook), so the
    common path skips the ffmpeg/ffprobe extraction entirely — see
    :func:`_ensure_poster_sidecar`, which falls back to the ffmpeg frame grab
    only when that in-render poster is absent or empty.
    """
    try:
        from mediahub.visual import audio_mux

        cut_times = (
            audio_mux.card_cut_times(duration_sec, n_cards, rhythm) if kind == "reel" else None
        )
        if plan:
            record_path = _audio_record_path(cached)
            audio_rec: dict = {}
            if record_path.exists():
                try:
                    prior = json.loads(record_path.read_text(encoding="utf-8"))
                    if isinstance(prior, dict) and prior.get("status") == "mixed":
                        audio_rec = prior
                except (OSError, ValueError):
                    audio_rec = {}
            if not audio_rec:
                audio_rec = audio_mux.apply_audio(
                    cached, plan, duration_sec=duration_sec, cut_times=cut_times
                )
                if audio_notes:
                    audio_rec = {**audio_rec, **audio_notes}
                try:
                    record_path.write_text(
                        json.dumps(audio_rec, indent=2, sort_keys=True, default=str),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        else:
            audio_rec = {"status": "off"}
            if audio_notes:
                audio_rec = {**audio_rec, **audio_notes}
        poster_source = _ensure_poster_sidecar(cached, kind=kind, duration_sec=duration_sec)
        return {**audio_rec, "poster_source": poster_source}
    except Exception as e:
        return {"status": "silent_fallback", "reason": str(e), "poster_source": ""}


def _publish(cached: Path, out_path: Path) -> Path:
    """Copy the cached MP4 — plus its explainability manifest and poster
    sidecars, when present — to the caller-requested path. No-op when they
    are the same file."""
    from mediahub.visual.audio_mux import poster_path_for

    cached = Path(cached)
    out_path = Path(out_path)
    if cached.resolve() == out_path.resolve():
        return cached
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, out_path)
    _publish_sidecar(cached, out_path)
    cached_poster = poster_path_for(cached)
    if cached_poster.exists():
        try:
            shutil.copyfile(cached_poster, poster_path_for(out_path))
        except OSError:
            pass
    return out_path


def _update_manifest_audio(cached: Path, audio_rec: dict) -> None:
    """Refresh the manifest's audio record after a late audio attach (a
    cache hit whose earlier audio attempt fell back to silent). Best-effort."""
    try:
        sidecar = Path(cached).with_suffix(".json")
        if not sidecar.exists():
            return
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if manifest.get("audio") == audio_rec:
            return
        manifest["audio"] = audio_rec
        sidecar.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def _motion_supersample() -> float:
    """Supersample factor for motion renders (``MEDIAHUB_MOTION_SUPERSAMPLE``),
    clamped to ``[1.0, 2.0]``. ``1.0`` (unset / malformed / default) renders at
    the native target resolution — byte-identical to today. A value > 1 renders
    at scale× and Lanczos-downscales back to the target for crisper text / vector
    / gradient edges, at extra render cost (mirrors the stills' DPR supersample)."""
    raw = os.environ.get("MEDIAHUB_MOTION_SUPERSAMPLE", "").strip()
    if not raw:
        return 1.0
    try:
        v = float(raw)
    except ValueError:
        return 1.0
    return max(1.0, min(2.0, v))


# true-motion-blur — the opt-in shutter-accumulation axis. OFF by default:
# without ``MEDIAHUB_MOTION_BLUR`` opted in, ``_motion_blur()`` returns ``None``
# so no ``motionBlur`` prop is folded into the card/reel props and every cache
# key + rendered byte is byte-identical to today. When ON, the composition wraps
# ONLY the settling moving layers (the story hero/result entrance + count-up, the
# reel whip flick) in a frame-pure multi-sample sampler: it recomputes the
# closed-form animated quantity at ``samples`` deterministic sub-frame offsets
# across the shutter window and composites the copies with equal-weight
# progressive alpha. The sub-frame set is a pure function of the integer frame,
# so identical env ⇒ identical render (no Math.random/Date.now anywhere). The
# perpetual camera/parallax channels are deliberately NOT sampled, so the
# terminal/held frame collapses to the single at-rest frame and still↔motion
# parity is preserved. A closed env parse + fixed clamp — no DSP/LLM guessing, so
# the deterministic-engine boundary is respected.
MOTION_BLUR_DEFAULT_SAMPLES = 8
MOTION_BLUR_SAMPLES_RANGE = (2, 16)
MOTION_BLUR_DEFAULT_SHUTTER = 180.0
MOTION_BLUR_SHUTTER_RANGE = (1.0, 360.0)


def _motion_blur() -> Optional[dict]:
    """Resolve the opt-in motion-blur config, or ``None`` when OFF.

    Returns ``None`` unless ``MEDIAHUB_MOTION_BLUR`` is truthy (the byte-identical
    default). When ON, reads the optional ``MEDIAHUB_MOTION_BLUR_SAMPLES`` (clamped
    to ``[2, 16]``) and ``MEDIAHUB_MOTION_BLUR_SHUTTER`` (shutter angle in degrees,
    clamped to ``[1.0, 360.0]``) and returns a canonical
    ``{"samples": <int>, "shutter": <float>}`` dict. Malformed values fall back to
    the defaults (never raises) so the render stays deterministic. Mirrors
    ``_motion_supersample``'s honest env parse — no DSP guessing."""
    if os.environ.get("MEDIAHUB_MOTION_BLUR", "").strip().lower() not in _TRUTHY:
        return None
    lo_s, hi_s = MOTION_BLUR_SAMPLES_RANGE
    samples = MOTION_BLUR_DEFAULT_SAMPLES
    raw_s = os.environ.get("MEDIAHUB_MOTION_BLUR_SAMPLES", "").strip()
    if raw_s:
        try:
            samples = int(round(float(raw_s)))
        except ValueError:
            samples = MOTION_BLUR_DEFAULT_SAMPLES
    samples = max(lo_s, min(hi_s, samples))
    lo_a, hi_a = MOTION_BLUR_SHUTTER_RANGE
    shutter = MOTION_BLUR_DEFAULT_SHUTTER
    raw_a = os.environ.get("MEDIAHUB_MOTION_BLUR_SHUTTER", "").strip()
    if raw_a:
        try:
            shutter = float(raw_a)
        except ValueError:
            shutter = MOTION_BLUR_DEFAULT_SHUTTER
    shutter = max(lo_a, min(hi_a, shutter))
    return {"samples": samples, "shutter": shutter}


# bit-depth-gamut — the opt-in higher-bit-depth / wide-gamut ENCODE vocabulary.
# Each entry is a FIXED, verified (codec, pixelFormat, colorSpace, container)
# quad — a closed table, never an expression language: no operator-supplied
# codec/pixelFormat string ever reaches renderMedia, only these names select a
# profile. All shipped profiles are MP4-container so the six ``video/mp4``
# serving routes need no change; the ``container`` field exists so a future
# ``.mov``/ProRes profile can slot in once those routes learn ``video/quicktime``.
#
# Honesty (invariant 5): Chromium composites 8-bit sRGB frames. These profiles
# RE-ENCODE those same brand-locked, APCA-gated colours at higher bit-depth
# precision (less encode banding) and TAG the container's gamut/transfer
# metadata. They do NOT synthesise wide-gamut colour that was never rendered.
# ``h265-10`` (genuine 10-bit precision, no colour tag) and ``h265-10-bt709``
# (10-bit + honest rec709 tag) are the SAFE recommended defaults. ``bt2020-ncl``
# is offered but FLAGGED: ffmpeg tags the file HLG/2020 and applies a limited-
# range matrix relabel over sRGB-origin pixels — it is NOT a true gamut map, and
# a tonemapping player that honours the tag can display it differently from the
# approved 8-bit sRGB still. The manifest states this verbatim.
MOTION_ENCODE_PROFILES: dict[str, dict] = {
    "h265-10": {
        "name": "h265-10",
        "codec": "h265",
        "pixelFormat": "yuv420p10le",
        "colorSpace": None,
        "container": ".mp4",
    },
    "h265-10-bt709": {
        "name": "h265-10-bt709",
        "codec": "h265",
        "pixelFormat": "yuv420p10le",
        "colorSpace": "bt709",
        "container": ".mp4",
    },
    "h265-10-bt2020": {
        "name": "h265-10-bt2020",
        "codec": "h265",
        "pixelFormat": "yuv420p10le",
        "colorSpace": "bt2020-ncl",
        "container": ".mp4",
    },
    "h265-8-bt709": {
        "name": "h265-8-bt709",
        "codec": "h265",
        "pixelFormat": "yuv420p",
        "colorSpace": "bt709",
        "container": ".mp4",
    },
}


def _motion_encode_profile() -> Optional[dict]:
    """The opt-in higher-bit-depth / wide-gamut ENCODE profile, or None (default).

    ``MEDIAHUB_MOTION_ENCODE`` selects a named profile from the closed
    :data:`MOTION_ENCODE_PROFILES` vocabulary. Unset / empty / ``"default"`` /
    ``"h264"`` / any unknown name → ``None``, which keeps the render
    byte-identical to today (8-bit ``yuv420p``, no colour tag, ``.mp4``).
    Returns a *copy* so callers cannot mutate the shared table.

    Deterministic-engine boundary respected: a pure dict + env lookup, no DSP,
    no model, no operator-supplied codec strings. Unknown names resolve to
    ``None`` (never a raise, never an arbitrary codec) — a typo silently keeps
    the safe byte-identical default rather than emitting an off-spec file, and
    can never smuggle a codec string through to ``renderMedia`` (invariant 7)."""
    raw = os.environ.get("MEDIAHUB_MOTION_ENCODE", "").strip().lower()
    if not raw or raw in ("default", "h264"):
        return None
    prof = MOTION_ENCODE_PROFILES.get(raw)
    return dict(prof) if prof is not None else None


# alpha-export — the opt-in transparent-background compositing vocabulary
# (Remotion-only). Each entry is a FIXED, internally-consistent
# ``(codec, pixel_format, prores_profile, ext, content_type)`` tuple from a
# CLOSED table — no operator-supplied codec/pixelFormat string ever reaches
# renderMedia, only these names select a profile (invariant 7). The two targets
# are both fully supported by the pinned Remotion 4.0.493 + its bundled
# compositor ffmpeg, and each triple is kept valid so Remotion's own
# pixel-format<->codec / proResProfile<->codec validators never throw:
#   - prores4444: ProRes 4444 (codec=prores, pixelFormat=yuva444p10le,
#     proResProfile=4444, .mov, video/quicktime) — the AE-parity target.
#   - vp9:        VP9 (codec=vp9, pixelFormat=yuva420p, NO proResProfile,
#     .webm, video/webm) — a web-friendly transparent video.
# Honesty (invariant 5): alpha only REMOVES the outer full-bleed ground paint
# (via the composition's false-default ``transparentBg`` prop) and re-encodes
# the SAME brand-locked, APCA-gated colours into an alpha container — it never
# synthesises colour. Scene-internal full-bleed fills and full-bleed athlete
# photos stay opaque (recorded honestly in the manifest). PNG-sequence export is
# out of scope (renderMedia cannot emit image sequences — that is renderFrames,
# a different output/packaging path).
class _AlphaProfile(NamedTuple):
    key: str
    codec: str
    pixel_format: str
    prores_profile: str  # "" when not applicable (vp9)
    ext: str  # container extension WITHOUT the dot ("mov" / "webm")
    content_type: str


ALPHA_PROFILES: dict[str, _AlphaProfile] = {
    "prores4444": _AlphaProfile(
        "prores4444", "prores", "yuva444p10le", "4444", "mov", "video/quicktime"
    ),
    "vp9": _AlphaProfile("vp9", "vp9", "yuva420p", "", "webm", "video/webm"),
}


class AlphaUnsupportedError(RuntimeError):
    """Raised when a transparent-background (alpha) export is requested on an
    engine that cannot produce one — currently the free FFmpeg fallback, which
    composites opaque 8-bit stills. Erroring is a DELIBERATE deviation from that
    engine's usual degrade-and-ship pattern: shipping a mislabeled OPAQUE file
    under a ``.mov``/``.webm`` transparent-export name would be an active lie,
    worse than an honest error (invariant 5). The web routes map this to a 503."""


def resolve_alpha_profile(name: str) -> Optional[_AlphaProfile]:
    """Resolve a transparent-export profile NAME to its ``_AlphaProfile``, or None.

    ``""`` / whitespace / any unknown name → ``None`` (alpha OFF — byte-identical
    default). A closed lower/strip dict lookup: no expression language, no eval,
    no operator-supplied codec strings (invariant 7)."""
    key = (name or "").strip().lower()
    return ALPHA_PROFILES.get(key)


def _alpha_encode(prof: _AlphaProfile) -> dict:
    """Express an ``_AlphaProfile`` as the ``encode`` dict ``_run_remotion`` and the
    cache-slot/manifest seams already understand (built by bit-depth-gamut).

    The dict reuses the bit-depth ``encode`` threading verbatim — ``codec`` /
    ``pixelFormat`` / ``container`` — with ``colorSpace=None`` (no gamut tag) and a
    ``proResProfile`` key added ONLY for a profile that carries one (dropped for
    vp9, so Remotion's "proResProfile with a non-prores codec throws" trap is
    avoided). ``alpha`` marks it as a transparent export so the manifest branch
    picks the alpha note rather than the bit-depth note."""
    d = {
        "name": prof.key,
        "codec": prof.codec,
        "pixelFormat": prof.pixel_format,
        "colorSpace": None,
        "container": f".{prof.ext}",
        "alpha": True,
    }
    if prof.prores_profile:
        d["proResProfile"] = prof.prores_profile
    return d


def _alpha_manifest(prof: _AlphaProfile) -> dict:
    """The manifest ``alpha`` block for a transparent export — states the real
    scope boundary and the deliberate deviations honestly (invariant 5)."""
    return {
        "profile": prof.key,
        "codec": prof.codec,
        "pixel_format": prof.pixel_format,
        **({"prores_profile": prof.prores_profile} if prof.prores_profile else {}),
        "container": prof.ext,
        "note": (
            "Transparent-background compositing export (Remotion-only). Only the "
            "OUTERMOST per-scene full-bleed ground fill (+ full-bleed meshBg) is "
            "suppressed; scene-internal full-bleed fills and full-bleed athlete "
            "photos stay OPAQUE. Silent by design — a compositing asset carries no "
            "audio (the aac-in-mp4/mov mux is not validated for 10-bit prores / "
            "vp9-webm). The poster is the in-render transparent PNG "
            "(renderStill imageFormat:png); the ffmpeg frame-grab fallback is "
            "intentionally unavailable for alpha containers. The operator owns the "
            "downstream backdrop, so the text-on-ground APCA pair no longer "
            "describes the final composited contrast — colour choice is unchanged; "
            "the ground paint is removed, not recoloured. PNG-sequence export is "
            "out of scope (renderMedia cannot emit image sequences)."
        ),
    }


def _photo_supersample() -> int:
    """Per-photo resample-quality knob (``MEDIAHUB_PHOTO_SUPERSAMPLE``), returned
    as ``0`` (off / default) or ``2`` (capped).

    This is the honest, opt-in analogue of the FFmpeg engine's fixed 2x Lanczos
    prescale for the Remotion transform-scaled athlete photos. It is deliberately
    NOT the whole-composition supersample (that is ``_motion_supersample`` /
    ``MEDIAHUB_MOTION_SUPERSAMPLE``, which renderMedia-scales the entire frame and
    Lanczos-downscales — the guaranteed dense-buffer path). When set, it folds a
    ``photoSupersample`` card prop that pins ``imageRendering:'auto'`` on those
    ``<img>`` elements so the compositor uses high-quality interpolation; the
    manifest records it as a best-effort hint, never a claimed supersample.

    Capped at ``2`` for cross-engine parity: the FFmpeg fallback's prescale is a
    fixed 2x, so a higher factor could never be honoured there. ``0`` (unset /
    malformed / ``<= 1``) means off — byte-identical to today (fold-only-when-
    active)."""
    raw = os.environ.get("MEDIAHUB_PHOTO_SUPERSAMPLE", "").strip()
    if not raw:
        return 0
    try:
        v = int(float(raw))
    except ValueError:
        return 0
    return 2 if v >= 2 else 0


def _run_remotion(
    *,
    composition_id: str,
    props: dict,
    out_path: Path,
    duration_sec: Optional[float] = None,
    size: Optional[tuple[int, int]] = None,
    timeout: int = 600,
    supersample: float = 1.0,
    fps: int = MOTION_FPS,
    encode: Optional[dict] = None,
) -> Path:
    """Invoke the Node render script. Raises RuntimeError on failure."""
    if not node_available():
        raise RuntimeError(
            "Node is not installed; install Node 18+ to render motion graphics. "
            "See CLAUDE.md → 'Remotion / motion graphics setup'."
        )
    if not RENDER_SCRIPT.exists():
        raise RuntimeError(f"Remotion render script missing at {RENDER_SCRIPT}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Render into a unique per-process/thread temp file in the same directory,
    # then atomically os.replace it into out_path (deep-review #73). render.js
    # writes its MP4 incrementally, so pointing it straight at the shared cache
    # slot let two concurrent same-key renders — or a reader on the cache-hit path
    # (`cached.exists() and size > 1024`) — observe a torn, half-written file. The
    # atomic same-filesystem rename means out_path only ever flips from absent to
    # a complete MP4 (or from one complete MP4 to another). (The opt-in
    # parallel-segment reel composite and the ffmpeg fallback engine write the
    # slot through their own ffmpeg invocations; they are separate follow-ups.)
    # bit-depth-gamut: the temp file carries the profile's container so a future
    # non-.mp4 profile writes the right suffix; every shipped profile is .mp4, so
    # the default (encode is None) suffix stays byte-identically ".tmp.mp4".
    tmp_suffix = (encode["container"] if encode is not None else ".mp4").lstrip(".")
    tmp_out = out_path.with_name(
        f".{out_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp.{tmp_suffix}"
    )

    # Write props to a temp file alongside the cache; cheap and lets us tail
    # the JSON if a render fails.
    props_dir = _cache_dir() / "props"
    props_dir.mkdir(parents=True, exist_ok=True)
    props_path = props_dir / f"{out_path.stem}.json"
    props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")

    cmd = [
        "node",
        str(RENDER_SCRIPT),
        "--composition",
        composition_id,
        "--props",
        str(props_path),
        "--output",
        str(tmp_out),
    ]
    if duration_sec is not None:
        cmd.extend(["--duration", str(duration_sec)])
    if size is not None:
        cmd.extend(["--width", str(int(size[0])), "--height", str(int(size[1]))])
    if supersample > 1.0:
        cmd.extend(["--scale", f"{supersample:g}"])
    # fps-option: append --fps only for a non-default rate, so the default node
    # command (and its cache-busting hash) stays byte-identical to before.
    if int(fps) != MOTION_FPS:
        cmd.extend(["--fps", str(int(fps))])
    # bit-depth-gamut: append the encode flags ONLY when a profile is active, so
    # the OFF path (encode is None) issues the identical argv as before —
    # render.js then falls back to its h264 / yuv420p / no-colorSpace defaults.
    # --color-space is appended only when the profile carries one (h265-10 has
    # None → no colour tag, matching Remotion's 'default' no-args behaviour).
    if encode is not None:
        cmd.extend(["--codec", encode["codec"], "--pixel-format", encode["pixelFormat"]])
        if encode.get("colorSpace"):
            cmd.extend(["--color-space", encode["colorSpace"]])
        # alpha-export: ProRes 4444 needs its proResProfile; it is present ONLY
        # for the prores profile (dropped for vp9), so Remotion never sees a
        # proResProfile paired with a non-prores codec.
        if encode.get("proResProfile"):
            cmd.extend(["--prores-profile", encode["proResProfile"]])

    from mediahub.visual.proc import run_capture

    try:
        # run_capture launches node in its own process group and kills the WHOLE
        # group on timeout, so Remotion's Chromium children don't leak (a plain
        # subprocess.run would SIGKILL only node and reparent Chromium to init).
        proc = run_capture(cmd, cwd=str(REMOTION_DIR), timeout=timeout)
    except subprocess.TimeoutExpired as e:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"Remotion render timed out after {timeout}s") from e

    if proc.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-15:]) if stderr else "(no stderr)"
        # Keep props_path on failure — it's the render's input, useful to reproduce.
        raise RuntimeError(f"Remotion render failed (exit {proc.returncode}):\n{tail}")
    if not tmp_out.exists() or tmp_out.stat().st_size < 1024:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"Remotion reported success but {out_path} is missing or empty")
    # Supersample finish: the node render emitted an n× MP4; Lanczos-downscale it
    # back to the exact target WxH (same h264/yuv420p deliverable) so only edge
    # fidelity improves — a deterministic ffmpeg pass, the same class the audio
    # mux and poster grabs already rely on.
    # alpha-export / bit-depth-gamut belt-and-braces: an active encode profile
    # (10-bit / alpha) is incompatible with this libx264/yuv420p downscale, which
    # would flatten the higher bit-depth or destroy the alpha channel. Callers
    # already force supersample=1.0 whenever encode is set, so this block is
    # unreachable on those paths; the ``encode is None`` guard makes that explicit.
    if supersample > 1.0 and size is not None and encode is None:
        from mediahub.visual.reel_ffmpeg import ffmpeg_exe

        exe = ffmpeg_exe()
        if not exe:
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError("supersample downscale needs an FFmpeg binary")
        down = out_path.with_name(f".{out_path.stem}.{os.getpid()}.{threading.get_ident()}.ss.mp4")
        ds = subprocess.run(
            [
                exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(tmp_out),
                "-vf",
                f"scale={int(size[0])}:{int(size[1])}:flags=lanczos",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(down),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        tmp_out.unlink(missing_ok=True)
        if ds.returncode != 0 or not down.exists() or down.stat().st_size < 1024:
            down.unlink(missing_ok=True)
            raise RuntimeError(f"supersample downscale failed (exit {ds.returncode})")
        tmp_out = down
    # Atomic publish: the completed MP4 flips into the cache slot in one rename,
    # so a concurrent same-key render or cache-hit reader never sees a torn file.
    os.replace(tmp_out, out_path)
    # Success: drop the props sidecar so it doesn't accumulate one-per-MP4 forever
    # (it was never pruned). Failed renders keep theirs for debugging (above).
    props_path.unlink(missing_ok=True)
    return out_path


# ---------------------------------------------------------------------------
# Engine dispatch
# ---------------------------------------------------------------------------


def _dispatch_engine() -> str:
    """Resolve and validate the configured engine; return its name.

    Called at the entry of each public render function.  When the engine
    resolves to 'remotion' (the default) the existing _run_remotion path
    continues completely unchanged.  'ffmpeg' routes to the free fallback
    in :mod:`mediahub.visual.reel_ffmpeg` (roadmap P0.1).
    """
    return select_reel_engine()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_story_card(
    card_payload: dict,
    brand_kit: Any,
    out_path: Path,
    *,
    variation_seed: int = 0,
    duration_sec: float = 6.0,
    brief: Optional[dict] = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
    fps: int = MOTION_FPS,
    review_ab: Optional[list[str]] = None,
    alpha_profile: str = "",
) -> Path:
    """Render a single content-pack card to an MP4 story.

    Returns the path to the rendered MP4. Cached by content hash so
    repeated calls with the same card + brand + seed + brief + format
    reuse the existing file.

    Pass ``brief`` (as ``CreativeBrief.to_dict()``) to forward the
    Gemini-directed variation axes (layout/typography/background/
    accent/mood/motion intent) to the TSX composition. Without a brief
    the render falls back to variationSeed-only behaviour for backwards
    compat.

    ``format_name`` picks the output cut: ``story`` (1080×1920, default),
    ``portrait`` (1080×1350), ``square`` (1080×1080) or ``landscape``
    (1920×1080). Beyond the presets it also accepts a validated arbitrary-canvas
    ``"WxH"`` token (any-canvas — the web routes expose it as ``?w=&h=`` /
    ``?size=WxH``): a distinct ``(w, h)`` keys its own cache entry via the
    already-folded ``size`` list, so the preset paths stay byte-identical.

    When audio is configured (``MEDIAHUB_VOICEOVER=1`` narration and/or an
    operator ``MEDIAHUB_REEL_MUSIC_DIR`` bed), the finished MP4 carries the
    mixed track and the audio plan is folded into the cache key; otherwise
    the silent path's cache keys stay byte-identical to the pre-audio era.
    A poster-frame PNG sidecar is written beside the MP4 either way.

    ``fps`` selects the output frame rate from the curated ``ALLOWED_FPS`` set
    (default 30). A non-default rate folds into the cache key and appends
    ``--fps`` to the render; 30 keeps the byte-identical default.

    ``review_ab`` (per-effect-toggle, REVIEW-ONLY) is an opt-in list of
    decorative axes to SUPPRESS for a with/without comparison — the "B" variant
    of an A/B review, rendered against the normal full-effect "A" render. It is
    validated against ``EFFECT_TOGGLE_ALLOWLIST`` (decorative axes only — photo
    scrims/filters and burn-in captions are never toggleable, so APCA is never at
    risk), attaches ``effectsDisabled`` to the card props, and folds a distinct
    ``ab_review`` marker into the cache key so it can never collide with or shift
    the default render's key/bytes. ``None`` (the default) — and a list that
    validates to empty — leave the render byte-identical to the shipped card, so
    a card that gets exported for posting always keeps still<->motion parity.

    ``alpha_profile`` (alpha-export, opt-in, Remotion-only) selects a
    transparent-background compositing export from the closed
    :data:`ALPHA_PROFILES` vocabulary (``"prores4444"`` / ``"vp9"``). When set,
    the composition's outer full-bleed ground fill is suppressed (via the
    ``transparentBg`` prop), the render is encoded into an alpha container
    (``.mov``/``.webm``) with a distinct cache key, the whole-composition
    supersample is forced off (its libx264 downscale would flatten alpha), and
    the asset is silent by design (a compositing layer carries no audio). On the
    free FFmpeg engine an alpha request raises :class:`AlphaUnsupportedError`
    rather than shipping a mislabeled opaque file. ``""`` (default) → alpha OFF,
    byte-identical to before.
    """
    fps = _validate_fps(fps)
    engine = _dispatch_engine()
    size = motion_format_size(format_name)
    supersample = _motion_supersample()
    # bit-depth-gamut: resolve the opt-in encode profile. None (default) keeps
    # everything byte-identical. When active it is MUTUALLY EXCLUSIVE with the
    # whole-composition supersample downscale, which hardcodes libx264/yuv420p
    # and would flatten a 10-bit render back to 8-bit h264 — so encode wins and
    # supersample is forced off (recorded honestly in the manifest below).
    encode = _motion_encode_profile()
    # alpha-export: an opt-in transparent export OVERRIDES the env encode profile
    # (mutually exclusive — alpha needs prores/vp9 + an alpha pixelFormat) and
    # rides the same ``encode`` seam. On the FFmpeg engine it errors honestly.
    alpha_prof = resolve_alpha_profile(alpha_profile)
    if alpha_prof is not None:
        if engine == "ffmpeg":
            raise AlphaUnsupportedError(
                "alpha_unsupported_on_engine: a transparent-background export "
                "requires the Remotion engine; the free FFmpeg engine composites "
                "opaque 8-bit stills and cannot produce a transparent asset."
            )
        encode = _alpha_encode(alpha_prof)
    if encode is not None:
        supersample = 1.0
    out_path = Path(out_path)
    brand_dict = _brand_to_dict(brand_kit)
    # M23 — footage-backed story: resolve the card's race clip for this 6s
    # beat. Remotion-only (the ffmpeg fallback renders pre-baked stills and
    # cannot play a video plane — its manifest says so honestly); a miss of
    # any kind keeps the photo path byte-identical, reason in the manifest.
    foot, foot_reason = (None, "")
    if engine != "ffmpeg":
        foot, foot_reason = _footage_for_card(
            card_payload,
            brief,
            brand_kit,
            beat_seconds=duration_sec,
            speed_ramp=_brief_speed_ramp(brief),
        )
    card_dict = _card_to_props(
        card_payload,
        variation_seed=variation_seed,
        brief=brief,
        brand_kit=brand_kit,
        format_name=format_name,
        footage=foot,
    )
    audio_plan = _story_audio_plan(
        card_dict, brand_dict, mix_profile=_card_mix_profile(card_payload, brief)
    )
    # alpha-export: a transparent compositing asset is silent by design — drop the
    # audio plan so the mux (_finish_cached_video) never runs (an aac-in-mp4/mov
    # mux is not validated for 10-bit prores / vp9-webm), and no burn-in caption
    # track is derived. Done before the caption build so captions stay off too.
    if alpha_prof is not None:
        audio_plan = None

    # Burn-in captions (R1.3): only attach the prop when a track exists so the
    # captions-off path keeps the historic cache key byte-identical.
    caption_json = _story_caption_json(
        card_dict, brand_dict, audio_plan, duration_sec=duration_sec, fps=fps
    )
    if caption_json:
        card_dict = {**card_dict, "captionsJson": caption_json}

    # transform-sampling (AE-gap): attach the per-photo resample hint ONLY when
    # the operator opted in (> 0), exactly like the captions fold above, so every
    # default render keeps its byte-identical card_dict and story cache key.
    photo_ss = _photo_supersample()
    if photo_ss > 0:
        card_dict = {**card_dict, "photoSupersample": photo_ss}

    # true-motion-blur: attach the opt-in shutter-accumulation config ONLY when
    # the operator opted in (None = OFF), exactly like the photoSupersample fold
    # above, so every default render keeps a byte-identical card_dict + story
    # cache key. The composition wraps only the settling hero/result entrance +
    # count-up in the frame-pure sampler; absent => the verbatim current DOM.
    mblur = _motion_blur()
    if mblur is not None:
        card_dict = {**card_dict, "motionBlur": mblur}

    # alpha-export: mark the card for the transparent export so the composition's
    # false-default ``transparentBg`` prop suppresses the outer full-bleed ground
    # fill. Attach-only (fold-only-when-active), so a non-alpha render keeps a
    # byte-identical card_dict + story cache key.
    if alpha_prof is not None:
        card_dict = {**card_dict, "transparentBg": True}

    # per-effect-toggle (REVIEW-ONLY A/B): attach the suppressed-axis list ONLY on
    # the explicit review path AND only when it validates non-empty, so a shipped
    # render (review_ab=None) keeps a byte-identical card_dict + cache key — the
    # still<->motion parity guarantee. The list rides inside card_dict, so it
    # folds into the story cache key automatically (fold-only-when-present).
    ab_disabled = _validate_effect_toggles(review_ab) if review_ab is not None else []
    if ab_disabled:
        card_dict = {**card_dict, "effectsDisabled": ab_disabled}

    if engine == "ffmpeg":
        from mediahub.visual import reel_ffmpeg

        return reel_ffmpeg.render_story_card_from_props(
            card_dict,
            brand_dict,
            brand_kit,
            out_path,
            duration_sec=duration_sec,
            brief_dict=brief,
            audio_plan=audio_plan,
            format_name=format_name,
            **_fps_kw(fps),
        )

    cache_payload = {
        "card": card_dict,
        "brand": brand_dict,
        "duration": duration_sec,
        "size": list(size),
        "rev": STORY_COMPOSITION_REVISION,
    }
    if audio_plan:
        cache_payload["audio"] = audio_plan
    # M21: an edited photo (safeguarding blur, crop, enhance) re-renders; the
    # signature is attached ONLY when a recipe exists so unedited assets keep
    # byte-identical keys.
    edit_sig = _photo_edit_signature_for_brief(brief)
    if edit_sig:
        cache_payload["photo_edit"] = edit_sig
    # M23: the footage beat's source fingerprint + trim window, folded ONLY
    # when a clip resolved — replacing the source clip re-renders while every
    # no-footage card keeps its byte-identical key.
    if foot is not None:
        cache_payload["footage"] = foot.cache_sig
    # Supersample folds in only when active, so a default (1x) render keeps its
    # byte-identical story cache key; a 2x render keys independently.
    if supersample > 1.0:
        cache_payload["supersample"] = supersample
    # fps-option: fold the frame rate only for a non-default choice, so the
    # default (30fps) story cache key is byte-identical to before.
    if int(fps) != MOTION_FPS:
        cache_payload["fps"] = int(fps)
    # per-effect-toggle (REVIEW-ONLY A/B): a distinct top-level marker so the
    # comparison "B" variant can never collide with, or perturb, the default
    # single-render key. Set ONLY when the review path validated non-empty, so a
    # shipped render's key is untouched.
    if ab_disabled:
        cache_payload["ab_review"] = ab_disabled
    # alpha-export: fold the transparent-export profile under a distinct ``alpha``
    # key when active, so an alpha cut can never be served from — or overwrite —
    # an opaque cache entry, and the default (alpha off) key is untouched.
    # bit-depth-gamut: fold the profile NAME (not the codec strings) into the key
    # only when active, so an 8-bit cache entry can never be served for a 10-bit
    # request (or vice-versa) and the default (encode is None) key is untouched.
    # The two are mutually exclusive (alpha overrode encode above), so exactly one
    # of these folds fires.
    if alpha_prof is not None:
        cache_payload["alpha"] = alpha_prof.key
    elif encode is not None:
        cache_payload["encode"] = encode["name"]
    cache_key = _content_hash(cache_payload, kind="story")
    # Container-aware cached slot: opaque profiles are .mp4; an alpha export writes
    # the profile's .mov/.webm slot (the alpha key already differs, so no collision
    # with an h264 slot).
    cached = _cache_dir() / f"{cache_key}{encode['container'] if encode else '.mp4'}"
    if cached.exists() and cached.stat().st_size > 1024:
        _touch_cache_hit(cached)  # LRU recency (#71)
        # Re-publish the cached MP4 at the caller-requested path. The
        # finishing pass is idempotent: it retries a previously-failed
        # audio attach and backfills a missing poster sidecar.
        audio_rec = _finish_cached_video(
            cached, kind="story", plan=audio_plan, duration_sec=duration_sec
        )
        audio_rec.pop("poster_source", "")
        if audio_plan:
            _update_manifest_audio(cached, audio_rec)
        return _publish(cached, out_path)

    # Render into the cache first so partial failures don't leave a half-
    # written file at the user-visible out_path.
    _run_remotion(
        composition_id=COMP_STORY,
        props={"card": card_dict, "brand": brand_dict},
        out_path=cached,
        duration_sec=duration_sec,
        size=size,
        supersample=supersample,
        **_encode_kw(encode),
        **_fps_kw(fps),
    )
    audio_rec = _finish_cached_video(
        cached, kind="story", plan=audio_plan, duration_sec=duration_sec
    )
    poster_source = audio_rec.pop("poster_source", "")
    from mediahub.visual.audio_mux import poster_path_for

    story_manifest = {
        "kind": "story",
        "engine": engine,
        "format": format_name,
        "size": list(size),
        "duration_sec": duration_sec,
        "fps": int(fps),
        "card": _card_manifest_axes(card_dict),
        "audio": audio_rec,
        "captions": _caption_manifest(card_dict.get("captionsJson") or ""),
        "poster": poster_path_for(cached).name if poster_path_for(cached).exists() else "",
        "poster_source": poster_source,
    }
    if supersample > 1.0:
        story_manifest["supersample"] = supersample
    # alpha-export: record the transparent export HONESTLY and state the real
    # scope boundary + deliberate deviations (silent, opaque scene-internal fills,
    # in-render PNG poster, APCA-pair caveat).
    if alpha_prof is not None:
        story_manifest["alpha"] = _alpha_manifest(alpha_prof)
    # bit-depth-gamut: record the encode profile HONESTLY — the source frames are
    # Chromium 8-bit sRGB; 10-bit reduces encode banding and colorSpace tags the
    # container. This is a precision + metadata change over the same brand-locked,
    # APCA-gated colours, NOT a synthesised wide-gamut master.
    elif encode is not None:
        story_manifest["encode"] = {
            "profile": encode["name"],
            "codec": encode["codec"],
            "pixel_format": encode["pixelFormat"],
            "color_space": encode.get("colorSpace") or "untagged",
            "note": (
                "Higher-bit-depth/gamut-tagged re-ENCODE of the same brand-locked, "
                "APCA-gated colours. Source frames are Chromium 8-bit sRGB; 10-bit "
                "reduces encode banding and colorSpace tags the container — this is "
                "a precision + metadata change, not a synthesised wide-gamut master. "
                "bt2020-ncl is a HLG/2020 re-tag + limited-range matrix relabel over "
                "sRGB-origin pixels (not a true gamut map): a tonemapping player that "
                "honours the tag may display it differently from the approved still."
            ),
        }
        # Mutual exclusion with the whole-composition supersample: if the operator
        # also asked for supersample, say so honestly (encode wins).
        if _motion_supersample() > 1.0:
            story_manifest["supersample"] = {
                "requested": _motion_supersample(),
                "applied": False,
                "reason": "incompatible with encode profile (10-bit downscale unsupported)",
            }
    # transform-sampling (AE-gap): record the per-photo hint HONESTLY — a
    # best-effort compositor interpolation hint, NOT a guaranteed dense-buffer
    # supersample (that is the whole-composition MEDIAHUB_MOTION_SUPERSAMPLE).
    if photo_ss > 0:
        story_manifest["photoSupersample"] = {
            "factor": photo_ss,
            "kind": "best-effort-hint",
            "note": "imageRendering:auto on scaled photos; guaranteed dense-buffer "
            "supersample is the whole-composition MEDIAHUB_MOTION_SUPERSAMPLE",
        }
    # true-motion-blur: record the opt-in shutter-accumulation HONESTLY — the
    # sample count is the per-frame cost multiplier (the composition re-renders the
    # wrapped settling layer ``samples``× per frame), and the scope is bounded to
    # the hero/result entrance + count-up (the photo camera / parallax are NOT
    # sampled, so the held frame stays the approved still). Fold-only-when-active.
    if mblur is not None:
        story_manifest["motionBlur"] = {
            "samples": mblur["samples"],
            "shutter": mblur["shutter"],
            "scope": "entrance+count_up",
            "note": (
                "Real multi-sample shutter accumulation: the settling hero/result "
                "entrance + count-up is recomputed at %d deterministic sub-frames "
                "across a %g-degree shutter and composited with equal-weight "
                "progressive alpha (frame-pure, no @remotion/motion-blur). The "
                "perpetual photo camera / parallax are NOT sampled, so the terminal "
                "held frame collapses to the approved still (still<->motion parity). "
                "Cost scales with the sample count (%d x the wrapped layer's "
                "per-frame work)." % (mblur["samples"], mblur["shutter"], mblur["samples"])
            ),
        }
    # M23 explainability: full provenance when a clip plays; the honest
    # fall-back reason when a candidate existed but the photo path won.
    if foot is not None:
        story_manifest["footage"] = foot.provenance
    elif foot_reason:
        story_manifest["footage"] = {"used": False, "reason": foot_reason}
    _write_render_manifest(cached, story_manifest)
    _prune_motion_cache()  # bound the cache after a cold write (#71)
    published = _publish(cached, out_path)
    return published if published.exists() else cached


# Data-driven reel allocation (SEQ-4): the reel's length follows the number
# of ranked moments instead of a fixed duration — a one-medal weekend is a
# tight 8.5s, a five-PB weekend a 25s recap. Mirrors MeetReel.tsx's scene
# layout (cover + N card scenes + outro beat).
REEL_COVER_SEC = 2.0
REEL_PER_CARD_SEC = 4.0
# M17 (MOTION-4): 2.5s default outro — the old 1.0s meant the CTA close
# (sponsor thank-you / next-up / follow) mathematically never reached full
# opacity before its own fade began. 2.5s gives the retimed OutroScreen a
# CTA fully readable by ~0.9s and a hold of ≥1.2s before the closing fade.
# Mirrored into MeetReel.tsx's rhythm default and reel_ffmpeg's carve;
# explicit rhythm.outro callers keep full control via REEL_OUTRO_RANGE.
REEL_OUTRO_SEC = 2.5

# Reel beat-rhythm & duration customisation (R1.12). The default skeleton above
# stays the contract; these bounds keep a *customised* reel readable and the
# render inside the worker/delayRender timeout. A reel can never be shorter than
# the floor or longer than the ceiling no matter what a caller asks for.
REEL_COVER_RANGE = (1.0, 6.0)
REEL_OUTRO_RANGE = (0.75, 6.0)
REEL_PER_CARD_RANGE = (1.5, 10.0)
REEL_WEIGHT_RANGE = (0.25, 4.0)
REEL_TOTAL_RANGE = (3.0, 60.0)

# Reel composition revision — folded into the reel cache key. Bump it whenever
# MeetReel.tsx's deterministic output changes for an *unchanged* payload, so
# reels cached against the previous render are retired and the upgrade reaches
# re-requested meets instead of serving a stale cut. Story renders are keyed
# separately and stay byte-identical, so this is reel-only.
#   "2" — R1.14: expanded transition library (glitch / slide-stack /
#         light-sweep) + per-card transition timing.
#   "3" — Phase C (M15–M20): default photo camera moves, paired
#         velocity-matched transitions (no mid-reel self-fades), legible
#         2.5s outro retime, brand-true cover/outro roles + photo cover,
#         beat-proportional choreography + resolve accents, reel chrome
#         (progress rail + club mark).
#   "4" — Still↔motion parity pass: photo-mode archetypes drop the cutout
#         plane, exact M10 duotone/halftone mirrors replace the CSS
#         approximation on beats, M11 stat chips + PB bars, and the M12
#         layered-archetype scenes (poster_name_behind / band_break).
#   (Phase D / M23 footage beats deliberately did NOT bump this: the video
#   plane only activates on the new attach-only videoSrc props, so a reel
#   with an unchanged payload renders byte-identically — the exact condition
#   this revision lever exists to police. Footage reels re-key through the
#   new props + the cache_payload["footage"] fold instead.)
#   "5" — #1058: per-card connective reel transitions (each lower beat now
#         picks its own quiet cut from ITS seed instead of one shared kind)
#         + firmer on-video text (outline / shadow3d / stroke_animate) and
#         firmer photo scrim for muted-feed legibility. All change MeetReel's
#         deterministic output for an unchanged payload, so cached reels retire.
#   "6" — the whip transition's blur is now velocity-aligned: an X-axis-only
#         SVG feGaussianBlur (a genuine directional smear along the lateral
#         motion) replaces the isotropic CSS blur() on both the incoming
#         (TransitionWrap) and paired exit (ExitWrap) whip. Reel-only (whip
#         lives only in MeetReel), so cached reels retire; story is untouched.
#   "7" — per-glyph text reveal: the shared KineticLine / KineticWords gained a
#         glyph-granularity branch for the kinetic_type / cascade intents. Word
#         mode is byte-identical; belt-and-braces bump since the shared line
#         component changed (renderer_generation already busts + re-renders the
#         untouched cards identically).
#   "8" — range selectors: the per-glyph reveal's stagger ORDER × SHAPE now flows
#         through the seeded sprint/rangeSelector.ts vocabulary (reverse /
#         centre-out / seeded scatter, eased), picked from (variationSeed, mood).
#         The identity selector ({index, linear}, e.g. every restraint mood) is
#         byte-identical to rev "7"; energetic / seed-varied glyph cards reveal
#         in a new order, so a glyph-opted reel's deterministic output changes for
#         an unchanged payload — hence the bump. Word-mode + non-glyph cards are
#         untouched (glyphAt is never invoked there).
#   "9" — varfont-animation: the supporting weight registers (kicker/meta/data)
#         now BLOOM their variable wght axis up to the still's static target over
#         the first ~20% of the beat (StoryCard.wghtFvs + shared wghtBloomAt;
#         sceneKit's data chips share the curve). Register-ABSENT cards
#         (wghtKicker/Meta/Data == 0) keep wghtFvs's unchanged `{}` branch and
#         render byte-identically; a register-BEARING reel's deterministic output
#         changes for an unchanged payload (the terminal/held weight equals the
#         still, so still↔motion parity holds) — hence the bump.
#   "10" — stylize-richer: photo_filters.tsx gained three held SVG stylize looks
#          (mosaic / motion_tile / roughen_edges) + the tunable
#          photo_treatment_intensity. Untreated cards attach none of the new
#          props and render byte-identically, but editing the shared photo_filters
#          layer busts renderer_generation()'s content hash once — a documented
#          full re-render (identical pixels for unchanged intents/cards), so this
#          bump is the explicit human signal for the shared-vocabulary change.
#   "11" — render-banding-dither: a new Dither.tsx overlay component, mounted in
#          StoryCard (every reel card beat) and on the reel cover/outro when a
#          card opted in. Cards WITHOUT the attach-only `dither` prop render the
#          untouched default path (pixel-identical), but adding Dither.tsx +
#          editing MeetReel busts renderer_generation()'s content hash once — a
#          documented full re-render, hence this explicit bump.
REEL_COMPOSITION_REVISION = "11"

# Story composition revision — folded into the STORY cache key (M15). The
# story payload historically had no revision field; introducing one both
# retires every pre-Phase-C cached story (buying the photo-camera +
# proportional-choreography upgrade on re-request) and gives future visual
# upgrades a clean lever. Bump whenever StoryCard.tsx's deterministic output
# changes for an unchanged payload.
#   "1" — Phase C (M15/M19): seed-chosen photo camera moves on every intent,
#         beat-proportional keyframes, resolve-phase micro-accent, ambient
#         PEAK_ALPHA 0.14.
#   "2" — Still↔motion parity pass: photo-mode archetypes show the original
#         photograph (no cutout plane), exact M10 duotone/halftone mirrors
#         replace the CSS approximation, M11 stat chips + PB bars, and the
#         M12 layered-archetype scenes (poster_name_behind / band_break).
#   (Phase D / M23 footage beats deliberately did NOT bump this: the video
#   plane only activates on the new attach-only videoSrc props, so a story
#   with an unchanged payload renders byte-identically — the exact condition
#   this revision lever exists to police. Footage stories re-key through the
#   new props + the cache_payload["footage"] fold instead.)
#   "3" — #1058: firmer on-video text (outline / shadow3d / stroke_animate)
#         and firmer photo scrim. The reel's per-card connective transition
#         change is reel-only, but StoryCard shares the text_fx + photo_scrim
#         sprint layers, so these firmer values change a story's deterministic
#         output for an unchanged payload too — hence the story bump.
#   "4" — per-glyph text reveal: KineticLine gained a glyph-granularity branch
#         (kinetic_type / cascade opt in via the deterministic seed gate). Word
#         mode renders byte-identically, so an unchanged, non-opted-in payload is
#         pixel-identical; this bump is belt-and-braces for the shared component.
#   "5" — range selectors: the per-glyph reveal's stagger ORDER × SHAPE now flows
#         through the seeded sprint/rangeSelector.ts vocabulary (reverse /
#         centre-out / seeded scatter, eased), picked from (variationSeed, mood).
#         The identity selector ({index, linear}, e.g. every restraint mood)
#         renders byte-identically to rev "4"; energetic / seed-varied glyph cards
#         reveal in a new order, so a glyph-opted story's deterministic output
#         changes for an unchanged payload. Word-mode + non-glyph cards are
#         untouched (glyphAt is never invoked there).
#   "6" — varfont-animation: the supporting weight registers (kicker/meta/data)
#         now BLOOM their variable wght axis up to the still's static target over
#         the first ~20% of the beat (StoryCard.wghtFvs + shared wghtBloomAt).
#         Register-ABSENT cards keep the unchanged `{}` branch and render
#         byte-identically; a register-BEARING story's deterministic output
#         changes for an unchanged payload (terminal/held weight equals the
#         still — still↔motion parity preserved) — hence the bump.
#   "7" — stylize-richer: photo_filters.tsx gained three held SVG stylize looks
#         (mosaic / motion_tile / roughen_edges) + the tunable
#         photo_treatment_intensity. Untreated cards attach none of the new props
#         and render byte-identically; editing the shared photo_filters layer
#         busts renderer_generation()'s content hash once — a documented full
#         re-render (identical pixels for unchanged cards) — so this bump is the
#         explicit human signal for the shared-vocabulary change.
#   "8" — render-banding-dither: StoryCard gained a Dither.tsx overlay, mounted
#         only when the attach-only `dither` prop is set. A card WITHOUT it
#         renders the untouched default path (pixel-identical); adding the new
#         component busts renderer_generation()'s content hash once — a
#         documented full re-render, so this bump is the explicit human signal.
STORY_COMPOSITION_REVISION = "8"


def _clamp(value: float, lo: float, hi: float) -> float:
    """Pin ``value`` into ``[lo, hi]`` (no surprises on NaN — treated as lo)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    if v != v:  # NaN
        return lo
    return lo if v < lo else hi if v > hi else v


def _fit_beat_weights(weights: list, n: int) -> list[float]:
    """Clamp + fit a caller's per-card weights to exactly ``n`` cards.

    Too few → padded with 1.0 (a normal beat); too many → truncated. Each
    weight is clamped into ``REEL_WEIGHT_RANGE`` and a non-numeric entry
    falls back to 1.0, so junk input degrades to a plain beat rather than a
    crash.
    """
    out: list[float] = []
    for i in range(max(0, int(n))):
        if i < len(weights):
            try:
                out.append(round(_clamp(float(weights[i]), *REEL_WEIGHT_RANGE), 4))
            except (TypeError, ValueError):
                out.append(1.0)
        else:
            out.append(1.0)
    return out


def reel_duration_for(
    n_cards: int,
    *,
    cover_sec: Optional[float] = None,
    outro_sec: Optional[float] = None,
    per_card_sec: Optional[float] = None,
    beat_weights: Optional[list] = None,
) -> float:
    """Total reel seconds for ``n_cards`` ranked moments.

    Deterministic structure maths (cover + per-card beats + outro), capped to
    the same 1..5 card range the route and the TSX composition enforce. Three
    cards land on the historic 15s default, so existing three-card reels keep
    their cached duration.

    R1.12 — beat-rhythm & duration customisation. With every keyword left
    ``None`` the result is byte-identical to the original ``2 + 4·n + 1``
    formula. A caller may stretch the bookends (``cover_sec`` / ``outro_sec``),
    re-scale the per-card base (``per_card_sec``), and/or pass explicit
    ``beat_weights`` — in which case the card budget grows with the weight sum
    (a weight-2 card earns twice a weight-1 card's seconds), so emphasising a
    moment lengthens the reel honestly rather than silently squeezing the
    others. All inputs are clamped to readable, render-safe bounds and the
    grand total is pinned to ``REEL_TOTAL_RANGE``.
    """
    n = max(1, min(int(n_cards or 1), 5))
    cover = REEL_COVER_SEC if cover_sec is None else _clamp(cover_sec, *REEL_COVER_RANGE)
    outro = REEL_OUTRO_SEC if outro_sec is None else _clamp(outro_sec, *REEL_OUTRO_RANGE)
    per_card = (
        REEL_PER_CARD_SEC if per_card_sec is None else _clamp(per_card_sec, *REEL_PER_CARD_RANGE)
    )
    if beat_weights:
        weight_total = sum(_fit_beat_weights(beat_weights, n))
    else:
        weight_total = float(n)
    total = cover + per_card * weight_total + outro
    return round(_clamp(total, *REEL_TOTAL_RANGE), 3)


def normalise_reel_rhythm(raw: Any, n_cards: int) -> Optional[dict]:
    """Resolve a caller's reel-rhythm request into a canonical dict — or
    ``None`` when it asks for nothing the default skeleton doesn't already do.

    Accepts snake_case, camelCase, and the obvious aliases
    (``cover``/``outro``/``weights``) so the web query string, a Python caller,
    and the persisted manifest can all speak the same shape. The returned dict
    is camelCase to match the Remotion props verbatim::

        {"coverSec": float, "outroSec": float, "perCardSec": float,
         "beatWeights": [float, …]}

    ``beatWeights`` is the explicit per-card list (fitted to ``n_cards``) when
    the caller supplied one, otherwise ``[]`` — meaning "keep the reel's
    default top-card emphasis". Returning ``None`` for an effectively-default
    request is what guarantees today's reels keep their exact cached output.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    n = max(1, min(int(n_cards or 1), 5))

    def _pick(*keys: str):
        for k in keys:
            if k in raw and raw[k] is not None:
                return raw[k]
        return None

    cover_raw = _pick("cover_sec", "coverSec", "cover")
    outro_raw = _pick("outro_sec", "outroSec", "outro")
    per_card_raw = _pick("per_card_sec", "perCardSec", "perCard", "beat_sec", "beatSec", "beat")
    weights_raw = _pick("beat_weights", "beatWeights", "weights")

    cover = REEL_COVER_SEC if cover_raw is None else _clamp(cover_raw, *REEL_COVER_RANGE)
    outro = REEL_OUTRO_SEC if outro_raw is None else _clamp(outro_raw, *REEL_OUTRO_RANGE)
    per_card = (
        REEL_PER_CARD_SEC if per_card_raw is None else _clamp(per_card_raw, *REEL_PER_CARD_RANGE)
    )

    weights: list[float] = []
    if weights_raw is not None:
        seq = weights_raw if isinstance(weights_raw, (list, tuple)) else [weights_raw]
        weights = _fit_beat_weights(list(seq), n)

    is_default = (
        abs(cover - REEL_COVER_SEC) < 1e-9
        and abs(outro - REEL_OUTRO_SEC) < 1e-9
        and abs(per_card - REEL_PER_CARD_SEC) < 1e-9
        and not weights
    )
    if is_default:
        return None
    return {
        "coverSec": round(cover, 3),
        "outroSec": round(outro, 3),
        "perCardSec": round(per_card, 3),
        "beatWeights": weights,
    }


# R1.13 — the honest stat vocabulary the reel cover can chip: the exact keys of
# MeetReel.tsx reelStats' counts table. Every value is counted from real card
# facts; the config below only chooses WHICH honest chips show, HOW MANY, and
# their display WORDING — never the numbers themselves.
REEL_STAT_IDS: tuple[str, ...] = (
    "swims",
    "pbs",
    "medals",
    "records",
    "seasonBests",
    "relayWins",
    "finals",
    "topSplits",
)


def normalise_reel_stat_config(raw: Any) -> Optional[dict]:
    """Resolve a caller's stat-chip config (R1.13) into the canonical
    ``reelStatConfig`` prop shape — or ``None`` when it asks for nothing.

    Accepts ``include`` (ordered stat ids), ``max`` (chip cap, ≥ 0) and
    ``labels`` (per-id wording overrides; a ``{n}`` placeholder marks where the
    honest count renders). Ids are validated against ``REEL_STAT_IDS`` and an
    unknown id / junk value raises ``ValueError`` — a typo should be a loud
    error at the caller, never a silently missing chip. Returning ``None`` for
    an empty request keeps unconfigured reels' props and cache keys
    byte-identical.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("reel stat config must be an object")
    if not raw:
        return None

    out: dict[str, Any] = {}

    include_raw = raw.get("include")
    if include_raw is not None:
        if not isinstance(include_raw, (list, tuple)):
            raise ValueError("stat config 'include' must be a list of stat ids")
        include = [str(i) for i in include_raw]
        unknown = sorted(set(include) - set(REEL_STAT_IDS))
        if unknown:
            raise ValueError(
                f"unknown stat id(s) {', '.join(unknown)} — valid: {', '.join(REEL_STAT_IDS)}"
            )
        if include:
            out["include"] = include

    max_raw = raw.get("max")
    if max_raw is not None:
        try:
            max_chips = int(max_raw)
        except (TypeError, ValueError):
            raise ValueError("stat config 'max' must be an integer") from None
        if max_chips < 0:
            raise ValueError("stat config 'max' must be >= 0")
        out["max"] = max_chips

    labels_raw = raw.get("labels")
    if labels_raw is not None:
        if not isinstance(labels_raw, dict):
            raise ValueError("stat config 'labels' must map stat ids to wording")
        unknown = sorted(set(str(k) for k in labels_raw) - set(REEL_STAT_IDS))
        if unknown:
            raise ValueError(
                f"unknown stat id(s) {', '.join(unknown)} — valid: {', '.join(REEL_STAT_IDS)}"
            )
        labels = {str(k): str(v) for k, v in labels_raw.items() if str(v).strip()}
        if labels:
            out["labels"] = labels

    return out or None


def _js_round(x: float) -> int:
    """JavaScript ``Math.round`` (half away from zero for positives) — Python's
    banker's rounding would drift off the TSX carve at exact .5 frames."""
    return int(math.floor(float(x) + 0.5))


def reel_card_beat_frames(
    n_cards: int, duration_sec: float, rhythm: Optional[dict] = None, *, fps: int = MOTION_FPS
) -> list[int]:
    """Per-card beat frames — the exact Python mirror of MeetReel.tsx's carve.

    The reel allocates ``durationInFrames`` as cover + rank/weight-carved card
    beats + outro; each beat's frames come from the rhythm's weights (explicit
    ``beatWeights``, else the default 1.25× top-card emphasis when more than
    one card). The caption track for a beat must be sized to *these* frames —
    not a flat ``REEL_PER_CARD_SEC`` grid — or trailing cues get cut off on
    shorter beats and end early on the emphasised one. Keep in lock-step with
    ``MeetReel.tsx`` (coverFrames/outroFrames/transitionFrames/minBeat maths).
    """
    n = max(0, min(int(n_cards or 0), 5))
    if n == 0:
        return []
    r = rhythm or {}
    cover_sec = (
        r["coverSec"] if r.get("coverSec", 0) and float(r["coverSec"]) > 0 else REEL_COVER_SEC
    )
    outro_sec = (
        r["outroSec"] if r.get("outroSec", 0) and float(r["outroSec"]) > 0 else REEL_OUTRO_SEC
    )
    duration_in_frames = max(1, _js_round(float(duration_sec) * fps))
    cover_frames = _js_round(fps * float(cover_sec))
    outro_frames = _js_round(fps * float(outro_sec))
    transition_frames = _js_round(fps * 0.35)
    remaining = max(0, duration_in_frames - cover_frames - outro_frames)

    explicit = list(r.get("beatWeights") or [])
    weights: list[float] = []
    for i in range(n):
        if explicit:
            w = explicit[i] if i < len(explicit) else None
            weights.append(float(w) if isinstance(w, (int, float)) and w > 0 else 1.0)
        else:
            weights.append(1.25 if i == 0 and n > 1 else 1.0)
    weight_sum = sum(weights) or 1.0
    min_beat = transition_frames * 2 + _js_round(fps * 0.5)
    return [
        max(min_beat, math.floor(remaining * w / weight_sum) + transition_frames) for w in weights
    ]


def _reel_duration_kwargs(rhythm: Optional[dict]) -> dict:
    """The ``reel_duration_for`` keyword args implied by a canonical rhythm."""
    if not rhythm:
        return {}
    kw = {
        "cover_sec": rhythm.get("coverSec"),
        "outro_sec": rhythm.get("outroSec"),
        "per_card_sec": rhythm.get("perCardSec"),
    }
    if rhythm.get("beatWeights"):
        kw["beat_weights"] = rhythm["beatWeights"]
    return kw


def _render_reel_parallel_or_none(
    *, props: dict, cached: Path, duration_sec: float, size: tuple[int, int], fps: int = MOTION_FPS
) -> Optional[Path]:
    """Opt-in parallel reel composition (roadmap R1.28).

    Delegates to :mod:`mediahub.visual.reel_parallel`: when
    ``MEDIAHUB_REEL_PARALLEL`` is set and Node/Remotion/FFmpeg are available,
    the reel's frame timeline is split across concurrent segment renders and
    composited into the silent cache MP4 at ``cached`` — exactly what the
    serial ``_run_remotion`` would write, just faster on a multi-core worker.

    Returns the path on success, or ``None`` (the signal to take the serial
    render) when the feature is disabled, the prerequisites are missing, or
    anything goes wrong. Frame-purity makes the parallel output identical to
    the serial reel, so the content cache key is unchanged either way.
    """
    from mediahub.visual import reel_parallel

    return reel_parallel.try_render_reel_parallel(
        composition_id=COMP_REEL,
        props=props,
        out_path=cached,
        duration_sec=duration_sec,
        size=size,
        **_fps_kw(fps),
    )


def _assemble_reel_props(
    top_cards: list[dict],
    brand_kit: Any,
    *,
    meet_name: str,
    duration_sec: Optional[float],
    briefs: Optional[list[Optional[dict]]],
    rhythm: Optional[dict] = None,
    dub_language: str = "",
    resolve_footage: bool = False,
    peak_speed_ramp: str = "",
    fps: int = MOTION_FPS,
) -> tuple[list[dict], dict, str, float, Any, list, Optional[dict], Optional[dict], list]:
    """Format-independent prop assembly shared by the single and batch reel
    renders.

    Embeds the cards' photos, resolves saliency + still-parity colour roles,
    derives the data-driven duration, picks the reel's audio-mix profile
    (R1.19), builds the audio plan, and bakes in the R1.3 burn-in captions —
    none of which depend on the output pixel size. Pulling it out lets
    ``render_meet_reel_all_formats`` do this once and reuse it across every
    cut, instead of re-embedding photos and re-resolving roles per format.

    R1.12 — the optional ``rhythm`` (a dict understood by
    ``normalise_reel_rhythm``: custom ``cover``/``outro``/``per_card`` seconds
    and/or per-card ``weights``) folds into the data-driven duration here and is
    returned normalised so each per-format render carries the same rhythm into
    its props + cache key. ``None`` or an effectively-default request keeps the
    historic skeleton and byte-identical cache key.

    ``resolve_footage`` (M23) turns on per-beat race-clip resolution: each
    card's clip is trimmed to ITS carved beat seconds (the exact MeetReel.tsx
    allocation — rank-weighted / rhythm-custom), so an emphasised beat earns a
    longer window. Off (the default, and always off for the ffmpeg engine),
    every prop dict is byte-identical to the photo-only behaviour.

    ``peak_speed_ramp`` (speed-ramp, opt-in) requests a baked decelerate-into-
    the-beat ramp on the reel's PEAK beat only (``idx==0`` — the #1 ranked card
    the beat carve already emphasises). It is a SERVER-ONLY field, deliberately
    kept OUT of the Remotion-bound ``rhythm`` dict (the ramp is baked into the
    clip, never a prop). ``""`` (the default) leaves every footage beat
    byte-identical.

    Returns ``(cards_props, brand_dict, meet_name, duration_sec, audio_plan,
    briefs_list, rhythm_norm, audio_notes, footage_list)`` — ``audio_notes``
    carries honest manifest-only facts about the plan (e.g. a dropped dub's
    reason) and never folds into any cache key; ``footage_list`` is the
    per-card ``(FootageResolution | None, reason)`` pairs for the cache fold
    and the manifest.
    """
    brand_dict = _brand_to_dict(brand_kit)

    # R1.12 — resolve the (optional) beat-rhythm customisation and the
    # data-driven duration UP FRONT (they depend only on the card count), so
    # the per-card beat carve is known before props are shaped and each
    # footage window (M23) can be sized to its own beat. ``None`` for a
    # default request, so the duration maths, cache key, and render props
    # below all stay byte-identical to a reel rendered before this feature.
    n_cards = len(top_cards or [])
    rhythm_norm = normalise_reel_rhythm(rhythm, n_cards)
    if duration_sec is None:
        duration_sec = reel_duration_for(n_cards, **_reel_duration_kwargs(rhythm_norm))
    beat_frames = reel_card_beat_frames(n_cards, duration_sec, rhythm_norm, fps=fps)

    cards_props: list[dict] = []
    footage_list: list[tuple[Optional[Any], str]] = []
    briefs_list = list(briefs or [])
    for idx, c in enumerate(top_cards or []):
        # variation seed per card — caller may pass via {"variation_seed": N}
        seed = 0
        if isinstance(c, dict):
            seed = int(c.get("variation_seed") or 0)
            if not seed:
                # Derive a stable seed from the card id so re-renders are
                # deterministic per card without the caller having to
                # pre-compute it.
                cid = (
                    c.get("id")
                    or c.get("swim_id")
                    or (c.get("achievement") or {}).get("swim_id")
                    or ""
                )
                if cid:
                    try:
                        from mediahub.creative_brief.generator import (
                            auto_variation_seed_for,
                        )

                        seed = auto_variation_seed_for(str(cid))
                    except Exception:
                        seed = 1
        brief = briefs_list[idx] if idx < len(briefs_list) else None
        # M23 — this card's footage beat, trimmed to its OWN carved beat
        # seconds. Only attempted when the engine can play it; any miss keeps
        # the card's props byte-identical with the reason kept for the manifest.
        foot, foot_reason = (None, "")
        if resolve_footage and idx < len(beat_frames):
            # Convert this beat's carved frames to seconds at the SELECTED fps —
            # beat_frames already scales with fps, so dividing by the fixed
            # MOTION_FPS would over-trim the footage window by fps/30 at 50/60.
            # speed-ramp is gated to the PEAK beat (idx==0) and only when the
            # server-only opt-in named a kind, so every other beat is untouched.
            foot, foot_reason = _footage_for_card(
                c,
                brief,
                brand_kit,
                beat_seconds=beat_frames[idx] / fps,
                speed_ramp=peak_speed_ramp if idx == 0 else "",
            )
        footage_list.append((foot, foot_reason))
        # Format-independent base focus (story 9:16); the per-cut saliency
        # photoPos is re-resolved downstream in _render_reel_one_format (R1.7).
        cards_props.append(
            _card_to_props(c, variation_seed=seed, brief=brief, brand_kit=brand_kit, footage=foot),
        )

    if not meet_name:
        for cp in cards_props:
            if cp.get("meetName"):
                meet_name = cp["meetName"]
                break

    # One reel, one mix (R1.19): the headline (first card to name one) drives
    # the voice/music balance; absent that, the operator env default decides.
    reel_mix = None
    for idx, c in enumerate(top_cards or []):
        b = briefs_list[idx] if idx < len(briefs_list) else None
        reel_mix = _card_mix_profile(c, b)
        if reel_mix:
            break
    audio_plan, dub_error = _reel_audio_plan(
        cards_props,
        brand_dict,
        meet_name,
        duration_sec=duration_sec,
        mix_profile=reel_mix,
        dub_language=dub_language,
    )
    audio_notes = {"dub_error": dub_error} if dub_error else None

    # Burn-in captions (R1.3): caption each beat from its own verified line when
    # the reel has a voice plan and the operator opted in. Only set when a track
    # exists, so the captions-off cache key stays byte-identical. The Remotion
    # engine paints these via captions.tsx; the still+FFmpeg fallback does not
    # burn reel captions (it renders pre-baked stills) and silently ignores them.
    # Beat-grid is the per-card duration, not the output size, so the same
    # captioned cards drive every cut a batch produces. Each card's track is
    # sized to its OWN carved beat (rank-weighted / rhythm-custom — the exact
    # MeetReel.tsx allocation), not a flat REEL_PER_CARD_SEC grid, so trailing
    # cues survive short beats and the emphasised beat stays captioned.
    if _subtitles_enabled() and audio_plan and audio_plan.get("voice") and audio_plan.get("script"):
        beats = reel_card_beat_frames(len(cards_props), duration_sec, rhythm_norm, fps=fps)
        for idx, cp in enumerate(cards_props):
            beat_frames = max(1, beats[idx]) if idx < len(beats) else 1
            cj = _reel_caption_json(cp, brand_dict, beat_frames=beat_frames, fps=fps)
            if cj:
                cp["captionsJson"] = cj

    return (
        cards_props,
        brand_dict,
        meet_name,
        duration_sec,
        audio_plan,
        briefs_list,
        rhythm_norm,
        audio_notes,
        footage_list,
    )


def _cover_brand_roles(brand_dict: dict, brand_kit: Any) -> dict[str, str]:
    """APCA-gated bookend roles for the reel cover/outro (M18 / MOTION-5).

    Runs the SAME graphic_renderer role resolver the card beats use
    (``resolved_role_vars_for_brief``) against the bare brand palette — Tier A
    brand baseline, contrast-picked on-colours, no invented hex — so a club
    whose accent fails contrast against its primary no longer gets an
    illegible cover. Empty dict on any miss (the TSX then keeps the legacy
    accent-on-primary pairing).
    """
    try:
        from types import SimpleNamespace

        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

        shim = SimpleNamespace(
            palette={
                "primary": str(brand_dict.get("primary") or ""),
                "secondary": str(brand_dict.get("secondary") or ""),
                "accent": str(brand_dict.get("accent") or ""),
            },
            colour_role_assignment=None,
            text_layers={},
            inspiration_pattern_id="",
        )
        root_vars = resolved_role_vars_for_brief(shim, brand_kit)
        roles = {
            "ground": str(root_vars.get("--mh-primary") or ""),
            "surface": str(root_vars.get("--mh-surface") or ""),
            "accent": str(root_vars.get("--mh-accent") or ""),
            "onGround": str(root_vars.get("--mh-on-primary") or ""),
        }
        return roles if roles["ground"] and roles["onGround"] else {}
    except Exception:
        return {}


def _reel_cover_props(cards_props: list[dict], brand_dict: dict, brand_kit: Any) -> dict[str, str]:
    """The reel's brand-true cover/outro props (M18), assembled Python-side:

    * ``coverRole*`` — the APCA-gated bookend roles (see ``_cover_brand_roles``);
    * ``coverTypography`` — the top card's typography pair, so the cover's
      masthead face matches the club's approved cards;
    * ``coverPhotoSrc``/``coverPhotoPos`` — the top photo-bearing card's photo,
      feeding the pool-gated fifth "photo" cover variant.

    Every key is attached ONLY when it resolved, and the dict is folded into
    the render props + cache key only when non-empty — a reel with none of
    them stays byte-identical.
    """
    out: dict[str, str] = {}
    roles = _cover_brand_roles(brand_dict, brand_kit)
    if roles:
        out["coverRoleGround"] = roles["ground"]
        out["coverRoleSurface"] = roles["surface"]
        out["coverRoleAccent"] = roles["accent"]
        out["coverRoleOnGround"] = roles["onGround"]
    for cp in cards_props:
        if cp.get("typographyPair"):
            out["coverTypography"] = str(cp["typographyPair"])
            break
    for cp in cards_props:
        if cp.get("photoSrc"):
            out["coverPhotoSrc"] = str(cp["photoSrc"])
            if cp.get("photoPos"):
                out["coverPhotoPos"] = str(cp["photoPos"])
            break
    return out


def _reel_cta_props(sponsor: str, next_meet: str) -> dict[str, str]:
    """R1.30 outro-CTA props (sponsor thanks / next meet), folded into the
    Remotion props AND the cache key ONLY when present, so a reel with neither
    stays byte-identical to before R1.30. Honest: only a sponsor / next meet
    the caller actually supplied is ever shown."""
    cta: dict[str, str] = {}
    sponsor = (sponsor or "").strip()
    next_meet = (next_meet or "").strip()
    if sponsor:
        cta["sponsor"] = sponsor
    if next_meet:
        cta["nextMeet"] = next_meet
    return cta


def _apply_format_photo_focus(
    cards_props: list[dict], briefs_list: list, format_name: str
) -> list[dict]:
    """Re-resolve each card's saliency ``photoPos`` for this cut (R1.7).

    ``_assemble_reel_props`` embeds photos + resolves colour roles once with the
    format-independent story (9:16) focus; every other cut needs the focal point
    recomputed for its own aspect ratio so the subject stays in frame. Returns a
    new list, shallow-copying only the cards whose focus actually changes. The
    ``story`` cut (and any card without a photo) is returned untouched, so its
    cache key — and the expensive embedded ``photoSrc``/``cutoutSrc`` bytes —
    stay byte-identical.
    """
    if format_name == DEFAULT_MOTION_FORMAT:
        return cards_props
    out: list[dict] = []
    for idx, cp in enumerate(cards_props):
        # LEFTOVER-1: a human's manual crop is format-agnostic and always
        # wins — never clobber it with the recomputed saliency focus.
        if cp.get("photoPosManual"):
            out.append(cp)
            continue
        brief = briefs_list[idx] if idx < len(briefs_list) else None
        pos = _photo_focus_for_brief(brief, format_name)
        if pos == cp.get("photoPos", ""):
            out.append(cp)
        else:
            updated = dict(cp)
            updated["photoPos"] = pos
            out.append(updated)
    return out


def _render_reel_one_format(
    *,
    cards_props: list[dict],
    brand_dict: dict,
    brand_kit: Any,
    meet_name: str,
    duration_sec: float,
    audio_plan: Any,
    briefs_list: list,
    cta_props: dict,
    engine: str,
    format_name: str,
    out_path: Path,
    rhythm: Optional[dict] = None,
    audio_notes: Optional[dict] = None,
    stat_config: Optional[dict] = None,
    footage_list: Optional[list] = None,
    fps: int = MOTION_FPS,
    review_ab: Optional[list[str]] = None,
    logo_drawon: bool = False,
    alpha_profile: str = "",
) -> Path:
    """Render (or serve cached) ONE reel cut from already-assembled props.

    The cache payload folds in the format's pixel ``size``, so each cut caches
    independently — and the ``story`` cut's key stays byte-identical to the
    pre-multi-format render (same cards/brand/meet/duration/cta/audio, same
    size), so existing cached reels remain valid cache hits whether they were
    produced by the single route or the batch. Carries main's R1.28 parallel
    path, R1.30 outro CTA, R1.19 audio-mix and R1.3 captions through unchanged.

    ``stat_config`` (R1.13, canonical via ``normalise_reel_stat_config``) rides
    into the Remotion props AND the cache key ONLY when present, so an
    unconfigured reel stays byte-identical. The still+FFmpeg fallback's cover
    is a pre-baked still with its own chip policy and silently ignores it
    (same contract as reel captions).
    """
    size = motion_format_size(format_name)
    supersample = _motion_supersample()
    # bit-depth-gamut: resolve the opt-in encode profile. None (default) keeps
    # every reel byte-identical. When active it is MUTUALLY EXCLUSIVE with the
    # supersample downscale (which would flatten 10-bit back to 8-bit h264) and
    # forces the SERIAL render path — the parallel-segment composite stream-copies
    # h264 segments and threads no codec/pixelFormat/colorSpace, so it cannot emit
    # the profile output. encode wins; supersample is forced off.
    encode = _motion_encode_profile()
    # alpha-export: an opt-in transparent reel OVERRIDES the env encode profile
    # (mutually exclusive) and rides the same ``encode`` seam. It forces the
    # SERIAL render (the parallel-segment composite stream-copies h264 and threads
    # no codec/pixelFormat — the ``encode is None`` guard below already excludes
    # it), silences the reel, and errors honestly on the FFmpeg engine.
    alpha_prof = resolve_alpha_profile(alpha_profile)
    if alpha_prof is not None:
        if engine == "ffmpeg":
            raise AlphaUnsupportedError(
                "alpha_unsupported_on_engine: a transparent-background reel "
                "requires the Remotion engine; the free FFmpeg engine composites "
                "opaque 8-bit stills and cannot produce a transparent asset."
            )
        encode = _alpha_encode(alpha_prof)
        audio_plan = None
    if encode is not None:
        supersample = 1.0
    photo_ss = _photo_supersample()
    # true-motion-blur: resolve the opt-in shutter-accumulation config once. None
    # (default) keeps the reel byte-identical. The whip transition lives in the
    # composition chrome (not per-card), so this is a REEL-LEVEL prop — it rides
    # into reel_props + the cache key only when active, and the composition threads
    # it down to each <StoryCard> beat's entrance/count-up as a dedicated prop, so
    # cards_props (and its cache contribution) stay byte-identical when off.
    mblur = _motion_blur()
    out_path = Path(out_path)
    # R1.7: steer each card's photo focus for this cut's aspect ratio (no-op for
    # the story base). Folds into the cache key below, so each cut caches its own
    # focus and the story cut stays byte-identical.
    cards_props = _apply_format_photo_focus(cards_props, briefs_list, format_name)

    # transform-sampling (AE-gap): attach the per-photo resample hint to each
    # beat's card ONLY when opted in (> 0), mirroring the fold-only pattern so an
    # un-opted reel keeps byte-identical card props and cache key. Each reel beat
    # renders through <StoryCard>, so the card prop drives supersampledImgStyle
    # identically to the story path.
    if photo_ss > 0:
        cards_props = [{**cp, "photoSupersample": photo_ss} for cp in cards_props]

    # alpha-export: mark every beat's card for the transparent export so each
    # <StoryCard> beat suppresses its outer ground fill; the reel-level cover/outro
    # inherit it via reel_props["transparentBg"] below. Attach-only, so a non-alpha
    # reel keeps byte-identical card props + cache key.
    if alpha_prof is not None:
        cards_props = [{**cp, "transparentBg": True} for cp in cards_props]

    # per-effect-toggle (REVIEW-ONLY A/B): suppress the decorative axes on EVERY
    # beat's card for a with/without comparison reel, attached ONLY on the
    # explicit review path AND only when it validates non-empty, so a shipped
    # reel keeps byte-identical card props + cache key. Rides through <StoryCard>
    # (and the ffmpeg path's card manifest) via the card prop. The reel COVER and
    # OUTRO are separate, non-per-card scenes and deliberately keep their full
    # treatment — the toggle scopes to the card beats it names.
    ab_disabled = _validate_effect_toggles(review_ab) if review_ab is not None else []
    if ab_disabled:
        cards_props = [{**cp, "effectsDisabled": ab_disabled} for cp in cards_props]

    # M18 — brand-true cover/outro props (APCA-gated roles, top card's
    # typography, top photo for the pool-gated photo cover). Assembled per cut
    # so the cover photo's saliency focus follows the format.
    cover_props = _reel_cover_props(cards_props, brand_dict, brand_kit)

    # svg-shape-decompose — opt-in logo draw-on for the cover/outro brand
    # scenes. Decompose the brand's OWN inline SVG into ordered per-path
    # draw-on data; ``None`` (opt-out OR an honest degrade — raster/circle-only
    # or an unsupported path command) keeps the static filled ``<img>`` and a
    # byte-identical cache key. Folded into props + cache key only when present.
    logo_drawon_payload = _decompose_logo_svg(_brand_logo_svg(brand_kit)) if logo_drawon else None

    if engine == "ffmpeg":
        from mediahub.visual import reel_ffmpeg

        return reel_ffmpeg.render_meet_reel_from_props(
            cards_props,
            brand_dict,
            brand_kit,
            out_path,
            meet_name=meet_name,
            duration_sec=duration_sec,
            brief_dicts=briefs_list,
            audio_plan=audio_plan,
            format_name=format_name,
            rhythm=rhythm,
            audio_notes=audio_notes,
            logo_drawon=logo_drawon,
            **_fps_kw(fps),
        )

    cache_payload = {
        "cards": cards_props,
        "brand": brand_dict,
        "meet": meet_name,
        "duration": duration_sec,
        "size": list(size),
        "rev": REEL_COMPOSITION_REVISION,
    }
    if rhythm:
        cache_payload["rhythm"] = rhythm
    if stat_config:
        cache_payload["reelStatConfig"] = stat_config
    if cta_props:
        cache_payload["cta"] = cta_props
    if cover_props:
        cache_payload["cover"] = cover_props
    # svg-shape-decompose: fold the decomposed logo paths ONLY when the draw-on
    # is active (opt-in + successful decompose), so every reel rendered without
    # it keeps a byte-identical cache key.
    if logo_drawon_payload:
        cache_payload["logoDrawOn"] = logo_drawon_payload
    if audio_plan:
        cache_payload["audio"] = audio_plan
    # M21: per-card edit-recipe signatures, folded only when any card's photo
    # actually carries an edit (unedited reels keep byte-identical keys).
    edit_sigs = [_photo_edit_signature_for_brief(b) for b in briefs_list]
    if any(edit_sigs):
        cache_payload["photo_edits"] = edit_sigs
    # M23: per-beat footage fingerprints + trim windows, folded ONLY when at
    # least one beat resolved a clip (footage-free reels keep byte-identical keys).
    footage_list = list(footage_list or [])
    if any(f is not None for f, _ in footage_list):
        cache_payload["footage"] = [
            (f.cache_sig if f is not None else None) for f, _ in footage_list
        ]
    # Supersample folds in only when active, so a default (1x) reel keeps its
    # byte-identical cache key; a 2x reel keys independently.
    if supersample > 1.0:
        cache_payload["supersample"] = supersample
    # true-motion-blur: the reel-level shutter-accumulation axis. Folded ONLY when
    # active (mblur is not None) so a blurred reel can never be served from — or
    # overwrite — an un-blurred cache entry, and the default reel key is untouched.
    # Reel-level (not per-card), so it needs its own fold: cards_props stay
    # byte-identical, and each distinct (samples, shutter) keys independently.
    if mblur is not None:
        cache_payload["motionBlur"] = mblur
    # fps-option: fold the frame rate only for a non-default choice, so the
    # default (30fps) reel cache key is byte-identical to before.
    if int(fps) != MOTION_FPS:
        cache_payload["fps"] = int(fps)
    # per-effect-toggle (REVIEW-ONLY A/B): a distinct top-level marker so the
    # comparison "B" reel can never collide with, or perturb, the default reel
    # key. Set ONLY on the validated review path; a shipped reel is untouched.
    if ab_disabled:
        cache_payload["ab_review"] = ab_disabled
    # alpha-export: fold the transparent-export profile under a distinct ``alpha``
    # key when active, so an alpha reel can never be served from — or overwrite —
    # an opaque cache entry, and the default reel key is untouched.
    # bit-depth-gamut: fold the profile NAME only when active, so a 10-bit/tagged
    # reel can never be served from an 8-bit cache entry and the default (encode
    # is None) reel key stays byte-identical. Mutually exclusive (alpha overrode
    # encode above) — exactly one fold fires.
    if alpha_prof is not None:
        cache_payload["alpha"] = alpha_prof.key
    elif encode is not None:
        cache_payload["encode"] = encode["name"]
    cache_key = _content_hash(cache_payload, kind="reel")
    # Container-aware cached slot: opaque reels are .mp4; an alpha reel writes the
    # profile's .mov/.webm slot (the alpha key already differs, so no collision).
    cached = _cache_dir() / f"{cache_key}{encode['container'] if encode else '.mp4'}"
    if cached.exists() and cached.stat().st_size > 1024:
        _touch_cache_hit(cached)  # LRU recency (#71)
        audio_rec = _finish_cached_video(
            cached,
            kind="reel",
            plan=audio_plan,
            duration_sec=duration_sec,
            n_cards=len(cards_props),
            rhythm=rhythm,
            audio_notes=audio_notes,
        )
        audio_rec.pop("poster_source", "")
        if audio_plan:
            _update_manifest_audio(cached, audio_rec)
        return _publish(cached, out_path)

    # R1.30 outro-CTA props (sponsor / next meet) ride into reel_props so BOTH
    # the parallel (R1.28) and the serial render path carry them. R1.12 — the
    # rhythm is attached ONLY when customised, so the default render's props
    # (and thus the bundle hash) stay byte-identical to before either feature.
    reel_props = {
        "cards": cards_props,
        "brand": brand_dict,
        "meetName": meet_name,
        **cta_props,
        **cover_props,
    }
    if rhythm:
        reel_props["rhythm"] = rhythm
    if stat_config:
        reel_props["reelStatConfig"] = stat_config
    # alpha-export: drive the CoverScreen/OutroScreen ground suppression via the
    # reel-level prop (the per-card beats already carry their own transparentBg).
    # Attach-only, so a non-alpha reel's props (and bundle hash) stay byte-identical.
    if alpha_prof is not None:
        reel_props["transparentBg"] = True
    # svg-shape-decompose: pass the decomposed logo paths into the reel props
    # ONLY when active, so the default reel's props (and thus the bundle hash)
    # stay byte-identical. The zod defaults (logoDrawOn:false, logoPaths:[])
    # make the composition's inactive DOM the exact filled ``<img>``.
    if logo_drawon_payload:
        reel_props["logoDrawOn"] = True
        reel_props["logoViewBox"] = logo_drawon_payload["viewBox"]
        reel_props["logoPaths"] = logo_drawon_payload["paths"]
    # true-motion-blur: pass the reel-level shutter-accumulation config into the
    # reel props ONLY when active, so the default reel's props (and thus the bundle
    # hash) stay byte-identical. The composition wraps the whip flick AND threads
    # this down to each <StoryCard> beat's entrance/count-up as a dedicated prop
    # (never via cards_props, which stays byte-identical). The zod
    # ``motionBlur.optional()`` default (absent => undefined) keeps the inactive
    # DOM the exact current whip feGaussianBlur + unwrapped beats.
    if mblur is not None:
        reel_props["motionBlur"] = mblur
    # Cold render. Try the opt-in parallel composition path (R1.28) first: it
    # splits the reel's frames across concurrent segment renders and composites
    # them into a byte-equivalent silent reel, cutting wall-clock on multi-core
    # workers. It returns None — and we take the unchanged serial render — when
    # disabled, unavailable, or on any failure.
    render_strategy = "serial"
    # Supersample forces the serial path: the parallel-segment composite doesn't
    # thread the --scale/downscale, so it's skipped when supersampling (an
    # unchanged 1x reel still tries parallel first). bit-depth-gamut: an active
    # encode profile forces serial too — the parallel composite stream-copies its
    # h264 segments and threads no codec/pixelFormat/colorSpace, so it cannot
    # produce the profile output; only the serial _run_remotion carries encode=.
    if (
        encode is None
        and supersample <= 1.0
        and (
            _render_reel_parallel_or_none(
                props=reel_props,
                cached=cached,
                duration_sec=duration_sec,
                size=size,
                **_fps_kw(fps),
            )
            is not None
        )
    ):
        render_strategy = "parallel-segments"
    else:
        _run_remotion(
            composition_id=COMP_REEL,
            props=reel_props,
            out_path=cached,
            duration_sec=duration_sec,
            size=size,
            supersample=supersample,
            **_encode_kw(encode),
            **_fps_kw(fps),
        )
    audio_rec = _finish_cached_video(
        cached,
        kind="reel",
        plan=audio_plan,
        duration_sec=duration_sec,
        n_cards=len(cards_props),
        rhythm=rhythm,
        audio_notes=audio_notes,
    )
    poster_source = audio_rec.pop("poster_source", "")
    from mediahub.visual.audio_mux import poster_path_for

    # M23 explainability: per-beat footage provenance / honest fall-back
    # reasons, recorded only when there is something to say.
    reel_footage_manifest = [
        (f.provenance if f is not None else {"used": False, "reason": r or ""})
        for f, r in footage_list
    ]
    _write_render_manifest(
        cached,
        {
            "kind": "reel",
            "engine": engine,
            "render_strategy": render_strategy,
            **({"supersample": supersample} if supersample > 1.0 else {}),
            # alpha-export: honest transparent-export record (fold-only-when-active,
            # mutually exclusive with the encode block below).
            **({"alpha": _alpha_manifest(alpha_prof)} if alpha_prof is not None else {}),
            # bit-depth-gamut: honest encode-profile record (fold-only-when-active).
            # Same brand-locked, APCA-gated colours re-encoded at higher bit-depth
            # precision + gamut-tagged — not a synthesised wide-gamut master.
            **(
                {
                    "encode": {
                        "profile": encode["name"],
                        "codec": encode["codec"],
                        "pixel_format": encode["pixelFormat"],
                        "color_space": encode.get("colorSpace") or "untagged",
                        "note": (
                            "Higher-bit-depth/gamut-tagged re-ENCODE of the same "
                            "brand-locked, APCA-gated colours. Source frames are "
                            "Chromium 8-bit sRGB; 10-bit reduces encode banding and "
                            "colorSpace tags the container — a precision + metadata "
                            "change, not a synthesised wide-gamut master. bt2020-ncl "
                            "is a HLG/2020 re-tag + limited-range matrix relabel over "
                            "sRGB-origin pixels (not a true gamut map): a tonemapping "
                            "player that honours the tag may display it differently "
                            "from the approved still."
                        ),
                    },
                    **(
                        {
                            "supersample": {
                                "requested": _motion_supersample(),
                                "applied": False,
                                "reason": "incompatible with encode profile "
                                "(10-bit downscale unsupported)",
                            }
                        }
                        if _motion_supersample() > 1.0
                        else {}
                    ),
                }
                if (encode is not None and alpha_prof is None)
                else {}
            ),
            # transform-sampling (AE-gap): honest per-photo hint record — a
            # best-effort compositor interpolation hint on the beats' scaled
            # photos, NOT a guaranteed dense-buffer supersample.
            **(
                {
                    "photoSupersample": {
                        "factor": photo_ss,
                        "kind": "best-effort-hint",
                        "note": "imageRendering:auto on scaled photos; guaranteed "
                        "dense-buffer supersample is the whole-composition "
                        "MEDIAHUB_MOTION_SUPERSAMPLE",
                    }
                }
                if photo_ss > 0
                else {}
            ),
            # true-motion-blur: honest reel-level shutter-accumulation record —
            # the sample count is the per-frame cost multiplier and the scope is
            # bounded to the whip flick + each beat's settling entrance/count-up
            # (the photo camera / parallax are NOT sampled, so held frames stay
            # the approved stills). Fold-only-when-active.
            **(
                {
                    "motionBlur": {
                        "samples": mblur["samples"],
                        "shutter": mblur["shutter"],
                        "scope": "whip+entrance+count_up",
                        "note": (
                            "Real multi-sample shutter accumulation: the whip "
                            "transition's lateral flick and each beat's settling "
                            "hero/result entrance + count-up are recomputed at "
                            "%d deterministic sub-frames across a %g-degree shutter "
                            "and composited with equal-weight progressive alpha "
                            "(frame-pure, no @remotion/motion-blur). The perpetual "
                            "photo camera / parallax are NOT sampled, so terminal "
                            "held frames collapse to the approved stills. Cost "
                            "scales with the sample count." % (mblur["samples"], mblur["shutter"])
                        ),
                    }
                }
                if mblur is not None
                else {}
            ),
            "format": format_name,
            "composition_revision": REEL_COMPOSITION_REVISION,
            "size": list(size),
            "duration_sec": duration_sec,
            "fps": int(fps),
            "meet_name": meet_name,
            "rhythm": rhythm or "default",
            "cta": cta_props,
            # M18 — the bookend treatment, without the photo bytes.
            "cover": {
                "roles_source": "brand-resolved"
                if cover_props.get("coverRoleGround")
                else "legacy-pairing",
                "role_ground": cover_props.get("coverRoleGround", ""),
                "role_accent": cover_props.get("coverRoleAccent", ""),
                "role_on_ground": cover_props.get("coverRoleOnGround", ""),
                "typography": cover_props.get("coverTypography", ""),
                "has_photo": bool(cover_props.get("coverPhotoSrc")),
            },
            "cards": [_card_manifest_axes(cp) for cp in cards_props],
            "stat_config": stat_config or "default",
            # svg-shape-decompose: honest provenance of the logo draw-on, folded
            # only when active — how many of the brand's OWN paths draw on.
            **(
                {
                    "logo_drawon": {
                        "paths": len(logo_drawon_payload["paths"]),
                        "view_box": logo_drawon_payload["viewBox"],
                    }
                }
                if logo_drawon_payload
                else {}
            ),
            "audio": audio_rec,
            "captions": _reel_caption_manifest(cards_props),
            "poster": poster_path_for(cached).name if poster_path_for(cached).exists() else "",
            "poster_source": poster_source,
            **(
                {"footage": reel_footage_manifest}
                if any(entry.get("used") or entry.get("reason") for entry in reel_footage_manifest)
                else {}
            ),
        },
    )
    _prune_motion_cache()  # bound the cache after a cold write (#71)
    published = _publish(cached, out_path)
    return published if published.exists() else cached


def render_meet_reel(
    top_cards: list[dict],
    brand_kit: Any,
    out_path: Path,
    *,
    meet_name: str = "",
    duration_sec: Optional[float] = None,
    briefs: Optional[list[Optional[dict]]] = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
    sponsor: str = "",
    next_meet: str = "",
    rhythm: Optional[dict] = None,
    dub_language: str = "",
    reel_stat_config: Optional[dict] = None,
    fps: int = MOTION_FPS,
    review_ab: Optional[list[str]] = None,
    logo_drawon: bool = False,
    peak_speed_ramp: str = "",
    alpha_profile: str = "",
) -> Path:
    """Render a multi-card reel from the top cards for a meet.

    Inputs:
      top_cards   list of card dicts (typically the top 3 from the content
                  pack). Each card is shaped via ``_card_to_props``.
      brand_kit   BrandKit or dict; applies palette, club name, logo hint.
      out_path    where the final MP4 should land. Cached results may be
                  copied here from the motion cache.
      meet_name   meet headline used on the reel cover. Defaults to the
                  first card's ``meet_name`` if blank.
      duration_sec explicit total reel duration. Default ``None`` =
                  data-driven: ``reel_duration_for(len(top_cards))`` folded with
                  ``rhythm``, so the reel's structure follows the number of
                  ranked moments (1 card → 7s … 5 cards → 23s; 3 cards keep the
                  historic 15s) unless customised.
      format_name  output cut: ``story`` (default) / ``portrait`` /
                  ``square`` / ``landscape``, or a validated arbitrary-canvas
                  ``"WxH"`` token (any-canvas — exposed on the routes as
                  ``?w=&h=`` / ``?size=WxH``). A custom size keys its own cache
                  entry via the folded ``size`` list; presets stay byte-identical.
      sponsor     optional sponsor name for the reel's outro close (R1.30).
                  When set, the Remotion outro shows a "proudly supported by"
                  thank-you; blank falls back to the follow-the-club close.
                  Only ever names a sponsor the caller actually supplied.
      next_meet   optional next-meet label for the outro "next up" close
                  (R1.30). Sponsor wins when both are given; the next meet
                  then rides along as the outro's secondary line.
      rhythm      optional beat-rhythm & duration customisation (R1.12) — a
                  dict understood by ``normalise_reel_rhythm`` (custom
                  ``cover``/``outro``/``per_card`` seconds and/or per-card
                  ``weights``). ``None`` or an effectively-default request keeps
                  today's exact skeleton and cache key.
      reel_stat_config  optional cover stat-chip config (R1.13) — a dict
                  understood by ``normalise_reel_stat_config`` (``include``
                  ids from ``REEL_STAT_IDS``, ``max`` cap, ``labels`` wording
                  overrides). Only selects/renames the honest counted chips,
                  never the numbers. ``None``/empty keeps the default cover
                  and cache key byte-identical; an unknown id raises
                  ``ValueError``.

    Audio + poster behaviour matches ``render_story_card``: opt-in narration
    (built only from the cards' own facts) and/or the operator's music bed
    are mixed in when configured, with an honest silent fallback, and a
    poster-frame PNG sidecar lands beside the MP4.

    ``fps`` selects the output frame rate from the curated ``ALLOWED_FPS`` set
    (default 30, byte-identical); a non-default rate folds into the cache key
    and re-times the render across the serial, parallel and ffmpeg engines.

    ``review_ab`` (per-effect-toggle, REVIEW-ONLY) mirrors ``render_story_card``:
    an opt-in list of decorative axes to SUPPRESS on every card beat for a
    with/without comparison reel, validated against ``EFFECT_TOGGLE_ALLOWLIST``
    and keyed distinctly (``ab_review``) so the default reel's key/bytes are
    untouched. The cover/outro keep their full treatment (they are not per-card
    axes). ``None`` — and an all-unknown list — render byte-identically.

    ``logo_drawon`` (svg-shape-decompose) opts the reel's cover + outro brand
    scenes into a per-path SVG stroke draw-on: the club's OWN logo paths trace
    on then cross-fade into the exact filled logo. Decomposed deterministically
    from the brand's inline SVG; a raster / circle-only / unsupported-command
    logo degrades honestly to the static ``<img>``. ``False`` (default) — and
    any logo that can't decompose — keeps the reel byte-identical, folding
    nothing into the cache key. The free FFmpeg engine reports it unsupported.

    ``peak_speed_ramp`` (speed-ramp, opt-in) bakes a decelerate-into-the-beat
    ramp onto the reel's PEAK beat (the #1 ranked card) via ffmpeg ``setpts`` —
    a server-only field kept OUT of the Remotion-bound rhythm dict. ``""`` (the
    default) keeps every footage beat byte-identical.

    For every cut in one request, see ``render_meet_reel_all_formats``.
    """
    fps = _validate_fps(fps)
    engine = _dispatch_engine()
    # Validate the stat-chip config up front so a typo fails loudly before any
    # expensive photo-embed/prop work.
    stat_config = normalise_reel_stat_config(reel_stat_config)
    (
        cards_props,
        brand_dict,
        meet_name,
        duration_sec,
        audio_plan,
        briefs_list,
        rhythm_norm,
        audio_notes,
        footage_list,
    ) = _assemble_reel_props(
        top_cards,
        brand_kit,
        meet_name=meet_name,
        duration_sec=duration_sec,
        briefs=briefs,
        rhythm=rhythm,
        dub_language=dub_language,
        resolve_footage=engine != "ffmpeg",
        peak_speed_ramp=peak_speed_ramp,
        fps=fps,
    )
    cta_props = _reel_cta_props(sponsor, next_meet)
    return _render_reel_one_format(
        cards_props=cards_props,
        brand_dict=brand_dict,
        brand_kit=brand_kit,
        meet_name=meet_name,
        duration_sec=duration_sec,
        audio_plan=audio_plan,
        briefs_list=briefs_list,
        cta_props=cta_props,
        engine=engine,
        format_name=format_name,
        out_path=out_path,
        rhythm=rhythm_norm,
        audio_notes=audio_notes,
        stat_config=stat_config,
        footage_list=footage_list,
        fps=fps,
        review_ab=review_ab,
        logo_drawon=logo_drawon,
        alpha_profile=alpha_profile,
    )


def reel_format_out_path(
    out_dir: Path, format_name: str, *, base_name: str = "reel", container_ext: str = "mp4"
) -> Path:
    """Resolve one cut's output path under ``out_dir``.

    The ``story`` cut keeps the bare ``<base_name>.mp4`` filename (so existing
    links and cached artifacts stay valid); every other cut is suffixed
    ``<base_name>_<format>.mp4``. Mirrors the naming the reel routes already
    use (``reel_<n>.mp4`` / ``reel_<n>_<fmt>.mp4``), so the batch writes the
    exact files the ``reel-file`` route serves.

    ``container_ext`` (alpha-export) swaps the ``.mp4`` extension for a
    transparent-export container (``mov``/``webm``); the default ``"mp4"`` keeps
    every existing name byte-identical.
    """
    motion_format_size(format_name)  # validate the name (raises on unknown)
    stem = base_name if format_name == DEFAULT_MOTION_FORMAT else f"{base_name}_{format_name}"
    return Path(out_dir) / f"{stem}.{container_ext.lstrip('.')}"


def render_meet_reel_all_formats(
    top_cards: list[dict],
    brand_kit: Any,
    out_dir: Path,
    *,
    meet_name: str = "",
    duration_sec: Optional[float] = None,
    briefs: Optional[list[Optional[dict]]] = None,
    formats: Optional[list[str]] = None,
    base_name: str = "reel",
    render_slot: Optional[Callable[[str], ContextManager]] = None,
    sponsor: str = "",
    next_meet: str = "",
    rhythm: Optional[dict] = None,
    dub_language: str = "",
    reel_stat_config: Optional[dict] = None,
    fps: int = MOTION_FPS,
    logo_drawon: bool = False,
    peak_speed_ramp: str = "",
    alpha_profile: str = "",
) -> dict[str, Any]:
    """Render + cache every requested reel format in a single pass (R1.15).

    One call shapes the cards' props once (photos embedded, saliency + colour
    roles resolved, audio plan + captions built — the expensive,
    format-independent work) and then renders each cut from those shared props.
    Cuts already in the motion cache are reused, so a story reel rendered
    earlier by the single route is a cache hit here and only the missing cuts
    cost a render. Each cut carries main's R1.28 parallel path, R1.30 outro CTA,
    R1.19 audio-mix and R1.3 captions identically to ``render_meet_reel``.

    Inputs mirror ``render_meet_reel`` plus:
      out_dir     directory the cuts are written into; each format's filename
                  comes from ``reel_format_out_path`` (story keeps the bare
                  ``<base_name>.mp4``; others are ``<base_name>_<fmt>.mp4``).
      formats     which cuts to produce; defaults to all of ``MOTION_FORMATS``
                  in declaration order. Unknown names raise ``ValueError``.
      base_name   filename stem (the route passes ``reel_<n>`` so the cuts land
                  exactly where the ``reel-file`` route looks).
      render_slot optional ``fmt -> context manager`` factory entered around
                  each cut's render, so a long batch on a single-slot box
                  yields the render gate between cuts instead of hogging it
                  for the whole multi-minute run.

    Returns a structured result so the caller can report honestly per cut::

        {
          "engine":   "remotion" | "ffmpeg",
          "rendered": {fmt: Path, ...},     # cuts produced, MOTION_FORMATS order
          "errors":   {fmt: reason, ...},   # cuts that could not be produced
        }

    A cut that the active engine cannot produce (e.g. the ffmpeg fallback's
    non-story cuts) is recorded in ``errors`` with the honest reason and never
    fakes an output; it does not abort the cuts that *can* render. A genuine
    render failure on one cut is likewise captured per-cut so a partial batch
    still ships what succeeded. The order of ``rendered`` follows
    ``MOTION_FORMATS`` for stable, predictable output.
    """
    fps = _validate_fps(fps)
    engine = _dispatch_engine()

    requested = list(formats) if formats else list(MOTION_FORMATS)
    # Validate up front so a typo fails loudly before any render work.
    for fmt in requested:
        motion_format_size(fmt)
    stat_config = normalise_reel_stat_config(reel_stat_config)
    # Render in canonical MOTION_FORMATS order regardless of request order,
    # de-duplicated, so the result is stable and story (the cheapest reuse) is
    # produced first.
    ordered = [f for f in MOTION_FORMATS if f in set(requested)]

    (
        cards_props,
        brand_dict,
        meet_name,
        duration_sec,
        audio_plan,
        briefs_list,
        rhythm_norm,
        audio_notes,
        footage_list,
    ) = _assemble_reel_props(
        top_cards,
        brand_kit,
        meet_name=meet_name,
        duration_sec=duration_sec,
        briefs=briefs,
        rhythm=rhythm,
        dub_language=dub_language,
        resolve_footage=engine != "ffmpeg",
        peak_speed_ramp=peak_speed_ramp,
        fps=fps,
    )
    cta_props = _reel_cta_props(sponsor, next_meet)

    out_dir = Path(out_dir)
    # alpha-export: every cut in the batch inherits the transparent profile; the
    # cut filenames carry the profile's .mov/.webm container so they match the
    # reel-file route's alpha-aware naming.
    alpha_prof = resolve_alpha_profile(alpha_profile)
    _cut_ext = alpha_prof.ext if alpha_prof else "mp4"
    rendered: dict[str, Path] = {}
    errors: dict[str, str] = {}
    for fmt in ordered:
        out_path = reel_format_out_path(out_dir, fmt, base_name=base_name, container_ext=_cut_ext)
        slot_cm: ContextManager = render_slot(fmt) if render_slot else contextlib.nullcontext()
        try:
            with slot_cm:
                rendered[fmt] = _render_reel_one_format(
                    cards_props=cards_props,
                    brand_dict=brand_dict,
                    brand_kit=brand_kit,
                    meet_name=meet_name,
                    duration_sec=duration_sec,
                    audio_plan=audio_plan,
                    briefs_list=briefs_list,
                    cta_props=cta_props,
                    engine=engine,
                    format_name=fmt,
                    out_path=out_path,
                    rhythm=rhythm_norm,
                    audio_notes=audio_notes,
                    stat_config=stat_config,
                    footage_list=footage_list,
                    fps=fps,
                    logo_drawon=logo_drawon,
                    alpha_profile=alpha_profile,
                )
        except ReelEngineUnavailable as e:
            # Expected capability gap (e.g. ffmpeg can't do non-story) —
            # record the honest reason, keep producing the cuts that can run.
            errors[fmt] = str(e)
        except Exception as e:
            # A genuine render failure on one cut must not lose the cuts that
            # already succeeded — capture it and carry on.
            errors[fmt] = str(e)

    _write_batch_manifest(
        out_dir,
        base_name=base_name,
        engine=engine,
        meet_name=meet_name,
        duration_sec=duration_sec,
        n_cards=len(cards_props),
        rendered=rendered,
        errors=errors,
    )

    return {"engine": engine, "rendered": rendered, "errors": errors}


def _write_batch_manifest(
    out_dir: Path,
    *,
    base_name: str,
    engine: str,
    meet_name: str,
    duration_sec: float,
    n_cards: int,
    rendered: dict[str, Path],
    errors: dict[str, str],
) -> None:
    """Persist the batch's explainability record beside the cuts it produced.

    A small ``<base_name>.batch.json`` sidecar answering "which cuts did this
    one request produce, and why is any cut missing?" — best-effort, never
    fails (or follows) the renders it summarises.
    """
    try:
        formats: dict[str, dict] = {}
        for fmt in MOTION_FORMATS:
            if fmt in rendered:
                w, h = motion_format_size(fmt)
                formats[fmt] = {
                    "status": "ok",
                    "file": Path(rendered[fmt]).name,
                    "size": [w, h],
                }
            elif fmt in errors:
                formats[fmt] = {"status": "unavailable", "reason": errors[fmt]}
        manifest = {
            "kind": "reel-batch",
            "engine": engine,
            "meet_name": meet_name,
            "duration_sec": duration_sec,
            "n_cards": n_cards,
            "rendered": [f for f in MOTION_FORMATS if f in rendered],
            "formats": formats,
        }
        sidecar = Path(out_dir) / f"{base_name}.batch.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


__all__ = [
    "render_story_card",
    "render_meet_reel",
    "render_meet_reel_all_formats",
    "reel_format_out_path",
    "reel_duration_for",
    "normalise_reel_rhythm",
    "motion_format_size",
    "validate_canvas_size",
    "canonical_motion_format",
    "MOTION_FORMATS",
    "DEFAULT_MOTION_FORMAT",
    "ALPHA_PROFILES",
    "resolve_alpha_profile",
    "AlphaUnsupportedError",
    "node_available",
    "remotion_installed",
    "REMOTION_DIR",
    "ReelEngineUnavailable",
]


# Re-exported for tests; underscore-prefixed names are intentionally not in
# __all__ but stay importable as ``from mediahub.visual.motion import _logo_to_data_uri``.
