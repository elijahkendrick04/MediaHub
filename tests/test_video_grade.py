"""Tests for the deterministic enhancement layer of the video suite (1.6):

the EDL colour grade + named looks + audio plan (``video.edl``), the enhancement
arg builders (``video.enhance``), and the soundtrack pass arg builder
(``video.audio_post``). All pure — asserted with no FFmpeg binary present.
"""

from __future__ import annotations

import pytest

from mediahub.video.edl import (
    LOOKS,
    AudioPlan,
    Clip,
    ColorAdjust,
    EDL,
    EDLError,
    compile_filtergraph,
    look_adjust,
    validate,
    video_clip_chain,
)


# --- ColorAdjust ----------------------------------------------------------


def test_identity_adjust_emits_no_filters():
    a = ColorAdjust()
    assert a.is_identity()
    assert a.pre_scale_filters() == []
    assert a.post_scale_filters() == []


def test_adjust_builds_eq_colorbalance_denoise_sharpen():
    a = ColorAdjust(brightness=0.1, contrast=1.2, saturation=1.3, gamma=1.1, warmth=0.5, denoise=0.5, sharpen=1.0)
    pre = ",".join(a.pre_scale_filters())
    assert "hqdn3d=" in pre
    assert "eq=" in pre and "contrast=1.2" in pre and "saturation=1.3" in pre
    assert "colorbalance=" in pre
    post = ",".join(a.post_scale_filters())
    assert post.startswith("unsharp=")


def test_adjust_roundtrips_and_clamps():
    a = ColorAdjust(contrast=99.0, saturation=-5.0, sharpen=9.0)
    back = ColorAdjust.from_dict(a.to_dict())
    assert back.contrast == 3.0  # clamped to [0, 3]
    assert back.saturation == 0.0
    assert back.sharpen == 2.0


def test_merged_over_composes_look_and_clip():
    base = ColorAdjust(contrast=1.1, saturation=1.2)  # a "look"
    clip = ColorAdjust(contrast=1.2, sharpen=0.5)  # a per-clip tweak
    m = clip.merged_over(base)
    assert m.contrast == pytest.approx(1.32)  # 1.1 * 1.2
    assert m.saturation == pytest.approx(1.2)
    assert m.sharpen == 0.5  # max(0, 0.5)


# --- named looks ----------------------------------------------------------


def test_look_adjust_known_and_unknown():
    assert look_adjust("vivid") is LOOKS["vivid"]
    assert look_adjust("does-not-exist").is_identity()
    assert look_adjust("").is_identity()


def test_mono_look_desaturates():
    assert LOOKS["mono"].saturation == 0.0


# --- AudioPlan ------------------------------------------------------------


def test_audio_plan_empty_and_roundtrip():
    assert AudioPlan().is_empty()
    assert not AudioPlan(music="/a.mp3").is_empty()
    assert not AudioPlan(enhance_voice=True).is_empty()
    p = AudioPlan(music="/a.mp3", music_gain_db=-12.0, duck=False, enhance_voice=True, loudness="voice")
    assert AudioPlan.from_dict(p.to_dict()) == p


# --- EDL serialisation: inert defaults are omitted -------------------------


def test_edl_omits_look_audio_and_identity_adjust_when_default():
    e = EDL(clips=[Clip(source="a.mp4", in_ms=0, out_ms=3000)])
    d = e.to_dict()
    assert "look" not in d and "audio" not in d
    assert d["clips"][0]["adjust"] is None


def test_edl_includes_and_roundtrips_grade_and_audio():
    c = Clip(source="a.mp4", in_ms=0, out_ms=3000, adjust=ColorAdjust(contrast=1.2))
    e = EDL(clips=[c], look="vivid", audio=AudioPlan(music="/m.mp3", enhance_voice=True))
    d = e.to_dict()
    assert d["look"] == "vivid" and d["audio"]["music"] == "/m.mp3"
    back = EDL.from_dict(d)
    assert back.to_dict() == d
    assert back.clips[0].adjust.contrast == 1.2
    assert back.look == "vivid"
    assert back.audio.enhance_voice is True


def test_empty_audio_plan_is_omitted():
    e = EDL(clips=[Clip(source="a.mp4", out_ms=3000)], audio=AudioPlan())
    assert "audio" not in e.to_dict()


# --- compile: grade is inserted, identity is untouched --------------------


def test_ungraded_chain_is_byte_identical():
    c = Clip(source="a.mp4", in_ms=0, out_ms=3000)
    chain = video_clip_chain(0, c, width=1080, height=1920, fps=30, background="#000000", look="none")
    assert "eq=" not in chain and "unsharp" not in chain and "hqdn3d" not in chain
    assert chain.endswith("[v0]") and chain.startswith("[0:v]")
    # exactly the pre-feature chain
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in chain
    assert "format=yuv420p[v0]" in chain


def test_clip_grade_inserts_before_scale_and_sharpen_after():
    c = Clip(source="a.mp4", in_ms=0, out_ms=3000, adjust=ColorAdjust(contrast=1.2, sharpen=0.8))
    chain = video_clip_chain(0, c, width=1080, height=1920, fps=30, background="#000000")
    # eq before scale; unsharp after fps, before final format
    assert chain.index("eq=") < chain.index("scale=")
    assert chain.index("fps=30") < chain.index("unsharp=") < chain.index("format=yuv420p")


