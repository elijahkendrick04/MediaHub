"""Tests for video.ingest — footage → media library (roadmap 1.6)."""

from __future__ import annotations

import io
import shutil

import pytest

from mediahub.video.ingest import ingest_footage, ingest_footage_stream, is_video_filename
from mediahub.video.probe import ClipProbe

_PROBE = lambda path: ClipProbe(  # noqa: E731
    duration_ms=12000,
    width=1920,
    height=1080,
    fps=30.0,
    has_video=True,
    has_audio=True,
    video_codec="h264",
    audio_codec="aac",
)


class _FakeStore:
    """Minimal media-library store stand-in: captures the saved asset."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.saved = None

    def store_blob(self, data, filename, profile_id):
        p = self.tmp_path / f"{profile_id or '_shared'}_{filename}"
        p.write_bytes(data)
        return p

    def store_blob_stream(self, fileobj, filename, profile_id):
        # Mirror the real store: chunked copy, never the whole file in memory.
        p = self.tmp_path / f"{profile_id or '_shared'}_{filename}"
        with open(p, "wb") as dst:
            shutil.copyfileobj(fileobj, dst)
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


# --- streaming ingest (no full-file buffer in memory) ---------------------


def test_ingest_stream_creates_footage_asset(tmp_path):
    store = _FakeStore(tmp_path)
    src = io.BytesIO(b"\x00\x00\x00\x18ftypmp42rest-of-a-clip")
    asset = ingest_footage_stream(
        src, "race.mp4", profile_id="club_a", store=store, probe_fn=_PROBE
    )
    assert asset.type == "footage" and asset.profile_id == "club_a"
    assert asset.permission_status == "needs_approval"
    assert asset.media_meta["duration_ms"] == 12000
    # the bytes really landed on disk (streamed, not dropped)
    assert (tmp_path / "club_a_race.mp4").read_bytes().startswith(b"\x00\x00\x00\x18ftyp")


def test_ingest_stream_tolerates_probe_failure(tmp_path):
    def _boom(path):
        raise RuntimeError("no ffmpeg")

    asset = ingest_footage_stream(
        io.BytesIO(b"ftypmp42-bytes"),
        "race.mov",
        profile_id="club_a",
        store=_FakeStore(tmp_path),
        probe_fn=_boom,
    )
    assert asset.type == "footage" and asset.media_meta == {}


def test_ingest_stream_rejects_empty_after_copy(tmp_path):
    # Emptiness can't be known before the copy; it's rejected after, and the
    # zero-byte file is cleaned up.
    store = _FakeStore(tmp_path)
    with pytest.raises(ValueError):
        ingest_footage_stream(io.BytesIO(b""), "race.mp4", profile_id="club_a", store=store)
    assert not (tmp_path / "club_a_race.mp4").exists()  # cleaned up


def test_ingest_stream_rejects_non_video(tmp_path):
    with pytest.raises(ValueError):
        ingest_footage_stream(
            io.BytesIO(b"data"), "notes.txt", profile_id="club_a", store=_FakeStore(tmp_path)
        )
