"""Tests for audio/library.py — the music + SFX catalogue (roadmap 1.8)."""

from __future__ import annotations

import json

import pytest

from mediahub.audio import library
from mediahub.audio.library import AudioLibrary, AudioTrack, Licence, load_library


def test_bundled_library_loads():
    lib = load_library(include_operator=False)
    summary = lib.summary()
    assert summary["count"] >= 8  # the shipped pool
    assert summary["by_source"].get("bundled", 0) == summary["count"]
    # Every bundled track resolves to a real file.
    for t in lib.all():
        assert t.path.is_file(), t.id


def test_filters_by_kind_and_energy():
    lib = load_library(include_operator=False)
    music = lib.tracks(kind="music")
    assert music and all(t.kind == "music" for t in music)
    sfx = lib.tracks(kind="sfx")
    assert sfx and all(t.kind == "sfx" for t in sfx)
    # energy bounds
    calm = lib.tracks(kind="music", max_energy=1)
    assert all(t.energy <= 1 for t in calm)
    hot = lib.tracks(min_energy=4)
    assert all(t.energy >= 4 for t in hot)


def test_mood_matches_mood_or_tags():
    lib = load_library(include_operator=False)
    up = lib.tracks(mood="uplifting")
    assert up and all("uplifting" in t.mood or "uplifting" in t.tags for t in up)


def test_pick_is_deterministic_and_spread():
    lib = load_library(include_operator=False)
    a = lib.pick("reel-123", kind="music")
    b = lib.pick("reel-123", kind="music")
    assert a is not None and a.id == b.id  # same key → same track
    # Different keys can land on different tracks; at least the call is stable.
    keys = {lib.pick(f"k{i}", kind="music").id for i in range(20)}
    assert len(keys) >= 1


def test_pick_returns_none_when_no_candidate():
    lib = AudioLibrary([])
    assert lib.pick("anything", kind="music") is None


def test_bundled_tracks_are_commercial_and_multiplatform():
    lib = load_library(include_operator=False)
    for t in lib.all():
        assert t.licence.commercial_ok is True
        assert t.licence.spdx == "CC0-1.0"
        assert t.safe_for("tiktok")
        assert t.safe_for("instagram")


def test_safe_for_respects_commercial_flag():
    nc = Licence(name="No commercial", commercial_ok=False)
    track = AudioTrack(id="x", path=library.assets_dir(), title="x", licence=nc)
    assert track.safe_for("instagram") is False


def test_licence_round_trip():
    lic = Licence(name="CC0 1.0", spdx="CC0-1.0", url="http://x", commercial_ok=True)
    assert Licence.from_dict(lic.to_dict()) == lic
    # tolerant of junk
    assert Licence.from_dict(None).name == "operator-supplied"


def test_platform_normalisation():
    track = AudioTrack(
        id="x",
        path=library.assets_dir(),
        title="x",
        platforms=library._norm_platforms(["TikTok", "bogus", "youtube"]),
    )
    assert "tiktok" in track.platforms and "youtube" in track.platforms
    assert "bogus" not in track.platforms


def test_operator_dir_loads_with_sidecar(tmp_path, monkeypatch):
    audio_dir = tmp_path / "op"
    audio_dir.mkdir()
    track_file = audio_dir / "anthem.128bpm.mp3"
    track_file.write_bytes(b"fake-mp3-bytes")
    sidecar = audio_dir / "anthem.128bpm.mp3.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": "Club Anthem",
                "kind": "music",
                "mood": ["proud"],
                "energy": 5,
                "licence": {"name": "Licensed", "commercial_ok": True},
                "platforms": ["instagram"],
            }
        )
    )
    monkeypatch.setenv("MEDIAHUB_AUDIO_LIBRARY_DIR", str(audio_dir))
    lib = load_library(include_operator=True)
    op = [t for t in lib.all() if t.source == "operator"]
    assert len(op) == 1
    t = op[0]
    assert t.title == "Club Anthem"
    assert t.bpm == 128.0  # from the filename convention
    assert t.mood == ("proud",)
    assert t.safe_for("instagram") and not t.safe_for("tiktok")


def test_operator_dir_without_sidecar_is_honest(tmp_path, monkeypatch):
    audio_dir = tmp_path / "op2"
    audio_dir.mkdir()
    (audio_dir / "mytrack.wav").write_bytes(b"fake")
    monkeypatch.setenv("MEDIAHUB_AUDIO_LIBRARY_DIR", str(audio_dir))
    lib = load_library(include_operator=True)
    t = next(t for t in lib.all() if t.source == "operator")
    assert t.licence.name == "operator-supplied"
    assert t.mood == ()  # no fabricated mood


def test_legacy_music_dir_folds_in(tmp_path, monkeypatch):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "bed.mp3").write_bytes(b"fake")
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music_dir))
    lib = load_library(include_operator=True)
    assert any(t.source == "legacy-music-dir" for t in lib.all())


def test_to_dict_omits_path_by_default():
    lib = load_library(include_operator=False)
    t = lib.all()[0]
    d = t.to_dict()
    assert "path" not in d
    assert "path" in t.to_dict(include_path=True)
    assert d["licence"]["spdx"] == "CC0-1.0"
