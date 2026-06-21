"""Tests for video.waveform — deterministic audio-peak bucketing for the scrubber.

``peaks_from_pcm`` is a pure function over raw PCM, so the bucketing + normalisation
maths is exercised against synthetic samples with no FFmpeg binary present;
``extract_peaks`` is tested with an injected runner.
"""

from __future__ import annotations

import array

import pytest

from mediahub.video import waveform
from mediahub.video.waveform import extract_peaks, peaks_from_pcm, pcm_args


def _pcm(samples: list[int]) -> bytes:
    """Pack signed ints into native-order s16le bytes (matches array('h'))."""
    return array.array("h", samples).tobytes()


def test_pcm_args_builds_mono_s16le_to_stdout():
    args = pcm_args("/clip.mp4", sample_rate=8000)
    assert args[:2] == ["-i", "/clip.mp4"]
    assert "s16le" in args and "-ac" in args and "1" in args and args[-1] == "-"


def test_peaks_normalise_to_global_max():
    # first half quiet (amp 1000), second half loud (amp 4000): with 16 buckets
    # the quiet buckets read ~0.25 and the loud ones normalise to 1.0.
    data = _pcm([1000, -1000] * 50 + [4000, -4000] * 50)
    peaks = peaks_from_pcm(data, buckets=16)
    assert peaks[15] == pytest.approx(1.0)
    assert peaks[0] == pytest.approx(0.25, abs=0.01)  # 1000 / 4000


def test_peaks_silent_pcm_is_flat_zero():
    assert peaks_from_pcm(_pcm([0] * 400), buckets=16) == [0.0] * 16


def test_peaks_empty_and_odd_bytes_are_zero():
    assert peaks_from_pcm(b"", buckets=16) == [0.0] * 16
    assert peaks_from_pcm(b"\x01", buckets=16) == [0.0] * 16  # single dangling byte


def test_peaks_bucket_count_is_clamped():
    data = _pcm([5000] * 1000)
    assert len(peaks_from_pcm(data, buckets=1)) == waveform.MIN_BUCKETS  # floored
    assert len(peaks_from_pcm(data, buckets=99999)) == waveform.MAX_BUCKETS  # capped
    assert len(peaks_from_pcm(data, buckets=120)) == 120


def test_peaks_in_unit_range():
    data = _pcm([i % 9000 - 4500 for i in range(2000)])
    peaks = peaks_from_pcm(data, buckets=64)
    assert all(0.0 <= p <= 1.0 for p in peaks)
    assert max(peaks) == pytest.approx(1.0)  # the loudest bucket normalises to 1


def test_extract_peaks_uses_injected_runner_no_ffmpeg():
    captured = {}

    def fake_runner(args, *, timeout=300):
        captured["args"] = args
        return _pcm([2000, -2000] * 100)

    peaks = extract_peaks("/clip.mp4", buckets=16, runner=fake_runner)
    assert len(peaks) == 16 and max(peaks) == pytest.approx(1.0)
    assert "s16le" in captured["args"]  # the real FFmpeg decode args were built


def test_extract_peaks_empty_audio_is_flat():
    # a clip with no audio stream → empty PCM → honest flat line, not a fake shape
    peaks = extract_peaks("/silent.mp4", buckets=32, runner=lambda *a, **k: b"")
    assert peaks == [0.0] * 32


def test_waveform_unavailable_is_raisable():
    with pytest.raises(waveform.WaveformUnavailable):
        raise waveform.WaveformUnavailable("no ffmpeg")
