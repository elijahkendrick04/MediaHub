"""Render debug / inspection overlay + design-explainability sidecar (roadmap G1.30).

The graphic-renderer's *show your working* surface. Given a finished card's HTML
and the :class:`~mediahub.graphic_renderer.sprint_hooks.RenderHookCtx` that
produced it, this module assembles two artefacts:

* a **design-explainability sidecar** — a plain, JSON-serialisable ``dict`` that
  records *why this design*: the archetype and format, every decorative lever the
  director chose (style pack, ground, accent, typography, composition, photo
  treatment, mood, motion intent), the resolved palette and colour-role
  assignment, the brief's own ``why_this_design`` rationale, and the *measured*
  layout facts read back out of the rendered HTML — the saliency focus the photo
  was steered to, the auto-fitted headline/stat font sizes, and (when an image
  path is supplied) the deterministic saliency crop box; and
* a **render inspection overlay** — a self-contained, ``pointer-events:none`` HUD
  injected on top of the card: a rule-of-thirds grid, a content safe-area frame,
  a crosshair on the saliency centroid, and a corner panel summarising the design
  decisions with the same JSON embedded as a machine-readable
  ``<script type="application/json">`` block.

Like the saliency and autofit modules it sits beside, this is **deterministic
layout-intelligence plumbing — no network, no LLM, no judgement.** It only reads
back facts the deterministic engine already decided; it never invents a design.
It is also strictly **opt-in** (see :func:`inspect_enabled`): off, the matching
render hook is a no-op and renders stay byte-identical.

Public API:
    inspect_enabled(ctx) -> bool
    parse_fitted_sizes(html) -> list[FittedSize]
    parse_focus_position(html) -> Focus | None
    crop_box_for(image_path, *, width, height, ratio) -> tuple | None
    design_explainability(html, ctx, *, image_path=None) -> dict
    build_overlay_html(data, ctx) -> str
    render_inspect_overlay(html, ctx, *, image_path=None) -> str
    write_sidecar(json_path, data) -> Path
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from html import escape as _escape
from pathlib import Path
from typing import Any, Optional, Union

from .style_packs import mood_preset_note

__all__ = [
    "INSPECT_ENV",
    "SCHEMA",
    "FittedSize",
    "Focus",
    "inspect_enabled",
    "parse_fitted_sizes",
    "parse_focus_position",
    "crop_box_for",
    "design_explainability",
    "build_overlay_html",
    "render_inspect_overlay",
    "write_sidecar",
]

# Operator toggle: any of these (case-insensitive) turns the overlay on globally.
INSPECT_ENV = "MEDIAHUB_INSPECT_OVERLAY"
# Per-brief opt-in attribute (read via getattr, so no CreativeBrief field is
# required — legacy briefs simply lack it and stay off).
_BRIEF_FLAG = "inspect_overlay"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Versioned so a downstream reader can tell which sidecar shape it's looking at.
SCHEMA = "mediahub.graphic.inspect/1"

# A high but legal z-index so the HUD sits above everything the pipeline injects
# (the demo watermark uses 9999); pointer-events:none keeps it non-interactive.
_Z = 2147483600


@dataclass(frozen=True)
class FittedSize:
    """One auto-fitted font size read back out of the rendered HTML."""

    px: float
    count: int  # how many elements carry this exact size
    sample: str  # a short snippet of text rendered at this size ("" if none)


@dataclass(frozen=True)
class Focus:
    """The saliency focus a full-bleed photo was steered to, as frame percentages."""

    x_pct: float
    y_pct: float
    raw: str  # the original CSS object-position value


# --------------------------------------------------------------------------- #
# Opt-in gate
# --------------------------------------------------------------------------- #
def inspect_enabled(ctx: Any) -> bool:
    """True when the inspection overlay should be drawn for this render.

    On when the ``MEDIAHUB_INSPECT_OVERLAY`` env var is truthy (operator-wide
    debug switch) **or** the brief carries a truthy ``inspect_overlay`` attribute
    (per-card opt-in). Off otherwise — the default — so renders are unchanged.
    """
    if os.environ.get(INSPECT_ENV, "").strip().lower() in _TRUTHY:
        return True
    brief = getattr(ctx, "brief", None)
    return bool(getattr(brief, _BRIEF_FLAG, False))


# --------------------------------------------------------------------------- #
# Read-back parsers — facts measured from the finished HTML
# --------------------------------------------------------------------------- #
# Capture the element's opening tag (with its font-size) plus the immediate text
# that follows, so we can show a representative sample for each fitted size.
_FONT_TAG_RE = re.compile(
    r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px[^>]*>\s*([^<>{]{0,48})",
    re.IGNORECASE,
)
_FONT_ANY_RE = re.compile(r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px", re.IGNORECASE)


def parse_fitted_sizes(html: str) -> list[FittedSize]:
    """Every ``font-size:Npx`` in ``html``, largest first, de-duplicated.

    These are the *actual* sizes the deterministic auto-fit baked into the card —
    read straight back out of the markup rather than re-derived, so the sidecar
    can never disagree with what was painted. Each entry keeps an occurrence count
    and a short sample of the text rendered at that size (best effort).
    """
    if not html:
        return []
    samples: dict[float, str] = {}
    counts: dict[float, int] = {}
    # First pass: sizes that sit directly on a text-bearing element (gives a sample).
    for m in _FONT_TAG_RE.finditer(html):
        px = round(float(m.group(1)), 2)
        text = " ".join(m.group(2).split()).strip()
        counts[px] = counts.get(px, 0) + 1
        if text and not samples.get(px):
            samples[px] = text[:32]
    # Second pass: any remaining sizes (wrappers with no inline text) still count.
    seen_total: dict[float, int] = {}
    for m in _FONT_ANY_RE.finditer(html):
        px = round(float(m.group(1)), 2)
        seen_total[px] = seen_total.get(px, 0) + 1
    for px, total in seen_total.items():
        counts[px] = max(counts.get(px, 0), total)
        samples.setdefault(px, "")
    return [
        FittedSize(px=px, count=counts[px], sample=samples.get(px, ""))
        for px in sorted(counts, reverse=True)
    ]


_KEYWORD_X = {"left": 0.0, "center": 50.0, "centre": 50.0, "right": 100.0}
_KEYWORD_Y = {"top": 0.0, "center": 50.0, "centre": 50.0, "bottom": 100.0}


def _css_value(html: str, name: str) -> str:
    """First value of a CSS custom property / declaration ``name`` in ``html``."""
    m = re.search(re.escape(name) + r"\s*:\s*([^;}\"'<]+)", html)
    return m.group(1).strip() if m else ""


def _axis_pct(token: str, axis: str) -> float:
    token = token.strip().lower()
    if token.endswith("%"):
        try:
            return max(0.0, min(100.0, float(token[:-1])))
        except ValueError:
            return 50.0
    table = _KEYWORD_X if axis == "x" else _KEYWORD_Y
    return table.get(token, 50.0)


def parse_focus_position(html: str) -> Optional[Focus]:
    """The saliency focus the photo was steered to, parsed to frame percentages.

    Reads the renderer's ``--mh-photo-pos`` custom property (falling back to a
    literal ``object-position``) — the value :func:`saliency.focus_position`
    produced — and converts keywords/percentages to an ``(x%, y%)`` centroid.
    Returns ``None`` when the card carries no full-bleed photo position.
    """
    raw = _css_value(html, "--mh-photo-pos") or _css_value(html, "object-position")
    if not raw:
        return None
    tokens = raw.replace(";", "").split()
    if not tokens:
        return None
    if len(tokens) == 1:
        only = tokens[0].lower()
        # A bare vertical keyword ("top"/"bottom") pins Y and centres X; anything
        # else is read as the X axis with Y centred (matches CSS shorthand).
        if only in _KEYWORD_Y and only not in _KEYWORD_X:
            return Focus(x_pct=50.0, y_pct=_axis_pct(only, "y"), raw=raw.strip())
        return Focus(x_pct=_axis_pct(only, "x"), y_pct=50.0, raw=raw.strip())
    return Focus(
        x_pct=_axis_pct(tokens[0], "x"),
        y_pct=_axis_pct(tokens[1], "y"),
        raw=raw.strip(),
    )


def crop_box_for(
    image_path: Optional[Union[str, Path]],
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    ratio: Optional[str] = None,
) -> Optional[tuple[int, int, int, int]]:
    """The deterministic saliency crop box for this card's format, or ``None``.

    Delegates to :func:`saliency.best_crop` — the same maths the renderer used to
    steer the photo — for callers that hold the source image. ``ratio`` wins; else
    it's derived from ``width``/``height``; else a portrait ``4:5`` default. Any
    failure (no image, bad file, missing Pillow) returns ``None`` rather than
    raising, so inspection never breaks a render.
    """
    if not image_path:
        return None
    try:
        from .saliency import best_crop

        spec = ratio
        if spec is None and width and height:
            spec = f"{int(width)}:{int(height)}"
        if spec is None:
            spec = "4:5"
        x, y, w, h = best_crop(image_path, spec)
        return int(x), int(y), int(w), int(h)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Explainability sidecar
# --------------------------------------------------------------------------- #
def _brief_get(brief: Any, name: str, default: Any = "") -> Any:
    value = getattr(brief, name, default)
    return default if value is None else value


def design_explainability(
    html: str,
    ctx: Any,
    *,
    image_path: Optional[Union[str, Path]] = None,
) -> dict:
    """Assemble the *why-this-design* sidecar dict for a finished card.

    Pure data: card identity, the director's chosen levers, palette/role
    assignment, the brief's rationale, and the measured layout facts read back
    from ``html`` (focus, fitted sizes, and — when ``image_path`` is given — the
    saliency crop box). JSON-serialisable; the same payload the overlay embeds and
    :func:`write_sidecar` can persist beside a PNG.
    """
    brief = getattr(ctx, "brief", None)
    width = int(getattr(ctx, "width", 0) or 0)
    height = int(getattr(ctx, "height", 0) or 0)

    fitted = parse_fitted_sizes(html)
    focus = parse_focus_position(html)
    crop = crop_box_for(image_path, width=width, height=height)

    sizes_px = [f.px for f in fitted]
    layout: dict[str, Any] = {
        "focus_position": (
            {"x_pct": round(focus.x_pct, 2), "y_pct": round(focus.y_pct, 2), "raw": focus.raw}
            if focus
            else None
        ),
        "crop_box": ({"x": crop[0], "y": crop[1], "w": crop[2], "h": crop[3]} if crop else None),
        "fitted_sizes": [{"px": f.px, "count": f.count, "sample": f.sample} for f in fitted],
        "fitted_size_range": (
            {"min": min(sizes_px), "max": max(sizes_px), "count": len(sizes_px)}
            if sizes_px
            else None
        ),
    }

    return {
        "schema": SCHEMA,
        "card": {
            "brief_id": str(_brief_get(brief, "id", "")),
            "content_item_id": str(_brief_get(brief, "content_item_id", "")),
            "profile_id": str(_brief_get(brief, "profile_id", "")),
            "format": str(getattr(ctx, "format_name", "") or ""),
            "width": width,
            "height": height,
            "archetype": str(getattr(ctx, "family", "") or ""),
            "is_v2": bool(getattr(ctx, "is_v2", False)),
        },
        "design": {
            "layout_family": str(_brief_get(brief, "layout_template", "")),
            "style_pack": str(_brief_get(brief, "style_pack", "")),
            "background_style": str(_brief_get(brief, "background_style", "")),
            "accent_style": str(_brief_get(brief, "accent_style", "")),
            "typography_pair": str(_brief_get(brief, "typography_pair", "")),
            "composition": str(_brief_get(brief, "composition", "")),
            "photo_treatment": str(_brief_get(brief, "photo_treatment", "")),
            "decoration_strength": _brief_get(brief, "decoration_strength", None),
            "mood": str(_brief_get(brief, "mood", "")),
            # The authored one-line rationale for the mood's curated pack
            # bundle — why a mood-scoped pack pick decorated the card this way.
            "mood_note": mood_preset_note(str(_brief_get(brief, "mood", ""))),
            "motion_intent": str(_brief_get(brief, "motion_intent", "")),
            "tone": str(_brief_get(brief, "tone", "")),
            "objective": str(_brief_get(brief, "objective", "")),
            "confidence_label": str(_brief_get(brief, "confidence_label", "")),
            "palette": dict(_brief_get(brief, "palette", {}) or {}),
            "colour_role_assignment": dict(_brief_get(brief, "colour_role_assignment", {}) or {}),
            "hero_stat_options": dict(_brief_get(brief, "hero_stat_options", {}) or {}),
            "variation_signature": str(_brief_get(brief, "variation_signature", "")),
        },
        "why_this_design": str(_brief_get(brief, "why_this_design", "")),
        "layout": layout,
    }


# --------------------------------------------------------------------------- #
# Visual overlay
# --------------------------------------------------------------------------- #
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_RGB_RE = re.compile(r"^rgba?\([0-9.,%\s]+\)$")
_NAMED_RE = re.compile(r"^[a-zA-Z]{3,20}$")

_GUIDE = "#36f0c8"  # cyan hairlines — grid + safe area
_MARK = "#ffb020"  # amber — saliency focus crosshair
_INK = "#d7f4ec"


def _safe_color(value: Any) -> str:
    """Clamp a palette value to a CSS colour we are willing to inline."""
    v = str(value or "").strip()
    if _HEX_RE.match(v) or _RGB_RE.match(v) or _NAMED_RE.match(v):
        return v
    return "#888888"


def _embedded_json(data: dict) -> str:
    """``data`` as JSON safe to drop inside a ``<script type=application/json>``."""
    raw = json.dumps(data, sort_keys=True, default=str)
    # Neutralise sequence-ending bytes so the payload can never break out of the
    # script element (or be misread as markup).
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _svg_guides(data: dict, width: int, height: int) -> str:
    """Rule-of-thirds grid, content safe-area frame, and the focus crosshair."""
    w, h = max(1, width), max(1, height)
    parts = [
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        f'style="position:absolute;inset:0;width:100%;height:100%;display:block">'
    ]
    # Rule-of-thirds.
    for fx in (1 / 3, 2 / 3):
        parts.append(
            f'<line x1="{w * fx:.1f}" y1="0" x2="{w * fx:.1f}" y2="{h}" '
            f'stroke="{_GUIDE}" stroke-width="1.5" opacity="0.25"/>'
        )
    for fy in (1 / 3, 2 / 3):
        parts.append(
            f'<line x1="0" y1="{h * fy:.1f}" x2="{w}" y2="{h * fy:.1f}" '
            f'stroke="{_GUIDE}" stroke-width="1.5" opacity="0.25"/>'
        )
    # Content safe-area (6% inset) — where platform UI won't crop the message.
    mx, my = w * 0.06, h * 0.06
    parts.append(
        f'<rect x="{mx:.1f}" y="{my:.1f}" width="{w - 2 * mx:.1f}" height="{h - 2 * my:.1f}" '
        f'fill="none" stroke="{_GUIDE}" stroke-width="2" stroke-dasharray="14 10" opacity="0.5"/>'
    )
    # Saliency focus crosshair.
    focus = (data.get("layout") or {}).get("focus_position")
    if focus:
        cx = max(0.0, min(100.0, float(focus.get("x_pct", 50.0)))) / 100.0 * w
        cy = max(0.0, min(100.0, float(focus.get("y_pct", 50.0)))) / 100.0 * h
        r = max(18.0, min(w, h) * 0.05)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" '
            f'stroke="{_MARK}" stroke-width="2.5"/>'
            f'<line x1="{cx:.1f}" y1="{cy - r * 1.7:.1f}" x2="{cx:.1f}" y2="{cy + r * 1.7:.1f}" '
            f'stroke="{_MARK}" stroke-width="2"/>'
            f'<line x1="{cx - r * 1.7:.1f}" y1="{cy:.1f}" x2="{cx + r * 1.7:.1f}" y2="{cy:.1f}" '
            f'stroke="{_MARK}" stroke-width="2"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{_MARK}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _swatches(palette: dict) -> str:
    chips = []
    for key in ("primary", "secondary", "accent"):
        if key in palette:
            chips.append(
                f'<span title="{_escape(str(key))}" style="display:inline-block;width:1em;'
                f"height:1em;border-radius:2px;margin-right:3px;vertical-align:-2px;"
                f'border:1px solid rgba(255,255,255,0.3);background:{_safe_color(palette[key])}"></span>'
            )
    return "".join(chips)


def _panel(data: dict, scale: float) -> str:
    """Top-left HUD card summarising the design decisions (HTML-escaped)."""
    card = data.get("card") or {}
    design = data.get("design") or {}
    layout = data.get("layout") or {}

    def row(label: str, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        return (
            f'<div style="display:flex;gap:8px;margin:2px 0">'
            f'<span style="opacity:0.55;min-width:5.5em">{_escape(label)}</span>'
            f'<span style="color:{_INK}">{_escape(value)}</span></div>'
        )

    fmt = card.get("format", "")
    dims = f"{card.get('width', 0)}×{card.get('height', 0)}"
    focus = layout.get("focus_position")
    focus_txt = f"{focus['x_pct']:.0f}% {focus['y_pct']:.0f}%" if focus else "—"
    rng = layout.get("fitted_size_range")
    fitted_txt = f"{rng['min']:.0f}–{rng['max']:.0f}px · {rng['count']} sizes" if rng else "—"
    crop = layout.get("crop_box")
    crop_txt = f"{crop['w']}×{crop['h']} @ {crop['x']},{crop['y']}" if crop else ""
    why = (data.get("why_this_design") or "").strip()
    if len(why) > 220:
        why = why[:217].rstrip() + "…"

    rows = "".join(
        [
            row("archetype", str(card.get("archetype", ""))),
            row("format", f"{fmt}  {dims}" if fmt else dims),
            row("style", str(design.get("style_pack", "")) or "—"),
            row("mood", str(design.get("mood_note", "")) or str(design.get("mood", ""))),
            row("ground", str(design.get("background_style", ""))),
            row("accent", str(design.get("accent_style", ""))),
            row("type", str(design.get("typography_pair", ""))),
            row("photo", str(design.get("photo_treatment", ""))),
            row("focus", focus_txt),
            row("crop", crop_txt),
            row("fitted", fitted_txt),
            row("conf", str(design.get("confidence_label", ""))),
        ]
    )
    palette_chips = _swatches(design.get("palette") or {})
    why_block = (
        f'<div style="margin-top:6px;padding-top:6px;border-top:1px solid '
        f'rgba(54,240,200,0.25);opacity:0.85;line-height:1.4">{_escape(why)}</div>'
        if why
        else ""
    )
    pad = max(10, round(14 * scale))
    base_px = max(12, round(15 * scale))
    head_px = max(13, round(17 * scale))
    return (
        f'<div class="mh-inspect-panel" style="position:absolute;top:{pad}px;left:{pad}px;'
        f"max-width:46%;background:rgba(6,12,16,0.86);color:{_INK};"
        f"border:1px solid rgba(54,240,200,0.5);border-radius:8px;padding:{pad}px {pad + 2}px;"
        f"font:{base_px}px/1.45 ui-monospace,'SF Mono',Menlo,Consolas,monospace;"
        f'box-shadow:0 6px 26px rgba(0,0,0,0.5);letter-spacing:0.01em">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;'
        f"font-size:{head_px}px;font-weight:700;letter-spacing:0.16em;color:{_GUIDE};"
        f'margin-bottom:6px">RENDER INSPECT {palette_chips}</div>'
        f"{rows}{why_block}</div>"
    )


def build_overlay_html(data: dict, ctx: Any) -> str:
    """The full ``pointer-events:none`` inspection HUD for ``data``.

    A fixed, full-canvas layer (SVG guides + focus crosshair, the summary panel,
    and the machine-readable JSON sidecar). Deterministic for a given ``data``.
    """
    width = int(getattr(ctx, "width", 0) or 0) or 1080
    height = int(getattr(ctx, "height", 0) or 0) or 1920
    scale = max(0.85, min(2.4, width / 1080.0))
    svg = _svg_guides(data, width, height)
    panel = _panel(data, scale)
    payload = _embedded_json(data)
    return (
        f'<div class="mh-inspect-overlay" data-mh-inspect="1" '
        f'style="position:fixed;inset:0;z-index:{_Z};pointer-events:none;overflow:hidden">'
        f"{svg}{panel}"
        f'<script type="application/json" id="mh-inspect-data">{payload}</script>'
        f"</div>"
    )


def render_inspect_overlay(
    html: str,
    ctx: Any,
    *,
    image_path: Optional[Union[str, Path]] = None,
) -> str:
    """Return ``html`` with the inspection overlay injected before ``</body>``.

    Idempotent (a card already carrying the overlay is returned unchanged) and
    best-effort: any internal failure returns the original ``html`` so inspection
    can never break a render.
    """
    if not isinstance(html, str) or not html:
        return html
    if 'id="mh-inspect-data"' in html:
        return html
    try:
        data = design_explainability(html, ctx, image_path=image_path)
        overlay = build_overlay_html(data, ctx)
    except Exception:
        return html
    if "</body>" in html:
        return html.replace("</body>", overlay + "</body>", 1)
    return html + overlay


# --------------------------------------------------------------------------- #
# Sidecar persistence
# --------------------------------------------------------------------------- #
def write_sidecar(json_path: Union[str, Path], data: dict) -> Path:
    """Write the explainability ``data`` to ``json_path`` (pretty, stable order).

    Mirrors the motion engine's ``<hash>.json`` manifest: a real on-disk sidecar a
    caller that holds the output path can drop beside the rendered PNG. Returns the
    written path; parent directories are created as needed.
    """
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path
