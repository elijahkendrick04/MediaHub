"""Governance 1.23 — the dashboard + settings surfaces (Build 4b).

Covers the org-facing /settings/governance section (usage + permission matrix +
provenance note) and the operator-only /healthz/governance per-org view.
"""

from __future__ import annotations

import pytest

ORG = "club-x"


@pytest.fixture
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_QUOTA_CAPTION"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club X", org_type="swimming_club"))

    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _client(app, org=ORG):
    c = app.test_client()
    if org:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = org
    return c


def test_settings_governance_section_renders(app_with_org):
    # Seed some caption usage so the table shows a real number.
    from mediahub.observability import feature_quota

    for _ in range(3):
        feature_quota.record_use(org_id=ORG, feature="caption", ok=True)

    client = _client(app_with_org)
    resp = client.get("/settings/governance")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "AI usage this month" in html
    assert "Who can use AI" in html
    assert "Provenance" in html
    assert "AI captions" in html  # feature label present
    # The permission matrix shows the Viewer row (read-only — no AI).
    assert "Viewer" in html


def test_settings_governance_card_on_landing(app_with_org):
    client = _client(app_with_org)
    html = client.get("/settings").get_data(as_text=True)
    assert "AI governance" in html
    assert "/settings/governance" in html


def test_governance_section_without_org_is_graceful(app_with_org):
    client = _client(app_with_org, org=None)
    resp = client.get("/settings/governance")
    # No active org → a friendly, directive empty state (never a 500): it names
    # the missing club and offers a one-click path to set one up.
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "No club yet" in body
    assert "/organisation/setup" in body


def test_operator_dashboard_requires_operator(app_with_org):
    # A normal session (no operator) is redirected away, not shown tenant data.
    client = _client(app_with_org)
    resp = client.get("/healthz/governance")
    assert resp.status_code in (301, 302)


def test_operator_dashboard_shows_per_org_usage(app_with_org, monkeypatch):
    from mediahub.observability import feature_quota

    feature_quota.record_use(org_id=ORG, feature="caption", ok=True)
    feature_quota.record_use(org_id="club-y", feature="palette", ok=True)

    from mediahub.web import auth

    client = app_with_org.test_client()
    with client.session_transaction() as sess:
        sess[auth._DEV_SESSION_KEY] = True  # operator session

    resp = client.get("/healthz/governance")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "AI governance" in html
    assert ORG in html and "club-y" in html
