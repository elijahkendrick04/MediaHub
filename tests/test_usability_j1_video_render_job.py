"""J-1 (part 1 — render) — the Video Studio render must run as a background job.

api_video_project_render held one HTTP connection open for the whole 30-90s
FFmpeg render, which reverse proxies kill — the button then "did nothing". The
new api_video_project_render_job returns 202 {job_id, poll_url} immediately and
renders on a background thread the client polls via api_reel_job_status (the same
disk-backed job store the reel/motion routes use). The fail-fast gates
(tenant / consent / engine) stay in the request thread; completion hands back the
existing project file URL, so the tile flips to the preview.
"""

from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
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
    from mediahub.video import projects as _vproj

    _vproj._store = None
    application = wm.create_app()
    application.config["TESTING"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    return application, tmp_path


def _pin(client, pid):
    client.post("/api/organisation/active", data={"profile_id": pid})


def _make_project(pid="alpha"):
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    return get_store().save(
        VideoProject(id="", profile_id=pid, edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )


def _poll_until(client, poll_url, want, tries=120, delay=0.05):
    """Poll the job-status route until status==want (or error), returning payload."""
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") in (want, "error"):
            return j
        time.sleep(delay)
    return client.get(poll_url).get_json()


def test_render_job_returns_202_and_completes(app, monkeypatch):
    application, tmp_path = app
    proj = _make_project("alpha")

    # A fast stub render that writes the MP4 where the real engine would, so the
    # worker completes deterministically without FFmpeg.
    def _fake_render(edl_input, out_path):
        from pathlib import Path

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"\x00" * 2048)

    monkeypatch.setattr("mediahub.video.render.render_edl", _fake_render)
    monkeypatch.setattr("mediahub.video.render.available", lambda: True)

    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            f"/api/video/projects/{proj.id}/render-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 202, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] is True
        import re

        assert re.fullmatch(r"[0-9a-f]{32}", body["job_id"])
        assert body["poll_url"]
        done = _poll_until(c, body["poll_url"], "done")
        assert done["status"] == "done", done
        assert done["video_url"].endswith(f"/api/video/projects/{proj.id}/file")
    # The MP4 exists where api_video_project_file serves it.
    assert (tmp_path / "video_projects" / proj.id / "story.mp4").exists()


def test_render_job_foreign_profile_404(app):
    application, _ = app
    proj = _make_project("alpha")
    with application.test_client() as c:
        _pin(c, "beta")
        r = c.post(
            f"/api/video/projects/{proj.id}/render-job", data="{}", content_type="application/json"
        )
        assert r.status_code == 404


def test_render_job_engine_unavailable_is_503_no_job(app, monkeypatch):
    application, _ = app
    proj = _make_project("alpha")
    monkeypatch.setattr("mediahub.video.render.available", lambda: False)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            f"/api/video/projects/{proj.id}/render-job", data="{}", content_type="application/json"
        )
        # Fail-fast in the request thread — 503, never a doomed 202.
        assert r.status_code == 503
        assert r.get_json()["error"] == "engine_unavailable"


def test_render_job_honest_error(app, monkeypatch):
    application, tmp_path = app
    proj = _make_project("alpha")

    def _boom(edl_input, out_path):
        raise RuntimeError("ffmpeg exploded mid-render")

    monkeypatch.setattr("mediahub.video.render.render_edl", _boom)
    monkeypatch.setattr("mediahub.video.render.available", lambda: True)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            f"/api/video/projects/{proj.id}/render-job", data="{}", content_type="application/json"
        )
        assert r.status_code == 202
        j = _poll_until(c, r.get_json()["poll_url"], "done")
        assert j["status"] == "error"
        assert "ffmpeg exploded" in (j.get("error") or "")
    # No fabricated success: the MP4 was never written.
    assert not (tmp_path / "video_projects" / proj.id / "story.mp4").exists()


def test_reel_job_status_admits_video_render_kind(app):
    """The shared poll route's allowlist now accepts the video-render kind and
    still enforces the owner-pid IDOR gate."""
    application, _ = app
    import mediahub.web.web as wm

    job = {
        "id": "a" * 32,
        "kind": "video-render",
        "status": "running",
        "owner_pid": "alpha",
        "video_url": "",
    }
    wm._variant_job_save(job)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get(f"/api/reel-jobs/{'a' * 32}")
        assert r.status_code == 200
        assert r.get_json()["kind"] == "video-render"
        # A foreign profile can't see it (IDOR gate).
        _pin(c, "beta")
        assert c.get(f"/api/reel-jobs/{'a' * 32}").status_code == 404
