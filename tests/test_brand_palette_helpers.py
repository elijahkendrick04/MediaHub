"""Tests for the pure helpers in `mediahub.brand.palette`.

The LLM-dependent path (`resolve_palette`) is not exercised here
because per CLAUDE.md palette resolution is judgement-based and must
go through the cloud LLM — never substituted with a heuristic. The
helpers around it (hex normalisation, source aggregation, manual
override sanitisation, effective-palette merge, and validation of the
LLM response shape) are all pure and deterministic, and this file
pins their contracts.
"""
from __future__ import annotations

import pytest

from mediahub.brand.palette import (
    ALL_SLOTS,
    FOURTH_SLOT,
    SLOTS,
    _clean_hex_list,
    _normalise_hex,
    _validate_picks,
    effective_palette,
    gather_colour_sources,
    sanitise_manual_palette,
)


# ---------------------------------------------------------------------------
# Slot constants
# ---------------------------------------------------------------------------


class TestSlots:
    def test_canonical_slots(self) -> None:
        assert SLOTS == ("primary", "secondary", "accent")

    def test_all_slots_appends_fourth(self) -> None:
        assert ALL_SLOTS == ("primary", "secondary", "accent", "fourth")
        assert FOURTH_SLOT == "fourth"


# ---------------------------------------------------------------------------
# _normalise_hex
# ---------------------------------------------------------------------------


class TestNormaliseHex:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("#FF00CC", "#ff00cc"),
            ("FF00CC", "#ff00cc"),
            ("  #ff00cc  ", "#ff00cc"),
            ("#abc", "#aabbcc"),
            ("abc", "#aabbcc"),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str) -> None:
        assert _normalise_hex(raw) == expected

    def test_uppercase_normalised_to_lower(self) -> None:
        assert _normalise_hex("#FFFFFF") == "#ffffff"

    @pytest.mark.parametrize(
        "raw",
        ["", "  ", "#GGGGGG", "#1234567", "#12345", "not-hex", "#1234"],
    )
    def test_invalid_returns_none(self, raw: str) -> None:
        assert _normalise_hex(raw) is None

    def test_non_string_returns_none(self) -> None:
        assert _normalise_hex(None) is None  # type: ignore[arg-type]
        assert _normalise_hex(123) is None  # type: ignore[arg-type]
        assert _normalise_hex([]) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _clean_hex_list
# ---------------------------------------------------------------------------


class TestCleanHexList:
    def test_basic_clean(self) -> None:
        out = _clean_hex_list(["#FF0000", "00FF00", "#0000FF"])
        assert out == ["#ff0000", "#00ff00", "#0000ff"]

    def test_dedupes_preserving_order(self) -> None:
        out = _clean_hex_list(["#abc", "#aabbcc", "#FF0000", "ff0000"])
        # "#abc" normalises to "#aabbcc", and the second "ff0000" dupes the first.
        assert out == ["#aabbcc", "#ff0000"]

    def test_drops_invalid(self) -> None:
        out = _clean_hex_list(["#abc", "garbage", "", None, "#deadbeef"])
        # "#deadbeef" is 8 chars — invalid hex format.
        assert out == ["#aabbcc"]

    def test_non_list_returns_empty(self) -> None:
        assert _clean_hex_list({"#abc"}) == []
        assert _clean_hex_list("#abc") == []
        assert _clean_hex_list(None) == []


# ---------------------------------------------------------------------------
# gather_colour_sources
# ---------------------------------------------------------------------------


class TestGatherColourSources:
    def test_empty_inputs_yield_empty(self) -> None:
        assert gather_colour_sources() == {}

    def test_link_signals_attached_per_platform(self) -> None:
        sources = gather_colour_sources(
            link_palette_signals={
                "website": ["#abc", "#FF0000"],
                "instagram": ["#0000FF"],
            },
        )
        assert sources["website (palette_mentions)"] == ["#aabbcc", "#ff0000"]
        assert sources["instagram (palette_mentions)"] == ["#0000ff"]

    def test_brand_guidelines_palette_mentions(self) -> None:
        sources = gather_colour_sources(
            brand_guidelines={"palette_mentions": ["#003366", "#FFFFFF"]},
        )
        assert sources["brand_guidelines (palette_mentions)"] == [
            "#003366",
            "#ffffff",
        ]

    def test_brand_logos_dominant_colours_per_label(self) -> None:
        sources = gather_colour_sources(
            brand_logos=[
                {"label": "navy.svg", "ai_dominant_colours": ["#003366"]},
                {"original_filename": "wordmark.svg", "ai_dominant_colours": ["#0a2540"]},
                {"logo_id": "logo-3", "ai_dominant_colours": ["#bada55"]},
            ],
        )
        assert "logo: navy.svg (dominant)" in sources
        assert "logo: wordmark.svg (dominant)" in sources
        assert "logo: logo-3 (dominant)" in sources

    def test_logo_with_empty_dominant_colours_skipped(self) -> None:
        sources = gather_colour_sources(
            brand_logos=[
                {"label": "x.svg", "ai_dominant_colours": []},
                {"label": "y.svg", "ai_dominant_colours": ["#aabbcc"]},
            ],
        )
        assert "logo: x.svg (dominant)" not in sources
        assert "logo: y.svg (dominant)" in sources

    def test_empty_links_for_platform_filtered(self) -> None:
        sources = gather_colour_sources(
            link_palette_signals={"website": [], "instagram": ["#ff0000"]},
        )
        assert "website (palette_mentions)" not in sources
        assert "instagram (palette_mentions)" in sources

    def test_non_dict_brand_guidelines_ignored(self) -> None:
        sources = gather_colour_sources(brand_guidelines=["just", "a", "list"])  # type: ignore[arg-type]
        assert sources == {}


