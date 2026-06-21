"""charts.csv_input — turn an uploaded CSV/table into a ChartSpec (roadmap 1.11).

The "editable data table / CSV import" path: a club pastes or uploads a table and
gets a brand-styled chart. Like every parser in MediaHub it is **deterministic and
honest** — a cell that isn't a number is *flagged for review*, never silently
guessed or coerced to zero (the "flag ambiguous rows" rule). The numbers it does
accept are plotted exactly.

Shape expected (the common spreadsheet convention):

    Swimmer, PBs, Medals      <- header row: first cell labels the category axis,
    Smith J,   3,      2          each remaining cell names a data series
    Okafor A,  2,      1      <- data rows: first cell = category label, rest = values

A single value column makes a one-series bar; several make a grouped bar / multi-line.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Optional

from .models import Axis, ChartSpec, DataPoint, Series

_CHART_KINDS_CSV = ("bar", "hbar", "line", "scatter")


@dataclass
class CsvWarning:
    """One thing the importer could not cleanly accept (surfaced, never hidden)."""

    row: int  # 1-based source row (0 = header / structural)
    message: str
    cell: str = ""

    def to_dict(self) -> dict:
        return {"row": self.row, "message": self.message, "cell": self.cell}


@dataclass
class CsvImport:
    """The result of importing a table: the spec (if any) + every warning raised."""

    spec: Optional[ChartSpec]
    warnings: list[CsvWarning]

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.spec.is_empty()

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "spec": self.spec.to_dict() if self.spec else None,
            "warnings": [w.to_dict() for w in self.warnings],
        }


def parse_csv_to_spec(
    text: str,
    *,
    kind: str = "bar",
    title: str = "",
    value_format: str = "number",
) -> CsvImport:
    """Parse delimited table ``text`` into a ChartSpec, flagging ambiguous rows."""
    warnings: list[CsvWarning] = []
    kind = kind if kind in _CHART_KINDS_CSV else "bar"

    rows = _read_rows(text)
    if not rows:
        warnings.append(CsvWarning(0, "The table is empty — nothing to chart."))
        return CsvImport(None, warnings)

    header = rows[0]
    if len(header) < 2:
        warnings.append(
            CsvWarning(0, "Need at least two columns: a label column and one value column.")
        )
        return CsvImport(None, warnings)

    series_names = [h.strip() or f"Series {i}" for i, h in enumerate(header[1:], start=1)]
    n_series = len(series_names)
    series_points: list[list[DataPoint]] = [[] for _ in range(n_series)]

    for ri, row in enumerate(rows[1:], start=1):
        if not any(str(c).strip() for c in row):
            continue  # blank line — skip silently (not ambiguous)
        label = str(row[0]).strip() if row else ""
        if not label:
            warnings.append(CsvWarning(ri, "Row has no label in the first column — skipped."))
            continue
        for si in range(n_series):
            raw = row[si + 1] if (si + 1) < len(row) else ""
            cell = str(raw).strip()
            if cell == "":
                continue  # a gap in a series is allowed (just no point here)
            value = _to_number(cell)
            if value is None:
                warnings.append(
                    CsvWarning(
                        ri,
                        f"'{cell}' under '{series_names[si]}' isn't a number — skipped.",
                        cell=cell,
                    )
                )
                continue
            series_points[si].append(
                DataPoint(
                    label=label, value=value, display=cell, source_ref=f"csv:row{ri}:col{si + 1}"
                )
            )

    series = tuple(
        Series(name=series_names[si], points=tuple(series_points[si]))
        for si in range(n_series)
        if series_points[si]
    )
    if not series:
        warnings.append(CsvWarning(0, "No numeric values found — nothing could be charted."))
        return CsvImport(None, warnings)

    spec = ChartSpec(
        kind=kind,
        title=title.strip() or (header[0].strip() or "Chart"),
        series=series,
        x_axis=Axis(title=header[0].strip(), kind="category"),
        y_axis=Axis(value_format=value_format),
        source_note="Source: uploaded table",
        chart_id="csv_upload",
    )
    return CsvImport(spec, warnings)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _read_rows(text: str) -> list[list[str]]:
    if not text or not text.strip():
        return []
    # Sniff the delimiter; default to comma. Tabs and semicolons are common too.
    sample = text[:2048]
    delim = ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        if "\t" in sample and "," not in sample:
            delim = "\t"
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return [list(r) for r in reader if r is not None]


def _to_number(cell: str) -> Optional[float]:
    """Parse a numeric cell. Accepts thousands separators and a trailing %/units;
    returns ``None`` for anything genuinely non-numeric (so it gets flagged)."""
    s = cell.strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    # strip a trailing unit token (e.g. "1.2s") but keep the number
    if s and s[-1].isalpha():
        i = len(s)
        while i > 0 and (s[i - 1].isalpha()):
            i -= 1
        s = s[:i].strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


__all__ = ["CsvImport", "CsvWarning", "parse_csv_to_spec"]
