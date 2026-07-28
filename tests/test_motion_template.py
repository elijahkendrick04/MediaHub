"""Tests for the declarative per-card motion template (data-driven-json).

Three layers, none of which needs Node or Remotion:

  - the pure validator / merge / render-kwarg-mapper contract in
    ``mediahub.visual.motion_template`` (the whole security surface);
  - the allowlist sync guards that keep the two locally-transcribed art axes
    (background style, composition) honest against the still renderer;
  - the render-seam byte-identity / merge-in-place proofs on
    ``render_story_card`` / ``_assemble_reel_props``, plus the free-FFmpeg
    engine honouring the merged brief.

The design invariant under test: an absent / empty template is object-identity
at the merge seam ⇒ byte-identical to today, and every out-of-vocabulary or
unknown key RAISES (the opposite of ``design_spec.normalise``'s silent
defaulting — correct for a hallucinated model field, wrong for operator input).
"""

from __future__ import annotations

import ast
import inspect

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion, reel_ffmpeg
from mediahub.visual import motion_template as mt


# ---------------------------------------------------------------------------
# validate_motion_template — empties, unknown keys, version, non-dict
# ---------------------------------------------------------------------------


def test_empty_and_none_return_none():
    assert mt.validate_motion_template(None) is None
    assert mt.validate_motion_template({}) is None
    # A version-only template asks for nothing → None (byte-identical).
    assert mt.validate_motion_template({"version": mt.MOTION_TEMPLATE_VERSION}) is None


def test_non_dict_raises():
    for bad in ("motion", 5, [1, 2], 3.4, True):
        with pytest.raises(mt.MotionTemplateError):
            mt.validate_motion_template(bad)


def test_bad_version_raises():
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"version": 2, "mood": "calm"})
    # ``True`` == 1 == VERSION numerically; it must still be rejected as a version.
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"version": True})


def test_unknown_top_level_key_raises():
    # The security guarantee: no colour / role / seed / arbitrary brief key can
    # ever enter the merged brief — an unknown top-level key is a hard error.
    for bad in ({"colour": "#fff"}, {"palette": {"a": "#000"}}, {"seed": 5},
                {"variation_signature": "x"}, {"layout_template": "poster_name_behind"},
                {"style_pack": "editorial"}, {"photo_src": "/etc/passwd"}):
        with pytest.raises(mt.MotionTemplateError):
            mt.validate_motion_template(bad)


# ---------------------------------------------------------------------------
# Enum art axes — out-of-vocab raises, case/space tolerant canonicalisation
# ---------------------------------------------------------------------------


def test_enum_out_of_vocab_raises():
    for key, bad in (
        ("motion_intent", "teleport"),
        ("mood", "hangry"),
        ("background_style", "plaid"),
        ("accent_style", "sparkles"),
        ("typography_pair", "comic-sans"),
        ("composition", "diagonal"),
        ("photo_treatment", "sepia_deluxe"),
        ("photo_frame_shape", "hexagon"),
    ):
        with pytest.raises(mt.MotionTemplateError):
            mt.validate_motion_template({key: bad})


def test_enum_case_and_space_tolerant_canonicalises():
    from mediahub.creative_brief.design_spec import MOTION_INTENTS

    out = mt.validate_motion_template({"motion_intent": " SNAP_IN_THEN_SETTLE "})
    assert out == {"art": {"motion_intent": "snap_in_then_settle"}}
    # The canonical spelling is stored (never an index pick), so appending a
    # vocabulary member can't shift an existing template's meaning.
    assert out["art"]["motion_intent"] in MOTION_INTENTS


def test_every_enum_axis_maps_to_a_valid_brief_value():
    # A representative member of each axis validates and lands in the art dict
    # under the exact brief key both surfaces read.
    t = mt.validate_motion_template(
        {
            "motion_intent": "fade_in",
            "mood": "calm",
            "background_style": "dots",
            "accent_style": "stripe",
            "typography_pair": "anton-inter",
            "composition": "left",
            "photo_treatment": "duotone",
            "photo_frame_shape": "arch",
        }
    )
    art = t["art"]
    assert art["motion_intent"] == "fade_in"
    assert art["background_style"] == "dots"
    assert art["composition"] == "left"
    assert set(art) == {
        "motion_intent", "mood", "background_style", "accent_style",
        "typography_pair", "composition", "photo_treatment", "photo_frame_shape",
    }


