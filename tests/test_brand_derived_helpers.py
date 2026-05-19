"""Tests for the pure helpers in `mediahub.brand.derived`.

`derive_operating_profile` itself requires the cloud LLM and is not
exercised here (per CLAUDE.md this surface must not be heuristic-
substituted). The normalisation + lookup helpers around it are pure
and deterministic — those are what we pin here so the AI-derived
operating profile keeps its shape across releases.
"""
from __future__ import annotations

import pytest

from mediahub.brand.derived import (
    ARTEFACT_PLATFORM,
    CANONICAL_ACHIEVEMENT_TYPES,
    CANONICAL_ARTEFACTS,
    CANONICAL_TONES,
    PLATFORM_FORMATS,
    _get_op_profile,
    _norm_artefact_voice,
    _norm_priorities,
    _norm_str,
    _norm_tone_prose,
    _norm_type_phrases,
    artefact_intent_for,
    platform_format_for,
    priority_for,
    tone_descriptor_for,
    type_phrase_for,
)


# ---------------------------------------------------------------------------
# Canonical inventories
# ---------------------------------------------------------------------------


class TestCanonicalInventories:
    def test_canonical_tones_include_ai_baseline(self) -> None:
        assert "ai" in CANONICAL_TONES

    def test_canonical_achievement_types_include_pb_and_medal(self) -> None:
        for k in (
            "pb_confirmed",
            "official_pb_confirmed",
            "medal_gold",
            "first_sub_barrier",
        ):
            assert k in CANONICAL_ACHIEVEMENT_TYPES

    def test_canonical_artefacts_include_meet_recap_and_spotlight(self) -> None:
        for k in ("meet_recap", "swimmer_spotlight", "linkedin_long"):
            assert k in CANONICAL_ARTEFACTS


# ---------------------------------------------------------------------------
# _norm_str
# ---------------------------------------------------------------------------


class TestNormStr:
    def test_strips_and_caps(self) -> None:
        assert _norm_str("  hello  ", 10) == "hello"
        assert _norm_str("a" * 50, 10) == "a" * 10

    def test_non_string_returns_empty(self) -> None:
        assert _norm_str(42, 10) == ""
        assert _norm_str(None, 10) == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert _norm_str("   ", 10) == ""


# ---------------------------------------------------------------------------
# _norm_tone_prose
# ---------------------------------------------------------------------------


class TestNormToneProse:
    def test_keeps_canonical_keys_only(self) -> None:
        out = _norm_tone_prose({
            "warm-club": "friendly, family voice",
            "hype": "BIG NRG",
            "made-up": "should be dropped",
        })
        assert "warm-club" in out
        assert "hype" in out
        assert "made-up" not in out

    def test_caps_long_strings_at_400(self) -> None:
        out = _norm_tone_prose({"warm-club": "x" * 1000})
        assert len(out["warm-club"]) == 400

    def test_empty_values_dropped(self) -> None:
        out = _norm_tone_prose({"warm-club": "   "})
        assert out == {}

    def test_non_dict_returns_empty(self) -> None:
        assert _norm_tone_prose("nope") == {}
        assert _norm_tone_prose(None) == {}


# ---------------------------------------------------------------------------
# _norm_priorities
# ---------------------------------------------------------------------------


class TestNormPriorities:
    def test_clamps_to_band(self) -> None:
        # 50× weight from a hallucinated LLM should clamp to 2.0.
        out = _norm_priorities({"pb_confirmed": 50.0, "_default": -10})
        assert out["pb_confirmed"] == 2.0
        assert out["_default"] == 0.3  # clamped to lower bound

    def test_passes_through_in_range(self) -> None:
        out = _norm_priorities({"pb_confirmed": 1.4})
        assert out["pb_confirmed"] == pytest.approx(1.4)

    def test_default_key_allowed(self) -> None:
        out = _norm_priorities({"_default": 0.8})
        assert out["_default"] == pytest.approx(0.8)

    def test_unknown_achievement_types_dropped(self) -> None:
        out = _norm_priorities({"made_up_type": 1.0, "pb_confirmed": 1.5})
        assert "made_up_type" not in out
        assert "pb_confirmed" in out

    def test_non_numeric_values_dropped(self) -> None:
        out = _norm_priorities({"pb_confirmed": "high"})
        assert out == {}

    def test_non_dict_returns_empty(self) -> None:
        assert _norm_priorities("nope") == {}


# ---------------------------------------------------------------------------
# _norm_type_phrases
# ---------------------------------------------------------------------------


class TestNormTypePhrases:
    def test_caps_at_120(self) -> None:
        out = _norm_type_phrases({"pb_confirmed": "y" * 200})
        assert len(out["pb_confirmed"]) == 120

    def test_unknown_keys_dropped(self) -> None:
        out = _norm_type_phrases({"pb_confirmed": "a PB", "totally_made_up": "x"})
        assert "totally_made_up" not in out
        assert out["pb_confirmed"] == "a PB"

    def test_non_dict_returns_empty(self) -> None:
        assert _norm_type_phrases([]) == {}


# ---------------------------------------------------------------------------
# _norm_artefact_voice
# ---------------------------------------------------------------------------


