"""charts.render — turn a ChartSpec into deterministic, brand-styled SVG.

This is the deterministic heart of roadmap 1.11: given a fully-resolved
:class:`~charts.models.ChartSpec` and the org's brand role vars, it draws the
chart as self-contained SVG — axes, gridlines, bars, lines, slices, tables — with
**no LLM anywhere near the geometry**. The numbers are plotted exactly as the spec
states them; the AI only ever chose *which* chart and *how to phrase* the takeaway
(elsewhere). Same spec + same role vars → byte-identical SVG.

The output is one ``<svg>`` document: it renders natively in a browser/``<img>``,
embeds into card or microsite HTML, and rasterises through the existing HTML→PNG
pass for export. Fonts are self-hosted and inlined (:mod:`charts.fonts`) so the
file is CDN-free on every surface.
"""

from __future__ import annotations

import math
from typing import Optional

from . import fonts as _fonts
from .models import ChartSpec, Series, format_value
from .palette import ChartColours, role_vars_from_palette

# Plot chrome proportions (fractions of the short edge) — kept deterministic.
_PAD = 0.055  # outer padding
_TITLE_H = 0.085  # headline band when a title is present
_SUB_H = 0.045  # subtitle line
_FOOT_H = 0.045  # source/footnote band


def render_chart_svg(
    spec: ChartSpec,
    role_vars: Optional[dict[str, str]] = None,
    *,
    palette: Optional[dict] = None,
    brand_kit=None,
    embed_fonts: bool = True,
) -> str:
    """Render ``spec`` to a complete, brand-styled SVG string.

    ``role_vars`` is the resolved ``--mh-*`` set (preferred). If absent it is
    derived from ``palette`` / ``brand_kit`` via the same resolver the cards use.
    """
    if role_vars is None:
        role_vars = role_vars_from_palette(palette, brand_kit)
    colours = ChartColours(role_vars)

    w, h = int(spec.width), int(spec.height)
    short = max(1, min(w, h))
    pad = round(_PAD * short)

    # Vertical bands: title → subtitle → plot → footer.
    y = pad
    head_top = y
    if spec.title:
        y += round(_TITLE_H * short)
    if spec.subtitle:
        y += round(_SUB_H * short)
    plot_top = y + (round(0.02 * short) if (spec.title or spec.subtitle) else 0)

    foot_h = round(_FOOT_H * short) if (spec.source_note or spec.footnote) else 0
    plot_bottom = h - pad - foot_h
    plot_left = pad
    plot_right = w - pad

    frag: list[str] = []
    frag.append(_svg_open(w, h, embed_fonts))
    # Brand ground.
    frag.append(_rect(0, 0, w, h, colours.ground))
    # Headline chrome.
    frag.append(_header(spec, colours, x=pad, top=head_top, width=w - 2 * pad, short=short))
    if foot_h:
        frag.append(
            _footer(spec, colours, x=pad, bottom=h - pad, width=w - 2 * pad, short=short)
        )

    box = _Box(plot_left, plot_top, plot_right, plot_bottom)
    if spec.is_empty():
        frag.append(_empty_state(box, colours, short))
    else:
        kind = spec.kind
        if kind in ("bar", "hbar"):
            frag.append(_render_bars(spec, colours, box, short, horizontal=(kind == "hbar")))
        elif kind in ("line", "progression"):
            frag.append(_render_line(spec, colours, box, short))
        elif kind in ("pie", "donut"):
            frag.append(_render_pie(spec, colours, box, short, donut=(kind == "donut")))
        elif kind == "scatter":
            frag.append(_render_scatter(spec, colours, box, short))
        elif kind in ("table", "medal_table"):
            frag.append(_render_table(spec, colours, box, short))
        elif kind == "split_ladder":
            frag.append(_render_split_ladder(spec, colours, box, short))
    frag.append("</svg>")
    return "".join(frag)


# --------------------------------------------------------------------------- #
# plot box
# --------------------------------------------------------------------------- #
class _Box:
    """The rectangle a chart body draws into."""

    __slots__ = ("left", "top", "right", "bottom")

    def __init__(self, left: float, top: float, right: float, bottom: float):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    @property
    def w(self) -> float:
        return max(1.0, self.right - self.left)

    @property
    def h(self) -> float:
        return max(1.0, self.bottom - self.top)


