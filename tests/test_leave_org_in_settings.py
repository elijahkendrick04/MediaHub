"""tests/test_leave_org_in_settings.py — the "Leave organisation" exit lives in
Settings → Account, not the top-nav org menu.

The leave-org control was relocated out of the nav dropdown so the exit sits
beside the other session/account actions instead of the nav chrome. Its gate is
unchanged: it is offered only to sessions that can actually leave without the
button being dead-or-looping — the dev operator and anonymous pilot sessions
(the org is pinned in the session, not bound to an account). A signed-in
member's access is bound to their account, so their exit is "Log out"; and when
no org is pinned there is nothing to leave, so the control stays hidden.
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


def _seed_profile(pid="demo-club"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=pid,
            display_name="Demo SC",
            brand_voice_summary="Friendly.",
        )
    )
    return pid


def _pin(client, pid):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = pid


def test_nav_orgmenu_no_longer_carries_leave_org_form(client):
    """An anonymous pilot session sees the org account menu, but the leave-org
    POST form is gone from it — the exit moved to Settings."""
    pid = _seed_profile()
    _pin(client, pid)
    body = client.get("/").get_data(as_text=True)
    # The org account menu still renders (chip + Settings link)...
    assert 'id="active-org-chip"' in body
    assert "/settings" in body
    # ...but the leave-org form no longer lives in the nav chrome.
    assert 'action="/sign-out"' not in body


def test_leave_org_shown_in_settings_account_for_pilot(client):
    """Anonymous pilot (org pinned, no account) — the Settings → Account page
    offers the relocated Leave organisation control."""
    pid = _seed_profile()
    _pin(client, pid)
    body = client.get("/settings/account").get_data(as_text=True)
    assert "Leave organisation" in body
    assert 'action="/sign-out"' in body


def test_leave_org_hidden_for_signed_in_member(client):
    """A member whose access is bound to their account exits via Log out, so
    the leave-org control would be a dead/looping button — keep it hidden."""
    client.post(
        "/signup",
        data={"email": "member@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    pid = _seed_profile()
    _pin(client, pid)  # preserves the signed-in account email in the session
    body = client.get("/settings/account").get_data(as_text=True)
    assert "Leave organisation" not in body
    assert 'action="/sign-out"' not in body


def test_leave_org_hidden_when_no_org_pinned(client):
    """Nothing to leave when no organisation is pinned."""
    body = client.get("/settings/account").get_data(as_text=True)
    assert "Leave organisation" not in body
