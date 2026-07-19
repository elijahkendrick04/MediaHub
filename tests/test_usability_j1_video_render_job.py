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

import time

import pytest


@pytest.fixture
def app(web_module, tmp_path):
    from mediahub.media_library import store as _mls

    _mls._default_store = _mls.MediaLibraryStore(
        db_path=tmp_path / "media.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )
    from mediahub.video import projects as _vproj

    _vproj._store = None
    application = web_module.create_app()
    application.config["TESTING"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    return application, tmp_path, _mls._default_store


def _add_footage(store, tmp_path, *, asset_id="ft_1", profile_id="alpha"):
    from mediahub.media_library.models import MediaAsset

    src = tmp_path / f"{asset_id}.mp4"
    src.write_bytes(b"\x00" * 4096)
    return store.save(
        MediaAsset(
            id=asset_id,
            filename=f"{asset_id}.mp4",
            path=str(src),
            type="footage",
            profile_id=profile_id,
            permission_status="approved_by_club",
            approval_status="approved",
            width=1920,
            height=1080,
            media_meta={"duration_ms": 12000, "has_audio": True},
        )
    )


def _fake_edl():
    from mediahub.video.edl import EDL, Clip

    return EDL(clips=[Clip(source="a.mp4", out_ms=3000)])


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
    application, tmp_path, _store = app
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
    application, _tmp, _store = app
    proj = _make_project("alpha")
    with application.test_client() as c:
        _pin(c, "beta")
        r = c.post(
            f"/api/video/projects/{proj.id}/render-job", data="{}", content_type="application/json"
        )
        assert r.status_code == 404


def test_render_job_engine_unavailable_is_503_no_job(app, monkeypatch):
    application, _tmp, _store = app
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
    application, tmp_path, _store = app
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
    application, _tmp, _store = app
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


def test_all_video_job_kinds_in_allowlist(app):
    """The poll route admits all four new kinds (and still gates on owner)."""
    application, _tmp, _store = app
    import mediahub.web.web as wm

    for i, kind in enumerate(("video-render", "video-clip", "video-reel", "video-stabilize")):
        jid = format(i, "x").rjust(32, "0")
        wm._variant_job_save({"id": jid, "kind": kind, "status": "running", "owner_pid": "alpha"})
        with application.test_client() as c:
            _pin(c, "alpha")
            r = c.get(f"/api/reel-jobs/{jid}")
            assert r.status_code == 200, kind
            assert r.get_json()["kind"] == kind


def test_clip_maker_job_completes_no_duplicate(app, monkeypatch):
    application, tmp_path, store = app
    _add_footage(store, tmp_path)
    import types

    calls = {"n": 0}

    def _fake_clip(*a, **k):
        calls["n"] += 1
        return types.SimpleNamespace(edl=_fake_edl(), manifest={})

    monkeypatch.setattr("mediahub.video.clip_maker.clip_maker", _fake_clip)
    from mediahub.video.projects import get_store

    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post("/api/video/clip-maker-job", json={"asset_id": "ft_1", "format": "story"})
        assert r.status_code == 202, r.get_data(as_text=True)
        j = _poll_until(c, r.get_json()["poll_url"], "done")
        assert j["status"] == "done", j
        assert j.get("project_id")
        # Analysis job hands back a project id, not a video_url (no MP4 yet).
        assert j.get("video_url", "") == ""
    # H-19: exactly ONE project row created for the one job (no duplicates).
    assert len(get_store().list(profile_id="alpha")) == 1
    assert calls["n"] == 1


def test_clip_maker_job_honest_error_leaves_no_orphan(app, monkeypatch):
    application, tmp_path, store = app
    _add_footage(store, tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("asr model missing")

    monkeypatch.setattr("mediahub.video.clip_maker.clip_maker", _boom)
    from mediahub.video.projects import get_store

    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post("/api/video/clip-maker-job", json={"asset_id": "ft_1"})
        assert r.status_code == 202
        j = _poll_until(c, r.get_json()["poll_url"], "done")
        assert j["status"] == "error"
        assert "asr model missing" in (j.get("error") or "")
    # The project row is created only on success — a failed analysis leaves none.
    assert get_store().list(profile_id="alpha") == []


def test_reel_job_completes(app, monkeypatch):
    application, tmp_path, store = app
    _add_footage(store, tmp_path, asset_id="ft_1")
    _add_footage(store, tmp_path, asset_id="ft_2")
    import types

    def _fake_reel(*a, **k):
        return types.SimpleNamespace(
            edl=_fake_edl(), plan=types.SimpleNamespace(hook="Big win"), manifest={}
        )

    monkeypatch.setattr("mediahub.video.reel_builder.make_reel", _fake_reel)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post("/api/video/reel-job", json={"asset_ids": ["ft_1", "ft_2"], "format": "story"})
        assert r.status_code == 202, r.get_data(as_text=True)
        j = _poll_until(c, r.get_json()["poll_url"], "done")
        assert j["status"] == "done", j
        assert j.get("project_id")


def test_reel_job_requires_asset_ids(app):
    application, _tmp, _store = app
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.post("/api/video/reel-job", json={}).status_code == 400


def test_stabilize_job_honest_error_when_unavailable(app, monkeypatch):
    application, _tmp, _store = app
    proj = _make_project("alpha")
    # Force the no-vidstab path so the honest error is deterministic.
    monkeypatch.setattr("mediahub.video.enhance.is_stabilize_available", lambda: False)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(f"/api/video/projects/{proj.id}/stabilize-job", json={})
        assert r.status_code == 202
        j = _poll_until(c, r.get_json()["poll_url"], "done")
        # Honest surface — never a fabricated "stabilised" success.
        assert j["status"] == "error"
        assert j.get("error") == "stabilize_unavailable"


def test_stabilize_job_foreign_profile_404(app):
    application, _tmp, _store = app
    proj = _make_project("alpha")
    with application.test_client() as c:
        _pin(c, "beta")
        assert c.post(f"/api/video/projects/{proj.id}/stabilize-job", json={}).status_code == 404


# --- Adversarial-review fixes (guarded at the source level: JS behaviours) ----

import pathlib  # noqa: E402

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_runvideojob_clears_panel_on_done():
    # Fix 1: clip/reel success must not leave a stuck 100% bar in the standalone
    # #vs-make-panel / #vs-reel-panel (loadProjects rebuilds only #vs-projects).
    assert "panel.hidden = true; panel.innerHTML = ''" in _SRC


def test_render_and_stabilise_disable_each_other():
    # Fix 2: render + stabilise share one .vs-render-panel per tile, so starting
    # one disables the sibling button (alsoButtons) to stop the second op
    # overwriting the first's mount mid-poll.
    assert "opts.alsoButtons" in _SRC
    assert "document.querySelector('.vs-stab[data-id=\"'+id+'\"]')" in _SRC
    assert "document.querySelector('.vs-render[data-id=\"'+id+'\"]')" in _SRC


def test_poll_cap_reaches_toward_the_job_ttl():
    # Fix 3: a healthy multi-minute stabilise/reel must not be abandoned at ~5min;
    # poll toward the 15-min TTL (300 * 3s) — a dead job is reported job_lost first.
    assert "if(tries > 300)" in _SRC
    assert "if(tries > 100)" not in _SRC