# --------------------------------------------------------------------------- #
# chrome: header / footer / empty state
# --------------------------------------------------------------------------- #
def _header(spec: ChartSpec, c: ChartColours, *, x: int, top: int, width: int, short: int) -> str:
    out: list[str] = []
    ty = top
    if spec.title:
        size = round(0.055 * short)
        ty += size
        out.append(
            _text(
                x, ty, _esc(spec.title), size, c.ink,
                family=_fonts.display_stack(), weight="400", spacing="0.5px",
            )
        )
        # Accent rule under the title.
        out.append(_rect(x, ty + round(0.012 * short), round(0.10 * short), max(3, round(0.006 * short)), c.accent))
    if spec.subtitle:
        size = round(0.028 * short)
        ty += round(0.05 * short)
        out.append(_text(x, ty, _esc(spec.subtitle), size, c.muted, family=_fonts.body_stack()))
    return "".join(out)


def _footer(spec: ChartSpec, c: ChartColours, *, x: int, bottom: int, width: int, short: int) -> str:
    size = round(0.020 * short)
    parts = [p for p in (spec.source_note, spec.footnote) if p]
    line = "  ·  ".join(parts)
    return _text(x, bottom, _esc(line), size, c.muted, family=_fonts.body_stack())


def _empty_state(box: _Box, c: ChartColours, short: int) -> str:
    size = round(0.03 * short)
    cx = (box.left + box.right) / 2
    cy = (box.top + box.bottom) / 2
    return _text(
        cx, cy, "No data to chart yet", size, c.muted,
        family=_fonts.body_stack(), anchor="middle",
    )


# --------------------------------------------------------------------------- #
# bar / hbar
# --------------------------------------------------------------------------- #
def _render_bars(spec: ChartSpec, c: ChartColours, box: _Box, short: int, *, horizontal: bool) -> str:
    series = [s for s in spec.series if s.points]
    if not series:
        return ""
    n_series = len(series)
    categories = [p.label for p in series[0].points]
    n_cat = len(categories)
    if n_cat == 0:
        return ""

    value_axis = spec.y_axis if not horizontal else spec.x_axis
    vlo, vhi = _bar_domain(spec, value_axis)
    ticks = _nice_ticks(vlo, vhi)
    vhi = max(vhi, ticks[-1]) if ticks else vhi
    out: list[str] = []
    label_size = round(0.022 * short)

    if not horizontal:
        # Vertical bars. Reserve a strip at the bottom for category labels.
        cat_h = round(0.05 * short)
        plot_b = box.bottom - cat_h
        plot_t = box.top
        out.append(_value_grid_v(box, plot_t, plot_b, vlo, vhi, ticks, value_axis, c, short))
        slot = box.w / n_cat
        bar_pad = slot * 0.18
        group_w = slot - 2 * bar_pad
        bw = group_w / n_series
        for ci in range(n_cat):
            slot_x = box.left + ci * slot + bar_pad
            for si, s in enumerate(series):
                if ci >= len(s.points):
                    continue
                p = s.points[ci]
                bx = slot_x + si * bw
                y = _v2y(p.value, vlo, vhi, plot_t, plot_b)
                bh = plot_b - y
                fill = _bar_fill(spec, c, s, p, ci, si, n_series)
                out.append(_rect(bx + 1, y, max(1, bw - 2), max(0, bh), fill, rx=round(0.004 * short)))
                if n_series == 1:
                    dv = p.display or format_value(p.value, value_axis.value_format)
                    out.append(
                        _text(bx + bw / 2, y - round(0.012 * short), _esc(dv), label_size, c.ink,
                              family=_fonts.body_stack(), weight="700", anchor="middle")
                    )
            # category label
            out.append(
                _text(box.left + ci * slot + slot / 2, box.bottom - round(0.012 * short),
                      _esc(_clip(categories[ci], 16)), label_size, c.muted,
                      family=_fonts.body_stack(), anchor="middle")
            )
    else:
        # Horizontal bars. Reserve a strip on the left for category labels.
        cat_w = round(0.22 * box.w)
        plot_l = box.left + cat_w
        plot_r = box.right
        out.append(_value_grid_h(box, plot_l, plot_r, vlo, vhi, ticks, value_axis, c, short))
        slot = box.h / n_cat
        bar_pad = slot * 0.18
        group_h = slot - 2 * bar_pad
        bh = group_h / n_series
        for ci in range(n_cat):
            slot_y = box.top + ci * slot + bar_pad
            for si, s in enumerate(series):
                if ci >= len(s.points):
                    continue
                p = s.points[ci]
                by = slot_y + si * bh
                x2 = _v2x(p.value, vlo, vhi, plot_l, plot_r)
                bw = x2 - plot_l
                fill = _bar_fill(spec, c, s, p, ci, si, n_series)
                out.append(_rect(plot_l, by + 1, max(0, bw), max(1, bh - 2), fill, rx=round(0.004 * short)))
                if n_series == 1:
                    dv = p.display or format_value(p.value, value_axis.value_format)
                    out.append(
                        _text(x2 + round(0.01 * short), by + bh / 2 + label_size * 0.35, _esc(dv),
                              label_size, c.ink, family=_fonts.body_stack(), weight="700")
                    )
            out.append(
                _text(box.left, box.top + ci * slot + slot / 2 + label_size * 0.35,
                      _esc(_clip(categories[ci], 18)), label_size, c.muted, family=_fonts.body_stack())
            )
    out.append(_legend(series, c, box, short) if n_series > 1 else "")
    return "".join(out)


