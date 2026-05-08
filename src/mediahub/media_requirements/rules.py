"""Per-content-type media requirement declarations.

The engine layer is sport-agnostic: rules are keyed off post_angle / card_type
strings that the recognition/content_pack layers produce. Swim-specific
vocabulary (events, strokes) is *not* referenced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MediaRequirement:
    role: str                     # e.g. "hero_athlete", "venue", "logo"
    required: bool                # True = must have to render; False = optional
    description: str              # human-facing label
    fallback_role: Optional[str] = None  # what to look for if primary role missing


@dataclass
class MediaRequirementSet:
    content_type: str
    items: list[MediaRequirement] = field(default_factory=list)
    suggested_layout: str = "individual_hero"
    notes: str = ""

    def required_roles(self) -> list[str]:
        return [i.role for i in self.items if i.required]

    def all_roles(self) -> list[str]:
        return [i.role for i in self.items]


# --------------------------------------------------------------------------
# Layout family per post_angle / card_type
# --------------------------------------------------------------------------

REQUIREMENT_RULES: dict[str, MediaRequirementSet] = {

    # --- PB family -------------------------------------------------------
    "confirmed_official_pb": MediaRequirementSet(
        content_type="confirmed_official_pb",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
            MediaRequirement("venue", False, "Venue / pool image"),
        ],
    ),
    "pb_improvement": MediaRequirementSet(
        content_type="pb_improvement",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "likely_pb": MediaRequirementSet(
        content_type="likely_pb",
        suggested_layout="individual_hero",
        notes="Confidence medium — wording must say 'LIKELY PB', not 'NEW PB'.",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "first_sub_barrier": MediaRequirementSet(
        content_type="first_sub_barrier",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),

    # --- Medals ----------------------------------------------------------
    "medal_gold": MediaRequirementSet(
        content_type="medal_gold",
        suggested_layout="medal_card",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "medal_silver": MediaRequirementSet(
        content_type="medal_silver",
        suggested_layout="medal_card",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "medal_bronze": MediaRequirementSet(
        content_type="medal_bronze",
        suggested_layout="medal_card",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "medal_and_pb_combo": MediaRequirementSet(
        content_type="medal_and_pb_combo",
        suggested_layout="medal_card",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),

    # --- Field context --------------------------------------------------
    "finalist": MediaRequirementSet(
        content_type="finalist",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "top_of_field": MediaRequirementSet(
        content_type="top_of_field",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "qualifying_time": MediaRequirementSet(
        content_type="qualifying_time",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "heat_to_final_drop": MediaRequirementSet(
        content_type="heat_to_final_drop",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
        ],
    ),
    "biggest_drop": MediaRequirementSet(
        content_type="biggest_drop",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
        ],
    ),

    # --- Team / aggregate ----------------------------------------------
    "weekend_in_numbers": MediaRequirementSet(
        content_type="weekend_in_numbers",
        suggested_layout="weekend_numbers",
        notes="Text-led; venue/team image optional background.",
        items=[
            MediaRequirement("logo", False, "Club logo"),
            MediaRequirement("venue", False, "Venue image (background)"),
            MediaRequirement("team", False, "Team photo (background)"),
        ],
    ),
    "athlete_spotlight": MediaRequirementSet(
        content_type="athlete_spotlight",
        suggested_layout="athlete_spotlight",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "relay_highlight": MediaRequirementSet(
        content_type="relay_highlight",
        suggested_layout="medal_card",
        items=[
            MediaRequirement("team", True, "Team / relay photo"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "team_depth": MediaRequirementSet(
        content_type="team_depth",
        suggested_layout="weekend_numbers",
        items=[
            MediaRequirement("team", False, "Team photo"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "recap_mention": MediaRequirementSet(
        content_type="recap_mention",
        suggested_layout="text_led_recap",
        items=[
            MediaRequirement("logo", False, "Club logo"),
            MediaRequirement("venue", False, "Venue image (background)"),
        ],
    ),
    "weekend_recap": MediaRequirementSet(
        content_type="weekend_recap",
        suggested_layout="text_led_recap",
        items=[
            MediaRequirement("team", False, "Team photo"),
            MediaRequirement("venue", False, "Venue image"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),

    # --- Preview / non-meet --------------------------------------------
    "meet_preview": MediaRequirementSet(
        content_type="meet_preview",
        suggested_layout="meet_preview",
        items=[
            MediaRequirement("venue", True, "Venue image", fallback_role="team"),
            MediaRequirement("logo", False, "Club logo"),
        ],
    ),
    "fastest_since": MediaRequirementSet(
        content_type="fastest_since",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
        ],
    ),
    "multi_pb_weekend": MediaRequirementSet(
        content_type="multi_pb_weekend",
        suggested_layout="athlete_spotlight",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
        ],
    ),
    "return_to_form": MediaRequirementSet(
        content_type="return_to_form",
        suggested_layout="individual_hero",
        items=[
            MediaRequirement("hero_athlete", True, "Real photo of the athlete"),
        ],
    ),
}


def requirements_for(content_type: str) -> MediaRequirementSet:
    """Look up requirement set for a content type, falling back to recap_mention."""
    return REQUIREMENT_RULES.get(
        content_type, REQUIREMENT_RULES["recap_mention"]
    )


__all__ = [
    "MediaRequirement",
    "MediaRequirementSet",
    "REQUIREMENT_RULES",
    "requirements_for",
]
