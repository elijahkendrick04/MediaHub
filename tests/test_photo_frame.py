"""E4 (Canva gap analysis) — the shaped photo-frame lever.

Covers the whole `photo_frame_shape` axis end to end:

  * the pure shape maths (`graphic_renderer.photo_frame`): deterministic seeded
    blob radii, the fixed arch curve, the seeded torn-edge filter params, and
    the colourless SVG def;
  * the renderer wiring (`render._photo_frame_shape_assets`): the three windowed
    archetypes get shaped CSS + the offset accent echo, every other archetype /
    ``rect`` / the lever absent emits nothing (byte-identical), all colour via
    the resolved ``--mh-*`` role tokens (brand-lock + mono-safety);
  * the design-spec contract (`design_spec`): the closed vocabulary, normalise,
    to_dict, and JSON-schema round-trips;
  * still↔motion parity (`visual.motion`): the exact seeded geometry the still
    painted is forwarded, and rect / other archetypes keep a byte-identical prop
    dict.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from mediahub.creative_brief import design_spec as ds
from mediahub.graphic_renderer import photo_frame as pf
from mediahub.graphic_renderer import render as R


# --------------------------------------------------------------------------- #
# Pure shape maths
# --------------------------------------------------------------------------- #


def test_vocabulary_parity_with_design_spec():
    # The renderer's shape list and the director's closed vocabulary must match
    # exactly, or the director could request a shape the renderer can't run.
    assert pf.PHOTO_FRAME_SHAPES == ds.PHOTO_FRAME_SHAPES
    assert ds.DEFAULT_PHOTO_FRAME_SHAPE == "rect"
    assert "rect" in pf.PHOTO_FRAME_SHAPES


def test_arch_radius_is_fixed_and_seedless():
    a = pf.frame_radius("arch", "card-1")
    b = pf.frame_radius("arch", "totally-different-card")
    assert a == b  # arch is the same clean curve for every card
    assert a == "50% 50% 0 0 / 34% 34% 0 0"


def test_blob_radius_is_deterministic_and_in_range():
    key = "swim-42|photo_passepartout"
    r1 = pf.frame_radius("blob", key)
    r2 = pf.frame_radius("blob", key)
    assert r1 == r2  # same key → identical silhouette (re-render stable)
    assert pf.frame_radius("blob", "swim-99|photo_passepartout") != r1  # spreads
    # 8 percentage values, all jittered inside 35–65%.
    vals = [int(x) for x in re.findall(r"(\d+)%", r1)]
    assert len(vals) == 8
    assert all(35 <= v <= 65 for v in vals)
    assert " / " in r1  # elliptical horizontal / vertical split


def test_frame_radius_empty_for_torn_and_rect():
    assert pf.frame_radius("torn_edge", "k") == ""
    assert pf.frame_radius("rect", "k") == ""
    assert pf.frame_radius("", "k") == ""


def test_torn_params_deterministic_and_in_range():
    key = "swim-7|spotlight_disc"
    p1 = pf.torn_params(key)
    p2 = pf.torn_params(key)
    assert p1 == p2
    freq, scale, seed = p1
    assert 0.028 <= freq <= 0.034
    assert 12.0 <= scale <= 18.0
    assert 0 <= seed < 1000
    assert pf.torn_params("swim-8|spotlight_disc") != p1


def test_torn_filter_svg_is_colourless_and_carries_seed():
    key = "swim-3|full_height_portrait_split"
    svg = pf.torn_filter_svg(key)
    freq, scale, seed = pf.torn_params(key)
    assert f'id="{pf.TORN_FILTER_ID}"' in svg
    assert "feTurbulence" in svg and "feDisplacementMap" in svg
    assert f'baseFrequency="{freq}"' in svg
    assert f'scale="{scale}"' in svg
    assert f'seed="{seed}"' in svg
    # A torn edge displaces, it never floods a colour — no brand colour leaks in.
    assert "flood-color" not in svg
    assert "#" not in svg


# --------------------------------------------------------------------------- #
# Renderer wiring — CSS assets
# --------------------------------------------------------------------------- #


class _Brief:
    def __init__(self, shape, cid="swim-1", surname="HUGHES"):
        self.photo_frame_shape = shape
        self.content_item_id = cid
        self.id = ""
        self.text_layers = {"athlete_surname": surname}


_WINDOWED = ("photo_passepartout", "spotlight_disc", "full_height_portrait_split")


def test_rect_and_absent_emit_nothing():
    for shape in ("rect", "", "nonsense"):
        for arch in _WINDOWED:
            css, defs = R._photo_frame_shape_assets(_Brief(shape), arch, 1080, 1350)
            assert css == "" and defs == "", (shape, arch)


def test_non_windowed_archetype_emits_nothing():
    for arch in ("big_number_dominant", "magazine_cover", "ticker_strip"):
        css, defs = R._photo_frame_shape_assets(_Brief("arch"), arch, 1080, 1350)
        assert css == "" and defs == ""


def test_shape_css_is_brand_locked_and_balanced():
    for shape in ("arch", "blob", "torn_edge"):
        for arch in _WINDOWED:
            css, defs = R._photo_frame_shape_assets(_Brief(shape), arch, 1080, 1350)
            assert css, (shape, arch)
            # Balanced braces (guards the f-string / plain-string brace hazard).
            assert css.count("{") == css.count("}"), (shape, arch, css)
            # Colour only via resolved role tokens — never a hardcoded hex.
            assert "var(--mh-accent)" in css
            assert "var(--mh-surface)" in css
            assert not re.search(r"#[0-9A-Fa-f]{3,6}\b", css), (shape, arch)
            # The offset accent echo is always paired with a non-rect shape.
            assert "::after" in css and "translate(" in css
            # torn injects the filter def like the duotone path; radius shapes don't.
            if shape == "torn_edge":
                assert defs and pf.TORN_FILTER_ID in defs
                assert f"url(#{pf.TORN_FILTER_ID})" in css
            else:
                assert defs == ""
                assert "border-radius:" in css


def test_shape_defines_no_new_brand_colour_token():
    # E4 introduces NO new ``--mh-*`` custom property — it only *consumes*
    # existing role tokens (``var(--mh-accent)`` / ``var(--mh-surface)``). So
    # mono mode's role remap + global grayscale already covers it with zero
    # additions to ``sprint_hooks/mono_mode._DERIVED_DECL_RE``; the shape fills
    # follow the tokens down to grey with the rest of the card.
    for shape in ("arch", "blob", "torn_edge"):
        css, _ = R._photo_frame_shape_assets(_Brief(shape), "photo_passepartout", 1080, 1350)
        # No ``--mh-foo:`` *definition* (a colon after the token) anywhere.
        assert not re.search(r"--mh-[\w-]+\s*:", css), (shape, css)


def test_torn_filter_composes_at_window_level_not_the_image():
    # The torn filter rides the WINDOW element so it composes over any photo
    # grade already on the <img>; it must not clobber the img's own filter slot.
    css, _ = R._photo_frame_shape_assets(_Brief("torn_edge"), "photo_passepartout", 1080, 1350)
    assert ".pp .pp__window { " in css
    assert f"filter: url(#{pf.TORN_FILTER_ID})" in css
    assert ".pp__window img { filter:" not in css


def test_selectors_are_root_prefixed_for_specificity():
    # Rules must out-specify the layout's own window rules (they're injected
    # ahead of the layout <style>), so each carries the archetype root class.
    css, _ = R._photo_frame_shape_assets(_Brief("arch"), "spotlight_disc", 1080, 1350)
    assert ".di .di__disc" in css
    assert ".di__disc {" not in css.replace(".di .di__disc {", "")


# --------------------------------------------------------------------------- #
# Byte-identical HTML (render-diff on the lever) via the studio harness
# --------------------------------------------------------------------------- #


def _capture_html(archetype, shape, monkeypatch):
    from mediahub.web import design_editor as DE

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    params = DE.coerce_params(
        {
            "archetype": archetype,
            "format": "feed_portrait",
            "full": True,
            "text": dict(DE.DEFAULT_TEXT),
        }
    )
    brief = DE.build_brief_from_params(params)
    if shape is not None:
        brief.photo_frame_shape = shape
    kit = DE.brand_kit_for_params(params)
    cap = {}

    def _fake_png(html, output_path, size, **kw):
        cap["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    with tempfile.TemporaryDirectory() as d:
        R.render_brief(
            brief,
            output_dir=d,
            size=params.size,
            format_name=params.format_id,
            brand_kit=kit,
            quality=params.render_quality,
        )
    return cap["html"]


def test_rect_html_is_byte_identical_to_absent(monkeypatch):
    for arch in _WINDOWED:
        base = _capture_html(arch, None, monkeypatch)
        rect = _capture_html(arch, "rect", monkeypatch)
        assert base == rect, arch


def test_shaped_html_differs_and_injects_assets(monkeypatch):
    for arch in _WINDOWED:
        base = _capture_html(arch, None, monkeypatch)
        for shape in ("arch", "blob", "torn_edge"):
            shaped = _capture_html(arch, shape, monkeypatch)
            assert shaped != base, (arch, shape)
            assert "E4 photo frame shape" in shaped
            if shape == "torn_edge":
                assert pf.TORN_FILTER_ID in shaped


# --------------------------------------------------------------------------- #
# Design-spec contract
# --------------------------------------------------------------------------- #


def _spec(raw):
    return ds.normalise(raw, archetypes=["photo_passepartout"], token_roles=["primary", "accent"])


def test_normalise_coerces_and_defaults():
    assert _spec({"photo_frame_shape": "blob"}).photo_frame_shape == "blob"
    assert _spec({"photo_frame_shape": "hexagon"}).photo_frame_shape == "rect"  # unknown → default
    assert _spec({}).photo_frame_shape == "rect"  # absent → default


def test_to_dict_and_schema_round_trip():
    d = _spec({"photo_frame_shape": "torn_edge"}).to_dict()
    assert d["photo_frame_shape"] == "torn_edge"
    schema = ds.design_spec_json_schema(archetypes=["photo_passepartout"], token_roles=["primary"])
    assert "photo_frame_shape" in schema["properties"]
    assert schema["properties"]["photo_frame_shape"]["enum"] == list(ds.PHOTO_FRAME_SHAPES)
    assert "photo_frame_shape" in schema["required"]


def test_apply_design_spec_carries_shape():
    from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec

    brief = CreativeBrief(
        id="b",
        content_item_id="c",
        profile_id="p",
        achievement_summary="",
        objective="",
        primary_hook="",
        confidence_label="",
        tone="",
        layout_template="photo_passepartout",
        inspiration_pattern_id="",
        image_treatment="",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={},
        palette={},
        format_priority=[],
    )
    spec = _spec({"photo_frame_shape": "arch", "archetype": "photo_passepartout"})
    apply_design_spec(brief, spec)
    assert brief.photo_frame_shape == "arch"


# --------------------------------------------------------------------------- #
# Still ↔ motion parity
# --------------------------------------------------------------------------- #


def test_motion_mirror_forwards_exact_geometry():
    from mediahub.visual import motion

    # arch: forwards the token + the still's exact radius string.
    b = {
        "layout_template": "photo_passepartout",
        "photo_frame_shape": "arch",
        "content_item_id": "swim-5",
    }
    props = motion._photo_frame_shape_mirror_props(b)
    key = R._photo_frame_shape_card_key(_Brief("arch", cid="swim-5"), "photo_passepartout")
    assert props["frameShape"] == "arch"
    assert props["frameRadius"] == pf.frame_radius("arch", key)

    # blob: the seeded radius must match the still's for the same card key.
    b2 = {
        "layout_template": "spotlight_disc",
        "photo_frame_shape": "blob",
        "content_item_id": "swim-5",
    }
    props2 = motion._photo_frame_shape_mirror_props(b2)
    key2 = R._photo_frame_shape_card_key(_Brief("blob", cid="swim-5"), "spotlight_disc")
    assert props2["frameRadius"] == pf.frame_radius("blob", key2)

    # torn: the three filter numbers must match the still's seeded params.
    b3 = {
        "layout_template": "full_height_portrait_split",
        "photo_frame_shape": "torn_edge",
        "content_item_id": "swim-5",
    }
    props3 = motion._photo_frame_shape_mirror_props(b3)
    key3 = R._photo_frame_shape_card_key(
        _Brief("torn_edge", cid="swim-5"), "full_height_portrait_split"
    )
    freq, scale, seed = pf.torn_params(key3)
    assert props3["frameShape"] == "torn_edge"
    assert props3["frameTornFreq"] == float(freq)
    assert props3["frameTornScale"] == float(scale)
    assert props3["frameTornSeed"] == int(seed)


def test_motion_mirror_empty_for_rect_and_other_archetypes():
    from mediahub.visual import motion

    assert (
        motion._photo_frame_shape_mirror_props(
            {"layout_template": "photo_passepartout", "photo_frame_shape": "rect"}
        )
        == {}
    )
    assert motion._photo_frame_shape_mirror_props({"layout_template": "photo_passepartout"}) == {}
    # A non-windowed archetype ignores the lever entirely.
    assert (
        motion._photo_frame_shape_mirror_props(
            {"layout_template": "big_number_dominant", "photo_frame_shape": "arch"}
        )
        == {}
    )
