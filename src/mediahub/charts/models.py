"""charts.models — the typed data model for a deterministic stat graphic (roadmap 1.11).

A :class:`ChartSpec` is a fully-resolved, **render-ready** description of one chart:
its kind (bar, line, pie, table, medal table, progression …), its data series, its
axes, and its provenance footer. It carries *numbers and labels only* — never an
instruction to "draw something nice". The renderer (:mod:`charts.render`) turns a
spec into brand-styled SVG deterministically; the data plumbing (:mod:`charts.series`)
builds specs from canonical results / history / CSV.

The contract that makes charts trustworthy (CLAUDE.md rule 5 — *facts are code*):

  - **The numbers are sacred.** Every :class:`DataPoint` carries the exact value to
    plot plus an optional pre-formatted ``display`` string and a ``source_ref`` back
    to the canonical row it came from (the explainability rule). No LLM ever supplies
    a value here.
  - **Deterministic.** Same spec + same brand role vars → byte-identical SVG. The
    model is plain data with ``to_dict`` / ``from_dict`` so a spec round-trips through
    JSON (persisted in run data, posted to the web layer) without loss.

The model is intentionally small and additive: unknown keys are dropped and missing
optionals default, so older/newer persisted shapes load cleanly (mirrors
``CreativeBrief.from_dict`` / ``elements.models``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# The chart kinds the engine renders. A tuple (not an enum) so persisted specs stay
# plain-text/JSON and new kinds are additive.
CHART_KINDS: tuple[str, ...] = (
    "bar",  # vertical bars — counts/totals by category (PBs per swimmer)
    "hbar",  # horizontal bars — ranked magnitudes (biggest drops of the meet)
    "line",  # line over a numeric/time x — trends (entries per season)
    "progression",  # season-best line where LOWER is better (a swimmer's times)
    "pie",  # part-to-whole (medal split)
    "donut",  # part-to-whole with a centre total
    "scatter",  # two numeric axes (age vs improvement)
    "table",  # brand-styled data table (results / heat sheet)
    "medal_table",  # gold/silver/bronze tally table (per swimmer / club)
    "split_ladder",  # per-50 split bars for one swim / relay
)

# How a numeric value is formatted for display when a point carries no explicit
# ``display`` string. Additive; unknown formats fall back to a plain number.
VALUE_FORMATS: tuple[str, ...] = (
    "number",  # 12, 1.2  (trimmed)
    "integer",  # 12
    "percent",  # 66.7%
    "seconds",  # 1.20s  (a time delta)
    "time_cs",  # 1:02.34  (a clock time held in centiseconds)
)

# Brand role a series paints in. Maps onto the renderer's resolved ``--mh-*`` roles
# (see :mod:`charts.palette`). "auto" lets the palette assign a deterministic ramp
# colour by the series' position.
SERIES_ROLES: tuple[str, ...] = (
    "auto",
    "accent",
    "secondary",
    "primary",
    "on_surface",
    "gold",
    "silver",
    "bronze",
)


@dataclass(frozen=True)
class DataPoint:
    """One datum to plot. The value is the truth; everything else is presentation."""

    label: str  # category / x-axis label, e.g. "Smith, J" or "100m Free"
    value: float  # the numeric value plotted on the value axis
    x: Optional[float] = None  # explicit numeric/time x for line/scatter (else index)
    display: str = ""  # pre-formatted value text ("1:02.34"); else derived from format
    source_ref: str = ""  # provenance back to the canonical row (explainability)
    note: str = ""  # optional short annotation rendered near the point
    emphasis: bool = False  # the standout datum — painted in accent, the rest recede

    def to_dict(self) -> dict:
        d: dict = {"label": self.label, "value": self.value}
        if self.x is not None:
            d["x"] = self.x
        if self.display:
            d["display"] = self.display
        if self.source_ref:
            d["source_ref"] = self.source_ref
        if self.note:
            d["note"] = self.note
        if self.emphasis:
            d["emphasis"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Optional["DataPoint"]:
        if not isinstance(data, dict):
            return None
        if "value" not in data:
            return None
        return cls(
            label=str(data.get("label", "")).strip(),
            value=_safe_float(data.get("value"), 0.0),
            x=(None if data.get("x") is None else _safe_float(data.get("x"), 0.0)),
            display=str(data.get("display", "")).strip(),
            source_ref=str(data.get("source_ref", "")).strip(),
            note=str(data.get("note", "")).strip(),
            emphasis=bool(data.get("emphasis", False)),
        )


@dataclass(frozen=True)
class ReferenceLine:
    """A horizontal marker on the value axis at a real, known value — a club record,
    a qualifying time, a season-best line. It is the chart's intelligence: it shows
    *where the story sits* relative to a benchmark. The value is always a real number
    from the deterministic data (club_records, standards) — never an invented line."""

    value: float  # where the line sits on the value axis
    label: str = ""  # the marker label, e.g. "Club record" / "County QT"
    display: str = ""  # pre-formatted value ("1:01.20"); else derived from the axis
    role: str = "secondary"  # colour role: "secondary" | "accent" | "on_surface"
    source_ref: str = ""  # provenance for the benchmark (explainability)

    def to_dict(self) -> dict:
        d: dict = {"value": self.value, "label": self.label, "role": self.role}
        if self.display:
            d["display"] = self.display
        if self.source_ref:
            d["source_ref"] = self.source_ref
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Optional["ReferenceLine"]:
        if not isinstance(data, dict) or "value" not in data:
            return None
        role = str(data.get("role", "secondary")).strip().lower()
        return cls(
            value=_safe_float(data.get("value"), 0.0),
            label=str(data.get("label", "")).strip(),
            display=str(data.get("display", "")).strip(),
            role=role if role in ("secondary", "accent", "on_surface") else "secondary",
            source_ref=str(data.get("source_ref", "")).strip(),
        )


@dataclass(frozen=True)
class Series:
    """A named run of points sharing a colour role."""

    name: str = ""
    points: tuple[DataPoint, ...] = ()
    role: str = "auto"  # one of SERIES_ROLES

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["Series"]:
        if not isinstance(data, dict):
            return None
        pts = tuple(
            p for p in (DataPoint.from_dict(x) for x in data.get("points", [])) if p is not None
        )
        role = str(data.get("role", "auto")).strip().lower()
        return cls(
            name=str(data.get("name", "")).strip(),
            points=pts,
            role=role if role in SERIES_ROLES else "auto",
        )


@dataclass(frozen=True)
class Axis:
    """One axis. ``lower_is_better`` inverts the value scale for time charts."""

    title: str = ""
    kind: str = "linear"  # "linear" | "category" | "time"
    value_format: str = "number"  # one of VALUE_FORMATS
    lower_is_better: bool = False  # progression: a faster (smaller) time sits higher
    min: Optional[float] = None  # explicit domain floor (else derived from data)
    max: Optional[float] = None  # explicit domain ceiling (else derived from data)

    def to_dict(self) -> dict:
        d: dict = {
            "title": self.title,
            "kind": self.kind,
            "value_format": self.value_format,
            "lower_is_better": self.lower_is_better,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        return d

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Axis":
        if not isinstance(data, dict):
            return cls()
        vf = str(data.get("value_format", "number")).strip().lower()
        kind = str(data.get("kind", "linear")).strip().lower()
        return cls(
            title=str(data.get("title", "")).strip(),
            kind=kind if kind in ("linear", "category", "time") else "linear",
            value_format=vf if vf in VALUE_FORMATS else "number",
            lower_is_better=bool(data.get("lower_is_better", False)),
            min=(None if data.get("min") is None else _safe_float(data.get("min"), 0.0)),
            max=(None if data.get("max") is None else _safe_float(data.get("max"), 0.0)),
        )


@dataclass(frozen=True)
class ChartSpec:
    """A fully-resolved, render-ready chart. Plain data; round-trips through JSON."""

    kind: str  # one of CHART_KINDS
    title: str = ""
    subtitle: str = ""
    series: tuple[Series, ...] = ()
    x_axis: Axis = field(default_factory=Axis)
    y_axis: Axis = field(default_factory=Axis)
    width: int = 1080
    height: int = 1080
    source_note: str = ""  # provenance footer ("Source: meet results file")
    footnote: str = ""  # optional caveat / sample-size note
    # Table kinds carry their own grid rather than series:
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    # Benchmark markers (club record, qualifying time) drawn across the value axis.
    reference_lines: tuple[ReferenceLine, ...] = ()
    # Stable id + free-form hints (e.g. {"highlight_label": "Smith, J"}).
    chart_id: str = ""
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def all_points(self) -> list[DataPoint]:
        """Every point across every series (for domain calc / aggregates)."""
        out: list[DataPoint] = []
        for s in self.series:
            out.extend(s.points)
        return out

    def is_empty(self) -> bool:
        """A spec with nothing to draw (so callers can show an honest empty state)."""
        if self.kind in ("table", "medal_table"):
            return not self.rows
        return not any(s.points for s in self.series)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "series": [s.to_dict() for s in self.series],
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
            "width": self.width,
            "height": self.height,
            "source_note": self.source_note,
            "footnote": self.footnote,
            "columns": list(self.columns),
            "rows": [list(r) for r in self.rows],
            "reference_lines": [r.to_dict() for r in self.reference_lines],
            "chart_id": self.chart_id,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["ChartSpec"]:
        """Build a ChartSpec from a persisted/posted dict. ``None`` if unusable."""
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind", "")).strip().lower()
        if kind not in CHART_KINDS:
            return None
        series = tuple(
            s for s in (Series.from_dict(x) for x in data.get("series", [])) if s is not None
        )
        rows_raw = data.get("rows", []) or []
        rows = tuple(
            tuple(str(c) for c in row) for row in rows_raw if isinstance(row, (list, tuple))
        )
        meta = data.get("meta", {})
        ref_lines = tuple(
            r
            for r in (ReferenceLine.from_dict(x) for x in (data.get("reference_lines", []) or []))
            if r is not None
        )
        return cls(
            kind=kind,
            title=str(data.get("title", "")).strip(),
            subtitle=str(data.get("subtitle", "")).strip(),
            series=series,
            x_axis=Axis.from_dict(data.get("x_axis")),
            y_axis=Axis.from_dict(data.get("y_axis")),
            width=_safe_int(data.get("width"), 1080, lo=200, hi=10000),
            height=_safe_int(data.get("height"), 1080, lo=200, hi=10000),
            source_note=str(data.get("source_note", "")).strip(),
            footnote=str(data.get("footnote", "")).strip(),
            columns=tuple(str(c) for c in (data.get("columns", []) or [])),
            rows=rows,
            reference_lines=ref_lines,
            chart_id=str(data.get("chart_id", "")).strip(),
            meta=dict(meta) if isinstance(meta, dict) else {},
        )


# --------------------------------------------------------------------------- #
# value formatting (deterministic, no deps) — the single place a number becomes
# its display string when a point carries no explicit ``display``.
# --------------------------------------------------------------------------- #
def format_value(value: float, value_format: str) -> str:
    """Format a numeric value per a VALUE_FORMATS code. Deterministic."""
    fmt = value_format if value_format in VALUE_FORMATS else "number"
    if fmt == "integer":
        return f"{int(round(value))}"
    if fmt == "percent":
        return f"{_trim(round(value, 1))}%"
    if fmt == "seconds":
        return f"{value:.2f}s"
    if fmt == "time_cs":
        return format_time_cs(int(round(value)))
    # "number": integers print clean, else up to 2 dp trimmed
    return _trim(value)


def format_time_cs(cs: int) -> str:
    """Centiseconds → clock time. 6234 → "1:02.34", 5012 → "50.12"."""
    cs = max(0, int(cs))
    mins = cs // 6000
    rem = cs - mins * 6000
    secs, frac = rem // 100, rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _trim(value: float) -> str:
    """Trim trailing zeros: 12.0 → "12", 1.20 → "1.2", 1.234 → "1.23"."""
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- #
# small numeric helpers (mirrors elements.models)
# --------------------------------------------------------------------------- #
def _safe_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default: int, *, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


__all__ = [
    "CHART_KINDS",
    "VALUE_FORMATS",
    "SERIES_ROLES",
    "DataPoint",
    "Series",
    "Axis",
    "ReferenceLine",
    "ChartSpec",
    "format_value",
    "format_time_cs",
]
