"""UI 1.17 — Content-cadence heatmap (Activity page).

A GitHub-contribution-graph-style calendar grid that shows how consistently an
organisation has been *making content* over the past year. Each square is one
day; its intensity reflects that day's content activity — pipeline runs
generated. It renders as a single inline SVG, server-side, from the org's own
run history (the ``runs`` table); no JS library, no client charting dependency.

Design rules honoured (see CLAUDE.md):
  * Dark-first, on the existing CSS variables. The heat ramp is lane-yellow
    (``--lane``) — MediaHub's "live / activity" signature — stepped by opacity
    over a faint empty cell. Medal-gold is deliberately NOT used: it is reserved
    for athlete achievements and must never be chrome.
  * Pure inline SVG geometry — no SMIL, no JS, no external deps. A native
    ``<title>`` child on every day gives an accessible, no-JS hover tooltip; the
    panel carries a visually-hidden text summary for screen readers.
  * No animation, so there is nothing to freeze under ``prefers-reduced-motion``.
  * Multi-tenant safe: this module is pure presentation over counts the caller
    has already scoped to one profile. It performs no DB access and embeds no
    identifiers or free text, so there is no XSS / IDOR surface here — every
    value written into the SVG is an integer or a constant month/day name.

The transformation helpers (``level_for``, ``window_start``, ``build_grid``,
``render_svg``, ``cadence_panel_html``) take no I/O and are unit-tested in
``tests/test_cadence_heatmap.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Optional, Union

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #

# Minimum day-count to reach heat level 1..4. Tuned for club cadence (a busy
# club generates a handful of pieces a day, not hundreds): a single piece
# already lights the cell; seven or more saturates it.
DEFAULT_LEVEL_THRESHOLDS: tuple[int, int, int, int] = (1, 2, 4, 7)

# Monday-start weeks (UK product). ``date.weekday()``: Mon=0 … Sun=6.
DEFAULT_WEEK_START = 0

# 53 columns covers a full year plus the current partial week (GitHub-style).
DEFAULT_WEEKS = 53

# Abbreviations indexed by ``date.weekday()`` (Monday-first) and by month number.
_DOW_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH_ABBR = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Weekday rows that get a left-margin label (Mon / Wed / Fri — the GitHub set).
_LABELLED_WEEKDAYS = (0, 2, 4)


# --------------------------------------------------------------------------- #
# Pure data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DayCell:
    """One day square in the grid."""

    day: date
    count: int
    level: int
    future: bool


@dataclass(frozen=True)
class CadenceGrid:
    """The shaped calendar: ``weeks`` columns of seven :class:`DayCell` rows,
    plus the summary statistics the panel surfaces."""

    weeks: list[list[DayCell]]
    start: date
    end: date
    week_start: int
    month_labels: list[tuple[int, str]]
    total: int
    active_days: int
    longest_streak: int
    current_streak: int
    busiest_day: Optional[date]
    busiest_count: int
    max_count: int


# --------------------------------------------------------------------------- #
# Pure transforms
# --------------------------------------------------------------------------- #


def level_for(
    count: int,
    thresholds: tuple[int, int, int, int] = DEFAULT_LEVEL_THRESHOLDS,
) -> int:
    """Map a day's activity ``count`` to a heat level 0..4."""
    if count <= 0:
        return 0
    level = 0
    for i, threshold in enumerate(thresholds, start=1):
        if count >= threshold:
            level = i
    return level


def window_start(
    end: date,
    *,
    weeks: int = DEFAULT_WEEKS,
    week_start: int = DEFAULT_WEEK_START,
) -> date:
    """The first calendar day the grid renders: the ``week_start`` day of the
    week containing ``end``, then ``weeks - 1`` whole weeks earlier."""
    offset = (end.weekday() - week_start) % 7
    end_week_start = end - timedelta(days=offset)
    return end_week_start - timedelta(days=(weeks - 1) * 7)


