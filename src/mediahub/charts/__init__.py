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

Public surface:
  - ``models``     — ChartSpec / Series / DataPoint / Axis data model (+ value formatting)
  - ``render``     — ChartSpec → brand-styled SVG (``render_chart_svg``)
  - ``palette``    — brand role vars → a chart's colours (``ChartColours``)
  - ``fonts``      — self-hosted typefaces inlined into standalone chart SVG
  - ``aggregates`` — the deterministic fact base over a processed run (build 2)
  - ``series``     — build ChartSpecs from real run data (build 2)
  - ``csv_input``  — turn an uploaded table into a ChartSpec, flagging bad rows (build 2)
  - ``recommend``  — AI picks which chart leads the story, honest-erroring (build 3)
  - ``insights``   — AI takeaways grounded in the facts, source-linked (build 3)
  - ``diagrams``   — data-driven org charts / timelines / journeys / flows (build 4)
"""

from .aggregates import MeetAggregates, compute_aggregates
from .csv_input import CsvImport, parse_csv_to_spec
from .diagrams import (
    DiagramSpec,
    athlete_journey,
    org_chart_from_roster,
    render_diagram_svg,
    season_timeline_from_meets,
    training_flow,
)
from .insights import generate_insights
from .models import (
    CHART_KINDS,
    Axis,
    ChartSpec,
    DataPoint,
    Series,
    format_time_cs,
    format_value,
)
from .recommend import recommend_chart
from .render import render_chart_svg
from .series import ChartCandidate, build_chart_candidates

__all__ = [
    "CHART_KINDS",
    "Axis",
    "ChartSpec",
    "DataPoint",
    "Series",
    "format_value",
    "format_time_cs",
    "render_chart_svg",
    "MeetAggregates",
    "compute_aggregates",
    "ChartCandidate",
    "build_chart_candidates",
    "CsvImport",
    "parse_csv_to_spec",
    "recommend_chart",
    "generate_insights",
    "DiagramSpec",
    "render_diagram_svg",
    "org_chart_from_roster",
    "season_timeline_from_meets",
    "athlete_journey",
    "training_flow",
]
