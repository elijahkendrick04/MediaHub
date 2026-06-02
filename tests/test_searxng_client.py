"""Tests for web_research.searxng_client and its WebResearcher integration.

Offline: requests.get is faked. Verifies the JSON client (parse, num cap, honest
failures), off-by-default config, and that WebResearcher prefers SearXNG when
configured but falls back to DuckDuckGo on failure / when unconfigured — adding
no infrastructure and no cost.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.web_research import search as search_mod
from mediahub.web_research import searxng_client
from mediahub.web_research.search import SearchResult, WebResearcher


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text="", raise_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("MEDIAHUB_SEARCH_ENDPOINT", "MEDIAHUB_SEARCH_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    yield


# --- client ----------------------------------------------------------------

def test_unconfigured_inert():
    assert searxng_client.is_configured() is False
    with pytest.raises(searxng_client.SearxngUnavailable):
        searxng_client.search("hi")


def test_configured_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://searxng:8080/")
    assert searxng_client.is_configured() is True
    assert searxng_client.endpoint() == "http://searxng:8080"


def test_search_parses_json(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://searxng:8080")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        captured.update(url=url, params=params)
        return _FakeResp(
            200,
            {
                "results": [
                    {"url": "https://a.com", "title": "A", "content": "snippet A"},
                    {"url": "https://b.com", "title": "B", "content": "snippet B"},
                    {"url": "", "title": "skip-no-url"},
                ]
            },
        )

    monkeypatch.setattr(requests, "get", fake_get)
    out = searxng_client.search("swimmer pb", num=5)
    assert captured["url"] == "http://searxng:8080/search"
    assert captured["params"] == {"q": "swimmer pb", "format": "json"}
    assert [r.url for r in out] == ["https://a.com", "https://b.com"]
    assert out[0].source == "searxng"
    assert out[0].snippet == "snippet A"


def test_search_respects_num(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")
    payload = {"results": [{"url": f"https://{i}.com", "title": str(i)} for i in range(10)]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(200, payload))
    assert len(searxng_client.search("q", num=3)) == 3


def test_search_non_200_raises(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(403, text="json disabled"))
    with pytest.raises(searxng_client.SearxngUnavailable):
        searxng_client.search("q")


def test_search_transport_error_raises(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(searxng_client.SearxngUnavailable):
        searxng_client.search("q")


def test_search_non_json_raises(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(200, raise_json=True))
    with pytest.raises(searxng_client.SearxngUnavailable):
        searxng_client.search("q")


# --- WebResearcher integration ---------------------------------------------

@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(search_mod, "_load_cache", lambda k: None)
    monkeypatch.setattr(search_mod, "_save_cache", lambda k, r: None)
    yield


def _ddg_must_not_run(q, n):
    raise AssertionError("DuckDuckGo should not be called")


def test_webresearcher_prefers_searxng(monkeypatch, no_cache):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")
    monkeypatch.setattr(
        searxng_client, "search", lambda q, num=5: [SearchResult("https://x", "X", "s", "searxng")]
    )
    wr = WebResearcher()
    monkeypatch.setattr(wr, "_check_pplx", lambda: False)
    monkeypatch.setattr(wr, "_search_duckduckgo", _ddg_must_not_run)
    out = wr.search("query", num=3)
    assert [r.source for r in out] == ["searxng"]


def test_webresearcher_falls_back_to_ddg_on_searxng_failure(monkeypatch, no_cache):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://s")

    def boom(q, num=5):
        raise searxng_client.SearxngUnavailable("down")

    monkeypatch.setattr(searxng_client, "search", boom)
    wr = WebResearcher()
    monkeypatch.setattr(wr, "_check_pplx", lambda: False)
    monkeypatch.setattr(
        wr, "_search_duckduckgo", lambda q, n: [SearchResult("https://ddg", "D", "s", "duckduckgo")]
    )
    out = wr.search("query")
    assert [r.source for r in out] == ["duckduckgo"]


def test_webresearcher_unconfigured_uses_ddg(monkeypatch, no_cache):
    called = {"searxng": 0}

    def should_not(q, num=5):
        called["searxng"] += 1
        return []

    monkeypatch.setattr(searxng_client, "search", should_not)
    wr = WebResearcher()
    monkeypatch.setattr(wr, "_check_pplx", lambda: False)
    monkeypatch.setattr(
        wr, "_search_duckduckgo", lambda q, n: [SearchResult("https://ddg", "D", "s", "duckduckgo")]
    )
    out = wr.search("query")
    assert called["searxng"] == 0  # is_configured() False => never called
    assert [r.source for r in out] == ["duckduckgo"]
