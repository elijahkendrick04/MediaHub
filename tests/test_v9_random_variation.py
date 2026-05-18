"""V9 content-generation overhaul — verify the random/AI variation system.

The user's bug: clicking "regenerate" produced the same template every
time because the route hashed the card_id into a deterministic seed.

The fix: ``random_variation_profile`` builds a fresh multi-axis profile
on every call; ``generate()`` honours the profile end-to-end; the
regenerate route passes a fresh profile each click.

This test file asserts the new contract directly:
  - 10 random profiles produce 10 distinct variation signatures.
  - A profile passed into ``generate()`` flows through onto the brief.
  - Text-led layouts get safe palette permutations (no accent-as-primary
    contrast traps).
  - Legacy seed-based variation still produces the seeds 0..3 contract.
"""
from __future__ import annotations

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import (
    BACKGROUND_STYLES,
    ACCENT_STYLES,
    TYPOGRAPHY_PAIRS,
    COMPOSITIONS,
    PHOTO_TREATMENTS,
    CreativeBrief,
    VariationProfile,
    generate,
    random_variation_profile,
)
from mediahub.media_requirements.evaluator import EvaluationResult


def _brand():
    return BrandKit(
        profile_id="v9test",
        display_name="V9 Test SC",
        primary_colour="#0A2540",
        secondary_colour="#101820",
        accent_colour="#FFD24A",
        short_name="V9",
    )


def _eval():
    return EvaluationResult(
        content_item_id="v9-card-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=None,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _item():
    return {
        "id": "v9-card-1",
        "post_angle": "confirmed_official_pb",
        "achievement": {
            "swim_id": "v9-card-1",
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "post_angle": "confirmed_official_pb",
        },
    }


def test_random_profile_axes_use_known_vocabulary():
    """Every axis returned must come from the published vocabulary."""
    profile = random_variation_profile(angle="confirmed_official_pb")
    assert profile.background_style in BACKGROUND_STYLES
    assert profile.accent_style in ACCENT_STYLES
    assert profile.typography_pair in TYPOGRAPHY_PAIRS
    assert profile.composition in COMPOSITIONS
    assert profile.photo_treatment in PHOTO_TREATMENTS
    assert 0 <= profile.palette_role_index <= 5
    assert 0.0 <= profile.decoration_strength <= 1.0


def test_ten_random_profiles_are_distinct():
    """The user's acceptance criterion — 10 regenerations, 10 distinct
    visual signatures for the same swim."""
    seen: set[str] = set()
    avoid: list[str] = []
    for _ in range(10):
        p = random_variation_profile(
            angle="confirmed_official_pb",
            avoid_signatures=avoid,
        )
        sig = p.signature()
        assert sig not in seen, f"duplicate profile signature: {sig}"
        seen.add(sig)
        avoid.append(sig)


def test_generate_honours_variation_profile():
    """Brief should pick up the profile's family + axes verbatim."""
    profile = VariationProfile(
        layout_family="big_number_hero",
        palette_role_index=2,
        background_style="halftone",
        accent_style="ribbon",
        typography_pair="druk-inter",
        composition="left",
        photo_treatment="vignette",
        decoration_strength=0.85,
        hook_phrase="LIFETIME BEST",
        mood="electric",
    )
    brief = generate(
        _item(), _eval(), _brand(),
        profile_id="v9test", variation_profile=profile,
    )
    assert brief.layout_template == "big_number_hero"
    assert brief.background_style == "halftone"
    assert brief.accent_style == "ribbon"
    assert brief.typography_pair == "druk-inter"
    assert brief.composition == "left"
    assert brief.photo_treatment == "vignette"
    assert brief.primary_hook == "LIFETIME BEST"
    assert brief.mood == "electric"
    assert brief.decoration_strength == pytest.approx(0.85)
    assert brief.variation_signature  # non-empty


def test_text_led_layouts_avoid_accent_as_primary():
    """Text-led layouts paint white type on the primary — they break
    visually if the (often-yellow) accent colour ends up as primary."""
    # Try many random profiles; whenever text_led_recap or weekend_numbers
    # is picked, the palette_role_index must be one of (0, 1, 3) — the
    # permutations that keep primary or secondary in the primary slot.
    safe_for_text_led = {0, 1, 3}
    found_one = False
    for _ in range(200):
        p = random_variation_profile(angle="confirmed_official_pb")
        if p.layout_family in {"text_led_recap", "weekend_numbers"}:
            found_one = True
            assert p.palette_role_index in safe_for_text_led, (
                f"text-led layout got unsafe palette_role_index={p.palette_role_index}"
            )
    assert found_one, (
        "didn't sample any text-led layout in 200 picks — adjust the "
        "test or the GENERIC_FAMILIES probability distribution"
    )


def test_legacy_seed_contract_still_holds():
    """The old test_v8_variation_seed assertions must keep passing."""
    item, ev, brand = _item(), _eval(), _brand()
    briefs = [
        generate(item, ev, brand, profile_id="v9test", variation_seed=s)
        for s in (0, 1, 2, 3)
    ]
    # seed 1: same family, primary <-> secondary swap
    assert briefs[1].layout_template == briefs[0].layout_template
    assert briefs[1].palette["primary"] == briefs[0].palette["secondary"]
    assert briefs[1].palette["secondary"] == briefs[0].palette["primary"]
    # seed 2: different family
    assert briefs[2].layout_template != briefs[0].layout_template
    # seed 3: text-led / no-photo
    assert (
        "no photo" in briefs[3].image_treatment.lower()
        or "text-led" in briefs[3].image_treatment.lower()
    )


def test_brief_carries_variation_signature():
    """The brief must always produce a non-empty signature so the route
    can persist it for next-regenerate dedupe."""
    brief = generate(
        _item(), _eval(), _brand(),
        profile_id="v9test",
        variation_profile=random_variation_profile(),
    )
    assert brief.variation_signature
    parts = brief.variation_signature.split("|")
    # signature shape: layout|primary_hex|bg|accent|type|comp|photo|hook
    assert len(parts) >= 7


def test_avoid_signatures_steers_away_from_duplicates():
    """When given a recent signature, the picker should try to dodge it."""
    first = random_variation_profile(angle="confirmed_official_pb")
    target = first.signature()
    # Ask for 5 more, all avoiding `target`. None should equal it.
    avoid = [target]
    for _ in range(5):
        nxt = random_variation_profile(
            angle="confirmed_official_pb",
            avoid_signatures=avoid,
        )
        assert nxt.signature() != target, "avoid_signatures wasn't honoured"
        avoid.append(nxt.signature())
