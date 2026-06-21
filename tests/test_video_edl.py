"""Tests for video.edl — the deterministic EDL model + FFmpeg compiler (1.6).

The compile is a pure function over the timeline data, so these assert on the
*structure* of the filter graph with no FFmpeg binary present.
"""

from __future__ import annotations

import pytest

from mediahub.video.edl import (
    EDL,
    Clip,
    CompiledGraph,
    EDLError,
    TextOverlay,
    Transition,
    atempo_chain,
    audio_clip_chain,
    compile_filtergraph,
    validate,
    video_clip_chain,
)


def _clip(src="a.mp4", **kw):
    return Clip(source=src, in_ms=kw.pop("in_ms", 0), out_ms=kw.pop("out_ms", 3000), **kw)


# --- validation -----------------------------------------------------------


def test_validate_rejects_empty_timeline():
    with pytest.raises(EDLError):
        validate(EDL(clips=[]))


def test_validate_rejects_bad_speed():
    with pytest.raises(EDLError):
        validate(EDL(clips=[_clip(speed=10.0)]))


def test_validate_rejects_out_before_in():
    with pytest.raises(EDLError):
        validate(EDL(clips=[Clip(source="a.mp4", in_ms=3000, out_ms=1000)]))


def test_validate_rejects_unknown_transition():
    c = _clip()
    c.transition_in = Transition(kind="explode", duration_ms=400)
    with pytest.raises(EDLError):
        validate(EDL(clips=[c]))


def test_validate_rejects_transition_on_first_clip():
    c = _clip()
    c.transition_in = Transition(kind="fade", duration_ms=400)
    with pytest.raises(EDLError):
        validate(EDL(clips=[c]))


def test_validate_rejects_degenerate_crop():
    with pytest.raises(EDLError):
        validate(EDL(clips=[_clip(crop=(0, 0, 0, 100))]))


# --- atempo decomposition -------------------------------------------------


def test_atempo_unit_speed_is_empty():
    assert atempo_chain(1.0) == ""


def test_atempo_4x_chains_two_stages():
    assert atempo_chain(4.0) == "atempo=2,atempo=2"


def test_atempo_quarter_chains_two_half_stages():
    assert atempo_chain(0.25) == "atempo=0.5,atempo=0.5"


def test_atempo_1_5_single_stage():
    assert atempo_chain(1.5) == "atempo=1.5"


# --- per-clip chains ------------------------------------------------------


def test_video_chain_has_trim_scale_pad_fps():
    chain = video_clip_chain(0, _clip(), width=1080, height=1920, fps=30, background="#000000")
    assert chain.startswith("[0:v]")
    assert "trim=start=0.000:end=3.000" in chain
    assert "setpts=PTS-STARTPTS" in chain
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in chain
    assert "pad=1080:1920" in chain
    assert "fps=30" in chain
    assert chain.endswith("[v0]")


def test_video_chain_folds_speed_into_setpts_and_crop():
    c = _clip(speed=2.0, crop=(10, 20, 540, 960))
    chain = video_clip_chain(1, c, width=1080, height=1920, fps=30, background="#000000")
    assert "setpts=(PTS-STARTPTS)/2" in chain
    assert "crop=540:960:10:20" in chain
    assert chain.endswith("[v1]")


def test_audio_chain_silent_when_muted():
    chain = audio_clip_chain(0, _clip(mute=True), keep_audio=True, has_audio=True)
    assert "anullsrc" in chain
    assert chain.endswith("[a0]")


def test_audio_chain_real_when_present():
    chain = audio_clip_chain(0, _clip(), keep_audio=True, has_audio=True)
    assert "[0:a]atrim=start=0.000:end=3.000" in chain
    assert "asetpts=PTS-STARTPTS" in chain


def test_audio_chain_speed_adds_atempo():
    chain = audio_clip_chain(0, _clip(speed=2.0), keep_audio=True, has_audio=True)
    assert "atempo=2" in chain


# --- full compile ---------------------------------------------------------


def test_compile_single_clip_maps_v0_a0():
    g = compile_filtergraph(EDL(clips=[_clip()]))
    assert isinstance(g, CompiledGraph)
    assert g.inputs == ("a.mp4",)
    assert g.vout == "v0" and g.aout == "a0"
    assert "concat" not in g.filter_complex  # nothing to join


