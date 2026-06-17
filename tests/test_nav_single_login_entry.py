"""Regression: nav bar must not show both 'Sign in' and 'Log in' simultaneously.

A fresh unauthenticated visitor has no org session (signed_in=False) and no
billing account session (account_email empty). Previously the nav rendered two
separate auth CTAs — 'Sign in' (org picker) and 'Log in' (billing account) —
with no explanation of the difference.  The expected behaviour is a single
'Log in' entry point; new users discover sign-up via the link on that page.
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
    """Return just the <nav> block so link-counts are scoped to navigation."""
    start = html.find("<nav")
    if start == -1:
        return html
    end = html.find("</nav>", start)
    return html[start : end + 6] if end != -1 else html[start:]


def test_unauthenticated_visitor_sees_only_one_auth_cta(client):
    """Nav must not simultaneously show 'Sign in' and 'Log in' to a fresh visitor."""
    resp = client.get("/")
    assert resp.status_code == 200
    nav = _nav_section(resp.data.decode("utf-8", errors="replace"))

    has_sign_in = ">Sign in<" in nav
    has_log_in = ">Log in<" in nav

    # The two labels must not both be visible to an unauthenticated visitor.
    assert not (
        has_sign_in and has_log_in
    ), (
        "Nav bar shows both 'Sign in' and 'Log in' to an unauthenticated visitor — "
        "this causes UX confusion (no explanation of the difference). "
        "Exactly one auth entry point should be shown."
    )
