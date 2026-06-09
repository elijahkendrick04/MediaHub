"""Tier B §5.4 — the LLM design-spec director (`ai_director.ai_design_spec`).

The director asks the provider for a `DesignSpec` (which archetype + emphasis +
hook fits THIS moment) and runs the response through `design_spec.normalise`, so
a hallucinated answer still yields a legal card. With no provider it returns
None and the generator falls back to the deterministic Tier A picker — never a
fabricated card. The LLM is mocked here (no network).
"""

import json

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import ai_director
from mediahub.creative_brief.design_spec import MOODS, STAT_KEYS, DesignSpec
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult


def _brand():
    return BrandKit(
        profile_id="t",
        display_name="Test SC",
        primary_colour="#0A2540",
        secondary_colour="#F2C14E",
        short_name="TSC",
    )


def _item():
    return {
        "id": "c1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }


def _ev():
    return EvaluationResult(
        content_item_id="c1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


_GOOD = json.dumps(
    {
        "archetype": "big_number_dominant",
        "colour_roles": {
            "ground": "primary",
            "surface": "surface",
            "headline": "on_primary",
            "accent": "accent",
        },
        "focal_element": "big_number",
        "crop_intent": "centered",
        "hero_stat": "pb_delta",
        "secondary_stats": ["final_time"],
        "headline_hook": "A personal best in the 200 free",
        "accent_treatment": "underline",
        "logo_lockup": "icon",
        "mood": "triumphant",
        "motion_intent": "snap_in_then_settle",
        "rationale": "A standout time is the story, so lead with the numeral.",
    }
)


def _patch_ask(monkeypatch, *, returns=None, raises=None):
    import mediahub.ai_core as core

    def _fake_ask(system, user, **kw):
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr(core, "ask", _fake_ask)


def test_director_emits_a_normalised_spec(monkeypatch):
    _patch_ask(monkeypatch, returns=_GOOD)
    spec = ai_director.ai_design_spec(
        content_item=_item(),
        brand_kit=_brand(),
        archetypes=archetypes.list_archetypes(),
        token_roles=list(archetypes.TOKEN_ROLES),
    )
    assert isinstance(spec, DesignSpec)
    assert spec.archetype == "big_number_dominant"
    assert spec.hero_stat == "pb_delta"
    assert "personal best" in spec.headline_hook.lower()


def test_director_normalises_garbage_to_a_legal_spec(monkeypatch):
    _patch_ask(monkeypatch, returns='{"archetype":"NOT_REAL","mood":"banana","hero_stat":"xyz"}')
    spec = ai_director.ai_design_spec(
        content_item=_item(),
        brand_kit=_brand(),
        archetypes=archetypes.list_archetypes(),
        token_roles=list(archetypes.TOKEN_ROLES),
    )
    assert isinstance(spec, DesignSpec)
    assert spec.archetype in archetypes.list_archetypes()  # coerced to a real archetype
    assert spec.mood in MOODS
    assert spec.hero_stat in STAT_KEYS


def test_director_returns_none_without_provider(monkeypatch):
    from mediahub.ai_core import ProviderNotConfigured

    _patch_ask(monkeypatch, raises=ProviderNotConfigured("no key"))
    spec = ai_director.ai_design_spec(
        content_item=_item(),
        brand_kit=_brand(),
        archetypes=archetypes.list_archetypes(),
        token_roles=list(archetypes.TOKEN_ROLES),
    )
    assert spec is None


def test_director_returns_none_on_unparseable_output(monkeypatch):
    _patch_ask(monkeypatch, returns="sorry, I can't do that")
    spec = ai_director.ai_design_spec(
        content_item=_item(),
        brand_kit=_brand(),
        archetypes=archetypes.list_archetypes(),
        token_roles=list(archetypes.TOKEN_ROLES),
    )
    assert spec is None


def test_generate_uses_the_director_when_v2_and_ai_on(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    _patch_ask(monkeypatch, returns=_GOOD)
    brief = gen_brief(
        _item(),
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Open",
        variation_seed=3,
        use_ai_director=True,
    )
    # the director's archetype wins over the seed-based pick
    assert brief.layout_template == "big_number_dominant"
    assert brief.ai_directed is True
    assert "personal best" in brief.primary_hook.lower()


def test_generate_falls_back_to_picker_without_provider(monkeypatch):
    from mediahub.ai_core import ProviderNotConfigured

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    _patch_ask(monkeypatch, raises=ProviderNotConfigured("no key"))
    brief = gen_brief(
        _item(),
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Open",
        variation_seed=3,
        use_ai_director=True,
    )
    # honest floor: a real v2 archetype from the deterministic picker
    assert brief.layout_template in archetypes.list_archetypes()


def test_director_hero_stat_choice_is_honoured_when_measured(monkeypatch):
    """The spec's hero_stat names a fact; the brief leads the emphasis slot
    with it ONLY when the detectors actually measured that fact."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    _patch_ask(monkeypatch, returns=_GOOD)  # hero_stat: "pb_delta"
    item = _item()
    item["achievement"]["raw_facts"] = {"drop_seconds": 1.86}
    brief = gen_brief(
        item,
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Open",
        variation_seed=3,
        use_ai_director=True,
    )
    assert brief.text_layers.get("hero_stat") == "−1.86s on PB"

    # the named fact was never measured → no fabricated stat line
    brief2 = gen_brief(
        _item(),
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Open",
        variation_seed=3,
        use_ai_director=True,
    )
    assert brief2.text_layers.get("hero_stat", "") == ""
