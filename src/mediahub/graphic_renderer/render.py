"""Playwright HTML→PNG renderer.

Takes a CreativeBrief + format size + asset paths, fills the appropriate HTML
template, and screenshots a real PNG via headless Chromium.

Design notes
------------
- Templates live in ``graphic_renderer/layouts/*.html`` and use ``{{PLACEHOLDER}}``
  string substitution (intentionally not Jinja, to avoid yet another dep).
- The shared ``_base.css`` is inlined into every template via the ``{{BASE_CSS}}``
  placeholder. Google Fonts are imported once at the top of every page.
- A water-pattern + noise-pattern are generated as data-URI SVG/PNGs and inlined
  via CSS variables, so the render is fully self-contained — no network
  required at screenshot time.
- Cutouts are produced by the providers (rembg / replicate) and base64-embedded
  into the HTML so Playwright never has to fetch a local file.

Public API
----------
- ``render_brief(brief, *, athlete_path=None, venue_path=None, output_dir,
                 size=(1080,1350), format_name="feed_portrait", logo_path=None)``
  → returns a ``RenderResult`` with the on-disk PNG path + GeneratedVisual record.
- ``render_html_to_png(html, output_path, size)`` → low-level helper.
"""

from __future__ import annotations

import atexit
import base64
import logging
import os
import queue
import re
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future
from concurrent.futures import TimeoutError as _FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from . import render_cache as _render_cache
from .sprint_hooks import RenderHookCtx as _RenderHookCtx
from .sprint_hooks import apply_render_hooks as _apply_render_hooks

log = logging.getLogger(__name__)

# Optional: PIL only if needed for size sanity / fallbacks.
try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore

LAYOUTS_DIR = Path(__file__).parent / "layouts"
_BASE_CSS_PATH = LAYOUTS_DIR / "_base.css"
_TEXT_LED_FILL_CSS_PATH = LAYOUTS_DIR / "_text_led_fill.css"
_SHARED_CSS_PATH = LAYOUTS_DIR / "_shared.css"


# ---------------------------------------------------------------------------
# V8.1 Issue 7 — feature flags (env-driven so tests + ops can toggle)
# ---------------------------------------------------------------------------


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "", "false", "no", "off")


def _grain_enabled() -> bool:
    return _flag("MEDIAHUB_RENDER_GRAIN", "1")


def _gen_bg_enabled() -> bool:
    """Tier C generative backgrounds (SEQ-4): opt-IN, default OFF.

    ``MEDIAHUB_GEN_BG=1`` switches the Imagen background fetch on — it is a
    billed API call, so it must never spend without the operator's say-so.
    The legacy ``MEDIAHUB_DISABLE_AI_BG=1`` kill switch still wins.
    """
    if os.environ.get("MEDIAHUB_DISABLE_AI_BG", "0") == "1":
        return False
    return _flag("MEDIAHUB_GEN_BG", "0")


# ---------------------------------------------------------------------------
# G1.14 — render quality profiles + WebP/AVIF output.
#
# A *quality profile* bundles the two knobs that trade render speed against
# output fidelity: the screenshot device-pixel-ratio (sharper text/gradients
# at higher DPR, but a bigger capture to resample) and the encoder settings for
# each still format. Three named profiles cover the useful range — ``fast`` for
# quick previews, ``standard`` (the historic default) for posts, ``high`` for
# print-adjacent crispness. The active profile is chosen by
# ``MEDIAHUB_RENDER_QUALITY``; an explicit ``MEDIAHUB_RENDER_DPR`` still wins for
# DPR so existing ops/tuning keeps working.
#
# The encode step is deliberately deterministic (no AI, no heuristics): a fixed
# suffix→format map and fixed per-profile encoder params, so the same HTML at
# the same profile always produces the same bytes for a given Pillow build. The
# canonical rendered artifact stays a target-size PNG (so the G1.23 pool and the
# G1.24 PNG cache keep working unchanged); WebP/AVIF/JPEG are a cheap transcode
# of that PNG in the dispatcher.
# ---------------------------------------------------------------------------


class RenderEncodeError(RuntimeError):
    """Raised when a requested still format cannot be honestly produced.

    We never write a mislabelled file (e.g. PNG bytes under a ``.avif`` name)
    or silently downgrade the format the caller asked for — if the deployment's
    Pillow can't encode the requested codec, the operator gets a clear error
    instead of a lie on disk.
    """


@dataclass(frozen=True)
class QualityProfile:
    """A render quality tier: screenshot DPR + per-format encoder settings.

    ``dpr`` is the device-pixel-ratio used at screenshot time (the capture is
    then resampled back down to the target canvas with Lanczos). The remaining
    fields are encoder knobs: ``webp_quality``/``webp_method`` (0-100 / 0-6),
    ``avif_quality``/``avif_speed`` (0-100 / 0-10, higher speed = faster &
    lossier), ``jpeg_quality`` (0-100), and ``png_optimize`` (zlib effort).
    """

    name: str
    dpr: int
    webp_quality: int
    webp_method: int
    avif_quality: int
    avif_speed: int
    jpeg_quality: int
    png_optimize: bool


# The three tiers. ``standard`` reproduces the historic render exactly (DPR 2,
# optimised PNG) so today's posts are byte-identical; ``fast`` halves the
# capture and skips the slow encoder passes; ``high`` triples the capture and
# spends the most encoder effort for the crispest result.
_QUALITY_PROFILES: dict[str, QualityProfile] = {
    "fast": QualityProfile(
        name="fast",
        dpr=1,
        webp_quality=80,
        webp_method=2,
        avif_quality=55,
        avif_speed=8,
        jpeg_quality=82,
        png_optimize=False,
    ),
    "standard": QualityProfile(
        name="standard",
        dpr=2,
        webp_quality=90,
        webp_method=4,
        avif_quality=65,
        avif_speed=6,
        jpeg_quality=90,
        png_optimize=True,
    ),
    "high": QualityProfile(
        name="high",
        dpr=3,
        webp_quality=95,
        webp_method=6,
        avif_quality=82,
        avif_speed=3,
        jpeg_quality=95,
        png_optimize=True,
    ),
}

_DEFAULT_QUALITY = "standard"

# Output still formats, keyed by the lowercase file suffix the caller writes to.
# The value is the Pillow format string passed to ``Image.save``. PNG is the
# default and the only lossless option; WEBP/AVIF are the G1.14 additions; JPEG
# rides along for free (and feeds the EXIF/print siblings).
_ENCODE_FORMATS: dict[str, str] = {
    ".png": "PNG",
    ".webp": "WEBP",
    ".avif": "AVIF",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
}

# Reverse map: Pillow format string → canonical lowercase extension, used by
# callers (``render_brief``) to name the output file for a chosen format.
_FORMAT_EXTENSIONS: dict[str, str] = {
    "PNG": "png",
    "WEBP": "webp",
    "AVIF": "avif",
    "JPEG": "jpg",
}


def _quality_profile(name: str | None = None) -> QualityProfile:
    """Resolve the active quality profile.

    ``name`` (or ``MEDIAHUB_RENDER_QUALITY`` when ``name`` is None) selects the
    tier; an unknown/blank value falls back to ``standard`` so a typo degrades
    to the safe default rather than erroring mid-render.
    """
    key = (
        (name if name is not None else os.environ.get("MEDIAHUB_RENDER_QUALITY", ""))
        .strip()
        .lower()
    )
    return _QUALITY_PROFILES.get(key, _QUALITY_PROFILES[_DEFAULT_QUALITY])


def _coerce_profile(quality) -> QualityProfile:
    """Normalise a caller-supplied profile (a name, a QualityProfile, or None)."""
    if isinstance(quality, QualityProfile):
        return quality
    if isinstance(quality, str) and quality.strip():
        return _quality_profile(quality)
    return _quality_profile()


def _dpr_render() -> int:
    """Device-pixel-ratio used at screenshot time.

    An explicit ``MEDIAHUB_RENDER_DPR`` always wins (clamped to 1..4) so existing
    ops tuning and tests keep their exact behaviour. With it unset/blank the DPR
    comes from the active quality profile (``standard`` → 2, matching the historic
    default); an invalid explicit value also falls back to the profile DPR.
    """
    raw = os.environ.get("MEDIAHUB_RENDER_DPR")
    if raw is not None and raw.strip() != "":
        try:
            return max(1, min(4, int(raw)))
        except Exception:
            return _quality_profile().dpr
    return _quality_profile().dpr


def _resolve_image_format(explicit: str | None, output_path: "str | Path") -> str:
    """Return the Pillow format string for the output.

    An ``explicit`` format name (``"webp"``, ``".avif"``, ``"PNG"`` …) wins;
    otherwise the format is inferred from the output path's suffix. An unknown
    explicit name is a hard error (the caller asked for something we don't do);
    an unknown *suffix* defaults to PNG (the historic behaviour for ``.png`` and
    anything else a caller happened to pass).
    """
    if explicit:
        key = "." + str(explicit).strip().lower().lstrip(".")
        fmt = _ENCODE_FORMATS.get(key)
        if fmt is None:
            raise RenderEncodeError(
                f"unsupported render image format {explicit!r}; "
                f"choose one of {sorted(set(_ENCODE_FORMATS.values()))}"
            )
        return fmt
    suffix = Path(output_path).suffix.lower()
    return _ENCODE_FORMATS.get(suffix, "PNG")


def _pil_can_encode(pil_format: str) -> bool:
    """True if the installed Pillow can encode ``pil_format``.

    PNG/JPEG are always present in Pillow; WEBP/AVIF are optional codecs whose
    availability we probe via ``PIL.features`` (falling back to the registered
    extension table). Used to turn an unavailable codec into an honest error
    rather than a corrupt/mislabelled file.
    """
    if pil_format in ("PNG", "JPEG"):
        return Image is not None
    if Image is None:
        return False
    feature = {"WEBP": "webp", "AVIF": "avif"}.get(pil_format)
    if feature is None:
        return True
    try:
        from PIL import features as _pil_features

        return bool(_pil_features.check(feature))
    except Exception:
        try:
            return pil_format in set(Image.registered_extensions().values())
        except Exception:
            return False


def _encode_image(img, pil_format: str, profile: QualityProfile) -> bytes:
    """Encode a PIL image to ``pil_format`` bytes under ``profile``.

    Deterministic: fixed encoder params per profile/format. JPEG drops alpha
    (it has none) by flattening to RGB; WEBP/AVIF keep the alpha channel. Raises
    ``RenderEncodeError`` if the codec isn't available so we never emit a
    mislabelled file.
    """
    from io import BytesIO

    if not _pil_can_encode(pil_format):
        raise RenderEncodeError(
            f"{pil_format} output was requested but this Pillow build cannot encode it; "
            f"install a Pillow with {pil_format} support or pick a supported format"
        )
    buf = BytesIO()
    if pil_format == "PNG":
        src = img if img.mode in ("RGBA", "RGB", "P", "L", "LA") else img.convert("RGBA")
        src.save(buf, format="PNG", optimize=profile.png_optimize)
    elif pil_format == "WEBP":
        src = img if img.mode in ("RGBA", "RGB") else img.convert("RGBA")
        src.save(buf, format="WEBP", quality=profile.webp_quality, method=profile.webp_method)
    elif pil_format == "AVIF":
        src = img if img.mode in ("RGBA", "RGB") else img.convert("RGBA")
        src.save(buf, format="AVIF", quality=profile.avif_quality, speed=profile.avif_speed)
    elif pil_format == "JPEG":
        src = img if img.mode == "RGB" else img.convert("RGB")
        src.save(
            buf,
            format="JPEG",
            quality=profile.jpeg_quality,
            optimize=profile.png_optimize,
            progressive=True,
        )
    else:  # pragma: no cover - guarded by _resolve_image_format
        raise RenderEncodeError(f"unsupported encode format: {pil_format}")
    return buf.getvalue()


_GRAIN_SVG_BLOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" '
    'style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">'
    "<defs>"
    '<filter id="grain" x="0%" y="0%" width="100%" height="100%">'
    # baseFrequency tuned for fine film-grain; numOctaves=2 keeps it cheap.
    '<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch" seed="7"/>'
    # Push values toward greys + drop alpha to 3%.
    '<feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0.03 0"/>'
    '<feComposite in2="SourceGraphic" operator="in"/>'
    "</filter>"
    "</defs>"
    "</svg>"
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class GeneratedVisual:
    """Persistent record of a rendered visual. Mirrors what we'll store in DB."""

    id: str
    brief_id: str
    content_item_id: str
    profile_id: str
    layout_template: str
    format_name: str
    width: int
    height: int
    file_path: str
    text_layers: dict[str, str]
    palette: dict[str, str]
    sourced_asset_ids: list[str]
    safety_notes: list[str]
    why_this_design: str
    confidence_label: str
    rendered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RenderResult:
    """Output of a single render — PNG path + visual record + html debug."""

    visual: GeneratedVisual
    html: str
    png_bytes: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 0, 0, 0


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


_BRAND_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _is_brand_hex(value) -> bool:
    """True only for a real 3- or 6-digit CSS hex colour.

    Used to decide whether a brief.palette role already carries a
    confirmed brand colour (which must win) versus an empty / sentinel
    slot the theme store may fill.
    """
    return isinstance(value, str) and bool(_BRAND_HEX_RE.match(value.strip()))


def darken(hex_colour: str, amount: float = 0.25) -> str:
    """Return a darker shade of the input hex colour (amount in [0..1])."""
    r, g, b = _hex_to_rgb(hex_colour)
    return _rgb_to_hex((r * (1 - amount), g * (1 - amount), b * (1 - amount)))


def lighten(hex_colour: str, amount: float = 0.25) -> str:
    r, g, b = _hex_to_rgb(hex_colour)
    return _rgb_to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


def _encode_img_data_uri(p: Path) -> str:
    """Read an image from disk and return a base64 ``data:`` URI (the raw work)."""
    raw = p.read_bytes()
    suffix = p.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "gif": "image/gif",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _img_to_data_uri(path: str | Path) -> str:
    """Read an image from disk, return a data: URI (PNG-ish).

    Routed through the G1.24 render cache (``render_cache.asset_data_uri``) so an
    unchanged file is read and base64-encoded once per process — the returned
    text is byte-identical to a direct encode. A genuine read error still
    surfaces, exactly as before, because the cache falls through to the encoder
    for any file it can't ``stat``.
    """
    return _render_cache.asset_data_uri(path, loader=_encode_img_data_uri)


# ----- Background generators (SVG data URIs, no network) -------------------


def _water_pattern_data_uri() -> str:
    """Subtle ripple pattern — repeating SVG."""
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='600' height='600' viewBox='0 0 600 600'>
  <defs>
    <radialGradient id='r' cx='50%' cy='50%' r='50%'>
      <stop offset='0%' stop-color='white' stop-opacity='0.20'/>
      <stop offset='100%' stop-color='white' stop-opacity='0'/>
    </radialGradient>
  </defs>
  <g fill='none' stroke='white' stroke-opacity='0.18' stroke-width='1.4'>
    <path d='M0 80 C 150 40, 300 120, 600 80'/>
    <path d='M0 200 C 150 160, 300 240, 600 200'/>
    <path d='M0 320 C 150 280, 300 360, 600 320'/>
    <path d='M0 440 C 150 400, 300 480, 600 440'/>
    <path d='M0 560 C 150 520, 300 600, 600 560'/>
  </g>
  <circle cx='150' cy='150' r='100' fill='url(#r)'/>
  <circle cx='450' cy='350' r='140' fill='url(#r)'/>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _noise_pattern_data_uri() -> str:
    """Tiny SVG turbulence — adds film-grain."""
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>
  <filter id='n'>
    <feTurbulence type='fractalNoise' baseFrequency='1.6' numOctaves='2' stitchTiles='stitch'/>
    <feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0'/>
  </filter>
  <rect width='100%' height='100%' filter='url(#n)' opacity='0.85'/>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


# ---------------------------------------------------------------------------
# Variation backgrounds — pick a pattern from the brief.background_style axis.
# Each returns a CSS ``url("data:image/svg+xml;base64,...")`` value that the
# templates plug into the ``--water-pattern`` CSS variable. The variable is
# rebadged for backwards compat but every layout reads the same slot, so
# every pattern works in every layout.
# ---------------------------------------------------------------------------


def _bg_halftone_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'>
  <g fill='white' fill-opacity='0.14'>
    <circle cx='40' cy='40' r='6'/><circle cx='120' cy='40' r='5'/>
    <circle cx='200' cy='40' r='4'/><circle cx='280' cy='40' r='3'/>
    <circle cx='360' cy='40' r='2.5'/>
    <circle cx='40' cy='120' r='6'/><circle cx='120' cy='120' r='5'/>
    <circle cx='200' cy='120' r='4'/><circle cx='280' cy='120' r='3'/>
    <circle cx='360' cy='120' r='2.5'/>
    <circle cx='40' cy='200' r='5.5'/><circle cx='120' cy='200' r='4.5'/>
    <circle cx='200' cy='200' r='3.5'/><circle cx='280' cy='200' r='2.5'/>
    <circle cx='360' cy='200' r='2'/>
    <circle cx='40' cy='280' r='5'/><circle cx='120' cy='280' r='4'/>
    <circle cx='200' cy='280' r='3'/><circle cx='280' cy='280' r='2'/>
    <circle cx='360' cy='280' r='1.5'/>
    <circle cx='40' cy='360' r='4'/><circle cx='120' cy='360' r='3'/>
    <circle cx='200' cy='360' r='2.5'/><circle cx='280' cy='360' r='2'/>
    <circle cx='360' cy='360' r='1.5'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_diagonal_stripes_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='600' height='600'>
  <g stroke='white' stroke-opacity='0.10' stroke-width='28'>
    <line x1='-100' y1='100' x2='700' y2='-300'/>
    <line x1='-100' y1='250' x2='700' y2='-150'/>
    <line x1='-100' y1='400' x2='700' y2='0'/>
    <line x1='-100' y1='550' x2='700' y2='150'/>
    <line x1='-100' y1='700' x2='700' y2='300'/>
    <line x1='-100' y1='850' x2='700' y2='450'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_radial_burst_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='800' height='800'>
  <defs>
    <radialGradient id='r' cx='50%' cy='50%' r='60%'>
      <stop offset='0%' stop-color='white' stop-opacity='0.30'/>
      <stop offset='40%' stop-color='white' stop-opacity='0.10'/>
      <stop offset='100%' stop-color='white' stop-opacity='0'/>
    </radialGradient>
    <radialGradient id='r2' cx='50%' cy='50%' r='60%'>
      <stop offset='0%' stop-color='white' stop-opacity='0'/>
      <stop offset='70%' stop-color='white' stop-opacity='0.06'/>
      <stop offset='100%' stop-color='white' stop-opacity='0.18'/>
    </radialGradient>
  </defs>
  <rect width='800' height='800' fill='url(#r2)'/>
  <circle cx='400' cy='400' r='280' fill='url(#r)'/>
  <g stroke='white' stroke-opacity='0.08' stroke-width='1.5' fill='none'>
    <circle cx='400' cy='400' r='180'/>
    <circle cx='400' cy='400' r='260'/>
    <circle cx='400' cy='400' r='340'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_geometric_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'>
  <g fill='white' fill-opacity='0.06'>
    <polygon points='0,0 200,0 100,200'/>
    <polygon points='200,0 400,0 300,200'/>
    <polygon points='0,400 200,400 100,200'/>
    <polygon points='200,400 400,400 300,200'/>
  </g>
  <g stroke='white' stroke-opacity='0.10' stroke-width='1' fill='none'>
    <polygon points='0,0 200,0 100,200'/>
    <polygon points='200,0 400,0 300,200'/>
    <polygon points='0,400 200,400 100,200'/>
    <polygon points='200,400 400,400 300,200'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_clean_data_uri() -> str:
    """No pattern, just an invisible 1x1 pixel — leaves the canvas clean
    so the gradient + vignette do all the lifting."""
    svg = "<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'></svg>"
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_vertical_stripes_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='200' height='400'>
  <g fill='white' fill-opacity='0.07'>
    <rect x='0'   y='0' width='40' height='400'/>
    <rect x='80'  y='0' width='40' height='400'/>
    <rect x='160' y='0' width='40' height='400'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_dots_data_uri() -> str:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>
  <g fill='white' fill-opacity='0.18'>
    <circle cx='20'  cy='20'  r='2.2'/>
    <circle cx='80'  cy='20'  r='2.2'/>
    <circle cx='140' cy='20'  r='2.2'/>
    <circle cx='50'  cy='80'  r='2.2'/>
    <circle cx='110' cy='80'  r='2.2'/>
    <circle cx='170' cy='80'  r='2.2'/>
    <circle cx='20'  cy='140' r='2.2'/>
    <circle cx='80'  cy='140' r='2.2'/>
    <circle cx='140' cy='140' r='2.2'/>
  </g>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


