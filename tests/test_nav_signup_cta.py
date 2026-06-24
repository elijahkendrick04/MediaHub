"""Regression: nav bar must show a 'Sign up' entry point to first-time visitors.

A fresh unauthenticated visitor (no org session, no billing account) must see a
'Sign up' (or 'Get started') link in the primary navigation so they can create
an account.  Previously the nav only showed 'Log in', making the product appear
closed or invite-only to anyone who scanned the header.
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


def _nav_section(html: str) -> str:
    """Return the first <nav …> … </nav> block (primary navigation)."""
    start = html.find("<nav")
    if start == -1:
        return html
    end = html.find("</nav>", start)
    return html[start : end + 6] if end != -1 else html[start:]


def test_unauthenticated_visitor_sees_signup_link_in_nav(client):
    """Nav bar must contain a /signup link for a fresh, unauthenticated visitor."""
    resp = client.get("/")
    assert resp.status_code == 200
    nav = _nav_section(resp.data.decode("utf-8", errors="replace"))

    assert "/signup" in nav, (
        "Nav bar does not contain a /signup link for an unauthenticated visitor. "
        "A first-time user scanning the nav cannot discover how to create an account "
        "— the product appears closed or invite-only."
    )


def test_unauthenticated_visitor_sees_signup_text_in_nav(client):
    """Nav bar must use 'Sign up' or 'Get started' label for the signup link."""
    resp = client.get("/")
    assert resp.status_code == 200
    nav = _nav_section(resp.data.decode("utf-8", errors="replace"))

    has_signup_text = "Sign up" in nav or "Get started" in nav
    assert has_signup_text, (
        "Nav bar does not show 'Sign up' or 'Get started' to an unauthenticated visitor. "
        "The signup link must be clearly labelled so users know they can register."
    )
