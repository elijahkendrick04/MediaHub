"""render-banding-dither — motion side: still<->motion parity + revision bumps.

A card whose still opted into the ordered-dither debanding overlay
(``background_style == "dither"``) carries a ``dither`` prop into its motion
render, so the video debands the same big fill the approved still did. Every
other card's props stay byte-identical (fold-only-when-present). The composition
revisions are bumped by hand to document the one unavoidable motion-cache bust
that adding ``Dither.tsx`` + editing ``MeetReel`` causes via
``renderer_generation()``.
"""

from __future__ import annotations

from mediahub.visual import motion


def test_dither_for_brief_reads_the_standalone_token():
    assert motion._dither_for_brief({"background_style": "dither"}) is True
    assert motion._dither_for_brief({"background_style": "DITHER"}) is True


def test_dither_for_brief_is_false_without_the_token():
    for style in ("", "water", "gradient_mesh", "gradient_mesh:radial", "halftone"):
        assert motion._dither_for_brief({"background_style": style}) is False
    assert motion._dither_for_brief(None) is False
    assert motion._dither_for_brief({}) is False


def test_dither_for_brief_does_not_collide_with_mesh_mode():
    # A mesh ":mode" suffix must never be misread as a dither opt-in.
    assert motion._dither_for_brief({"background_style": "gradient_mesh:conic"}) is False


_CARD = {
    "achievement": {
        "swimmer_name": "Alex Reed",
        "event_name": "100 Free",
        "result_time": "52.30",
        "achievement_label": "PB",
    },
}


def test_card_props_carry_dither_when_the_still_opted_in():
    props = motion._card_to_props(
        _CARD,
        variation_seed=1,
        brief={"background_style": "dither"},
        brand_kit=None,
    )
    assert props.get("dither") is True


def test_card_props_omit_dither_by_default():
    props = motion._card_to_props(
        _CARD,
        variation_seed=1,
        brief={"background_style": ""},
        brand_kit=None,
    )
    assert "dither" not in props, "opted-out cards keep a byte-identical prop dict"


def test_composition_revisions_bumped_for_dither():
    assert int(motion.STORY_COMPOSITION_REVISION) >= 8
    assert int(motion.REEL_COMPOSITION_REVISION) >= 11
