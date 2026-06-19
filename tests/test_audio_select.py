"""Tests for audio/select.py — AI track selection + honest floor (roadmap 1.8).

The AI is mocked at the ``media_ai.generate_json`` seam so the suite never needs
a real provider. The deterministic floor and the honest-error path are the key
behaviours under test.
"""

from __future__ import annotations

import pytest

import mediahub.media_ai as media_ai
from mediahub.audio import select
from mediahub.audio.library import load_library
from mediahub.audio.select import AudioSelectionUnavailable, describe_arc
from mediahub.media_ai.llm import ClaudeUnavailableError


def _lib():
    return load_library(include_operator=False)


# ---- describe_arc (deterministic) ----------------------------------------


def test_describe_arc_counts_and_moods():
    cards = [
        {"achievement": {"type": "medal"}},
        {"achievement": {"type": "medal"}},
        {"achievement": {"type": "pb"}},
    ]
    arc = describe_arc(cards)
    assert "2 medal" in arc
    assert "1 pb" in arc
    assert "triumphant" in arc  # medal mood
    # deterministic
    assert describe_arc(cards) == arc


def test_describe_arc_handles_empty_and_typeless():
    assert "highlights reel" in describe_arc([])
    assert "highlights reel" in describe_arc([{"foo": "bar"}, {"baz": 1}])


# ---- select_track (AI, mocked) -------------------------------------------


def test_select_track_returns_model_choice(monkeypatch):
    lib = _lib()
    target = lib.tracks(kind="music")[0]
    monkeypatch.setattr(
        media_ai, "generate_json", lambda *a, **k: {"track_id": target.id, "reason": "fits"}
    )
    chosen = select.select_track(lib, cards_props=[{"achievement": {"type": "medal"}}])
    assert chosen.id == target.id


def test_select_track_rejects_invalid_id(monkeypatch):
    lib = _lib()
    monkeypatch.setattr(media_ai, "generate_json", lambda *a, **k: {"track_id": "not-real"})
    with pytest.raises(AudioSelectionUnavailable):
        select.select_track(lib, cards_props=[])


def test_select_track_honest_error_when_no_provider(monkeypatch):
    lib = _lib()

    def _raise(*a, **k):
        raise ClaudeUnavailableError("no provider")

    monkeypatch.setattr(media_ai, "generate_json", _raise)
    with pytest.raises(AudioSelectionUnavailable):
        select.select_track(lib, cards_props=[])


def test_select_track_no_candidates_raises(monkeypatch):
    from mediahub.audio.library import AudioLibrary

    monkeypatch.setattr(media_ai, "generate_json", lambda *a, **k: {"track_id": "x"})
    with pytest.raises(AudioSelectionUnavailable):
        select.select_track(AudioLibrary([]), cards_props=[])


# ---- select_or_default (never raises) ------------------------------------


def test_select_or_default_uses_ai_when_available(monkeypatch):
    lib = _lib()
    target = lib.tracks(kind="music")[-1]
    monkeypatch.setattr(media_ai, "generate_json", lambda *a, **k: {"track_id": target.id})
    sel = select.select_or_default(lib, "reel-1", cards_props=[{"achievement": {"type": "pb"}}])
    assert sel.method == "ai"
    assert sel.track.id == target.id
    assert sel.arc  # recorded for explainability


def test_select_or_default_falls_back_to_deterministic(monkeypatch):
    lib = _lib()

    def _raise(*a, **k):
        raise ClaudeUnavailableError("no provider")

    monkeypatch.setattr(media_ai, "generate_json", _raise)
    sel = select.select_or_default(lib, "reel-1", cards_props=[])
    assert sel.method == "deterministic"
    assert sel.track is not None
    # deterministic → same key, same track
    sel2 = select.select_or_default(lib, "reel-1", cards_props=[])
    assert sel2.track.id == sel.track.id


def test_select_or_default_none_when_pool_empty(monkeypatch):
    from mediahub.audio.library import AudioLibrary

    def _raise(*a, **k):
        raise ClaudeUnavailableError("no provider")

    monkeypatch.setattr(media_ai, "generate_json", _raise)
    sel = select.select_or_default(AudioLibrary([]), "reel-1", cards_props=[])
    assert sel.method == "none"
    assert sel.track is None
