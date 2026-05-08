"""
history/schema.py — Generic history provider interface schema.

These are sport-agnostic dataclasses. Swimming implements them via
swim_content_pb.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PreviousBest:
    """A participant's best performance for a specific event/course."""
    participant_id: str
    participant_name: str
    event_key: str                  # sport-specific event identifier
    performance_value: float        # lower = better (seconds, strokes, etc.)
    performance_display: str        # human-readable e.g. "1:01.42"
    recorded_date_iso: Optional[str] = None
    recorded_at_event: Optional[str] = None
    source_url: str = ""
    confidence: str = "high"        # "high" | "medium" | "low"
    notes: list = field(default_factory=list)


@dataclass
class IdentityMatch:
    """Result of matching a participant from the results file to an external record."""
    participant_id: Optional[str]
    raw_name: str                   # name from the results file
    matched_name: Optional[str]     # name returned by external source
    method: str                     # e.g. "id_verified" | "name_match" | "needs_verification"
    confidence: float               # 0.0-1.0
    safe_to_use: bool
    notes: list = field(default_factory=list)


@dataclass
class HistoryAudit:
    """Aggregate audit for history lookups in one run."""
    run_id: str
    participants_total: int = 0
    participants_matched: int = 0
    participants_needs_verification: int = 0
    participants_fetch_failed: int = 0
    decisions_count: int = 0
    confirmed_count: int = 0
    warnings: list = field(default_factory=list)
