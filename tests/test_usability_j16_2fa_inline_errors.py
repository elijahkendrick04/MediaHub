"""J-16: 2FA error paths re-render the same form inline — no dead-end pages.

- a wrong code at /login/2fa re-renders the code form with an inline error
  (input cleared + autofocused), not a bare "Try again" interstitial
- /login/2fa carries a "Back to log in" link that clears pending_2fa_email
  and returns to /login
- a wrong code on the enable path re-renders the setup page (QR + secret
  intact) with the error inline
- a wrong code on the disable path re-renders the 2FA-on settings page with
  the error inline
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web import auth as auth_mod
    from mediahub.web.web import create_app

    # lockout + TOTP replay state are process-global — isolate per test
    auth_mod._failed_logins.clear()
    auth_mod._totp_last_counter.clear()
    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


EMAIL = "coach@club.org"
PASSWORD = "twelvechars1"


def _signup(client):
    return client.post(
        "/signup", data={"email": EMAIL, "password": PASSWORD, "accept_terms": "1"}
    )


def _totp_now(secret, step_offset=0):
    from mediahub.web.auth import _totp_code

    return _totp_code(secret, int(time.time() // 30) + step_offset)


def _enable_2fa(client):
    r = client.get("/account/2fa")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    r = client.post("/account/2fa", data={"action": "enable", "totp": _totp_now(secret)})
    assert r.status_code == 200
    return secret


def _park_on_2fa(client):
    client.get("/logout")
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]


def _assert_inline_form(text, *, form_action: str):
    """The failure page IS the form page: inline error + cleared, focused input."""
    assert 'role="alert"' in text
    assert f'action="{form_action}"' in text
    assert 'name="totp"' in text
    assert "autofocus" in text
    assert 'value="' not in text.split('name="totp"')[1][:80]  # input not re-filled


# --------------------------------------------------------------- login path


def test_wrong_login_code_rerenders_form_inline(client):
    _signup(client)
    _enable_2fa(client)
    _park_on_2fa(client)
    r = client.post("/login/2fa", data={"totp": "000000"})
    assert r.status_code == 401
    text = r.get_data(as_text=True)
    _assert_inline_form(text, form_action="/login/2fa")
    assert "did not match" in text
    # the old dead-end interstitial ("Try again" link as the only way on) is gone
    assert ">Try again</a>" not in text
    # still recoverable: the same response carries the way back
    assert "Back to log in" in text


def test_lockout_rerenders_form_with_inline_error(client):
    _signup(client)
    _enable_2fa(client)
    _park_on_2fa(client)
    from mediahub.web import auth as auth_mod

    for _ in range(auth_mod.LOGIN_FAILURE_LIMIT):
        client.post("/login/2fa", data={"totp": "000000"})
    r = client.post("/login/2fa", data={"totp": "000000"})
    assert r.status_code == 429
    text = r.get_data(as_text=True)
    assert 'role="alert"' in text
    assert "Back to log in" in text


def test_back_to_login_link_clears_pending_email(client):
    _signup(client)
    _enable_2fa(client)
    _park_on_2fa(client)
    r = client.get("/login/2fa")
    text = r.get_data(as_text=True)
    assert "Back to log in" in text
    assert "/login/2fa?cancel=1" in text
    r = client.get("/login/2fa?cancel=1")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "pending_2fa_email" not in sess
    # with the pending step abandoned, /login/2fa just bounces to /login
    r = client.get("/login/2fa")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# ------------------------------------------------------- enable/disable path


def test_wrong_enable_code_rerenders_setup_inline(client):
    _signup(client)
    r = client.get("/account/2fa")
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    r = client.post("/account/2fa", data={"action": "enable", "totp": "000000"})
    assert r.status_code == 400
    text = r.get_data(as_text=True)
    _assert_inline_form(text, form_action="/account/2fa")
    assert "did not match" in text
    # the SAME pending secret is still on the page — the user retries in place
    assert secret in text
    assert 'value="enable"' in text
    with client.session_transaction() as sess:
        assert sess["totp_setup_secret"] == secret


def test_wrong_disable_code_rerenders_settings_inline(client):
    _signup(client)
    _enable_2fa(client)
    r = client.post("/account/2fa", data={"action": "disable", "totp": "000000"})
    assert r.status_code == 400
    text = r.get_data(as_text=True)
    _assert_inline_form(text, form_action="/account/2fa")
    assert "switch 2FA off" in text
    # it is the real settings page, not an interstitial
    assert 'value="disable"' in text
    assert "Regenerate recovery codes" in text
    # 2FA is still on
    from mediahub.web.auth import UserStore

    assert UserStore().get(EMAIL).totp_secret
