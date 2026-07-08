"""tests/test_signup_first_run_routing.py — a brand-new signup lands on org
setup, and the sign-in empty state is honest (audit finding A-4).

Before the fix, signup_post redirected to /make, which is not gate-exempt, so
the org-ready gate immediately re-redirected a brand-new (org-less) user to
/sign-in — where the empty state falsely read "No organisation profiles exist
on this deployment yet" (wrong on a shared multi-tenant deployment, and a
small deployment-state leak).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


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


@pytest.fixture
def client(app):
    return app.test_client()


def test_new_signup_lands_on_org_setup(client):
    """A first signup (no invite, no workspace) goes straight to setup, not
    through the /make -> gate -> sign-in bounce."""
    r = client.post(
        "/signup",
        data={"email": "founder@newclub.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    assert r.status_code == 302
    assert "/organisation/setup" in r.headers["Location"], r.headers["Location"]


def test_sign_in_empty_state_is_honest(client):
    """The sign-in empty state no longer claims 'no organisations exist on this
    deployment' — it speaks to the signed-in user's own access."""
    # Sign up (org-less) then hit the picker.
    client.post(
        "/signup",
        data={"email": "founder2@newclub.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    r = client.get("/sign-in")
    assert r.status_code == 200
    body = r.data.decode()
    assert "No organisation profiles exist on this deployment" not in body
    assert "don't have access to any organisation" in body
