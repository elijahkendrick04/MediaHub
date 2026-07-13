"""Tests for searxng_client.health() and the /healthz/search endpoint.

Offline: requests.get is faked. Confirms the endpoint plainly reports which
search backend is live, so an operator can tell whether the in-container SearXNG
actually started (vs. silently falling back to DuckDuckGo).
"""

from __future__ import annotations

import pytest
import requests

from mediahub.web_research import searxng_client


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("MEDIAHUB_SEARCH_ENDPOINT", "MEDIAHUB_SEARCH_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    yield


def test_health_unconfigured():
    h = searxng_client.health()
    assert h["engine"] == "duckduckgo"
    assert h["searxng_configured"] is False
    assert h["searxng_reachable"] is False


def test_health_reachable(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://searxng:8888")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200))
    h = searxng_client.health()
    assert h["engine"] == "searxng"
    assert h["searxng_configured"] is True
    assert h["searxng_reachable"] is True


def test_health_unreachable_falls_back(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://searxng:8888")

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(requests, "get", boom)
    h = searxng_client.health()
    assert h["engine"] == "duckduckgo"
    assert h["searxng_configured"] is True
    assert h["searxng_reachable"] is False
    assert "refused" in h["detail"]


def test_health_non_200_falls_back(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SEARCH_ENDPOINT", "http://searxng:8888")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(403))
    h = searxng_client.health()
    assert h["engine"] == "duckduckgo"
    assert h["searxng_reachable"] is False
    assert "403" in h["detail"]


def test_healthz_search_endpoint_operator_sees_backend(monkeypatch, tmp_path):
    """The signed-in operator still gets the live search backend — this is who
    the diagnostic is for."""
    from mediahub.web.web import create_app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as s:
        s["dev_operator"] = True
    r = client.get("/healthz/search")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["engine"] in ("searxng", "duckduckgo")


def test_healthz_search_endpoint_anonymous_hides_backend(monkeypatch, tmp_path):
    """An anonymous caller gets the liveness boolean but NOT which backend is
    live (SearXNG vs DuckDuckGo) — that is a deployment internal (deep-review
    #29). Uptime monitoring still works off `ok`."""
    from mediahub.web.web import create_app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/healthz/search")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "engine" not in data
    assert "searxng_configured" not in data
