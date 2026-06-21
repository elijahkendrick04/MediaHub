"""Route smoke + isolation tests for the video suite (roadmap 1.6).

Covers the Studio page, footage upload/list, Clip-Maker, project CRUD, the
approval-before-export gate, and per-profile isolation. The full
upload→clip-maker→render→approve→export flow is gated behind FFmpeg
availability (absent in bare sandboxes); the access-control and honest-error
paths run everywhere.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


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

    # Isolate the per-process singletons onto this test's tmp dirs so footage
    # uploads + projects don't leak between tests (the media-library store binds
    # a fixed DB by design — repoint it here for test hygiene only).
    from mediahub.media_library import store as _mlstore

    _mlstore._default_store = _mlstore.MediaLibraryStore(
        db_path=tmp_path / "media.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )
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


def _ffmpeg_exe():
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    return ffmpeg_exe()


def _render_available():
    from mediahub.video.render import available

    return available()


def _upload_real_clip(client, tmp_path, *, size="640x480", dur=2):
    exe = _ffmpeg_exe()
    src = tmp_path / "raw.mp4"
    subprocess.run(
        [
            exe,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=30:duration={dur}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={dur}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    data = src.read_bytes()
    return client.post(
        "/api/video/footage",
        data={"file": (Path(str(src)).open("rb"), "race.mp4")},
        content_type="multipart/form-data",
    )


# --- page + empty states --------------------------------------------------


def test_studio_page_renders(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get("/video")
        assert r.status_code == 200
        assert b"Clip Maker" in r.data
        assert b"Footage" in r.data


def test_footage_list_empty(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get("/api/video/footage")
        assert r.status_code == 200
        assert r.get_json()["footage"] == []


def test_projects_list_empty(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.get("/api/video/projects").get_json()["projects"] == []


def test_footage_upload_rejects_non_video(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            "/api/video/footage",
            data={"file": (Path(__file__).open("rb"), "notes.txt")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 415


def test_clip_maker_unknown_footage_404(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post("/api/video/clip-maker", json={"asset_id": "ma_missing"})
        assert r.status_code == 404


def test_project_foreign_profile_is_404(app):
    """A project created under alpha must be invisible to a beta session."""
    application, tmp_path = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    with application.test_client() as c:
        _pin(c, "beta")
        assert c.get(f"/api/video/projects/{proj.id}").status_code == 404
        assert c.post(f"/api/video/projects/{proj.id}/render").status_code == 404


def test_export_gate_blocks_unapproved(app):
    """`?download=1` is refused until a human approves (rule 6)."""
    application, tmp_path = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    # Place a fake rendered file so the gate (not the missing-file check) is hit.
    out = tmp_path / "video_projects" / proj.id / "story.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00" * 4096)
    with application.test_client() as c:
        _pin(c, "alpha")
        # Inline preview is allowed for review...
        assert c.get(f"/api/video/projects/{proj.id}/file").status_code == 200
        # ...but export is blocked until approval.
        assert c.get(f"/api/video/projects/{proj.id}/file?download=1").status_code == 403
        # Approve, then export is allowed.
        assert (
            c.post(
                f"/api/video/projects/{proj.id}/approve", json={"status": "approved"}
            ).status_code
            == 200
        )
        assert c.get(f"/api/video/projects/{proj.id}/file?download=1").status_code == 200


def test_edit_reopens_approval(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            status="approved",
            edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        new_edl = EDL(clips=[Clip(source="a.mp4", out_ms=2000)]).to_dict()
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": new_edl})
        assert r.status_code == 200
        assert r.get_json()["project"]["status"] == "draft"  # editing reopens approval


def test_update_rejects_invalid_edl(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": {"clips": []}})
        assert r.status_code == 400


# --- AI editing surfaces: looks, reel director, enhance --------------------


def test_studio_page_has_ai_editing_controls(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get("/video")
        assert r.status_code == 200
        body = r.data
        assert b"AI reel" in body  # the director surface
        assert b"Look" in body and b"Vivid" in body  # the grade picker
        assert b"Clean &amp; level the audio" in body  # the soundtrack option
        assert b"Remove silences" in body  # the tighten option


def test_reel_requires_asset_ids(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.post("/api/video/reel", json={}).status_code == 400
        assert c.post("/api/video/reel", json={"asset_ids": []}).status_code == 400


def test_reel_unknown_footage_404(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post("/api/video/reel", json={"asset_ids": ["ma_missing"]})
        assert r.status_code == 404


def test_enhance_look_sets_grade_and_reopens_approval(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            status="approved",
            edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(f"/api/video/projects/{proj.id}/enhance", json={"look": "vivid"})
        assert r.status_code == 200
        data = r.get_json()["project"]
        assert data["edl"]["look"] == "vivid"
        assert data["status"] == "draft"  # an enhancement reopens approval (rule 6)


def test_enhance_music_attaches_audio_plan(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            f"/api/video/projects/{proj.id}/enhance", json={"enhance_audio": True, "with_music": False}
        )
        assert r.status_code == 200
        assert r.get_json()["project"]["edl"]["audio"]["enhance_voice"] is True


def test_enhance_foreign_profile_404(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    with application.test_client() as c:
        _pin(c, "beta")
        assert c.post(f"/api/video/projects/{proj.id}/enhance", json={"look": "vivid"}).status_code == 404


def test_enhance_stabilize_honest_error_without_vidstab(app, monkeypatch):
    application, _ = app
    from mediahub.video import enhance as _enh
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    # Force the "no vidstab" path so the honest-error surfaces regardless of host.
    monkeypatch.setattr(_enh, "is_stabilize_available", lambda: False)
    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(f"/api/video/projects/{proj.id}/enhance", json={"stabilize": True})
        assert r.status_code == 503
        assert "message" in r.get_json()


# --- full flow (gated on FFmpeg) ------------------------------------------


@pytest.mark.skipif(not _render_available(), reason="FFmpeg + renderer not available")
def test_full_flow_upload_clipmaker_render_approve_export(app):
    application, tmp_path = app
    with application.test_client() as c:
        _pin(c, "alpha")
        up = _upload_real_clip(c, tmp_path)
        assert up.status_code == 200
        asset_id = up.get_json()["asset"]["id"]

        # Footage list now shows it.
        listed = c.get("/api/video/footage").get_json()["footage"]
        assert any(a["id"] == asset_id for a in listed)

        # Clip-Maker → project.
        cm = c.post(
            "/api/video/clip-maker",
            json={"asset_id": asset_id, "format": "story", "title": "New PB!"},
        )
        assert cm.status_code == 200, cm.get_data(as_text=True)
        pid = cm.get_json()["project_id"]

        # Render → MP4 served inline.
        rr = c.post(f"/api/video/projects/{pid}/render")
        assert rr.status_code == 200, rr.get_data(as_text=True)
        assert c.get(f"/api/video/projects/{pid}/file").status_code == 200

        # Export blocked until approval, then allowed.
        assert c.get(f"/api/video/projects/{pid}/file?download=1").status_code == 403
        c.post(f"/api/video/projects/{pid}/approve", json={"status": "approved"})
        exp = c.get(f"/api/video/projects/{pid}/file?download=1")
        assert exp.status_code == 200
        assert exp.headers["Content-Type"].startswith("video/mp4")
