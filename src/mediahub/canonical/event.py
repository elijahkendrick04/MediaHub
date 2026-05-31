"""
canonical/event.py — Generic SportEvent base class.

Every sport adapter outputs a SportEvent or a subclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SportEvent:
    """Generic canonical schema. Every sport adapter outputs a SportEvent
    or a subclass."""

    sport: str  # "swimming" | "basketball" | "athletics" | ...
    event_id: str  # uniquely identifies this competition/match
    name: str  # human-readable e.g. "Spring Open Meet"
    start_date_iso: Optional[str] = None
    end_date_iso: Optional[str] = None
    venue: Optional[str] = None
    governing_body: Optional[str] = None

    # Sport-specific data lives here. Detectors for that sport know its shape.
    sport_data: dict = field(default_factory=dict)

    # Common entities
    participants: list = field(default_factory=list)  # SportParticipant or sport-specific
    results: list = field(default_factory=list)  # SportResult or sport-specific
    warnings: list = field(default_factory=list)
