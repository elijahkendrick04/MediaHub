"""The motion vocabulary (1.5): presets, reduce-motion, caps, and the three
compilers (CSS / FFmpeg / Remotion tokens) — all deterministic, all derived
from the one Python source of truth.
"""
from __future__ import annotations

import pytest

from mediahub.motion import compile_css, compile_ffmpeg, compile_remotion
from mediahub.motion import vocabulary as v


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_registry_is_non_empty_and_unique():
    assert len(v.PRESETS) >= 12
    assert len(v.PRESETS) == len(set(v.names()))


def test_every_preset_has_valid_taxonomy():
    for p in v.PRESETS.values():
        assert p.family in v.FAMILIES, p.name
        assert p.energy in v.ENERGIES, p.name
        assert p.direction in v.DIRECTIONS, p.name
        assert p.duration_frames > 0, p.name
        assert set(p.channels).issubset(set(v.CHANNELS)), p.name
        assert p.loop == (p.family == "loop"), p.name


def test_keyframe_offsets_are_ordered_within_unit_interval():
    for p in v.PRESETS.values():
        for ch, kfs in p.channels.items():
            offs = [k.offset for k in kfs]
            assert offs == sorted(offs), f"{p.name}/{ch} keyframes out of order"
            assert 0.0 <= offs[0] and offs[-1] <= 1.0, f"{p.name}/{ch} out of range"


def test_absent_channel_samples_to_rest():
    fade = v.get("fade_in")  # opacity only
    assert fade.value_at("scale", 0.5) == 1.0
    assert fade.value_at("translateY", 0.5) == 0.0
    assert fade.value_at("rotate", 0.5) == 0.0


def test_entrance_presets_settle_to_rest_at_end():
    for p in v.by_family("in"):
        for ch in p.channel_names():
            assert p.value_at(ch, 1.0) == pytest.approx(v.REST[ch], abs=1e-6), (
                f"{p.name}/{ch} must finish at rest"
            )


