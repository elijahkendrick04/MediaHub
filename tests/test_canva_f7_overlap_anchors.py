"""F7 (Canva gap analysis) — declarative overlap anchors + overlap accent lever.

Canva output reads rich because a foreground accent crosses a midground edge (a
badge half-off a photo, a tab over a panel corner). MediaHub marks overlap-safe
edges with ``mh-anchor--*`` classes on ~8 archetypes and drops a seeded
badge/tab/rule/tape into one anchor via the ``{{OVERLAP_ACCENT}}`` slot. These
tests pin the deterministic seeded pick, the brand-locked markup, byte-identity
when the lever is absent, and the still↔motion prop mirror.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.graphic_renderer import style_packs as sp

_V2 = Path(sp.__file__).parent / "layouts" / "v2"
_ANCHORED = [
    "broadcast_scorebug",
    "full_bleed_photo_lower_third",
    "photo_passepartout",
    "poster_name_behind",
    "spotlight_disc",
    "full_height_portrait_split",
    "stat_stack_sidebar",
    "index_card",
]


def test_overlap_accent_is_deterministic_per_key():
    a = sp.overlap_accent_for("swim-1")
    b = sp.overlap_accent_for("swim-1")
    assert a == b and a is not None
    shape, rot = a
    assert shape in sp.OVERLAP_SHAPES
    assert rot in (-4, -2, 2, 4)


def test_overlap_accent_axis_varies_across_keys():
    picks = {sp.overlap_accent_for(f"swim-{i}") for i in range(24)}
    # more than one distinct (shape, rotation) across a content pack
    assert len({p[0] for p in picks}) >= 2


def test_overlap_accent_independent_of_pack_salt():
    # salt='overlap' differs from salt='pack', so the two axes are decorrelated.
    assert sp._seed_for("swim-1", salt="overlap") != sp._seed_for("swim-1", salt="pack")


def test_missing_key_yields_no_accent():
    assert sp.overlap_accent_for("") is None
    assert sp.overlap_accent_for(None) is None
    assert sp.overlap_accent_for_card("", width=1080, height=1350) == ""


@pytest.mark.parametrize("shape", sp.OVERLAP_SHAPES)
def test_accent_html_is_brand_locked(shape):
    html = sp.overlap_accent_html(shape, -4, width=1080, height=1350)
    assert html.startswith("<div") and "translate(-50%,-50%)" in html
    # Only role tokens — never a decorative hex fill (shadows use neutral alphas).
    assert "var(--mh-accent)" in html
    lowered = html.lower()
    assert "#f" not in lowered and "#0" not in lowered  # no hardcoded hex fills


def test_unknown_shape_injects_nothing():
    assert sp.overlap_accent_html("sticker", 0, width=1080, height=1350) == ""


def test_anchored_layouts_declare_the_slot():
    for name in _ANCHORED:
        raw = (_V2 / f"{name}.html").read_text(encoding="utf-8")
        assert "mh-anchor" in raw, f"{name} missing anchor class"
        assert "{{OVERLAP_ACCENT}}" in raw, f"{name} missing overlap slot"


def test_components_css_defines_the_anchor_utilities():
    css = (Path(sp.__file__).parent / "layouts" / "_components.css").read_text()
    for cls in ("mh-anchor--panel-tr", "mh-anchor--photo-tr", "mh-anchor"):
        assert cls in css


def test_motion_props_mirror_the_overlap_accent(monkeypatch):
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate
    from mediahub.visual import motion

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brand = BrandKit(
        profile_id="p",
        display_name="P",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#E8563F",
        short_name="P",
    )
    b = generate(
        {
            "id": "swim-9",
            "post_angle": "individual_pb",
            "achievement": {
                "swimmer_name": "Eira",
                "event_name": "200 Free",
                "result_time": "2:08.41",
            },
        },
        None,
        brand,
        profile_id="p",
        variation_seed=5,
    )
    bd = b.to_dict()
    if not bd.get("style_pack"):
        pytest.skip("no pack picked for this seed")
    props = motion._card_to_props(
        {"id": "swim-9", "swim_id": "swim-9", "achievement": {"swimmer_name": "Eira"}},
        brief=bd,
        brand_kit=brand,
    )
    expected = motion._overlap_accent_for_brief(bd)
    assert props.get("overlapAccent", "") == expected
    if expected:
        assert ":" in expected  # "shape:rotation"


def test_bare_pack_card_gets_no_motion_overlap():
    from mediahub.visual import motion

    assert (
        motion._overlap_accent_for_brief({"style_pack": "flat-none-none-standard", "id": "x"}) == ""
    )
    assert motion._overlap_accent_for_brief({"style_pack": "", "id": "x"}) == ""
    assert motion._overlap_accent_for_brief(None) == ""


def test_tsx_paints_the_overlap_accent():
    src = (
        Path(sp.__file__).parents[1] / "remotion" / "src" / "compositions" / "StoryCard.tsx"
    ).read_text()
    assert "packOverlapAccent" in src
    assert "overlapAccent" in src
    for shape in sp.OVERLAP_SHAPES:
        assert f'"{shape}"' in src, f"motion side missing shape {shape}"
