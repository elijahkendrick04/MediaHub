"""Tests for mediahub.memory.embedder — cloud-only embeddings.

Offline: requests.post is faked. Verifies off-by-default inertness, the request
shape against an OpenAI-compatible /v1/embeddings endpoint, the Gemini-key
fallback for Google's OpenAI-compat layer, and honest-error behaviour (no
fabricated vectors) on failure.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.memory import embedder


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _emb_payload(*vecs):
    return {"data": [{"embedding": list(v)} for v in vecs]}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("MEDIAHUB_EMBED_ENDPOINT", "MEDIAHUB_EMBED_MODEL", "MEDIAHUB_EMBED_API_KEY",
              "MEDIAHUB_EMBED_TIMEOUT", "MEDIAHUB_LLM_ENDPOINTS", "MEDIAHUB_LLM_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    yield


def test_unconfigured_is_inert():
    assert embedder.is_configured() is False
    with pytest.raises(embedder.EmbedderUnavailable):
        embedder.embed(["hi"])


def test_configured_via_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "text-embedding-3-small")
    assert embedder.is_configured() is True


def test_embed_calls_endpoint(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m-embed")
    monkeypatch.setenv("MEDIAHUB_EMBED_API_KEY", "k")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured.update(url=url, json=json, headers=headers)
        return _FakeResp(200, _emb_payload([0.1, 0.2, 0.3], [0.4, 0.5, 0.6]))

    monkeypatch.setattr(requests, "post", fake_post)
    res = embedder.embed(["a", "b"])
    assert res.dim == 3
    assert res.model_id == "m-embed"
    assert res.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["url"] == "https://host/v1/embeddings"
    assert captured["json"]["model"] == "m-embed"
    assert captured["json"]["input"] == ["a", "b"]
    assert captured["headers"]["Authorization"] == "Bearer k"


def test_falls_back_to_llm_endpoints(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "https://chat/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")
    assert embedder.embed_endpoint() == "https://chat/v1"
    assert embedder.is_configured() is True


def test_gemini_key_fallback_for_google_endpoint(monkeypatch):
    monkeypatch.setenv(
        "MEDIAHUB_EMBED_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "text-embedding-004")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["headers"] = headers
        return _FakeResp(200, _emb_payload([0.1, 0.2]))

    monkeypatch.setattr(requests, "post", fake_post)
    res = embedder.embed(["x"])
    assert captured["headers"]["Authorization"] == "Bearer gem-key"
    assert res.dim == 2


def test_empty_texts_returns_empty(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")
    res = embedder.embed([])
    assert res.vectors == [] and res.dim == 0


def test_http_failure_raises_unavailable(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(500, text="boom")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(embedder.EmbedderUnavailable):
        embedder.embed(["x"])


def test_ragged_dims_raises(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.1]}]})

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(embedder.EmbedderUnavailable):
        embedder.embed(["a", "b"])


def test_vector_count_mismatch_raises(monkeypatch):
    # Fewer vectors than inputs must raise, never silently misalign vector i
    # against text i (#47).
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(200, _emb_payload([0.1, 0.2]))

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(embedder.EmbedderUnavailable, match="1 vectors for 2 inputs"):
        embedder.embed(["a", "b"])


def test_null_vector_row_raises(monkeypatch):
    # A null/empty embedding row must raise, never be dropped (#47) — dropping
    # would shift every later vector off its text.
    monkeypatch.setenv("MEDIAHUB_EMBED_ENDPOINT", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_EMBED_MODEL", "m")

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": None}]})

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(embedder.EmbedderUnavailable, match="empty/null vector row"):
        embedder.embed(["a", "b"])