# ---------------------------------------------------------------------------
# The four helper-read art axes (photo_frame_shape / decoration_strength /
# photo_treatment_intensity / seeded_blend) — read by helpers, not the
# 1634-1657 range in _card_to_props. Cover them explicitly.
# ---------------------------------------------------------------------------


def test_float_fields_clamped_to_unit():
    assert mt.validate_motion_template({"decoration_strength": 2.0})["art"][
        "decoration_strength"
    ] == 1.0
    assert mt.validate_motion_template({"decoration_strength": 0.5})["art"][
        "decoration_strength"
    ] == 0.5
    assert mt.validate_motion_template({"photo_treatment_intensity": 1.9})["art"][
        "photo_treatment_intensity"
    ] == 1.0
    assert mt.validate_motion_template({"photo_treatment_intensity": 0.25})["art"][
        "photo_treatment_intensity"
    ] == 0.25


def test_float_fields_non_numeric_raises():
    for bad in ("0.5", None, [0.5], True):
        with pytest.raises(mt.MotionTemplateError):
            mt.validate_motion_template({"decoration_strength": bad})


def test_photo_treatment_intensity_forbids_auto_sentinel():
    # -1.0 is the UNSET "auto" sentinel; absence is the only channel for auto,
    # so an operator must not be able to re-express it.
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"photo_treatment_intensity": -1.0})


def test_seeded_blend_requires_bool():
    assert mt.validate_motion_template({"seeded_blend": True})["art"]["seeded_blend"] is True
    assert mt.validate_motion_template({"seeded_blend": False})["art"]["seeded_blend"] is False
    for bad in ("true", 1, 0, "yes"):
        with pytest.raises(mt.MotionTemplateError):
            mt.validate_motion_template({"seeded_blend": bad})


def test_four_helper_axes_flow_through_card_props():
    # These four axes are consumed by helpers inside _card_to_props, so prove the
    # merged brief actually changes the emitted props.
    brief = {
        "layout_template": "photo_passepartout",
        "style_pack": "editorial",
        "variation_signature": "sig-xyz",
        "id": "card-1",
        "mood": "electric",
        "seeded_blend": False,
    }
    t = mt.validate_motion_template(
        {
            "photo_frame_shape": "arch",
            "decoration_strength": 0.9,
            "seeded_blend": True,
        }
    )
    merged = mt.merge_into_brief(brief, t)
    assert merged["photo_frame_shape"] == "arch"
    assert merged["decoration_strength"] == 0.9
    assert merged["seeded_blend"] is True
    # The frame-shape helper honours the merged brief for the windowed archetype.
    frame_props = motion._photo_frame_shape_mirror_props(merged)
    assert frame_props.get("frameShape") == "arch"
    # The decoration-strength helper reads the merged value.
    assert abs(motion._decoration_strength_of(merged) - 0.9) < 1e-9
    assert abs(motion._resolved_treatment_strength_of(merged) - 0.9) < 1e-9


# ---------------------------------------------------------------------------
# Render section → existing kwargs
# ---------------------------------------------------------------------------


def test_render_section_maps_to_kwargs():
    t = mt.validate_motion_template(
        {"format": "square", "fps": 60, "effect_toggles": ["accent", "cutout"],
         "weights": [3, 1, 1]}
    )
    kw = mt.render_kwargs_from_template(t, n_cards=3)
    assert kw["format_name"] == "square"
    assert kw["fps"] == 60
    assert kw["review_ab"] == ["accent", "cutout"]  # sorted, list (review_ab) form
    assert kw["rhythm"]["beatWeights"] == [3.0, 1.0, 1.0]


def test_render_bad_fps_format_and_toggle_raise():
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"fps": 48})
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"fps": 30.0})  # float rejected
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"format": "widescreen"})
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"format": "800x600"})  # named presets only
    # An unknown toggle key must RAISE (not be silently dropped like
    # motion._validate_effect_toggles does).
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"effect_toggles": ["accent", "not_a_toggle"]})
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"effect_toggles": "accent"})  # must be a list


def test_effect_toggles_raise_where_validate_effect_toggles_would_drop():
    # motion._validate_effect_toggles silently drops the unknown key; the
    # template validator must not.
    assert motion._validate_effect_toggles(["accent", "bogus"]) == ["accent"]
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"effect_toggles": ["accent", "bogus"]})


