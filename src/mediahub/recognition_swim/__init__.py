"""
recognition_swim — Swimming-specific recognition detectors.

Importing this module auto-registers "swimming" in the sport registry.
"""

from __future__ import annotations

from mediahub.recognition.registry import register_sport
from swim_content_v5.achievements import get_all_detectors
from .achievements.club_record import ClubRecordDetector
from .achievements.milestones import MilestoneDetector
from .achievements.official_pb import OfficialPBDetector


def production_detectors() -> list:
    """The full swimming detector set: OfficialPBDetector first (it covers
    the swim-equals-listed-PB case the plain PB detectors can't fire on),
    then the V5 detector suite, then the Phase W registry-fed detectors
    (milestones, club records — silent without workspace context)."""
    return (
        [OfficialPBDetector()]
        + get_all_detectors()
        + [MilestoneDetector(), ClubRecordDetector()]
    )


def init():
    """Register swimming in the sport registry with all detectors."""
    all_detectors = production_detectors()

    register_sport(
        "swimming",
        display_name="Swimming",
        detectors=all_detectors,
        history_provider=None,  # history flows via the V5 SwimmerHistory wrapper
        default_voice_templates={
            "pb_confirmed": "{name} goes {time} in {event} — a new personal best!",
            "medal_gold": "{name} wins gold in {event} at {meet}!",
            "official_pb_confirmed": "{name} sets an official PB: {time} in {event} (confirmed against an official PB lookup)",
        },
    )


# Auto-register on import
init()