def _bg_duotone_data_uri() -> str:
    """Diagonal half-tone split — a flat triangle slice gives the
    composition a strong, modern poster feel."""
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'>
  <polygon points='0,400 400,0 400,400' fill='white' fill-opacity='0.09'/>
</svg>"""
    return f'url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}")'


# Lookup table: brief.background_style → CSS url() value
def _background_pattern_for(style: str) -> str:
    style = (style or "water").lower()
    builders = {
        "water": _water_pattern_data_uri,
        "halftone": _bg_halftone_data_uri,
        "diagonal": _bg_diagonal_stripes_data_uri,
        "radial": _bg_radial_burst_data_uri,
        "geometric": _bg_geometric_data_uri,
        "clean": _bg_clean_data_uri,
        "stripes": _bg_vertical_stripes_data_uri,
        "dots": _bg_dots_data_uri,
        "duotone": _bg_duotone_data_uri,
        "grain": _bg_clean_data_uri,  # rely on the noise overlay only
    }
    builder = builders.get(style, _water_pattern_data_uri)
    return builder()


# ---------------------------------------------------------------------------
# Typography pairs. Each pair returns a small CSS override block that
# rebinds the headline / numeral / body classes onto the chosen fonts.
# All listed fonts are loaded by _shared.css / the @import URL so we can
# reference them safely; an unknown pair falls back to the legacy default.
# ---------------------------------------------------------------------------

_TYPOGRAPHY_OVERRIDES: dict[str, str] = {
    "anton-inter": "",  # legacy default — no override
    "bebas-grotesk": (
        ".surname-bg, .fg-firstname, .hero-numeral, .label-ribbon, "
        ".headline-line { font-family: 'Bebas Neue','Anton',sans-serif !important; }\n"
        ".result-chip .value, .fg-event, .meet-line, .club-line, "
        ".sponsor-strip { font-family: 'Space Grotesk','Inter',sans-serif !important; }"
    ),
    "druk-inter": (
        ".surname-bg, .fg-firstname, .hero-numeral, .label-ribbon, "
        ".headline-line { font-family: 'Anton','Bowlby One','Bebas Neue',sans-serif !important; "
        "letter-spacing: -0.05em !important; font-stretch: condensed !important; }\n"
        ".result-chip .value, .fg-event, .meet-line, .club-line, "
        ".sponsor-strip { font-family: 'Inter',sans-serif !important; }"
    ),
    "bowlby-inter": (
        ".surname-bg, .fg-firstname, .hero-numeral, .label-ribbon, "
        ".headline-line { font-family: 'Bowlby One','Anton',sans-serif !important; "
        "letter-spacing: -0.01em !important; }\n"
        ".result-chip .value, .fg-event, .meet-line, .club-line, "
        ".sponsor-strip { font-family: 'Inter',sans-serif !important; }"
    ),
    "archivo-inter": (
        ".surname-bg, .fg-firstname, .hero-numeral, .label-ribbon, "
        ".headline-line { font-family: 'Anton','Bebas Neue',sans-serif !important; "
        "letter-spacing: 0.01em !important; text-transform: uppercase; }\n"
        ".result-chip .value, .fg-event, .meet-line, .club-line "
        "{ font-family: 'Inter',sans-serif !important; font-weight: 700 !important; }"
    ),
    "oswald-inter": (
        ".surname-bg, .fg-firstname, .hero-numeral, .label-ribbon, "
        ".headline-line { font-family: 'Anton','Bebas Neue',sans-serif !important; "
        "font-stretch: condensed !important; letter-spacing: 0.02em !important; }\n"
        ".result-chip .value, .fg-event, .meet-line, .club-line "
        "{ font-family: 'Inter',sans-serif !important; }"
    ),
}


def _typography_overrides_css(pair: str) -> str:
    return _TYPOGRAPHY_OVERRIDES.get((pair or "").lower(), "")


# ---------------------------------------------------------------------------
# Accent decorations — small extra HTML elements layered on top of the
# canvas to give the brand accent a fresh visual signature without
# touching the layout structure.
# ---------------------------------------------------------------------------


def _accent_decoration_html(
    style: str, accent: str, width: int, height: int, strength: float = 0.5
) -> str:
    style = (style or "brackets").lower()
    s = max(0.0, min(1.0, float(strength)))
    if s <= 0.05 or style == "minimal":
        return ""
    # Common helpers
    weight = max(2, int(min(width, height) * 0.005 * (0.6 + s)))
    long_side = int(min(width, height) * (0.10 + 0.10 * s))
    color = accent or "#FFFFFF"
    if style == "brackets":
        offset = int(min(width, height) * 0.04)
        return (
            f'<div style="position:absolute;left:{offset}px;top:{offset}px;width:{long_side}px;'
            f"height:{long_side}px;border-top:{weight}px solid {color};border-left:{weight}px solid {color};"
            f'z-index:11;pointer-events:none;"></div>'
            f'<div style="position:absolute;right:{offset}px;bottom:{offset + int(height * 0.07)}px;'
            f"width:{long_side}px;height:{long_side}px;border-bottom:{weight}px solid {color};"
            f'border-right:{weight}px solid {color};z-index:11;pointer-events:none;"></div>'
        )
    if style == "stripe":
        band_h = max(6, int(height * 0.012 * (0.6 + s)))
        top = int(height * 0.46)
        return (
            f'<div style="position:absolute;left:0;right:0;top:{top}px;height:{band_h}px;'
            f"background:linear-gradient(90deg,transparent 0%,{color} 50%,transparent 100%);"
            f'opacity:0.85;z-index:5;pointer-events:none;"></div>'
        )
    if style == "frame":
        inset = int(min(width, height) * 0.035)
        return (
            f'<div style="position:absolute;left:{inset}px;right:{inset}px;top:{inset}px;'
            f"bottom:{inset}px;border:{weight}px solid {color};opacity:0.55;"
            f'z-index:11;pointer-events:none;"></div>'
        )
    if style == "ribbon":
        size = int(min(width, height) * 0.20 * (0.6 + s))
        return (
            f'<div style="position:absolute;left:-{size // 2}px;top:{int(height * 0.20)}px;'
            f"width:{size * 2}px;height:{max(20, int(size * 0.18))}px;background:{color};"
            f"transform:rotate(-32deg);transform-origin:left center;opacity:0.85;"
            f'z-index:11;pointer-events:none;"></div>'
        )
    if style == "arrow":
        size = int(min(width, height) * 0.05 * (0.6 + s))
        top = int(height * 0.52)
        return (
            f'<div style="position:absolute;right:{int(width * 0.06)}px;top:{top}px;'
            f"width:0;height:0;border-left:{size}px solid {color};"
            f"border-top:{size}px solid transparent;border-bottom:{size}px solid transparent;"
            f'z-index:11;pointer-events:none;opacity:0.95;"></div>'
        )
    if style == "underline":
        bar_h = max(4, int(height * 0.006 * (0.6 + s)))
        return (
            f'<div style="position:absolute;left:{int(width * 0.06)}px;right:{int(width * 0.40)}px;'
            f"top:{int(height * 0.20)}px;height:{bar_h}px;background:{color};"
            f'z-index:11;pointer-events:none;"></div>'
        )
    if style == "badge":
        size = int(min(width, height) * 0.085 * (0.6 + s))
        return (
            f'<div style="position:absolute;right:{int(width * 0.06)}px;top:{int(height * 0.32)}px;'
            f"width:{size}px;height:{size}px;border-radius:50%;background:{color};"
            f"opacity:0.85;z-index:11;pointer-events:none;"
            f'box-shadow:0 6px 18px rgba(0,0,0,0.35);"></div>'
        )
    return ""


# ---------------------------------------------------------------------------
# Composition override — flip the cutout to left / centre when the brief
# requests it. The default templates pin .athlete-wrap to right:-40px so
# all we need to do is inject a CSS override that retargets it.
# ---------------------------------------------------------------------------


def _composition_overrides_css(composition: str) -> str:
    c = (composition or "right").lower()
    if c == "left":
        return (
            ".athlete-wrap { left: -40px !important; right: auto !important; "
            "transform: scaleX(-1); }\n"
            ".surname-bg.has-photo { right: 0 !important; left: auto !important; "
            "text-align: right !important; }\n"
            ".fg-text { left: auto !important; right: 56px !important; "
            "text-align: right !important; }"
        )
    if c == "center":
        return (
            ".athlete-wrap { left: 50% !important; right: auto !important; "
            "transform: translateX(-50%); }\n"
            ".surname-bg.has-photo { left: 0 !important; right: 0 !important; "
            "text-align: center !important; }\n"
            ".fg-text { left: 0 !important; right: 0 !important; "
            "text-align: center !important; }"
        )
    if c == "off-center":
        return (
            ".athlete-wrap { right: 12% !important; }\n"
            ".surname-bg.has-photo { left: -2% !important; }"
        )
    return ""


# ---------------------------------------------------------------------------
# Photo treatment — apply a CSS filter / wrapper effect to the athlete
# cutout based on brief.photo_treatment. "no-photo" is handled upstream
# by the brief generator (image_treatment phrase), but we still set the
# CSS in case the cutout slipped through.
# ---------------------------------------------------------------------------


def _photo_treatment_css(treatment: str, palette: dict) -> str:
    t = (treatment or "cutout").lower()
    accent = palette.get("accent", "#FFFFFF")
    if t == "vignette":
        return (
            ".athlete-cutout { filter: drop-shadow(0 0 36px rgba(0,0,0,0.55)) "
            "drop-shadow(0 0 14px rgba(0,0,0,0.40)); }"
        )
    if t == "duotone":
        return (
            ".athlete-cutout { filter: grayscale(1) contrast(1.10) brightness(0.96) "
            f"sepia(0.30); }}\n.athlete-cutout {{ mix-blend-mode: luminosity; opacity: 0.92; }}"
        )
    if t == "halftone":
        return ".athlete-cutout { filter: grayscale(0.45) contrast(1.18) brightness(0.96); }"
    if t == "frame":
        return (
            ".athlete-wrap { border-left: 4px solid " + accent + "; "
            "padding-left: 6px; box-sizing: border-box; }"
        )
    return ""


# ----- Athlete cutout pipeline ---------------------------------------------


def _maybe_cut_out_athlete(src_path: str | Path, *, profile_id: str = "default") -> Path:
    """Run the configured background remover on the athlete photo if needed.

    Caches results in ``<UPLOADS_DIR>/media_library/<profile_id>/cutouts/``
    so we don't re-run rembg on the same photo every render. The cache
    dir is DATA_DIR-derived so cutouts survive Render redeploys (the
    persistent disk holds them); a previous version of this used a
    relative path that mapped to /app/uploads_v4 and was wiped on every
    container restart.
    """
    src = Path(src_path)
    if not src.exists():
        return src

    # Already a cutout?
    if "cutout" in src.stem.lower() or src.parent.name == "cutouts":
        return src

    uploads_root = os.environ.get("UPLOADS_DIR") or str(
        Path(os.environ.get("DATA_DIR", "data")) / "uploads_v4"
    )
    cache_dir = Path(uploads_root) / "media_library" / profile_id / "cutouts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{src.stem}__cutout.png"
    if out_path.exists() and out_path.stat().st_size > 1000:
        return out_path

    try:
        from mediahub.media_ai.providers import get_bg_remover  # type: ignore

        remover = get_bg_remover()
        if remover is None:
            log.warning("cutout: no bg remover provider available for %s", src.name)
            return src
        ok = remover.remove(src, out_path)
        if ok and out_path.exists():
            return out_path
        log.warning("cutout: provider returned ok=%s for %s (out=%s)", ok, src.name, out_path)
    except Exception as exc:
        log.warning("cutout: provider raised for %s: %s", src.name, exc)
    return src


# ---------------------------------------------------------------------------
# Logo / sponsor / result-chip block builders
# ---------------------------------------------------------------------------

# Cache preprocessed logos by (abs path, mtime, size) so the trim/knockout
# pixel work runs once per logo per process rather than on every card render.
_LOGO_PREP_CACHE: dict[tuple, tuple[str, Optional[str]]] = {}


def clear_logo_prep_cache() -> int:
    """Drop the in-process preprocessed-logo cache; returns the entry count removed.

    Re-derivable (each entry is pure trim/knockout pixel work keyed by the logo
    file's path+mtime+size), so a site-wide cache purge clears it to actually
    free the worker's memory rather than leave the encoded logos resident.
    """
    n = len(_LOGO_PREP_CACHE)
    _LOGO_PREP_CACHE.clear()
    return n


def _knockout_uniform_background(img):
    """Flood-fill a connected, near-uniform border background to transparent.

    Handles white-background PNGs and JPG logos that otherwise render as an
    opaque rectangle inside the chip. Conservative: only fills regions
    connected to the four corners (interior fills of the same colour are
    preserved), and reverts entirely if the fill would erase almost the whole
    image (i.e. the logo itself was that colour).
    """
    from PIL import ImageDraw

    w, h = img.size
    if w < 4 or h < 4:
        return img
    corners = [
        img.getpixel((0, 0)),
        img.getpixel((w - 1, 0)),
        img.getpixel((0, h - 1)),
        img.getpixel((w - 1, h - 1)),
    ]
    if all(len(c) == 4 and c[3] < 32 for c in corners):
        return img  # already transparent border — nothing to do

    def _close(a, b, t=28):
        return all(abs(a[i] - b[i]) <= t for i in range(3))

    base = corners[0]
    if not all(_close(base, c) for c in corners[1:]):
        return img  # non-uniform corners → real imagery, leave it alone

    rgb = img.convert("RGB")
    SENT = (1, 254, 2)  # improbable sentinel fill colour
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        try:
            ImageDraw.floodfill(rgb, (x, y), SENT, thresh=36)
        except Exception:
            return img
    out = img.copy()
    src = rgb.load()
    dst = out.load()
    removed = 0
    for y in range(h):
        for x in range(w):
            if src[x, y] == SENT:
                r, g, b, a = dst[x, y]
                dst[x, y] = (r, g, b, 0)
                removed += 1
    if removed > 0.92 * (w * h):
        return img  # would blank the logo — keep the original
    return out


def _logo_dominant_hex(img) -> Optional[str]:
    """The logo's representative brand colour — average of its saturated,
    opaque pixels (falls back to all opaque pixels). Used only to decide the
    chip treatment, never to recolour the logo."""
    rs = gs = bs = n = 0
    rs2 = gs2 = bs2 = n2 = 0
    for px in img.getdata():
        if len(px) != 4:
            continue
        r, g, b, a = px
        if a < 64:
            continue
        n2 += 1
        rs2 += r
        gs2 += g
        bs2 += b
        if max(r, g, b) - min(r, g, b) < 24:
            continue  # near-neutral — skip when looking for the brand hue
        n += 1
        rs += r
        gs += g
        bs += b
    if n >= max(20, n2 * 0.02):
        return _rgb_to_hex((rs / n, gs / n, bs / n))
    if n2:
        return _rgb_to_hex((rs2 / n2, gs2 / n2, bs2 / n2))
    return None


def _prepare_logo_data_uri(logo_path: str | Path) -> tuple[str, Optional[str]]:
    """Clean a raster logo for crisp, integrated placement.

    Knocks out a uniform background, auto-trims whitespace, adds a small
    transparent clear-zone, and renders at a crisp size. Returns
    ``(png_data_uri, dominant_hex)``. SVGs are embedded as-is (no dominant
    colour). Results are cached per file.
    """
    p = Path(logo_path)
    suffix = p.suffix.lower().lstrip(".")
    if suffix == "svg":
        return _img_to_data_uri(logo_path), None
    try:
        st = p.stat()
        key = (str(p.resolve()), int(st.st_mtime), int(st.st_size))
    except Exception:
        key = None
    if key is not None and key in _LOGO_PREP_CACHE:
        return _LOGO_PREP_CACHE[key]

    import io
    from PIL import Image

    img = Image.open(p).convert("RGBA")
    if max(img.size) > 400:
        img.thumbnail((400, 400), Image.LANCZOS)
    img = _knockout_uniform_background(img)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    pad = max(2, int(0.06 * max(img.size)))
    canvas = Image.new("RGBA", (img.size[0] + 2 * pad, img.size[1] + 2 * pad), (0, 0, 0, 0))
    canvas.paste(img, (pad, pad), img)
    img = canvas
    target = 288  # ~3x the 96px chip so it stays sharp
    if max(img.size) < target:
        scale = target / max(img.size)
        img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
    dom = _logo_dominant_hex(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    result = (uri, dom)
    if key is not None:
        _LOGO_PREP_CACHE[key] = result
    return result


def _decide_logo_mark_mod(dominant_hex: Optional[str], surface_hex: str) -> str:
    """Pick the chip treatment using the deterministic ΔE2000 / APCA gates.

    Returns a class modifier appended to ``.logo-mark``:
      ""                  → default white chip
      " logo-mark--bare"  → no chip; the logo is distinct enough to sit bare
      " logo-mark--dark"  → dark chip; the logo is too light for a white chip
    """
    if not dominant_hex or not surface_hex:
        return ""
    try:
        from mediahub.theming.logo_chip import decide_logo_chip

        if decide_logo_chip(dominant_hex, surface_hex).mode == "bare":
            return " logo-mark--bare"
        # Chip needed against the surface — choose its colour: white unless the
        # logo is too close to white (then a white chip would hide it).
        if decide_logo_chip(dominant_hex, "#FFFFFF").mode == "chip":
            return " logo-mark--dark"
    except Exception:
        return ""
    return ""


def _build_logo_treatment(
    brand_kit,
    logo_path: Optional[str | Path],
    surface_hex: str = "",
) -> tuple[str, str]:
    """Return ``(inner_html, logo_mark_modifier)`` for ``.brand-corner .logo-mark``."""
    if logo_path:
        try:
            uri, dom = _prepare_logo_data_uri(logo_path)
            return f'<img src="{uri}" alt="logo" />', _decide_logo_mark_mod(dom, surface_hex)
        except Exception:
            try:
                return f'<img src="{_img_to_data_uri(logo_path)}" alt="logo" />', ""
            except Exception:
                pass
    # SVG logo string?
    svg = getattr(brand_kit, "logo_svg", None)
    if svg and isinstance(svg, str) and svg.lstrip().startswith("<"):
        return svg, ""
    # Text-mark fallback: club initials
    name = (
        getattr(brand_kit, "short_name", None) or getattr(brand_kit, "display_name", "") or "CLUB"
    )
    parts = [w for w in str(name).replace("Swimming Club", "").split() if w]
    initials = "".join(p[0].upper() for p in parts[:3]) or "CL"
    return initials, ""


def _build_logo_block(brand_kit, logo_path: Optional[str | Path]) -> str:
    """Return inner HTML for ``.brand-corner .logo-mark`` (treatment-agnostic)."""
    return _build_logo_treatment(brand_kit, logo_path)[0]


def _build_athlete_block(athlete_data_uri: Optional[str], full_name: str) -> str:
    """Render the athlete cutout if we have one, else an empty placeholder.

    The text-led fallback (mega-initial + stat strip) is added separately via
    ``_build_text_led_fill_block`` so layouts can place it freely.
    """
    if athlete_data_uri:
        return (
            f'<img class="athlete-cutout" src="{athlete_data_uri}" '
            f'alt="{html_escape(full_name)}" />'
        )
    # No photo: render nothing inside the athlete-wrap. The layout's
    # text-led-fill block (added separately) takes over the empty region.
    return ""


def _build_text_led_fill_block(
    *,
    full_name: str,
    surname: str,
    width: int,
    height: int,
    layers: dict,
    palette: dict,
    has_photo: bool,
    compact: bool = False,
    skip_stat_strip: bool = False,
) -> str:
    """Build the HTML block injected when there is no athlete photo.

    Composition: a giant blurred surname watermark on the empty side, a soft
    photo-glow disc, a slim diagonal accent bar, a dot-grid texture, and a
    3-cell stat strip with event/course/meet date. Everything is positioned
    relative to the canvas so it works for portrait, square, and story formats.
    """
    if has_photo:
        return ""
    initials = "".join(p[0] for p in (full_name or "").split()[:2]).upper()
    if not initials:
        initials = (surname or "").strip()[:2].upper() or "\u2014"
    mega_letter = (surname or full_name or "").upper()
    if not mega_letter:
        mega_letter = initials

    # Stat strip cells
    event = (layers.get("event_name") or "").strip()
    course = ""
    if "LC" in event.upper():
        course = "Long Course"
    elif "SC" in event.upper():
        course = "Short Course"
    elif event:
        course = "Race"
    meet = (layers.get("meet_name") or "").strip()
    result = (layers.get("result_value") or "").strip()
    place = (layers.get("place") or "").strip()

    cells = []
    if event:
        cells.append(("EVENT", _clean_event_name(event)))
    if result:
        cells.append(("TIME", result))
    if place:
        place_label = (
            f"{place} place" if not place.lower().endswith(("st", "nd", "rd", "th")) else place
        )
        cells.append(("FINISH", place_label))
    if course and len(cells) < 3:
        cells.append(("COURSE", course))
    if meet and len(cells) < 3:
        cells.append(("MEET", _ellipsize(meet, 28)))
    cells = cells[:3]
    if not cells:
        cells = [("NEW PB", layers.get("achievement_label") or "PB")]

    # Position the mega-initial roughly where the photo would have been.
    # Use a smaller, more architectural sizing for `compact` mode (so it lives
    # behind the fg-text instead of swallowing it).
    if compact:
        mega_size = int(min(width, height) * 0.62)
        mega_top = int(height * 0.22)
        glow_size = int(min(width, height) * 0.55)
        glow_top = int(height * 0.20)
        glow_right = int(-width * 0.12)
    else:
        mega_size = int(min(width, height) * 0.78)
        mega_top = int(height * 0.18)
        glow_size = int(min(width, height) * 0.70)
        glow_top = int(height * 0.20)
        glow_right = int(-width * 0.16)

    # Fit the giant surname watermark so the WHOLE name reads ("CARTER", not a
    # clipped "CA"/"ARTER"); short names keep their drama (autofit caps at
    # mega_size). Centred below so any residual width is shared, not edge-cut.
    mega_px = _mega_watermark_px(mega_letter, width, mega_size)

    strip_class = "txl-stat-strip compact-tr" if compact else "txl-stat-strip"
    # In compact mode, only show 2 cells (event/time) so the column is short.
    cells_for_render = cells[:2] if compact else cells
    cells_html = "".join(
        f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
        f'<div class="val">{html_escape(val)}</div></div>'
        for lab, val in cells_for_render
    )
    strip_html = "" if skip_stat_strip else f'<div class="{strip_class}">{cells_html}</div>'

    return (
        f'<div class="txl-photo-glow" '
        f'style="top:{glow_top}px;right:{glow_right}px;width:{glow_size}px;height:{glow_size}px;"></div>'
        f'<div class="txl-accent-bar diagonal"></div>'
        f'<div class="txl-accent-bar dot-grid"></div>'
        f'<div class="txl-mega-initial" '
        f'style="top:{mega_top}px;left:50%;transform:translateX(-50%);'
        f'right:auto;font-size:{mega_px}px;">'
        f"{html_escape(mega_letter[:14])}"
        f"</div>"
        f"{strip_html}"
    )


def _build_result_chip(label: str, value: str) -> str:
    if not value:
        return ""
    return (
        f'<div class="result-chip">'
        f'<div class="label">{html_escape(label or "Time")}</div>'
        f'<div class="value">{html_escape(value)}</div>'
        f"</div>"
    )


def _build_sponsor_block(sponsor_name: str | None, logo_data_uri: str = "") -> str:
    if not sponsor_name:
        return ""
    logo_html = (
        f'<img class="logo" src="{logo_data_uri}" alt="" '
        'style="height:1.6em;width:auto;vertical-align:middle;margin-right:0.5em"/>'
        if logo_data_uri
        else ""
    )
    return (
        '<div class="sponsor-strip">'
        f"{logo_html}"
        '<span class="label">Performance supported by</span>'
        f'<span class="name">{html_escape(sponsor_name)}</span>'
        "</div>"
    )


def html_escape(s: Any) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Layout-specific filler functions
# ---------------------------------------------------------------------------


def _surname_for_display(surname: str, max_chars: int = 8) -> str:
    s = (surname or "").upper()
    return s[:max_chars] if len(s) > max_chars else s


_COURSE_SUFFIX_RE = re.compile(r"\s*\((?:SC|LC)\)\s*$", re.IGNORECASE)


def _clean_event_name(name: str) -> str:
    """Strip trailing "(SC)" / "(LC)" course jargon from an event name.

    Course codes are results-file plumbing, not public copy — "100M
    BACKSTROKE (SC)" on a celebration graphic reads as jargon. Layouts that
    want the course render it as its own labelled cell instead.
    """
    return _COURSE_SUFFIX_RE.sub("", name or "").strip()


# The ghost-surname watermark uses the layouts' condensed display stack
# (Anton / Bebas Neue) — autofit classifies these as "condensed".
_SURNAME_FONT_FAMILY = "Anton"


def _surname_font_px(surname: str, width: int, height: int, base_px: int) -> int:
    """Font size for the giant background surname so the FULL name fits.

    The fixed ``height * 0.30`` sizing clipped long surnames mid-letter at
    the canvas edge ("SCOT|T"). Autofit binary-searches the largest size at
    which the whole surname spans at most the canvas width, capped at the
    layout's original size and floored at ``height * 0.12`` so short names
    keep their drama and long ones stay architectural rather than vanishing.
    """
    text = (surname or "").upper().strip()
    if not text:
        return base_px
    from mediahub.graphic_renderer.autofit import fit_font_px

    floor = max(8, int(height * 0.12))
    cap = max(floor, int(base_px))
    return fit_font_px(
        text,
        box_w=width * 0.96,
        box_h=cap,  # single line: height bound == the size cap
        font_family=_SURNAME_FONT_FAMILY,
        weight=900,
        min_px=floor,
        max_px=cap,
        line_height=1.0,
    )


def _mega_watermark_px(text: str, width: int, cap_px: int) -> int:
    """Font size for the giant no-photo surname watermark (text-led fill).

    Fits the whole word into ~84% of the canvas width — a deliberately bigger
    safety margin than the ~96% used for the in-layout surname, because the
    watermark is *centred* and must never bleed a letter off either edge (the
    char-width table runs a touch narrow for real Anton, so ~96% sometimes
    pushed a "CARTER" out to "ARTER"). Capped at the layout's design size so
    short names keep their drama; floored so very long names stay legible.
    """
    text = (text or "").upper().strip()
    if not text:
        return cap_px
    from mediahub.graphic_renderer.autofit import fit_font_px

    floor = max(40, int(width * 0.12))
    cap = max(floor, int(cap_px))
    return fit_font_px(
        text,
        box_w=width * 0.84,
        box_h=cap,
        font_family=_SURNAME_FONT_FAMILY,
        weight=900,
        min_px=floor,
        max_px=cap,
        line_height=1.0,
    )


# ---------------------------------------------------------------------------
# Per-format composition (G1.3) — landscape & extended aspect-ratio support
#
# The standard formats are all square or taller-than-wide (feed_square 1:1,
# feed_portrait 4:5, story 9:16). G1.3 adds landscape / extended ratios to
# FORMAT_SIZES (16:9, 3:2, 4:3), and the three helpers below carry the matching
# composition rules so a wide canvas reads as a deliberate landscape design
# rather than a portrait layout stretched sideways:
#   * _scale_for_format        — v1 layout typography multipliers (height-rel)
#   * _v2_fit_boxes            — v2 archetype autofit box constraints
#   * _format_composition_css  — wide-canvas retune of the shared base classes
#
# Hard invariant: every helper returns its *legacy* value for any
# square/portrait/story canvas, so renders of the existing formats stay
# byte-identical. Only width > height (landscape) canvases pick up new
# behaviour.
# ---------------------------------------------------------------------------

# The three landscape families G1.3 supports. Used by the helpers below to key
# their per-format rules and by tests/callers that want to reason about them.
_LANDSCAPE_ASPECTS = ("landscape_169", "landscape_32", "landscape_43")


def _format_aspect(width: int, height: int) -> str:
    """Classify a canvas into a composition family.

    Returns one of ``square``, ``portrait``, ``story`` (tall portrait),
    ``landscape_43`` (≈4:3), ``landscape_32`` (≈3:2) or ``landscape_169``
    (≈16:9 or wider). The square/portrait/story split is exactly the one
    ``_scale_for_format`` used before G1.3, so existing renders are unaffected.
    Landscape thresholds sit *between* the target ratios (4:3≈1.333, 3:2=1.5,
    16:9≈1.778) so an off-nominal wide canvas snaps to the nearest family.
    """
    if width == height:
        return "square"
    if height > width:
        return "story" if (height / width) >= 1.7 else "portrait"
    ratio = width / height
    if ratio >= 1.64:  # midpoint between 3:2 (1.500) and 16:9 (1.778)
        return "landscape_169"
    if ratio >= 1.42:  # midpoint between 4:3 (1.333) and 3:2 (1.500)
        return "landscape_32"
    return "landscape_43"


def _scale_for_format(width: int, height: int) -> dict[str, float]:
    """Return per-format multipliers used to pick font sizes (v1 layouts).

    Each multiplier is applied to the canvas **height** by the layout fillers.
    Landscape families lift the multipliers above the portrait baseline so the
    hero type stays visually large despite the short (height) edge — the wider
    the format, the more vertical share the hero can claim.
    """
    kind = _format_aspect(width, height)
    if kind == "square":
        return {"surname": 0.32, "first": 0.075, "event": 0.026, "result": 0.055, "ribbon": 0.034}
    if kind == "story":  # 9:16
        return {"surname": 0.28, "first": 0.06, "event": 0.022, "result": 0.045, "ribbon": 0.028}
    if kind == "portrait":  # 4:5
        return {"surname": 0.34, "first": 0.07, "event": 0.024, "result": 0.052, "ribbon": 0.032}
    if kind == "landscape_169":  # 16:9 — widest, biggest height share
        return {"surname": 0.42, "first": 0.078, "event": 0.028, "result": 0.062, "ribbon": 0.037}
    if kind == "landscape_32":  # 3:2
        return {"surname": 0.40, "first": 0.075, "event": 0.027, "result": 0.059, "ribbon": 0.036}
    # landscape_43 — closest to square, gentlest lift
    return {"surname": 0.38, "first": 0.072, "event": 0.026, "result": 0.056, "ribbon": 0.035}


def _v2_fit_boxes(width: int, height: int) -> dict[str, tuple[float, float, int, int]]:
    """Per-format autofit box constraints for the v2 archetype hero slots.

    Each value is ``(width_fraction, height_fraction, min_px, max_px)`` fed to
    ``_fit_one_line_px``. Square/portrait/story keep the historic fractions so
    those renders stay byte-identical. Landscape families let the hero claim a
    larger share of the short (height) edge and a tighter share of the now-
    abundant width — so a 16:9 card reads as boldly as a portrait one without a
    single line spanning the whole ultra-wide frame — and raise the minimum so
    type stays substantial on the larger canvas.
    """
    kind = _format_aspect(width, height)
    if kind not in _LANDSCAPE_ASPECTS:
        return {
            "surname": (0.86, 0.18, 44, 132),
            "result": (0.52, 0.12, 40, 104),
            "mega_result": (0.92, 0.34, 72, 300),
            "mega_name": (0.92, 0.22, 64, 220),
        }
    if kind == "landscape_169":
        return {
            "surname": (0.66, 0.30, 56, 150),
            "result": (0.42, 0.22, 48, 120),
            "mega_result": (0.80, 0.56, 96, 360),
            "mega_name": (0.80, 0.40, 84, 260),
        }
    if kind == "landscape_32":
        return {
            "surname": (0.72, 0.27, 52, 144),
            "result": (0.46, 0.20, 46, 116),
            "mega_result": (0.84, 0.52, 90, 340),
            "mega_name": (0.84, 0.37, 80, 248),
        }
    # landscape_43
    return {
        "surname": (0.78, 0.24, 50, 138),
        "result": (0.50, 0.18, 44, 110),
        "mega_result": (0.88, 0.46, 84, 320),
        "mega_name": (0.88, 0.32, 74, 236),
    }


def _format_composition_css(width: int, height: int) -> str:
    """Per-format CSS composition overrides appended to BASE_CSS.

    Empty for square/portrait/story (those renders stay byte-identical). For a
    landscape / extended aspect ratio it (a) publishes the format as CSS custom
    properties future layouts and sprint-hooks can read, and (b) retunes the
    shared base-layout classes — tuned for a 1080-wide *portrait* canvas — so
    the v1 layouts compose for the wide frame: wider safe insets, capped
    vertical type, and a denser stat grid. v2 archetypes additionally adapt via
    the aspect-aware autofit boxes (``_v2_fit_boxes``) and their own
    flex/percentage CSS, so these class overrides are harmless no-ops for them.
    """
    kind = _format_aspect(width, height)
    if kind not in _LANDSCAPE_ASPECTS:
        return ""
    ratio = width / height
    # 56px portrait baseline inset scales up with the ratio (≈99px at 16:9).
    pad = int(round(56 * min(1.8, ratio)))
    fg_bottom = int(height * 0.14)
    fg_first = int(height * 0.13)
    recap_top = int(height * 0.10)
    recap_size = int(height * 0.16)
    recap_bottom = int(height * 0.10)
    grid_cols = 4 if kind == "landscape_169" else 3
    grid_top = int(height * 0.12)
    grid_bottom = int(height * 0.14)
    stat_num = int(height * 0.16)
    # Equal-specificity selectors mirroring layouts/_base.css; appended after
    # the base sheet so they win the cascade. Doubled braces are literal CSS.
    return f"""
/* --- G1.3 per-format composition ({kind}) --- */
:root{{--mh-format:"{kind}";--mh-format-ratio:{ratio:.3f};--mh-edge-pad:{pad}px;}}
.label-ribbon{{top:var(--mh-edge-pad);left:var(--mh-edge-pad);}}
.result-chip{{top:var(--mh-edge-pad);right:var(--mh-edge-pad);}}
.brand-corner{{bottom:var(--mh-edge-pad);left:var(--mh-edge-pad);}}
.sponsor-strip{{padding-left:var(--mh-edge-pad);padding-right:var(--mh-edge-pad);}}
.fg-text{{left:var(--mh-edge-pad);right:var(--mh-edge-pad);bottom:{fg_bottom}px;}}
.fg-firstname{{font-size:min(168px,{fg_first}px);line-height:0.9;}}
.surname-bg{{line-height:0.82;}}
.recap-headline{{top:{recap_top}px;left:var(--mh-edge-pad);right:var(--mh-edge-pad);font-size:min(160px,{recap_size}px);}}
.recap-bullets{{bottom:{recap_bottom}px;left:var(--mh-edge-pad);right:var(--mh-edge-pad);}}
.stat-grid{{inset:{grid_top}px var(--mh-edge-pad) {grid_bottom}px var(--mh-edge-pad);grid-template-columns:repeat({grid_cols},1fr);}}
.stat-tile .num{{font-size:min(130px,{stat_num}px);}}
.medal-badge{{right:var(--mh-edge-pad);}}
"""


def _detect_medal_tier(brief) -> Optional[str]:
    """Return 'gold' | 'silver' | 'bronze' | None based on the brief.

    Looks at achievement_label, post_angle, inspiration_pattern_id, and place
    so any layout (not just medal_card) can colour itself appropriately.
    A swimmer that medalled should always read as "medalled" at a glance,
    regardless of which layout the brief picked.

    A PB is deliberately NOT a tier here: it keeps the club's real brand
    accent (see ``_MEDAL_ACCENTS``) rather than being repainted, so the most
    common card type still looks like the club.
    """
    layers = brief.text_layers or {}
    label = (layers.get("achievement_label") or "").lower()
    angle = (layers.get("post_angle") or "").lower()
    pattern = (getattr(brief, "inspiration_pattern_id", "") or "").lower()
    place = str(layers.get("place") or "").strip()
    combined = " ".join([label, angle, pattern])

    # Parse the placing as a NUMBER — a bare prefix match would paint a
    # 10th/12th place gold and a 21st silver.
    m = re.match(r"(\d+)", place)
    place_n = int(m.group(1)) if m else 0

    if "gold" in combined or place_n == 1:
        return "gold"
    if "silver" in combined or place_n == 2:
        return "silver"
    if "bronze" in combined or place_n == 3:
        return "bronze"
    return None


# Medal palette overrides — applied on top of the club's brand colours so the
# medal tier is unmistakable at a glance while the brand still dominates. Only
# the three medal tiers tint the accent, because for a medal the colour *is* the
# information (a gold card should feel gold). A PB is intentionally absent: it
# keeps the club's confirmed brand accent and reads "NEW PB" through the ribbon
# text, so a navy+gold club's PB card stays navy+gold instead of turning a
# generic, off-brand cyan — and the most common card type looks on-brand.
_MEDAL_ACCENTS = {
    "gold": {"accent": "#FFD24A", "accent_deep": "#A77A07", "badge": "GOLD"},
    "silver": {"accent": "#E8EAED", "accent_deep": "#6F757B", "badge": "SILVER"},
    "bronze": {"accent": "#E2A26A", "accent_deep": "#7E481B", "badge": "BRONZE"},
}


def _common_replacements(
    brief,
    width: int,
    height: int,
    brand_kit,
    *,
    athlete_data_uri: str | None,
    logo_block: str,
    result_chip: str,
    sponsor_block: str,
    logo_mark_mod: str = "",
    bg_photo_uri: str = "",
    theme_json: Optional[dict] = None,
    skip_ai_bg: bool = False,
) -> dict[str, str]:
    palette = dict(brief.palette or {})

    # Phase 1.6 Stage G — when an on-disk theme JSON is reachable
    # (via the brand_kit's profile_id) prefer its light-scheme roles
    # over brief.palette. Static graphics are posted to social feeds
    # which default to light backgrounds, so the LIGHT scheme's
    # primary gives high contrast.
    if theme_json is None:
        pid = getattr(brand_kit, "profile_id", None) if brand_kit else None
        if isinstance(brand_kit, dict):
            pid = brand_kit.get("profile_id") or pid
        if pid:
            try:
                from mediahub.theming.theme_store import read_theme

                theme_json = read_theme(pid)
            except Exception:
                theme_json = None
    if theme_json:
        try:
            from mediahub.theming.theme_store import palette_for_static

            p = palette_for_static(theme_json)
            # The brief palette already carries the club's CONFIRMED brand
            # colours (primary/secondary/accent from the BrandKit). Those
            # win. The MD3 theme store is a single-seed projection that
            # tone-shifts the brand for contrast and cannot represent a
            # second brand colour — so for a navy+gold club it would emit
            # a washed-out blue primary and drop the gold entirely. Let it
            # only FILL a role the brief left unset, never override a
            # confirmed brand hex.
            for k in ("primary", "secondary", "accent"):
                if _is_brand_hex(palette.get(k)):
                    continue
                if isinstance(p.get(k), str) and p[k].startswith("#"):
                    palette[k] = p[k]
        except Exception:
            pass

    primary = palette.get("primary", "#0A2540")
    secondary = palette.get("secondary", "#000000")
    accent = palette.get("accent", "#FFFFFF")
    primary_deep = darken(primary, 0.30)

    # Medal-tier override: gold/silver/bronze should be unmistakable in the
    # accent colour without losing the club's brand identity in the primary.
    tier = _detect_medal_tier(brief)
    medal_badge_html = ""
    if tier and tier in _MEDAL_ACCENTS:
        ovr = _MEDAL_ACCENTS[tier]
        # Override accent so result-chip border, label-ribbon, and event
        # subtitle all pick up the tier colour automatically.
        accent = ovr["accent"]
        # Tier badge — only medals (gold/silver/bronze) reach here, so the
        # badge always carries real, non-duplicate information. It sits below
        # the result chip, top-right, next to the time (the hero element), and
        # never collides with the .label-ribbon top-left achievement label.
        badge_top = int(height * 0.215)
        font_size = max(36, int(height * 0.038))
        medal_badge_html = (
            f'<div class="tier-badge" style="position:absolute;'
            f"top:{badge_top}px;right:56px;z-index:10;"
            f"background:linear-gradient(135deg,{ovr['accent']} 0%,{ovr['accent_deep']} 100%);"
            f"color:#1a1a1a;padding:14px 28px;border-radius:999px;"
            f"font-family:'Bebas Neue','Anton',sans-serif;"
            f"font-size:{font_size}px;letter-spacing:0.14em;"
            f"font-weight:700;box-shadow:0 10px 26px rgba(0,0,0,0.50),"
            f"inset 0 2px 0 rgba(255,255,255,0.5);"
            f'border:2px solid rgba(255,255,255,0.25)">'
            f"&#9733; {ovr['badge']}</div>"
        )

    base_css = _read_text(_BASE_CSS_PATH)
    try:
        text_led_css = _read_text(_TEXT_LED_FILL_CSS_PATH)
    except Exception:
        text_led_css = ""
    # Poster @font-face declarations from _shared.css (V8.1 Issue 7 §1).
    # SELF-HOSTED (Council audit 2026-05-31): _shared.css carries relative
    # url(fonts/<name>.woff2) for all six poster families (incl. JetBrains
    # Mono). The render page is a file:// in a throwaway out_dir, so the
    # relatives won't resolve there — rewrite them to absolute file:// URLs
    # under the layouts dir. No Google Fonts CDN @import: closes the GDPR hole
    # on the posted graphic and makes renders network-independent (the old
    # version-pinned CDN URLs had also started 404ing). Same families, so
    # autofit text metrics are unchanged.
    try:
        shared_css = _read_text(_SHARED_CSS_PATH) if _SHARED_CSS_PATH.exists() else ""
    except Exception:
        shared_css = ""
    if shared_css:
        shared_css = shared_css.replace(
            "url(fonts/", f"url({(_SHARED_CSS_PATH.parent / 'fonts').as_uri()}/"
        )
    base_css = shared_css + "\n" + base_css + "\n" + text_led_css

    layers = brief.text_layers or {}
    full_name = layers.get("athlete_full_name") or ""
    first = layers.get("athlete_first_name") or ""
    # Full surname for the ghost watermark — the fillers now autofit its
    # font size (``_surname_font_px``) so even "REEKIE-AYALA" fits the
    # canvas instead of being hard-cut at 8 chars or clipped at the edge.
    surname = (layers.get("athlete_surname") or "").upper()
    label = layers.get("achievement_label") or brief.confidence_label or ""

    has_photo = bool(athlete_data_uri)
    text_led_fill_html = _build_text_led_fill_block(
        full_name=full_name,
        surname=layers.get("athlete_surname") or "",
        width=width,
        height=height,
        layers=layers,
        palette=palette,
        has_photo=has_photo,
    )

    # Optional generative background (Tier C, SEQ-4): an Imagen-built
    # brand-aware backdrop composited UNDER the deterministic text layer.
    # Behind its own opt-in flag, MEDIAHUB_GEN_BG, **default OFF** — it is a
    # billed API call, so it never spends without the operator switching it
    # on (roadmap P0 cost discipline). The legacy MEDIAHUB_DISABLE_AI_BG=1
    # kill switch still force-disables it. When off/unavailable the
    # procedural water-pattern + noise backdrop renders as before.
    # v2 archetypes have no {{AI_BG_URI}} slot, so the caller skips the
    # fetch for them — a paid API call whose output would be discarded.
    ai_bg_uri = None
    if not skip_ai_bg:
        try:
            if _gen_bg_enabled():
                from mediahub.visual.ai_background import (
                    is_available as _ai_bg_ok,
                    background_data_uri_for,
                )

                if _ai_bg_ok():
                    # Map width/height back to a format name so the cache key
                    # is stable across cards of the same shape.
                    fmt_for_bg = (
                        "feed_square"
                        if width == height
                        else ("story" if height > width * 1.5 else "feed_portrait")
                    )
                    ai_bg_uri = background_data_uri_for(brief, format_name=fmt_for_bg)
        except Exception:
            ai_bg_uri = None

    # ---- Variation axes (V9 overhaul) ----
    # The brief now carries multi-axis variation: background_style picks the
    # canvas pattern, typography_pair rebinds the headline/body fonts,
    # composition flips the cutout L/R/C, accent_style draws decorations,
    # and photo_treatment applies CSS filters to the cutout. The choices
    # ride on top of base_css via a single override <style> block + a
    # decoration overlay placeholder. Everything degrades to the legacy
    # look when a brief comes in with the default values.
    bg_style = getattr(brief, "background_style", None) or "water"
    accent_style = getattr(brief, "accent_style", None) or "brackets"
    type_pair = getattr(brief, "typography_pair", None) or "anton-inter"
    composition = getattr(brief, "composition", None) or "right"
    photo_treatment = getattr(brief, "photo_treatment", None) or "cutout"
    decoration_strength = float(getattr(brief, "decoration_strength", 0.5) or 0.5)

    variation_css_blocks: list[str] = []
    type_css = _typography_overrides_css(type_pair)
    if type_css:
        variation_css_blocks.append(type_css)
    comp_css = _composition_overrides_css(composition)
    if comp_css:
        variation_css_blocks.append(comp_css)
    photo_css = _photo_treatment_css(photo_treatment, {"accent": accent})
    if photo_css:
        variation_css_blocks.append(photo_css)

    # Inline the variation overrides at the end of the base CSS so they
    # win the cascade (they all use !important too).
    if variation_css_blocks:
        base_css = (
            base_css + "\n\n/* --- variation overrides --- */\n" + "\n".join(variation_css_blocks)
        )

    accent_overlay_html = _accent_decoration_html(
        accent_style,
        accent,
        width,
        height,
        decoration_strength,
    )

    return {
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "PRIMARY": primary,
        "PRIMARY_DEEP": primary_deep,
        "SECONDARY": secondary,
        "ACCENT": accent,
        "BASE_CSS": base_css,
        "WATER_PATTERN": _background_pattern_for(bg_style),
        "ACCENT_DECORATION": accent_overlay_html,
        "NOISE_PATTERN": _noise_pattern_data_uri(),
        "AI_BG_URI": ai_bg_uri or "",
        "ATHLETE_FULL_NAME": html_escape(full_name),
        "ATHLETE_FIRST_NAME": html_escape(first.upper()),
        "ATHLETE_SURNAME_DISPLAY": html_escape(surname),
        "EVENT_NAME": html_escape(_clean_event_name(layers.get("event_name") or "")),
        "ACHIEVEMENT_LABEL": html_escape(label),
        "MEET_NAME": html_escape(layers.get("meet_name") or ""),
        "MEET_NAME_SHORT": html_escape((layers.get("meet_name") or "")[:40]),
        "CLUB_FULL": html_escape(layers.get("club_full") or ""),
        "ATHLETE_IMG_BLOCK": _build_athlete_block(athlete_data_uri, full_name),
        "TEXT_LED_FILL_BLOCK": text_led_fill_html,
        "HAS_PHOTO": "1" if has_photo else "0",
        # Conditional wrappers — templates use {{PHOTO_ONLY_OPEN}} / {{PHOTO_ONLY_CLOSE}}
        # to bracket photo-only HTML, and {{TEXT_ONLY_OPEN}} / {{TEXT_ONLY_CLOSE}}
        # for blocks that only render in the no-photo path.
        "PHOTO_ONLY_OPEN": "" if has_photo else "<!--photo-only ",
        "PHOTO_ONLY_CLOSE": "" if has_photo else " photo-only-->",
        "TEXT_ONLY_OPEN": "<!--text-only " if has_photo else "",
        "TEXT_ONLY_CLOSE": " text-only-->" if has_photo else "",
        "LOGO_BLOCK": logo_block,
        "LOGO_MARK_MOD": logo_mark_mod,
        # User-chosen background photo for caption-led graphics: a full-bleed
        # cover image + a dark scrim so the headline/bullets stay legible.
        "BG_PHOTO_BLOCK": (
            f'<div class="bg-photo" style="background-image:url(\'{bg_photo_uri}\')"></div>'
            '<div class="bg-photo-scrim"></div>'
        )
        if bg_photo_uri
        else "",
        "RESULT_CHIP_BLOCK": result_chip,
        "SPONSOR_BLOCK": sponsor_block,
        "MEDAL_BADGE_BLOCK": medal_badge_html,
    }


def _ellipsize(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars at a word boundary with an ellipsis.

    Replaces the bare ``[:N]`` chops that left mid-word fragments like
    "County Championshi" on rendered graphics.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: max(1, limit - 1)]
    if " " in cut:
        head = cut.rsplit(" ", 1)[0].rstrip(",;:·-")
        if len(head) >= max(4, int(limit * 0.4)):
            cut = head
    return cut + "…"


def _fit_ribbon_label(label: str, base_px: int, canvas_w: int) -> tuple[str, int]:
    """Make the achievement ribbon's label always fit the canvas.

    The ``.label-ribbon`` sits at left:64px and shares the top band with
    the result chip on the right, so long AI hooks ("BREASTSTROKE
    DOMINANCE") used to overflow and render clipped at both ends. Budget
    ~55% of the canvas width, shrink the font to no less than 60% of its
    base size, then word-boundary truncate whatever still doesn't fit.
    Bebas/Anton condensed caps average ~0.52em advance width.
    """
    label = " ".join((label or "").split())
    if not label:
        return label, int(base_px)
    budget = canvas_w * 0.55 - 56  # minus ribbon padding

    def _w(text: str, px: float) -> float:
        return len(text) * 0.52 * px

    px = float(base_px)
    floor = max(18.0, base_px * 0.60)
    while px > floor and _w(label, px) > budget:
        px -= 2.0
    if _w(label, px) > budget:
        words = label.split(" ")
        kept = ""
        for word in words:
            cand = (kept + " " + word).strip()
            if kept and _w(cand + "…", px) > budget:
                break
            kept = cand
        if kept and kept != label:
            label = kept + "…"
        elif _w(label, px) > budget:
            max_chars = max(4, int(budget / (0.52 * px)) - 1)
            label = label[:max_chars] + "…"
    return label, int(px)


def _fill_individual_hero(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    s = _scale_for_format(width, height)
    repl = dict(repl)
    has_photo = repl.get("HAS_PHOTO") == "1"
    layers = brief.text_layers or {}
    # Rebuild the text-led fill block in compact mode so it does not collide
    # with the bottom fg-text + result-chip area.
    if not has_photo:
        # Skip the compact stat strip here: the event is already the subtitle
        # and the time is already the hero result chip, so the strip only
        # repeated them. Dropping it gives a clean single-chip top-right.
        repl["TEXT_LED_FILL_BLOCK"] = _build_text_led_fill_block(
            full_name=layers.get("athlete_full_name") or "",
            surname=layers.get("athlete_surname") or "",
            width=width,
            height=height,
            layers=layers,
            palette=brief.palette or {},
            has_photo=False,
            compact=True,
            skip_stat_strip=True,
        )
    repl.update(
        {
            "SURNAME_BOTTOM": str(int(height * 0.30)),
            "SURNAME_LEFT": str(-int(width * 0.04)),
            "SURNAME_RIGHT": "auto",
            "SURNAME_FONT_SIZE": str(
                _surname_font_px(
                    layers.get("athlete_surname") or "", width, height, int(height * s["surname"])
                )
            ),
            "ATHLETE_W": str(int(width * 0.82)),
            "ATHLETE_H": str(int(height * 0.78)),
            "FG_TEXT_BOTTOM": str(int(height * 0.16)),
            "FIRSTNAME_FONT_SIZE": str(int(height * s["first"])),
            "EVENT_FONT_SIZE": str(int(height * s["event"])),
            "RIBBON_FONT_SIZE": str(int(height * s["ribbon"])),
            "RESULT_FONT_SIZE": str(int(height * s["result"])),
        }
    )
    _rl, _rpx = _fit_ribbon_label(
        layers.get("achievement_label") or "", int(height * s["ribbon"]), width
    )
    repl["ACHIEVEMENT_LABEL"] = html_escape(_rl)
    repl["RIBBON_FONT_SIZE"] = str(_rpx)
    return repl


def _fill_medal_card(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    angle = (brief.text_layers or {}).get("post_angle", "") or brief.inspiration_pattern_id
    place = (brief.text_layers or {}).get("place", "") or ""
    label = (brief.text_layers or {}).get("achievement_label", "") or ""

    medal_label = "GOLD"
    if "silver" in (label + brief.inspiration_pattern_id).lower() or place.startswith("2"):
        medal_label = "SILVER"
    elif "bronze" in (label + brief.inspiration_pattern_id).lower() or place.startswith("3"):
        medal_label = "BRONZE"
    elif "gold" in (label + brief.inspiration_pattern_id).lower() or place.startswith("1"):
        medal_label = "GOLD"

    medals = {
        "GOLD": ("#FFE07A", "#9A6E0E", "1ST"),
        "SILVER": ("#F2F2F2", "#6E6E6E", "2ND"),
        "BRONZE": ("#F0BC8A", "#7A4314", "3RD"),
    }
    light, dark, place_label = medals.get(medal_label, medals["GOLD"])

    s = _scale_for_format(width, height)
    repl = dict(repl)
    _surname = (brief.text_layers or {}).get("athlete_surname") or ""
    repl.update(
        {
            "SURNAME_BOTTOM": str(int(height * 0.32)),
            "SURNAME_LEFT": str(-int(width * 0.03)),
            "SURNAME_FONT_SIZE": str(
                _surname_font_px(_surname, width, height, int(height * s["surname"] * 0.85))
            ),
            "ATHLETE_W": str(int(width * 0.55)),
            "ATHLETE_H": str(int(height * 0.78)),
            "FG_TEXT_BOTTOM": str(int(height * 0.16)),
            "FIRSTNAME_FONT_SIZE": str(int(height * s["first"])),
            "EVENT_FONT_SIZE": str(int(height * s["event"])),
            "RIBBON_FONT_SIZE": str(int(height * s["ribbon"])),
            "MEDAL_LIGHT": light,
            "MEDAL_DARK": dark,
            "MEDAL_TEXT": medal_label,
            "MEDAL_PLACE_LABEL": place_label,
            "MEDAL_SIZE": str(int(min(width, height) * 0.40)),
            "MEDAL_FONT_SIZE": str(int(min(width, height) * 0.10)),
        }
    )
    # The giant medal element already names the tier; the floating
    # "★ GOLD" pill on top of it made the same word appear three times
    # on one card (pill + medal + a "GOLDEN …" hook). Drop the pill on
    # this layout only — photo-led layouts keep it.
    repl["MEDAL_BADGE_BLOCK"] = ""
    _rl, _rpx = _fit_ribbon_label(
        (brief.text_layers or {}).get("achievement_label") or "",
        int(height * s["ribbon"]),
        width,
    )
    repl["ACHIEVEMENT_LABEL"] = html_escape(_rl)
    repl["RIBBON_FONT_SIZE"] = str(_rpx)
    return repl


def _fill_weekend_numbers(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    # Pull stat_* keys (numeric values only — skip blanks/em-dashes which
    # would render as massive bars in the 130px Anton font).
    stat_pairs: list[tuple[str, str]] = []
    for k, v in layers.items():
        if k.startswith("stat_"):
            sval = str(v).strip()
            if not sval or sval in ("—", "-", "None"):
                continue
            label = k[5:].replace("_", " ").upper()
            stat_pairs.append((sval, label))
    if not stat_pairs:
        # Sensible synthesised stats so the layout reads as a polished recap
        # even when the caller didn't pass numbers. Inferred from any swim/
        # meet metadata available on the brief.
        meet = (layers.get("meet_name") or "").strip()
        result = (layers.get("result_value") or "").strip()
        event = (layers.get("event_name") or "").strip()
        place = (layers.get("place") or "").strip()
        stat_pairs = []
        if result:
            stat_pairs.append((result, "BEST TIME"))
        if place:
            stat_pairs.append((place, "BEST FINISH"))
        if event:
            stat_pairs.append((_ellipsize(_clean_event_name(event), 14), "FEATURE EVENT"))
        # Pad to 4 with placeholder counts that read as professional copy
        defaults = [("1", "MEET"), ("✓", "COMPLETE"), ("24", "HOURS"), ("★", "HIGHLIGHT")]
        i = 0
        while len(stat_pairs) < 4 and i < len(defaults):
            stat_pairs.append(defaults[i])
            i += 1
    num_base = int(min(width, height) * 0.13)
    # Two-column grid: fit each tile's value font so a long value (e.g. an
    # event name) doesn't overflow the tile. Numeric values like "58.34" stay
    # at the full display size; "100m Freestyle" shrinks to fit rather than
    # being clipped mid-word. Anton caps advance ~0.52em.
    tile_inner = max(120, int((width - 112 - 18) / 2) - 48)
    tiles_html = ""
    for value, label in stat_pairs[:6]:
        value = _ellipsize(str(value), 16)
        fit_px = max(30, min(num_base, int(tile_inner / (max(1, len(value)) * 0.52))))
        tiles_html += (
            '<div class="stat-tile">'
            f'<div class="num" style="font-size:{fit_px}px">{html_escape(value)}</div>'
            f'<div class="label">{html_escape(label)}</div>'
            "</div>\n"
        )

    headline_line1 = (layers.get("headline_line1") or "WEEKEND").upper()
    headline_line2 = (layers.get("headline_line2") or "IN NUMBERS").upper()

    repl = dict(repl)
    repl.update(
        {
            "STAT_TILES": tiles_html,
            "SUBHEAD_TEXT": html_escape(layers.get("meet_name") or ""),
            # Subhead sits ABOVE the headline; leave room for letter-spacing.
            "SUBHEAD_TOP": str(int(height * 0.035)),
            "HEADLINE_TOP": str(int(height * 0.075)),
            "GRID_TOP": str(int(height * 0.32)),
            "GRID_BOTTOM": str(int(height * 0.16)),
            "NUM_FONT_SIZE": str(int(min(width, height) * 0.13)),
            "HEADLINE_FONT_SIZE": str(int(height * 0.085)),
            "HEADLINE_LINE1": html_escape(headline_line1),
            "HEADLINE_LINE2": html_escape(headline_line2),
        }
    )
    return repl


def _fill_athlete_spotlight(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    has_photo = repl.get("HAS_PHOTO") == "1"

    # Override the text-led-fill block: skip its bottom stat-strip (we have the
    # support-grid for that) so they don't collide. Also build a centered
    # mega-watermark to fill the middle of the canvas where the photo would be.
    if not has_photo:
        repl = dict(repl)
        # Build a custom watermark + dot-grid + diagonal that's centered, not
        # right-aligned, since spot-side now spans the full width.
        surname = (layers.get("athlete_surname") or "").upper()
        full_name = layers.get("athlete_full_name") or ""
        mega_letter = (surname or full_name or "").upper()[:14]
        mega_size = int(min(width, height) * 0.62)
        # Fit to the canvas width so the full surname reads when centred (no clip).
        mega_px = _mega_watermark_px(mega_letter, width, mega_size)
        # Position centered horizontally, in the middle vertical band
        custom_block = (
            f'<div class="txl-photo-glow" style="top:{int(height * 0.40)}px;'
            f"left:50%;transform:translateX(-50%);width:{int(min(width, height) * 0.55)}px;"
            f'height:{int(min(width, height) * 0.55)}px;"></div>'
            f'<div class="txl-accent-bar diagonal"></div>'
            f'<div class="txl-mega-initial" style="top:{int(height * 0.36)}px;'
            f"left:50%;transform:translateX(-50%);right:auto;font-size:{mega_px}px;"
            f'-webkit-text-stroke:4px rgba(255,255,255,0.16);">'
            f"{html_escape(mega_letter)}</div>"
        )
        repl["TEXT_LED_FILL_BLOCK"] = custom_block

    # Stat rows — prefer caller-provided list, then synthesise from primary swim
    rows: list[tuple[str, str, str]] = []
    if "stat_rows" in layers and isinstance(layers["stat_rows"], list):
        for r in layers["stat_rows"]:
            if isinstance(r, dict):
                rows.append((r.get("event") or "", r.get("result") or "", r.get("note") or ""))
    if not rows:
        _raw_event = layers.get("event_name") or ""
        primary_event = _clean_event_name(_raw_event)
        primary_result = layers.get("result_value") or ""
        primary_label = layers.get("achievement_label") or ""
        # The career-best card (below) already headlines the primary event +
        # result, so don't repeat it as the first stat row — start the rows
        # from the supporting facts instead. Only show the primary row when
        # there's no career-best card to carry it (i.e. no result value).
        has_career_best = bool(primary_result)
        if (primary_event or primary_result) and not has_career_best:
            rows.append((primary_event, primary_result, primary_label))
        # Synthesise supporting rows so the panel doesn't look bare
        place = layers.get("place") or ""
        if place:
            place_disp = place if place.lower().endswith(("st", "nd", "rd", "th")) else f"{place}"
            rows.append(("Final placing", place_disp, "PLACE"))
        # Course inferred from the RAW event suffix (the display name has
        # the "(SC)"/"(LC)" jargon stripped — course gets its own row).
        if _raw_event and ("LC" in _raw_event.upper() or "SC" in _raw_event.upper()):
            course = "Long Course" if "LC" in _raw_event.upper() else "Short Course"
            rows.append(("Course", course, ""))
        # Confidence label as a row when present and not redundant
        cl = (brief.confidence_label or "").strip()
        if cl and cl != primary_label:
            rows.append(("Recognition", cl, ""))

    rows_html = ""
    for ev, res, note in rows[:5]:
        rows_html += (
            '<div class="stat-row">'
            f'<div class="ev">{html_escape(ev)}</div>'
            f'<div class="rs">{html_escape(res)}</div>'
            f'<div class="lab">{html_escape(note)}</div>'
            "</div>"
        )

    # Career-best card — the headline metric for this swimmer at this meet
    cb_value = layers.get("result_value") or ""
    cb_event = _clean_event_name(layers.get("event_name") or "")
    cb_delta = (
        layers.get("recent_improvement")
        or layers.get("delta")
        or layers.get("achievement_label")
        or ""
    )
    if cb_value:
        career_best_html = (
            '<div class="career-best">'
            f'<div class="lab">Headline result · {html_escape(cb_event)}</div>'
            f'<div class="val">{html_escape(cb_value)}</div>'
        )
        if cb_delta:
            career_best_html += f'<div class="delta">{html_escape(cb_delta)}</div>'
        career_best_html += "</div>"
    else:
        career_best_html = ""

    # Bottom support grid — always shown when no photo (to fill the empty
    # left half) and when at least one secondary fact exists. Renders as a
    # full-width 4-column row at the bottom so long meet names fit.
    support_cells: list[tuple[str, str]] = []
    if layers.get("meet_name"):
        support_cells.append(("Meet", _ellipsize(layers["meet_name"], 22)))
    if layers.get("venue_name"):
        support_cells.append(("Venue", _ellipsize(layers["venue_name"], 22)))
    if layers.get("event_name"):
        ev_text = layers["event_name"]
        course = (
            "Long Course"
            if "LC" in ev_text.upper()
            else ("Short Course" if "SC" in ev_text.upper() else "Race")
        )
        support_cells.append(("Course", course))
    if layers.get("club_full"):
        support_cells.append(("Club", _ellipsize(layers["club_full"], 22)))
    support_cells = support_cells[:4]
    support_grid_html = ""
    if support_cells and not has_photo:
        cells_html = "".join(
            f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
            f'<div class="val">{html_escape(val)}</div></div>'
            for lab, val in support_cells
        )
        # Full-width row — 4 equal cells across the canvas bottom
        support_grid_html = f'<div class="support-grid full-row">{cells_html}</div>'

    side_width = int(width * (0.46 if has_photo else 0.50))
    name_size = int(height * (0.060 if not has_photo else 0.075))

    repl = dict(repl)
    repl.update(
        {
            "STAT_ROWS": rows_html,
            "SIDE_WIDTH": str(side_width),
            "SUPPORT_WIDTH": str(int(width * 0.46)),
            "ATHLETE_W": str(int(width * 0.46)),
            "ATHLETE_H": str(int(height * 0.82)),
            "NAME_FONT_SIZE": str(name_size),
            "SPOTLIGHT_TAG": "ATHLETE SPOTLIGHT",
            "CAREER_BEST_BLOCK": career_best_html,
            "SUPPORT_GRID_BLOCK": support_grid_html,
        }
    )
    return repl


def _fill_meet_preview(
    brief,
    width: int,
    height: int,
    repl: dict[str, str],
    *,
    venue_data_uri: str | None,
    venue_attribution: str = "",
) -> dict[str, str]:
    layers = brief.text_layers or {}
    repl = dict(repl)

    # Build the preview stripe (3 fact cards) shown roughly mid-canvas.
    # Always populated so the centre never reads as empty.
    cells: list[tuple[str, str]] = []
    if layers.get("meet_name"):
        cells.append(("Meet", layers["meet_name"][:32]))
    if layers.get("dates"):
        cells.append(("Dates", layers["dates"]))
    if layers.get("venue_name"):
        cells.append(("Venue", layers["venue_name"][:28]))
    if layers.get("course"):
        cells.append(("Course", layers["course"]))
    if layers.get("club_full"):
        cells.append(("Host", layers["club_full"][:28]))
    if not cells:
        cells = [("Status", "Coming up"), ("Type", "Race meet"), ("Format", "Multi-event")]
    cells = cells[:3]
    cells_html = "".join(
        f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
        f'<div class="val">{html_escape(val)}</div></div>'
        for lab, val in cells
    )
    stripe_html = f'<div class="preview-stripe">{cells_html}</div>'

    repl.update(
        {
            "VENUE_BG_URL": f"url('{venue_data_uri}')"
            if venue_data_uri
            else f"linear-gradient(180deg, {repl['PRIMARY']}, {repl['PRIMARY_DEEP']})",
            "VENUE_ATTRIBUTION": html_escape(venue_attribution),
            "VENUE_NAME": html_escape(layers.get("venue_name") or ""),
            "DATES": html_escape(layers.get("dates") or "TBA"),
            "HEADLINE": html_escape(layers.get("meet_name") or "UPCOMING MEET"),
            "HEADLINE_FONT_SIZE": str(int(height * 0.075)),
            "PREVIEW_STRIPE_BLOCK": stripe_html,
        }
    )
    return repl


def _fill_text_led_recap(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    bullets = layers.get("bullets") or []
    if not bullets:
        if layers.get("athlete_full_name"):
            bullets = [
                f"{layers.get('athlete_full_name')} — {layers.get('event_name') or ''}".strip(" —"),
                layers.get("achievement_label") or "Strong swim",
            ]
        else:
            # No real content — fall back to NEUTRAL lines built from what
            # we actually know. The old defaults here invented claims
            # ("Multiple medals on day two") on cards with no data, which
            # broke the product's "we don't invent results" promise.
            bullets = [b for b in (layers.get("meet_name"), layers.get("club_full")) if b] or [
                "Full story in the caption"
            ]
    bullets_html = ""
    for i, b in enumerate(bullets[:4], 1):
        bullets_html += (
            f'<div class="row"><span class="num">0{i}</span><span>{html_escape(b)}</span></div>'
        )
    headline_line1 = (layers.get("headline_line1") or "").upper()
    if headline_line1:
        # An explicitly-set empty line 2 means "single-line headline".
        # Only fall back to "RECAP" when the caller never set the key at
        # all (the legacy weekend-recap path) — sponsor thank-yous were
        # rendering as "ACME SPORTS RECAP" because of this default.
        if "headline_line2" in layers:
            headline_line2 = (layers.get("headline_line2") or "").upper()
        else:
            headline_line2 = "RECAP"
    else:
        headline_line1, headline_line2 = "WEEKEND", "RECAP"

    # Centre stat strip — keeps the middle of the canvas alive when bullets
    # alone don't fill the page. Caller-supplied stat_* layers win; else
    # infer from REAL fields only. No fabricated filler: a card with no
    # stats shows no strip rather than "3 VOICES / WEEK WINDOW" nonsense.
    stat_cells: list[tuple[str, str]] = []
    for k, v in layers.items():
        if k.startswith("stat_") and v not in (None, "", "—"):
            label = k[5:].replace("_", " ").upper()
            stat_cells.append((_ellipsize(str(v), 20), label))
    if not stat_cells:
        if layers.get("result_value"):
            stat_cells.append((layers["result_value"], "TIME"))
        if layers.get("event_name"):
            stat_cells.append((_ellipsize(_clean_event_name(layers["event_name"]), 14), "EVENT"))
        if layers.get("meet_name") and len(stat_cells) < 3:
            stat_cells.append((_ellipsize(layers["meet_name"], 18), "MEET"))
        if (layers.get("club_short") or layers.get("club_full")) and 0 < len(stat_cells) < 3:
            stat_cells.append(
                (_ellipsize(layers.get("club_short") or layers.get("club_full"), 14), "CLUB")
            )
    stat_cells = stat_cells[:3]
    if stat_cells:
        stats_inner = "".join(
            f'<div class="cell"><div class="num">{html_escape(v)}</div>'
            f'<div class="lab">{html_escape(l)}</div></div>'
            for v, l in stat_cells
        )
        # Size the grid to the actual cell count so 1-2 cells fill the row
        # instead of huddling in the left third of a fixed 3-column grid.
        n_cols = max(1, len(stat_cells))
        recap_stats_block = (
            f'<div class="recap-stats" style="grid-template-columns:repeat({n_cols},1fr)">'
            f"{stats_inner}</div>"
        )
    else:
        recap_stats_block = ""

    repl = dict(repl)
    repl.update(
        {
            "BULLETS_HTML": bullets_html,
            "KICKER": html_escape(layers.get("meet_name") or ""),
            "HEADLINE_LINE1": html_escape(headline_line1),
            "HEADLINE_LINE2": html_escape(headline_line2),
            "HEADLINE_FONT_SIZE": str(int(height * 0.115)),
            "RECAP_STATS_BLOCK": recap_stats_block,
        }
    )
    return repl


def _fill_story_card(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    repl = dict(repl)
    meet = layers.get("meet_name") or ""
    headline = (meet[:36] + "…") if len(meet) > 36 else meet
    if not headline:
        headline = "FEATURED RESULT"
    repl.update(
        {
            "ATHLETE_W": str(int(width * 0.78)),
            "ATHLETE_H": str(int(height * 0.42)),
            "FIRSTNAME_FONT_SIZE": str(int(height * 0.080)),
            "EVENT_FONT_SIZE": str(int(height * 0.030)),
            "RIBBON_FONT_SIZE": str(int(height * 0.028)),
            "RESULT_FONT_SIZE": str(int(height * 0.060)),
            "SURNAME_FONT_SIZE": str(
                _surname_font_px(
                    layers.get("athlete_surname") or "", width, height, int(height * 0.30)
                )
            ),
            "RESULT_VALUE_RAW": html_escape(layers.get("result_value") or "—"),
            "STORY_HEADLINE": html_escape(headline.upper()),
        }
    )
    return repl


def _fill_sponsor_branded(
    brief, width: int, height: int, repl: dict[str, str], sponsor_name: str = ""
) -> dict[str, str]:
    repl = _fill_individual_hero(brief, width, height, repl)
    repl["SPONSOR_NAME"] = html_escape(sponsor_name or "")
    return repl


def _fill_reel_cover(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    has_photo = repl.get("HAS_PHOTO") == "1"
    repl = dict(repl)
    repl["HEADLINE_FONT_SIZE"] = str(int(height * 0.08))
    repl["MEGA_FONT_SIZE"] = str(int(height * 0.16))

    if not has_photo:
        # Build a centered text-led cover
        full_name = (layers.get("athlete_full_name") or "").upper()
        surname = (layers.get("athlete_surname") or "").upper()
        first = (layers.get("athlete_first_name") or "").upper()
        event = layers.get("event_name") or ""
        result = layers.get("result_value") or ""
        sub_bits = [b for b in [event, result] if b]
        sub_text = " · ".join(sub_bits) if sub_bits else ""
        mega = surname or full_name or first
        # Long titles (multi-word meet names, double-barrelled surnames)
        # overflow the .cover-mega box at the fixed 0.16*height size.
        # Auto-fit DOWN only — short covers keep their exact historic size.
        if mega:
            from mediahub.graphic_renderer.autofit import fit_font_px

            default_px = int(height * 0.16)
            fitted = fit_font_px(
                mega,
                box_w=width * 0.88,  # .cover-mega: left 6% / right 6%
                box_h=height * 0.52,  # top 22% .. sub at bottom 26%
                font_family="Anton",
                weight=900,
                min_px=int(height * 0.05),
                max_px=default_px,
                line_height=0.86,
            )
            repl["MEGA_FONT_SIZE"] = str(min(default_px, fitted))
        repl["TEXT_LED_COVER_BLOCK"] = (
            f'<div class="cover-mega">{html_escape(mega)}</div>'
            + (f'<div class="cover-sub">{html_escape(sub_text)}</div>' if sub_text else "")
            + (
                f'<div class="cover-name">{html_escape(full_name)}</div>'
                if full_name and full_name != mega
                else ""
            )
        )
    else:
        repl["TEXT_LED_COVER_BLOCK"] = ""
    return repl


def _fill_big_number_hero(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    """Time/result as the dominant visual element — competitor 'numerical hero'.

    The numeral fills ~55% of canvas height. Event sits above as a small
    spaced-caps strip, athlete name sits below as a Bebas display row.
    """
    layers = brief.text_layers or {}
    repl = dict(repl)
    result_value = (layers.get("result_value") or "").strip() or "—"
    # Numeral size scales with both axes; aim for ~55% of canvas height for
    # a 6-char time like "2:28.21" — characters render narrower than they tax.
    char_count = max(1, len(result_value))
    # Cap so very long results don't overflow horizontally.
    by_width = (width * 0.85) / max(2, char_count) * 1.50
    by_height = height * 0.30
    hero_size = int(min(by_width, by_height))

    repl.update(
        {
            "HERO_FONT_SIZE": str(hero_size),
            "EVENT_TOP": str(int(height * 0.22)),
            "EVENT_FONT_SIZE": str(int(min(width, height) * 0.028)),
            "ATHLETE_BOTTOM": str(int(height * 0.20)),
            "NAME_FONT_SIZE": str(int(min(width, height) * 0.068)),
            "RESULT_VALUE": html_escape(result_value),
        }
    )
    return repl


def _fill_action_photo_hero(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    """Full-bleed real-photo hero — clean lower-third lockup over a brand scrim.

    The photo (HERO_PHOTO_URI) is the original, un-cutout image, supplied by
    ``render_brief`` only when a real athlete/action photo exists. When it is
    empty the template falls back to the brand gradient — this layout never
    fabricates a person (MediaHub's standing "no fake people" rule).
    """
    layers = brief.text_layers or {}
    repl = dict(repl)
    repl.update(
        {
            "NAME_FONT_SIZE": str(int(height * 0.086)),
            "EVENT_FONT_SIZE": str(int(min(width, height) * 0.026)),
            "RESULT_FONT_SIZE": str(int(height * 0.058)),
            "RESULT_VALUE_RAW": html_escape(layers.get("result_value") or ""),
        }
    )
    _rl, _rpx = _fit_ribbon_label(layers.get("achievement_label") or "", int(height * 0.030), width)
    repl["ACHIEVEMENT_LABEL"] = html_escape(_rl)
    repl["RIBBON_FONT_SIZE"] = str(_rpx)
    return repl


def _fill_stat_line(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    """Restrained editorial recap — one hero stat, generous negative space.

    The Canva-cleanliness lesson rendered in MediaHub's poster type: a kicker, a
    stacked headline (the AI hook), one big autofit hero numeral on an accent
    rule, and a tidy support row. Text-led, so it never needs a photo.
    """
    layers = brief.text_layers or {}
    repl = dict(repl)

    # Headline: prefer the AI hook, else the achievement label. A multi-word hook
    # splits across two lines (the second line picks up the accent colour).
    hook = (
        (getattr(brief, "primary_hook", "") or "").strip()
        or (layers.get("achievement_label") or "").strip()
        or "RESULT"
    ).upper()
    words = hook.split()
    if len(words) >= 2:
        mid = (len(words) + 1) // 2
        line1, line2 = " ".join(words[:mid]), " ".join(words[mid:])
    else:
        line1, line2 = hook, ""

    hero_value = (layers.get("result_value") or layers.get("place") or "—").strip()
    hero_event = _clean_event_name(layers.get("event_name") or "") or (
        layers.get("meet_name") or ""
    )

    # Fit the hero numeral to the column width so long values never overflow.
    from mediahub.graphic_renderer.autofit import fit_font_px as _fit

    hero_px = _fit(
        hero_value or "—",
        box_w=(width - 128) * 0.98,
        box_h=int(height * 0.22),
        font_family="Anton",
        weight=900,
        min_px=int(height * 0.07),
        max_px=int(height * 0.17),
        line_height=1.0,
    )

    cells: list[tuple[str, str]] = []
    name = (layers.get("athlete_full_name") or "").strip()
    if name:
        cells.append(("Swimmer", _ellipsize(name, 18)))
    place = (layers.get("place") or "").strip()
    if place:
        cells.append(("Finish", place))
    club = (layers.get("club_short") or layers.get("club_full") or "").strip()
    if club and len(cells) < 3:
        cells.append(("Club", _ellipsize(club, 18)))
    cells = cells[:3]
    support_html = "".join(
        f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
        f'<div class="v">{html_escape(val)}</div></div>'
        for lab, val in cells
    )

    repl.update(
        {
            "KICKER": html_escape(layers.get("meet_name") or layers.get("club_full") or ""),
            "HEADLINE_LINE1": html_escape(line1),
            "HEADLINE_LINE2": html_escape(line2),
            "HEADLINE_FONT_SIZE": str(int(height * 0.084)),
            "HERO_EVENT": html_escape(hero_event),
            "HERO_VALUE": html_escape(hero_value),
            "HERO_FONT_SIZE": str(hero_px),
            "SUPPORT_CELLS": support_html,
        }
    )
    return repl


# Map family → filler
_FILLERS = {
    "individual_hero": _fill_individual_hero,
    "medal_card": _fill_medal_card,
    "weekend_numbers": _fill_weekend_numbers,
    "athlete_spotlight": _fill_athlete_spotlight,
    "text_led_recap": _fill_text_led_recap,
    "story_card": _fill_story_card,
    "reel_cover": _fill_reel_cover,
    "big_number_hero": _fill_big_number_hero,
    "action_photo_hero": _fill_action_photo_hero,
    "stat_line": _fill_stat_line,
}


# ---------------------------------------------------------------------------
# Substitution
# ---------------------------------------------------------------------------


def _apply(template: str, replacements: dict[str, str]) -> str:
    out = template
    for k, v in replacements.items():
        out = out.replace("{{" + k + "}}", "" if v is None else str(v))
    return out


# ---------------------------------------------------------------------------
# Playwright runner — launch args + per-context security + per-page pixels
# ---------------------------------------------------------------------------

# Chromium launch flags shared by the one-shot path and every pooled browser, so
# a warm pooled render is byte-identical to a cold one-shot render.
_CHROMIUM_LAUNCH_ARGS = ["--no-sandbox", "--font-render-hinting=none"]


def _renderer_net_locked() -> bool:
    """True unless the operator has opened the renderer's network egress.

    Renderer lockdown (THREAT_MODEL §3): card HTML carries user-influenced
    text, so by default the render context gets NO network — only file:// (the
    page itself + self-hosted fonts/assets), data: URIs and about:blank may
    load. A template-injected https:// fetch is aborted, killing both SSRF and
    exfiltration through the renderer. Escape hatch: MEDIAHUB_RENDERER_ALLOW_NET=1.
    """
    return os.environ.get("MEDIAHUB_RENDERER_ALLOW_NET", "") != "1"


def _renderer_route_guard(route) -> None:
    """Abort any non-local subresource the card HTML tries to fetch."""
    url = route.request.url
    if url.startswith(("file://", "data:", "about:")):
        route.continue_()
    else:
        log.warning("renderer blocked network request: %s", url.split("?")[0][:200])
        route.abort()


def _new_render_context(browser, size: tuple[int, int], dpr: int):
    """Create a Chromium context sized for ``size`` at device-scale ``dpr``.

    Identical construction on the one-shot and pooled paths — same viewport,
    same device_scale_factor, same network lockdown — so pooling never changes
    a single rendered pixel.
    """
    width, height = size
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=dpr,
    )
    if _renderer_net_locked():
        ctx.route("**/*", _renderer_route_guard)
    return ctx


def _render_on_context(ctx, html: str, output_path: Path, size: tuple[int, int], dpr: int) -> int:
    """Render ``html`` to ``output_path`` on an already-built context; return bytes.

    This is the single source of render pixels — both the one-shot launch and
    the warm pool funnel through here, so a pooled render is byte-for-byte the
    same as a cold one.

    V8.1 Issue 7 upgrades:
      - device_scale_factor (default 2) for sharper text + gradients; the
        captured PNG is then resampled back down to the target dimensions with
        PIL Lanczos for a clean final size.
      - Awaits ``document.fonts.ready`` so @font-face WOFF2 fetches finish
        before the screenshot fires.
    Both degrade gracefully: if PIL is missing or the larger PNG is already the
    target size, we just write what we have.
    """
    width, height = size
    # The page MUST be navigated as a real file:// document, not injected via
    # set_content(): set_content leaves the document on an about:blank origin,
    # and Chromium refuses to fetch file:// subresources from there — so every
    # self-hosted @font-face (url(file://...woff2), rewritten from _shared.css)
    # silently failed and text fell back to generic sans. Writing the HTML next
    # to the output and goto()-ing it puts the document on the file scheme,
    # which is allowed to load file fonts.
    page_path = output_path.with_suffix(output_path.suffix + ".render.html")
    page_path.write_text(html, encoding="utf-8")
    page = ctx.new_page()
    try:
        page.goto(page_path.as_uri(), wait_until="networkidle", timeout=30_000)
        # Wait for ALL @font-face downloads to settle. Playwright exposes
        # `evaluate` with a Promise return — the inner JS resolves once
        # `document.fonts.ready` does. Falls back to a timed pause if the
        # page doesn't expose document.fonts at all.
        try:
            page.evaluate(
                "() => (document.fonts && document.fonts.ready) "
                "? document.fonts.ready.then(() => true) : true"
            )
        except Exception:
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
        png = page.screenshot(
            full_page=False,
            type="png",
            omit_background=False,
            clip={"x": 0, "y": 0, "width": width, "height": height},
        )
    finally:
        # Close the page (NOT the context) so a pooled context stays warm for
        # the next render while per-render page memory is released immediately.
        try:
            page.close()
        except Exception:
            pass
        try:
            page_path.unlink()
        except OSError:
            pass

    # If we rendered at DPR>1, the screenshot will be width*dpr by height*dpr;
    # downsample with high-quality Lanczos so the final PNG matches the target
    # canvas dimensions while preserving the sharper sub-pixel rendering.
    if dpr > 1 and Image is not None:
        try:
            from io import BytesIO

            src_img = Image.open(BytesIO(png))
            if src_img.size != (width, height):
                src_img = src_img.convert("RGBA") if src_img.mode != "RGBA" else src_img
                resized = src_img.resize((width, height), Image.LANCZOS)
                buf = BytesIO()
                resized.save(buf, format="PNG", optimize=True)
                png = buf.getvalue()
        except Exception:
            # Fall back to the high-DPR PNG; size on disk will be larger
            # but the contents are still correct.
            pass

    output_path.write_bytes(png)
    # G1.24 cache: persist the finished PNG so the next identical
    # (HTML, size, DPR) render is a cache hit (served by render_html_to_png
    # below without launching Chromium). The key is the same pure function of
    # (html, size, dpr) the dispatcher checks, so pooled and one-shot renders
    # populate one shared cache.
    _render_cache.store_png(_render_cache.png_cache_key(html, width, height, dpr), png)
    return len(png)


# ---------------------------------------------------------------------------
# Headless-Chromium context pool (roadmap G1.23)
# ---------------------------------------------------------------------------
#
# Launching Chromium — and even spinning up the Playwright driver subprocess —
# costs hundreds of milliseconds to a couple of seconds. A content pack renders
# many cards back-to-back (each at 2–3 formats), so paying that cost per render
# dominates a batch. This pool keeps a small set of Chromium browsers WARM and
# reuses their contexts across renders, turning a batch from
# ``N × (launch + render)`` into ``launch + N × render``.
#
# Sync Playwright objects are bound to the OS thread that created them — you
# cannot create a browser on one thread and close it on another. So the pool
# owns its own long-lived worker threads: each worker creates, uses, and tears
# down its browser entirely on its own thread. That also means warm browsers
# survive across the transient ``ThreadPoolExecutor`` that ``render_all_formats``
# spins up per call, and are cleaned up deterministically when the pool shuts
# down (no leaked Chromium processes).
#
# Pooling is OFF for a lone render (byte-identical, zero lingering process) and
# turns ON inside a ``render_pool_session()`` — which the content-pack batch
# loop opens — or globally when ``MEDIAHUB_RENDER_POOL_ALWAYS`` is set. The
# master kill switch ``MEDIAHUB_RENDER_POOL=0`` forces the one-shot path
# everywhere. On any pool-infrastructure failure the renderer falls back to a
# one-shot launch, so a broken pool degrades to "slow but correct", never broken.

# Each worker keeps at most this many warm contexts (keyed by size/dpr/net). A
# content pack uses a tiny fixed set of formats, so this is never a real cap;
# it just bounds memory if an unusual mix of sizes streams through one worker.
_CTX_CACHE_CAP = 6
# Hard ceiling on how long a single pooled render may take before the caller
# gives up on the pool and falls back to a one-shot launch (renders are bounded
# by the 30s goto timeout, so this only fires if a worker is truly wedged).
_POOL_SUBMIT_TIMEOUT_S = 90.0
# Sentinel pushed onto the task queue to tell a worker to shut down.
_POOL_SHUTDOWN = object()


class _PoolUnavailable(RuntimeError):
    """Raised when the pool cannot service a render (so the caller one-shots)."""


def _pool_enabled() -> bool:
    """Master switch. Default ON; ``MEDIAHUB_RENDER_POOL=0`` is the kill switch."""
    return _flag("MEDIAHUB_RENDER_POOL", "1")


def _pool_always_on() -> bool:
    """When set, every render (even outside a session) uses a process-wide pool."""
    return _flag("MEDIAHUB_RENDER_POOL_ALWAYS", "0")


def _pool_size() -> int:
    """Number of warm browsers. Defaults to the render-worker count (≈3)."""
    raw = os.environ.get("MEDIAHUB_RENDER_POOL_SIZE") or os.environ.get(
        "MEDIAHUB_RENDER_WORKERS", "3"
    )
    try:
        return max(1, min(8, int(raw)))
    except Exception:
        return 3


def _is_closed_error(exc: Exception) -> bool:
    """Heuristic: did Chromium / the context / the page die under us?"""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(s in text for s in ("closed", "crash", "disconnected", "target page"))


class _RenderWorker(threading.Thread):
    """A long-lived thread owning one warm Chromium browser + a context cache.

    All Playwright calls for this worker's browser happen on this thread, which
    is the only thread allowed to touch them. Tasks arrive on a shared queue;
    results come back via per-task ``Future`` objects.
    """

    def __init__(self, task_q: "queue.Queue", broken: threading.Event) -> None:
        super().__init__(name="mh-render-pool", daemon=True)
        self._q = task_q
        self._broken = broken
        self._pw = None
        self._browser = None
        self._contexts: "OrderedDict[tuple, Any]" = OrderedDict()

    # -- browser lifecycle (all on this thread) ----------------------------
    def _launch_browser(self) -> None:
        self._browser = self._pw.chromium.launch(args=_CHROMIUM_LAUNCH_ARGS)

    def _recreate_browser(self) -> None:
        """Tear the (probably-dead) browser down and launch a fresh one."""
        for ctx in self._contexts.values():
            try:
                ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        self._launch_browser()

    def _context_for(self, size: tuple[int, int], dpr: int):
        key = (size[0], size[1], dpr, _renderer_net_locked())
        ctx = self._contexts.get(key)
        if ctx is not None:
            self._contexts.move_to_end(key)
            return ctx
        ctx = _new_render_context(self._browser, size, dpr)
        self._contexts[key] = ctx
        while len(self._contexts) > _CTX_CACHE_CAP:
            _old_key, old_ctx = self._contexts.popitem(last=False)
            try:
                old_ctx.close()
            except Exception:
                pass
        return ctx

    def _render(self, html: str, output_path: Path, size: tuple[int, int], dpr: int) -> int:
        try:
            ctx = self._context_for(size, dpr)
            return _render_on_context(ctx, html, output_path, size, dpr)
        except Exception as exc:
            # Browser/context died mid-batch — recreate once and retry so a
            # single Chromium hiccup doesn't fail the whole pack.
            if _is_closed_error(exc):
                log.warning("render pool: browser closed mid-render, recreating (%s)", exc)
                self._recreate_browser()
                ctx = self._context_for(size, dpr)
                return _render_on_context(ctx, html, output_path, size, dpr)
            raise

    # -- thread body -------------------------------------------------------
    def run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            self._pw = sync_playwright().start()
            self._launch_browser()
        except Exception as exc:
            # Could not stand up a warm browser: mark the pool broken so
            # submitters fall back to a one-shot launch (which surfaces the
            # real error honestly), and exit WITHOUT draining the queue so a
            # healthy sibling worker can still pick the tasks up.
            log.warning("render pool worker failed to start: %s", exc)
            self._broken.set()
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass
            return

        try:
            while True:
                task = self._q.get()
                try:
                    if task is _POOL_SHUTDOWN:
                        return
                    html, output_path, size, dpr, fut = task
                    if not fut.set_running_or_notify_cancel():
                        continue
                    try:
                        fut.set_result(self._render(html, output_path, size, dpr))
                    except Exception as exc:
                        fut.set_exception(exc)
                finally:
                    self._q.task_done()
        finally:
            # Teardown on this (the owning) thread — never cross-thread.
            for ctx in self._contexts.values():
                try:
                    ctx.close()
                except Exception:
                    pass
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass


class _RenderPool:
    """A fixed set of warm-browser workers sharing one task queue."""

    def __init__(self, size: int) -> None:
        self._q: "queue.Queue" = queue.Queue()
        self._broken = threading.Event()
        self._size = max(1, size)
        self._workers = [_RenderWorker(self._q, self._broken) for _ in range(self._size)]
        for w in self._workers:
            w.start()

    def submit(self, html: str, output_path: Path, size: tuple[int, int], dpr: int) -> int:
        if self._broken.is_set():
            raise _PoolUnavailable("render pool has no live browser")
        fut: "Future[int]" = Future()
        self._q.put((html, output_path, size, dpr, fut))
        # Poll the future rather than block forever: if a worker fails to stand
        # up its browser AFTER we queued (so ``_broken`` flips under us), wake
        # within the poll interval and bail to a one-shot launch instead of
        # hanging on a task no live worker will ever serve.
        deadline = time.monotonic() + _POOL_SUBMIT_TIMEOUT_S
        while True:
            try:
                return fut.result(timeout=0.5)
            except _FutureTimeout:
                if self._broken.is_set():
                    raise _PoolUnavailable("render pool lost its browser") from None
                if time.monotonic() >= deadline:
                    raise _PoolUnavailable(
                        f"render pool timed out after {_POOL_SUBMIT_TIMEOUT_S}s"
                    ) from None

    def shutdown(self) -> None:
        for _ in self._workers:
            self._q.put(_POOL_SHUTDOWN)
        for w in self._workers:
            try:
                w.join(timeout=15.0)
            except Exception:
                pass


# Process-global pool state, guarded by one lock. ``_POOL`` is the live pool (or
# None); ``_SESSION_DEPTH`` ref-counts nested ``render_pool_session`` scopes so
# only the outermost one warms and tears the pool down.
_POOL: Optional[_RenderPool] = None
_SESSION_DEPTH = 0
_POOL_LOCK = threading.RLock()


def warm_render_pool(size: Optional[int] = None) -> Optional[_RenderPool]:
    """Start the process-wide render pool if pooling is enabled. Idempotent."""
    global _POOL
    if not _pool_enabled():
        return None
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = _RenderPool(size or _pool_size())
        return _POOL


def shutdown_render_pool() -> None:
    """Tear the process-wide render pool down (safe to call repeatedly)."""
    global _POOL, _SESSION_DEPTH
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
        _SESSION_DEPTH = 0
    if pool is not None:
        pool.shutdown()


def render_pool_active() -> bool:
    """True when a warm render pool is currently serving renders."""
    with _POOL_LOCK:
        return _POOL is not None


@contextmanager
def render_pool_session(size: Optional[int] = None) -> Iterator[None]:
    """Keep one warm Chromium pool alive for the duration of a batch render.

    Wrap a loop that renders many cards in this and every ``render_html_to_png``
    inside it reuses warm browsers instead of relaunching Chromium each time.
    Nesting is ref-counted — only the outermost scope warms and tears down — so
    callers can open a session defensively without worrying about double work.
    A no-op when pooling is disabled (``MEDIAHUB_RENDER_POOL=0``).
    """
    global _SESSION_DEPTH
    if not _pool_enabled():
        yield
        return
    with _POOL_LOCK:
        _SESSION_DEPTH += 1
        outermost = _SESSION_DEPTH == 1
        if outermost:
            warm_render_pool(size)
    try:
        yield
    finally:
        with _POOL_LOCK:
            _SESSION_DEPTH = max(0, _SESSION_DEPTH - 1)
            tear_down = _SESSION_DEPTH == 0
        if tear_down:
            shutdown_render_pool()


def _active_pool() -> Optional[_RenderPool]:
    """The pool to use for the current render, or None for the one-shot path."""
    if not _pool_enabled():
        return None
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
    if _pool_always_on():
        return warm_render_pool()
    return None


# A broken process-wide pool is torn down at exit; daemon workers wouldn't block
# shutdown, but this closes their Chromium processes promptly.
atexit.register(shutdown_render_pool)


def _produce_png(html: str, output_path: Path, size: tuple[int, int], dpr: int) -> int:
    """Render (or cache-serve) the canonical target-size PNG to ``output_path``.

    This is the format-agnostic render core: the G1.24 PNG cache, the G1.23 warm
    pool, and the one-shot Chromium fallback, all keyed on ``dpr`` passed in by
    the caller. ``render_html_to_png`` wraps it to add the output-format encode.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = size

    # G1.24 incremental render-stage cache: the screenshot is a pure function of
    # (final HTML, canvas size, DPR), so an identical card reuses the previously
    # rendered PNG byte-for-byte and never launches Chromium — nor the pool. A
    # warm hit even serves when Playwright is absent, so this check sits ahead of
    # the import and the pool dispatch.
    _cache_key = _render_cache.png_cache_key(html, width, height, dpr)
    _cached_png = _render_cache.get_cached_png(_cache_key)
    if _cached_png is not None:
        output_path.write_bytes(_cached_png)
        return len(_cached_png)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Playwright not installed: {e}")

    pool = _active_pool()
    if pool is not None:
        try:
            return pool.submit(html, output_path, size, dpr)
        except _PoolUnavailable as exc:
            # Pool can't serve this render — fall through to a one-shot launch
            # so the render still succeeds (just without the warm-reuse win).
            log.warning("render pool unavailable, falling back to one-shot: %s", exc)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=_CHROMIUM_LAUNCH_ARGS)
        try:
            ctx = _new_render_context(browser, size, dpr)
            return _render_on_context(ctx, html, output_path, size, dpr)
        finally:
            browser.close()


def render_html_to_png(
    html: str,
    output_path: str | Path,
    size: tuple[int, int],
    *,
    image_format: str | None = None,
    quality=None,
) -> int:
    """Headless-Chromium render; returns bytes written. Raises if Playwright is unavailable.

    Routes through the warm render pool when one is active (see
    ``render_pool_session``); otherwise launches a fresh one-shot Chromium. Both
    paths share ``_render_on_context``, so the rendered PNG is identical either
    way, and the G1.24 cache reuses it across calls.

    G1.14 — output format + quality profiles:
      - ``image_format`` picks the still format (``"png"`` (default), ``"webp"``,
        ``"avif"``, ``"jpeg"``). When None it's inferred from the output path's
        suffix, so ``foo.webp`` writes WebP with no extra argument.
      - ``quality`` is a :class:`QualityProfile` or a profile name
        (``"fast"``/``"standard"``/``"high"``); None uses the active profile from
        ``MEDIAHUB_RENDER_QUALITY``. The profile drives both the screenshot DPR
        and the encoder settings.
    The canonical rendered/cached artifact is always a target-size PNG; a
    non-PNG output renders that PNG to a temp sibling, then transcodes it — so
    the pool and cache stay shared across formats and the default PNG path is
    byte-identical. A WebP/AVIF the deployment's Pillow can't encode is an honest
    ``RenderEncodeError`` rather than a mislabelled file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = _coerce_profile(quality)
    img_format = _resolve_image_format(image_format, output_path)
    # DPR resolution: an explicit MEDIAHUB_RENDER_DPR is the ops override and
    # always wins (handled inside _dpr_render). With it unset, a caller-supplied
    # ``quality`` profile drives the DPR; otherwise the env profile/default does.
    dpr = _dpr_render()
    if quality is not None and os.environ.get("MEDIAHUB_RENDER_DPR", "").strip() == "":
        dpr = profile.dpr

    # PNG: the canonical artifact is exactly the output — unchanged historic path.
    if img_format == "PNG":
        return _produce_png(html, output_path, size, dpr)

    # Non-PNG: render the canonical PNG to a temp sibling, then transcode it to
    # the requested format under the active profile.
    png_path = output_path.with_name(output_path.name + ".g114src.png")
    try:
        _produce_png(html, png_path, size, dpr)
        if Image is None:
            raise RenderEncodeError(f"{img_format} output requires Pillow, which is not installed")
        try:
            with Image.open(png_path) as im:
                im.load()
                data = _encode_image(im, img_format, profile)
        except RenderEncodeError:
            raise
        except Exception as exc:
            raise RenderEncodeError(f"failed to encode {img_format} output: {exc}")
        output_path.write_bytes(data)
        return len(data)
    finally:
        try:
            png_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Generation Engine v2 — Tier A render helpers (gated by MEDIAHUB_GEN_V2)
# ---------------------------------------------------------------------------


# NB: hex parsing reuses the module-level ``_hex_to_rgb`` (defined above with the
# other colour helpers). A second definition here would shadow it and silently
# change ``darken``/``lighten``'s malformed-input fallback on the flag-OFF path.


def _rel_luminance(hex_colour: str) -> float:
    """WCAG relative luminance (0=black … 1=white). Deterministic colour maths."""

    def _chan(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_colour)
    return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)


def _on_color(hex_colour: str) -> str:
    """Black or white — whichever reads better as a foreground on ``hex_colour``."""
    return "#0B0B0C" if _rel_luminance(hex_colour) > 0.42 else "#FFFFFF"


def _contrast_ratio(c1: str, c2: str) -> float:
    """WCAG contrast ratio (1..21) between two hex colours."""
    hi = max(_rel_luminance(c1), _rel_luminance(c2))
    lo = min(_rel_luminance(c1), _rel_luminance(c2))
    return (hi + 0.05) / (lo + 0.05)


def _legible_accent(primary: str) -> str:
    """A same-hue brand tint that CLEARS the compliance gate against ``primary``.

    Lightens a dark primary / darkens a light one, stepping the amount up until
    the tint reads both as kicker text on the primary ground AND as a result-chip
    background behind primary-coloured text (both APCA directions ≥ the gate
    threshold). Used only when the club provides no usable accent — never
    overrides a real, contrasting brand accent.
    """
    from mediahub.quality.compliance import is_legible

    dark = _rel_luminance(primary) < 0.45
    for amt in (0.62, 0.74, 0.85, 0.92, 0.97):
        cand = lighten(primary, amt) if dark else darken(primary, amt)
        if is_legible(cand, primary) and is_legible(primary, cand):
            return cand
    return "#FFFFFF" if dark else "#0B0B0C"  # last resort: maximum contrast


def _fit_one_line_px(
    text: str,
    box_w: float,
    box_h: float,
    *,
    font_family: str,
    weight,
    min_px: int,
    max_px: int,
) -> int:
    """Largest int px at which ``text`` fits on **one line** in ``box_w`` (≤ ``box_h``).

    The v2 hero slots render with ``white-space: nowrap``, so they must be sized
    single-line. ``autofit.fit_font_px`` word-*wraps* to measure, which over-sizes
    a multi-word surname ("Van Dyk") that then overflows on the one forced line.
    """
    from mediahub.graphic_renderer.autofit import em_width

    if not text or not text.strip():
        return max_px
    ew = em_width(text, font_family=font_family, weight=weight)
    if ew <= 0:
        return max_px
    px = min(int(box_w / ew), int(box_h))
    return max(min_px, min(max_px, px))


# v2 hero archetypes whose surname / result sits in ONE dominant autofit slot
# that is tall enough to carry a balanced second line. For these, a compound
# surname or a split-time result is wrapped + balanced (G1.12) instead of forced
# onto a single shrinking line; every other archetype keeps the single-line fit.
# (Surname slots: mega_surname_bleed/minimal_type_poster use the mega-name box,
# split_diagonal_hero uses the surname box. Result slots: the two big-numeral
# archetypes use the mega-result box.)
_MULTILINE_SURNAME_ARCHETYPES = frozenset(
    {"mega_surname_bleed", "minimal_type_poster", "split_diagonal_hero"}
)
_MULTILINE_RESULT_ARCHETYPES = frozenset({"big_number_dominant", "cornerstone_numeral"})


def _mh_role_vars(palette: dict, brand_kit=None) -> dict[str, str]:
    """Map the club's CANONICAL brand colours to the v2 ``--mh-*`` role tokens.

    v2 keeps brand identity *stable* — unlike the v1 seed-rotated palette, which
    can swap which brand colour plays "primary" and turn a navy+gold club's
    ground muddy. So primary/accent come from the ``BrandKit`` when present and
    only fall back to the brief palette otherwise. Deterministic colour maths
    (``darken`` + WCAG luminance) fill surface/on-*/outline; no brand colour is
    invented. ``surface`` is a deep brand-tinted ground, ``on-*`` are
    contrast-picked, and the hairline ``outline`` is a translucent on-colour.
    """

    primary = getattr(brand_kit, "primary_colour", None) if brand_kit is not None else None
    secondary = getattr(brand_kit, "secondary_colour", None) if brand_kit is not None else None
    accent = getattr(brand_kit, "accent_colour", None) if brand_kit is not None else None

    # _is_brand_hex is strict (3/6-digit only), so a junk value can't slip a
    # ``;``/``}`` into the injected ``:root{}`` block, and darken/_on_color always
    # receive a parseable colour.
    if not _is_brand_hex(primary):
        primary = palette.get("primary")
    if not _is_brand_hex(primary):
        primary = "#0A2540"
    if not _is_brand_hex(secondary):
        secondary = palette.get("secondary")
    if not _is_brand_hex(secondary):
        secondary = darken(primary, 0.40)

    # The accent paints kickers/labels and the result chip, so it MUST contrast
    # with the primary ground. Prefer an explicit accent; else the secondary only
    # when it actually reads (navy+gold → gold); else a legible brand tint. The
    # "does it read" test is the deterministic APCA compliance gate (Tier B §5.5),
    # the same gate that ranks the LLM director's pool — so the Tier A accent
    # repair and the Tier B pool ranking judge legibility by one shared measure.
    # Without this, a single-colour kit (accent=None, secondary=#000000 by the
    # BrandKit default) collapses the accent to black and hides the result time.
    if not _is_brand_hex(accent):
        accent = palette.get("accent")
    if not _is_brand_hex(accent):
        from mediahub.quality.compliance import is_legible

        # Use the secondary only when it reads BOTH as kicker text on the ground
        # and as a chip behind primary text; else derive a gate-passing tint.
        if is_legible(secondary, primary) and is_legible(primary, secondary):
            accent = secondary
        else:
            accent = _legible_accent(primary)

    surface = darken(primary, 0.50)
    on_primary = _on_color(primary)
    on_surface = _on_color(surface)
    outline = "rgba(255,255,255,0.20)" if on_primary == "#FFFFFF" else "rgba(0,0,0,0.20)"
    return {
        "--mh-primary": primary,
        "--mh-secondary": secondary,
        "--mh-accent": accent,
        "--mh-surface": surface,
        "--mh-on-primary": on_primary,
        "--mh-on-surface": on_surface,
        "--mh-outline": outline,
    }


# Allowed manual-crop tokens for the UI 1.18 inspector. A strict allow-list so
# a user-supplied object-position can never inject CSS into the :root{} block.
_PHOTO_POS_KEYWORDS = {"left", "right", "top", "bottom", "center"}


def _sanitise_photo_pos(value: str) -> str:
    """Return a safe CSS ``object-position`` from a manual-crop request, or ''.

    Accepts one or two tokens, each either an allow-listed keyword
    (left/right/top/bottom/center) or a percentage in 0–100 (``"25%"``).
    Anything else — units, ``url()``, semicolons, braces — yields ``""`` so the
    caller falls back to the deterministic saliency focus. Defence-in-depth: the
    value is injected verbatim into a ``:root{…}`` CSS block.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    tokens = raw.split()
    if not (1 <= len(tokens) <= 2):
        return ""
    clean: list[str] = []
    for tok in tokens:
        if tok in _PHOTO_POS_KEYWORDS:
            clean.append(tok)
            continue
        if tok.endswith("%"):
            num = tok[:-1]
            try:
                pct = float(num)
            except ValueError:
                return ""
            if 0 <= pct <= 100 and num.replace(".", "", 1).isdigit():
                clean.append(tok)
                continue
        return ""
    return " ".join(clean)


def _v2_photo_position(athlete_path) -> str:
    """CSS ``object-position`` that keeps the saliency focus in frame.

    Delegates to ``saliency.focus_position`` — the same deterministic helper
    the motion compositions consume, so the still and the video steer a photo
    identically. Safe default on any failure.
    """
    try:
        from mediahub.graphic_renderer.saliency import focus_position

        return focus_position(athlete_path, "4:5")
    except Exception:
        return "center 28%"


def _v2_hero_stat(brief) -> str:
    """The optional emphasis line for an archetype's stat slot.

    Honest by construction: only real brief text is used (an explicit
    ``hero_stat``/``context`` layer if the pipeline set one), never a fabricated
    number. Empty is fine — every v2 archetype collapses the slot gracefully.
    """
    layers = brief.text_layers or {}
    return (layers.get("hero_stat") or layers.get("context") or "").strip()


# The compositional slots a DesignSpec colour-role assignment may repaint,
# mapped to the renderer var each one drives. The headline slot is handled
# separately (it must stay an on-colour of the final ground).
_ASSIGN_SLOT_TO_VAR: dict[str, str] = {
    "ground": "--mh-primary",
    "surface": "--mh-surface",
    "accent": "--mh-accent",
}


def _apply_role_assignment(root_vars: dict[str, str], assignment: dict) -> dict[str, str]:
    """Apply the director's colour-role assignment — only if it stays legible.

    ``assignment`` maps compositional slots (ground/surface/headline/accent)
    to token *role names* (Tier B §5.4); each role resolves to the hex the
    Tier A baseline already computed, so no colour is ever invented. The
    reassigned set ships ONLY when the full APCA compliance gate passes;
    otherwise the brand-safe baseline returns unchanged (legibility beats art
    direction, deterministically).
    """
    from mediahub.quality.compliance import check_roles

    role_hex = {
        role: root_vars.get("--mh-" + role.replace("_", "-"))
        for role in ("primary", "secondary", "surface", "accent", "on_primary", "on_surface")
    }
    cand = dict(root_vars)
    changed = False
    for slot, var in _ASSIGN_SLOT_TO_VAR.items():
        hex_value = role_hex.get(str(assignment.get(slot) or ""))
        if isinstance(hex_value, str) and hex_value.startswith("#") and cand.get(var) != hex_value:
            cand[var] = hex_value
            changed = True
    head = role_hex.get(str(assignment.get("headline") or ""))
    new_on_primary = (
        head if isinstance(head, str) and head.startswith("#") else _on_color(cand["--mh-primary"])
    )
    if cand.get("--mh-on-primary") != new_on_primary:
        changed = True
    if not changed:
        return root_vars
    cand["--mh-on-primary"] = new_on_primary
    cand["--mh-on-surface"] = _on_color(cand["--mh-surface"])
    cand["--mh-outline"] = (
        "rgba(255,255,255,0.20)" if cand["--mh-on-primary"] == "#FFFFFF" else "rgba(0,0,0,0.20)"
    )
    return cand if check_roles(cand).passes else root_vars


def resolved_role_vars_for_brief(brief, brand_kit=None) -> dict[str, str]:
    """The exact ``--mh-*`` set a v2 render of ``brief`` paints.

    Single source of truth shared by the archetype fill and the Tier B
    candidate-pool compliance scoring: Tier A brand-role baseline → the
    director's APCA-gated colour-role assignment → the medal tint (the metal
    IS the information, so it wins the accent — behind the same gate).
    """
    root_vars = _mh_role_vars(dict(brief.palette or {}), brand_kit)
    assignment = getattr(brief, "colour_role_assignment", None) or {}
    if isinstance(assignment, dict) and assignment:
        root_vars = _apply_role_assignment(root_vars, assignment)
    tier = _detect_medal_tier(brief)
    if tier and tier in _MEDAL_ACCENTS:
        from mediahub.quality.compliance import is_legible

        ground = root_vars["--mh-primary"]
        for metal in (_MEDAL_ACCENTS[tier]["accent"], _MEDAL_ACCENTS[tier]["accent_deep"]):
            if is_legible(metal, ground) and is_legible(ground, metal):
                root_vars = {**root_vars, "--mh-accent": metal}
                break
    return root_vars


def _v2_style_pack_overlay(brief, width: int, height: int) -> str:
    """The injected overlay markup for the brief's v2 style pack (or "").

    Resolves ``brief.style_pack`` (a ``graphic_renderer.style_packs`` pack id)
    and builds its ground/texture/accent-geometry overlay. An empty/unknown
    pack id → "" (the undecorated card), so every legacy/flag-off brief renders
    exactly as before. Any failure degrades silently to the bare card — a pack
    is decoration, never load-bearing.
    """
    pack_id = (getattr(brief, "style_pack", "") or "").strip()
    if not pack_id:
        return ""
    try:
        from mediahub.graphic_renderer import style_packs as _sp

        pack = _sp.style_pack_from_id(pack_id)
        if pack is None:
            return ""
        return _sp.pack_overlay_html(pack, width=width, height=height)
    except Exception:
        return ""


# 1.9 — per-slot text effects ride the substituted text VALUE (archetype-
# agnostic), so no v2 template is edited and an empty effect map leaves every
# card byte-identical. This maps a design-spec text-effect slot to the repl key
# whose value it decorates.
_TEXT_EFFECT_SLOT_KEYS: dict[str, str] = {
    "headline": "ATHLETE_SURNAME_DISPLAY",
    "result": "RESULT_VALUE",
    "kicker": "ACHIEVEMENT_LABEL",
    "event": "EVENT_NAME",
    "meta": "MEET_NAME",
}


def _unescape_basic(s: str) -> str:
    """Reverse ``html_escape`` + drop ``<br>`` — for feeding curve's SVG raw text."""
    return (
        s.replace("<br>", " ")
        .replace("<br/>", " ")
        .replace("<br />", " ")
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _apply_text_effects_to_repl(repl: dict, effects: dict, root_vars: dict) -> None:
    """Wrap effect-bearing slot values in APCA-policed effect spans / curve SVG.

    Mutates ``repl`` in place. Reads the card's resolved role colours from
    ``root_vars`` so each effect tracks the actual ground/ink/accent (medal tints
    included), and the renderer-side APCA gate downgrades an illegible effect to a
    safe outline. Unknown slots/effects are ignored and an empty slot value is
    skipped — so this can only decorate, never break, a card.
    """
    try:
        from mediahub.graphic_renderer import text_effects as _fx
    except Exception:
        return
    ground = root_vars.get("--mh-primary") or "#101010"
    ink = root_vars.get("--mh-on-primary") or "#FFFFFF"
    accent = root_vars.get("--mh-accent") or ink
    try:
        on_accent = _on_color(accent)
    except Exception:
        on_accent = "#FFFFFF"
    for slot, effect in effects.items():
        key = _TEXT_EFFECT_SLOT_KEYS.get(str(slot).strip().lower())
        if not key:
            continue
        value = repl.get(key) or ""
        if not value:
            continue
        try:
            res = _fx.effect_css(
                str(effect), ground=ground, ink=ink, accent=accent, on_accent=on_accent
            )
        except Exception:
            continue
        if res.is_noop:
            continue
        if res.svg:
            repl[key] = _fx.curve_text_svg(
                _unescape_basic(value), fill="currentColor", font_family="inherit"
            )
        else:
            repl[key] = _fx.apply_to_value(value, res)


def _fill_v2_archetype(
    brief,
    width,
    height,
    base_repl,
    *,
    athlete_path=None,
    brand_kit=None,
    photo_pos_override: str = "",
) -> dict:
    """Replacements for a ``layouts/v2`` archetype: roles + autofit + saliency.

    Starts from the shared replacements (names/event/logo/photo already filled),
    adds the result + hero-stat slots the v2 layouts use, and appends one
    ``:root{…}`` block to BASE_CSS carrying the brand role tokens, the
    autofit-computed hero sizes, and the saliency photo position.

    ``photo_pos_override``: when a non-empty CSS ``object-position`` value is
    given (the UI 1.18 inspector's manual crop, e.g. ``"left top"``), it
    replaces the deterministic saliency focus for ``--mh-photo-pos`` — an
    explicit human override on top of the automatic crop, never AI-chosen.
    """
    repl = dict(base_repl)
    layers = brief.text_layers or {}

    result = layers.get("result_value") or ""
    surname = (layers.get("athlete_surname") or "").upper()
    repl["RESULT_VALUE"] = html_escape(result)
    repl["HERO_STAT"] = html_escape(_v2_hero_stat(brief))
    # The v1 accent-decoration overlay targets the v1 `.canvas` and would paint a
    # stray band on a v2 composition, so it stays suppressed. Instead the v2
    # ``{{ACCENT_DECORATION}}`` slot (the last child inside every archetype root)
    # carries the brief's **style pack** — the ground/texture/accent-geometry
    # overlay that turns the v2 archetypes into thousands of distinct, brand-safe
    # templates (``graphic_renderer.style_packs``). The bare pack (and any
    # legacy brief with no ``style_pack``) yields "", i.e. the undecorated card.
    repl["ACCENT_DECORATION"] = _v2_style_pack_overlay(brief, width, height)

    # Tier A baseline → director's APCA-gated colour-role assignment → medal
    # tint (the metal IS the information, gated the same way). One resolver,
    # shared with the Tier B pool's compliance scoring.
    root_vars = resolved_role_vars_for_brief(brief, brand_kit)
    # Size the hero slots SINGLE-LINE: the v2 layouts render name/result with
    # `white-space: nowrap`, so a long or multi-word surname ("Van Dyk") must
    # shrink rather than overflow. The per-layout defaults handle the short case.
    # Per-format autofit boxes (G1.3). Square/portrait/story keep the historic
    # fractions (byte-identical renders); landscape families give the hero more
    # of the short edge and less of the abundant width.
    _boxes = _v2_fit_boxes(width, height)
    _sw, _sh, _smin, _smax = _boxes["surname"]
    root_vars["--mh-fit-surname-px"] = "%dpx" % _fit_one_line_px(
        surname or "X",
        width * _sw,
        height * _sh,
        font_family="Anton",
        weight=400,
        min_px=_smin,
        max_px=_smax,
    )
    _rw, _rh, _rmin, _rmax = _boxes["result"]
    fit_result_px = _fit_one_line_px(
        result or "X",
        width * _rw,
        height * _rh,
        font_family="JetBrains Mono",
        weight=700,
        min_px=_rmin,
        max_px=_rmax,
    )
    root_vars["--mh-fit-result-px"] = "%dpx" % fit_result_px
    # "Mega" sizes for archetypes where the numeral or the name is THE hero
    # (big_number_dominant, minimal_type_poster) — fit to almost the full width.
    _mw, _mh, _mmin, _mmax = _boxes["mega_result"]
    fit_mega_result_px = _fit_one_line_px(
        result or "X",
        width * _mw,
        height * _mh,
        font_family="JetBrains Mono",
        weight=700,
        min_px=_mmin,
        max_px=_mmax,
    )
    root_vars["--mh-fit-mega-result-px"] = "%dpx" % fit_mega_result_px
    _nw, _nh, _nmin, _nmax = _boxes["mega_name"]
    root_vars["--mh-fit-mega-name-px"] = "%dpx" % _fit_one_line_px(
        surname or "X",
        width * _nw,
        height * _nh,
        font_family="Anton",
        weight=400,
        min_px=_nmin,
        max_px=_nmax,
    )
    # G1.12 — Multi-line hero & split-result fitting. The archetypes below carry
    # the surname / result in ONE dominant autofit slot. When a compound or
    # double-barrelled surname, or a split-time result ("1:45.23 / 50.12"), will
    # not fit one line at the slot's cap, balance it across two lines (break at
    # spaces/hyphens for names, at the slash for splits) and size to the wider
    # line — so the hero stays large instead of shrinking to a thin strip. A
    # value that already fits one line keeps that line at the identical size and
    # text, so every common single-line card is byte-identical to before. The
    # balanced fit reuses the SAME (format-aware) box the single-line fit used,
    # so the wrapped block lands in the footprint the layout already reserved.
    from mediahub.graphic_renderer.autofit import fit_balanced

    archetype = getattr(brief, "layout_template", "") or ""
    if surname and archetype in _MULTILINE_SURNAME_ARCHETYPES:
        if archetype == "split_diagonal_hero":
            var = "--mh-fit-surname-px"
            _bw, _bh, _bmin, _bmax = _boxes["surname"]
        else:  # mega_surname_bleed / minimal_type_poster — the mega-name slot
            var = "--mh-fit-mega-name-px"
            _bw, _bh, _bmin, _bmax = _boxes["mega_name"]
        size, lines = fit_balanced(
            surname,
            width * _bw,
            height * _bh,
            max_lines=2,
            font_family="Anton",
            weight=400,
            min_px=_bmin,
            max_px=_bmax,
            line_height=1.0,
            mode="name",
        )
        if len(lines) > 1:
            root_vars[var] = "%dpx" % size
            repl["ATHLETE_SURNAME_DISPLAY"] = "<br>".join(html_escape(ln) for ln in lines)
    if result and "/" in result and archetype in _MULTILINE_RESULT_ARCHETYPES:
        _grw, _grh, _grmin, _grmax = _boxes["mega_result"]
        size, lines = fit_balanced(
            result,
            width * _grw,
            height * _grh,
            max_lines=2,
            font_family="JetBrains Mono",
            weight=700,
            min_px=_grmin,
            max_px=_grmax,
            line_height=1.0,
            mode="split",
        )
        if len(lines) > 1:
            root_vars["--mh-fit-mega-result-px"] = "%dpx" % size
            repl["RESULT_VALUE"] = "<br>".join(html_escape(ln) for ln in lines)

    # G1.9 — per-slot variable-font axis optimisation for the result numerals.
    # The result slots are JetBrains Mono, which carries a genuine weight axis;
    # ``optimise_axes`` returns a non-empty ``css`` ONLY when the fitted px has
    # bottomed out and the line still overflows, in which case it trades the
    # weight down to recover the last sliver of width instead of clipping. When
    # the slot already fits, ``css`` is "" and the var is omitted, so the layout
    # falls back to ``normal`` and renders byte-identically to before. The
    # surname slots are Anton (a static face, no axes), so they are not tuned.
    # Runs AFTER the G1.12 balancer: a split result it spread onto two lines
    # already fits, so the mega numeral is left untraded (guarded below).
    from mediahub.graphic_renderer.autofit import optimise_axes as _optimise_axes

    result_axes = _optimise_axes(
        result or "",
        width * _rw,
        font_family="JetBrains Mono",
        weight=700,
        fitted_px=fit_result_px,
    )
    if result_axes.css:
        root_vars["--mh-axes-result"] = result_axes.css
    if "<br>" not in (repl.get("RESULT_VALUE") or ""):
        mega_result_axes = _optimise_axes(
            result or "",
            width * _mw,
            font_family="JetBrains Mono",
            weight=700,
            fitted_px=fit_mega_result_px,
        )
        if mega_result_axes.css:
            root_vars["--mh-axes-mega-result"] = mega_result_axes.css
    root_vars["--mh-photo-pos"] = _sanitise_photo_pos(photo_pos_override) or _v2_photo_position(
        athlete_path
    )

    # 1.9 — apply per-slot text effects to the finalised slot values (AFTER the
    # multi-line balancer has settled RESULT_VALUE / ATHLETE_SURNAME_DISPLAY).
    # Empty (the default) is a no-op, so a card with no effects is byte-identical.
    effects = getattr(brief, "text_effects", None) or {}
    if effects:
        _apply_text_effects_to_repl(repl, effects, root_vars)

    root_block = "\n:root{" + "".join(f"{k}:{v};" for k, v in root_vars.items()) + "}\n"
    repl["BASE_CSS"] = base_repl.get("BASE_CSS", "") + root_block
    return repl


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def render_brief(
    brief,
    *,
    output_dir: str | Path,
    size: tuple[int, int] = (1080, 1350),
    format_name: str = "feed_portrait",
    athlete_path: Optional[str | Path] = None,
    venue_path: Optional[str | Path] = None,
    logo_path: Optional[str | Path] = None,
    bg_photo_path: Optional[str | Path] = None,
    brand_kit=None,
    sponsor_name: str = "",
    sponsor_logo_path: Optional[str | Path] = None,
    venue_attribution: str = "",
    skip_cutout: bool = False,
    watermark_text: str = "",
    photo_pos_override: str = "",
    image_format: str = "png",
    quality=None,
) -> RenderResult:
    """Render a CreativeBrief into a single still. Returns RenderResult.

    ``sponsor_logo_path`` (PC.8): an optional sponsor logo image embedded in
    the sponsor strip beside the sponsor name.
    ``watermark_text`` (PC.7): when set, a repeated diagonal text overlay is
    stamped across the finished canvas — used by the public try-before-signup
    demo so preview cards are visibly non-production.
    ``photo_pos_override`` (UI 1.18): an explicit CSS ``object-position`` from
    the inspector's manual crop control, used in place of the saliency focus
    for v2 archetypes. Empty (the default) keeps the automatic crop.
    ``image_format`` (G1.14): the output still format — ``"png"`` (default,
    lossless), ``"webp"``, ``"avif"``, or ``"jpeg"``. The file is named
    ``<format_name>.<ext>`` accordingly. ``quality`` (G1.14) selects the render
    quality profile (``"fast"``/``"standard"``/``"high"`` or a
    :class:`QualityProfile`); None uses ``MEDIAHUB_RENDER_QUALITY``.
    """
    width, height = size
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    family = brief.layout_template or "individual_hero"
    # Gen Engine v2 (Tier A): when the flag is on and the brief names a v2
    # archetype, load it from layouts/v2/ — BEFORE the legacy existence-check
    # below, which would otherwise treat the v2 name as "unknown" and fall back.
    _v2_archetype = None
    try:
        from mediahub.graphic_renderer import archetypes as _archetypes

        if _archetypes.is_enabled() and family in _archetypes.list_archetypes():
            _v2_archetype = family
            template_path = _archetypes.V2_DIR / f"{family}.html"
    except Exception:
        _v2_archetype = None
    if _v2_archetype is None:
        template_path = LAYOUTS_DIR / f"{family}.html"
        if not template_path.exists():
            # Fallback to text-led recap if family is unknown
            family = "text_led_recap"
            template_path = LAYOUTS_DIR / f"{family}.html"

    # G1.25 — server-side photo adjustment stack (deterministic PIL recipes).
    # Resolve the recipe once; ``None`` (the default) keeps the un-adjusted
    # inline so the render is byte-identical. When a recipe is set it bakes
    # sharpen/contrast/saturation/levels into the photo bytes *before* they're
    # base64-inlined below — the athlete cutout's alpha mask is preserved exactly.
    _photo_recipe = None
    try:
        from mediahub.graphic_renderer import photo_adjust as _photo_adjust

        _photo_recipe = _photo_adjust.recipe_for(
            explicit=getattr(brief, "photo_adjust", "") or "",
            treatment=getattr(brief, "photo_treatment", "") or "",
        )
    except Exception:
        _photo_recipe = None

    def _inline_photo(path) -> str:
        """Inline a real photo, applying the resolved adjustment recipe if any.

        Falls back to the plain (un-adjusted) inline on any error, so an
        optional adjustment can never break a render.
        """
        if _photo_recipe is not None:
            try:
                return _photo_adjust.adjust_to_data_uri(path, _photo_recipe)
            except Exception:
                pass
        return _img_to_data_uri(path)

    # Athlete cutout
    athlete_uri = None
    if athlete_path:
        try:
            cut_path = (
                athlete_path
                if skip_cutout
                else _maybe_cut_out_athlete(athlete_path, profile_id=brief.profile_id or "default")
            )
            athlete_uri = _inline_photo(cut_path)
        except Exception:
            athlete_uri = None

    # Full-bleed photo families (action_photo_hero) render the ORIGINAL,
    # un-cutout image as a cover background with a brand scrim. Only ever a real
    # provided photo — never a fabricated person — and left empty when none is
    # supplied (the layout then falls back to the brand gradient).
    hero_photo_uri = ""
    if family == "action_photo_hero" and athlete_path:
        try:
            hero_photo_uri = _inline_photo(athlete_path)
        except Exception:
            hero_photo_uri = ""

    venue_uri = None
    if venue_path:
        try:
            venue_uri = _inline_photo(venue_path)
        except Exception:
            venue_uri = None

    # User-chosen background photo (caption-led graphics). Embedded as-is —
    # the scrim layer handles legibility, no cutout needed.
    bg_photo_uri = ""
    if bg_photo_path:
        try:
            bg_photo_uri = _inline_photo(bg_photo_path)
        except Exception:
            bg_photo_uri = ""

    # PC.8: sponsor logo riding the sponsor strip (best-effort — a missing
    # or unreadable file falls back to the name-only strip).
    _sponsor_logo_uri = ""
    if sponsor_name and sponsor_logo_path:
        try:
            _sponsor_logo_uri = _img_to_data_uri(sponsor_logo_path)
        except Exception:
            _sponsor_logo_uri = ""

    # Build common replacements. The logo surface proxy is the brand primary
    # (the dark ground the bottom-left logo usually sits over) — used only to
    # pick chip vs. bare, never to recolour the logo.
    _logo_surface = (
        (brief.palette or {}).get("primary")
        or getattr(brand_kit, "primary_colour", "")
        or "#0A2540"
    )
    _logo_inner, _logo_mod = _build_logo_treatment(brand_kit, logo_path, _logo_surface)
    base_repl = _common_replacements(
        brief,
        width,
        height,
        brand_kit,
        athlete_data_uri=athlete_uri,
        logo_block=_logo_inner,
        logo_mark_mod=_logo_mod,
        bg_photo_uri=bg_photo_uri,
        result_chip=_build_result_chip(
            "Time" if (brief.text_layers or {}).get("event_name") else "Result",
            (brief.text_layers or {}).get("result_value", ""),
        ),
        sponsor_block=_build_sponsor_block(sponsor_name, _sponsor_logo_uri) if sponsor_name else "",
        skip_ai_bg=bool(_v2_archetype),
    )
    base_repl["HERO_PHOTO_URI"] = hero_photo_uri

    # G1.3 — per-format composition rules. Appended to BASE_CSS for every
    # layout family; an empty string for square/portrait/story so those renders
    # stay byte-identical. Landscape / extended ratios pick up the wide-canvas
    # retune of the shared base classes here, and v2 archetypes additionally
    # adapt via the aspect-aware autofit boxes in _fill_v2_archetype.
    base_repl["BASE_CSS"] = base_repl.get("BASE_CSS", "") + _format_composition_css(width, height)

    # Layout-specific
    if _v2_archetype:
        repl = _fill_v2_archetype(
            brief,
            width,
            height,
            base_repl,
            athlete_path=athlete_path,
            brand_kit=brand_kit,
            photo_pos_override=photo_pos_override,
        )
    elif family == "meet_preview":
        repl = _fill_meet_preview(
            brief,
            width,
            height,
            base_repl,
            venue_data_uri=venue_uri,
            venue_attribution=venue_attribution,
        )
    elif family == "sponsor_branded":
        repl = _fill_sponsor_branded(brief, width, height, base_repl, sponsor_name=sponsor_name)
    else:
        filler = _FILLERS.get(family, _fill_individual_hero)
        repl = filler(brief, width, height, base_repl)

    # Render template
    template = _read_text(template_path)
    html = _apply(template, repl)
    # Replace any unfilled placeholders to avoid raw {{X}} in output
    import re as _re

    html = _re.sub(r"\{\{[A-Z0-9_]+\}\}", "", html)

    # Inject the accent decoration overlay (V9 variation overhaul). It sits
    # inside the .canvas so it inherits the same stacking context as the
    # rest of the layout. We insert it before the closing </div> of the
    # .canvas wrapper; if we can't find it cleanly we fall back to just
    # before </body>.
    # v1 only: the v2 path already substituted the style-pack overlay into the
    # archetype's ``{{ACCENT_DECORATION}}`` slot via _apply(), so re-injecting it
    # here would paint it twice. v1 templates have no such slot and rely on this.
    accent_html = repl.get("ACCENT_DECORATION") or ""
    if accent_html and not _v2_archetype:
        # Find the canvas's closing </div> using the same depth-walk the
        # grain injector below uses.
        canvas_marker = '<div class="canvas'
        idx = html.find(canvas_marker)
        if idx != -1:
            search_from = html.find(">", idx) + 1
            depth = 1
            i = search_from
            close_at = -1
            while i < len(html) and depth > 0:
                next_open = html.find("<div", i)
                next_close = html.find("</div>", i)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    i = html.find(">", next_open) + 1
                else:
                    depth -= 1
                    if depth == 0:
                        close_at = next_close
                        break
                    i = next_close + len("</div>")
            if close_at != -1:
                html = html[:close_at] + accent_html + html[close_at:]
            else:
                html = html.replace("</body>", accent_html + "</body>", 1)
        else:
            html = html.replace("</body>", accent_html + "</body>", 1)

    # Inject the grain SVG <filter> right after <body> so layouts that
    # opt in via class="texture-grain" get the filter resolved. Strip
    # the class entirely when the grain feature flag is off so renders
    # are byte-different (verifiable). V8.1 Issue 7 §3. The grain injector
    # targets the v1 `.canvas` wrapper, which v2 archetypes do not have —
    # so skip it for v2 (they manage their own surface texture).
    if _grain_enabled() and not _v2_archetype:
        html = _re.sub(r"(<body[^>]*>)", r"\1" + _GRAIN_SVG_BLOCK, html, count=1)
        html = html.replace(
            '<div class="canvas"',
            '<div class="canvas texture-grain-host"',
            1,
        )
        # Inject the grain overlay INSIDE the .canvas as the last child so it
        # shares the canvas' stacking context (the canvas sets
        # `isolation: isolate`, which would otherwise prevent mix-blend-mode
        # from compositing against the canvas contents).
        # We find the last </div> matching the canvas wrapper by looking for
        # the canvas open tag, then injecting just before its closing tag.
        canvas_open = '<div class="canvas texture-grain-host"'
        idx = html.find(canvas_open)
        if idx != -1:
            # Walk forward to find the matching close </div> at the canvas
            # wrapper's level. Use a depth counter starting at 0 (we'll
            # enter the canvas at +1 once we step past its opening tag).
            search_from = html.find(">", idx) + 1
            depth = 1
            i = search_from
            close_at = -1
            while i < len(html) and depth > 0:
                next_open = html.find("<div", i)
                next_close = html.find("</div>", i)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    i = html.find(">", next_open) + 1
                else:
                    depth -= 1
                    if depth == 0:
                        close_at = next_close
                        break
                    i = next_close + len("</div>")
            if close_at != -1:
                html = (
                    html[:close_at]
                    + '<div class="grain-overlay texture-grain"></div>'
                    + html[close_at:]
                )
            else:
                # Fallback: append before </body>
                html = html.replace(
                    "</body>",
                    '<div class="grain-overlay texture-grain"></div></body>',
                    1,
                )
        else:
            html = html.replace(
                "</body>",
                '<div class="grain-overlay texture-grain"></div></body>',
                1,
            )
    else:
        # Strip the texture-grain class so flag-off renders differ.
        html = html.replace("texture-grain", "texture-grain-disabled")

    # PC.7: demo watermark overlay — a repeated diagonal text layer stamped
    # over EVERYTHING (z-index above accent/grain), injected last so no
    # layout family can cover it. Body-level, so it works for both v1
    # `.canvas` layouts and v2 archetypes.
    if watermark_text:
        wm = html_escape(watermark_text)
        tiles = "".join(
            f'<div style="transform:rotate(-30deg);font:700 {max(28, width // 18)}px '
            "system-ui,sans-serif;color:rgba(255,255,255,0.28);text-shadow:0 1px 2px "
            'rgba(0,0,0,0.25);white-space:nowrap;letter-spacing:0.12em">'
            f"{wm}</div>"
            for _ in range(9)
        )
        watermark_html = (
            '<div class="mh-demo-watermark" style="position:fixed;inset:0;z-index:9999;'
            "pointer-events:none;display:grid;grid-template-columns:repeat(3,1fr);"
            'place-items:center;overflow:hidden">' + tiles + "</div>"
        )
        html = html.replace("</body>", watermark_html + "</body>", 1)

    # Sprint render hooks (G1.*): deterministic post-render HTML transforms that
    # register as their own module under graphic_renderer/sprint_hooks/ — no edits
    # here. A no-op until a hook module is present, so renders stay byte-identical.
    html = _apply_render_hooks(
        html,
        _RenderHookCtx(
            brief=brief,
            width=width,
            height=height,
            family=family,
            format_name=format_name,
            is_v2=_v2_archetype,
        ),
    )

    # Output path — the file extension follows the requested image format
    # (G1.14): PNG by default, else WebP/AVIF/JPEG.
    visual_id = "v_" + uuid.uuid4().hex[:12]
    pil_format = _resolve_image_format(image_format, output_dir / format_name)
    out_ext = _FORMAT_EXTENSIONS.get(pil_format, "png")
    out_path = output_dir / f"{format_name}.{out_ext}"

    # Forward the encode controls only when they deviate from the defaults, so
    # the common PNG path keeps the historic 3-positional-arg call into
    # render_html_to_png (the output suffix already drives PNG inference). This
    # keeps existing render_html_to_png stubs valid and the default render
    # byte-for-byte unchanged.
    encode_kwargs: dict = {}
    if pil_format != "PNG":
        encode_kwargs["image_format"] = image_format
    if quality is not None:
        encode_kwargs["quality"] = quality
    bytes_written = render_html_to_png(html, out_path, (width, height), **encode_kwargs)

    # G1.13: optionally drop an editable, outlined-font SVG beside the PNG. Off
    # by default (the SVG needs a second Chromium pass), so default renders stay
    # byte-identical and fast; opt in with MEDIAHUB_SVG_SIDECAR=1. A failure here
    # never sinks the render — the PNG is the deliverable.
    if _flag("MEDIAHUB_SVG_SIDECAR", "0"):
        try:
            from mediahub.graphic_renderer.svg_export import export_svg_alongside

            export_svg_alongside(out_path, html, (width, height), title=family)
        except Exception as e:  # pragma: no cover - opt-in, environment-dependent
            log.warning("SVG sidecar export skipped: %s", e)

    visual = GeneratedVisual(
        id=visual_id,
        brief_id=brief.id,
        content_item_id=brief.content_item_id,
        profile_id=brief.profile_id,
        layout_template=family,
        format_name=format_name,
        width=width,
        height=height,
        file_path=str(out_path),
        text_layers=dict(brief.text_layers or {}),
        palette=dict(brief.palette or {}),
        sourced_asset_ids=list(brief.sourced_asset_ids or []),
        safety_notes=list(brief.safety_notes or []),
        why_this_design=brief.why_this_design or "",
        confidence_label=brief.confidence_label or "",
    )

    return RenderResult(visual=visual, html=html, png_bytes=bytes_written)


__all__ = [
    "GeneratedVisual",
    "RenderResult",
    "QualityProfile",
    "RenderEncodeError",
    "render_brief",
    "render_html_to_png",
    "render_pool_session",
    "warm_render_pool",
    "shutdown_render_pool",
    "render_pool_active",
    "darken",
    "lighten",
]
