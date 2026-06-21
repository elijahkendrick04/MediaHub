"""Tests for video.silence — deterministic dead-air detection + jump-cut plan (1.6).

The parser + planner are pure functions over the FFmpeg ``silencedetect`` text,
so these assert with no binary present; the runner's honest-error is exercised
by stubbing the FFmpeg resolver.
"""

from __future__ import annotations

import pytest

from mediahub.video import silence
from mediahub.video.silence import (
    SilenceUnavailable,
    parse_silences,
    plan_keep_segments,
    removed_ms,
    silencedetect_args,
)


def test_silencedetect_args_carry_threshold_and_duration():
    a = silencedetect_args("clip.mp4", threshold_db=-28, min_silence_ms=700)
    j = " ".join(a)
    assert "silencedetect=noise=-28dB:d=0.700" in j
    assert "-vn" in a  # audio-only analysis


def test_parse_silences_pairs_start_and_end():
    text = (
        "[silencedetect @ x] silence_start: 2.0\n"
        "[silencedetect @ x] silence_end: 4.5 | silence_duration: 2.5\n"
        "[silencedetect @ x] silence_start: 8.0\n"
        "[silencedetect @ x] silence_end: 9.25 | silence_duration: 1.25\n"
    )
    assert parse_silences(text) == [(2000, 4500), (8000, 9250)]


def test_parse_silences_open_ended_is_sentinel():
    # silence running to the end of the clip → end -1 (resolved by the planner).
    assert parse_silences("silence_start: 5.0\n") == [(5000, -1)]


def test_parse_silences_empty():
    assert parse_silences("") == []
    assert parse_silences("no markers here") == []


def test_plan_keep_segments_inverts_and_pads():
    keeps = plan_keep_segments([(2000, 4000), (8000, 9000)], 12000, pad_ms=100, min_keep_ms=300)
    # speech windows: [0,2000], [4000,8000], [9000,12000], padded outward, clamped.
    assert keeps[0] == (0, 2100)
    assert keeps[1] == (3900, 8100)
    assert keeps[2] == (8900, 12000)


def test_plan_keep_segments_drops_slivers():
    # a 100 ms gap between two silences is below min_keep_ms → dropped.
    keeps = plan_keep_segments([(0, 2000), (2100, 4000)], 4000, pad_ms=0, min_keep_ms=300)
    assert keeps == []


def test_plan_keep_segments_open_ended_resolved_against_duration():
    keeps = plan_keep_segments([(8000, -1)], 12000, pad_ms=0, min_keep_ms=300)
    assert keeps == [(0, 8000)]


def test_plan_keep_segments_no_silence_keeps_whole():
    assert plan_keep_segments([], 10000) == [(0, 10000)]


def test_plan_keep_segments_all_silent_keeps_nothing():
    assert plan_keep_segments([(0, 10000)], 10000) == []


def test_removed_ms():
    assert removed_ms([(0, 2000), (4000, 8000)], 10000) == 4000


def test_detect_silences_honest_error_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(silence, "ffmpeg_exe", lambda: None)
    with pytest.raises(SilenceUnavailable):
        silence.detect_silences("clip.mp4")


def test_plan_jump_cuts_falls_back_to_whole_clip(monkeypatch):
    # If detection finds no removable silence, the whole clip is kept (a no-op).
    monkeypatch.setattr(silence, "detect_silences", lambda *a, **k: [])
    assert silence.plan_jump_cuts("clip.mp4", 9000) == [(0, 9000)]
