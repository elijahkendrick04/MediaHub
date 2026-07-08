"""tests/test_account_delete_ux.py — account deletion is safe and honest
(audit finding E-9).

The Settings delete form's password field lacked `required` (so an empty submit
sailed past the confirm into a full-page "Password check failed" whose only exit
was "Back" to /privacy — not the Settings page they came from), and a successful
delete silently redirected to home with no confirmation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


def _signup(client, email="del@club.org", pw="twelvechars1"):
    client.post("/signup", data={"email": email, "password": pw, "accept_terms": "1"})


def test_settings_delete_form_requires_password(client):
    _signup(client)
    body = client.get("/settings/account").get_data(as_text=True)
    # The password input is required and the form carries a return_to.
    assert 'name="password" required' in body, "delete password must be required (E-9)"
    assert 'name="return_to"' in body


def test_wrong_password_returns_to_origin_not_privacy(client):
    _signup(client)
    r = client.post(
        "/account/delete",
        data={"password": "wrongwrongwrong", "return_to": "/settings/account"},
    )
    assert r.status_code == 403
    body = r.get_data(as_text=True)
    assert "NOT deleted" in body
    # Back-link goes to where they came from, not the hardcoded /privacy.
    assert 'href="/settings/account"' in body


def test_successful_delete_shows_confirmation(client):
    _signup(client, email="bye@club.org")
    r = client.post(
        "/account/delete",
        data={"password": "twelvechars1", "return_to": "/settings/account"},
    )
    # A real confirmation page, not a silent 302 to home.
    assert r.status_code == 200
    assert "has been" in r.get_data(as_text=True) and "deleted" in r.get_data(as_text=True)