def _bar_fill(spec: ChartSpec, c: ChartColours, s: Series, p, ci: int, si: int, n_series: int) -> str:
    """The fill for one bar. Single-series bars are one clean accent colour
    (with medal-awareness and an optional ``meta['highlight_label']`` pop), not a
    rainbow ramp; grouped bars get one colour per series."""
    if n_series > 1:
        return c.series_colour(s.role, si)
    low = (p.label or "").strip().lower()
    for medal in ("gold", "silver", "bronze"):
        if medal in low:
            from .palette import MEDAL_COLOURS

            return MEDAL_COLOURS[medal]
    highlight = str(spec.meta.get("highlight_label", "")).strip().lower()
    if highlight:
        if low == highlight:
            return c.accent
        from .palette import _mix

        return _mix(c.secondary, c.ground, 0.25)  # recede the rest
    return c.accent


def _bar_domain(spec: ChartSpec, axis) -> tuple[float, float]:
    vals = [p.value for s in spec.series for p in s.points]
    if not vals:
        return (0.0, 1.0)
    dmax = max(vals)
    dmin = min(vals)
    lo = axis.min if axis.min is not None else min(0.0, dmin)
    hi = axis.max if axis.max is not None else dmax
    if hi <= lo:
        hi = lo + 1.0
    return (lo, hi)