def test_entrance_opacity_starts_hidden():
    for p in v.by_family("in"):
        if "opacity" in p.channels:
            assert p.value_at("opacity", 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Reduce-motion
# ---------------------------------------------------------------------------


def test_reduced_entrance_is_opacity_only():
    r = v.get("slide_up").reduced()
    assert r.is_reduced
    assert set(r.channels) == {"opacity"}
    assert r.value_at("opacity", 0.0) == pytest.approx(0.0)
    assert r.value_at("opacity", 1.0) == pytest.approx(1.0)


def test_reduced_loop_is_static():
    r = v.get("ken_burns_in").reduced()
    assert r.channels == {} or r.channels == {}  # no motion at all
    assert not r.loop


def test_reduced_exit_fades_out():
    r = v.get("fade_out").reduced()
    assert set(r.channels) == {"opacity"}
    assert r.value_at("opacity", 1.0) == pytest.approx(0.0)


def test_reduced_is_idempotent():
    r = v.get("pop").reduced()
    assert r.reduced() is r


def test_reduced_strips_movement_everywhere():
    for p in v.PRESETS.values():
        r = p.reduced()
        for ch in ("translateX", "translateY", "scale", "rotate", "blur"):
            assert ch not in r.channels, f"{p.name} reduced still moves on {ch}"


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def test_clamp_helpers():
    assert v.clamp_anim_seconds(99) == v.MAX_ANIM_SECONDS
    assert v.clamp_anim_seconds(-1) == 0.0
    assert v.clamp_anim_frames(10_000) == v.MAX_ANIM_FRAMES


def test_enforce_design_caps():
    v.enforce_design_caps(v.MAX_ANIMS_PER_DESIGN)  # ok at the limit
    with pytest.raises(v.MotionCapError):
        v.enforce_design_caps(v.MAX_ANIMS_PER_DESIGN + 1)


def test_capped_clamps_overlong_preset():
    long = v.MotionPreset(
        name="x", family="loop", energy="calm", direction="none",
        duration_frames=600, channels={"scale": (v.kf(0, 1), v.kf(1, 1.1))}, loop=True,
    )
    assert long.capped().duration_frames == v.MAX_ANIM_FRAMES


def test_all_shipped_presets_are_within_the_cap():
    for p in v.PRESETS.values():
        assert p.duration_frames <= v.MAX_ANIM_FRAMES, p.name


# ---------------------------------------------------------------------------
# MotionPlan (per-element substrate)
# ---------------------------------------------------------------------------


def test_motion_plan_validates_known_presets():
    plan = v.MotionPlan(
        elements=(v.ElementMotion("hero", enter="rise", loop="", exit="fade_out"),)
    )
    plan.validate()  # no raise


def test_motion_plan_rejects_unknown_preset():
    plan = v.MotionPlan(elements=(v.ElementMotion("hero", enter="nope"),))
    with pytest.raises(v.MotionCapError):
        plan.validate()


def test_motion_plan_enforces_element_cap():
    els = tuple(
        v.ElementMotion(f"e{i}", enter="fade_in") for i in range(v.MAX_ANIMS_PER_DESIGN + 1)
    )
    with pytest.raises(v.MotionCapError):
        v.MotionPlan(elements=els).validate()


# ---------------------------------------------------------------------------
# CSS compiler
# ---------------------------------------------------------------------------


def test_css_keyframes_and_class():
    css = compile_css.compile_preset_css(v.get("rise"))
    assert "@keyframes mh-rise{" in css
    assert ".mh-anim-rise{" in css
    assert "animation:mh-rise" in css


def test_css_bakes_easing_into_many_stops_for_eased_presets():
    # rise uses eased channels → it is baked into a fine grid, played linear.
    kf = compile_css.keyframes_block(v.get("rise"))
    assert kf.count("%{") > 10
    assert "linear" in compile_css.class_block(v.get("rise"))


def test_css_loop_runs_infinite():
    cls = compile_css.class_block(v.get("breathe"))
    assert "infinite" in cls


def test_full_stylesheet_has_every_preset_and_reduce_motion():
    sheet = compile_css.compile_all_css()
    for name in v.names():
        assert f"mh-{name.replace('_','-')}" in sheet, name
    assert "@media (prefers-reduced-motion: reduce)" in sheet


def test_reduced_loop_block_disables_animation():
    block = compile_css.reduced_block(v.get("ken_burns_in"))
    assert "animation:none" in block


# ---------------------------------------------------------------------------
# FFmpeg compiler
# ---------------------------------------------------------------------------


def test_ffmpeg_supports_photo_and_opacity_only():
    assert compile_ffmpeg.supports_ffmpeg(v.get("ken_burns_in"))
    assert compile_ffmpeg.supports_ffmpeg(v.get("fade_in"))
    assert not compile_ffmpeg.supports_ffmpeg(v.get("rise"))  # element transform


def test_ffmpeg_fade_in_and_out():
    fin = compile_ffmpeg.compile_ffmpeg(v.get("fade_in"), duration_sec=6, clip_sec=6)
    assert fin.startswith("fade=t=in")
    fout = compile_ffmpeg.compile_ffmpeg(v.get("fade_out"), duration_sec=1, clip_sec=6)
    assert fout.startswith("fade=t=out")
    assert "st=5" in fout  # lands at the clip tail (6 - 1)


def test_ffmpeg_photo_delegates_to_shipped_ken_burns():
    frag = compile_ffmpeg.compile_ffmpeg(
        v.get("ken_burns_in"), duration_sec=4, width=1080, height=1920
    )
    assert isinstance(frag, str) and "zoompan" in frag


def test_ffmpeg_rejects_element_transform():
    with pytest.raises(v.MotionCapError):
        compile_ffmpeg.compile_ffmpeg(v.get("rise"), duration_sec=6)


def test_ffmpeg_xfade_kinds_come_from_the_shipped_map():
    kinds = compile_ffmpeg.xfade_kinds()
    assert kinds["crossfade"] == "fade"
    assert compile_ffmpeg.ffmpeg_xfade_for("iris") == "circleopen"
    assert compile_ffmpeg.ffmpeg_xfade_for("nope") is None


def test_nearest_ken_burns_variant_maps_photo_presets():
    assert v.nearest_ken_burns_variant("ken_burns_in") == "zoom_in"
    assert v.nearest_ken_burns_variant("pan_left") == "pan_left"
    assert v.nearest_ken_burns_variant("rise") is None


# ---------------------------------------------------------------------------
# Remotion token compiler
# ---------------------------------------------------------------------------


def test_token_bundle_shape():
    b = compile_remotion.token_bundle()
    assert b["version"] == v.MOTION_REV
    assert b["fps"] == v.FPS
    assert set(b["presets"]) == set(v.names())
    assert set(b["reduced"]) == set(v.names())
    # every easing a preset references is exported with bézier points
    for name, e in b["easings"].items():
        assert len(e["bezier"]) == 4


def test_preset_tokens_round_trip_values():
    p = v.get("rise")
    tok = compile_remotion.preset_tokens(p)
    assert tok["name"] == "rise"
    assert tok["durationFrames"] == p.duration_frames
    ty = tok["channels"]["translateY"]
    assert ty[0]["value"] == pytest.approx(40.0)
    assert ty[-1]["value"] == pytest.approx(0.0)


def test_export_ts_is_a_typed_const_module():
    ts = compile_remotion.export_ts()
    assert "export const MOTION_TOKENS" in ts
    assert "export default MOTION_TOKENS" in ts
    assert "GENERATED" in ts
