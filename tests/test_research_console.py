"""Tests for the web-research console (Capability 3c).

Offline: deep_research is faked, so no real LLM or network happens. Covers the
off-by-default gate, the page render, the background-submit + poll lifecycle
(running -> done), the empty-question guard, the error path, unknown-job 404,
and the per-organisation IDOR guard on the poll endpoint.
"""

from __future__ import annotations

import time
import types

import pytest

from mediahub.web_research.deep_research import ResearchResult


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # Feature off unless a test opts in; job files land in a tmp dir.
    monkeypatch.delenv("MEDIAHUB_RESEARCH_UI", raising=False)
    monkeypatch.setattr("mediahub.web.web.DATA_DIR", tmp_path)
    yield


@pytest.fixture
def client(monkeypatch):
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


def _enable(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESEARCH_UI", "1")


def _wait(client, status_url, tries=200, delay=0.02):
    """Poll until the background job leaves the 'running' state."""
    r = client.get(status_url)
    for _ in range(tries):
        j = r.get_json()
        if not j or j.get("status") != "running":
            return r, j
        time.sleep(delay)
        r = client.get(status_url)
    return r, r.get_json()


def _fake_research(**kw):
    def _run(question, **_):
        return ResearchResult(
            answer="The PB is 25.10, confirmed via the official page.",
            sources=["https://authority.test/x", "https://blog.test/y"],
            authority_sources=["https://authority.test/x"],
            complete=True,
            rounds=2,
            tool_calls=3,
        )

    return _run


# --- off by default ---------------------------------------------------------


def test_disabled_by_default(client):
    assert client.get("/web-research").status_code == 404
    assert client.post("/api/web-research", json={"question": "x"}).status_code == 404
    assert client.get("/api/web-research/whatever").status_code == 404


# --- enabled: page + lifecycle ---------------------------------------------


def test_page_renders_when_enabled(client, monkeypatch):
    _enable(monkeypatch)
    r = client.get("/web-research")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Web research" in html
    assert 'id="rform"' in html  # the question form is present


def test_submit_empty_question_is_rejected(client, monkeypatch):
    _enable(monkeypatch)
    r = client.post("/api/web-research", json={"question": "   "})
    assert r.status_code == 400
    assert r.get_json()["error"] == "empty_question"


def test_submit_then_poll_completes(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("mediahub.web_research.deep_research.deep_research", _fake_research())
    sub = client.post("/api/web-research", json={"question": "what is the pb"})
    assert sub.status_code == 200
    body = sub.get_json()
    assert body["ok"] is True and body["status"] == "running"
    assert body["status_url"].endswith(body["job_id"])

    r, j = _wait(client, body["status_url"])
    assert r.status_code == 200
    assert j["ok"] is True and j["status"] == "done"
    assert "25.10" in j["answer"]
    assert j["sources"] == ["https://authority.test/x", "https://blog.test/y"]
    assert j["authority_sources"] == ["https://authority.test/x"]
    assert j["rounds"] == 2 and j["tool_calls"] == 3
    # The owning org id is internal — never echoed to the client.
    assert "profile_id" not in j


def test_poll_unknown_job_is_404(client, monkeypatch):
    _enable(monkeypatch)
    r = client.get("/api/web-research/deadbeefdeadbeef")
    assert r.status_code == 404
    assert r.get_json()["status"] == "not_found"


def test_error_in_loop_surfaces_as_500(client, monkeypatch):
    _enable(monkeypatch)

    def _boom(question, **_):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr("mediahub.web_research.deep_research.deep_research", _boom)
    sub = client.post("/api/web-research", json={"question": "q"}).get_json()
    r, j = _wait(client, sub["status_url"])
    assert r.status_code == 500
    assert j["status"] == "error"
    assert "exploded" in j["error"]


def test_job_is_scoped_to_owning_org(client, monkeypatch):
    """A job created by one signed-in org can't be polled by another, even
    though the job_id is an unguessable uuid4 (IDOR guard)."""
    _enable(monkeypatch)
    monkeypatch.setattr("mediahub.web_research.deep_research.deep_research", _fake_research())
    # Make any pinned profile id resolve to a ready org.
    monkeypatch.setattr(
        "mediahub.web.web.load_profile",
        lambda pid: types.SimpleNamespace(profile_id=pid, is_ready=lambda: True) if pid else None,
    )

    with client.session_transaction() as s:
        s["active_profile_id"] = "orgA"
    sub = client.post("/api/web-research", json={"question": "q"}).get_json()
    r, j = _wait(client, sub["status_url"])
    assert j["status"] == "done"  # orgA can read its own job

    with client.session_transaction() as s:
        s["active_profile_id"] = "orgB"
    r2 = client.get(sub["status_url"])
    assert r2.status_code == 404
    assert r2.get_json()["status"] == "not_found"
