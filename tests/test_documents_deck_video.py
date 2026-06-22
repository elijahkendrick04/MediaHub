"""Document engine (roadmap 1.15) — build 3: deck → MP4 (needs FFmpeg + Chromium)."""

from __future__ import annotations

import pytest

from mediahub.documents import models as m
from mediahub.documents.deck_video import _ffmpeg, deck_to_mp4
from mediahub.documents.models import DocumentSpec, Section

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-accent": "#F2C14E",
    "--mh-surface": "#0B1B2E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
}


def _deck():
    return DocumentSpec(
        title="AGM 2026",
        kind="deck",
        geometry="slide_16_9",
        sections=[
            Section(layout="cover", background="primary", blocks=[m.heading("AGM 2026", 1)]),
            Section(blocks=[m.heading("The year", 2), m.bullet_list(["120 members", "9 medals"])]),
            Section(layout="closing", background="accent", blocks=[m.heading("Thank you", 1)]),
        ],
    )


def test_honest_error_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mediahub.documents.deck_video._ffmpeg", lambda: None)
    with pytest.raises(RuntimeError) as ei:
        deck_to_mp4(_deck(), role_vars=_RV)
    assert "ffmpeg" in str(ei.value).lower()


def test_empty_deck_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        deck_to_mp4(DocumentSpec(title="x", kind="deck", sections=[]), role_vars=_RV)


def test_deck_to_mp4_renders(tmp_path, monkeypatch):
    if _ffmpeg() is None:
        pytest.skip("deck→MP4 needs FFmpeg (install imageio-ffmpeg or put ffmpeg on PATH)")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    try:
        out = deck_to_mp4(_deck(), role_vars=_RV, seconds_per_slide=1.0, fps=12)
    except RuntimeError as e:
        if any(t in str(e).lower() for t in ("chromium", "playwright", "browser")):
            pytest.skip(f"needs Chromium: {e}")
        raise
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[4:8] == b"ftyp"  # MP4 container signature
