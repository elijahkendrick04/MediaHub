"""
Tone enum and metadata.

Three tones are supported:
  WARM_CLUB  — conversational, member-facing, first-name use (default)
  HYPE       — energetic, race-day language, full names, exclamation-friendly
  DATA_LED   — numbers-first, formal, sponsor-friendly
"""
from __future__ import annotations

from enum import Enum


class Tone(str, Enum):
    WARM_CLUB = "warm-club"
    HYPE = "hype"
    DATA_LED = "data-led"


TONE_META: dict[Tone, dict] = {
    Tone.WARM_CLUB: {
        "label": "Warm club",
        "description": "Conversational and member-facing. Defaults to first-name use.",
        "example": "Mathew dropped 1.4s on his 100 fly — biggest improvement of the weekend.",
    },
    Tone.HYPE: {
        "label": "Hype",
        "description": "Energetic, race-day language, full names with 'goes sub-X' framing.",
        "example": "MATHEW BRADLEY GOES SUB-58 ON 100 FLY — first time under the barrier.",
    },
    Tone.DATA_LED: {
        "label": "Data-led",
        "description": "Numbers first, formal, sponsor-friendly, lower exclamation density.",
        "example": "Mathew Bradley: 100m Butterfly LC — 57.95 (PB, −1.4s). New club record.",
    },
}


def tone_from_str(s: str) -> Tone:
    """Convert a string to a Tone, returning WARM_CLUB as the safe default."""
    try:
        return Tone(s)
    except ValueError:
        return Tone.WARM_CLUB
