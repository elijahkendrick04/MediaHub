"""/audit/<run_id> rendering — discovery runs vs legacy identity runs.

Discovery-path audits carry no identity matches, so the page must show the
lookup truth (found / no online history / failed + source link) and must NOT
render the legacy Verify / Ignore controls — those write ASA-id corrections
that only the old SR identity flow reads, promising a re-fetch that never
happens on the discovery pipeline. Legacy persisted runs that do carry
identity data keep the original table and its controls.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    """Fresh DATA_DIR with one club profile and a test client."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-test",
            display_name="Test Club",
            brand_voice_summary="Clear and energetic.",
        )
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


def _seed_run(tmp_path, wm, run_payload):
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-test", run_payload["meet"]["name"], "test.pdf"),
    )
    conn.commit()
    conn.close()
    return run_id


def _base_payload(pb_audit):
    return {
        "run_id": "run-audit-page-" + uuid.uuid4().hex[:8],
        "profile_id": "org-test",
        "profile_display": "Test Club",
        "meet": {"name": "AUDIT PAGE TEST MEET"},
        "cards": [],
        "trust": {},
        "recognition_report": {"ranked_achievements": [], "n_achievements": 0},
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
        "pb_audit": pb_audit,
    }


def _discovery_audit():
    """A discovery-shaped audit: identity None everywhere, lookup truth set."""
    return {
        "run_id": "x",
        "swimmers_total": 3,
        "swimmers_matched_verified": 0,
        "swimmers_needs_verification": 0,
        "swimmers_no_id": 0,
        "swimmers_fetch_failed": 1,
        "swimmers_no_history": 1,
        "pb_decisions_count": 1,
        "pb_confirmed_count": 1,
        "pb_confirmed_official_count": 0,
        "pb_matched_count": 0,
        "pb_likely_count": 0,
        "pb_not_pb_count": 0,
        "pb_unverified_count": 0,
        "pb_suppressed_count": 0,
        "pb_ambiguous_count": 0,
        "fetch_total_seconds": 42.5,
        "fetch_budget_exceeded": False,
        "cache_hits": 1,
        "cache_misses": 2,
        "per_swimmer": [
            {
                "asa_id": "anytown_sc:hughes,eira",
                "hy3_name": "Eira Hughes",
                "sr_name": None,
                "identity": None,
                "events_fetched": ["100FRLC", "200FRLC"],
                "pb_decisions": [
                    {"status": "CONFIRMED_PB_IMPROVEMENT", "event": "100m Freestyle (LC)"}
                ],
                "fetch_ok": True,
                "fetch_error": None,
                "no_history": False,
                "source_urls": ["https://example.org/eira"],
                "fetched_at": "2026-06-01T10:00:00Z",
            },
            {
                "asa_id": "anytown_sc:davies,tom",
                "hy3_name": "Tom Davies",
                "sr_name": None,
                "identity": None,
                "events_fetched": [],
                "pb_decisions": [],
                "fetch_ok": True,
                "fetch_error": None,
                "no_history": True,
                "source_urls": [],
                "fetched_at": None,
            },
            {
                "asa_id": "anytown_sc:price,nia",
                "hy3_name": "Nia Price",
                "sr_name": None,
                "identity": None,
                "events_fetched": [],
                "pb_decisions": [],
                "fetch_ok": False,
                "fetch_error": "web search returned no candidate pages",
                "no_history": False,
                "source_urls": [],
                "fetched_at": None,
            },
        ],
        "warnings": [],
        "started_at": "",
        "finished_at": "",
    }


def _legacy_audit():
    """An old SR-identity audit: identity data present → legacy controls stay."""
    audit = _discovery_audit()
    audit["per_swimmer"] = [
        {
            "asa_id": "1382076",
            "hy3_name": "Eira Hughes",
            "sr_name": "HUGHES, Eira",
            "identity": {
                "asa_id": "1382076",
                "hy3_name": "Eira Hughes",
                "sr_name": "HUGHES, Eira",
                "canonical_hy3_name": "eira hughes",
                "canonical_sr_name": "eira hughes",
                "method": "needs_verification",
                "confidence": 0.4,
                "safe_to_use": False,
                "notes": [],
                "alternative_matches": [],
            },
            "events_fetched": [],
            "pb_decisions": [],
            "fetch_ok": True,
            "fetch_error": None,
            "source_urls": [],
            "fetched_at": None,
        }
    ]
    return audit


class TestDiscoveryAuditPage:
    def test_lookup_truth_rendered_without_dead_controls(self, audit_env):
        wm, tmp_path, client = audit_env["wm"], audit_env["tmp_path"], audit_env["client"]
        run_id = _seed_run(tmp_path, wm, _base_payload(_discovery_audit()))

        r = client.get(f"/audit/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        # Lookup truth per swimmer
        assert "Found 2 events" in body
        assert "No online history" in body
        assert "https://example.org/eira" in body
        # The failed lookup is labelled as such, with the reason
        assert "Failed" in body
        assert "web search returned no candidate pages" in body
        # Dead legacy controls must NOT render on a discovery audit
        assert "Ignore PBs" not in body
        assert ">Verify<" not in body
        # And the always-zero identity stats are replaced by lookup stats
        assert "Lookups failed" in body
        assert "Needs verification" not in body

    def test_legacy_identity_audit_keeps_verify_controls(self, audit_env):
        wm, tmp_path, client = audit_env["wm"], audit_env["tmp_path"], audit_env["client"]
        run_id = _seed_run(tmp_path, wm, _base_payload(_legacy_audit()))

        r = client.get(f"/audit/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        assert ">Verify<" in body
        assert "Ignore PBs" in body
        assert "Needs verification" in body

    def test_review_panel_splits_no_history_from_failures(self, audit_env):
        wm, tmp_path, client = audit_env["wm"], audit_env["tmp_path"], audit_env["client"]
        run_id = _seed_run(tmp_path, wm, _base_payload(_discovery_audit()))

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "No online history" in body
        assert "Lookups failed" in body