def test_look_applies_to_every_clip_in_compile():
    e = EDL(clips=[Clip(source="a.mp4", out_ms=3000), Clip(source="b.mp4", out_ms=3000)], look="vivid")
    g = compile_filtergraph(e)
    # vivid = contrast 1.12 / sat 1.28 on both clip chains
    assert g.filter_complex.count("eq=contrast=1.12:saturation=1.28") == 2


def test_validate_rejects_unknown_look():
    with pytest.raises(EDLError):
        validate(EDL(clips=[Clip(source="a.mp4", out_ms=3000)], look="cyberpunk"))


# --- smooth slow-mo (minterpolate) ----------------------------------------


def test_smooth_off_is_byte_identical():
    e = EDL(clips=[Clip(source="a.mp4", out_ms=3000)])
    assert "smooth" not in e.to_dict()["clips"][0]
    assert "minterpolate" not in compile_filtergraph(e).filter_complex


def test_smooth_on_inserts_minterpolate_and_roundtrips():
    e = EDL(clips=[Clip(source="a.mp4", out_ms=3000, speed=0.5, smooth=True)])
    assert e.to_dict()["clips"][0]["smooth"] is True
    assert EDL.from_dict(e.to_dict()).clips[0].smooth is True
    fc = compile_filtergraph(e).filter_complex
    assert "minterpolate=fps=30:mi_mode=mci" in fc
    assert "setpts=(PTS-STARTPTS)/0.5" in fc  # the slow-down retime is still there


# --- enhance arg builders -------------------------------------------------


def test_enhance_look_helpers():
    from mediahub.video.enhance import describe_look, look_names

    names = look_names()
    assert names[0] == "none"  # default first
    assert "vivid" in names
    assert describe_look("vivid") == "Vivid"
    assert describe_look("none") == "Original"


def test_vidstab_arg_builders_are_two_pass():
    from mediahub.video.enhance import vidstabdetect_args, vidstabtransform_args

    d = vidstabdetect_args("in.mp4", "/tmp/t.trf", shakiness=5, accuracy=15)
    assert "vidstabdetect=shakiness=5:accuracy=15:result=/tmp/t.trf" in " ".join(d)
    t = vidstabtransform_args("in.mp4", "/tmp/t.trf", "out.mp4", smoothing=10)
    j = " ".join(t)
    assert "vidstabtransform=input=/tmp/t.trf:smoothing=10" in j
    assert "-c:a" in t and "copy" in t  # audio passed through


def test_lanczos_scale_args():
    from mediahub.video.enhance import lanczos_scale_args

    a = lanczos_scale_args("in.mp4", "out.mp4", width=1080, height=1920)
    assert "scale=1080:1920:flags=lanczos" in " ".join(a)


def test_stabilize_honest_error_without_ffmpeg(monkeypatch):
    from mediahub.video import enhance

    monkeypatch.setattr(enhance, "ffmpeg_exe", lambda: None)
    with pytest.raises(enhance.VideoEnhanceUnavailable):
        enhance.stabilize_source("a.mp4", "b.mp4")


# --- audio_post arg builder -----------------------------------------------


def test_audio_post_voice_plus_music_ducks_and_copies_video():
    from mediahub.video.audio_post import build_audio_post_args

    plan = AudioPlan(music="m.mp3", enhance_voice=True, loudness="social")
    args = build_audio_post_args("v.mp4", "o.mp4", plan, has_voice=True, music_path="m.mp3", duration_s=8.0)
    j = " ".join(args)
    assert "sidechaincompress" in j  # bed ducks under voice
    assert "afftdn" in j  # voice denoise (enhance_voice)
    assert "loudnorm" in j  # master loudness
    assert args[args.index("-c:v") + 1] == "copy"  # picture untouched
    assert "-stream_loop" in args  # music looped to length


def test_audio_post_voice_only_has_no_music_input():
    from mediahub.video.audio_post import build_audio_post_args

    plan = AudioPlan(enhance_voice=True, loudness="social")
    args = build_audio_post_args("v.mp4", "o.mp4", plan, has_voice=True, music_path=None, duration_s=8.0)
    j = " ".join(args)
    assert "sidechaincompress" not in j
    assert "loudnorm" in j
    assert args.count("-i") == 1  # only the video input


def test_audio_post_music_only_for_silent_footage():
    from mediahub.video.audio_post import build_audio_post_args

    plan = AudioPlan(music="m.mp3", loudness="social")
    args = build_audio_post_args("v.mp4", "o.mp4", plan, has_voice=False, music_path="m.mp3", duration_s=8.0)
    j = " ".join(args)
    assert "[1:a]" in j  # the bed is the soundtrack
    assert "sidechaincompress" not in j  # nothing to duck under


def test_audio_post_empty_plan_is_copy_through(tmp_path):
    from mediahub.video.audio_post import apply_audio_plan

    src = tmp_path / "v.mp4"
    src.write_bytes(b"\x00" * 4096)
    out = tmp_path / "o.mp4"
    res = apply_audio_plan(src, out, AudioPlan())
    assert res == out and out.exists() and out.read_bytes() == src.read_bytes()
