"""Tests for audio/clean.py — denoise + EBU R128 loudness (roadmap 1.8)."""

from __future__ import annotations

import pytest

from mediahub.audio import clean, library, ops
from mediahub.audio.ops import AudioOpError

_HAS_FFMPEG = ops.ffmpeg_available()
_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary available")


def test_loudnorm_targets():
    assert clean.loudnorm_filter("social") == "loudnorm=I=-14:TP=-1:LRA=11"
    assert clean.loudnorm_filter("voice") == "loudnorm=I=-16:TP=-1.5:LRA=7"
    assert clean.loudnorm_filter("broadcast").startswith("loudnorm=I=-23")


def test_resolve_target_defaults():
    assert clean.resolve_target("nonsense") == "social"
    assert clean.resolve_target("") == "social"
    assert clean.resolve_target("VOICE") == "voice"


def test_denoise_filter_clamps():
    assert clean.denoise_filter(strength=12.0) == "afftdn=nr=12:nt=w"
    assert "nr=97" in clean.denoise_filter(strength=999)
    assert "nr=0.01" in clean.denoise_filter(strength=-5)


def test_rnnoise_model_missing_is_honest_error(monkeypatch, tmp_path):
    # When the operator sets a model path that doesn't exist, denoise must raise
    # rather than silently fall back — checked before any FFmpeg call.
    monkeypatch.setenv("MEDIAHUB_RNNOISE_MODEL", str(tmp_path / "nope.rnnn"))
    with pytest.raises(AudioOpError):
        clean.denoise(tmp_path / "in.wav", tmp_path / "out.wav")


def _bed():
    return library.load_library(include_operator=False).get("bed_uplift").path


@_ffmpeg
def test_normalise_runs(tmp_path):
    out = tmp_path / "norm.wav"
    clean.normalise(_bed(), out, target="social")
    assert out.stat().st_size > 1000


@_ffmpeg
def test_denoise_default_runs(tmp_path):
    out = tmp_path / "den.wav"
    clean.denoise(_bed(), out)
    assert out.stat().st_size > 1000


@_ffmpeg
def test_enhance_voice_pipeline(tmp_path):
    out = tmp_path / "enh.wav"
    clean.enhance_voice(_bed(), out, target="voice")
    assert out.stat().st_size > 1000
