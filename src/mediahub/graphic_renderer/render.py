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

import base64
import io
import json
import math
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def _premium_fonts_enabled() -> bool:
    return _flag("MEDIAHUB_RENDER_PREMIUM_FONTS", "1")


def _grain_enabled() -> bool:
    return _flag("MEDIAHUB_RENDER_GRAIN", "1")


def _dpr_render() -> int:
    """Device-pixel-ratio used at screenshot time. Defaults to 2."""
    try:
        v = int(os.environ.get("MEDIAHUB_RENDER_DPR", "2"))
        return max(1, min(4, v))
    except Exception:
        return 2


_GRAIN_SVG_BLOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" '
    'style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">'
    '<defs>'
    '<filter id="grain" x="0%" y="0%" width="100%" height="100%">'
    # baseFrequency tuned for fine film-grain; numOctaves=2 keeps it cheap.
    '<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch" seed="7"/>'
    # Push values toward greys + drop alpha to 3%.
    '<feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0.03 0"/>'
    '<feComposite in2="SourceGraphic" operator="in"/>'
    '</filter>'
    '</defs>'
    '</svg>'
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


def darken(hex_colour: str, amount: float = 0.25) -> str:
    """Return a darker shade of the input hex colour (amount in [0..1])."""
    r, g, b = _hex_to_rgb(hex_colour)
    return _rgb_to_hex((r * (1 - amount), g * (1 - amount), b * (1 - amount)))


def lighten(hex_colour: str, amount: float = 0.25) -> str:
    r, g, b = _hex_to_rgb(hex_colour)
    return _rgb_to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


def _img_to_data_uri(path: str | Path) -> str:
    """Read an image from disk, return a data: URI (PNG-ish)."""
    p = Path(path)
    raw = p.read_bytes()
    suffix = p.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "svg": "image/svg+xml", "gif": "image/gif",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


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
    return f"url(\"data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}\")"


def _noise_pattern_data_uri() -> str:
    """Tiny SVG turbulence — adds film-grain."""
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>
  <filter id='n'>
    <feTurbulence type='fractalNoise' baseFrequency='1.6' numOctaves='2' stitchTiles='stitch'/>
    <feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.6 0'/>
  </filter>
  <rect width='100%' height='100%' filter='url(#n)' opacity='0.85'/>
