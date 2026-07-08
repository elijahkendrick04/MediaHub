"""F-7 — the PB Verify screen must speak the audit table's language + a trust key.

The audit table renders the identity match as a friendly label ("Needs check",
"Verified"), but the Verify screen one click deeper showed the raw internal enum
("needs_verification") under "Match status". Both now go through the shared
_pb_match_status_meta map, and a plain-language legend explains confirmed vs
unconfirmed on both surfaces.
"""

from __future__ import annotations

import importlib
import json
import uuid

import pytest


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/api/organisation/active", data={"profile_id": "org-test"})
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


def _seed_legacy_audit_run(tmp_path, wm):
    run_id = "run-f7-" + uuid.uuid4().hex[:8]
    payload = {
        "run_id": run_id,
        "profile_id": "org-test",
        "meet": {"name": "F7 AUDIT MEET"},
        "cards": [],
        "recognition_report": {"ranked_achievements": [], "n_achievements": 0},
        "pb_audit": {
            "run_id": run_id,
            "swimmers_total": 1,
            "swimmers_matched_verified": 0,
            "swimmers_needs_verification": 1,
            "pb_confirmed_count": 0,
            "pb_decisions_count": 0,
            "fetch_total_seconds": 1.0,
            "per_swimmer": [
                {
                    "asa_id": "1382076",
                    "hy3_name": "Eira Hughes",
                    "sr_name": "HUGHES, Eira",
                    "identity": {
                        "asa_id": "1382076",
                        "hy3_name": "Eira Hughes",
                        "method": "needs_verification",
                        "confidence": 0.4,
                        "safe_to_use": False,
                        "notes": ["Two swimmers share this name"],
                    },
                    "events_fetched": [],
                    "pb_decisions": [],
                    "fetch_ok": True,
                }
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-test", "F7 AUDIT MEET", "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


def test_verify_screen_shows_friendly_label_not_raw_enum(audit_env):
    run_id = _seed_legacy_audit_run(audit_env["tmp_path"], audit_env["wm"])
    body = audit_env["client"].get(f"/audit/{run_id}/verify/1382076").get_data(as_text=True)
    assert "Match status" in body
    # The friendly label, never the raw enum.
    assert "Needs check" in body
    assert "needs_verification" not in body


def test_verify_screen_carries_plain_language_trust_key(audit_env):
    run_id = _seed_legacy_audit_run(audit_env["tmp_path"], audit_env["wm"])
    body = audit_env["client"].get(f"/audit/{run_id}/verify/1382076").get_data(as_text=True)
    assert "What do these mean?" in body
    assert "Confirmed PB" in body
    assert "we couldn't confirm the swimmer's ID" in body


def test_audit_page_carries_trust_key_and_no_raw_enum(audit_env):
    run_id = _seed_legacy_audit_run(audit_env["tmp_path"], audit_env["wm"])
    body = audit_env["client"].get(f"/audit/{run_id}").get_data(as_text=True)
    assert "What do these mean?" in body
    # The table shows the friendly label, never the snake_case enum.
    assert "Needs check" in body
    assert "needs_verification" not in body
