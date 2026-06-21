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


def test_snap_to_beats():
    from mediahub.video.reel_builder import snap_to_beats

    assert snap_to_beats(1800, 500) == 2000  # 3.6 beats → 4 beats (round to nearest)
    assert snap_to_beats(1700, 500) == 1500  # 3.4 beats → 3 beats
    assert snap_to_beats(2000, 0) == 2000  # no tempo → no-op
    assert snap_to_beats(100, 500, min_beats=2) == 1000  # floored to 2 beats


def test_build_reel_edl_beat_snaps_clip_lengths():
    mbc = [[Moment(0, 1800, 0.9, "energy", "x")]]
    edl = build_reel_edl(["a.mp4"], [ClipBeat(0, 0)], mbc, beat_ms=500.0)
    assert edl.clips[0].out_ms == 2000  # 1.8s snapped to 4 beats = 2.0s


# --- per-beat weight (director depth) -------------------------------------


def test_build_reel_edl_weight_one_is_byte_identical():
    # An even (1.0) weight must produce the exact same EDL as no weight at all,
    # so an un-weighted reel keeps its content-cache key.
    mbc = [[Moment(1000, 3000, 0.9, "energy", "x")]]
    plain = build_reel_edl(["a.mp4"], [ClipBeat(0, 0)], mbc)
    weighted = build_reel_edl(["a.mp4"], [ClipBeat(0, 0, weight=1.0)], mbc)
    assert plain.to_dict() == weighted.to_dict()


def test_build_reel_edl_weight_scales_screen_time():
    mbc = [[Moment(1000, 3000, 0.9, "energy", "x")]]  # 2000ms moment
    edl = build_reel_edl(["a.mp4"], [ClipBeat(0, 0, weight=1.5)], mbc)
    assert edl.clips[0].out_ms - edl.clips[0].in_ms == 3000  # 2000 * 1.5


def test_build_reel_edl_weight_floored_for_short_moment():
    from mediahub.video.reel_builder import MIN_WEIGHTED_BEAT_MS

    mbc = [[Moment(0, 1000, 0.9, "energy", "x")]]  # 1000ms, weight 0.6 → 600 < floor
    edl = build_reel_edl(["a.mp4"], [ClipBeat(0, 0, weight=0.6)], mbc)
    assert edl.clips[0].out_ms - edl.clips[0].in_ms == MIN_WEIGHTED_BEAT_MS


# --- multi-beat captions (director depth) ---------------------------------


def _fake_caption_each(src, *, in_ms, out_ms, fps, ground="", onground="", accent=""):
    # one cue per beat, frame 0 of its own window, tagged with the source window
    return {
        "color": "#FFF",
        "scrim": "#000",
        "style": "karaoke",
        "cues": [{"from": 0, "dur": 30, "text": f"{src}:{in_ms}", "words": [{"from": 0, "dur": 15, "text": "w"}]}],
    }


def test_make_reel_captions_multiple_beats_offset_on_timeline():
    res = make_reel(
        ["a.mp4", "b.mp4"],
        with_captions=True,
        caption_beats=2,
        caption_style="karaoke",
        with_reframe=False,
        with_music=False,
        probe_fn=_fake_probe,
        detect_fn=_fake_detect,
        plan_fn=_fake_plan,
        caption_fn=_fake_caption_each,
    )
    cues = res.edl.captions["cues"]
    assert len(cues) == 2  # both beats captioned and merged into one track
    # beat 0 stays at frame 0; beat 1 is offset to its place on the timeline (>0)
    assert cues[0]["from"] == 0
    assert cues[1]["from"] > 0
    # karaoke word stamps are offset with their cue
    assert cues[1]["words"][0]["from"] == cues[1]["from"]
    assert res.manifest["captioned_beats"] == 2
    assert res.manifest["captions"] == "burned-2beats-karaoke"


def test_make_reel_single_caption_path_unchanged():
    # caption_beats=1 keeps the lead-only behaviour (one cue, no offset).
    res = make_reel(
        ["a.mp4", "b.mp4"],
        with_captions=True,
        caption_beats=1,
        with_reframe=False,
        with_music=False,
        probe_fn=_fake_probe,
        detect_fn=_fake_detect,
        plan_fn=_fake_plan,
        caption_fn=_fake_caption_each,
    )
    assert len(res.edl.captions["cues"]) == 1
    assert res.manifest["captioned_beats"] == 1


def test_make_reel_multibeat_skips_silent_beats_honestly():
    # a caption fn that only returns speech for the first clip → 1 captioned, honest
    def lead_only(src, *, in_ms, out_ms, fps, ground="", onground="", accent=""):
        return _fake_caption_each(src, in_ms=in_ms, out_ms=out_ms, fps=fps) if src == "a.mp4" else None

    res = make_reel(
        ["a.mp4", "b.mp4"],
        with_captions=True,
        caption_beats=3,
        with_reframe=False,
        with_music=False,
        probe_fn=_fake_probe,
        detect_fn=_fake_detect,
        plan_fn=_fake_plan,
        caption_fn=lead_only,
    )
    assert res.manifest["captioned_beats"] == 1
    assert len(res.edl.captions["cues"]) == 1


def test_make_reel_beat_syncs_to_music_bpm(monkeypatch):
    import mediahub.visual.audio_mux as am

    monkeypatch.setattr(am, "track_bpm", lambda p: 120.0)  # 120 BPM → 500ms/beat
    res = make_reel(
        ["a.mp4"],
        with_captions=False,
        with_reframe=False,
        with_music=True,
        beat_sync=True,
        probe_fn=_fake_probe,
        detect_fn=lambda *a, **k: [Moment(0, 1800, 0.9, "energy", "x")],
        plan_fn=lambda *a, **k: ReelPlan(order=[ClipBeat(0, 0)], music_mood="x", source="ai"),
        music_fn=lambda *a, **k: "/lib/track.mp3",
    )
    assert res.edl.clips[0].out_ms == 2000  # snapped to the beat grid
    assert res.manifest["beat_synced"] == 120.0


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


def test_clip_maker_remove_fillers_builds_keep_segments():
    # filler spans at 2000-2300 and 4000-4300 → kept speech around them.
    res = clip_maker(
        "a.mp4",
        with_captions=True,
        with_reframe=False,
        remove_fillers=True,
        probe_fn=lambda s: ClipProbe(duration_ms=6000, width=1080, height=1920, has_audio=True),
        filler_fn=lambda src, aggressive=False: [(2000, 2300), (4000, 4300)],
    )
    # the two filler spans split the clip into 3 kept windows
    assert len(res.edl.clips) >= 2
    assert res.manifest["captions"] == "skipped-fillercut"
    assert "fillers" in res.manifest["silence"]


def test_clip_maker_silence_and_fillers_intersect():
    # silence keeps [0,3000],[3500,6000]; fillers cut 1000-1200 → both applied.
    res = clip_maker(
        "a.mp4",
        with_captions=False,
        with_reframe=False,
        remove_silence=True,
        remove_fillers=True,
        probe_fn=lambda s: ClipProbe(duration_ms=6000, width=1080, height=1920, has_audio=True),
        silence_fn=lambda src, dur: [(0, 3000), (3500, 6000)],
        filler_fn=lambda src, aggressive=False: [(1000, 1200)],
    )
    spans = [(c.in_ms, c.out_ms) for c in res.edl.clips]
    # the 1000-1200 filler carves the first silence-kept window in two
    assert any(e <= 1200 for _s, e in spans) and any(s >= 1000 for s, _e in spans)


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
