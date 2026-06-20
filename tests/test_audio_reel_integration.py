"""Tests for the 1.8 bundled-library reel bed wired into the audio mux + motion.

The headline guarantee: the bed is opt-in and byte-parity-safe — with the flag
off, plans and cache keys are exactly the pre-1.8 ones.
"""

from __future__ import annotations

import pytest

from mediahub.audio.library import load_library
from mediahub.visual import audio_mux, motion


@pytest.fixture(autouse=True)
def _clean_audio_env(monkeypatch):
    # Start from a known-silent baseline for every test.
    for var in (
        "MEDIAHUB_VOICEOVER",
        "MEDIAHUB_REEL_MUSIC_DIR",
        "MEDIAHUB_REEL_MUSIC_LIBRARY",
        "MEDIAHUB_REEL_MIX_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)


def test_library_bed_disabled_by_default():
    assert audio_mux.library_bed_enabled() is False
    # No voice, no operator music, flag off → no audio at all (silent path).
    assert audio_mux.audio_active() is False


def test_flag_enables_audio_active(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_LIBRARY", "1")
    assert audio_mux.library_bed_enabled() is True
    assert audio_mux.audio_active() is True


def test_build_plan_byte_identical_when_no_library_track():
    # The historic call (no library_track) must return exactly None on the
    # silent path — the cache-parity guarantee.
    assert audio_mux.build_audio_plan(script="", content_key="reel:x") is None


def test_build_plan_records_library_bed():
    track = load_library(include_operator=False).pick("reel:x", kind="music")
    assert track is not None
    plan = audio_mux.build_audio_plan(script="", content_key="reel:x", library_track=track)
    assert plan is not None
    assert plan["music"] == track.id
    assert plan["music_path"] == str(track.path)
    assert plan["music_source"] == "bundled"


def test_resolve_music_path_uses_absolute_library_path():
    track = load_library(include_operator=False).pick("reel:x", kind="music")
    plan = {"music": track.id, "music_path": str(track.path)}
    assert audio_mux._resolve_music_path(plan) == track.path


def test_resolve_music_path_legacy_name_still_works(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    bed = music / "bed.mp3"
    bed.write_bytes(b"fake")
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music))
    assert audio_mux._resolve_music_path({"music": "bed.mp3"}) == bed


def test_motion_library_bed_for_off_returns_none():
    assert motion._library_bed_for("reel:x") is None  # flag off


def test_motion_library_bed_for_on_picks_bundled(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_LIBRARY", "1")
    track = motion._library_bed_for("reel:meet:3:Maya")
    assert track is not None
    assert track.kind == "music"
    # Deterministic: same key → same pick (cache-stable).
    assert motion._library_bed_for("reel:meet:3:Maya").id == track.id


def test_operator_music_dir_wins_over_library(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    (music / "anthem.mp3").write_bytes(b"fake")
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music))
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_LIBRARY", "1")
    # The operator has their own licensed music → library bed suppressed.
    assert motion._library_bed_for("reel:x") is None
    # build_audio_plan picks the operator track, not any passed library track.
    lib_track = load_library(include_operator=False).pick("reel:x", kind="music")
    plan = audio_mux.build_audio_plan(script="", content_key="reel:x", library_track=lib_track)
    assert plan["music"] == "anthem.mp3"
    assert "music_path" not in plan  # operator track resolved by name in music_dir
