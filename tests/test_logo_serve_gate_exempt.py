"""tests/test_logo_serve_gate_exempt.py — logo routes bypass the org-ready gate.

Regression for bug 123b710601c1: organisation_logo_serve and
organisation_logo_mirror were missing from _SETUP_EXEMPT_ENDPOINTS.

Under the enforced org-setup gate, requests with no active organisation are
redirected to /sign-in (HTML).  When the sign-in picker embeds logo <img> tags
pointing at these routes the browser receives HTML instead of an image and
aborts the request with net::ERR_ABORTED.

The fix exempts both routes so the gate skips them; each route's own
_session_can_use_profile IDOR guard still controls access.

These tests assert both routes return a non-redirect response (200 or 404 —
never 302) under the enforced gate with no active org, while a content route
(/make) still redirects as a control.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def gated_client(web_module):
    """App with ENFORCE_ORG_GATE=True and no active org in a clean tmp dir.

    DATA_DIR isolation + one-time web.py import come from the autouse
    ``_isolate_data_dir`` fixture in conftest.py."""
    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield c


def test_organisation_logo_serve_not_gated(gated_client):
    """GET /organisation/<pid>/logo/<lid> returns 404, not a redirect to /sign-in."""
    r = gated_client.get("/organisation/some-club/logo/abc123")
    assert r.status_code == 404, (
        f"expected 404 (route handled, no file) but got {r.status_code}; "
        "a 302 here means the route is still gated"
    )


def test_organisation_logo_mirror_not_gated(gated_client):
    """GET /organisation/<pid>/brand-logo returns 404, not a redirect to /sign-in."""
    r = gated_client.get("/organisation/some-club/brand-logo")
    assert r.status_code == 404, (
        f"expected 404 (no detected logo) but got {r.status_code}; "
        "a 302 here means the route is still gated"
    )


def test_content_route_still_gated(gated_client):
    """Control: a content-production route is still 302-redirected by the gate."""
    r = gated_client.get("/make")
    assert r.status_code in (301, 302), r.status_code
