"""Async reel rendering — /reel-job + /api/reel-jobs/<id> + /reel-file.

The synchronous /reel route holds the HTTP connection for the whole
30–90s first render, which front-line proxies kill — the button then
"does nothing". The async flow kicks a background job, polls for the
outcome, and streams the finished MP4 from a file route that never
triggers a render.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_env(tmp_path, monkeypatch):
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

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))

    run = {
        "run_id": "r1",
        "profile_id": "alpha",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
            ]
        },
    }
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, wm, tmp_path


def _poll_until_settled(client, poll_url, tries=60, delay=0.2):
    j = {}
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


class TestReelJob:
    def test_job_renders_and_file_streams(self, app_env, tmp_path):
        app, wm, _ = app_env
        out_dir = wm.RUNS_DIR / "r1" / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp4 = out_dir / "reel_3.mp4"
        mp4.write_bytes(b"0" * 2048)

        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_meet_reel", return_value=mp4):
                resp = c.post("/api/runs/r1/reel-job")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["ok"] and body["poll_url"]
                j = _poll_until_settled(c, body["poll_url"])
            assert j["status"] == "done", j
            assert j["video_url"]
            f = c.get(j["video_url"])
            assert f.status_code == 200
            assert "video/mp4" in (f.headers.get("Content-Type") or "")

    def test_render_failure_reports_error_not_silence(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion, "render_meet_reel", side_effect=RuntimeError("boom: render exploded")
            ):
                resp = c.post("/api/runs/r1/reel-job")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "error"
        assert j["error"]

    def test_foreign_org_cannot_see_job_or_run(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion, "render_meet_reel", side_effect=RuntimeError("x")
            ):
                resp = c.post("/api/runs/r1/reel-job")
                poll = resp.get_json()["poll_url"]
                _poll_until_settled(c, poll)

        with app.test_client() as other:
            other.post("/api/organisation/active", data={"profile_id": "beta"})
            assert other.get(poll).status_code == 404
            assert other.post("/api/runs/r1/reel-job").status_code == 404
            assert other.get("/api/runs/r1/reel-file").status_code == 404

    def test_reel_file_never_renders(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/reel-file")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "reel_not_rendered"
