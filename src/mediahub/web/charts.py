"""UI 1.6 — Animated results/data charts (Mixpanel-inspired).

Two small, dependency-free chart renderers used on two surfaces:

* the **landing** "sample-outputs" section (honest sample data), and
* the **in-app** parsed-results review view (real per-run data).

Both produce pure HTML/SVG styled with CSS custom properties — **no charting
SDK, no canvas, no external fetch** (vanilla, self-hosted, GDPR-clean like the
rest of MediaHub). They animate *on scroll*: the markup carries
``class="mh-chart" data-mh-animate`` so the existing ``bindReveals``
IntersectionObserver (in ``web._layout``) adds ``.is-in`` when the chart scrolls
into view; the bar-grow / line-draw is then a pure CSS transition gated on that
class (see ``theme-components.css`` → "UI 1.6"). No-JS and
``prefers-reduced-motion`` visitors get the final, fully-drawn chart immediately
— the animation is pure progressive enhancement, data is never hidden.

These renderers are *presentation only*. They never invent data: the caller
passes already-computed values (counts, the ranker's worthiness scores, …) and
the chart draws exactly those. This keeps them on the deterministic side of the
engine boundary — there is no judgement to make, so there is no LLM here.

Everything user/data-derived (labels, captions, values) is HTML-escaped via
``markupsafe.escape``; tone names and ids are validated against allow-lists, so
the output is XSS-safe even when fed swimmer names straight from a parsed file.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

from markupsafe import escape as _esc

__all__ = ["BarDatum", "AreaPoint", "bar_chart", "area_chart"]

# Tone → CSS class. Anything not in here falls back to "neutral", so a caller
# can never inject an arbitrary class name through the `tone` field.
_TONES = {
    "gold",
    "silver",
    "bronze",
    "lane",
    "info",
    "good",
    "bad",
    "neutral",
}


def _safe_tone(tone: Optional[str]) -> str:
    t = (tone or "").strip().lower()
    return t if t in _TONES else "neutral"


def _id_attr(chart_id: Optional[str]) -> str:
    """An optional ``id="mh-chart-<safe>"`` for the <figure>, for anchoring."""
    return f' id="mh-chart-{_safe_id(chart_id)}"' if chart_id else ""


def _safe_id(chart_id: Optional[str]) -> str:
    """A DOM/SVG-safe id fragment. Unknown chars dropped; empty → random.

    SVG gradient ids must be unique per page (two charts sharing a
    ``<linearGradient id>`` would cross-reference), so when the caller gives
    no id we mint a short random one.
    """
    raw = "".join(ch for ch in (chart_id or "") if ch.isalnum() or ch in "-_")
    return raw or "c" + uuid.uuid4().hex[:8]


def _fmt_value(value: float) -> str:
    """Whole numbers render clean ("8"), fractions to one decimal ("0.9")."""
    if not math.isfinite(value):
        return "0"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:.1f}"


@dataclass(frozen=True)
class BarDatum:
    """One column of a bar/podium chart.

    ``value`` drives the bar height (relative to the tallest bar). ``text`` is
    an optional pre-formatted display string (e.g. ``"52.41s"``); when given,
    the value is shown verbatim and *not* count-animated (you cannot count a
    swim time up from zero honestly). When absent, the numeric value is shown
    and — if it is a whole number — counts up via ``data-mh-count``.
    """

    label: str
    value: float
    tone: Optional[str] = None
    text: Optional[str] = None


@dataclass(frozen=True)
class AreaPoint:
    """One point of the cohort/area trend line. ``label`` is the x-axis tick."""

    label: str
    value: float


def _coerce_bars(bars: Iterable) -> list[BarDatum]:
    out: list[BarDatum] = []
    for b in bars:
        if isinstance(b, BarDatum):
            out.append(b)
        elif isinstance(b, dict):
            try:
                val = float(b.get("value", 0) or 0)
            except (TypeError, ValueError):
                val = 0.0
            out.append(
                BarDatum(
                    label=str(b.get("label", "")),
                    value=val,
                    tone=b.get("tone"),
                    text=b.get("text"),
                )
            )
    return out


def _coerce_points(points: Iterable) -> list[AreaPoint]:
    out: list[AreaPoint] = []
    for p in points:
        if isinstance(p, AreaPoint):
            out.append(p)
        elif isinstance(p, dict):
            try:
                val = float(p.get("value", 0) or 0)
            except (TypeError, ValueError):
                val = 0.0
            out.append(AreaPoint(label=str(p.get("label", "")), value=val))
    return out


def _empty(kind: str, caption: Optional[str]) -> str:
    cap = f'<figcaption class="mh-chart-cap">{_esc(caption)}</figcaption>' if caption else ""
    return (
        f'<figure class="mh-chart mh-chart--{kind} is-empty">'
        '<div class="mh-chart-empty">No data to chart yet.</div>'
        f"{cap}</figure>"
    )


def bar_chart(
    bars: Iterable,
    *,
    caption: Optional[str] = None,
    chart_id: Optional[str] = None,
    animate: bool = True,
) -> str:
    """Render an animated vertical **bar / podium** chart.

    ``bars`` is a sequence of :class:`BarDatum` (or plain dicts with the same
    keys). Heights are scaled to the tallest bar (the tallest fills the plot).
    Returns a self-contained ``<figure>`` string.
    """
    data = _coerce_bars(bars)
    if not data:
        return _empty("bars", caption)

    vmax = max((b.value for b in data), default=0.0)
    rows = []
    for b in data:
        pct = 0.0 if vmax <= 0 else max(0.0, b.value) / vmax * 100.0
        pct_s = f"{pct:.2f}".rstrip("0").rstrip(".") or "0"
        tone = _safe_tone(b.tone)
        # The value readout. A pre-formatted `text` is shown verbatim; a bare
        # whole number counts up on reveal; a fraction is shown as-is.
        if b.text is not None:
            val_html = str(_esc(b.text))
        elif animate and math.isfinite(b.value) and float(b.value).is_integer():
            n = int(b.value)
            val_html = f'<span data-mh-count="{n}">{_fmt_value(b.value)}</span>'
        else:
            val_html = _fmt_value(b.value)
        rows.append(
            f'<div class="mh-chart-bar tone-{tone}" style="--mh-bar:{pct_s}%">'
            '<span class="mh-chart-bar-track">'
            f'<span class="mh-chart-bar-val">{val_html}</span>'
            '<span class="mh-chart-bar-fill"></span>'
            "</span>"
            "</div>"
        )

    # The x-axis labels ride a parallel flex row so each tick sits under its bar
    # and a single baseline can run beneath the plot. Same column model
    # (flex:1 per cell) keeps them aligned on every viewport.
    ticks = "".join(f'<span class="mh-chart-xtick">{_esc(b.label)}</span>' for b in data if b.label)
    xaxis = (
        f'<div class="mh-chart-xaxis mh-chart-xaxis--bars">{ticks}</div>' if ticks.strip() else ""
    )

    # Accessible summary: the figure announces the data; the bars carry their
    # own visible numbers/labels too, so AT users get the full picture.
    summary = ", ".join(f"{b.label} {_fmt_value(b.value)}" for b in data if b.label)
    aria = _esc(caption or summary or "Bar chart")
    cap_html = f'<figcaption class="mh-chart-cap">{_esc(caption)}</figcaption>' if caption else ""
    animate_attr = " data-mh-animate" if animate else ""
    return (
        f'<figure class="mh-chart mh-chart--bars"{_id_attr(chart_id)}{animate_attr} '
        f'role="group" aria-label="{aria}">'
        '<div class="mh-chart-bars">' + "".join(rows) + "</div>"
        f"{xaxis}"
        f"{cap_html}</figure>"
    )


# Area-chart geometry (viewBox units). Wide + short so it reads as a trend
# strip across a card; the aspect ratio is preserved on scale so dots stay
# round and the stroke stays even.
_AW, _AH = 384.0, 120.0
_PAD_T, _PAD_B, _PAD_X = 14.0, 12.0, 8.0


def area_chart(
    points: Iterable,
    *,
    caption: Optional[str] = None,
    chart_id: Optional[str] = None,
    tone: str = "lane",
    animate: bool = True,
    show_dots: Optional[bool] = None,
) -> str:
    """Render an animated **cohort / area** trend chart.

    ``points`` is a sequence of :class:`AreaPoint` (or dicts). Needs at least
    two points to draw a line; fewer renders a tasteful empty state. The line
    *draws* left-to-right on reveal (``pathLength`` + ``stroke-dashoffset``) and
    the fill fades up under it. Returns a self-contained ``<figure>`` string.
    """
    data = _coerce_points(points)
    if len(data) < 2:
        return _empty("area", caption)

    cid = _safe_id(chart_id)
    grad_id = f"mh-area-grad-{cid}"
    tone_cls = _safe_tone(tone)

    n = len(data)
    vmax = max((p.value for p in data), default=0.0)
    inner_w = _AW - 2 * _PAD_X
    inner_h = _AH - _PAD_T - _PAD_B
    baseline = _AH - _PAD_B

    coords: list[tuple[float, float]] = []
    for i, p in enumerate(data):
        x = _PAD_X + (i / (n - 1)) * inner_w
        frac = 0.0 if vmax <= 0 else max(0.0, p.value) / vmax
        y = _PAD_T + (1.0 - frac) * inner_h
        coords.append((round(x, 2), round(y, 2)))

    line_d = "M" + " L".join(f"{x},{y}" for x, y in coords)
    area_d = (
        f"M{coords[0][0]},{baseline:.2f} "
        + "L"
        + " L".join(f"{x},{y}" for x, y in coords)
        + f" L{coords[-1][0]},{baseline:.2f} Z"
    )

    # Faint horizontal gridlines (top, middle, baseline) for a little structure.
    grid = "".join(
        f'<line class="mh-chart-grid" x1="{_PAD_X:.2f}" y1="{gy:.2f}" '
        f'x2="{_AW - _PAD_X:.2f}" y2="{gy:.2f}" />'
        for gy in (_PAD_T, _PAD_T + inner_h / 2, baseline)
    )

    if show_dots is None:
        show_dots = n <= 12
    dots = ""
    if show_dots:
        dots = "".join(
            f'<circle class="mh-chart-area-dot" cx="{x}" cy="{y}" r="2.2" style="--mh-dot-i:{i}" />'
            for i, (x, y) in enumerate(coords)
        )

    ticks = "".join(f'<span class="mh-chart-xtick">{_esc(p.label)}</span>' for p in data if p.label)
    xaxis = f'<div class="mh-chart-xaxis">{ticks}</div>' if ticks.strip() else ""

    cap_html = f'<figcaption class="mh-chart-cap">{_esc(caption)}</figcaption>' if caption else ""
    first_v = _fmt_value(data[0].value)
    last_v = _fmt_value(data[-1].value)
    aria = _esc(caption or f"Trend chart from {first_v} to {last_v} across {n} points")
    animate_attr = " data-mh-animate" if animate else ""

    svg = (
        f'<svg class="mh-chart-area-svg" viewBox="0 0 {_AW:.0f} {_AH:.0f}" '
        'preserveAspectRatio="xMidYMid meet" aria-hidden="true" '
        'focusable="false">'
        f'<defs><linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" class="mh-chart-area-stop-0" />'
        '<stop offset="1" class="mh-chart-area-stop-1" />'
        "</linearGradient></defs>"
        f"{grid}"
        f'<path class="mh-chart-area-fill" d="{area_d}" '
        f'fill="url(#{grad_id})" />'
        f'<path class="mh-chart-area-line" d="{line_d}" pathLength="1" '
        'fill="none" />'
        f"{dots}"
        "</svg>"
    )
    return (
        f'<figure class="mh-chart mh-chart--area tone-{tone_cls}"{_id_attr(chart_id)}'
        f'{animate_attr} role="group" aria-label="{aria}">'
        f'<div class="mh-chart-area-wrap">{svg}</div>'
        f"{xaxis}"
        f"{cap_html}</figure>"
    )
