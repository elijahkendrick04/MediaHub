"""tests/test_home_hero_cta.py — Home hero primary CTA must be 'Sign up' for new users.

Regression for: primary hero CTA for a signed-out visitor must link to /signup
with clear 'Sign up' language so first-time visitors have an obvious entry point.
'Sign in' implies an existing account; 'Set up my organisation' is ambiguous and
does not signal account creation. The fix surfaces /signup as the primary action.
"""
from __future__ import annotations

import re

import pytest

from mediahub.web import web as webmod
from mediahub.web.club_profile import ClubProfile, save_profile


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u9_hero_word_cycle.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def zero_org_client(tmp_path, monkeypatch):
    """Fresh deployment with no organisations — signed-out landing."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def orgs_present_client(tmp_path, monkeypatch):
    """Deployment with an existing organisation, viewed signed out."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    save_profile(
        ClubProfile(
            profile_id="riverside",
            display_name="Riverside SC",
            brand_voice_summary="Competitive club.",
            brand_capture_status="ok_heuristic",
        )
    )
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        # No session → signed out
        yield c


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, f"/ → {resp.status_code}"
    return resp.get_data(as_text=True)


def _primary_cta_href(html: str) -> str:
    """Return the href of the first mh-cta-primary anchor."""
    m = re.search(r'<a class="mh-cta-primary" href="([^"]+)"', html)
    assert m, "No mh-cta-primary anchor found in home page"
    return m.group(1)


def _primary_cta_text(html: str) -> str:
    """Return the text content of the first mh-cta-primary anchor."""
    m = re.search(r'<a class="mh-cta-primary"[^>]*>([^<]+)', html)
    assert m, "No mh-cta-primary anchor text found in home page"
    return m.group(1)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class TestSignedOutPrimaryCTA:
    """Primary CTA for a signed-out visitor must always be a clear 'Sign up' link."""

    def test_zero_orgs_primary_cta_is_signup(self, zero_org_client):
        """No-org deployment: primary CTA must link to /signup."""
        body = _home(zero_org_client)
        href = _primary_cta_href(body)
        assert "/signup" in href, (
            f"Expected primary CTA to link to /signup, got {href!r}"
        )

    def test_orgs_present_primary_cta_is_signup_not_setup(self, orgs_present_client):
        """With existing orgs but signed out, primary CTA must be /signup.

        A first-time visitor landing on the home page has no account. 'Set up
        my organisation' is ambiguous (sounds like configuring an existing org)
        and 'Sign in' implies an account already exists. '/signup' is the clear
        entry point for new users.
        """
        body = _home(orgs_present_client)
        href = _primary_cta_href(body)
        assert "/signup" in href, (
            f"Primary CTA must link to /signup (new-user entry point), got {href!r}. "
            "Sign in must not be the primary action for a first-time visitor."
        )

    def test_orgs_present_sign_in_is_still_present_as_secondary(self, orgs_present_client):
        """Sign in link must still appear for returning users, just as secondary."""
        body = _home(orgs_present_client)
        assert "/sign-in" in body, "Sign-in link must still appear on the home page"
        assert 'class="mh-cta-secondary"' in body, "Sign-in must be present as a secondary CTA"

    def test_orgs_present_primary_cta_text_is_signup(self, orgs_present_client):
        """Primary CTA text should say 'Sign up' (not 'Sign in' or 'Set up')."""
        body = _home(orgs_present_client)
        text = _primary_cta_text(body)
        assert "Sign in" not in text, (
            f"Primary CTA text must not say 'Sign in', got {text!r}"
        )
        assert "Sign up" in text, (
            f"Primary CTA text should say 'Sign up', got {text!r}"
        )

    def test_zero_orgs_signup_link_present(self, zero_org_client):
        """Home page must contain a /signup link so new users have a clear entry point."""
        body = _home(zero_org_client)
        assert "/signup" in body, (
            "Home page must link to /signup — new users have no obvious entry point otherwise"
        )

    def test_orgs_present_signup_link_present(self, orgs_present_client):
        """Home page must contain a /signup link even when orgs already exist."""
        body = _home(orgs_present_client)
        assert "/signup" in body, (
            "Home page must link to /signup — new users have no obvious entry point otherwise"
        )
