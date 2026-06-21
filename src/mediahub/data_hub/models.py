"""data_hub.models — the shape of a user-facing data table (roadmap 1.13).

MediaHub is structured-data-first: the canonical results store *is* the
spreadsheet. This module gives that store (and the club's own editable tables)
a single, serialisable shape the UI can browse and edit — a **table** of
**columns** and **rows**, where every **cell** carries its own *provenance*:
where the value came from and how much we trust it.

The provenance badge is the "flag ambiguous rows" rule made visible. A value
that was parsed from a results file looks different from one a volunteer typed
in, from one a deterministic formula derived, from one a connector pulled. A
cell that could not be cleanly read is *flagged* — never silently guessed.

Everything here is plain data: dataclasses with ``to_dict`` / ``from_dict`` so a
table round-trips through JSON, CSV and XLSX without losing its meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Provenance — where a cell's value came from, and the honesty rule
# ---------------------------------------------------------------------------


class Provenance:
    """How a cell got its value. A small, stable vocabulary the UI badges.

    Not an ``enum.Enum`` so values serialise as plain strings and old persisted
    tables keep loading even if we add a kind later.
    """

    PARSED = "parsed"  # extracted from a results file by the deterministic engine
    IMPORTED = "imported"  # came from a CSV/XLSX the user uploaded
    HAND_ENTERED = "hand"  # typed in by a person in the data hub
    DERIVED = "derived"  # computed by a registered deterministic derivation
    CONNECTOR = "connector"  # pulled from an external connector (with trust metadata)
    REGISTRY = "registry"  # held in an org-scoped store (athletes, records)
    UNKNOWN = "unknown"

    ALL = (PARSED, IMPORTED, HAND_ENTERED, DERIVED, CONNECTOR, REGISTRY, UNKNOWN)

    # Plain-English label for each kind (used by the grid's provenance badge).
    LABELS = {
        PARSED: "From results file",
        IMPORTED: "Imported",
        HAND_ENTERED: "Typed in",
        DERIVED: "Calculated",
        CONNECTOR: "Synced",
        REGISTRY: "Club store",
        UNKNOWN: "Unknown",
    }

    @classmethod
    def normalise(cls, value: object) -> str:
        s = str(value or "").strip().lower()
        return s if s in cls.ALL else cls.UNKNOWN

    @classmethod
    def label(cls, value: object) -> str:
        return cls.LABELS.get(cls.normalise(value), cls.LABELS[cls.UNKNOWN])


# Column value kinds. Kept deliberately small; "time" means swim time stored as
# centiseconds (the engine's canonical unit) with a mm:ss.ss display.
COLUMN_TYPES = ("text", "number", "int", "time", "date", "bool")


# ---------------------------------------------------------------------------
# Cell
# ---------------------------------------------------------------------------


@dataclass
class DataCell:
    """One value in one row, with its provenance and trust."""

    value: Any = None  # canonical typed value (str/int/float/bool/None)
    display: str = ""  # human display string (what the grid shows)
    provenance: str = Provenance.UNKNOWN
    confidence: str = ""  # "high" | "medium" | "low" | "" (mirrors engine vocab)
    source: str = ""  # short source label or URL
    note: str = ""  # e.g. an ambiguity explanation
    flagged: bool = False  # True ⇒ needs a human's eye (ambiguous/uncertain)

    def __post_init__(self) -> None:
        self.provenance = Provenance.normalise(self.provenance)
        if not self.display and self.value is not None:
            self.display = str(self.value)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "display": self.display,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "source": self.source,
            "note": self.note,
            "flagged": bool(self.flagged),
        }

    @classmethod
    def from_dict(cls, d: object) -> "DataCell":
        if not isinstance(d, dict):
            # Tolerate a bare value (older/looser payloads).
            return cls(value=d, display="" if d is None else str(d))
        return cls(
            value=d.get("value"),
            display=str(d.get("display", "") or ""),
            provenance=d.get("provenance", Provenance.UNKNOWN),
            confidence=str(d.get("confidence", "") or ""),
            source=str(d.get("source", "") or ""),
            note=str(d.get("note", "") or ""),
            flagged=bool(d.get("flagged", False)),
        )


def text_cell(value: object, **kw) -> DataCell:
    """Convenience: a plain text cell (defaults to hand-entered)."""
    kw.setdefault("provenance", Provenance.HAND_ENTERED)
    s = "" if value is None else str(value)
    return DataCell(value=s, display=s, **kw)


# ---------------------------------------------------------------------------
# Column
# ---------------------------------------------------------------------------


@dataclass
class DataColumn:
    """One column: its key, heading, value kind and editing/derivation rules."""

    key: str
    title: str
    type: str = "text"
    editable: bool = False  # can a person edit cells in this column?
    derived: bool = False  # computed by a derivation (read-only, recomputed)
    derivation: str = ""  # name of the derivation that fills it (if derived)
    frozen: bool = False  # UI hint: keep this column pinned while scrolling
    width: int = 0  # UI hint: preferred px width (0 = auto)
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in COLUMN_TYPES:
            self.type = "text"
        if self.derived:
            # A derived column is computed, so never hand-editable.
            self.editable = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "type": self.type,
            "editable": bool(self.editable),
            "derived": bool(self.derived),
            "derivation": self.derivation,
            "frozen": bool(self.frozen),
            "width": int(self.width or 0),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DataColumn":
        return cls(
            key=str(d.get("key", "")),
            title=str(d.get("title", d.get("key", ""))),
            type=str(d.get("type", "text") or "text"),
            editable=bool(d.get("editable", False)),
            derived=bool(d.get("derived", False)),
            derivation=str(d.get("derivation", "") or ""),
            frozen=bool(d.get("frozen", False)),
            width=int(d.get("width", 0) or 0),
            description=str(d.get("description", "") or ""),
        )


# ---------------------------------------------------------------------------
# Warning (mirrors charts.csv_input.CsvWarning / canonical.ParseWarning)
# ---------------------------------------------------------------------------


@dataclass
class DataWarning:
    """One thing the importer/derivation could not cleanly accept — surfaced."""

    row: int  # 1-based source row (0 = header / structural)
    message: str
    cell: str = ""
    severity: str = "warn"  # info | warn | error

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "message": self.message,
            "cell": self.cell,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DataWarning":
        return cls(
            row=int(d.get("row", 0) or 0),
            message=str(d.get("message", "")),
            cell=str(d.get("cell", "") or ""),
            severity=str(d.get("severity", "warn") or "warn"),
        )


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

# Table "kinds". The canonical views are read-only mirrors of the engine's
# stores; "org" tables are the club's own editable sheets.
TABLE_KINDS = (
    "athletes",
    "results",
    "swimmers",
    "clubs",
    "meets",
    "records",
    "org",
)


@dataclass
class DataTable:
    """A browsable/editable table of cells with provenance.

    ``rows`` is a list of dicts keyed by column key → :class:`DataCell`. A
    missing key renders as an empty cell, so rows need not be dense.
    """

    table_id: str
    title: str
    kind: str = "org"
    profile_id: str = ""
    columns: list[DataColumn] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)  # list[dict[str, DataCell]]
    editable: bool = False  # whole-table edit gate (org tables = True)
    source: str = ""  # provenance of the table itself (run id, store, connector)
    description: str = ""
    warnings: list[DataWarning] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in TABLE_KINDS:
            self.kind = "org"

    # ----- conveniences -----

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_keys(self) -> list[str]:
        return [c.key for c in self.columns]

    def column(self, key: str) -> Optional[DataColumn]:
        for c in self.columns:
            if c.key == key:
                return c
        return None

    def cell(self, row_index: int, key: str) -> DataCell:
        """Return the cell at (row, column) or an empty cell if absent."""
        if 0 <= row_index < len(self.rows):
            c = self.rows[row_index].get(key)
            if isinstance(c, DataCell):
                return c
            if c is not None:
                return DataCell.from_dict(c)
        return DataCell()

    @property
    def flagged_count(self) -> int:
        n = 0
        for row in self.rows:
            for c in row.values():
                cell = c if isinstance(c, DataCell) else DataCell.from_dict(c)
                if cell.flagged:
                    n += 1
        return n

    def summary(self) -> dict:
        """Counts for the table header / hub index."""
        return {
            "table_id": self.table_id,
            "title": self.title,
            "kind": self.kind,
            "editable": self.editable,
            "n_columns": len(self.columns),
            "n_rows": self.row_count,
            "n_flagged": self.flagged_count,
            "n_warnings": len(self.warnings),
            "source": self.source,
        }

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "title": self.title,
            "kind": self.kind,
            "profile_id": self.profile_id,
            "editable": bool(self.editable),
            "source": self.source,
            "description": self.description,
            "columns": [c.to_dict() for c in self.columns],
            "rows": [
                {
                    k: (v.to_dict() if isinstance(v, DataCell) else DataCell.from_dict(v).to_dict())
                    for k, v in row.items()
                }
                for row in self.rows
            ],
            "warnings": [w.to_dict() for w in self.warnings],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DataTable":
        cols = [DataColumn.from_dict(c) for c in d.get("columns", []) if isinstance(c, dict)]
        rows: list[dict] = []
        for row in d.get("rows", []):
            if isinstance(row, dict):
                rows.append({k: DataCell.from_dict(v) for k, v in row.items()})
        warns = [DataWarning.from_dict(w) for w in d.get("warnings", []) if isinstance(w, dict)]
        return cls(
            table_id=str(d.get("table_id", "")),
            title=str(d.get("title", "")),
            kind=str(d.get("kind", "org") or "org"),
            profile_id=str(d.get("profile_id", "") or ""),
            columns=cols,
            rows=rows,
            editable=bool(d.get("editable", False)),
            source=str(d.get("source", "") or ""),
            description=str(d.get("description", "") or ""),
            warnings=warns,
        )


__all__ = [
    "Provenance",
    "COLUMN_TYPES",
    "TABLE_KINDS",
    "DataCell",
    "DataColumn",
    "DataWarning",
    "DataTable",
    "text_cell",
]
