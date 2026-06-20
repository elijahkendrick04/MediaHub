"""Tests for the bundled audio assets + manifest integrity (roadmap 1.8).

These guard the shipped CC0 pool: the manifest stays well-formed, every listed
file exists, and every track is genuinely commercial-safe — the promise
``audio/library`` makes to the reel pipeline.
"""

from __future__ import annotations

import json

from mediahub.audio import library
from mediahub.audio.library import KINDS, PLATFORMS


def _manifest() -> dict:
    return json.loads((library.assets_dir() / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_is_wellformed():
    data = _manifest()
    assert data.get("version") == 1
    assert isinstance(data.get("tracks"), list) and data["tracks"]


def test_every_track_has_required_fields_and_file():
    base = library.assets_dir()
    ids = set()
    for entry in _manifest()["tracks"]:
        for key in ("id", "file", "title", "kind", "energy", "licence", "platforms"):
            assert key in entry, key
        assert entry["id"] not in ids, f"duplicate id {entry['id']}"
        ids.add(entry["id"])
        assert (base / entry["file"]).is_file(), entry["file"]
        assert entry["kind"] in KINDS
        assert 1 <= int(entry["energy"]) <= 5
        assert set(entry["platforms"]).issubset(set(PLATFORMS))


def test_bundled_pool_is_all_cc0_commercial():
    for entry in _manifest()["tracks"]:
        lic = entry["licence"]
        assert lic["spdx"] == "CC0-1.0"
        assert lic["commercial_ok"] is True
        assert "first-party" in lic["source"].lower()


def test_pool_has_music_and_sport_sfx():
    data = _manifest()["tracks"]
    kinds = {e["kind"] for e in data}
    assert "music" in kinds
    assert "sfx" in kinds
    # A sport set: a whistle and a splash are the signature ones.
    ids = {e["id"] for e in data}
    assert "sfx_whistle" in ids
    assert "sfx_splash" in ids