def _normalise_counts(counts: Optional[Mapping[Union[str, date], int]]) -> dict[str, int]:
    """Coerce a ``{date|iso-string: count}`` mapping to ``{iso-string: int}``,
    skipping anything that doesn't parse to a non-negative integer."""
    out: dict[str, int] = {}
    if not counts:
        return out
    for key, value in counts.items():
        iso = key.isoformat() if isinstance(key, date) else str(key)[:10]
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[iso] = out.get(iso, 0) + n
    return out


def build_grid(
    generated: Optional[Mapping[Union[str, date], int]],
    *,
    end: date,
    weeks: int = DEFAULT_WEEKS,
    week_start: int = DEFAULT_WEEK_START,
    thresholds: tuple[int, int, int, int] = DEFAULT_LEVEL_THRESHOLDS,
) -> CadenceGrid:
    """Shape per-day ``generated`` counts into a calendar grid.

    Days after ``end`` (the trailing part of the current week) are marked
    ``future`` and carry no counts. Statistics are computed over the in-range
    days only, in chronological order.
    """
    gen = _normalise_counts(generated)
    start = window_start(end, weeks=weeks, week_start=week_start)

    columns: list[list[DayCell]] = []
    in_range: list[DayCell] = []
    for w in range(weeks):
        column: list[DayCell] = []
        for d in range(7):
            day = start + timedelta(days=w * 7 + d)
            future = day > end
            iso = day.isoformat()
            c = 0 if future else gen.get(iso, 0)
            cell = DayCell(
                day=day,
                count=c,
                level=0 if future else level_for(c, thresholds),
                future=future,
            )
            column.append(cell)
            if not future:
                in_range.append(cell)
        columns.append(column)

    # Month labels — placed at the first column whose week starts a new month.
    month_labels: list[tuple[int, str]] = []
    last_month: Optional[int] = None
    last_label_col = -99
    for w, column in enumerate(columns):
        month = column[0].day.month
        if month != last_month:
            if w - last_label_col >= 2:
                month_labels.append((w, _MONTH_ABBR[month]))
                last_label_col = w
            last_month = month

    # Summary stats + streaks over the chronological in-range days.
    total = sum(cell.count for cell in in_range)
    active_days = sum(1 for cell in in_range if cell.count > 0)
    max_count = max((cell.count for cell in in_range), default=0)

    longest_streak = 0
    run = 0
    for cell in in_range:
        if cell.count > 0:
            run += 1
            longest_streak = max(longest_streak, run)
        else:
            run = 0

    current_streak = 0
    for cell in reversed(in_range):
        if cell.count > 0:
            current_streak += 1
        else:
            break

    busiest_day: Optional[date] = None
    busiest_count = 0
    for cell in in_range:
        if cell.count > busiest_count:
            busiest_count = cell.count
            busiest_day = cell.day

    return CadenceGrid(
        weeks=columns,
        start=start,
        end=end,
        week_start=week_start,
        month_labels=month_labels,
        total=total,
        active_days=active_days,
        longest_streak=longest_streak,
        current_streak=current_streak,
        busiest_day=busiest_day,
        busiest_count=busiest_count,
        max_count=max_count,
    )


# --------------------------------------------------------------------------- #
# SVG rendering (pure strings; all values int / known-constant — no escaping
# needed, no user text reaches the markup)
# --------------------------------------------------------------------------- #


def _format_day(day: date) -> str:
    return f"{_DOW_ABBR[day.weekday()]} {day.day} {_MONTH_ABBR[day.month]} {day.year}"


def _cell_title(cell: DayCell) -> str:
    head = _format_day(cell.day)
    if cell.count == 0:
        return f"{head} — no activity"
    return f"{head} — {cell.count} generated"


def aria_summary(grid: CadenceGrid) -> str:
    """A plain-text description of the grid for screen readers."""
    return (
        f"Content-cadence heatmap. {grid.total} "
        f"{'piece' if grid.total == 1 else 'pieces'} generated across "
        f"{grid.active_days} active "
        f"{'day' if grid.active_days == 1 else 'days'} in the year ending "
        f"{_format_day(grid.end)}. Longest streak "
        f"{grid.longest_streak} {'day' if grid.longest_streak == 1 else 'days'}."
    )


