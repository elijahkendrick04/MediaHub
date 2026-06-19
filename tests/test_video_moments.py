"""Tests for video.moments — deterministic highlight detection (roadmap 1.6).

The parsers and ranker are pure, so they run with no FFmpeg. The AI label is
asserted to stay off (and never fabricate) with no provider configured.
"""

from __future__ import annotations

from mediahub.video.moments import (
    EnergyWindow,
    Moment,
    energy_args,
    label_moment,
    parse_astats_energy,
    parse_scene_cuts,
    rank_moments,
    scene_args,
)

_ASTATS = """\
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-40.5
frame:1    pts:44100   pts_time:1
lavfi.astats.Overall.RMS_level=-12.0
frame:2    pts:88200   pts_time:2
lavfi.astats.Overall.RMS_level=-38.0
frame:3    pts:132300  pts_time:3
lavfi.astats.Overall.RMS_level=-inf
"""

_SCENE = """\
frame:10   pts_time:4.0
lavfi.scene_score=0.45
frame:25   pts_time:8.5
lavfi.scene_score=0.62
"""


def test_parse_astats_energy_pairs_pts_with_rms():
    ws = parse_astats_energy(_ASTATS)
    assert [w.start_ms for w in ws] == [0, 1000, 2000, 3000]
    assert ws[1].rms_db == -12.0
    # -inf silence clamps to a finite floor.
    assert ws[3].rms_db == -120.0


def test_parse_scene_cuts_reads_timestamps():
    cuts = parse_scene_cuts(_SCENE)
    assert cuts == [4000, 8500]


def test_parse_scene_cuts_empty_is_empty():
    assert parse_scene_cuts("") == []


def test_rank_picks_loud_window_first():
    energy = parse_astats_energy(_ASTATS)
    moments = rank_moments(energy, [], duration_ms=4000, target_len_ms=2000, max_moments=3)
    assert moments
    # The loudest window (1s, -12dB) should anchor the top moment.
    top = max(moments, key=lambda m: m.score)
    assert top.start_ms <= 1000 <= top.end_ms


def test_rank_boosts_window_containing_a_scene_cut():
    energy = [EnergyWindow(0, -20.0), EnergyWindow(4000, -20.0)]
    # Same energy, but a scene cut at 4s → that window should win.
    moments = rank_moments(
        energy, [4000], duration_ms=8000, target_len_ms=2000, max_moments=1, min_gap_ms=500
    )
    assert len(moments) == 1
    assert moments[0].kind == "energy+scene"
    assert "scene cut" in moments[0].reason


def test_rank_is_deterministic():
    energy = parse_astats_energy(_ASTATS)
    a = rank_moments(energy, [4000], duration_ms=8000, target_len_ms=3000, max_moments=3)
    b = rank_moments(energy, [4000], duration_ms=8000, target_len_ms=3000, max_moments=3)
    assert [m.to_dict() for m in a] == [m.to_dict() for m in b]


def test_rank_chronological_order():
    energy = [EnergyWindow(i * 1000, -10.0 - i) for i in range(8)]
    moments = rank_moments(energy, [], duration_ms=8000, target_len_ms=1500, max_moments=4)
    starts = [m.start_ms for m in moments]
    assert starts == sorted(starts)


def test_rank_flat_silent_clip_keeps_opening():
    moments = rank_moments([], [], duration_ms=6000, target_len_ms=4000)
    assert len(moments) == 1
    assert moments[0].start_ms == 0
    assert "opening" in moments[0].reason


def test_rank_window_clamped_to_clip_bounds():
    energy = [EnergyWindow(9500, -5.0)]  # peak near the very end
    moments = rank_moments(energy, [], duration_ms=10000, target_len_ms=4000, max_moments=1)
    m = moments[0]
    assert m.end_ms <= 10000
    assert m.start_ms >= 0
    assert m.duration_ms <= 4000


def test_energy_and_scene_args_are_pure_builders():
    ea = energy_args("clip.mp4", window_ms=500)
    assert "-i" in ea and "clip.mp4" in ea and "astats" in " ".join(ea)
    sa = scene_args("clip.mp4", threshold=0.4)
    assert "select='gt(scene,0.4)'" in " ".join(sa)


def test_label_moment_silent_without_provider(monkeypatch):
    # No AI provider configured → no label, never a fabricated string.
    import mediahub.media_ai.llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    assert label_moment("audio energy 0.9 at 8s") == ""