# --------------------------------------------------------------------------- #
# line / progression
# --------------------------------------------------------------------------- #
def _render_line(spec: ChartSpec, c: ChartColours, box: _Box, short: int) -> str:
    series = [s for s in spec.series if s.points]
    if not series:
        return ""
    lower_better = spec.y_axis.lower_is_better
    # x domain from explicit x, else point index.
    all_x = [(_pt_x(p, i) for i, p in enumerate(s.points)) for s in series]
    xs = [x for gen in all_x for x in gen]
    xlo, xhi = (min(xs), max(xs)) if xs else (0.0, 1.0)
    if xhi <= xlo:
        xhi = xlo + 1.0
    vals = [p.value for s in series for p in s.points]
    vlo, vhi = (min(vals), max(vals)) if vals else (0.0, 1.0)
    span = (vhi - vlo) or 1.0
    vlo -= span * 0.12
    vhi += span * 0.12
    if spec.y_axis.min is not None:
        vlo = spec.y_axis.min
    if spec.y_axis.max is not None:
        vhi = spec.y_axis.max
    ticks = _nice_ticks(vlo, vhi)

    cat_h = round(0.05 * short)
    plot_b = box.bottom - cat_h
    plot_t = box.top
    out: list[str] = []
    out.append(_value_grid_v(box, plot_t, plot_b, vlo, vhi, ticks, spec.y_axis, c, short, invert=lower_better))
    dot = max(2.5, round(0.007 * short))
    label_size = round(0.020 * short)

    for si, s in enumerate(series):
        fill = c.series_colour(s.role, si)
        pts = []
        for i, p in enumerate(s.points):
            px = _v2x(_pt_x(p, i), xlo, xhi, box.left, box.right)
            py = _v2y(p.value, vlo, vhi, plot_t, plot_b, invert=lower_better)
            pts.append((px, py))
        if len(pts) >= 2:
            d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts)
            out.append(f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{max(2, round(0.005*short))}" stroke-linejoin="round" stroke-linecap="round"/>')
        for (px, py), p in zip(pts, s.points):
            out.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{dot:.2f}" fill="{fill}"/>')
        # End-of-line value label for single series.
        if len(series) == 1 and pts:
            ex, ey = pts[-1]
            p = s.points[-1]
            dv = p.display or format_value(p.value, spec.y_axis.value_format)
            out.append(_text(ex - round(0.01 * short), ey - round(0.014 * short), _esc(dv),
                             round(0.024 * short), c.ink, family=_fonts.body_stack(), weight="700", anchor="end"))
    # x labels (first/mid/last to avoid crowding).
    n0 = series[0].points
    idxs = sorted(set([0, len(n0) // 2, len(n0) - 1])) if n0 else []
    for i in idxs:
        if i < len(n0):
            px = _v2x(_pt_x(n0[i], i), xlo, xhi, box.left, box.right)
            out.append(_text(px, box.bottom - round(0.012 * short), _esc(_clip(n0[i].label, 14)),
                             label_size, c.muted, family=_fonts.body_stack(), anchor="middle"))
    out.append(_legend(series, c, box, short) if len(series) > 1 else "")
    return "".join(out)


def _pt_x(p, index: int) -> float:
    return p.x if p.x is not None else float(index)


# --------------------------------------------------------------------------- #
# pie / donut
# --------------------------------------------------------------------------- #
def _render_pie(spec: ChartSpec, c: ChartColours, box: _Box, short: int, *, donut: bool) -> str:
    pts = spec.series[0].points if spec.series else ()
    total = sum(max(0.0, p.value) for p in pts)
    if total <= 0:
        return _empty_state(box, c, short)
    cx = box.left + box.w * 0.36
    cy = box.top + box.h / 2
    r = min(box.w * 0.34, box.h * 0.44)
    inner = r * 0.58 if donut else 0.0
    out: list[str] = []
    angle = -math.pi / 2  # start at 12 o'clock
    for i, p in enumerate(pts):
        frac = max(0.0, p.value) / total
        a2 = angle + frac * 2 * math.pi
        fill = c.category_colour(p.label, i)
        out.append(_arc_slice(cx, cy, r, inner, angle, a2, fill))
        angle = a2
    if donut:
        out.append(_text(cx, cy - round(0.005 * short), _esc(format_value(total, spec.y_axis.value_format)),
                         round(0.06 * short), c.ink, family=_fonts.display_stack(), anchor="middle"))
        out.append(_text(cx, cy + round(0.035 * short), "TOTAL", round(0.02 * short), c.muted,
                         family=_fonts.body_stack(), anchor="middle", spacing="2px"))
    # Legend down the right side with values.
    lx = box.left + box.w * 0.72
    ly = box.top + box.h * 0.5 - (len(pts) * round(0.045 * short)) / 2
    sw = round(0.026 * short)
    for i, p in enumerate(pts):
        fill = c.category_colour(p.label, i)
        ry = ly + i * round(0.05 * short)
        out.append(_rect(lx, ry, sw, sw, fill, rx=round(0.004 * short)))
        dv = p.display or format_value(p.value, spec.y_axis.value_format)
        out.append(_text(lx + sw + round(0.014 * short), ry + sw * 0.82,
                         _esc(f"{_clip(p.label, 16)}  {dv}"), round(0.024 * short), c.ink,
                         family=_fonts.body_stack()))
    return "".join(out)


# --------------------------------------------------------------------------- #
# scatter
# --------------------------------------------------------------------------- #
def _render_scatter(spec: ChartSpec, c: ChartColours, box: _Box, short: int) -> str:
    series = [s for s in spec.series if s.points]
    if not series:
        return ""
    xs = [_pt_x(p, i) for s in series for i, p in enumerate(s.points)]
    ys = [p.value for s in series for p in s.points]
    xlo, xhi = _pad_domain(min(xs), max(xs))
    ylo, yhi = _pad_domain(min(ys), max(ys))
    yticks = _nice_ticks(ylo, yhi)
    cat_h = round(0.05 * short)
    plot_b = box.bottom - cat_h
    out: list[str] = []
    out.append(_value_grid_v(box, box.top, plot_b, ylo, yhi, yticks, spec.y_axis, c, short))
    dot = max(3.0, round(0.009 * short))
    for si, s in enumerate(series):
        fill = c.series_colour(s.role, si)
        for i, p in enumerate(s.points):
            px = _v2x(_pt_x(p, i), xlo, xhi, box.left, box.right)
            py = _v2y(p.value, ylo, yhi, box.top, plot_b)
            out.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{dot:.2f}" fill="{fill}" fill-opacity="0.85"/>')
    # x axis end labels
    out.append(_text(box.left, box.bottom - round(0.012 * short), _esc(format_value(xlo, spec.x_axis.value_format)),
                     round(0.02 * short), c.muted, family=_fonts.body_stack()))
    out.append(_text(box.right, box.bottom - round(0.012 * short), _esc(format_value(xhi, spec.x_axis.value_format)),
                     round(0.02 * short), c.muted, family=_fonts.body_stack(), anchor="end"))
    out.append(_legend(series, c, box, short) if len(series) > 1 else "")
    return "".join(out)


# --------------------------------------------------------------------------- #
# table / medal_table
# --------------------------------------------------------------------------- #
def _render_table(spec: ChartSpec, c: ChartColours, box: _Box, short: int) -> str:
    cols = list(spec.columns)
    rows = [list(r) for r in spec.rows]
    if not rows:
        return _empty_state(box, c, short)
    n_col = max(len(cols), max((len(r) for r in rows), default=0))
    if n_col == 0:
        return ""
    medal = spec.kind == "medal_table"
    out: list[str] = []
    head_h = round(0.06 * short) if cols else 0
    row_h = min(round(0.07 * short), (box.h - head_h) / max(1, len(rows)))
    col_w = box.w / n_col
    head_size = round(0.024 * short)
    cell_size = round(0.026 * short)

    y = box.top
    if cols:
        out.append(_rect(box.left, y, box.w, head_h, c.accent, rx=round(0.006 * short)))
        for ci in range(n_col):
            label = cols[ci] if ci < len(cols) else ""
            anchor, tx = _cell_anchor(ci, box.left, col_w)
            out.append(_text(tx, y + head_h * 0.66, _esc(_clip(label, 18)), head_size, c.on_accent,
                             family=_fonts.body_stack(), weight="700", anchor=anchor, spacing="0.4px"))
        y += head_h

    for ri, row in enumerate(rows):
        ry = y + ri * row_h
        if ri % 2 == 1:
            out.append(_rect(box.left, ry, box.w, row_h, _row_zebra(c), rx=0))
        for ci in range(n_col):
            val = row[ci] if ci < len(row) else ""
            anchor, tx = _cell_anchor(ci, box.left, col_w)
            ink = c.ink
            if medal and ci > 0 and ci <= 3:
                medal_key = ("gold", "silver", "bronze")[ci - 1]
                ink = _medal_ink(c, medal_key)
            fam = _fonts.mono_stack() if _looks_time(val) else _fonts.body_stack()
            out.append(_text(tx, ry + row_h * 0.64, _esc(_clip(str(val), 22)), cell_size, ink,
                             family=fam, anchor=anchor))
    # bottom rule
    out.append(_rect(box.left, y + len(rows) * row_h, box.w, max(1, round(0.004 * short)), c.grid))
    return "".join(out)


def _cell_anchor(ci: int, left: float, col_w: float) -> tuple[str, float]:
    if ci == 0:
        return ("start", left + col_w * 0.04)
    return ("end", left + (ci + 1) * col_w - col_w * 0.06)


def _row_zebra(c: ChartColours) -> str:
    from .palette import _mix

    return _mix(c.ground, c.ink, 0.06)


def _medal_ink(c: ChartColours, key: str) -> str:
    """The medal tint, shown exactly when it reads on the ground; nudged toward
    the legible ink only if it would otherwise be hard to read (rare on a dark
    brand surface, possible on a light one)."""
    from .palette import MEDAL_COLOURS, _mix

    tint = MEDAL_COLOURS.get(key, c.ink)
    try:
        from mediahub.quality.compliance import is_legible

        if is_legible(tint, c.ground):
            return tint
    except Exception:
        return tint
    # Blend toward the legible body ink until it clears the gate.
    return _mix(tint, c.ink, 0.45)


def _looks_time(val: str) -> bool:
    s = str(val).strip()
    return bool(s) and (":" in s or s.replace(".", "", 1).isdigit()) and any(ch.isdigit() for ch in s)


# --------------------------------------------------------------------------- #
# split_ladder — per-50 split bars for one swim/relay
# --------------------------------------------------------------------------- #
def _render_split_ladder(spec: ChartSpec, c: ChartColours, box: _Box, short: int) -> str:
    pts = spec.series[0].points if spec.series else ()
    if not pts:
        return _empty_state(box, c, short)
    vals = [p.value for p in pts]
    vhi = max(vals) * 1.05
    row_h = box.h / len(pts)
    label_w = round(0.18 * box.w)
    plot_l = box.left + label_w
    plot_r = box.right - round(0.16 * box.w)
    out: list[str] = []
    label_size = round(0.024 * short)
    for i, p in enumerate(pts):
        ry = box.top + i * row_h
        bar_w = (p.value / vhi) * (plot_r - plot_l) if vhi else 0
        fill = c.ramp(0) if i % 2 == 0 else c.ramp(1)
        out.append(_text(box.left, ry + row_h * 0.6, _esc(_clip(p.label, 12)), label_size, c.muted,
                         family=_fonts.body_stack()))
        out.append(_rect(plot_l, ry + row_h * 0.2, max(1, bar_w), row_h * 0.6, fill, rx=round(0.004 * short)))
        dv = p.display or format_value(p.value, spec.y_axis.value_format)
        out.append(_text(plot_r + round(0.012 * short), ry + row_h * 0.6, _esc(dv), label_size, c.ink,
                         family=_fonts.mono_stack(), weight="700"))
    return "".join(out)


# --------------------------------------------------------------------------- #
# shared: value grids, legends, scales, ticks
# --------------------------------------------------------------------------- #
def _value_grid_v(box: _Box, top: float, bottom: float, vlo: float, vhi: float, ticks, axis,
                  c: ChartColours, short: int, *, invert: bool = False) -> str:
    out: list[str] = []
    size = round(0.020 * short)
    for t in ticks:
        if t < vlo - 1e-9 or t > vhi + 1e-9:
            continue
        ty = _v2y(t, vlo, vhi, top, bottom, invert=invert)
        out.append(f'<line x1="{box.left:.2f}" y1="{ty:.2f}" x2="{box.right:.2f}" y2="{ty:.2f}" stroke="{c.grid}" stroke-width="1"/>')
        out.append(_text(box.left, ty - round(0.006 * short), _esc(format_value(t, axis.value_format)),
                         size, c.muted, family=_fonts.body_stack()))
    return "".join(out)


def _value_grid_h(box: _Box, left: float, right: float, vlo: float, vhi: float, ticks, axis,
                  c: ChartColours, short: int) -> str:
    out: list[str] = []
    size = round(0.020 * short)
    for t in ticks:
        if t < vlo - 1e-9 or t > vhi + 1e-9:
            continue
        tx = _v2x(t, vlo, vhi, left, right)
        out.append(f'<line x1="{tx:.2f}" y1="{box.top:.2f}" x2="{tx:.2f}" y2="{box.bottom:.2f}" stroke="{c.grid}" stroke-width="1"/>')
        out.append(_text(tx, box.bottom + round(0.022 * short), _esc(format_value(t, axis.value_format)),
                         size, c.muted, family=_fonts.body_stack(), anchor="middle"))
    return "".join(out)


def _legend(series: list[Series], c: ChartColours, box: _Box, short: int) -> str:
    out: list[str] = []
    sw = round(0.022 * short)
    size = round(0.022 * short)
    x = box.left
    y = box.top - round(0.012 * short)
    for si, s in enumerate(series):
        fill = c.series_colour(s.role, si)
        out.append(_rect(x, y - sw, sw, sw, fill, rx=round(0.004 * short)))
        label = _esc(_clip(s.name or f"Series {si + 1}", 18))
        out.append(_text(x + sw + round(0.008 * short), y - sw * 0.12, label, size, c.muted,
                         family=_fonts.body_stack()))
        x += round(0.20 * box.w)
    return "".join(out)


def _v2y(v: float, lo: float, hi: float, top: float, bottom: float, *, invert: bool = False) -> float:
    span = (hi - lo) or 1.0
    frac = (v - lo) / span
    if invert:
        return top + frac * (bottom - top)
    return bottom - frac * (bottom - top)


def _v2x(v: float, lo: float, hi: float, left: float, right: float) -> float:
    span = (hi - lo) or 1.0
    frac = (v - lo) / span
    return left + frac * (right - left)


def _pad_domain(lo: float, hi: float) -> tuple[float, float]:
    if hi <= lo:
        return (lo - 1.0, hi + 1.0)
    span = hi - lo
    return (lo - span * 0.08, hi + span * 0.08)


def _nice_ticks(vlo: float, vhi: float, target: int = 5) -> list[float]:
    """Deterministic 'nice' tick values spanning [vlo, vhi]."""
    if vhi <= vlo:
        return [vlo]
    span = vhi - vlo
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    norm = raw / mag
    if norm < 1.5:
        step = 1 * mag
    elif norm < 3:
        step = 2 * mag
    elif norm < 7:
        step = 5 * mag
    else:
        step = 10 * mag
    start = math.floor(vlo / step) * step
    ticks: list[float] = []
    t = start
    # guard against runaway loops
    for _ in range(200):
        if t > vhi + step * 0.5:
            break
        if t >= vlo - 1e-9:
            ticks.append(round(t, 6))
        t += step
    return ticks or [vlo, vhi]


# --------------------------------------------------------------------------- #
# SVG primitives (deterministic strings; all text XML/XSS-escaped)
# --------------------------------------------------------------------------- #
def _svg_open(w: int, h: int, embed_fonts: bool) -> str:
    style = _fonts.font_face_css(embed_fonts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img">'
        f"<style>{style}</style>"
    )


def _rect(x, y, w, h, fill: str, *, rx: int = 0) -> str:
    rxs = f' rx="{rx}"' if rx else ""
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}"{rxs}/>'


def _text(x, y, text: str, size: int, fill: str, *, family: str, weight: str = "400",
          anchor: str = "start", spacing: str = "0") -> str:
    ls = f' letter-spacing="{spacing}"' if spacing and spacing != "0" else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}>{text}</text>'
    )


def _arc_slice(cx: float, cy: float, r: float, inner: float, a1: float, a2: float, fill: str) -> str:
    """A pie/donut slice from angle a1→a2 (radians)."""
    large = 1 if (a2 - a1) > math.pi else 0
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
    if inner <= 0:
        d = (
            f"M{cx:.2f},{cy:.2f} L{x1:.2f},{y1:.2f} "
            f"A{r:.2f},{r:.2f} 0 {large} 1 {x2:.2f},{y2:.2f} Z"
        )
    else:
        xi1, yi1 = cx + inner * math.cos(a2), cy + inner * math.sin(a2)
        xi2, yi2 = cx + inner * math.cos(a1), cy + inner * math.sin(a1)
        d = (
            f"M{x1:.2f},{y1:.2f} A{r:.2f},{r:.2f} 0 {large} 1 {x2:.2f},{y2:.2f} "
            f"L{xi1:.2f},{yi1:.2f} A{inner:.2f},{inner:.2f} 0 {large} 0 {xi2:.2f},{yi2:.2f} Z"
        )
    return f'<path d="{d}" fill="{fill}"/>'


def _esc(text: str) -> str:
    """XML/XSS-safe text for an SVG <text> body or attribute."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _clip(text: str, n: int) -> str:
    s = str(text)
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"


__all__ = ["render_chart_svg"]
