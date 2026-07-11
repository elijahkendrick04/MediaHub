"""Consent / opt-out gating — the compliance/lawful-basis-and-consent capability.

The guarantee under test: a card featuring an opted-out (refused/revoked/
restricted) athlete can NEVER be approved, rendered into a pack, or pass the
publish gate — and in opt-in mode, neither can an athlete with no recorded
consent (with parental consent required for under-18s).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _make_profile(profile_id="clubx", **overrides):
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile = ClubProfile(profile_id=profile_id, display_name="Club X")
    for k, v in overrides.items():
        setattr(profile, k, v)
    save_profile(profile)
    return profile


def _make_run(tmp_path, run_id="run1", profile_id="clubx", athletes=(("c1", "Eira Hughes", 14),)):
    # RUNS_DIR is a module-level global pinned at first import of web.py —
    # write where the app actually reads, not into this test's tmp_path.
    from mediahub.web import web as _webmod

    runs_dir = Path(_webmod.RUNS_DIR)
    ranked = []
    for cid, name, age in athletes:
        ranked.append(
            {
                "rank": 1,
                "achievement": {
                    "type": "pb_confirmed",
                    "swim_id": cid,
                    "swimmer_name": name,
                    "event": "100 Free",
                    "headline": f"{name} set a PB",
                    "confidence": 0.9,
                    "raw_facts": {"time": "57.10", "age": age},
                },
                "safe_to_post": {"level": "safe", "reason": "high confidence"},
            }
        )
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "status": "done",
        "meet": {"name": "Test Meet"},
        "cards": [],
        "recognition_report": {"ranked_achievements": ranked, "n_achievements": len(ranked)},
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run))
    return run


# ---------------------------------------------------------------- registry


def test_registry_roundtrip_and_last_write_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry

    reg = ConsentRegistry("clubx")
    reg.record(athlete_name="Eira Hughes", status="granted", parental=True, under_18=True)
    assert reg.get("eira  hughes").status == "granted"  # normalised match
    reg.record(athlete_name="Eira Hughes", status="revoked")
    rec = reg.get("Eira Hughes")
    assert rec.status == "revoked"
    assert rec.under_18 is True  # carried forward from the previous record
    assert len(reg.all()) == 1


def test_registries_are_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry

    ConsentRegistry("club-a").record(athlete_name="Eira Hughes", status="refused")
    assert ConsentRegistry("club-b").get("Eira Hughes") is None


# ------------------------------------------------------------ decision rules


def test_opt_out_mode_blocks_only_recorded_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import consent_block_reason

    _make_profile("clubx")  # consent_mode unset → opt_out behaviour
    assert consent_block_reason("clubx", "Unknown Athlete", age=14) is None
    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="refused")
    assert "opted out" in consent_block_reason("clubx", "Eira Hughes", age=14)


def test_opt_in_mode_blocks_no_consent_and_requires_parental_for_minors(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import consent_block_reason

    _make_profile("clubx", consent_mode="opt_in")
    # no record at all → blocked
    assert "no recorded consent" in consent_block_reason("clubx", "Eira Hughes", age=14)
    # granted but not parental, minor → blocked
    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="granted", parental=False)
    assert "parental" in consent_block_reason("clubx", "Eira Hughes", age=14)
    # parental grant → allowed
    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="granted", parental=True)
    assert consent_block_reason("clubx", "Eira Hughes", age=14) is None
    # adult with plain grant → allowed
    ConsentRegistry("clubx").record(athlete_name="Sam Adult", status="granted", under_18=False)
    assert consent_block_reason("clubx", "Sam Adult", age=25) is None


def test_unknown_age_treated_as_minor_in_opt_in_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import consent_block_reason

    _make_profile("clubx", consent_mode="opt_in")
    ConsentRegistry("clubx").record(athlete_name="Mystery Swimmer", status="granted", parental=False)
    assert "parental" in consent_block_reason("clubx", "Mystery Swimmer", age=None)


def test_restriction_blocks_in_every_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import consent_block_reason

    _make_profile("clubx")  # opt-out floor
    reg = ConsentRegistry("clubx")
    reg.record(athlete_name="Eira Hughes", status="granted", parental=True)
    reg.set_restricted("Eira Hughes", True)
    assert "restricted" in consent_block_reason("clubx", "Eira Hughes", age=14).lower()
    reg.set_restricted("Eira Hughes", False)
    assert consent_block_reason("clubx", "Eira Hughes", age=14) is None


# ------------------------------------------------------- enforcement points


def test_approval_route_blocks_opted_out_athlete(client, tmp_path):
    _make_profile("clubx")
    _make_run(tmp_path, athletes=(("c1", "Eira Hughes", 14),))
    from mediahub.compliance.consent import ConsentRegistry

    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="refused")

    r = client.post(
        "/api/workflow/run1/c1", json={"action": "set_status", "status": "approved"}
    )
    assert r.status_code == 403
    body = r.get_json()
    assert body["error"] == "consent_blocked"
    assert "opted out" in body["reason"]

    # rejection (non-publishing status) is still allowed — opt-out blocks
    # publication, not the club's internal bookkeeping
    r2 = client.post(
        "/api/workflow/run1/c1", json={"action": "set_status", "status": "rejected"}
    )
    assert r2.status_code == 200


def test_approval_route_allows_consented_athlete(client, tmp_path):
    _make_profile("clubx")
    _make_run(tmp_path, athletes=(("c1", "Eira Hughes", 14),))
    r = client.post(
        "/api/workflow/run1/c1", json={"action": "set_status", "status": "approved"}
    )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_pack_filter_removes_blocked_athletes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import filter_consent_blocked

    _make_profile("clubx")
    run = _make_run(
        tmp_path,
        athletes=(("c1", "Eira Hughes", 14), ("c2", "Amelia Osborne", 15)),
    )
    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="revoked")

    filtered, excluded = filter_consent_blocked("clubx", run)
    kept = [
        ra["achievement"]["swimmer_name"]
        for ra in filtered["recognition_report"]["ranked_achievements"]
    ]
    assert kept == ["Amelia Osborne"]
    assert excluded == ["Eira Hughes"]
    # original run dict untouched
    assert len(run["recognition_report"]["ranked_achievements"]) == 2


# ------------------------------------------------------------------- UI


def test_consent_page_requires_active_org(client):
    assert client.get("/organisation/consent").status_code == 404


def test_consent_settings_and_records_via_ui(client, tmp_path):
    _make_profile("clubx")
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"

    # G-9: the registry lives on /athletes?tab=records; the old URL redirects.
    page = client.get("/organisation/consent", follow_redirects=True)
    assert page.status_code == 200
    assert b"Lawful basis" in page.data

    r = client.post(
        "/organisation/consent/settings",
        data={
            "lawful_basis_publication": "consent",
            "lawful_basis_enrichment": "legitimate_interests",
            "consent_mode": "opt_in",
            "parental_minors": "1",
            "pb_enrichment_enabled": "1",
            "lawful_basis_notes": "Annual membership form 2026",
        },
    )
    assert r.status_code == 302
    from mediahub.web.club_profile import load_profile

    profile = load_profile("clubx")
    assert profile.lawful_basis_publication == "consent"
    assert profile.consent_mode == "opt_in"
    assert profile.consent_require_parental_for_minors is True

    r = client.post(
        "/organisation/consent/record",
        data={
            "athlete_name": "Eira Hughes",
            "status": "granted",
            "parental": "1",
            "under_18": "1",
            "note": "Form signed by parent 2026-06-01",
        },
    )
    assert r.status_code == 302
    from mediahub.compliance.consent import ConsentRegistry

    rec = ConsentRegistry("clubx").get("Eira Hughes")
    assert rec.status == "granted"
    assert rec.parental is True
    assert rec.under_18 is True

    page = client.get("/organisation/consent", follow_redirects=True)
    assert b"Eira Hughes" in page.data


def test_consent_record_validates_input(client, tmp_path):
    _make_profile("clubx")
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"
    r = client.post(
        "/organisation/consent/record", data={"athlete_name": "", "status": "granted"}
    )
    assert r.status_code == 400
    r = client.post(
        "/organisation/consent/record", data={"athlete_name": "X", "status": "bogus"}
    )
    assert r.status_code == 400
