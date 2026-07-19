"""Tests for mediahub.memory.learning — the cross-run caption memory loop.

Offline: the cloud embedder is faked with a deterministic hash → vector (so the
same event context always maps to the same vector, identical context => distance
0), and the real sqlite-vec store runs against a temp memory.db. Verifies the
event-context key, capture (incl. the redundancy guard and off-by-default
no-op), recall (off-by-default, cold-start floor, dedup), and store.get_caption.
"""
from __future__ import annotations

import hashlib

import pytest

from mediahub.memory import embedder, learning, store


@pytest.fixture(autouse=True)
def tmp_memory_db(tmp_path, monkeypatch):
    # The store resolves DATA_DIR/memory.db per call now, so point DATA_DIR here.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Quiet env so tests control the knobs explicitly.
    for k in ("MEDIAHUB_MEMORY_MIN_CORPUS", "MEDIAHUB_MEMORY_TOPK"):
        monkeypatch.delenv(k, raising=False)
    yield


def _fake_embed_one(text):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vec = [b / 255.0 for b in h[:8]]
    return embedder.EmbedResult(vectors=[vec], model_id="fake-embed", dim=8)


def _enable(monkeypatch):
    """Make the embedder look configured and deterministic (no network)."""
    monkeypatch.setattr(embedder, "is_configured", lambda: True)
    monkeypatch.setattr(embedder, "embed_one", _fake_embed_one)


# --- canonical_event_context ------------------------------------------------

def test_canonical_event_context_structured():
    ctx = learning.canonical_event_context(
        {"event": "50 Free", "type": "PB", "pb": True, "place": "1", "meet": "County"}
    )
    assert "50 Free" in ctx and "personal best" in ctx and "place 1" in ctx and "County" in ctx


def test_canonical_event_context_headline_fallback():
    assert learning.canonical_event_context({"headline": "Record smashed"}) == "Record smashed"


def test_canonical_event_context_empty():
    assert learning.canonical_event_context({}) == ""


# --- off-by-default ---------------------------------------------------------

def test_capture_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(embedder, "is_configured", lambda: False)
    assert learning.is_enabled() is False
    assert learning.capture("clubA", {"event": "50 Free"}, "nice swim", card_id="c1") is False
    assert store.count(tenant_id="clubA") == 0


def test_recall_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(embedder, "is_configured", lambda: False)
    assert learning.recall("clubA", {"event": "50 Free"}) == []


# --- capture + recall round trip --------------------------------------------

def test_capture_then_recall(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MEMORY_MIN_CORPUS", "1")
    ach = {"event": "100 Fly", "pb": True, "meet": "Regionals"}
    assert learning.capture("clubA", ach, "Huge PB in the fly!", card_id="c1") is True
    # Identical event context → distance 0 → returns the stored caption.
    out = learning.recall("clubA", ach, k=3)
    assert out == ["Huge PB in the fly!"]


def test_recall_cold_start_floor(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MEMORY_MIN_CORPUS", "5")
    ach = {"event": "100 Fly", "pb": True}
    learning.capture("clubA", ach, "cap", card_id="c1")
    # Only 1 stored, floor is 5 → dormant.
    assert learning.recall("clubA", ach) == []
    monkeypatch.setenv("MEDIAHUB_MEMORY_MIN_CORPUS", "1")
    assert learning.recall("clubA", ach) == ["cap"]


def test_capture_redundancy_guard(monkeypatch):
    _enable(monkeypatch)
    calls = {"n": 0}
    real = _fake_embed_one

    def counting_embed(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(embedder, "embed_one", counting_embed)
    ach = {"event": "200 IM", "meet": "Champs"}
    assert learning.capture("clubA", ach, "same caption", card_id="c1") is True
    n_after_first = calls["n"]
    # Same caption again → guard skips the embed + returns False.
    assert learning.capture("clubA", ach, "same caption", card_id="c1") is False
    assert calls["n"] == n_after_first
    # Changed caption → re-embeds + stores.
    assert learning.capture("clubA", ach, "edited caption", card_id="c1") is True
    assert calls["n"] == n_after_first + 1
    assert store.count(tenant_id="clubA") == 1  # still one row (idempotent)


def test_recall_tenant_isolation(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MEMORY_MIN_CORPUS", "1")
    ach = {"event": "50 Free", "pb": True}
    learning.capture("clubA", ach, "A caption", card_id="c1")
    learning.capture("clubB", ach, "B caption", card_id="c1")
    assert learning.recall("clubA", ach) == ["A caption"]
    assert learning.recall("clubB", ach) == ["B caption"]


def test_capture_skips_empty_caption(monkeypatch):
    _enable(monkeypatch)
    assert learning.capture("clubA", {"event": "50 Free"}, "   ", card_id="c1") is False
    assert store.count(tenant_id="clubA") == 0


def test_store_get_caption(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MEMORY_MIN_CORPUS", "1")
    learning.capture("clubA", {"event": "50 Free"}, "stored cap", card_id="c1")
    assert store.get_caption(tenant_id="clubA", entry_id="c1") == "stored cap"
    assert store.get_caption(tenant_id="clubA", entry_id="missing") is None
