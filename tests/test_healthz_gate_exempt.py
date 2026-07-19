"""tests/test_healthz_gate_exempt.py — health probes bypass the org gate.

Regression for B1-1: /healthz/search and /healthz/breaker were missing
from `_SETUP_EXEMPT_ENDPOINTS`, so under the enforced org-setup gate (no
active organisation) they 302-redirected to /sign-in and returned an HTML
page instead of health JSON. Their /healthz/* siblings were all exempt.

These tests assert both endpoints return 200 (not a redirect) under the
enforced gate, while a content route (/make) still redirects as a control.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_profiles(tmp_path):
    """A clean slate (no active org) under tmp_path. DATA_DIR isolation + the
    one-time web.py import come from the autouse ``_isolate_data_dir`` fixture in
    conftest.py, which points the web module's globals at this test's tmp dir."""
    yield tmp_path


@pytest.fixture
def gated_client(isolated_profiles, web_module):
    """Test client with TESTING=True but ENFORCE_ORG_GATE=True so the
    org-setup gate is actually active."""
    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield c, app


@pytest.mark.parametrize("path", ["/healthz/search", "/healthz/breaker"])
def test_healthz_probe_not_gated(gated_client, path):
    """Health probes return 200 (JSON), not a 302 redirect to /sign-in."""
    c, _ = gated_client
    r = c.get(path)
    assert r.status_code == 200, (path, r.status_code, r.headers.get("Location"))


def test_content_route_still_gated(gated_client):
    """Control: a content route is still redirected by the active gate."""
    c, _ = gated_client
    r = c.get("/make")
    assert r.status_code in (301, 302), r.status_code
