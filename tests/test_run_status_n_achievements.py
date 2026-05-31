"""Regression test: /api/runs/<id>/status must include n_achievements when
the run is done, so the run-status page can show a human-readable completion
message ('N moments found — ready to review') instead of exposing the raw
internal flow_result slug.

Bug b07572c63c13: 'live:judged-6-runs' was the only signal available to the
user_brain judge; adding n_achievements to the status payload gives the
run-status poller the count it needs to render a plain-English outcome.
"""
from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def status_app(tmp_path, monkeypatch):
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
    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))

    app = wm.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/api/organisation/active", data={"profile_id": "org-test"})

    yield {"client": client, "wm": wm, "tmp_path": tmp_path}


def _seed_run(fix, n_achievements: int) -> str:
    """Write a run JSON + DB row and return the run_id."""
    wm = fix["wm"]
    tmp_path = fix["tmp_path"]
    run_id = "run-" + uuid.uuid4().hex[:10]
    payload = {
        "run_id": run_id,
        "profile_id": "org-test",
        "meet": {"name": "Test Meet"},
        "cards": [],
        "trust": {},
        "recognition_report": {
            "n_achievements": n_achievements,
            "n_elite": 0, "n_strong": 0, "n_story": 0,
            "n_swims_analysed": 10,
            "ranked_achievements": [],
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-test", "Test Meet", "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


class TestApiStatusNAchievements:
    def test_done_run_includes_n_achievements(self, status_app):
        """A finished run must expose n_achievements in the status payload."""
        run_id = _seed_run(status_app, n_achievements=6)
        r = status_app["client"].get(f"/api/runs/{run_id}/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "done"
        assert "n_achievements" in data, (
            "api_status must include n_achievements when done so the "
            "run-status page can show a human-readable outcome message"
        )
        assert data["n_achievements"] == 6

    def test_done_run_zero_achievements(self, status_app):
        """Zero-achievement runs also get n_achievements=0 in the payload."""
        run_id = _seed_run(status_app, n_achievements=0)
        r = status_app["client"].get(f"/api/runs/{run_id}/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "done"
        assert data.get("n_achievements") == 0

    def test_unknown_run_returns_404(self, status_app):
        """Non-existent run must still return 404 (tenant gate unchanged)."""
        r = status_app["client"].get("/api/runs/no-such-run-xyz/status")
        assert r.status_code == 404

    def test_run_without_recognition_report_defaults_to_zero(self, status_app):
        """A run JSON without recognition_report must not crash; n_achievements=0."""
        wm = status_app["wm"]
        tmp_path = status_app["tmp_path"]
        run_id = "run-" + uuid.uuid4().hex[:10]
        payload = {
            "run_id": run_id,
            "profile_id": "org-test",
            "meet": {"name": "Minimal Meet"},
            "cards": [],
            "trust": {},
            "parse_warnings": [],
            "self_check": {},
            "detector_summary": {},
            "dispatch_log": {},
        }
        (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
        conn = wm._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
            (run_id, "org-test", "Minimal Meet", "minimal.hy3"),
        )
        conn.commit()
        conn.close()

        r = status_app["client"].get(f"/api/runs/{run_id}/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "done"
        assert data.get("n_achievements") == 0
