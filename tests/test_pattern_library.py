"""Tests for `mediahub.inspiration.pattern_library`.

The pattern library is the curated set of layout families the renderer
picks from when building a card. It's pure data + four deterministic
lookup functions; these tests pin the contract and exercise the
fallback / preference logic.
"""
from __future__ import annotations

import pytest

from mediahub.inspiration.pattern_library import (
    PATTERNS,
    best_pattern_for,
    get_pattern,
    list_patterns,
    patterns_for_post_angle,
)


# ---------------------------------------------------------------------------
# PATTERNS — structural invariants
# ---------------------------------------------------------------------------


class TestPatternsStructure:
    def test_non_empty(self) -> None:
        assert len(PATTERNS) > 0

    def test_each_pattern_has_required_keys(self) -> None:
        required = {"id", "label", "family", "post_angles", "format_priority"}
        for p in PATTERNS:
            assert required.issubset(p.keys()), f"missing keys on {p.get('id')}"

    def test_ids_are_unique(self) -> None:
        ids = [p["id"] for p in PATTERNS]
        assert len(ids) == len(set(ids))

    def test_post_angles_lists(self) -> None:
        for p in PATTERNS:
            assert isinstance(p["post_angles"], list)
            for a in p["post_angles"]:
                assert isinstance(a, str)

    def test_format_priority_lists(self) -> None:
        for p in PATTERNS:
            assert isinstance(p["format_priority"], list)
            for f in p["format_priority"]:
                assert isinstance(f, str)

    def test_text_led_recap_present(self) -> None:
        # `best_pattern_for` falls back to this id — it must exist.
        assert any(p["id"] == "text_led_recap" for p in PATTERNS)


# ---------------------------------------------------------------------------
# list_patterns
# ---------------------------------------------------------------------------


class TestListPatterns:
    def test_returns_one_entry_per_pattern(self) -> None:
        assert len(list_patterns()) == len(PATTERNS)

    def test_each_entry_has_summary_keys(self) -> None:
        for entry in list_patterns():
            assert set(entry.keys()) == {"id", "label", "family"}

    def test_returns_shallow_copy(self) -> None:
        # Mutating the listing should NOT mutate the registry.
        entries = list_patterns()
        entries[0]["id"] = "MUTATED"
        # The PATTERNS list is unaffected.
        assert all(p["id"] != "MUTATED" for p in PATTERNS)


# ---------------------------------------------------------------------------
# get_pattern
# ---------------------------------------------------------------------------


class TestGetPattern:
    def test_returns_pattern_dict(self) -> None:
        any_id = PATTERNS[0]["id"]
        p = get_pattern(any_id)
        assert p is not None
        assert p["id"] == any_id

    def test_unknown_id_returns_none(self) -> None:
        assert get_pattern("not-a-real-id") is None

    def test_empty_string_returns_none(self) -> None:
        assert get_pattern("") is None


# ---------------------------------------------------------------------------
# patterns_for_post_angle
# ---------------------------------------------------------------------------


class TestPatternsForPostAngle:
    def test_known_angle_returns_patterns(self) -> None:
        # Use the first angle of the first pattern as the probe.
        probe = PATTERNS[0]["post_angles"][0]
        out = patterns_for_post_angle(probe)
        assert len(out) > 0
        for p in out:
            assert probe in p["post_angles"]

    def test_unknown_angle_returns_empty(self) -> None:
        assert patterns_for_post_angle("not-an-angle") == []

    def test_confirmed_official_pb_has_matches(self) -> None:
        # This angle should match the athlete-hero family at minimum.
        out = patterns_for_post_angle("confirmed_official_pb")
        assert len(out) >= 1


# ---------------------------------------------------------------------------
# best_pattern_for
# ---------------------------------------------------------------------------


class TestBestPatternFor:
    def test_unknown_angle_falls_back_to_text_led_recap(self) -> None:
        chosen = best_pattern_for("totally_unknown_angle")
        assert chosen["id"] == "text_led_recap"

    def test_known_angle_returns_a_candidate(self) -> None:
        chosen = best_pattern_for("confirmed_official_pb")
        assert "confirmed_official_pb" in chosen["post_angles"]

    def test_prefer_family_filters_candidates(self) -> None:
        # individual_hero is a documented family.
        chosen = best_pattern_for(
            "confirmed_official_pb",
            prefer_family="individual_hero",
        )
        assert chosen["family"] == "individual_hero"

    def test_format_hint_prefers_matching_format(self) -> None:
        chosen = best_pattern_for(
            "confirmed_official_pb",
            format_hint="story",
        )
        # `story` should appear earlier in the chosen pattern's priority list
        # than alternatives without it.
        assert "story" in chosen["format_priority"]

    def test_prefer_family_not_matching_falls_through(self) -> None:
        # If no candidate matches the preferred family, the function does
        # not return None — it should still return a pattern.
        chosen = best_pattern_for(
            "confirmed_official_pb",
            prefer_family="some-imaginary-family",
        )
        # Without a match, prefer_family is just ignored; we still get a pattern.
        assert chosen is not None
        assert "confirmed_official_pb" in chosen["post_angles"]

    def test_format_hint_unknown_does_not_crash(self) -> None:
        chosen = best_pattern_for(
            "confirmed_official_pb",
            format_hint="totally-made-up-format",
        )
        # Unknown format hint scores all candidates equally → returns the
        # first one. Either way, we get a valid pattern.
        assert chosen is not None
        assert "id" in chosen
