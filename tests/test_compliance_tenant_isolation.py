"""Cross-tenant isolation for the compliance surfaces (security/authn-authz).

Tenant A must never read or mutate tenant B's consent registry, DSR
requests, retention settings, or child-policy settings. Run/card/brand-kit
/media isolation is pinned by the existing suites
(test_run_route_isolation_invariant, test_cross_tenant_access,
test_media_library_profile_isolation); this file covers the surfaces the
compliance programme added.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A"))
    save_profile(ClubProfile(profile_id="org-b", display_name="Org B"))
    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


def _pin(client, profile_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess["active_profile_id"] = profile_id


def test_consent_records_stay_in_own_tenant(client, tmp_path):
    _pin(client, "org-a")
    r = client.post(
        "/organisation/consent/record",
        data={"athlete_name": "Athlete A", "status": "refused"},
    )
    assert r.status_code == 302

    from mediahub.compliance.consent import ConsentRegistry

    assert ConsentRegistry("org-a").get("Athlete A") is not None
    assert ConsentRegistry("org-b").get("Athlete A") is None
    # B's page never shows A's athlete (G-9: the registry now renders on
    # /athletes?tab=records — follow the redirect so the table is actually
    # rendered, not just the 302 body)
    _pin(client, "org-b")
    page = client.get("/organisation/consent", follow_redirects=True)
    assert page.status_code == 200
    assert b"Athlete A" not in page.data


def test_consent_settings_only_mutate_active_tenant(client):
    _pin(client, "org-a")
    client.post("/organisation/consent/settings", data={"consent_mode": "opt_in"})
    from mediahub.web.club_profile import load_profile

    assert load_profile("org-a").consent_mode == "opt_in"
    assert load_profile("org-b").consent_mode == ""


def test_dsr_requests_invisible_and_unrunnable_across_tenants(client):
    _pin(client, "org-a")
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": "Athlete A", "request_type": "erasure"},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    req = DsrRequestLog().all(profile_id="org-a")[0]

    _pin(client, "org-b")
    page = client.get("/organisation/athlete-rights")
    assert req.id.encode() not in page.data  # not listed
    assert client.post(f"/organisation/athlete-rights/{req.id}/run").status_code == 404
    assert (
        client.post(f"/organisation/athlete-rights/{req.id}/clock", data={"op": "stop"}).status_code
        == 404
    )
    # and the request is untouched
    assert DsrRequestLog().get(req.id).status == "open"


def test_erasure_for_one_tenant_leaves_other_tenants_runs_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    shared_name = "Jamie Shared"
    for org, rid in (("org-a", "runA"), ("org-b", "runB")):
        (runs / f"{rid}.json").write_text(
            json.dumps(
                {
                    "run_id": rid,
                    "profile_id": org,
                    "cards": [],
                    "recognition_report": {
                        "ranked_achievements": [
                            {"achievement": {"swim_id": "c1", "swimmer_name": shared_name}}
                        ]
                    },
                }
            )
        )
    from mediahub.compliance.dsr import erase_athlete

    erase_athlete("org-a", shared_name)
    # same-named athlete at another club is a DIFFERENT data subject —
    # org-b's run must be untouched
    run_b = json.loads((runs / "runB.json").read_text())
    assert run_b["recognition_report"]["ranked_achievements"]
    run_a = json.loads((runs / "runA.json").read_text())
    assert not run_a["recognition_report"]["ranked_achievements"]


def test_retention_and_child_policy_settings_scoped(client):
    _pin(client, "org-a")
    client.post("/organisation/consent/retention", data={"runs": "30"})
    client.post("/organisation/consent/child-policy", data={"child_surname_initial": "1"})
    from mediahub.web.club_profile import load_profile

    assert load_profile("org-a").retention_overrides == {"runs": 30}
    assert load_profile("org-a").child_surname_initial is True
    assert load_profile("org-b").retention_overrides == {}
    assert load_profile("org-b").child_surname_initial is False


def test_anonymous_session_cannot_use_tenant_compliance_routes(client):
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get("/organisation/consent").status_code == 404
    assert client.get("/organisation/athlete-rights").status_code == 404
    assert (
        client.post(
            "/organisation/consent/record",
            data={"athlete_name": "X", "status": "refused"},
        ).status_code
        == 404
    )
