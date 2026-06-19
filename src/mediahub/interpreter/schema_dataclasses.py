"""
schema_dataclasses.py — data model for the V7.5 interpreter output.

No domain vocabulary literals here.  All canonical term sets live in data/ontology/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Low-level layout primitives produced by ingest.py
# ---------------------------------------------------------------------------


@dataclass
class Line:
    text: str
    page_no: int = 0
    y_position: float = 0.0
    x_position: float = 0.0
    font_size_hint: Optional[float] = None


@dataclass
class TableCandidate:
    """A region of text that looks like a table."""

    rows: list[list[str]]  # [row_idx][col_idx] → cell text
    page_no: int = 0
    x_range: tuple[float, float] = (0.0, 0.0)
    y_range: tuple[float, float] = (0.0, 0.0)
    col_x_centers: list[float] = field(default_factory=list)


@dataclass
class IngestStream:
    text: str
    lines: list[Line]
    tables: list[TableCandidate]
    format_detected: str = "unknown"


# ---------------------------------------------------------------------------
# Schema induction outputs
# ---------------------------------------------------------------------------


@dataclass
class ColumnSchema:
    name: str  # e.g. "place", "name", "time", …
    col_type: str  # same vocabulary as name (column semantic type)
    confidence: float  # 0..1
    x_range: tuple[float, float] = (0.0, 0.0)
    header_text: Optional[str] = None
    col_index: Optional[int] = None  # for table-based extraction


# ---------------------------------------------------------------------------
# Interpreted output
# ---------------------------------------------------------------------------


@dataclass
class InterpretedSwim:
    swimmer_name: str
    yob: Optional[int]
    club: Optional[str]
    place: Optional[int]
    time: Optional[str]  # canonical "mm:ss.cc" or "ss.cc"
    reaction: Optional[str]
    confidence: float  # 0..1 per swim
    raw_row: str
    field_confidence: dict[str, float] = field(default_factory=dict)


@dataclass
class InterpretedEvent:
    gender: Optional[str]  # "M" / "F" / "X" / None
    distance_m: Optional[int]
    stroke: Optional[str]  # canonical stroke name from ontology
    course: Optional[str]  # "LC" / "SC" / None
    age_band: Optional[str]
    swims: list[InterpretedSwim] = field(default_factory=list)
    confidence: float = 0.0
    raw_header: str = ""


@dataclass
class InterpretedMeet:
    meet_name: Optional[str]
    venue: Optional[str]
    dates: Optional[tuple[str, str]]
    course_default: Optional[str]
    governing_body_hint: Optional[str]
    events: list[InterpretedEvent] = field(default_factory=list)
    overall_confidence: float = 0.0
    needs_review: list[dict] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    patterns_used: list[str] = field(default_factory=list)
    new_patterns_proposed: list[dict] = field(default_factory=list)
