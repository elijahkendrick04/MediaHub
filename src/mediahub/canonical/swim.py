"""
canonical/swim.py — SwimMeet, a swim-specific extension of SportEvent.

Back-compat alias: Meet = SwimMeet
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .event import SportEvent


@dataclass
class SwimMeet(SportEvent):
    """Swim-specific extension of SportEvent."""
    course: str = "LC"              # LC | SC | Y

    # Swim-specific entities (types from swim_content_v4.canonical)
    swimmers: dict = field(default_factory=dict)        # swimmer_key -> Swimmer
    clubs: dict = field(default_factory=dict)
    races: list = field(default_factory=list)
    relays: list = field(default_factory=list)
    standards_meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.sport:
            self.sport = "swimming"


# Back-compat alias — existing code uses Meet everywhere
Meet = SwimMeet
