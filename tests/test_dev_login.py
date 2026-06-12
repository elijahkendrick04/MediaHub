"""Operator developer sign-in.

Public, passwordless, unrestricted operator access (ADR-0018). Pinned here:
  1. The /developer route and the footer link ALWAYS exist — no env var needed.
  2. The page is passwordless: a one-click button, no key field.
  3. One click grants an unrestricted (Owner-plan) session that bypasses the
     paywall.
  4. The footer "Developer access" pill is home-page only.
  5. An anonymous visitor (who hasn't clicked through) stays on Free.
  6. Logout clears the operator session.
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
    # No MEDIAHUB_DEV_* vars: developer access must work with zero config.
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    monkeypatch.delenv("MEDIAHUB_DEV_OPEN", raising=False)
    from mediahub.web.web import create_app

    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _csrf(client) -> dict:
    """This suite runs with TESTING unset, so CSRF enforcement is live
    (security/web-hardening) — mint a session token and carry it."""
    token = "devlogin-csrf-token-0123456789ab"
    with client.session_transaction() as sess:
        sess["_csrf"] = token
    return {"csrf_token": token}


# ---- always present, passwordless, no env needed -----------------------


def test_route_always_available_passwordless(client):
    resp = client.get("/developer")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Passwordless: a one-click button, no key field.
    assert 'name="dev_key"' not in body
    assert "Enter unrestricted" in body


def test_footer_link_on_home_without_any_env(client):
    home = client.get("/").get_data(as_text=True)
    assert "Developer access" in home
    assert "/developer" in home


def test_footer_pill_is_home_only(client):
    # The "Developer access" footer pill is home-scoped; it must not appear on
    # other pages' footers.
    assert "Developer access" not in client.get("/pricing").get_data(as_text=True)


def test_login_page_links_to_developer(client):
    body = client.get("/login").get_data(as_text=True)
    assert "/developer" in body
    assert "Developer sign-in" in body


# ---- one click grants the unrestricted session -------------------------


def test_one_click_grants_unrestricted_session(client):
    resp = client.post("/developer", data={**_csrf(client)})  # no key
    assert resp.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is True
    # The nav now renders operator mode (the dev_operator branch), not "Log in".
    page = client.get("/pricing").get_data(as_text=True)
    assert "Operator mode" in page


def test_operator_session_is_premium(app):
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        assert _auth.current_plan() == _auth.PLAN_OWNER
        assert _auth.is_premium() is True
        user = _auth.current_user()
        assert user is not None and user.plan == _auth.PLAN_OWNER


def test_anonymous_visitor_is_not_premium(app):
    with app.test_request_context("/"):
        assert _auth.is_dev_operator() is False
        assert _auth.is_premium() is False  # signed out → Free, gates closed


# ---- logout ------------------------------------------------------------


def test_logout_clears_operator_session(app):
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        _auth.logout_user()
        assert session.get(_auth._DEV_SESSION_KEY) is None
        assert _auth.is_dev_operator() is False
