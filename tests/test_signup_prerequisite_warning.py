"""tests/test_signup_prerequisite_warning.py — Sign-up page must warn about brand prerequisites.

Regression for: the /signup page gave no indication that the engine requires a
club website, social profiles, and brand guidelines before it can produce any
content.  A new volunteer who signed up without knowing this arrived at the
app with zero context for why nothing worked.

The fix adds a prerequisite sentence to the sign-up page lede so users arrive
prepared rather than stuck.
"""
from __future__ import annotations

import pytest


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


class TestSignupPrerequisiteWarning:
    """The sign-up page must state what users need before the engine produces content."""

    def test_signup_page_mentions_brand_guidelines(self, client):
        """Lede must mention brand guidelines so users know what to prepare."""
        body = client.get("/signup").get_data(as_text=True)
        assert "brand guidelines" in body.lower(), (
            "Sign-up page must mention 'brand guidelines' as a prerequisite — "
            "new users must know the engine needs their brand assets before setup."
        )

    def test_signup_page_mentions_social_profiles(self, client):
        """Lede must mention social profiles as a required input."""
        body = client.get("/signup").get_data(as_text=True)
        assert "social profiles" in body.lower(), (
            "Sign-up page must mention 'social profiles' — users need to know "
            "social media presence is part of the required brand setup."
        )

    def test_signup_page_mentions_club_website(self, client):
        """Lede must mention the club website as a required input."""
        body = client.get("/signup").get_data(as_text=True)
        assert "website" in body.lower(), (
            "Sign-up page must mention 'website' — the engine reads the club "
            "site for brand voice and tone; users must know to have it ready."
        )

    def test_signup_page_still_renders_form(self, client):
        """Prerequisite addition must not break the sign-up form itself."""
        resp = client.get("/signup")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="email"' in body
        assert 'name="password"' in body
        assert 'name="accept_terms"' in body
