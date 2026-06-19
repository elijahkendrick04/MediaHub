"""Tests for video.matting — the honest-by-default provider seam (roadmap 1.6)."""

from __future__ import annotations

import pytest

from mediahub.video.matting import (
    MAX_SERVER_CLIP_MS,
    MattingUnavailable,
    is_available,
    matting_status,
    remove_background,
    select_matting_provider,
)


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", raising=False)
    assert select_matting_provider() == ""
    assert is_available() is False


def test_unknown_provider_is_honest_error(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", "magic")
    with pytest.raises(MattingUnavailable):
        select_matting_provider()


def test_aliases_resolve(monkeypatch):
    for alias in ("rembg", "local", "modnet"):
        monkeypatch.setenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", alias)
        assert select_matting_provider() == "server"


def test_remove_background_off_is_honest(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", raising=False)
    with pytest.raises(MattingUnavailable):
        remove_background(tmp_path / "in.mp4", tmp_path / "out.mp4")


def test_remove_background_missing_dep_is_honest(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", "server")
    # Provider selected but its dependency/binary absent → honest error.
    monkeypatch.setattr("mediahub.video.matting._provider_available", lambda p: False)
    with pytest.raises(MattingUnavailable):
        remove_background(tmp_path / "in.mp4", tmp_path / "out.mp4")


def test_server_clip_too_long_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", "server")
    monkeypatch.setattr("mediahub.video.matting._provider_available", lambda p: True)
    with pytest.raises(MattingUnavailable):
        remove_background(
            tmp_path / "in.mp4", tmp_path / "out.mp4", duration_ms=MAX_SERVER_CLIP_MS + 1
        )


def test_status_shape(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VIDEO_MATTING_PROVIDER", raising=False)
    s = matting_status()
    assert s["active"] == ""
    assert s["available"] is False
    assert "rembg_available" in s
    assert s["max_server_clip_ms"] == MAX_SERVER_CLIP_MS
