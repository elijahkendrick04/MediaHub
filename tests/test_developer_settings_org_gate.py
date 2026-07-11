"""Developer settings surfaces stay reachable for the operator before an org exists.

The operator developer area (Settings -> Developer) and the operator-only
dashboards it links to are *deployment* surfaces, not organisation content: an
operator signing in to a fresh deployment must be able to check health, the
deployment status and the AI-governance usage table before any organisation
profile has been created.

Two operator surfaces were being caught by the first-run organisation gate
(``_gate_until_org_ready``) because they were missing from the exemption that
their sibling operator surfaces (``operator_commercial``, ``mobile_parity_tool``,
``healthz_usage``) already carry:

  1. ``/settings/developer`` -- the developer dashboard itself.
  2. ``/healthz/governance`` -- the "AI governance - usage" dashboard linked
     from that page (its sibling ``/healthz/usage`` was exempt; the governance
     twin's own docstring claimed it shared the exemption, but it did not).

For an operator with no ready organisation both used to 302 to
``/organisation/setup`` instead of rendering. These tests pin them reachable
(200) while confirming the operator gate itself is unchanged for non-operators.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_app(tmp_path, monkeypatch):
    """App with the first-run org gate ACTIVE (ENFORCE_ORG_GATE) and no
    organisation on disk -- the exact state a fresh-deployment operator sees."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signed-sessions")
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    return app


@pytest.fixture
def operator_client(gated_app):
    c = gated_app.test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True
    return c


@pytest.fixture
def anon_client(gated_app):
    return gated_app.test_client()


# ---- the developer dashboard itself ------------------------------------


def test_operator_reaches_developer_settings_without_org(operator_client):
    resp = operator_client.get("/settings/developer", follow_redirects=False)
    assert resp.status_code == 200, (
        "operator with no org was bounced to setup: " f"{resp.headers.get('Location')!r}"
    )
    body = resp.get_data(as_text=True)
    # The developer dashboard's own content, not the org-setup page.
    assert "Deployment status" in body
    assert "Clear all caches" in body


def test_operator_reaches_governance_dashboard_without_org(operator_client):
    resp = operator_client.get("/healthz/governance", follow_redirects=False)
    assert resp.status_code == 200, (
        "governance dashboard bounced to setup: " f"{resp.headers.get('Location')!r}"
    )
    assert "AI governance" in resp.get_data(as_text=True)


def test_governance_matches_its_usage_sibling(operator_client):
    """Both operator dashboards linked from the developer page behave the
    same for a no-org operator -- neither is caught by the org gate."""
    usage = operator_client.get("/healthz/usage", follow_redirects=False)
    gov = operator_client.get("/healthz/governance", follow_redirects=False)
    assert usage.status_code == 200
    assert gov.status_code == 200


# ---- the gate is unchanged for everyone else ---------------------------


def test_non_operator_still_cannot_see_developer_settings(anon_client):
    """A non-operator hitting the developer section is redirected away and
    never sees operator content -- the org-gate exemption is not an auth grant."""
    resp = anon_client.get("/settings/developer", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    loc = resp.headers.get("Location", "")
    assert "/settings/developer" not in loc
    assert "Deployment status" not in resp.get_data(as_text=True)


def test_non_operator_governance_redirected(anon_client):
    resp = anon_client.get("/healthz/governance", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)


# ---- the cache-purge action on the developer page ----------------------


def test_operator_cache_purge_runs_without_org(operator_client):
    """The "Clear all caches" button on the (now reachable) developer page
    must actually run for a no-org operator, not 302 to org setup. The handler
    redirects back to the developer section on success; the org gate must not
    swallow the POST first."""
    with operator_client.session_transaction() as s:
        s["_csrf"] = "cachepurge-csrf-token-0123456789"
    resp = operator_client.post(
        "/operator/cache/purge",
        data={"csrf_token": "cachepurge-csrf-token-0123456789"},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)
    # The purge ran and sent us back to the developer section -- NOT bounced to
    # organisation setup by the first-run gate.
    loc = resp.headers.get("Location", "")
    assert "/organisation/setup" not in loc
    assert "/settings/developer" in loc


def test_non_operator_cache_purge_blocked(anon_client):
    """The exemption is not an auth grant: a non-operator's purge POST never
    reaches the purge (it is turned away, and never lands on the developer
    section)."""
    with anon_client.session_transaction() as s:
        s["_csrf"] = "cachepurge-csrf-token-0123456789"
    resp = anon_client.post(
        "/operator/cache/purge",
        data={"csrf_token": "cachepurge-csrf-token-0123456789"},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/settings/developer" not in resp.headers.get("Location", "")


def test_content_route_still_gated_for_operator(operator_client):
    """The exemption is scoped to the operator dashboards; a normal
    content-production route still gates to setup even for the operator."""
    resp = operator_client.get("/upload", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/organisation/setup" in resp.headers.get("Location", "")
