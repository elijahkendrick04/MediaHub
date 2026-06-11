"""
canonical — Canonical event schema.

Re-exports SportEvent and the swim-specific SwimMeet.
"""

from .event import SportEvent
from .swim import SwimMeet, Meet

__all__ = ["SportEvent", "SwimMeet", "Meet"]
