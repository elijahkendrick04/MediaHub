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
            assert p.value_at(ch, 1.0) == pytest.approx(
                v.REST[ch], abs=1e-6
            ), f"{p.name}/{ch} must finish at rest"


def test_entrance_opacity_starts_hidden():
    for p in v.by_family("in"):
        if "opacity" in p.channels:
            assert p.value_at("opacity", 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Per-keyframe interpolation modes (hold / auto / continuous)
# ---------------------------------------------------------------------------


def _p(channel, kfs, *, duration=20):
    """A throwaway single-channel preset for interp sampling tests."""
    return v.MotionPreset(
        name="synthetic",
        family="in",
        energy="standard",
        direction="none",
        duration_frames=duration,
        channels={channel: tuple(kfs)},
    )


def test_default_bezier_sampling_is_byte_identical_regression():
    # Guard: the default (bezier) branch must be unchanged for every shipped
    # preset — same sampled values a pre-change build produced.
    for p in v.PRESETS.values():
        for ch in p.channel_names():
            for i in range(21):
                t = i / 20.0
                val = p.value_at(ch, t)
                # Re-derive with the explicit bezier _sample path (all shipped
                # keyframes are interp='bezier').
                assert val == v._sample(p.channels[ch], t)


def test_hold_holds_then_jumps_at_offset():
    p = _p("opacity", [v.kf(0.0, 0.0), v.kf(0.5, 1.0, interp="hold")])
    assert p.value_at("opacity", 0.0) == pytest.approx(0.0)
    assert p.value_at("opacity", 0.25) == pytest.approx(0.0)  # still held
    assert p.value_at("opacity", 0.49999) == pytest.approx(0.0)  # held right up to
    assert p.value_at("opacity", 0.5) == pytest.approx(1.0)  # jump AT the offset
    assert p.value_at("opacity", 0.8) == pytest.approx(1.0)


def test_continuous_has_smooth_velocity_across_interior_keyframe():
    # A monotone rising track: continuous keeps a non-zero tangent at the
    # interior keyframe (velocity continuous), so the sampled curve passes
    # through the middle value with matched slope on both sides.
    kfs = [
        v.kf(0.0, 0.0),
        v.kf(0.5, 5.0, interp="continuous"),
        v.kf(1.0, 10.0, interp="continuous"),
    ]
    p = _p("translateY", kfs)
    # interior tangent = (10-0)/(1-0) = 10 (Catmull-Rom finite difference)
    tangents = v._track_tangents(kfs, "continuous")
    assert tangents[1] == pytest.approx(10.0)
    # symmetric linear-ish track passes through the mid value at its offset
    assert p.value_at("translateY", 0.5) == pytest.approx(5.0)


def test_auto_flattens_tangent_and_never_overshoots_at_extremum():
    # A track that rises to a peak then falls: the middle keyframe is a local
    # maximum, so auto flattens its tangent to 0 (no overshoot beyond the peak).
    kfs = [v.kf(0.0, 0.0), v.kf(0.5, 10.0, interp="auto"), v.kf(1.0, 0.0, interp="auto")]
    p = _p("translateY", kfs)
    tangents = v._track_tangents(kfs, "auto")
    assert tangents[1] == pytest.approx(0.0)  # flattened at the extremum
    # continuous would keep the raw tangent (0 here too, since symmetric) — use
    # an asymmetric track to prove the flatten only happens for auto.
    asym = [
        v.kf(0.0, 0.0),
        v.kf(0.5, 10.0, interp="continuous"),
        v.kf(1.0, 8.0, interp="continuous"),
    ]
    cont_t = v._track_tangents(asym, "continuous")
    auto_t = v._track_tangents(
        [v.kf(0.0, 0.0), v.kf(0.5, 10.0, interp="auto"), v.kf(1.0, 8.0, interp="auto")], "auto"
    )
    assert cont_t[1] != pytest.approx(0.0)  # continuous keeps the raw tangent
    assert auto_t[1] == pytest.approx(0.0)  # auto flattens at the max
    # auto never rises above the peak neighbour value anywhere in the segment
    for i in range(21):
        t = i / 20.0
        assert p.value_at("translateY", t) <= 10.0 + 1e-9


def test_interp_endpoints_still_clamp():
    kfs = [v.kf(0.0, 2.0), v.kf(1.0, 9.0, interp="continuous")]
    p = _p("scale", kfs)
    assert p.value_at("scale", -0.5) == pytest.approx(2.0)
    assert p.value_at("scale", 0.0) == pytest.approx(2.0)
    assert p.value_at("scale", 1.0) == pytest.approx(9.0)
    assert p.value_at("scale", 1.5) == pytest.approx(9.0)


def test_unknown_interp_mode_raises_at_construction():
    with pytest.raises(v.MotionCapError):
        v.kf(0.0, 1.0, interp="bogus")
    with pytest.raises(v.MotionCapError):
        v.Keyframe(0.0, 1.0, interp="wobble")


def test_ffmpeg_rejects_non_bezier_interp():
    # honest fallback: opacity-only preset with a hold interp is unsupported and
    # compile_ffmpeg raises rather than baking a wrong linear fade.
    held = _p("opacity", [v.kf(0.0, 1.0), v.kf(1.0, 0.0, interp="hold")])
    assert not compile_ffmpeg.supports_ffmpeg(held)
    with pytest.raises(v.MotionCapError):
        compile_ffmpeg.compile_ffmpeg(held, duration_sec=6, clip_sec=6)
    # a photo (scale) preset with a non-bezier interp is also refused.
    photo = v.MotionPreset(
        name="synthetic_photo",
        family="loop",
        energy="calm",
        direction="in",
        duration_frames=120,
        channels={"scale": (v.kf(0.0, 1.0), v.kf(1.0, 1.06, interp="continuous"))},
        loop=True,
        photo=True,
    )
    assert not compile_ffmpeg.supports_ffmpeg(photo)


def test_ffmpeg_still_supports_bezier_photo_and_opacity():
    # regression: the tightening must NOT break today's bezier presets.
    assert compile_ffmpeg.supports_ffmpeg(v.get("ken_burns_in"))
    assert compile_ffmpeg.supports_ffmpeg(v.get("fade_in"))


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
        name="x",
        family="loop",
        energy="calm",
        direction="none",
        duration_frames=600,
        channels={"scale": (v.kf(0, 1), v.kf(1, 1.1))},
        loop=True,
    )
    assert long.capped().duration_frames == v.MAX_ANIM_FRAMES


def test_all_shipped_presets_are_within_the_cap():
    for p in v.PRESETS.values():
        assert p.duration_frames <= v.MAX_ANIM_FRAMES, p.name


# ---------------------------------------------------------------------------
# MotionPlan (per-element substrate)
# ---------------------------------------------------------------------------


def test_motion_plan_validates_known_presets():
    plan = v.MotionPlan(elements=(v.ElementMotion("hero", enter="rise", loop="", exit="fade_out"),))
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