class TestNormArtefactVoice:
    def test_caps_at_500(self) -> None:
        out = _norm_artefact_voice({"meet_recap": "z" * 1200})
        assert len(out["meet_recap"]) == 500

    def test_unknown_keys_dropped(self) -> None:
        out = _norm_artefact_voice({
            "meet_recap": "recap voice",
            "fake_artefact": "ignored",
        })
        assert "fake_artefact" not in out
        assert out["meet_recap"] == "recap voice"


# ---------------------------------------------------------------------------
# _get_op_profile
# ---------------------------------------------------------------------------


class TestGetOpProfile:
    def test_none_returns_empty(self) -> None:
        assert _get_op_profile(None) == {}

    def test_dict_profile_reads_brand_operating_profile_key(self) -> None:
        prof = {"brand_operating_profile": {"tone_prose": {"hype": "X"}}}
        op = _get_op_profile(prof)
        assert op["tone_prose"]["hype"] == "X"

    def test_object_profile_reads_attribute(self) -> None:
        class _P:
            brand_operating_profile = {"type_phrases": {"medal_gold": "gold"}}

        op = _get_op_profile(_P())
        assert op["type_phrases"]["medal_gold"] == "gold"

    def test_missing_op_returns_empty(self) -> None:
        assert _get_op_profile({}) == {}
        assert _get_op_profile({"brand_operating_profile": None}) == {}

    def test_non_dict_op_returns_empty(self) -> None:
        assert _get_op_profile({"brand_operating_profile": "wrong type"}) == {}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


class TestToneDescriptorFor:
    def test_returns_org_specific_value(self) -> None:
        prof = {
            "brand_operating_profile": {
                "tone_prose": {"hype": "Loud and proud"},
            },
        }
        assert tone_descriptor_for(prof, "hype", default="DEFAULT") == "Loud and proud"

    def test_falls_back_to_default_when_missing(self) -> None:
        assert tone_descriptor_for({}, "hype", default="DEFAULT") == "DEFAULT"

    def test_blank_value_falls_back(self) -> None:
        prof = {"brand_operating_profile": {"tone_prose": {"hype": "   "}}}
        assert tone_descriptor_for(prof, "hype", default="DEFAULT") == "DEFAULT"


class TestPriorityFor:
    def test_returns_specific_priority(self) -> None:
        prof = {
            "brand_operating_profile": {
                "achievement_priorities": {"pb_confirmed": 1.4},
            },
        }
        assert priority_for(prof, "pb_confirmed", default=1.0) == pytest.approx(1.4)

    def test_falls_back_to_default_key(self) -> None:
        prof = {
            "brand_operating_profile": {
                "achievement_priorities": {"_default": 0.8},
            },
        }
        assert priority_for(prof, "no_such_type", default=1.0) == pytest.approx(0.8)

    def test_falls_back_to_default_arg(self) -> None:
        assert priority_for({}, "pb_confirmed", default=1.2) == pytest.approx(1.2)

    def test_non_numeric_priority_falls_back(self) -> None:
        prof = {
            "brand_operating_profile": {
                "achievement_priorities": {"pb_confirmed": "bogus"},
            },
        }
        assert priority_for(prof, "pb_confirmed", default=1.0) == pytest.approx(1.0)


class TestTypePhraseFor:
    def test_returns_org_value(self) -> None:
        prof = {
            "brand_operating_profile": {
                "type_phrases": {"medal_gold": "a gold gong"},
            },
        }
        assert type_phrase_for(prof, "medal_gold", default="a gold") == "a gold gong"

    def test_falls_back_to_default(self) -> None:
        assert type_phrase_for({}, "medal_gold", default="a gold") == "a gold"


class TestArtefactIntentFor:
    def test_returns_org_value(self) -> None:
        prof = {
            "brand_operating_profile": {
                "artefact_voice": {"meet_recap": "warm community"},
            },
        }
        assert artefact_intent_for(prof, "meet_recap", default="X") == "warm community"

    def test_falls_back_to_default(self) -> None:
        assert artefact_intent_for({}, "meet_recap", default="X") == "X"


# ---------------------------------------------------------------------------
# platform_format_for — mechanical lookup, NOT AI-derived
# ---------------------------------------------------------------------------


class TestPlatformFormatFor:
    def test_known_artefact_returns_specific_rules(self) -> None:
        out = platform_format_for("instagram_long")
        assert "Instagram" in out
        assert "2,200" in out

    def test_x_artefact_rules(self) -> None:
        out = platform_format_for("data_thread_post")
        assert "280" in out

    def test_linkedin_artefact_rules(self) -> None:
        out = platform_format_for("linkedin_long")
        assert "LinkedIn" in out

    def test_email_artefact_rules(self) -> None:
        out = platform_format_for("parent_newsletter")
        assert "Email" in out or "email" in out

    def test_unknown_artefact_returns_generic(self) -> None:
        out = platform_format_for("totally_unknown")
        assert out == PLATFORM_FORMATS["generic"]

    def test_artefact_platform_map_covers_known_keys(self) -> None:
        # Pin the map so a removal/rename is deliberate.
        assert ARTEFACT_PLATFORM["instagram_long"] == "instagram"
        assert ARTEFACT_PLATFORM["data_thread_post"] == "x"
