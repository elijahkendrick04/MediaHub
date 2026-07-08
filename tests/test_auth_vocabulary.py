"""tests/test_auth_vocabulary.py — account vs organisation vocabulary stays
distinct (audit finding A-5).

The app has two separate concepts that used near-identical words:
  * the ACCOUNT session  -> "Log in" / "Log out"
  * the ORGANISATION pick -> "Choose / Switch organisation" / "Leave organisation"

Clicking "Log out" (meaning "switch club") used to end the whole session, and
"Sign in" (org) sat next to "Log in" (account) with no explanation. This pins
the disambiguated vocabulary so the collision can't creep back.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def test_catalogue_keeps_account_and_org_verbs_distinct():
    from mediahub.localize import ui_catalogue as UI

    # Org vocabulary is organisation-scoped, never the account "Sign in/out".
    assert UI.t("nav.sign_in", "en") == "Choose organisation"
    assert UI.t("nav.switch_org", "en") == "Switch organisation"
    assert UI.t("nav.sign_out", "en") == "Leave organisation"
    # Welsh mirrors the split.
    assert UI.t("nav.sign_out", "cy") == "Gadael sefydliad"
    assert UI.t("nav.sign_in", "cy") == "Dewis sefydliad"


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


def test_org_picker_uses_org_vocabulary(client):
    body = client.get("/sign-in").data.decode()
    # The picker is titled with organisation vocabulary...
    assert "Choose your organisation" in body
    # ...and does not present itself as the account "Sign in".
    assert "<h1>Sign in</h1>" not in body


def test_home_hero_secondary_is_account_login(client):
    """A signed-out prospect's secondary CTA is the account log-in, not the
    org picker — so the two vocabularies never collide on the landing page."""
    body = client.get("/").data.decode()
    assert "Log in" in body
    # The org-picker verb must not appear as a hero CTA to a signed-out visitor.
    assert ">Sign in</a>" not in body
