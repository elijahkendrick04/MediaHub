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

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """App with ENFORCE_ORG_GATE=True and no active org in a clean tmp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
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
