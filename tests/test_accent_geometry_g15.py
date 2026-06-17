"""G1.5 — accent-geometry expansion pack (graphic generator sprint).

Five new accent geometries widen the style-pack catalog: ``hexagons``,
``deco_corners`` (art-deco corners), ``wave_rule``, ``spiral_flourish`` and
``glitch_divider``. Each is appended to ``style_packs.ACCENT_GEOS`` and drawn by
the accent-geometry generator as a margin-confined, brand-colour-only overlay,
and — like every other lever — mirrored verbatim into the motion renderer so a
card's video keeps its still's decoration (the still↔motion parity contract).

This suite pins, for the new batch specifically: the levers are in the
vocabulary, the catalog grew, every one renders legibility-safe /
brand-colour-only / pointer-safe / margin-confined, each carries a label +
weight (no KeyError in name()/why()/weight), the overlays are distinct and
deterministic, the role tokens are untouched, and the motion renderer executes
every new lever (with the shared wave/spiral path helpers present on both
sides). No Node and no browser: the TSX is checked as a source contract and the
Python side is pure shaping — the same shape the existing parity suites use.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion

# The G1.5 batch, with the silhouette each one must actually draw.
NEW_ACCENTS = ("hexagons", "deco_corners", "wave_rule", "spiral_flourish", "glitch_divider")


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


def _overlay(accent_geo: str, *, w: int = 1080, h: int = 1350) -> str:
    return sp.pack_overlay_html(sp.normalise_pack(accent_geo=accent_geo), width=w, height=h)


# --------------------------------------------------------------------------- #
# Vocabulary + catalog growth
# --------------------------------------------------------------------------- #


def test_new_accents_are_in_the_vocabulary():
    for a in NEW_ACCENTS:
        assert a in sp.ACCENT_GEOS, a
    # appended, never reordered — the seeded picker indexes the catalog, so a
    # reorder of the originals would change every historical pick.
    assert sp.ACCENT_GEOS[:12] == (
        "none", "corner_ticks", "side_rule", "baseline_rule", "frame", "wedge",
        "ring", "corner_blocks", "double_rule", "dot_row", "cross_ticks", "corner_arc",
    )


def test_catalog_still_clears_the_thousand_template_floor():
    # The product requirement: ≥1000 unique templates remain available; the new
    # levers only multiply the deterministic catalog further.
    assert sp.style_pack_count() > 1000
    assert sp.template_count(A.list_archetypes()) >= 1000
    # ids stay unique after the expansion (no accidental collision)
    ids = [p.id for p in sp.list_style_packs()]
    assert len(ids) == len(set(ids))


def test_each_new_accent_is_reachable_by_the_picker():
    # Every new lever appears in at least one catalog pack, so the deterministic
    # picker can actually surface it (variety reaches output).
    reachable = {p.accent_geo for p in sp.list_style_packs()}
    for a in NEW_ACCENTS:
        assert a in reachable, a


# --------------------------------------------------------------------------- #
# Each new lever: legibility-safe, brand-colour-only, pointer-safe
# --------------------------------------------------------------------------- #


def test_each_new_accent_renders_brand_only_and_pointer_safe():
    for a in NEW_ACCENTS:
        html = _overlay(a)
        assert html, a
        # absolutely-positioned, inert overlay (an accent-only pack's *sole*
        # layer is the geometry, so these must live on the geometry itself).
        assert "position:absolute" in html, a
        assert "pointer-events:none" in html, a
        # brand colour only — never a raw hex; the accent rides --mh-accent.
        assert "var(--mh-accent)" in html, a
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html), f"{a}: raw hex in overlay"


def test_each_new_accent_carries_a_label_and_weight():
    for a in NEW_ACCENTS:
        p = sp.normalise_pack(accent_geo=a)
        # name()/why()/weight read the label + weight tables — a missing entry
        # would KeyError here.
        assert p.name() and p.why()
        assert isinstance(p.weight, int) and p.weight >= 1
        assert a in sp._ACCENT_W and a in sp._ACCENT_LABEL


def test_weights_respect_the_coherence_caps():
    # No pack built on a new accent may exceed its density's coherence cap, so
    # the catalog never stacks an over-decorated card.
    for p in sp.list_style_packs():
        if p.accent_geo in NEW_ACCENTS:
            cap = 3 if p.density == "bold" else 4
            assert p.weight <= cap, p.id


def test_new_accents_draw_their_distinct_silhouettes():
    # Each lever must draw its named shape, not a generic box: the curved/
    # ornamental ones are stroked inline SVG; glitch is displaced div slivers.
    hexagons = _overlay("hexagons")
    assert "<polygon" in hexagons and "<svg" in hexagons
    deco = _overlay("deco_corners")
    assert "<path" in deco and "rotate(180deg)" in deco  # mirrored opposite corner
    wave = _overlay("wave_rule")
    assert "<path" in wave and " C " in wave  # cubic-bézier sine humps
    spiral = _overlay("spiral_flourish")
    assert "<polyline" in spiral and "rotate(180deg)" in spiral
    glitch = _overlay("glitch_divider")
    assert glitch.count("<div") == 3 and "opacity:0.7" in glitch  # torn, fading slivers
    # the five silhouettes are mutually distinct payloads → distinct pixels
    overlays = [hexagons, deco, wave, spiral, glitch]
    assert len(set(overlays)) == len(overlays)


def test_new_accents_are_deterministic_and_scale_with_canvas():
    for a in NEW_ACCENTS:
        # same pack + size → byte-identical overlay (re-renders are stable)
        assert _overlay(a) == _overlay(a)
        # a smaller canvas reshapes the geometry — corner ornaments size off
        # min(w,h); the bottom rules size off w/h directly, so both shift.
        assert _overlay(a, w=540, h=675) != _overlay(a, w=1080, h=1350)


def test_bold_density_intensifies_the_new_accents():
    # The bold tier scales geometry up (the documented 1.35× multiplier), so a
    # bold pack's overlay differs from its standard sibling.
    for a in NEW_ACCENTS:
        std = sp.pack_overlay_html(
            sp.normalise_pack(accent_geo=a, density="standard"), width=1080, height=1350
        )
        bold = sp.pack_overlay_html(
            sp.normalise_pack(accent_geo=a, density="bold"), width=1080, height=1350
        )
        assert std != bold, a


# --------------------------------------------------------------------------- #
# Still↔motion parity: every new lever is executed in the motion renderer
# --------------------------------------------------------------------------- #


def test_new_accents_are_mirrored_into_storycard():
    src = _story_src()
    # registered in the parser's accepted set…
    for a in NEW_ACCENTS:
        assert f'"{a}"' in src, f"{a} not registered/executed in StoryCard.tsx"
    # …and the shared geometry helpers exist on the motion side too, so the
    # wave and spiral match the still's maths rather than a lookalike.
    assert "packWavePath" in src and "packSpiralPoints" in src
    # the still side owns the same helpers (drift guard across the two surfaces)
    assert hasattr(sp, "_wave_path") and hasattr(sp, "_spiral_points")


def test_motion_geometry_helpers_match_the_still_shape():
    # The still's wave/spiral helpers produce a non-trivial, deterministic path
    # the motion side mirrors verbatim (same constants, same loop).
    wave = sp._wave_path(908, 29)
    assert wave.startswith("M 0 ") and wave.count(" C ") == 7  # 7 humps
    assert sp._wave_path(908, 29) == wave
    spiral = sp._spiral_points()
    assert spiral.startswith("50.0,50.0") and len(spiral.split(" ")) == 73  # 72 steps + 1
    assert sp._spiral_points() == spiral


# --------------------------------------------------------------------------- #
# Decoration only — the new levers never touch the resolved role tokens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("accent_geo", NEW_ACCENTS)
def test_new_accents_never_change_resolved_role_tokens(accent_geo):
    from mediahub.creative_brief.generator import generate
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    brand = BrandKit(
        profile_id="t",
        display_name="Test SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#FFFFFF",
        short_name="TSC",
    )
    card = {
        "id": "c1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    b = generate(card, None, brand, profile_id="t", meet_name="Open", variation_seed=0)
    b.style_pack = sp.normalise_pack(accent_geo=accent_geo).id
    with_pack = resolved_role_vars_for_brief(b, brand)
    b.style_pack = ""
    bare = resolved_role_vars_for_brief(b, brand)
    # The seven core --mh-* role tokens (text-contrast pairings + still↔motion
    # colour parity) are identical with or without the accent geometry.
    assert with_pack == bare
