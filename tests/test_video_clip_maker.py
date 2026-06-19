"""Tests for video.clip_maker — Clip-Maker-for-sport orchestration (1.6).

The pure assembler is tested directly; the orchestrator is tested with injected
fakes so it never touches FFmpeg/ASR.
"""

from __future__ import annotations

from mediahub.video.clip_maker import (
    BrandColours,
    build_clip_edl,
    canvas_for,
    clip_maker,
)
from mediahub.video.moments import Moment
from mediahub.video.probe import ClipProbe


def _probe(w=1920, h=1080, dur=12000, audio=True):
    return ClipProbe(
        duration_ms=dur, width=w, height=h, fps=30.0, has_video=True, has_audio=audio,
        video_codec="h264", audio_codec="aac" if audio else "",
    )


def _moment(start=2000, end=8000):
    return Moment(start, end, 0.9, "energy+scene", "loud cheer with a scene cut")


# --- pure assembler -------------------------------------------------------


def test_canvas_for():
    assert canvas_for("story") == (1080, 1920)
    assert canvas_for("landscape") == (1920, 1080)
    assert canvas_for("bogus") == (1080, 1920)  # defaults to story


def test_build_clip_edl_one_moment():
    edl = build_clip_edl("a.mp4", _probe(), [_moment()], format_name="story")
    assert (edl.width, edl.height) == (1080, 1920)
    assert len(edl.clips) == 1
    assert edl.clips[0].in_ms == 2000 and edl.clips[0].out_ms == 8000
    assert edl.clips[0].transition_in.is_cut


def test_build_clip_edl_multi_moment_transitions():
    moments = [_moment(0, 3000), _moment(5000, 8000), _moment(9000, 11000)]
    edl = build_clip_edl(
        "a.mp4", _probe(), moments, transition_kind="fade", transition_ms=400
    )
    assert len(edl.clips) == 3
    assert edl.clips[0].transition_in.is_cut  # first is always a cut
    assert edl.clips[1].transition_in.kind == "fade"
    assert edl.clips[2].transition_in.kind == "fade"


def test_build_clip_edl_applies_crops_and_title():
    edl = build_clip_edl(
        "a.mp4", _probe(), [_moment()], crops=[(0, 100, 608, 1080)], title="New PB!"
    )
    assert edl.clips[0].crop == (0, 100, 608, 1080)
    assert edl.overlays and edl.overlays[0].text == "New PB!"


def test_build_clip_edl_restyles_captions_to_brand():
    track = {"color": "#FFFFFF", "scrim": "#000000", "cues": [{"from": 0, "dur": 30, "text": "Go"}]}
    edl = build_clip_edl(
        "a.mp4", _probe(), [_moment()], caption_track=track,
        colours=BrandColours(ground="#FFFFFF", accent="#FF0000"),
    )
    # Restyled for a white ground → ink no longer white.
    assert edl.captions["color"] != "#FFFFFF"


def test_build_clip_edl_no_moments_keeps_opening():
    edl = build_clip_edl("a.mp4", _probe(dur=4000), [])
    assert len(edl.clips) == 1
    assert edl.clips[0].in_ms == 0


# --- orchestration (injected fakes; no FFmpeg/ASR) ------------------------


def test_clip_maker_single_moment_full_result():
    captured = {}

    def fake_detect(source, *, duration_ms, target_len_ms, max_moments):
        captured["dur"] = duration_ms
        return [_moment(2000, 8000)]

    def fake_reframe(source, *, in_ms, out_ms, dst_w, dst_h):
        return (0, 100, 608, 1080)

    def fake_caption(source, *, in_ms, out_ms, fps, ground, onground, accent):
        return {"color": "#fff", "scrim": "#000", "cues": [{"from": 0, "dur": 30, "text": "PB"}]}

    res = clip_maker(
        "a.mp4",
        format_name="story",
        probe_fn=lambda s: _probe(1920, 1080),
        detect_fn=fake_detect,
        reframe_fn=fake_reframe,
        caption_fn=fake_caption,
    )
    assert captured["dur"] == 12000
    assert len(res.edl.clips) == 1
    assert res.edl.clips[0].crop == (0, 100, 608, 1080)  # reframed (landscape→portrait)
    assert res.edl.captions is not None
    assert res.manifest["reframed"] is True
    assert res.manifest["captions"] == "burned"
    assert res.manifest["moments"][0]["kind"] == "energy+scene"


def test_clip_maker_skips_reframe_when_ratio_matches():
    called = {"reframe": 0}

    def fake_reframe(*a, **k):
        called["reframe"] += 1
        return (0, 0, 1, 1)

    res = clip_maker(
        "a.mp4",
        format_name="story",
        probe_fn=lambda s: _probe(1080, 1920),  # already 9:16
        detect_fn=lambda *a, **k: [_moment()],
        reframe_fn=fake_reframe,
        caption_fn=lambda *a, **k: None,
    )
    assert called["reframe"] == 0  # no crop attempted
    assert res.manifest["reframed"] is False
    assert not res.edl.clips[0].crop


def test_clip_maker_skips_captions_for_multimoment():
    res = clip_maker(
        "a.mp4",
        target_moments=3,
        probe_fn=lambda s: _probe(1080, 1920),
        detect_fn=lambda *a, **k: [_moment(0, 3000), _moment(5000, 8000), _moment(9000, 11000)],
        reframe_fn=lambda *a, **k: None,
        caption_fn=lambda *a, **k: {"cues": [{"from": 0, "dur": 1, "text": "x"}]},
    )
    assert res.manifest["captions"] == "skipped-multimoment"
    assert res.edl.captions is None
    assert len(res.edl.clips) == 3


def test_clip_maker_manifest_is_explainable():
    res = clip_maker(
        "race.mp4",
        probe_fn=lambda s: _probe(1920, 1080),
        detect_fn=lambda *a, **k: [_moment()],
        reframe_fn=lambda *a, **k: (0, 0, 608, 1080),
        caption_fn=lambda *a, **k: None,
    )
    m = res.manifest
    assert m["source"] == "race.mp4"
    assert m["canvas"] == [1080, 1920]
    assert m["source_duration_ms"] == 12000
    assert m["timeline_ms"] > 0
