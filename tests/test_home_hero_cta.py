"""tests/test_home_hero_cta.py — Home hero primary CTA must be 'Set up' not 'Sign in'.

Regression for: primary hero CTA says 'Sign in' not 'Sign up' when organisations
already exist on the deployment. A first-time visitor has no account — 'Sign in'
as the primary action misleads them. 'Set up my organisation' must always be the
primary CTA for any signed-out visitor, regardless of n_orgs.
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
    m = re.search(r'<a class="mh-cta-primary"[^>]*>([^<]+)</a>', html)
    assert m, "No mh-cta-primary anchor text found in home page"
    return m.group(1)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class TestSignedOutPrimaryCTA:
    """Primary CTA for a signed-out visitor must always point at onboarding."""

    def test_zero_orgs_primary_cta_is_setup(self, zero_org_client):
        """No-org deployment: primary CTA should already be 'Set up my organisation'."""
        body = _home(zero_org_client)
        href = _primary_cta_href(body)
        assert "/organisation/setup" in href, (
            f"Expected primary CTA to link to /organisation/setup, got {href!r}"
        )

    def test_orgs_present_primary_cta_is_setup_not_sign_in(self, orgs_present_client):
        """With existing orgs but signed out, primary CTA must be setup, not sign in.

        A first-time visitor landing on the home page has no account. Making
        'Sign in' the primary action misleads them; 'Set up my organisation'
        is the correct entry point for new users.
        """
        body = _home(orgs_present_client)
        href = _primary_cta_href(body)
        assert "/organisation/setup" in href, (
            f"Primary CTA must link to /organisation/setup (onboarding), got {href!r}. "
            "Sign in must not be the primary action for a first-time visitor."
        )

    def test_orgs_present_sign_in_is_still_present_as_secondary(self, orgs_present_client):
        """Sign in link must still appear for returning users, just as secondary."""
        body = _home(orgs_present_client)
        assert "/sign-in" in body, "Sign-in link must still appear on the home page"
        assert 'class="mh-cta-secondary"' in body, "Sign-in must be present as a secondary CTA"

    def test_orgs_present_primary_cta_text_is_setup(self, orgs_present_client):
        """Primary CTA text should say 'Set up' (not 'Sign in')."""
        body = _home(orgs_present_client)
        text = _primary_cta_text(body)
        assert "Sign in" not in text, (
            f"Primary CTA text must not say 'Sign in', got {text!r}"
        )
        assert "Set up" in text, (
            f"Primary CTA text should say 'Set up my organisation', got {text!r}"
        )
