"""F9 (Canva gap analysis) — medal chrome: specular ramps + bevels.

Canva medal templates use metallic chrome so a gold card visibly outranks a
silver one. This adds a deterministic 7-stop specular ramp derived from the
resolved medal tint, gated on the ramp's darkest stop vs the ground, painted as
a gradient-clipped numeral (big-numeral layouts) or a bevelled chip (medal
spotlight). Non-medal cards are byte-identical.
"""

from __future__ import annotations

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import medal_chrome as mc
from mediahub.graphic_renderer.render import resolved_role_vars_for_brief


BRAND = BrandKit(
    profile_id="p",
    display_name="Test SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#E8563F",
    short_name="TSC",
)


def test_ramp_is_deterministic_and_seven_stops():
    a = mc.medal_ramp_stops("#FFD24A")
    b = mc.medal_ramp_stops("#FFD24A")
    assert a == b
    assert len(a) == 7
    # dark → bright → dark (specular): the mid stop is the lightest.
    assert a[3] == mc.medal_ramp_stops("#FFD24A")[3]
    assert a[0] == a[-1] == mc.darkest_ramp_stop("#FFD24A")


def test_ramp_css_is_a_linear_gradient_of_the_tint():
    css = mc.medal_ramp_css("#FFD24A")
    assert css.startswith("linear-gradient(135deg,")
    assert css.count("%") == 7  # seven positioned stops


def test_darkest_stop_is_darker_than_the_tint():
    def lum(h):
        h = h.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return r + g + b

    assert lum(mc.darkest_ramp_stop("#FFD24A")) < lum("#FFD24A")


def _medal_brief(seed=1):
    b = generate(
        {
            "id": "swim-medal",
            "post_angle": "podium_finish",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200m Freestyle",
                "result_time": "2:08.41",
                "place": "1st",
            },
        },
        None,
        BRAND,
        profile_id="p",
        variation_seed=seed,
    )
    return b


def test_resolver_emits_ramp_for_a_gold_card():
    brief = _medal_brief()
    roles = resolved_role_vars_for_brief(brief, BRAND)
    # gold accent chosen + chip ramp emitted (accent gate passed on this ground).
    assert roles.get("--mh-accent") == "#FFD24A"
    assert roles.get("--mh-medal-ramp", "").startswith("linear-gradient")


def test_numeral_ramp_gated_on_darkest_stop_vs_ground():
    from mediahub.quality.compliance import is_legible

    brief = _medal_brief()
    roles = resolved_role_vars_for_brief(brief, BRAND)
    ground = roles["--mh-primary"]
    numeral = roles.get("--mh-medal-numeral-ramp", "")
    # The numeral twin appears iff the darkest stop clears the relaxed gate.
    gate = is_legible(mc.darkest_ramp_stop("#FFD24A"), ground, min_lc=45.0)
    assert bool(numeral) == bool(gate)


def test_resolver_emits_no_ramp_for_a_pb_card():
    b = generate(
        {
            "id": "swim-pb",
            "post_angle": "confirmed_official_pb",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200m Freestyle",
                "result_time": "2:08.41",
            },
        },
        None,
        BRAND,
        profile_id="p",
    )
    roles = resolved_role_vars_for_brief(b, BRAND)
    assert "--mh-medal-ramp" not in roles


def test_numeral_and_chip_css_consume_the_ramp_var():
    num = mc.medal_numeral_css(".bn__result")
    assert "var(--mh-medal-ramp)" in num
    assert "background-clip: text" in num and "transparent" in num
    chip = mc.medal_chip_css(".cm__result")
    assert "var(--mh-medal-ramp)" in chip
    assert "inset 0 1px 0" in chip  # bevel highlight


def test_selector_map_covers_only_big_numeral_and_spotlight():
    from mediahub.graphic_renderer.render import _MEDAL_CHROME_SELECTORS

    assert set(_MEDAL_CHROME_SELECTORS) == {
        "big_number_dominant",
        "cornerstone_numeral",
        "centered_medal_spotlight",
    }


def test_motion_props_forward_the_ramp_for_a_medal_card():
    from mediahub.visual import motion

    brief = _medal_brief().to_dict()
    props = motion._card_to_props(
        {
            "id": "swim-medal",
            "swim_id": "swim-medal",
            "achievement": {"swimmer_name": "Eira", "place": "1st"},
        },
        brief=brief,
        brand_kit=BRAND,
    )
    assert props.get("roleMedalRamp", "").startswith("linear-gradient")


def test_motion_props_no_ramp_for_a_non_medal_card():
    from mediahub.visual import motion

    props = motion._card_to_props(
        {"id": "swim-1", "swim_id": "swim-1", "achievement": {"swimmer_name": "Eira"}},
        brief={"style_pack": ""},
        brand_kit=BRAND,
    )
    assert "roleMedalRamp" not in props


def test_tsx_paints_medal_chrome():
    from pathlib import Path

    src = (
        Path(mc.__file__).parents[1] / "remotion" / "src" / "compositions" / "StoryCard.tsx"
    ).read_text()
    assert "roleMedalRamp" in src
    assert "medalNumeralStyle" in src
    assert "WebkitBackgroundClip" in src