def test_compile_two_cuts_uses_concat():
    c2 = _clip(src="b.mp4")
    g = compile_filtergraph(EDL(clips=[_clip(), c2]))
    assert g.inputs == ("a.mp4", "b.mp4")
    assert "[v0][v1]concat=n=2:v=1:a=0" in g.filter_complex
    assert "[a0][a1]concat=n=2:v=0:a=1" in g.filter_complex
    assert g.vout == "vx1" and g.aout == "ax1"


def test_compile_transition_uses_xfade_with_offset():
    c2 = _clip(src="b.mp4", out_ms=4000)  # 4s clip
    c2.transition_in = Transition(kind="fade", duration_ms=500)
    edl = EDL(clips=[_clip(out_ms=3000), c2])  # first clip 3s
    g = compile_filtergraph(edl)
    # offset = running(3000) - 500 = 2500ms → 2.500
    assert "xfade=transition=fade:duration=0.500:offset=2.500" in g.filter_complex
    assert "acrossfade=d=0.500" in g.filter_complex


def test_compile_resolves_open_out_with_probe():
    c = Clip(source="a.mp4", in_ms=0, out_ms=0)  # open-ended
    g = compile_filtergraph(EDL(clips=[c]), probes={"a.mp4": 5000})
    assert "trim=start=0.000:end=5.000" in g.filter_complex


def test_compile_silent_source_uses_anullsrc():
    # A source with no audio stream must get a silence segment, never a
    # dangling [0:a] that would crash FFmpeg.
    g = compile_filtergraph(EDL(clips=[_clip()]), audio={"a.mp4": False})
    assert "anullsrc" in g.filter_complex
    assert "[0:a]" not in g.filter_complex


def test_compile_audio_source_uses_real_stream():
    g = compile_filtergraph(EDL(clips=[_clip()]), audio={"a.mp4": True})
    assert "[0:a]atrim" in g.filter_complex
    assert "anullsrc" not in g.filter_complex


def test_compile_ignores_overlays_in_graph():
    # Title overlays are burned via libass in render.py, not in the filter graph.
    edl = EDL(clips=[_clip()], overlays=[TextOverlay(text="New PB!", start_ms=0, duration_ms=2000)])
    g = compile_filtergraph(edl)
    assert "drawtext" not in g.filter_complex
    assert "New PB" not in g.filter_complex
    assert g.vout == "v0"  # composite is the clip, text layered later


def test_total_timeline_ms_subtracts_transition_overlap():
    c2 = _clip(src="b.mp4", out_ms=4000)
    c2.transition_in = Transition(kind="fade", duration_ms=500)
    edl = EDL(clips=[_clip(out_ms=3000), c2])
    # 3000 + 4000 - 500 = 6500
    assert edl.total_timeline_ms() == 6500


def test_clip_start_offsets_mirror_running_ms_walk():
    # clip0 [0,2000); clip1 (cut) dominant at 2000; clip2 (320ms dissolve) fully
    # on screen at 4000 — the offsets used to place per-beat reel captions.
    c1 = _clip(src="b.mp4", out_ms=2000)
    c1.transition_in = Transition(kind="cut")
    c2 = _clip(src="c.mp4", out_ms=2000)
    c2.transition_in = Transition(kind="dissolve", duration_ms=320)
    edl = EDL(clips=[_clip(out_ms=2000), c1, c2])
    assert edl.clip_start_offsets_ms() == [0, 2000, 4000]
    # the dissolve overlaps, so the composite is shorter than the last offset + clip
    assert edl.total_timeline_ms() == 2000 + 2000 + 2000 - 320


def test_clip_start_offsets_single_clip():
    assert EDL(clips=[_clip(out_ms=2000)]).clip_start_offsets_ms() == [0]


def test_edl_roundtrips_through_dict():
    c2 = _clip(src="b.mp4", speed=2.0, crop=(1, 2, 3, 4))
    c2.transition_in = Transition(kind="wipeleft", duration_ms=300)
    edl = EDL(clips=[_clip(), c2], overlays=[TextOverlay(text="hi")], captions={"cues": []})
    back = EDL.from_dict(edl.to_dict())
    assert back.to_dict() == edl.to_dict()
    assert back.clips[1].crop == (1, 2, 3, 4)
    assert back.clips[1].transition_in.kind == "wipeleft"
