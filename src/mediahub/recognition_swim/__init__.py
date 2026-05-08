"""
recognition_swim — Swimming-specific recognition detectors.

Importing this module auto-registers "swimming" in the sport registry.
"""
from __future__ import annotations

from mediahub.recognition.registry import register_sport
from swim_content_v5.achievements import get_all_detectors
from .achievements.official_pb import OfficialPBDetector


def init():
    """Register swimming in the sport registry with all detectors."""
    detectors = get_all_detectors()
    # Prepend OfficialPBDetector so it runs before other PB detectors
    official_pb = OfficialPBDetector()
    all_detectors = [official_pb] + detectors

    register_sport(
        "swimming",
        display_name="Swimming",
        detectors=all_detectors,
        history_provider=None,  # set later when swim_content_pb is wired
        default_voice_templates={
            "pb_confirmed": "{name} goes {time} in {event} — a new personal best!",
            "medal_gold": "{name} wins gold in {event} at {meet}!",
            "official_pb_confirmed": "{name} sets an official PB: {time} in {event} (confirmed against an official PB lookup)",
        },
    )


# Auto-register on import
init()
