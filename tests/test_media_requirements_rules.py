"""Tests for `mediahub.media_requirements.rules`.

REQUIREMENT_RULES is the sport-agnostic mapping of content type →
required media roles. The engine reads it to know whether a card
needs a hero athlete photo, a logo, a venue image, etc.

These tests pin the public-API contract (`requirements_for`,
`required_roles`, `all_roles`) and the role-shape invariants every
entry in REQUIREMENT_RULES must satisfy.
"""
from __future__ import annotations

import pytest

from mediahub.media_requirements.rules import (
    REQUIREMENT_RULES,
    MediaRequirement,
    MediaRequirementSet,
    requirements_for,
)


# ---------------------------------------------------------------------------
# requirements_for — lookup with fallback
# ---------------------------------------------------------------------------


class TestRequirementsFor:
    def test_returns_matching_rule(self) -> None:
        rs = requirements_for("confirmed_official_pb")
        assert isinstance(rs, MediaRequirementSet)
        assert rs.content_type == "confirmed_official_pb"

    def test_unknown_type_falls_back_to_recap_mention(self) -> None:
        rs = requirements_for("totally_made_up_content_type")
        assert rs.content_type == "recap_mention"

    def test_empty_string_falls_back_to_recap_mention(self) -> None:
        rs = requirements_for("")
        assert rs.content_type == "recap_mention"


# ---------------------------------------------------------------------------
# MediaRequirementSet accessors
# ---------------------------------------------------------------------------


class TestMediaRequirementSet:
    def test_required_roles_returns_only_required(self) -> None:
        rs = requirements_for("confirmed_official_pb")
        required = rs.required_roles()
        assert "hero_athlete" in required
        assert "logo" not in required  # logo is optional here

    def test_all_roles_returns_every_item(self) -> None:
        rs = requirements_for("confirmed_official_pb")
        roles = rs.all_roles()
        assert set(roles) >= {"hero_athlete", "logo", "venue"}

    def test_required_subset_of_all(self) -> None:
        rs = requirements_for("confirmed_official_pb")
        assert set(rs.required_roles()).issubset(rs.all_roles())

    def test_text_led_recap_has_no_required_hero(self) -> None:
        # Sanity: text-led layouts shouldn't force athlete photos.
        rs = requirements_for("weekend_recap")
        assert "hero_athlete" not in rs.required_roles()


# ---------------------------------------------------------------------------
# Whole-table invariants
# ---------------------------------------------------------------------------


class TestRequirementRulesInvariants:
    def test_every_key_matches_content_type(self) -> None:
        # The dictionary key MUST match the entry's content_type to avoid
        # silent drift after a copy-paste rename.
        for key, rs in REQUIREMENT_RULES.items():
            assert rs.content_type == key, f"mismatch on {key}"

    def test_recap_mention_present_as_fallback(self) -> None:
        # `requirements_for` relies on this entry; if it ever gets renamed
        # the fallback breaks silently — pin it here.
        assert "recap_mention" in REQUIREMENT_RULES

    def test_pb_family_requires_hero_athlete(self) -> None:
        # All PB-style cards should require a hero athlete photo.
        for key in (
            "confirmed_official_pb",
            "pb_improvement",
            "likely_pb",
            "first_sub_barrier",
        ):
            rs = REQUIREMENT_RULES[key]
            assert "hero_athlete" in rs.required_roles(), key

    def test_meet_preview_requires_venue_with_team_fallback(self) -> None:
        rs = REQUIREMENT_RULES["meet_preview"]
        venue_item = next(i for i in rs.items if i.role == "venue")
        assert venue_item.required is True
        assert venue_item.fallback_role == "team"

    def test_relay_highlight_requires_team_photo(self) -> None:
        rs = REQUIREMENT_RULES["relay_highlight"]
        assert "team" in rs.required_roles()

    def test_every_role_has_a_description(self) -> None:
        # Descriptions are user-facing — none should be blank.
        for key, rs in REQUIREMENT_RULES.items():
            for item in rs.items:
                assert item.description.strip(), f"{key} → {item.role} has no description"

    def test_every_set_has_a_layout(self) -> None:
        # Layout strings drive the renderer; never permit blanks.
        for key, rs in REQUIREMENT_RULES.items():
            assert rs.suggested_layout.strip(), f"{key} has no suggested_layout"


# ---------------------------------------------------------------------------
# MediaRequirement dataclass
# ---------------------------------------------------------------------------


class TestMediaRequirement:
    def test_default_fallback_is_none(self) -> None:
        item = MediaRequirement("hero_athlete", True, "Required photo")
        assert item.fallback_role is None

    def test_explicit_fallback_recorded(self) -> None:
        item = MediaRequirement("venue", True, "Venue", fallback_role="team")
        assert item.fallback_role == "team"
