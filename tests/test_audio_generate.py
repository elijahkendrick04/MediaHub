"""Tests for audio/generate.py — flagged generation slots (roadmap 1.8)."""

from __future__ import annotations

import pytest

from mediahub.audio import generate
from mediahub.audio.generate import GenerationUnavailable


def test_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_MUSIC_GEN_PROVIDER", raising=False)
    monkeypatch.delenv("MEDIAHUB_SFX_GEN_PROVIDER", raising=False)
    assert generate.music_gen_available() is False
    assert generate.sfx_gen_available() is False
    with pytest.raises(GenerationUnavailable):
        generate.generate_music("triumphant reel", out=tmp_path / "m.wav")
    with pytest.raises(GenerationUnavailable):
        generate.generate_sfx("whistle", out=tmp_path / "s.wav")


def test_status_reports_library_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MUSIC_GEN_PROVIDER", raising=False)
    st = generate.generation_status()
    assert st["default"] == "library"
    assert "gemini" in st["recognised_providers"]


def test_unknown_provider_is_honest_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_MUSIC_GEN_PROVIDER", "totally-made-up")
    with pytest.raises(GenerationUnavailable):
        generate.generate_music("x", out=tmp_path / "m.wav")
    assert generate.music_gen_available() is False


def test_recognised_provider_slot_honest_errors_until_wired(monkeypatch, tmp_path):
    # 'gemini' is a recognised slot, but no backend is connected → honest error,
    # never a fabricated clip.
    monkeypatch.setenv("MEDIAHUB_MUSIC_GEN_PROVIDER", "gemini")
    assert generate.music_gen_available() is True
    with pytest.raises(GenerationUnavailable):
        generate.generate_music("triumphant", out=tmp_path / "m.wav")


def test_generation_requires_output_path(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_MUSIC_GEN_PROVIDER", "gemini")
    with pytest.raises(GenerationUnavailable):
        generate.generate_music("x")  # no out=
