"""Tests for video.reel_builder + the clip_maker enhancement options (1.6).

``build_reel_edl`` and ``build_clip_edl`` are pure; ``make_reel`` is orchestration
with every engine piece injectable, so the full reel assembly is exercised with
no FFmpeg, no transcription, and no AI provider.
"""

from __future__ import annotations

from mediahub.video.clip_maker import build_clip_edl, clip_maker
from mediahub.video.director import ClipBeat, ReelPlan
from mediahub.video.edl import AudioPlan
from mediahub.video.moments import Moment
from mediahub.video.probe import ClipProbe
from mediahub.video.reel_builder import build_reel_edl, make_reel


# --- build_reel_edl (pure) ------------------------------------------------


def test_build_reel_edl_one_clip_per_beat_with_transitions():
    sources = ["a.mp4", "b.mp4"]
    mbc = [[Moment(0, 4000, 0.9, "energy", "x")], [Moment(1000, 5000, 0.7, "energy", "y")]]
    plan = ReelPlan(order=[ClipBeat(0, 0), ClipBeat(1, 0)], look="warm", hook="Big day", source="ai")
    edl = build_reel_edl(sources, plan.order, mbc, plan=plan)
    assert len(edl.clips) == 2
    assert edl.clips[0].source == "a.mp4" and edl.clips[0].transition_in.is_cut
    assert edl.clips[1].source == "b.mp4" and edl.clips[1].transition_in.kind == "dissolve"
    assert edl.look == "warm"
    assert edl.overlays and edl.overlays[0].text == "Big day"


def test_build_reel_edl_attaches_nonempty_audio_plan():
    mbc = [[Moment(0, 4000, 0.9, "energy", "x")]]
    edl = build_reel_edl(
        ["a.mp4"], [ClipBeat(0, 0)], mbc, audio_plan=AudioPlan(music="m.mp3", enhance_voice=True)
    )
    assert edl.audio is not None and edl.audio.music == "m.mp3"


def test_build_reel_edl_drops_empty_audio_plan():
    mbc = [[Moment(0, 4000, 0.9, "energy", "x")]]
    edl = build_reel_edl(["a.mp4"], [ClipBeat(0, 0)], mbc, audio_plan=AudioPlan())
    assert edl.audio is None


def test_build_reel_edl_degenerate_keeps_opening():
    edl = build_reel_edl(["a.mp4"], [], [], plan=ReelPlan())
    assert len(edl.clips) == 1 and edl.clips[0].in_ms == 0


# --- make_reel (orchestration with injected engine pieces) ----------------


def _fake_probe(src):
    return ClipProbe(duration_ms=12000, width=1920, height=1080, fps=30, has_video=True, has_audio=True)


def _fake_detect(src, *, duration_ms, target_len_ms, max_moments):
    return [Moment(0, 4000, 0.9, "energy", "cheer"), Moment(6000, 10000, 0.6, "scene", "cut")][:max_moments]


def _fake_plan(clips_meta, *, brief_context="", max_beats=5):
    # one beat per clip, AI-style
    order = [ClipBeat(ci, 0) for ci, _ in enumerate(clips_meta)]
    return ReelPlan(order=order, look="punch", music_mood="uplifting", hook="Meet recap", source="ai")


def test_make_reel_assembles_from_many_clips():
    res = make_reel(
        ["a.mp4", "b.mp4"],
        with_captions=False,
        with_reframe=False,
        with_music=False,
        enhance_audio=True,
        probe_fn=_fake_probe,
        detect_fn=_fake_detect,
        plan_fn=_fake_plan,
    )
    assert len(res.edl.clips) == 2
    assert res.edl.look == "punch"
    assert res.edl.overlays[0].text == "Meet recap"
    assert res.plan.source == "ai"
    # enhance_audio only → audio plan present, voice-only
    assert res.edl.audio is not None and res.edl.audio.enhance_voice is True
    assert res.manifest["kind"] == "reel" and res.manifest["beats"]


def test_make_reel_reframes_when_shapes_differ():
    calls = {"n": 0}

    def fake_reframe(src, *, in_ms, out_ms, dst_w, dst_h, **kw):
        calls["n"] += 1
        return (100, 0, 1080, 1920)

    res = make_reel(
        ["a.mp4"],
        with_captions=False,
        with_music=False,
        probe_fn=_fake_probe,  # 1920x1080 landscape → story needs reframe
        detect_fn=_fake_detect,
        reframe_fn=fake_reframe,
        plan_fn=lambda *a, **k: ReelPlan(order=[ClipBeat(0, 0)], source="default"),
    )
    assert calls["n"] == 1
    assert res.edl.clips[0].crop == (100, 0, 1080, 1920)


def test_make_reel_music_resolution_injectable():
    seen = {}

    def fake_music(mood, *, platform, content_key):
        seen["mood"] = mood
        return "/library/triumph.mp3"

    res = make_reel(
        ["a.mp4"],
        with_captions=False,
        with_reframe=False,
        with_music=True,
        probe_fn=_fake_probe,
        detect_fn=_fake_detect,
        plan_fn=lambda *a, **k: ReelPlan(order=[ClipBeat(0, 0)], music_mood="triumphant", source="ai"),
        music_fn=fake_music,
    )
    assert seen["mood"] == "triumphant"
    assert res.edl.audio.music == "/library/triumph.mp3"


def test_resolve_music_honest_none_when_library_empty(monkeypatch):
    from mediahub.video import reel_builder

    class _EmptyLib:
        def pick(self, *a, **k):
            return None

    monkeypatch.setattr("mediahub.audio.library.AudioLibrary.load", classmethod(lambda cls: _EmptyLib()))
    assert reel_builder.resolve_music("triumphant") is None


# --- clip_maker enhancement options ---------------------------------------


def test_build_clip_edl_carries_look_and_audio():
    edl = build_clip_edl(
        "a.mp4",
        ClipProbe(duration_ms=6000),
        [Moment(0, 5000, 0.9, "energy", "x")],
        look="film",
        audio_plan=AudioPlan(enhance_voice=True, loudness="social"),
    )
    assert edl.look == "film"
    assert edl.audio is not None and edl.audio.enhance_voice is True


def test_clip_maker_remove_silence_builds_keep_segments():
    # remove_silence tightens the whole clip: keep-segments → multiple clips.
    def fake_silence(src, dur):
        return [(0, 2000), (3000, 6000)]

    res = clip_maker(
        "a.mp4",
        with_captions=True,
        with_reframe=False,
        remove_silence=True,
        probe_fn=lambda s: ClipProbe(duration_ms=6000, width=1080, height=1920, has_audio=True),
        silence_fn=fake_silence,
    )
    assert len(res.edl.clips) == 2
    assert res.edl.clips[0].in_ms == 0 and res.edl.clips[0].out_ms == 2000
    assert res.manifest["captions"] == "skipped-silencecut"  # tightened → no single transcript
    assert "removed" in res.manifest["silence"]


def test_clip_maker_look_and_music_thread_into_edl():
    res = clip_maker(
        "a.mp4",
        with_captions=False,
        with_reframe=False,
        look="vivid",
        enhance_audio=True,
        with_music=True,
        probe_fn=lambda s: ClipProbe(duration_ms=6000, width=1080, height=1920, has_audio=True),
        detect_fn=lambda *a, **k: [Moment(0, 5000, 0.9, "energy", "x")],
        music_fn=lambda mood, **kw: "/lib/track.mp3",
    )
    assert res.edl.look == "vivid"
    assert res.edl.audio.music == "/lib/track.mp3"
    assert res.edl.audio.enhance_voice is True
