"""charts — deterministic, brand-styled stat graphics from MediaHub's own data (roadmap 1.11).

This is home turf: MediaHub already owns clean, parsed, trustworthy results — the
one thing a blank-canvas tool never has. The ``charts`` package turns the canonical
store + history into **stat graphics**: PBs-per-swimmer bars, season-progression
lines, medal tables, club-record boards, relay split ladders. Every chart is a
brand-themed SVG drawn **deterministically** — the numbers are sacred, no LLM ever
draws an axis.

The intelligence sits either side of the deterministic core, never inside it:
  - :mod:`charts.recommend` — the AI picks *which* chart tells the story (build 3).
  - :mod:`charts.insights` — the AI phrases takeaways grounded in pre-computed
    aggregates, each carrying its source rows (build 3).
Both honest-error when no AI provider is configured (CLAUDE.md rule 5).

Public surface (build 1):
  - ``models``  — ChartSpec / Series / DataPoint / Axis data model (+ value formatting)
  - ``render``  — ChartSpec → brand-styled SVG (``render_chart_svg``)
  - ``palette`` — brand role vars → a chart's colours (``ChartColours``)
  - ``fonts``   — self-hosted typefaces inlined into standalone chart SVG
"""

from .models import (
    CHART_KINDS,
    Axis,
    ChartSpec,
    DataPoint,
    Series,
    format_time_cs,
    format_value,
)
from .render import render_chart_svg

__all__ = [
    "CHART_KINDS",
    "Axis",
    "ChartSpec",
    "DataPoint",
    "Series",
    "format_value",
    "format_time_cs",
    "render_chart_svg",
]
