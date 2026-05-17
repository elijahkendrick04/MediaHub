"""Tests for creative_brief.generator — combines achievement + brand + evaluation
+ inspiration pattern into a CreativeBrief the renderer can consume.
"""
from __future__ import annotations

from unittest import mock

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import CreativeBrief, generate
from mediahub.creative_brief import generator as gen_mod
from mediahub.media_ai.llm import ClaudeUnavailableError
from mediahub.media_requirements.evaluator import EvaluationResult


def _eval(layout="individual_hero", confidence_label="NEW PB", tier="high"):
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier=tier,
        confidence_label=confidence_label,
        explain="ok",
    )


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def test_generate_basic_brief_pb():
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    brief = generate(item, _eval(), _brand(), profile_id="test", meet_name="National Champs", venue_name="Ponds Forge")
    assert isinstance(brief, CreativeBrief)
    assert brief.id
    assert brief.confidence_label == "NEW PB"
    assert brief.layout_template
    # Athlete + result must propagate into text layers
    assert brief.text_layers["athlete_full_name"] == "Eira Hughes"
    assert brief.text_layers["athlete_surname"] == "Hughes"
    assert brief.text_layers["athlete_first_name"] == "Eira"
    assert brief.text_layers["event_name"] == "200m Freestyle"
    assert brief.text_layers["result_value"] == "2:08.41"
    assert brief.text_layers["meet_name"] == "National Champs"
    # Palette wired
    assert brief.palette["primary"] == "#0E5BFF"
    # Format priority is non-empty (variants will iterate over it)
    assert isinstance(brief.format_priority, list) and len(brief.format_priority) >= 1
    # Why-this-design explanation must be human readable
    assert brief.why_this_design and len(brief.why_this_design) > 10


def test_generate_medal_uses_hype_tone():
    item = {
        "id": "ci-2",
        "post_angle": "medal_gold",
        "achievement": {
            "swimmer_name": "Owen Davies",
            "event_name": "100m Butterfly",
            "result_time": "55.12",
            "place": 1,
        },
    }
    brief = generate(item, _eval(layout="medal_card", confidence_label="GOLD"), _brand(), profile_id="test")
    assert brief.tone == "hype"
    assert brief.text_layers["place"] == "1"
    assert "GOLD" in brief.confidence_label


def test_generate_serializable():
    item = {
        "id": "ci-3",
        "post_angle": "weekend_recap",
        "achievement": {},
    }
    brief = generate(item, _eval(layout="weekend_in_numbers", confidence_label="WEEKEND"), _brand(), profile_id="test")
    d = brief.to_dict()
    assert d["id"] == brief.id
    assert isinstance(d["text_layers"], dict)
    assert isinstance(d["palette"], dict)
    assert "warm_club" == brief.tone


# ---------------------------------------------------------------------------
# _generate_why_this_design — LLM failures must map to the heuristic fallback,
# never propagate up and 500 the /create-graphic endpoint.
# ---------------------------------------------------------------------------

def test_why_this_design_falls_back_when_llm_unavailable():
    """If the LLM raises ClaudeUnavailableError, the brief still gets a
    human-readable why_this_design string built from the heuristic parts."""
    item = {
        "id": "ci-llm-down",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    # Force the _llm_available gate open so we exercise the try/except wrap.
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.generate",
            side_effect=ClaudeUnavailableError("no provider"),
        ):
            brief = generate(item, _eval(), _brand(), profile_id="test")
    # Contract: never raise; always produce a non-empty rationale string.
    assert isinstance(brief.why_this_design, str)
    assert len(brief.why_this_design) > 10
    # Heuristic fallback mentions the chosen pattern label.
    assert "Pattern" in brief.why_this_design


def test_why_this_design_falls_back_on_generic_exception():
    """Any non-ClaudeUnavailableError exception from the LLM call also maps
    to the heuristic fallback — never propagates."""
    item = {
        "id": "ci-llm-boom",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Owen Davies",
            "event_name": "100m Butterfly",
            "result_time": "55.12",
        },
    }
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.generate",
            side_effect=RuntimeError("transport error"),
        ):
            brief = generate(item, _eval(), _brand(), profile_id="test")
    assert isinstance(brief.why_this_design, str)
    assert len(brief.why_this_design) > 10
