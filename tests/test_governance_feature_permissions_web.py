"""Governance 1.23 — role-based feature permissions enforced at AI routes (Build 3).

On a BOUND workspace (one with active members), only roles with the right seat
may spend the org's AI. A viewer is blocked at the caption route with an honest
403; an editor sails through. Pilot/unbound orgs keep the owner seat and are
covered by the metering tests, so this focuses on the bound-org gate.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

ORG = "club-bound"
SWIM = "swim-001"
PW = "correct horse battery"


@pytest.fixture
def app_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_QUOTA_CAPTION"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web import auth, tenancy
    import mediahub.web.web as web_module

    save_profile(ClubProfile(profile_id=ORG, display_name="Bound Club", org_type="swimming_club"))

    # Two real accounts so current_user() resolves (and doesn't drop the session).
    users = auth.UserStore()
    users.create("viewer@club.org", PW)
    users.create("editor@club.org", PW)

    # Binding the org to active members makes it members-only.
    members = tenancy.MembershipStore()
    members.add("viewer@club.org", ORG, role=tenancy.ROLE_VIEWER, status=tenancy.STATUS_ACTIVE)
    members.add("editor@club.org", ORG, role=tenancy.ROLE_EDITOR, status=tenancy.STATUS_ACTIVE)

    achievement = {
        "swim_id": SWIM,
        "swimmer_name": "Emma Davies",
        "event": "200m Backstroke",
        "time": "2:23.45",
        "pb": True,
        "type": "pb",
        "headline": "New PB",
    }
    run = {
        "run_id": "run-1",
        "profile_id": ORG,
        "profile_display": "Bound Club",
        "meet": {"name": "Champs"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [{"rank": 1, "achievement": achievement, "factors": []}],
        },
    }
    monkeypatch.setattr(web_module, "RUNS_DIR", tmp_path / "runs_v4", raising=False)
    (tmp_path / "runs_v4" / "run-1.json").write_text(json.dumps(run), encoding="utf-8")

    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _signed_in(app, email):
    from mediahub.web import auth

    c = app.test_client()
    with c.session_transaction() as sess:
        sess[auth._SESSION_KEY] = email
        sess["active_profile_id"] = ORG
    return c


def _ledger_count():
    from mediahub.observability import feature_quota

    return feature_quota.count_for_org(ORG, feature="caption")


def _url():
    return f"/api/runs/run-1/swim/{SWIM}/caption?tone=ai"


def test_viewer_is_forbidden_and_llm_untouched(app_bound):
    client = _signed_in(app_bound, "viewer@club.org")
    gen = mock.Mock(return_value={"caption": "x", "alt_text": "", "caption_secondary": None,
                                  "secondary_language": None})
    with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch(
        "mediahub.web.ai_caption.generate_caption_bundle", gen
    ):
        resp = client.post(_url())
    assert resp.status_code == 403
    j = resp.get_json()
    assert j["error"] == "forbidden"
    assert "can't use" in j["message"].lower()
    assert gen.call_count == 0  # never reached generation
    assert _ledger_count() == 0  # nothing metered


def test_editor_is_allowed_and_metered(app_bound):
    client = _signed_in(app_bound, "editor@club.org")
    bundle = {"caption": "Emma PB!", "alt_text": "", "caption_secondary": None,
              "secondary_language": None}
    with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch(
        "mediahub.web.ai_caption.generate_caption_bundle", return_value=bundle
    ):
        resp = client.post(_url())
    assert resp.status_code == 200
    assert resp.get_json()["caption"] == "Emma PB!"
    assert _ledger_count() == 1