def test_render_weights_validation():
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"weights": []})
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"weights": ["a", 1]})
    with pytest.raises(mt.MotionTemplateError):
        mt.validate_motion_template({"weights": [True, 1]})
    # A supplied weight list is a real rhythm customisation (uniform weights are
    # NOT the reel's rank-weighted default), so it folds a rhythm through.
    t = mt.validate_motion_template({"weights": [3, 1, 1]})
    kw = mt.render_kwargs_from_template(t, n_cards=3)
    assert kw["rhythm"]["beatWeights"] == [3.0, 1.0, 1.0]


def test_render_kwargs_empty_for_none_or_art_only():
    assert mt.render_kwargs_from_template(None) == {}
    assert mt.render_kwargs_from_template(mt.validate_motion_template({"mood": "calm"})) == {}


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_merge_is_identity_when_none():
    brief = {"background_style": "water", "mood": "neutral"}
    assert mt.merge_into_brief(brief, None) is brief
    # An art-less (render-only) template is also a no-op overlay.
    render_only = mt.validate_motion_template({"fps": 60})
    assert mt.merge_into_brief(brief, render_only) is brief


def test_merge_overlays_only_validated_keys():
    brief = {"background_style": "water", "mood": "neutral", "typography_pair": "anton-inter"}
    t = mt.validate_motion_template({"background_style": "dots"})
    merged = mt.merge_into_brief(brief, t)
    assert merged is not brief
    assert merged["background_style"] == "dots"
    assert merged["mood"] == "neutral"  # untouched
    assert merged["typography_pair"] == "anton-inter"  # untouched
    assert brief["background_style"] == "water"  # original not mutated


def test_merge_tolerates_none_brief():
    t = mt.validate_motion_template({"mood": "electric"})
    merged = mt.merge_into_brief(None, t)
    assert merged == {"mood": "electric"}
    # _card_to_props shapes an overrides-only brief without error.
    props = motion._card_to_props({"swimmer_name": "A B", "event": "50 Free"}, brief=merged)
    assert props["mood"] == "electric"


# ---------------------------------------------------------------------------
# Allowlist sync guards — the two locally-transcribed axes must stay honest
# against the still renderer's registries (drift protection, both directions).
# ---------------------------------------------------------------------------


def _string_keys_of_builders_dict(func) -> set[str]:
    """Extract the string keys of the ``builders`` dict literal in a function."""
    tree = ast.parse(inspect.getsource(func))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "builders" for t in node.targets
        ):
            for k in node.value.keys:  # type: ignore[attr-defined]
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _mesh_trigger_literals(func) -> set[str]:
    """The gradient-mesh trigger spellings special-cased before the dict lookup."""
    src = inspect.getsource(func)
    tree = ast.parse(src)
    out: set[str] = set()
    for node in ast.walk(tree):
        # ``style.partition(":")[0] in ("gradient_mesh", "gradient-mesh", "mesh")``
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.In) for op in node.ops
        ):
            for comp in node.comparators:
                if isinstance(comp, (ast.Tuple, ast.List)):
                    vals = {e.value for e in comp.elts if isinstance(e, ast.Constant)}
                    if "mesh" in vals or "gradient_mesh" in vals:
                        out |= {v for v in vals if isinstance(v, str)}
    return out


def test_background_allowlist_is_in_sync_with_renderer():
    from mediahub.graphic_renderer import render as grender

    registered = _string_keys_of_builders_dict(grender._background_pattern_for)
    registered |= _mesh_trigger_literals(grender._background_pattern_for)
    assert registered, "failed to introspect the background builders registry"
    # Bidirectional: the template offers exactly the registered grounds — no
    # value that the renderer would silently map to its default, and no
    # registered ground the template silently omits.
    assert set(mt.BACKGROUND_STYLE_KEYS) == registered


def _composition_branch_literals(func) -> set[str]:
    """The ``if c == "X"`` string literals of a composition-override function."""
    tree = ast.parse(inspect.getsource(func))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.Eq) for op in node.ops
        ):
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    out.add(comp.value)
    return out


def test_composition_allowlist_is_in_sync_with_renderer():
    from mediahub.graphic_renderer import render as grender

    branches = _composition_branch_literals(grender._composition_overrides_css)
    assert branches, "failed to introspect the composition branches"
    # Explicit branches + the default ("right"): every COMPOSITION_KEYS member is
    # a real registered composition (no value maps unexpectedly to default), and
    # every explicit branch is offered.
    assert branches <= set(mt.COMPOSITION_KEYS)
    assert set(mt.COMPOSITION_KEYS) == branches | {"right"}


