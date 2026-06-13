"""Tests for the "Ask the data" web console (club_qa routes).

Offline: answer_club_question is faked, so no LLM happens. Mirrors the
web-research console suite — page render, submit + poll lifecycle, the
empty-question guard, the honest no-provider error, unknown-job 404, and
the per-organisation IDOR guard on the poll endpoint.
"""

from __future__ import annotations

import time
import types

import pytest

from mediahub.club_qa import QAAnswer


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
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


def _wait(client, status_url, tries=200, delay=0.02):
    r = client.get(status_url)
    for _ in range(tries):
        j = r.get_json()
        if not j or j.get("status") != "running":
            return r, j
        time.sleep(delay)
        r = client.get(status_url)
    return r, r.get_json()


def _fake_answer(question, env, **kw):
    return QAAnswer(
        answer="Alice Lee's best is 57.95, set at Spring Open 2026.",
        provider="fake",
        tool_calls=3,
        runs_consulted=[{"run_id": "r1", "meet_name": "Spring Open 2026"}],
    )


def test_console_page_renders(client):
    r = client.get("/club-qa")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Ask the data" in html
    assert 'id="qaform"' in html


def test_submit_empty_question_is_rejected(client):
    r = client.post("/api/club-qa", json={"question": "   "})
    assert r.status_code == 400
    assert r.get_json()["error"] == "empty_question"


def test_submit_then_poll_completes(client, monkeypatch):
    monkeypatch.setattr("mediahub.club_qa.answer_club_question", _fake_answer)
    sub = client.post("/api/club-qa", json={"question": "Alice's best 100 Free?"})
    assert sub.status_code == 200
    body = sub.get_json()
    assert body["ok"] is True and body["status"] == "running"
    assert body["status_url"].endswith(body["job_id"])

    r, j = _wait(client, body["status_url"])
    assert r.status_code == 200
    assert j["ok"] is True and j["status"] == "done"
    assert "57.95" in j["answer"]
    assert j["runs_consulted"] == [{"run_id": "r1", "meet_name": "Spring Open 2026"}]
    assert j["tool_calls"] == 3
    # The owning org id is internal — never echoed to the client.
    assert "profile_id" not in j


def test_no_provider_surfaces_honest_error(client, monkeypatch):
    from mediahub.ai_core import ProviderNotConfigured

    def _boom(question, env, **kw):
        raise ProviderNotConfigured("no provider")

    monkeypatch.setattr("mediahub.club_qa.answer_club_question", _boom)
    sub = client.post("/api/club-qa", json={"question": "q"}).get_json()
    r, j = _wait(client, sub["status_url"])
    assert r.status_code == 500
    assert j["status"] == "error"
    assert "not configured" in j["error"]
    # Never a fabricated answer on provider failure.
    assert "answer" not in j


def test_error_in_agent_surfaces_as_500(client, monkeypatch):
    def _boom(question, env, **kw):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr("mediahub.club_qa.answer_club_question", _boom)
    sub = client.post("/api/club-qa", json={"question": "q"}).get_json()
    r, j = _wait(client, sub["status_url"])
    assert r.status_code == 500
    assert j["status"] == "error"
    assert "exploded" in j["error"]


def test_poll_unknown_job_is_404(client):
    r = client.get("/api/club-qa/deadbeefdeadbeef")
    assert r.status_code == 404
    assert r.get_json()["status"] == "not_found"


def test_job_is_scoped_to_owning_org(client, monkeypatch):
    """A job created by one signed-in org can't be polled by another (IDOR)."""
    monkeypatch.setattr("mediahub.club_qa.answer_club_question", _fake_answer)
    monkeypatch.setattr(
        "mediahub.web.web.load_profile",
        lambda pid: types.SimpleNamespace(profile_id=pid, is_ready=lambda: True) if pid else None,
    )

    with client.session_transaction() as s:
        s["active_profile_id"] = "orgA"
    sub = client.post("/api/club-qa", json={"question": "q"}).get_json()
    r, j = _wait(client, sub["status_url"])
    assert j["status"] == "done"  # orgA can read its own job

    with client.session_transaction() as s:
        s["active_profile_id"] = "orgB"
    r2 = client.get(sub["status_url"])
    assert r2.status_code == 404
    assert r2.get_json()["status"] == "not_found"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