</svg>"""
    return f"url(\"data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}\")"


# ----- Athlete cutout pipeline ---------------------------------------------

def _maybe_cut_out_athlete(src_path: str | Path, *, profile_id: str = "default") -> Path:
    """Run the configured background remover on the athlete photo if needed.

    Caches results in ``uploads_v4/media_library/<profile_id>/cutouts/`` so we
    don't re-run rembg on the same photo every render.
    """
    src = Path(src_path)
    if not src.exists():
        return src

    # Already a cutout?
    if "cutout" in src.stem.lower() or src.parent.name == "cutouts":
        return src

    cache_dir = Path("uploads_v4/media_library") / profile_id / "cutouts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{src.stem}__cutout.png"
    if out_path.exists() and out_path.stat().st_size > 1000:
        return out_path

    try:
        from mediahub.media_ai.providers import get_bg_remover  # type: ignore
        remover = get_bg_remover()
        if remover is None:
            return src
        ok = remover.remove(src, out_path)
        if ok and out_path.exists():
            return out_path
    except Exception:
        pass
    return src


# ---------------------------------------------------------------------------
# Logo / sponsor / result-chip block builders
# ---------------------------------------------------------------------------

def _build_logo_block(brand_kit, logo_path: Optional[str | Path]) -> str:
    """Return inner HTML for ``.brand-corner .logo-mark``."""
    if logo_path:
        try:
            uri = _img_to_data_uri(logo_path)
            return f'<img src="{uri}" alt="logo" />'
        except Exception:
            pass
    # SVG logo string?
    svg = getattr(brand_kit, "logo_svg", None)
    if svg and isinstance(svg, str) and svg.lstrip().startswith("<"):
        return svg
    # Text-mark fallback: club initials
    name = getattr(brand_kit, "short_name", None) or getattr(brand_kit, "display_name", "") or "CLUB"
    parts = [w for w in str(name).replace("Swimming Club", "").split() if w]
    initials = "".join(p[0].upper() for p in parts[:3]) or "CL"
    return initials


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
    return ''


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
        return ''
    initials = ''.join(p[0] for p in (full_name or '').split()[:2]).upper()
    if not initials:
        initials = (surname or '').strip()[:2].upper() or '\u2014'
    mega_letter = (surname or full_name or '').upper()
    if not mega_letter:
        mega_letter = initials

    # Stat strip cells
    event = (layers.get('event_name') or '').strip()
    course = ''
    if 'LC' in event.upper():
        course = 'Long Course'
    elif 'SC' in event.upper():
        course = 'Short Course'
    elif event:
        course = 'Race'
    meet = (layers.get('meet_name') or '').strip()
    result = (layers.get('result_value') or '').strip()
    place = (layers.get('place') or '').strip()

    cells = []
    if event:
        cells.append(('EVENT', event))
    if result:
        cells.append(('TIME', result))
    if place:
        place_label = (
            f"{place} place" if not place.lower().endswith(('st', 'nd', 'rd', 'th'))
            else place
        )
        cells.append(('FINISH', place_label))
    if course and len(cells) < 3:
        cells.append(('COURSE', course))
    if meet and len(cells) < 3:
        cells.append(('MEET', meet[:32]))
    cells = cells[:3]
    if not cells:
        cells = [('NEW PB', layers.get('achievement_label') or 'PB')]

    # Position the mega-initial roughly where the photo would have been.
    # Use a smaller, more architectural sizing for `compact` mode (so it lives
    # behind the fg-text instead of swallowing it).
    if compact:
        mega_size = int(min(width, height) * 0.62)
        mega_top = int(height * 0.22)
        mega_right = int(-width * 0.02)
        glow_size = int(min(width, height) * 0.55)
        glow_top = int(height * 0.20)
        glow_right = int(-width * 0.12)
    else:
        mega_size = int(min(width, height) * 0.78)
        mega_top = int(height * 0.18)
        mega_right = int(-width * 0.04)
        glow_size = int(min(width, height) * 0.70)
        glow_top = int(height * 0.20)
        glow_right = int(-width * 0.16)

    strip_class = 'txl-stat-strip compact-tr' if compact else 'txl-stat-strip'
    # In compact mode, only show 2 cells (event/time) so the column is short.
    cells_for_render = cells[:2] if compact else cells
    cells_html = ''.join(
        f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
        f'<div class="val">{html_escape(val)}</div></div>'
        for lab, val in cells_for_render
    )
    strip_html = '' if skip_stat_strip else f'<div class="{strip_class}">{cells_html}</div>'

    return (
        f'<div class="txl-photo-glow" '
        f'style="top:{glow_top}px;right:{glow_right}px;width:{glow_size}px;height:{glow_size}px;"></div>'
        f'<div class="txl-accent-bar diagonal"></div>'
        f'<div class="txl-accent-bar dot-grid"></div>'
        f'<div class="txl-mega-initial" '
        f'style="top:{mega_top}px;right:{mega_right}px;font-size:{mega_size}px;">'
        f'{html_escape(mega_letter[:8])}'
        f'</div>'
        f'{strip_html}'
    )


def _build_result_chip(label: str, value: str) -> str:
    if not value:
        return ""
    return (
        f'<div class="result-chip">'
        f'<div class="label">{html_escape(label or "Time")}</div>'
        f'<div class="value">{html_escape(value)}</div>'
        f'</div>'
    )


def _build_sponsor_block(sponsor_name: str | None) -> str:
    if not sponsor_name:
        return ""
    return (
        '<div class="sponsor-strip">'
        '<span class="label">Performance supported by</span>'
        f'<span class="name">{html_escape(sponsor_name)}</span>'
        '</div>'
    )


def html_escape(s: Any) -> str:
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Layout-specific filler functions
# ---------------------------------------------------------------------------

def _surname_for_display(surname: str, max_chars: int = 8) -> str:
    s = (surname or "").upper()
    return s[:max_chars] if len(s) > max_chars else s


def _scale_for_format(width: int, height: int) -> dict[str, float]:
    """Return per-format multipliers used to pick font sizes."""
    if width == height:           # square
        return {"surname": 0.32, "first": 0.075, "event": 0.026, "result": 0.055, "ribbon": 0.034}
    if height > width:            # portrait / story
        ratio = height / width
        if ratio >= 1.7:          # 9:16 story
            return {"surname": 0.28, "first": 0.06, "event": 0.022, "result": 0.045, "ribbon": 0.028}
        return {"surname": 0.34, "first": 0.07, "event": 0.024, "result": 0.052, "ribbon": 0.032}
    return {"surname": 0.30, "first": 0.07, "event": 0.024, "result": 0.050, "ribbon": 0.032}


def _detect_medal_tier(brief) -> Optional[str]:
    """Return 'gold' | 'silver' | 'bronze' | 'pb' | None based on the brief.

    Looks at achievement_label, post_angle, inspiration_pattern_id, and place
    so any layout (not just medal_card) can colour itself appropriately.
    A swimmer that medalled should always read as "medalled" at a glance,
    regardless of which layout the brief picked.
    """
    layers = brief.text_layers or {}
    label = (layers.get("achievement_label") or "").lower()
    angle = (layers.get("post_angle") or "").lower()
    pattern = (getattr(brief, "inspiration_pattern_id", "") or "").lower()
    place = str(layers.get("place") or "").strip()
    combined = " ".join([label, angle, pattern])

    if "gold" in combined or place in ("1", "1st") or place.startswith("1"):
        return "gold"
    if "silver" in combined or place in ("2", "2nd") or place.startswith("2"):
        return "silver"
    if "bronze" in combined or place in ("3", "3rd") or place.startswith("3"):
        return "bronze"
    if "new pb" in combined or "personal best" in combined or "pb swim" in combined:
        return "pb"
    return None


# Medal palette overrides — applied on top of the club's brand colours so
# tier is unmistakable at a glance while the brand still dominates.
_MEDAL_ACCENTS = {
    "gold":   {"accent": "#FFD24A", "accent_deep": "#A77A07", "badge": "GOLD"},
    "silver": {"accent": "#E8EAED", "accent_deep": "#6F757B", "badge": "SILVER"},
    "bronze": {"accent": "#E2A26A", "accent_deep": "#7E481B", "badge": "BRONZE"},
    "pb":     {"accent": "#22D3EE", "accent_deep": "#0E7C8F", "badge": "NEW PB"},
}


def _common_replacements(brief, width: int, height: int, brand_kit, *,
                         athlete_data_uri: str | None,
                         logo_block: str,
                         result_chip: str,
                         sponsor_block: str) -> dict[str, str]:
    palette = brief.palette or {}
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
        # Tier badge — placed below the result chip, top-right, so it
        # sits next to the time (which is the hero element) and never
        # collides with the .label-ribbon top-left achievement label.
        # PB uses a lighter, less-shouty treatment than medal tiers.
        badge_top = int(height * 0.20)
        font_size = max(36, int(height * 0.038))
        medal_badge_html = (
            f'<div class="tier-badge" style="position:absolute;'
            f'top:{badge_top}px;right:56px;z-index:10;'
            f'background:linear-gradient(135deg,{ovr["accent"]} 0%,{ovr["accent_deep"]} 100%);'
            f'color:#1a1a1a;padding:14px 28px;border-radius:999px;'
            f'font-family:\'Bebas Neue\',\'Anton\',sans-serif;'
            f'font-size:{font_size}px;letter-spacing:0.14em;'
            f'font-weight:700;box-shadow:0 10px 26px rgba(0,0,0,0.50),'
            f'inset 0 2px 0 rgba(255,255,255,0.5);'
            f'border:2px solid rgba(255,255,255,0.25)">'
            f'&#9733; {ovr["badge"]}</div>'
        )

    base_css = _read_text(_BASE_CSS_PATH)
    try:
        text_led_css = _read_text(_TEXT_LED_FILL_CSS_PATH)
    except Exception:
        text_led_css = ''
    # Premium @font-face declarations from _shared.css (V8.1 Issue 7 §1).
    # Feature-flagged via MEDIAHUB_RENDER_PREMIUM_FONTS; falls back to the
    # legacy @import css2 URL otherwise.
    if _premium_fonts_enabled() and _SHARED_CSS_PATH.exists():
        try:
            shared_css = _read_text(_SHARED_CSS_PATH)
        except Exception:
            shared_css = ''
        # Also keep the @import as a belt-and-braces fallback if the
        # gstatic .woff2 URLs above shift; @font-face wins in cascade order.
        fonts_import = (
            '@import url(\'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Anton'
            '&family=Bowlby+One&family=Inter:wght@400;500;600;700;800'
            '&family=Space+Grotesk:wght@500;600;700'
            '&family=JetBrains+Mono:wght@500;700&display=swap\');\n'
        )
        base_css = fonts_import + shared_css + '\n' + base_css + '\n' + text_led_css
    else:
        fonts_import = (
            '@import url(\'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Anton'
            '&family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700'
            '&family=JetBrains+Mono:wght@500;700&display=swap\');\n'
        )
        base_css = fonts_import + base_css + '\n' + text_led_css

    layers = brief.text_layers or {}
    full_name = layers.get("athlete_full_name") or ""
    first = layers.get("athlete_first_name") or ""
    surname = _surname_for_display(layers.get("athlete_surname") or "")
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

    # Optional AI-generated brand-aware background. Activated only when
    # REPLICATE_API_TOKEN is set; otherwise the water-pattern + noise
    # overlay is used as before. Cached aggressively by content hash.
    ai_bg_uri = None
    try:
        import os as _os
        if _os.environ.get("MEDIAHUB_DISABLE_AI_BG", "0") != "1":
            from mediahub.visual.ai_background import (
                is_available as _ai_bg_ok,
                background_data_uri_for,
            )
            if _ai_bg_ok():
                # Map width/height back to a format name so the cache key
                # is stable across cards of the same shape.
                fmt_for_bg = "feed_square" if width == height else (
                    "story" if height > width * 1.5 else "feed_portrait"
                )
                ai_bg_uri = background_data_uri_for(brief, format_name=fmt_for_bg)
    except Exception:
        ai_bg_uri = None

    return {
        "WIDTH": str(width), "HEIGHT": str(height),
        "PRIMARY": primary, "PRIMARY_DEEP": primary_deep,
        "SECONDARY": secondary, "ACCENT": accent,
        "BASE_CSS": base_css,
        "WATER_PATTERN": _water_pattern_data_uri(),
        "NOISE_PATTERN": _noise_pattern_data_uri(),
        "AI_BG_URI": ai_bg_uri or "",
        "ATHLETE_FULL_NAME": html_escape(full_name),
        "ATHLETE_FIRST_NAME": html_escape(first.upper()),
        "ATHLETE_SURNAME_DISPLAY": html_escape(surname),
        "EVENT_NAME": html_escape(layers.get("event_name") or ""),
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
        "RESULT_CHIP_BLOCK": result_chip,
        "SPONSOR_BLOCK": sponsor_block,
        "MEDAL_BADGE_BLOCK": medal_badge_html,
    }


def _fill_individual_hero(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    s = _scale_for_format(width, height)
    repl = dict(repl)
    has_photo = repl.get("HAS_PHOTO") == "1"
    layers = brief.text_layers or {}
    # Rebuild the text-led fill block in compact mode so it does not collide
    # with the bottom fg-text + result-chip area.
    if not has_photo:
        repl["TEXT_LED_FILL_BLOCK"] = _build_text_led_fill_block(
            full_name=layers.get("athlete_full_name") or "",
            surname=layers.get("athlete_surname") or "",
            width=width, height=height, layers=layers,
            palette=brief.palette or {}, has_photo=False, compact=True,
        )
    repl.update({
        "SURNAME_BOTTOM": str(int(height * 0.30)),
        "SURNAME_LEFT": str(-int(width * 0.04)),
        "SURNAME_RIGHT": "auto",
        "SURNAME_FONT_SIZE": str(int(height * s["surname"])),
        "ATHLETE_W": str(int(width * 0.82)),
        "ATHLETE_H": str(int(height * 0.78)),
        "FG_TEXT_BOTTOM": str(int(height * 0.16)),
        "FIRSTNAME_FONT_SIZE": str(int(height * s["first"])),
        "EVENT_FONT_SIZE": str(int(height * s["event"])),
        "RIBBON_FONT_SIZE": str(int(height * s["ribbon"])),
        "RESULT_FONT_SIZE": str(int(height * s["result"])),
    })
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
        "GOLD":   ("#FFE07A", "#9A6E0E", "1ST"),
        "SILVER": ("#F2F2F2", "#6E6E6E", "2ND"),
        "BRONZE": ("#F0BC8A", "#7A4314", "3RD"),
    }
    light, dark, place_label = medals.get(medal_label, medals["GOLD"])

    s = _scale_for_format(width, height)
    repl = dict(repl)
    repl.update({
        "SURNAME_BOTTOM": str(int(height * 0.32)),
        "SURNAME_LEFT": str(-int(width * 0.03)),
        "SURNAME_FONT_SIZE": str(int(height * s["surname"] * 0.85)),
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
    })
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
            stat_pairs.append((event[:14], "FEATURE EVENT"))
        # Pad to 4 with placeholder counts that read as professional copy
        defaults = [("1", "MEET"), ("✓", "COMPLETE"), ("24", "HOURS"), ("★", "HIGHLIGHT")]
        i = 0
        while len(stat_pairs) < 4 and i < len(defaults):
            stat_pairs.append(defaults[i]); i += 1
    tiles_html = ""
    for value, label in stat_pairs[:6]:
        tiles_html += (
            '<div class="stat-tile">'
            f'<div class="num">{html_escape(value)}</div>'
            f'<div class="label">{html_escape(label)}</div>'
            '</div>\n'
        )

    headline_line1 = (layers.get("headline_line1") or "WEEKEND").upper()
    headline_line2 = (layers.get("headline_line2") or "IN NUMBERS").upper()

    repl = dict(repl)
    repl.update({
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
    })
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
        mega_letter = (surname or full_name or "").upper()[:8]
        mega_size = int(min(width, height) * 0.62)
        # Position centered horizontally, in the middle vertical band
        custom_block = (
            f'<div class="txl-photo-glow" style="top:{int(height*0.40)}px;'
            f'left:50%;transform:translateX(-50%);width:{int(min(width,height)*0.55)}px;'
            f'height:{int(min(width,height)*0.55)}px;"></div>'
            f'<div class="txl-accent-bar diagonal"></div>'
            f'<div class="txl-mega-initial" style="top:{int(height*0.36)}px;'
            f'left:50%;transform:translateX(-50%);right:auto;font-size:{mega_size}px;'
            f'-webkit-text-stroke:4px rgba(255,255,255,0.16);">'
            f'{html_escape(mega_letter)}</div>'
        )
        repl["TEXT_LED_FILL_BLOCK"] = custom_block

    # Stat rows — prefer caller-provided list, then synthesise from primary swim
    rows: list[tuple[str, str, str]] = []
    if "stat_rows" in layers and isinstance(layers["stat_rows"], list):
        for r in layers["stat_rows"]:
            if isinstance(r, dict):
                rows.append((r.get("event") or "", r.get("result") or "", r.get("note") or ""))
    if not rows:
        primary_event = layers.get("event_name") or ""
        primary_result = layers.get("result_value") or ""
        primary_label = layers.get("achievement_label") or ""
        if primary_event or primary_result:
            rows.append((primary_event, primary_result, primary_label))
        # Synthesise supporting rows so the panel doesn't look bare
        place = layers.get("place") or ""
        if place:
            place_disp = place if place.lower().endswith(("st", "nd", "rd", "th")) else f"{place}"
            rows.append(("Final placing", place_disp, "PLACE"))
        # Course inferred from event suffix
        if primary_event and ("LC" in primary_event.upper() or "SC" in primary_event.upper()):
            course = "Long Course" if "LC" in primary_event.upper() else "Short Course"
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
            '</div>'
        )

    # Career-best card — the headline metric for this swimmer at this meet
    cb_value = layers.get("result_value") or ""
    cb_event = layers.get("event_name") or ""
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
        career_best_html += '</div>'
    else:
        career_best_html = ''

    # Bottom support grid — always shown when no photo (to fill the empty
    # left half) and when at least one secondary fact exists. Renders as a
    # full-width 4-column row at the bottom so long meet names fit.
    support_cells: list[tuple[str, str]] = []
    if layers.get("meet_name"):
        support_cells.append(("Meet", layers["meet_name"][:24]))
    if layers.get("venue_name"):
        support_cells.append(("Venue", layers["venue_name"][:24]))
    if layers.get("event_name"):
        ev_text = layers["event_name"]
        course = "Long Course" if "LC" in ev_text.upper() else ("Short Course" if "SC" in ev_text.upper() else "Race")
        support_cells.append(("Course", course))
    if layers.get("club_full"):
        support_cells.append(("Club", layers["club_full"][:24]))
    support_cells = support_cells[:4]
    support_grid_html = ''
    if support_cells and not has_photo:
        cells_html = ''.join(
            f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
            f'<div class="val">{html_escape(val)}</div></div>'
            for lab, val in support_cells
        )
        # Full-width row — 4 equal cells across the canvas bottom
        support_grid_html = (
            f'<div class="support-grid full-row">{cells_html}</div>'
        )

    side_width = int(width * (0.46 if has_photo else 0.50))
    name_size = int(height * (0.060 if not has_photo else 0.075))

    repl = dict(repl)
    repl.update({
        "STAT_ROWS": rows_html,
        "SIDE_WIDTH": str(side_width),
        "SUPPORT_WIDTH": str(int(width * 0.46)),
        "ATHLETE_W": str(int(width * 0.46)),
        "ATHLETE_H": str(int(height * 0.82)),
        "NAME_FONT_SIZE": str(name_size),
        "SPOTLIGHT_TAG": "ATHLETE SPOTLIGHT",
        "CAREER_BEST_BLOCK": career_best_html,
        "SUPPORT_GRID_BLOCK": support_grid_html,
    })
    return repl


def _fill_meet_preview(brief, width: int, height: int, repl: dict[str, str], *,
                        venue_data_uri: str | None,
                        venue_attribution: str = "") -> dict[str, str]:
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
    cells_html = ''.join(
        f'<div class="cell"><div class="lab">{html_escape(lab)}</div>'
        f'<div class="val">{html_escape(val)}</div></div>'
        for lab, val in cells
    )
    stripe_html = f'<div class="preview-stripe">{cells_html}</div>'

    repl.update({
        "VENUE_BG_URL": f"url('{venue_data_uri}')" if venue_data_uri else f"linear-gradient(180deg, {repl['PRIMARY']}, {repl['PRIMARY_DEEP']})",
        "VENUE_ATTRIBUTION": html_escape(venue_attribution),
        "VENUE_NAME": html_escape(layers.get("venue_name") or ""),
        "DATES": html_escape(layers.get("dates") or "TBA"),
        "HEADLINE": html_escape(layers.get("meet_name") or "UPCOMING MEET"),
        "HEADLINE_FONT_SIZE": str(int(height * 0.075)),
        "PREVIEW_STRIPE_BLOCK": stripe_html,
    })
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
            bullets = [
                "Personal bests across the squad",
                "Multiple medals on day two",
                "Big finals representation",
            ]
    bullets_html = ""
    for i, b in enumerate(bullets[:4], 1):
        bullets_html += (
            f'<div class="row"><span class="num">0{i}</span>'
            f'<span>{html_escape(b)}</span></div>'
        )
    headline_line1 = (layers.get("headline_line1") or "WEEKEND").upper()
    headline_line2 = (layers.get("headline_line2") or "RECAP").upper()

    # Centre stat strip — keeps the middle of the canvas alive when bullets
    # alone don't fill the page. Use any stat_* layers, else infer from
    # bullets.
    stat_cells: list[tuple[str, str]] = []
    for k, v in layers.items():
        if k.startswith("stat_") and v not in (None, "", "—"):
            label = k[5:].replace("_", " ").upper()
            stat_cells.append((str(v), label))
    if not stat_cells:
        if layers.get("result_value"):
            stat_cells.append((layers["result_value"], "TIME"))
        if layers.get("event_name"):
            ev = layers["event_name"]
            stat_cells.append((ev[:14], "EVENT"))
        if layers.get("achievement_label"):
            stat_cells.append((layers["achievement_label"], "RESULT"))
        if layers.get("meet_name") and len(stat_cells) < 3:
            stat_cells.append((layers["meet_name"][:18], "MEET"))
        # Last-resort defaults so the row never reads as blank
        defaults = [(str(len(bullets[:6])), "HIGHLIGHTS"), ("3", "VOICES"), ("WEEK", "WINDOW")]
        i = 0
        while len(stat_cells) < 3 and i < len(defaults):
            stat_cells.append(defaults[i]); i += 1
    stat_cells = stat_cells[:3]
    stats_inner = ''.join(
        f'<div class="cell"><div class="num">{html_escape(v)}</div>'
        f'<div class="lab">{html_escape(l)}</div></div>'
        for v, l in stat_cells
    )
    recap_stats_block = f'<div class="recap-stats">{stats_inner}</div>'

    repl = dict(repl)
    repl.update({
        "BULLETS_HTML": bullets_html,
        "KICKER": html_escape(layers.get("meet_name") or ""),
        "HEADLINE_LINE1": html_escape(headline_line1),
        "HEADLINE_LINE2": html_escape(headline_line2),
        "HEADLINE_FONT_SIZE": str(int(height * 0.115)),
        "RECAP_STATS_BLOCK": recap_stats_block,
    })
    return repl


def _fill_story_card(brief, width: int, height: int, repl: dict[str, str]) -> dict[str, str]:
    layers = brief.text_layers or {}
    repl = dict(repl)
    meet = layers.get("meet_name") or ""
    headline = (meet[:36] + "…") if len(meet) > 36 else meet
    if not headline:
        headline = "FEATURED RESULT"
    repl.update({
        "ATHLETE_W": str(int(width * 0.78)),
        "ATHLETE_H": str(int(height * 0.42)),
        "FIRSTNAME_FONT_SIZE": str(int(height * 0.080)),
        "EVENT_FONT_SIZE": str(int(height * 0.030)),
        "RIBBON_FONT_SIZE": str(int(height * 0.028)),
        "RESULT_FONT_SIZE": str(int(height * 0.060)),
        "SURNAME_FONT_SIZE": str(int(height * 0.30)),
        "RESULT_VALUE_RAW": html_escape(layers.get("result_value") or "—"),
        "STORY_HEADLINE": html_escape(headline.upper()),
    })
    return repl


def _fill_sponsor_branded(brief, width: int, height: int, repl: dict[str, str], sponsor_name: str = "") -> dict[str, str]:
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
        repl["TEXT_LED_COVER_BLOCK"] = (
            f'<div class="cover-mega">{html_escape(mega)}</div>'
            + (f'<div class="cover-sub">{html_escape(sub_text)}</div>' if sub_text else '')
            + (f'<div class="cover-name">{html_escape(full_name)}</div>' if full_name and full_name != mega else '')
        )
    else:
        repl["TEXT_LED_COVER_BLOCK"] = ''
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
    by_width  = (width * 0.85) / max(2, char_count) * 1.50
    by_height = height * 0.30
    hero_size = int(min(by_width, by_height))

    repl.update({
        "HERO_FONT_SIZE": str(hero_size),
        "EVENT_TOP": str(int(height * 0.22)),
        "EVENT_FONT_SIZE": str(int(min(width, height) * 0.028)),
        "ATHLETE_BOTTOM": str(int(height * 0.20)),
        "NAME_FONT_SIZE": str(int(min(width, height) * 0.068)),
        "RESULT_VALUE": html_escape(result_value),
    })
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
# Playwright runner
# ---------------------------------------------------------------------------

def render_html_to_png(html: str, output_path: str | Path, size: tuple[int, int]) -> int:
    """Headless-Chromium render; returns bytes written. Raises if Playwright is unavailable.

    V8.1 Issue 7 upgrades:
      - device_scale_factor configurable (default 2) for sharper text +
        gradients; the captured PNG is then resampled back down to the
        target dimensions with PIL Lanczos for a clean final size.
      - Awaits ``document.fonts.ready`` so @font-face WOFF2 fetches finish
        before the screenshot fires.
    Both upgrades degrade gracefully: if PIL is missing or the larger PNG
    is already the target size, we just write what we have.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Playwright not installed: {e}")

    width, height = size
    dpr = _dpr_render()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--font-render-hinting=none"])
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=dpr,
        )
        page = ctx.new_page()
        page.set_content(html, wait_until="networkidle", timeout=30_000)
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
            full_page=False, type="png", omit_background=False,
            clip={"x": 0, "y": 0, "width": width, "height": height},
        )
        browser.close()

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
    return len(png)


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
    brand_kit=None,
    sponsor_name: str = "",
    venue_attribution: str = "",
    skip_cutout: bool = False,
) -> RenderResult:
    """Render a CreativeBrief into a single PNG. Returns RenderResult."""
    width, height = size
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    family = brief.layout_template or "individual_hero"
    template_path = LAYOUTS_DIR / f"{family}.html"
    if not template_path.exists():
        # Fallback to text-led recap if family is unknown
        family = "text_led_recap"
        template_path = LAYOUTS_DIR / f"{family}.html"

    # Athlete cutout
    athlete_uri = None
    if athlete_path:
        try:
            cut_path = athlete_path if skip_cutout else _maybe_cut_out_athlete(
                athlete_path, profile_id=brief.profile_id or "default")
            athlete_uri = _img_to_data_uri(cut_path)
        except Exception:
            athlete_uri = None

    venue_uri = None
    if venue_path:
        try:
            venue_uri = _img_to_data_uri(venue_path)
        except Exception:
            venue_uri = None

    # Build common replacements
    base_repl = _common_replacements(
        brief, width, height, brand_kit,
        athlete_data_uri=athlete_uri,
        logo_block=_build_logo_block(brand_kit, logo_path),
        result_chip=_build_result_chip(
            "Time" if (brief.text_layers or {}).get("event_name") else "Result",
            (brief.text_layers or {}).get("result_value", ""),
        ),
        sponsor_block=_build_sponsor_block(sponsor_name) if sponsor_name else "",
    )

    # Layout-specific
    if family == "meet_preview":
        repl = _fill_meet_preview(brief, width, height, base_repl,
                                  venue_data_uri=venue_uri,
                                  venue_attribution=venue_attribution)
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

    # Inject the grain SVG <filter> right after <body> so layouts that
    # opt in via class="texture-grain" get the filter resolved. Strip
    # the class entirely when the grain feature flag is off so renders
    # are byte-different (verifiable). V8.1 Issue 7 §3.
    if _grain_enabled():
        html = _re.sub(r"(<body[^>]*>)", r"\1" + _GRAIN_SVG_BLOCK, html, count=1)
        html = html.replace(
            '<div class="canvas"',
            '<div class="canvas texture-grain-host"', 1,
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
            search_from = html.find('>', idx) + 1
            depth = 1
            i = search_from
            close_at = -1
            while i < len(html) and depth > 0:
                next_open = html.find('<div', i)
                next_close = html.find('</div>', i)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    i = html.find('>', next_open) + 1
                else:
                    depth -= 1
                    if depth == 0:
                        close_at = next_close
                        break
                    i = next_close + len('</div>')
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

    # Output path
    visual_id = "v_" + uuid.uuid4().hex[:12]
    out_png = output_dir / f"{format_name}.png"

    bytes_written = render_html_to_png(html, out_png, (width, height))

    visual = GeneratedVisual(
        id=visual_id,
        brief_id=brief.id,
        content_item_id=brief.content_item_id,
        profile_id=brief.profile_id,
        layout_template=family,
        format_name=format_name,
        width=width, height=height,
        file_path=str(out_png),
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
    "render_brief",
    "render_html_to_png",
    "darken",
    "lighten",
]
