"""UK legal baseline — Art. 32 hardening: auth rate limiting, security
headers, and the LLM prompt pseudonymisation flag (data minimisation)."""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


# ---- rate limiting ----------------------------------------------------------


def test_login_rate_limited_after_budget(app):
    c = app.test_client()
    last = None
    for _ in range(12):
        last = c.post("/login", data={"email": "x@club.org", "password": "wrong-pass"})
    assert last.status_code == 429
    assert "Too many attempts" in last.get_data(as_text=True)


def test_signup_rate_limited_after_budget(app):
    c = app.test_client()
    last = None
    for i in range(12):
        last = c.post(
            "/signup",
            data={"email": f"u{i}@club.org", "password": "short", "accept_terms": "1"},
        )
    assert last.status_code == 429


def test_rate_limit_is_per_ip(app):
    c = app.test_client()
    for _ in range(12):
        c.post("/login", data={"email": "x@club.org", "password": "wrong-pass"})
    # A different source address still gets through (401, not 429).
    r = c.post(
        "/login",
        data={"email": "x@club.org", "password": "wrong-pass"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert r.status_code == 401


# ---- security headers --------------------------------------------------------


def test_security_headers_present(app):
    r = app.test_client().get("/terms")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_hsts_only_when_secure(app):
    c = app.test_client()
    plain = c.get("/terms")
    assert "Strict-Transport-Security" not in plain.headers
    secure = c.get("/terms", base_url="https://mediahub.test")
    assert secure.headers["Strict-Transport-Security"].startswith("max-age=")


# ---- LLM pseudonymisation flag ------------------------------------------------


def _achievement():
    return {
        "swimmer_name": "Jane Smith",
        "event": "100 Free",
        "time": "58.21",
        "pb": True,
        "club": "Sharks",
    }


def test_prompt_carries_name_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_LLM_PSEUDONYMISE", raising=False)
    from mediahub.web import ai_caption

    with mock.patch.object(ai_caption, "call_claude", return_value="Jane Smith flew to a PB!") as m:
        out = ai_caption.generate_caption_for_tone(_achievement())
    assert "Jane Smith" in m.call_args.kwargs["user"]
    assert out == "Jane Smith flew to a PB!"


def test_pseudonymise_flag_strips_name_from_prompt_and_restores_it(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_LLM_PSEUDONYMISE", "1")
    from mediahub.web import ai_caption

    with mock.patch.object(
        ai_caption, "call_claude", return_value="Athlete A stormed to a 100 Free PB!"
    ) as m:
        out = ai_caption.generate_caption_for_tone(_achievement())
    sent = m.call_args.kwargs["user"]
    assert "Jane Smith" not in sent and "Jane" not in sent
    assert "Athlete A" in sent
    # The returned caption has the real name restored locally.
    assert out == "Jane Smith stormed to a 100 Free PB!"
