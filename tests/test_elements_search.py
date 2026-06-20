"""Roadmap 1.10 build 2 — element search (semantic + honest keyword fallback)."""

from __future__ import annotations

import hashlib

import pytest

from mediahub.elements import search


# --------------------------------------------------------------------------- #
# fake embedder (deterministic, no network) — mirrors test_memory_learning
# --------------------------------------------------------------------------- #
def _fake_vec(text: str, dim: int = 16) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in h[:dim]]


class _FakeEmbedResult:
    def __init__(self, vectors, model_id="fake-embed", dim=16):
        self.vectors = vectors
        self.model_id = model_id
        self.dim = dim


def _enable_semantic(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.memory import embedder

    monkeypatch.setattr(embedder, "is_configured", lambda: True)
    monkeypatch.setattr(embedder, "embed_model", lambda: "fake-embed")
    monkeypatch.setattr(embedder, "embed", lambda texts: _FakeEmbedResult([_fake_vec(t) for t in texts]))
    monkeypatch.setattr(embedder, "embed_one", lambda t: _FakeEmbedResult([_fake_vec(t)]))


def _disable_semantic(monkeypatch):
    from mediahub.memory import embedder

    monkeypatch.setattr(embedder, "is_configured", lambda: False)


# --------------------------------------------------------------------------- #
# keyword fallback (no provider)
# --------------------------------------------------------------------------- #
def test_keyword_search_when_no_provider(monkeypatch):
    _disable_semantic(monkeypatch)
    assert search.is_semantic_available() is False
    hits = search.search("trophy")
    assert hits
    assert hits[0].method == "keyword"
    assert any(h.element.id == "pictogram.trophy" for h in hits)


def test_keyword_search_substring(monkeypatch):
    _disable_semantic(monkeypatch)
    hits = search.search("free")  # should still find freestyle via substring
    assert any("freestyle" in h.element.id for h in hits)


def test_empty_query_returns_catalogue(monkeypatch):
    _disable_semantic(monkeypatch)
    hits = search.search("", kind="pictogram")
    assert hits and all(h.element.kind == "pictogram" for h in hits)


def test_kind_filter_applies(monkeypatch):
    _disable_semantic(monkeypatch)
    hits = search.search("", kind="chip")
    assert hits and all(h.element.kind == "chip" for h in hits)


# --------------------------------------------------------------------------- #
# semantic path
# --------------------------------------------------------------------------- #
def test_semantic_search_ranks_and_caches(monkeypatch, tmp_path):
    _enable_semantic(monkeypatch, tmp_path)
    assert search.is_semantic_available() is True
    hits = search.search("award winner")
    assert hits
    assert hits[0].method == "semantic"
    # scores are sorted descending
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    # cache file written under DATA_DIR/element_index
    idx = tmp_path / "element_index"
    assert idx.exists() and any(idx.iterdir())


def test_semantic_reembed_skipped_on_second_call(monkeypatch, tmp_path):
    _enable_semantic(monkeypatch, tmp_path)
    calls = {"n": 0}
    from mediahub.memory import embedder

    real = embedder.embed

    def _counting(texts):
        calls["n"] += 1
        return real(texts)

    monkeypatch.setattr(embedder, "embed", _counting)
    search.search("first call")
    first = calls["n"]
    search.search("second call")
    # second query embeds only the query (via embed_one), not the catalogue again
    assert calls["n"] == first


def test_semantic_falls_back_to_keyword_on_embed_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.memory import embedder

    monkeypatch.setattr(embedder, "is_configured", lambda: True)
    monkeypatch.setattr(embedder, "embed_model", lambda: "fake-embed")

    def _boom(texts):
        raise RuntimeError("embed endpoint down")

    monkeypatch.setattr(embedder, "embed", _boom)
    monkeypatch.setattr(embedder, "embed_one", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    # must not raise — degrades to keyword
    hits = search.search("trophy")
    assert hits and any(h.element.id == "pictogram.trophy" for h in hits)


# --------------------------------------------------------------------------- #
# contextual suggestions
# --------------------------------------------------------------------------- #
def test_suggest_for_gold_medal_context(monkeypatch):
    _disable_semantic(monkeypatch)
    sugg = search.suggest_for_context({"medal_tier": "gold", "event_name": "100 Free"})
    ids = {e.id for e in sugg}
    # gold should surface trophy / rosette / podium-ish elements deterministically
    assert ids & {"pictogram.trophy", "badge.first", "pictogram.podium"}


def test_suggest_for_pb_context(monkeypatch):
    _disable_semantic(monkeypatch)
    sugg = search.suggest_for_context({"is_pb": True})
    ids = {e.id for e in sugg}
    assert ids & {"chip.pb", "pictogram.stopwatch"}


def test_suggest_works_with_empty_context(monkeypatch):
    _disable_semantic(monkeypatch)
    # no signals → still returns a (possibly empty) list, never raises
    out = search.suggest_for_context({})
    assert isinstance(out, list)


def test_context_query_builds_from_facts():
    q = search.context_query({"medal_tier": "gold", "event_name": "200 IM", "is_pb": True})
    assert "gold medal" in q
    assert "200 IM" in q
    assert "personal best" in q
