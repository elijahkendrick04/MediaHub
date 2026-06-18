"""P6.1 — the format transformer (turn_into/transform.py).

Pins the Magic-Switch behaviour: re-target an approved design to a new format
by re-laying-out the composition for the new aspect while preserving the
approved copy / palette / photo. Covers the deterministic floor, the AI-director
path (mocked), the blank-start escape hatch, and the no-mutation guarantee.
"""

from __future__ import annotations

from unittest import mock

import pytest

from mediahub.club_platform import format_catalog as fc
from mediahub.creative_brief.generator import CreativeBrief
from mediahub.graphic_renderer import archetypes as A
from mediahub.turn_into import transform_design, blank_brief_for_format
from mediahub.turn_into.transform import TransformResult


def _brief(layout="split_diagonal_hero", fmt_priority=None) -> CreativeBrief:
    return CreativeBrief(
        id="cb_src",
        content_item_id="swim_42",
        profile_id="p1",
        achievement_summary="New PB",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template=layout,
        inspiration_pattern_id="x",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="b",
        sponsor_instructions=None,
        sourced_asset_ids=["asset-1"],
        safety_notes=[],
        why_this_design="because",
        text_layers={"athlete_full_name": "Alice Lee", "event_name": "100 Free", "result_value": "57.95"},
        palette={"primary": "#A30D2D", "secondary": "#000000", "accent": "#FFFFFF"},
        format_priority=list(fmt_priority or ["story", "feed_portrait"]),
    )


# ---------------------------------------------------------------------------
# Core re-target behaviour
# ---------------------------------------------------------------------------


def test_returns_transform_result_with_target_format():
    r = transform_design(source_brief=_brief(), target_format="youtube_thumbnail")
    assert isinstance(r, TransformResult)
    assert r.format.slug == "youtube_thumbnail"
    assert r.brief.format_priority[0] == r.format.render_name


def test_preserves_approved_creative_decisions():
    src = _brief()
    r = transform_design(source_brief=src, target_format="ig_square")
    assert r.brief.palette == src.palette
    assert r.brief.primary_hook == src.primary_hook
    assert r.brief.text_layers == src.text_layers
    assert r.brief.sourced_asset_ids == src.sourced_asset_ids
    assert r.brief.confidence_label == src.confidence_label


def test_relayouts_for_a_mismatched_aspect():
    # split_diagonal_hero suits tall canvases, not a 16:9 thumbnail.
    r = transform_design(source_brief=_brief("split_diagonal_hero"), target_format="youtube_thumbnail")
    assert r.target_archetype != r.source_archetype
    assert r.target_archetype in fc.preferred_archetypes(r.format)


def test_keeps_layout_when_it_already_suits_the_aspect():
    # A tall source archetype re-targeted to another tall format is kept as-is.
    tall_arch = fc.ARCHETYPES_BY_BUCKET["tall"][0]
    r = transform_design(source_brief=_brief(tall_arch), target_format="pinterest_pin")
    assert r.format.bucket == "tall"
    assert r.target_archetype == tall_arch


def test_deterministic_and_stable():
    r1 = transform_design(source_brief=_brief(), target_format="ig_square")
    r2 = transform_design(source_brief=_brief(), target_format="ig_square")
    assert r1.target_archetype == r2.target_archetype


def test_pick_is_a_function_of_card_id():
    # The deterministic floor seeds on the card id: same card → same layout,
    # and a different card still lands on a valid (square-suitable) archetype.
    b = _brief()
    b.content_item_id = "swim_99"
    rb = transform_design(source_brief=b, target_format="ig_square")
    assert rb.target_archetype in fc.preferred_archetypes(rb.format)
    # re-running the same card reproduces the same pick
    rb2 = transform_design(source_brief=b, target_format="ig_square")
    assert rb.target_archetype == rb2.target_archetype


def test_source_brief_is_not_mutated():
    src = _brief("split_diagonal_hero", fmt_priority=["story"])
    transform_design(source_brief=src, target_format="youtube_thumbnail")
    assert src.layout_template == "split_diagonal_hero"
    assert src.format_priority == ["story"]


