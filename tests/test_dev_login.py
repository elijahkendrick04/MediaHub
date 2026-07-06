"""Operator developer sign-in.

Username + password operator access (ADR-0019). Pinned here:
  1. The /developer route and the footer link always exist — no env var needed.
  2. The page asks for a username AND a password (no passwordless one-click).
  3. Correct credentials grant an unrestricted (Owner-plan) session; wrong
     credentials are rejected (401) and grant nothing.
  4. The footer "Developer access" pill is home-page only.
  5. The password is never echoed back into the page.
  6. The baked-in default credential ships only as an argon2id hash — never the
     plaintext password (the repo-secret rule covers tests too, so these tests
     drive the login through a TEST credential set via the env override).
  7. Logout clears the operator session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web import auth as _auth  # noqa: E402

# A throwaway credential used only by this suite (never the real operator
# password) — set via the documented env override so the full sign-in path is
# exercised without putting any real secret in the repo.
TEST_USER = "test-operator"
TEST_PASSWORD = "test-operator-password-123"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signed-sessions")
    monkeypatch.setenv("MEDIAHUB_DEV_USER", TEST_USER)
    monkeypatch.setenv("MEDIAHUB_DEV_PASSWORD_HASH", _auth.hash_password(TEST_PASSWORD))
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


# ---- the page: present, asks for username + password -------------------


def test_route_available_and_asks_for_credentials(client):
    resp = client.get("/developer")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="dev_user"' in body
    assert 'name="dev_password"' in body


def test_footer_link_on_home(client):
    home = client.get("/").get_data(as_text=True)
    assert "Developer access" in home
    assert "/developer" in home


def test_footer_pill_is_home_only(client):
    assert "Developer access" not in client.get("/pricing").get_data(as_text=True)


def test_login_page_links_to_developer(client):
    body = client.get("/login").get_data(as_text=True)
    assert "/developer" in body
    assert "Developer sign-in" in body


# ---- credentials: correct grants, wrong rejected -----------------------


def test_correct_credentials_grant_unrestricted_session(client):
    resp = client.post(
        "/developer",
        data={"dev_user": TEST_USER, "dev_password": TEST_PASSWORD, **_csrf(client)},
    )
    assert resp.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is True
    # The nav now renders operator mode, not "Log in".
    page = client.get("/pricing").get_data(as_text=True)
    assert "Operator mode" in page


def test_operator_login_rotates_session(client):
    """The highest-privilege grant must follow the same session-rotation
    convention as login_post: pre-auth session state is dropped before the
    operator identity is established."""
    csrf = _csrf(client)
    with client.session_transaction() as sess:
        sess["pre_login_marker"] = "planted"
    resp = client.post(
        "/developer",
        data={"dev_user": TEST_USER, "dev_password": TEST_PASSWORD, **csrf},
    )
    assert resp.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert "pre_login_marker" not in sess  # pre-auth state dropped
        assert sess.get("dev_operator") is True


def test_wrong_password_rejected_and_grants_nothing(client):
    resp = client.post(
        "/developer",
        data={"dev_user": TEST_USER, "dev_password": "not-the-password", **_csrf(client)},
    )
    assert resp.status_code == 401
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is None
    assert "not-the-password" not in resp.get_data(as_text=True)


def test_wrong_username_rejected(client):
    resp = client.post(
        "/developer",
        data={"dev_user": "someone-else", "dev_password": TEST_PASSWORD, **_csrf(client)},
    )
    assert resp.status_code == 401
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is None


def test_non_ascii_username_rejected_not_500(client):
    # hmac.compare_digest raises TypeError on non-ASCII str input; the
    # comparison must run on UTF-8 bytes so this returns the 401 error
    # page, not a 500.
    resp = client.post(
        "/developer",
        data={"dev_user": "ékandani", "dev_password": TEST_PASSWORD, **_csrf(client)},
    )
    assert resp.status_code == 401
    with client.session_transaction() as sess:
        assert sess.get("dev_operator") is None


# ---- credential verification unit + secret hygiene ---------------------


def test_verify_dev_credentials_unit(app):
    with app.test_request_context("/"):
        assert _auth.verify_dev_credentials(TEST_USER, TEST_PASSWORD) is True
        assert _auth.verify_dev_credentials(TEST_USER, "wrong") is False
        assert _auth.verify_dev_credentials("wrong", TEST_PASSWORD) is False
        assert _auth.verify_dev_credentials("", "") is False


def test_baked_in_default_is_a_hash_not_plaintext():
    # The committed default credential must be an argon2id hash, never a
    # plaintext password (repo-secret rule).
    assert _auth._DEV_PASSWORD_HASH_DEFAULT.startswith("$argon2id$")
    assert _auth._DEV_USERNAME_DEFAULT == "ekandani"


def test_operator_session_is_premium(app):
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        assert _auth.current_plan() == _auth.PLAN_OWNER
        assert _auth.is_premium() is True


def test_anonymous_visitor_is_not_premium(app):
    with app.test_request_context("/"):
        assert _auth.is_dev_operator() is False
        assert _auth.is_premium() is False


def test_logout_clears_operator_session(app):
    with app.test_request_context("/"):
        from flask import session

        session[_auth._DEV_SESSION_KEY] = True
        assert _auth.is_dev_operator() is True
        _auth.logout_user()
        assert session.get(_auth._DEV_SESSION_KEY) is None
        assert _auth.is_dev_operator() is False