# ---------------------------------------------------------------------------
# sanitise_manual_palette
# ---------------------------------------------------------------------------


class TestSanitiseManualPalette:
    def test_all_three_slots_clean(self) -> None:
        out = sanitise_manual_palette(
            primary="#FF0000",
            secondary="00FF00",
            accent="#0000FF",
        )
        assert out == {
            "primary": "#ff0000",
            "secondary": "#00ff00",
            "accent": "#0000ff",
        }

    def test_invalid_slots_dropped(self) -> None:
        out = sanitise_manual_palette(
            primary="not-hex",
            secondary="#00FF00",
            accent="",
        )
        assert out == {"secondary": "#00ff00"}

    def test_fourth_slot_only_when_opted_in(self) -> None:
        out = sanitise_manual_palette(
            primary="#FF0000",
            fourth="#ABCDEF",
            include_fourth=True,
        )
        assert out.get("fourth") == "#abcdef"

    def test_fourth_dropped_when_include_false(self) -> None:
        out = sanitise_manual_palette(
            primary="#FF0000",
            fourth="#ABCDEF",
            include_fourth=False,
        )
        assert "fourth" not in out

    def test_empty_call_returns_empty(self) -> None:
        assert sanitise_manual_palette() == {}


# ---------------------------------------------------------------------------
# effective_palette — manual overrides per-slot
# ---------------------------------------------------------------------------


class TestEffectivePalette:
    def test_manual_wins_per_slot(self) -> None:
        out = effective_palette(
            manual={"primary": "#FF0000"},
            extracted={"primary": "#0000FF", "secondary": "#00FF00", "accent": "#ABCDEF"},
        )
        assert out == {
            "primary": "#ff0000",
            "secondary": "#00ff00",
            "accent": "#abcdef",
        }

    def test_manual_missing_slot_falls_back_to_extracted(self) -> None:
        out = effective_palette(
            manual={"primary": "#FF0000"},
            extracted={"primary": "#0000FF", "secondary": "#123456"},
        )
        assert out["primary"] == "#ff0000"
        assert out["secondary"] == "#123456"

    def test_invalid_manual_slot_falls_back(self) -> None:
        out = effective_palette(
            manual={"primary": "garbage"},
            extracted={"primary": "#abcdef"},
        )
        assert out["primary"] == "#abcdef"

    def test_fourth_only_present_when_explicit(self) -> None:
        # Neither dict carries 'fourth' → output omits it.
        out = effective_palette(
            manual={"primary": "#ff0000"},
            extracted={"primary": "#ff0000"},
        )
        assert "fourth" not in out

    def test_fourth_from_manual(self) -> None:
        out = effective_palette(
            manual={"fourth": "#abcdef"},
            extracted={},
        )
        assert out["fourth"] == "#abcdef"

    def test_fourth_from_extracted_when_manual_missing(self) -> None:
        out = effective_palette(
            manual={},
            extracted={"fourth": "#abcdef"},
        )
        assert out["fourth"] == "#abcdef"

    def test_both_none_returns_empty(self) -> None:
        assert effective_palette(manual=None, extracted=None) == {}


# ---------------------------------------------------------------------------
# _validate_picks — guard against LLM hallucinated colours
# ---------------------------------------------------------------------------


class TestValidatePicks:
    def test_universe_filter_drops_hallucinated(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "secondary": "#deadda"},
            allow_fourth=False,
            universe={"#aabbcc", "#112233"},
        )
        assert out == {"primary": "#aabbcc"}

    def test_empty_universe_allows_anything(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "secondary": "#112233"},
            allow_fourth=False,
            universe=set(),
        )
        assert out == {"primary": "#aabbcc", "secondary": "#112233"}

    def test_non_dict_raw_returns_empty(self) -> None:
        assert _validate_picks("not a dict", allow_fourth=False, universe=set()) == {}
        assert _validate_picks(None, allow_fourth=False, universe=set()) == {}

    def test_allow_fourth_lets_through_fourth_slot(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "fourth": "#112233"},
            allow_fourth=True,
            universe={"#aabbcc", "#112233"},
        )
        assert out["fourth"] == "#112233"

    def test_fourth_dropped_when_not_allowed(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "fourth": "#112233"},
            allow_fourth=False,
            universe={"#aabbcc", "#112233"},
        )
        assert "fourth" not in out

    def test_reasoning_string_preserved_and_truncated(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "reasoning": "x" * 500},
            allow_fourth=False,
            universe={"#aabbcc"},
        )
        assert "reasoning" in out
        assert len(out["reasoning"]) <= 240

    def test_non_string_reasoning_ignored(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "reasoning": 42},
            allow_fourth=False,
            universe={"#aabbcc"},
        )
        assert "reasoning" not in out

    def test_blank_reasoning_ignored(self) -> None:
        out = _validate_picks(
            {"primary": "#aabbcc", "reasoning": "   "},
            allow_fourth=False,
            universe={"#aabbcc"},
        )
        assert "reasoning" not in out