# ---------------------------------------------------------------------------
# Render-seam byte-identity + template-changes-key on render_story_card
# ---------------------------------------------------------------------------


def _card():
    return {
        "id": "c-tmpl",
        "achievement": {
            "swimmer_name": "Tem Plate",
            "event_name": "100m Free LC",
            "result_time": "00:51.10",
        },
    }


def test_render_story_card_no_template_is_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cache_dir = tmp_path / "motion_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096

    card = _card()
    brand = BrandKit(profile_id="x", display_name="Tmpl Club")
    brand_dict = motion._brand_to_dict(brand)
    # The PRE-FEATURE cache payload (no template axis anywhere).
    card_dict = motion._card_to_props(card, variation_seed=7, brand_kit=brand)
    cache_key = motion._content_hash(
        {
            "card": card_dict,
            "brand": brand_dict,
            "duration": 6.0,
            "size": [1080, 1920],
            "rev": motion.STORY_COMPOSITION_REVISION,
        },
        kind="story",
    )
    (cache_dir / f"{cache_key}.mp4").write_bytes(fake)

    out = tmp_path / "out.mp4"
    # motion_template=None must serve the pre-feature cache entry (same key).
    res = motion.render_story_card(card, brand, out, variation_seed=7, motion_template=None)
    assert res.exists()
    assert res.stat().st_size == len(fake)


