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

    def test_heartbeat_keeps_a_slow_render_reported_running(self, app_env):
        """A legitimately slow render past the 5-min stall threshold must not
        be reported job_lost while the worker is alive: the worker heartbeat
        re-saves the job file, refreshing updated_at. A dead worker stops
        heartbeating, so honest job-lost reports still happen."""
        app, wm, _ = app_env
        job = {
            "id": "a" * 32,
            "kind": "reel",
            "status": "running",
            "error": "",
            "user_message": "",
            "video_url": "",
            "created_at": time.time(),
            "owner_pid": "alpha",
        }
        wm._variant_job_save(job)
        # Backdate the persisted snapshot past the stall threshold — without a
        # heartbeat the status route reports it lost.
        path = wm._variant_jobs_dir() / f"{job['id']}.json"
        stale = json.loads(path.read_text())
        stale["updated_at"] = time.time() - (wm._VARIANT_JOB_STALL_S + 60)
        path.write_text(json.dumps(stale))
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            lost = c.get(f"/api/reel-jobs/{job['id']}").get_json()
            assert lost["status"] == "error" and "job_lost" in (lost["error"] or "")
            # …but with the worker's heartbeat running, the file stays fresh.
            with wm._job_heartbeat(job, interval_s=0.05):
                time.sleep(0.2)
            alive = c.get(f"/api/reel-jobs/{job['id']}").get_json()
        assert alive["status"] == "running"
        assert not alive["error"]

    def test_reel_file_never_renders(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/reel-file")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "reel_not_rendered"

    def test_job_forwards_dub_and_next_meet_to_render(self, app_env):
        """The async job route passes the same 1.24 dub_language and R1.30
        next_meet inputs the sync route resolves, and mints a lang-aware file
        URL so the dubbed MP4 is actually streamable."""
        app, wm, _ = app_env
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(
            ClubProfile(
                profile_id="alpha",
                display_name="Alpha SC",
                notes="Next meet: County Champs — 12 Jul",
            )
        )
        import mediahub.visual.motion as motion

        captured = {}

        def _fake_render(cards, brand_kit, out_path, **kw):
            captured.update(kw)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"0" * 2048)
            return Path(out_path)

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_meet_reel", _fake_render):
                resp = c.post("/api/runs/r1/reel-job?lang=es")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
            assert j["status"] == "done", j
            assert captured["dub_language"] == "es"
            assert captured["next_meet"].startswith("County Champs")
            assert "lang=es" in j["video_url"]
            f = c.get(j["video_url"])
            assert f.status_code == 200
            assert "video/mp4" in (f.headers.get("Content-Type") or "")

    def test_reel_file_serves_poster_sidecar(self, app_env):
        """?poster=1 streams the poster PNG written beside the rendered MP4,
        and 404s honestly when the sidecar is absent (a pre-poster render)."""
        app, wm, _ = app_env
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        (motion_dir / "reel_3.mp4").write_bytes(b"0" * 2048)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/reel-file?poster=1")
            assert resp.status_code == 404
            assert resp.get_json()["error"] == "poster_not_rendered"

            (motion_dir / "reel_3.poster.png").write_bytes(b"\x89PNG fake poster")
            resp = c.get("/api/runs/r1/reel-file?poster=1")
            assert resp.status_code == 200
            assert "image/png" in (resp.headers.get("Content-Type") or "")
            # The plain request still streams the MP4.
            resp = c.get("/api/runs/r1/reel-file")
            assert resp.status_code == 200
            assert "video/mp4" in (resp.headers.get("Content-Type") or "")


class TestVariantJobStoreAtomicity:
    def test_variant_job_save_survives_concurrent_writers(self, app_env):
        """CON-4: the worker thread and its heartbeat both save the same job.
        A shared ``.tmp`` path let their writes interleave into a torn/absent
        job JSON for a poll cycle — the tmp name is now unique per write, so
        the loader always sees a complete snapshot and never a torn file."""
        import threading

        _app, wm, _tmp = app_env
        job_id = "c" * 32
        wm._variant_job_save({"id": job_id, "kind": "reel", "status": "running"})

        failures: list = []
        stop = threading.Event()

        def _writer(tag: str) -> None:
            for i in range(200):
                wm._variant_job_save(
                    {"id": job_id, "kind": "reel", "status": "running", tag: i}
                )

        def _reader() -> None:
            path = wm._variant_jobs_dir() / f"{job_id}.json"
            while not stop.is_set():
                # Loader must never see a torn/absent file once the job exists.
                if wm._variant_job_load(job_id) is None:
                    failures.append("load returned None")
                # And the raw bytes on disk always parse (loader masks parse
                # errors as None, so check the file directly too).
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    failures.append(f"torn file: {e!r}")

        threads = [threading.Thread(target=_writer, args=(t,)) for t in ("a", "b")]
        reader = threading.Thread(target=_reader)
        reader.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stop.set()
        reader.join()
        assert not failures, failures[:5]
        final = wm._variant_job_load(job_id)
        assert final and final["id"] == job_id and final["kind"] == "reel"
        # Successful writes leave no stray tmp files behind.
        assert not list(wm._variant_jobs_dir().glob("*.tmp"))
