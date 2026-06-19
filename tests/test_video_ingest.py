"""Tests for video.ingest — footage → media library (roadmap 1.6)."""

from __future__ import annotations

import pytest

from mediahub.video.ingest import ingest_footage, is_video_filename
from mediahub.video.probe import ClipProbe


class _FakeStore:
    """Minimal media-library store stand-in: captures the saved asset."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.saved = None

    def store_blob(self, data, filename, profile_id):
        p = self.tmp_path / f"{profile_id or '_shared'}_{filename}"
        p.write_bytes(data)
        return p

    def save(self, asset):
        if not asset.id:
            asset.id = "ma_test"
        self.saved = asset
        return asset


def test_is_video_filename():
    assert is_video_filename("race.MP4") is True
    assert is_video_filename("clip.mov") is True
    assert is_video_filename("photo.jpg") is False
    assert is_video_filename("") is False


def test_ingest_creates_footage_asset_with_meta(tmp_path):
    store = _FakeStore(tmp_path)
    probe = lambda path: ClipProbe(  # noqa: E731
        duration_ms=12000,
        width=1920,
        height=1080,
        fps=30.0,
        has_video=True,
        has_audio=True,
        video_codec="h264",
        audio_codec="aac",
    )
    asset = ingest_footage(
        b"\x00\x00\x00\x18ftypmp42rest",
        "race.mp4",
        profile_id="club_a",
        store=store,
        probe_fn=probe,
    )
    assert asset.type == "footage"
    assert asset.permission_status == "needs_approval"  # safeguarding default
    assert asset.profile_id == "club_a"
    assert asset.media_meta["duration_ms"] == 12000
    assert asset.media_meta["has_audio"] is True
    assert asset.width == 1920 and asset.height == 1080


def test_ingest_tolerates_probe_failure(tmp_path):
    store = _FakeStore(tmp_path)

    def _boom(path):
        raise RuntimeError("no ffmpeg")

    asset = ingest_footage(
        b"\x00\x00\x00\x18ftypmp42", "race.mp4", profile_id="club_a", store=store, probe_fn=_boom
    )
    # Stored honestly without measurement rather than rejected.
    assert asset.type == "footage"
    assert asset.media_meta == {}


def test_ingest_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        ingest_footage(b"", "race.mp4", profile_id="club_a", store=_FakeStore(tmp_path))


def test_ingest_rejects_non_video(tmp_path):
    with pytest.raises(ValueError):
        ingest_footage(b"data", "notes.txt", profile_id="club_a", store=_FakeStore(tmp_path))
