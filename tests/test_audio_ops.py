"""Tests for audio/ops.py — deterministic FFmpeg audio edits (roadmap 1.8).

The pure filter/argument builders are tested unconditionally; the runners that
shell out to FFmpeg skip when no binary is available (mirroring
test_audio_mux.py).
"""

from __future__ import annotations

import pytest

from mediahub.audio import library, ops
from mediahub.audio.ops import AudioOpError

_HAS_FFMPEG = ops.ffmpeg_available()
_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary available")


# ---- pure builders --------------------------------------------------------


def test_fade_filter_builds_in_and_out():
    chain = ops.fade_filter(duration_sec=5.0, fade_in=0.5, fade_out=0.6)
    assert "afade=t=in:st=0:d=0.500" in chain
    assert "afade=t=out:st=4.400:d=0.600" in chain


def test_fade_filter_empty_when_no_fades():
    assert ops.fade_filter(duration_sec=5.0) == ""


def test_gain_filter_db_and_unity():
    assert ops.gain_filter(-6.0) == "volume=-6.000dB"
    assert ops.gain_filter(0.0) == ""  # unity is a no-op


def test_speed_filter_chains_out_of_range():
    # 1.0 → empty
    assert ops.speed_filter(1.0) == ""
    # 3.0 needs two atempo stages (2.0 * 1.5)
    chain = ops.speed_filter(3.0)
    assert chain.count("atempo=") == 2
    # 0.25 needs splitting below the 0.5 floor too
    slow = ops.speed_filter(0.25)
    assert slow.count("atempo=") >= 2


def test_speed_filter_clamps():
    assert ops.speed_filter(99.0).count("atempo=") >= 1  # clamped to 4.0
    assert ops.speed_filter(0.01).count("atempo=") >= 1  # clamped to 0.25


def test_trim_args_with_and_without_end():
    a = ops.trim_args(__file__, "out.wav", start=1.0, end=3.0)  # type: ignore[arg-type]
    assert "-ss" in a and "1.000" in a and "-t" in a and "2.000" in a
    b = ops.trim_args(__file__, "out.wav", start=0.5)  # type: ignore[arg-type]
    assert "-t" not in b


def test_convert_and_export_suffix():
    assert ops.export_suffix("mp3") == ".mp3"
    assert ops.export_suffix("wav") == ".wav"
    with pytest.raises(AudioOpError):
        ops.export_suffix("xyz")
    with pytest.raises(AudioOpError):
        ops.convert_args("a", "b", fmt="xyz")  # type: ignore[arg-type]


def test_extract_audio_args_has_vn():
    a = ops.extract_audio_args("clip.mp4", "out.wav", fmt="wav")  # type: ignore[arg-type]
    assert "-vn" in a and "0:a" in a


# ---- runners (need a binary) ---------------------------------------------


def _bed():
    return library.load_library(include_operator=False).get("bed_uplift").path


@_ffmpeg
def test_probe_duration_reads_bed():
    assert abs((ops.probe_duration(_bed()) or 0) - 8.0) < 0.3


@_ffmpeg
def test_trim_produces_expected_length(tmp_path):
    out = tmp_path / "trim.wav"
    ops.trim(_bed(), out, start=0.5, end=2.5)
    assert abs((ops.probe_duration(out) or 0) - 2.0) < 0.2


@_ffmpeg
def test_gain_speed_extract_convert(tmp_path):
    bed = _bed()
    g = tmp_path / "g.wav"
    ops.gain(bed, g, gain_db=-6)
    assert g.stat().st_size > 1000
    s = tmp_path / "s.wav"
    ops.change_speed(bed, s, factor=1.5)
    assert abs((ops.probe_duration(s) or 0) - (8.0 / 1.5)) < 0.3
    m = tmp_path / "x.mp3"
    ops.convert(bed, m, fmt="mp3")
    assert m.stat().st_size > 1000


@_ffmpeg
def test_concat_mix_silence(tmp_path):
    bed = _bed()
    sil = tmp_path / "sil.wav"
    ops.silence(sil, duration_sec=1.0)
    assert abs((ops.probe_duration(sil) or 0) - 1.0) < 0.2
    cat = tmp_path / "cat.wav"
    ops.concat([sil, sil], cat)
    assert abs((ops.probe_duration(cat) or 0) - 2.0) < 0.3
    mixed = tmp_path / "mix.wav"
    ops.mix([bed, sil], mixed)
    assert mixed.stat().st_size > 1000


def test_runners_honest_error_without_binary(monkeypatch, tmp_path):
    # Force "no ffmpeg" and confirm an honest error, never a silent no-op.
    monkeypatch.setattr(ops, "ffmpeg_exe", lambda: None)
    with pytest.raises(AudioOpError):
        ops.trim(tmp_path / "a.wav", tmp_path / "b.wav", start=0)