def render_svg(
    grid: CadenceGrid,
    *,
    cell: int = 11,
    gap: int = 3,
    pad_left: int = 30,
    pad_top: int = 18,
    pad_right: int = 6,
    pad_bottom: int = 6,
) -> str:
    """Render the grid as a self-contained inline ``<svg>`` string."""
    step = cell + gap
    n_weeks = len(grid.weeks)
    width = pad_left + n_weeks * cell + max(n_weeks - 1, 0) * gap + pad_right
    height = pad_top + 7 * cell + 6 * gap + pad_bottom

    parts: list[str] = [
        f'<svg class="mh-cad-svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{aria_summary(grid)}" '
        'xmlns="http://www.w3.org/2000/svg">'
    ]

    # Month labels along the top.
    for col_idx, label in grid.month_labels:
        x = pad_left + col_idx * step
        parts.append(f'<text class="mh-cad-mon" x="{x}" y="{pad_top - 6}">{label}</text>')

    # Weekday labels down the left (Mon / Wed / Fri).
    for d in range(7):
        weekday = (grid.week_start + d) % 7
        if weekday in _LABELLED_WEEKDAYS:
            y = pad_top + d * step + cell - 1
            parts.append(
                f'<text class="mh-cad-dow" x="{pad_left - 6}" y="{y}" '
                f'text-anchor="end">{_DOW_ABBR[weekday]}</text>'
            )

    # Day squares — future days in the current week are simply not drawn.
    for w, column in enumerate(grid.weeks):
        x = pad_left + w * step
        for d, c in enumerate(column):
            if c.future:
                continue
            y = pad_top + d * step
            parts.append(
                f'<rect class="mh-cad-cell mh-cad-l{c.level}" x="{x}" y="{y}" '
                f'width="{cell}" height="{cell}" rx="2" ry="2">'
                f"<title>{_cell_title(c)}</title></rect>"
            )

    parts.append("</svg>")
    return "".join(parts)