def test_accepts_a_brief_dict():
    r = transform_design(source_brief=_brief().to_dict(), target_format="ig_square")
    assert isinstance(r.brief, CreativeBrief)
    assert r.format.slug == "ig_square"


def test_accepts_a_formatspec_object():
    spec = fc.format_for("ig_story")
    r = transform_design(source_brief=_brief(), target_format=spec)
    assert r.format is spec


def test_custom_format_target():
    spec = fc.custom_format(1200, 1500, slug="mypin")
    r = transform_design(source_brief=_brief(), target_format=spec)
    assert r.format.size == (1200, 1500)
    assert r.target_archetype in fc.preferred_archetypes(spec)


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        transform_design(source_brief=_brief(), target_format="nope_nope")


def test_bad_source_raises():
    with pytest.raises(ValueError):
        transform_design(source_brief=12345, target_format="ig_story")


def test_rationale_is_explainable():
    r = transform_design(source_brief=_brief("split_diagonal_hero"), target_format="youtube_thumbnail")
    assert "YouTube thumbnail" in r.rationale
    assert r.brief.why_this_design == r.rationale


# ---------------------------------------------------------------------------
# AI-director path (mocked) + deterministic floor
# ---------------------------------------------------------------------------


def test_ai_director_choice_is_applied_when_available():
    # Mock the director to return a spec selecting a specific (suitable) archetype.
    wide = fc.preferred_archetypes(fc.format_for("youtube_thumbnail"))
    chosen = wide[-1]
    fake_spec = mock.Mock()
    fake_spec.archetype = chosen
    with mock.patch(
        "mediahub.creative_brief.ai_director.ai_design_spec", return_value=fake_spec
    ) as m:
        r = transform_design(
            source_brief=_brief("split_diagonal_hero"),
            target_format="youtube_thumbnail",
            use_ai_director=True,
        )
    assert m.called
    assert r.ai_directed is True
    assert r.target_archetype == chosen
    assert r.brief.ai_directed is True


def test_falls_back_to_deterministic_when_director_returns_none():
    with mock.patch(
        "mediahub.creative_brief.ai_director.ai_design_spec", return_value=None
    ):
        r = transform_design(
            source_brief=_brief("split_diagonal_hero"),
            target_format="youtube_thumbnail",
            use_ai_director=True,
        )
    assert r.ai_directed is False
    assert r.target_archetype in fc.preferred_archetypes(r.format)


def test_no_director_call_when_layout_already_suits():
    tall_arch = fc.ARCHETYPES_BY_BUCKET["tall"][0]
    with mock.patch(
        "mediahub.creative_brief.ai_director.ai_design_spec"
    ) as m:
        transform_design(
            source_brief=_brief(tall_arch),
            target_format="ig_story",
            use_ai_director=True,
        )
    # The source already suits a tall canvas → no need to re-direct.
    assert not m.called


# ---------------------------------------------------------------------------
# Blank-start escape hatch
# ---------------------------------------------------------------------------


class _Brand:
    display_name = "Test Swim Club"
    short_name = "TSC"
    primary_colour = "#0E5BFF"
    secondary_colour = "#101820"
    accent_colour = "#F4D58D"
    tone = "warm-club"
    logo_path = None


def test_blank_brief_seeds_from_brand_tokens():
    b = blank_brief_for_format("poster", _Brand(), headline="OPEN DAY")
    assert b.palette["primary"] == "#0E5BFF"
    assert b.palette["accent"] == "#F4D58D"
    assert b.text_layers["club_full"] == "Test Swim Club"
    assert b.primary_hook == "OPEN DAY"
    assert b.layout_template in fc.preferred_archetypes(fc.format_for("poster"))
    assert b.format_priority == [fc.format_for("poster").render_name]


def test_blank_brief_tolerates_no_brand_kit():
    b = blank_brief_for_format("ig_story", None)
    assert b.palette["primary"]  # a sensible default, not a crash
    assert b.layout_template in A.list_archetypes()


def test_blank_brief_unknown_format_raises():
    with pytest.raises(ValueError):
        blank_brief_for_format("nope", _Brand())