def test_render_story_card_template_changes_key_and_props(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cache_dir = tmp_path / "motion_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096

    card = _card()
    brand = BrandKit(profile_id="x", display_name="Tmpl Club")
    brand_dict = motion._brand_to_dict(brand)

    # Default (no template) key.
    base_dict = motion._card_to_props(card, variation_seed=7, brand_kit=brand)
    base_key = motion._content_hash(
        {"card": base_dict, "brand": brand_dict, "duration": 6.0,
         "size": [1080, 1920], "rev": motion.STORY_COMPOSITION_REVISION},
        kind="story",
    )

    template = {"motion_intent": "kinetic_type", "background_style": "dots"}
    merged = mt.merge_into_brief(None, mt.validate_motion_template(template))
    tmpl_dict = motion._card_to_props(card, variation_seed=7, brief=merged, brand_kit=brand)
    assert tmpl_dict["motionIntent"] == "kinetic_type"
    assert tmpl_dict["backgroundStyle"] == "dots"
    tmpl_key = motion._content_hash(
        {"card": tmpl_dict, "brand": brand_dict, "duration": 6.0,
         "size": [1080, 1920], "rev": motion.STORY_COMPOSITION_REVISION},
        kind="story",
    )
    assert tmpl_key != base_key

    # Seed ONLY the templated key; render with the template must hit it (proves
    # the render call keys off the merged brief, no renderer_generation bump).
    (cache_dir / f"{tmpl_key}.mp4").write_bytes(fake)
    out = tmp_path / "out.mp4"
    res = motion.render_story_card(card, brand, out, variation_seed=7, motion_template=template)
    assert res.exists()
    assert res.stat().st_size == len(fake)


def test_render_story_card_bad_template_raises_before_render(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    card = _card()
    brand = BrandKit(profile_id="x", display_name="Tmpl Club")
    out = tmp_path / "out.mp4"
    with pytest.raises(mt.MotionTemplateError):
        motion.render_story_card(
            card, brand, out, variation_seed=7, motion_template={"colour": "#fff"}
        )


# ---------------------------------------------------------------------------
# Reel per-card merge-in-place
# ---------------------------------------------------------------------------


def test_reel_per_card_template_merges_in_place(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    cards = [
        {"id": f"r{i}", "achievement": {"swimmer_name": f"A{i} B{i}",
         "event_name": "50 Free", "result_time": "00:25.0"}}
        for i in range(3)
    ]
    brand = BrandKit(profile_id="x", display_name="Reel Club")
    b0 = {"background_style": "water", "mood": "neutral"}
    b1 = {"background_style": "clean", "mood": "calm"}
    b2 = {"background_style": "water", "mood": "bold"}
    briefs = [dict(b0), dict(b1), dict(b2)]
    templates = [
        {"background_style": "dots"},
        None,
        {"background_style": "diagonal", "mood": "explosive"},
    ]
    result = motion._assemble_reel_props(
        cards, brand, meet_name="Meet", duration_sec=None,
        briefs=briefs, motion_templates=templates,
    )
    cards_props, _brand_dict, _mn, _dur, _audio, briefs_list, *_ = result
    # Cards 0 and 2 merged; card 1 untouched.
    assert briefs_list[0]["background_style"] == "dots"
    assert briefs_list[1] == b1  # unchanged
    assert briefs_list[2]["background_style"] == "diagonal"
    assert briefs_list[2]["mood"] == "explosive"
    # The emitted props reflect the merged briefs.
    assert cards_props[0]["backgroundStyle"] == "dots"
    assert cards_props[1]["backgroundStyle"] == "clean"
    assert cards_props[2]["backgroundStyle"] == "diagonal"


def test_reel_no_templates_leaves_briefs_untouched(monkeypatch):
    cards = [
        {"id": "r0", "achievement": {"swimmer_name": "A B", "event_name": "50 Free",
         "result_time": "00:25.0"}},
    ]
    brand = BrandKit(profile_id="x", display_name="Reel Club")
    original = {"background_style": "water", "mood": "neutral"}
    briefs = [original]
    result = motion._assemble_reel_props(
        cards, brand, meet_name="Meet", duration_sec=None,
        briefs=briefs, motion_templates=None,
    )
    briefs_list = result[5]
    assert briefs_list[0] is original  # object identity preserved


# ---------------------------------------------------------------------------
# FFmpeg fallback honours the merged brief (honest engine) — and the one
# un-honourable knob (effect_toggles) is still reported unsupported, unchanged.
# ---------------------------------------------------------------------------


def test_ffmpeg_engine_honours_template_brief():
    props = {
        "athleteFullName": "Ada Lovelace",
        "athleteFirstName": "Ada",
        "athleteSurname": "Lovelace",
        "eventName": "100m Free LC",
        "resultValue": "00:58.31",
        "achievementLabel": "NEW PB",
        "variationSeed": 3,
    }
    brand_dict = {"primary": "#0A2540", "secondary": "#101418", "accent": "#D4FF3A",
                  "displayName": "Club", "shortName": "C"}
    brand = BrandKit(profile_id="p", display_name="Club", short_name="C",
                     primary_colour="#0A2540", secondary_colour="#101418",
                     accent_colour="#D4FF3A")
    base_brief = reel_ffmpeg._minimal_brief(props, brand_dict, profile_id="p").to_dict()
    t = mt.validate_motion_template({"background_style": "diagonal", "accent_style": "ribbon"})
    merged = mt.merge_into_brief(base_brief, t)
    # The ffmpeg engine rehydrates a CreativeBrief from exactly this dict, so the
    # baked still it renders picks up the template's reselected treatment.
    frame = reel_ffmpeg._frame_brief(props, brand_dict, brand, merged)
    assert frame.background_style == "diagonal"
    assert frame.accent_style == "ribbon"


# ---------------------------------------------------------------------------
# Still<->motion parity: v1 is PREVIEW-only. The template must never
# regenerate or persist the still — the merge is a render-time-only overlay.
# ---------------------------------------------------------------------------


def test_template_is_preview_only_still_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cache_dir = tmp_path / "motion_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096

    card = _card()
    brand = BrandKit(profile_id="x", display_name="Tmpl Club")

    # The persisted brief the approved STILL was rendered from.
    persisted_brief = {"background_style": "water", "mood": "neutral",
                       "typography_pair": "anton-inter"}
    persisted_snapshot = dict(persisted_brief)

    template = {"background_style": "dots"}
    merged = mt.merge_into_brief(persisted_brief, mt.validate_motion_template(template))
    tmpl_dict = motion._card_to_props(card, variation_seed=7, brief=merged, brand_kit=brand)
    brand_dict = motion._brand_to_dict(brand)
    tmpl_key = motion._content_hash(
        {"card": tmpl_dict, "brand": brand_dict, "duration": 6.0,
         "size": [1080, 1920], "rev": motion.STORY_COMPOSITION_REVISION},
        kind="story",
    )
    (cache_dir / f"{tmpl_key}.mp4").write_bytes(fake)

    out = tmp_path / "out.mp4"
    motion.render_story_card(
        card, brand, out, variation_seed=7, brief=persisted_brief, motion_template=template
    )
    # The render seam merged into a NEW dict — the caller's persisted brief (the
    # still's source of truth) is byte-for-byte unchanged.
    assert persisted_brief == persisted_snapshot