def _legend_svg(cell: int = 11, gap: int = 5) -> str:
    """A tiny five-step ramp reusing the same cell classes for visual parity."""
    step = cell + gap
    width = 5 * cell + 4 * gap
    parts = [
        f'<svg class="mh-cad-legend-svg" width="{width}" height="{cell}" '
        f'viewBox="0 0 {width} {cell}" aria-hidden="true" '
        'xmlns="http://www.w3.org/2000/svg">'
    ]
    for i in range(5):
        x = i * step
        parts.append(
            f'<rect class="mh-cad-cell mh-cad-l{i}" x="{x}" y="0" '
            f'width="{cell}" height="{cell}" rx="2" ry="2"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Panel composition
# --------------------------------------------------------------------------- #


def cadence_panel_html(
    generated: Optional[Mapping[Union[str, date], int]],
    posted: Optional[Mapping[Union[str, date], int]] = None,
    *,
    end: date,
    weeks: int = DEFAULT_WEEKS,
    week_start: int = DEFAULT_WEEK_START,
    thresholds: tuple[int, int, int, int] = DEFAULT_LEVEL_THRESHOLDS,
) -> str:
    """The full Activity-page panel markup for the content-cadence heatmap.

    ``posted`` is a transitional argument: MediaHub does not post to social
    channels, so the grid has a single "generated" lane. Any counts passed
    here are merged into that lane. It exists only because the web.py caller
    still passes its (always-empty) second dict positionally — drop it once
    that caller passes a single mapping.
    """
    counts = _normalise_counts(generated)
    for iso, n in _normalise_counts(posted).items():
        counts[iso] = counts.get(iso, 0) + n
    grid = build_grid(
        counts,
        end=end,
        weeks=weeks,
        week_start=week_start,
        thresholds=thresholds,
    )
    svg = render_svg(grid)

    total = grid.total
    metrics = [
        (f"{total:,}", "piece" if total == 1 else "pieces"),
        (
            f"{grid.active_days:,}",
            "active day" if grid.active_days == 1 else "active days",
        ),
        (f"{grid.longest_streak:,}", "day streak"),
    ]
    metrics_html = "".join(
        f'<span class="mh-cad-metric"><b>{value}</b> {label}</span>' for value, label in metrics
    )

    if total == 0:
        foot_note = (
            "Each square is a day. As you generate content, this grid "
            "fills in — brighter days are busier ones."
        )
    else:
        foot_note = (
            "Each square is a day over the last year. Brighter means more pieces "
            "generated that day."
        )

    return (
        '<section class="card mh-cad-panel mh-reveal" '
        'aria-label="Content cadence over the last year">'
        '<div class="mh-cad-head">'
        '<div class="mh-cad-head-text">'
        '<span class="label mh-cad-eyebrow">Content cadence</span>'
        '<h2 class="mh-cad-title">The last year at a glance</h2>'
        "</div>"
        f'<div class="mh-cad-metrics">{metrics_html}</div>'
        "</div>"
        f'<p class="mh-visually-hidden">{aria_summary(grid)}</p>'
        f'<div class="mh-cad-scroll">{svg}</div>'
        '<div class="mh-cad-foot">'
        f'<p class="mh-cad-foot-note">{foot_note}</p>'
        '<div class="mh-cad-legend" aria-hidden="true">'
        f"<span>Less</span>{_legend_svg()}<span>More</span>"
        "</div>"
        "</div>"
        "</section>"
    )


# --------------------------------------------------------------------------- #
# CSS — appended to BASE_CSS ahead of the responsive-guardrails layer.
# --------------------------------------------------------------------------- #
CADENCE_HEATMAP_CSS = """
/* ===================================================================== */
/* UI 1.17 — Content-cadence heatmap (Activity page)                     */
/* GitHub-contribution-graph-style year grid, server-rendered inline SVG */
/* from run history. Heat ramp is lane-yellow stepped by opacity over a  */
/* faint empty cell; medal-gold is never used (reserved                  */
/* for athlete achievements). No animation — nothing to freeze under     */
/* prefers-reduced-motion.                                               */
/* ===================================================================== */
.mh-cad-panel {
  padding: var(--sp-5) var(--sp-5) var(--sp-4);
  margin-bottom: var(--sp-5);
}
.mh-cad-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin-bottom: var(--sp-4);
}
.mh-cad-eyebrow { display: block; margin-bottom: 4px; }
.mh-cad-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.01em;
}
.mh-cad-metrics {
  display: flex;
  gap: var(--sp-5);
  flex-wrap: wrap;
  align-items: baseline;
}
.mh-cad-metric {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
}
.mh-cad-metric b {
  display: inline-block;
  margin-right: 4px;
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 18px;
  color: var(--ink);
}
.mh-cad-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 4px;
}
.mh-cad-svg { display: block; height: auto; }
.mh-cad-cell { stroke: rgba(245, 242, 232, 0.04); stroke-width: 1; }
.mh-cad-l0 { fill: rgba(245, 242, 232, 0.06); }
.mh-cad-l1 { fill: var(--lane); fill-opacity: 0.22; }
.mh-cad-l2 { fill: var(--lane); fill-opacity: 0.44; }
.mh-cad-l3 { fill: var(--lane); fill-opacity: 0.70; }
.mh-cad-l4 { fill: var(--lane); fill-opacity: 1; }
.mh-cad-dow, .mh-cad-mon {
  fill: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.04em;
}
.mh-cad-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}
.mh-cad-foot-note {
  margin: 0;
  max-width: 60ch;
  color: var(--ink-faint);
  font-size: 12px;
  line-height: 1.5;
}
.mh-cad-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.mh-cad-legend-svg { display: inline-block; vertical-align: middle; }
"""
