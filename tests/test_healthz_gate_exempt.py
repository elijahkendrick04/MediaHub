"""tests/test_healthz_gate_exempt.py — health probes bypass the org gate.

Regression for B1-1: /healthz/search and /healthz/breaker were missing
from `_SETUP_EXEMPT_ENDPOINTS`, so under the enforced org-setup gate (no
active organisation) they 302-redirected to /sign-in and returned an HTML
page instead of health JSON. Their /healthz/* siblings were all exempt.

These tests assert both endpoints return 200 (not a redirect) under the
enforced gate, while a content route (/make) still redirects as a control.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Redirect the profile store + DATA_DIR under tmp_path so the gate
    sees a clean slate (no active org). The web module is reloaded so its
    module-level globals re-resolve against the fresh tmp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import importlib
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    yield tmp_path


@pytest.fixture
def gated_client(isolated_profiles):
    """Test client with TESTING=True but ENFORCE_ORG_GATE=True so the
    org-setup gate is actually active."""
    import mediahub.web.web as wm
    app = wm.create_app()
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
