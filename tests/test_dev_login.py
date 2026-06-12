"""Operator developer sign-in (Phase C add-on).

An env-gated, unrestricted operator session. Pinned here:
  1. The /developer route and its buttons DO NOT EXIST unless MEDIAHUB_DEV_KEY
     is set — never a public backdoor.
  2. A correct key grants an unrestricted (Owner-plan) session that bypasses the
     paywall; a wrong key is rejected (401) and grants nothing.
  3. Removing MEDIAHUB_DEV_KEY instantly revokes outstanding operator sessions.
  4. The key is never echoed back into the page.
  5. An anonymous visitor stays on Free (gates closed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web import auth as _auth  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signed-sessions")
    from mediahub.web.web import create_app

    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


# ---- disabled when no key configured -----------------------------------



def _csrf(client) -> dict:
    """This suite runs with TESTING unset, so CSRF enforcement is live
    (security/web-hardening) — mint a session token and carry it."""
    token = "devlogin-csrf-token-0123456789ab"
    with client.session_transaction() as sess:
        sess["_csrf"] = token
    return {"csrf_token": token}


def test_route_404s_when_key_unset(client, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    assert client.get("/developer").status_code == 404
    assert client.post("/developer", data={"dev_key": "anything", **_csrf(client)}).status_code == 404


def test_no_button_when_key_unset(client, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    login = client.get("/login").get_data(as_text=True)
    assert "/developer" not in login
    assert "Developer sign-in" not in login


def test_verify_dev_key_false_when_unset(app, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    with app.test_request_context("/"):
        assert _auth.verify_dev_key("anything") is False
        assert _auth.dev_login_enabled() is False


# ---- enabled: form + correct / wrong key -------------------------------


def test_form_renders_when_key_set(client, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    resp = client.get("/developer")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="dev_key"' in body
    # the secret must never be echoed into the page
    assert "s3cret-dev-key" not in body


def test_button_appears_on_login_when_key_set(client, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    body = client.get("/login").get_data(as_text=True)
    assert "/developer" in body


def test_correct_key_grants_unrestricted_session(client, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    resp = client.post("/developer", data={"dev_key": "s3cret-dev-key", **_csrf(client)})
    assert resp.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is True
    # The nav now renders operator mode (the dev_operator branch), not "Log in".
    page = client.get("/pricing").get_data(as_text=True)
    assert "Operator mode" in page


def test_wrong_key_rejected_and_grants_nothing(client, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    resp = client.post("/developer", data={"dev_key": "wrong", **_csrf(client)})
    assert resp.status_code == 401
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is None
    assert "wrong" not in resp.get_data(as_text=True)


# ---- the gate: owner plan bypasses the paywall -------------------------


def test_operator_session_is_premium(app, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        assert _auth.current_plan() == _auth.PLAN_OWNER
        assert _auth.is_premium() is True
        user = _auth.current_user()
        assert user is not None and user.plan == _auth.PLAN_OWNER


def test_anonymous_visitor_is_not_premium(app, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    with app.test_request_context("/"):
        assert _auth.is_dev_operator() is False
        assert _auth.is_premium() is False  # signed out → Free, gates closed


# ---- revocation + logout -----------------------------------------------


def test_removing_key_revokes_outstanding_session(app, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        # The operator pulls the key from the environment to revoke access.
        monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
        assert _auth.is_dev_operator() is False
        assert _auth.is_premium() is False


def test_logout_clears_operator_session(app, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "s3cret-dev-key")
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        _auth.logout_user()
        assert session.get(_auth._DEV_SESSION_KEY) is None
        assert _auth.is_dev_operator() is False
