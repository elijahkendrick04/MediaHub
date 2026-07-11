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


def test_footage_upload_cap_raised_above_global_50mb(app):
    """Regression: real videos exceed the 50 MB global cap. A 51 MB payload would
    413 under it, but the footage route raises the cap per-request so a normal
    phone clip can actually upload (the reported bug). Other routes are untouched.
    """
    import io

    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        big = io.BytesIO(b"\x00" * (51 * 1024 * 1024))  # just over the global cap
        r = c.post(
            "/api/video/footage",
            data={"file": (big, "clip.mp4")},
            content_type="multipart/form-data",
        )
        # Not 413 ⇒ the raised cap applied (the body was accepted, whatever ingest
        # then makes of these bytes). Before the fix this was a hard 413.
        assert r.status_code != 413, "footage upload still capped at the global 50 MB"
        # The global cap is unchanged, so every other route stays at 50 MB.
        assert application.config["MAX_CONTENT_LENGTH"] == 50 * 1024 * 1024


def test_media_store_default_paths_follow_data_dir(tmp_path, monkeypatch):
    """Regression (QA-010): footage/photo blobs and the asset DB must live under
    DATA_DIR — the writable persistent disk — not the package dir.

    On the deploy the code tree (``/app/src/mediahub``) is root-owned and the
    runtime user (uid 10001) can't write there. The store hardcoded a
    package-relative default, so every footage upload tried to ``mkdir``/write
    under that read-only tree and raised ``PermissionError`` → an unhandled HTTP
    500 (the reported bug). The default must derive from ``DATA_DIR`` like
    ``video/projects.py`` and the rest of the app do. Resolved at construction
    time, so simply setting the env var is enough — no import reload.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.media_library.store import MediaLibraryStore

    store = MediaLibraryStore()  # no explicit paths ⇒ must come from DATA_DIR
    assert store.db_path == tmp_path / "data.db"
    assert store.uploads_dir == tmp_path / "uploads_v4" / "media_library"
    # A written blob lands under DATA_DIR, never under the read-only package tree.
    blob = store.store_blob(b"\x00\x01\x02", "race.mp4", "alpha")
    assert str(blob).startswith(str(tmp_path))
    pkg_dir = Path(__file__).resolve().parents[1] / "src" / "mediahub"
    assert str(pkg_dir) not in str(blob)


def test_footage_upload_valid_mp4_does_not_500(app, tmp_path):
    """Regression (QA-010): a valid small MP4 posted to /api/video/footage must
    not 500. A real H.264+AAC clip is used when FFmpeg is present (matching the
    QA repro); otherwise a small .mp4 payload still exercises the store/ingest
    path, which must succeed honestly even with no probe binary available.
    """
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        exe = _ffmpeg_exe()
        if exe:
            r = _upload_real_clip(c, tmp_path, size="720x1280", dur=1)
        else:
            import io

            r = c.post(
                "/api/video/footage",
                data={"file": (io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64), "race.mp4")},
                content_type="multipart/form-data",
            )
        assert r.status_code != 500, r.get_data(as_text=True)
        body = r.get_json()
        assert body is not None and body.get("ok") is True
        # And never the generic placeholder the QA report saw.
        assert body.get("error") != "internal_error"


def test_video_studio_exposes_upload_cap_to_js(app):
    """The studio page must hand the configured cap to the client (no placeholder)."""
    import re

    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        body = c.get("/video").get_data(as_text=True)
        m = re.search(r"var VIDEO_MAX_MB = (\d+);", body)
        assert m and int(m.group(1)) >= 50
        assert "__VIDEO_MAX_MB__" not in body


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


def test_update_rejects_malformed_edl_types_without_500(app):
    """A wrong-typed EDL field ("width": "abc", null fps, a non-list clips) fails
    EDL.from_dict's int/float coercion with a plain ValueError/TypeError/
    AttributeError, not EDLError. The route must catch those and answer an honest
    400 invalid_edl, never let them escape to an unhandled 500 with a Python trace.
    """
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(id="", profile_id="alpha", edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]))
    )
    base = {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "clips": [
            {"source": "a.mp4", "in_ms": 0, "out_ms": 3000, "transition_in": {"kind": "cut"}}
        ],
    }
    malformed = [
        {**base, "width": "abc"},  # int() cast fails
        {**base, "fps": None},  # int(None) → TypeError
        {**base, "clips": "notalist"},  # iterating a str → Clip.from_dict('n') AttributeError
        {**base, "clips": [{"source": "a.mp4", "speed": "fast"}]},  # float() cast fails
    ]
    with application.test_client() as c:
        _pin(c, "alpha")
        for edl in malformed:
            r = c.post(f"/api/video/projects/{proj.id}", json={"edl": edl})
            assert r.status_code == 400, f"expected 400, got {r.status_code} for {edl}"
            assert r.get_json()["error"] == "invalid_edl"


def test_edl_update_rejects_foreign_clip_source(app, tmp_path):
    """Security: the EDL validator only checks a source is non-empty, so without a
    source-binding guard a caller could point a clip at ANY file on the box (another
    tenant's footage, any readable media) and have the render/waveform/export engine
    read it back. An edit may reorder/trim/grade the clips it was given, but must not
    introduce a NEW source path — new footage only enters via Clip-Maker/the reel.
    """
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    # A file that is NOT one of the project's own footage clips.
    victim = tmp_path / "someone_elses.mp4"
    victim.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    store = get_store()
    proj = store.save(
        VideoProject(
            id="", profile_id="alpha", edl=EDL(clips=[Clip(source="own.mp4", out_ms=3000)])
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        evil = {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "clips": [
                {
                    "source": str(victim),
                    "in_ms": 0,
                    "out_ms": 1000,
                    "transition_in": {"kind": "cut"},
                }
            ],
        }
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": evil})
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid_edl"
        # The injected source must NOT have been persisted onto the timeline.
        after = c.get(f"/api/video/projects/{proj.id}").get_json()["project"]
        assert after["edl"]["clips"][0]["source"] == "own.mp4"
        # A legitimate edit that keeps the project's own source still succeeds.
        ok = c.post(
            f"/api/video/projects/{proj.id}",
            json={"edl": EDL(clips=[Clip(source="own.mp4", out_ms=2000)]).to_dict()},
        )
        assert ok.status_code == 200
        assert ok.get_json()["project"]["edl"]["clips"][0]["out_ms"] == 2000


def test_export_download_name_with_newline_does_not_500(app, tmp_path):
    """Regression: send_file writes the project name into the Content-Disposition
    header; werkzeug raises on a header value containing a newline, so a project
    named with one used to 500 on export. The name is sanitised for the header now.
    """
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    application, data_dir = app
    store = get_store()
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            name='evil"\r\nX-Injected: 1 clip',
            status="approved",
            format_name="story",
            edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)]),
        )
    )
    # Place a rendered file so the export gate reaches send_file (no FFmpeg needed).
    render_dir = data_dir / "video_projects" / proj.id
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "story.mp4").write_bytes(b"\x00" * 2048)

    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get(f"/api/video/projects/{proj.id}/file?download=1")
        assert r.status_code == 200, "export must not 500 on a newline in the project name"
        cd = r.headers.get("Content-Disposition", "")
        assert "\n" not in cd and "\r" not in cd
        # The header-injection attempt does not create a real header.
        assert "X-Injected" not in r.headers


# --- AI editing surfaces: looks, reel director, enhance --------------------


def test_studio_page_has_ai_editing_controls(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get("/video")
        assert r.status_code == 200
        body = r.data
        # G-7: the director surface is user-labelled "Footage reel" so it stops
        # colliding with the pack page's card-built "Meet reel".
        assert b"Footage reel" in body  # the director surface
        assert b"Look" in body and b"Vivid" in body  # the grade picker
        assert b"Clean &amp; level the audio" in body  # the soundtrack option
        assert b"Remove silences" in body  # the tighten option


def test_studio_page_has_timeline_editor(app):
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        body = c.get("/video").data
        assert b"Edit timeline" in body  # per-project editor entry point
        assert b"vstudio-modal" in body and b"vs-ed-clips" in body  # the editor sheet
        assert b"vs-ed-grade" in body and b"gradeSlider" in body  # per-clip grade sliders
        assert b"vs-ed-grip" in body and b"reorderFrom" in body  # drag-to-reorder
        assert b"vs-ed-wave" in body and b"prefetchWaveforms" in body  # waveform scrubber
        # both editor URL templates must be resolved (no leftover placeholder)
        assert b"__PROJECT_TMPL__" not in body and b"__PROJECT_WAVEFORM_TMPL__" not in body
        assert b"/api/video/projects/__PID__" in body  # client-side id-substitution template
        assert b"/clip/__CIDX__/waveform" in body  # waveform URL template


def test_timeline_editor_save_path_persists_and_reopens_approval(app):
    """The editor saves by POSTing the edited EDL — reorder + trim must persist."""
    application, _ = app
    from mediahub.video.edl import EDL, Clip, Transition
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    edl = EDL(
        clips=[
            Clip(source="a.mp4", in_ms=0, out_ms=3000),
            Clip(source="b.mp4", in_ms=0, out_ms=3000, transition_in=Transition("dissolve", 300)),
        ]
    )
    proj = store.save(VideoProject(id="", profile_id="alpha", status="approved", edl=edl))
    with application.test_client() as c:
        _pin(c, "alpha")
        # GET returns the full EDL the editor loads.
        got = c.get(f"/api/video/projects/{proj.id}").get_json()
        assert got["ok"] and len(got["project"]["edl"]["clips"]) == 2
        # Editor reorders (b first) + trims, forcing the new lead clip to a cut.
        new_edl = got["project"]["edl"]
        new_edl["clips"] = [new_edl["clips"][1], new_edl["clips"][0]]
        new_edl["clips"][0]["transition_in"] = {"kind": "cut", "duration_ms": 0}
        new_edl["clips"][0]["out_ms"] = 2000
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": new_edl})
        assert r.status_code == 200
        saved = r.get_json()["project"]
        assert saved["edl"]["clips"][0]["source"] == "b.mp4"  # reorder persisted
        assert saved["edl"]["clips"][0]["out_ms"] == 2000  # trim persisted
        assert saved["status"] == "draft"  # editing reopens approval (rule 6)


def test_timeline_editor_persists_per_clip_grade(app):
    """A per-clip colour grade posted from the editor survives the save round-trip."""
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            status="approved",
            edl=EDL(clips=[Clip(source="a.mp4", in_ms=0, out_ms=3000)]),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        new_edl = c.get(f"/api/video/projects/{proj.id}").get_json()["project"]["edl"]
        # The editor writes a non-identity grade onto the clip.
        new_edl["clips"][0]["adjust"] = {
            "brightness": 0.1,
            "contrast": 1.2,
            "saturation": 1.3,
            "warmth": 0.4,
        }
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": new_edl})
        assert r.status_code == 200
        adj = r.get_json()["project"]["edl"]["clips"][0]["adjust"]
        assert adj is not None
        assert adj["contrast"] == 1.2 and adj["warmth"] == 0.4  # grade persisted


def test_timeline_editor_identity_grade_stays_omitted(app):
    """An identity grade serialises back as null (un-graded clip stays byte-identical)."""
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            status="approved",
            edl=EDL(clips=[Clip(source="a.mp4", in_ms=0, out_ms=3000)]),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        new_edl = c.get(f"/api/video/projects/{proj.id}").get_json()["project"]["edl"]
        # An identity grade (the client nulls these, but tolerate one arriving).
        new_edl["clips"][0]["adjust"] = {
            "brightness": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "warmth": 0.0,
        }
        r = c.post(f"/api/video/projects/{proj.id}", json={"edl": new_edl})
        assert r.status_code == 200
        assert r.get_json()["project"]["edl"]["clips"][0]["adjust"] is None  # omitted


def test_studio_look_options_is_valid_js_string(app):
    """Regression: the look-picker HTML is injected into a JS string (var LOOK_OPTIONS).

    Its <option> attributes are double-quoted, so the value MUST be JSON-encoded or
    the literal quotes terminate the string and the whole studio IIFE fails to
    parse — silently breaking upload, projects, and the entire timeline editor.
    """
    import json
    import re

    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        body = c.get("/video").get_data(as_text=True)
        m = re.search(r'var LOOK_OPTIONS = ("(?:[^"\\]|\\.)*");', body)
        assert m, "LOOK_OPTIONS assignment not found / not a JS string literal"
        val = json.loads(m.group(1))  # must be a valid JS/JSON string literal
        # the FULL options HTML must survive the encoding (a broken/truncated
        # string would lose the closing tags) — proves the quotes were escaped.
        assert val.count("<option") >= 2 and "</option>" in val


def test_studio_modal_respects_hidden_attribute(app):
    """Regression: .vstudio-modal sets display:flex, which overrode the `hidden`
    attribute — the editor overlay then covered the page and ate every click."""
    application, _ = app
    with application.test_client() as c:
        _pin(c, "alpha")
        body = c.get("/video").get_data(as_text=True)
        assert ".vstudio-modal[hidden]{display:none}" in body


def _project_with_real_source(tmp_path, profile="alpha"):
    """A project whose single clip points at a real (dummy) file on disk."""
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    src = tmp_path / "footage_src.mp4"
    src.write_bytes(b"\x00" * 256)  # presence only; extraction is mocked
    proj = EDL(clips=[Clip(source=str(src), in_ms=0, out_ms=3000)])
    return get_store().save(VideoProject(id="", profile_id=profile, edl=proj))


def test_clip_waveform_returns_peaks(app, monkeypatch):
    """The scrubber route returns normalised peaks for a clip's source."""
    application, tmp_path = app
    import mediahub.video.waveform as wf

    monkeypatch.setattr(wf, "extract_peaks", lambda *a, **k: [0.0, 0.5, 1.0, 0.25])
    proj = _project_with_real_source(tmp_path)
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.get(f"/api/video/projects/{proj.id}/clip/0/waveform?buckets=120")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] and body["peaks"] == [0.0, 0.5, 1.0, 0.25]
        assert body["buckets"] == 120 and "duration_ms" in body  # echoed clamped request


def test_clip_waveform_bad_index_404(app, monkeypatch):
    application, tmp_path = app
    import mediahub.video.waveform as wf

    monkeypatch.setattr(wf, "extract_peaks", lambda *a, **k: [0.0])
    proj = _project_with_real_source(tmp_path)
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.get(f"/api/video/projects/{proj.id}/clip/9/waveform").status_code == 404


def test_clip_waveform_missing_source_410(app):
    """A clip whose source vanished from disk honest-errors, never a fake shape."""
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    proj = get_store().save(
        VideoProject(
            id="", profile_id="alpha", edl=EDL(clips=[Clip(source="/gone/x.mp4", out_ms=3000)])
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.get(f"/api/video/projects/{proj.id}/clip/0/waveform").status_code == 410


def test_clip_waveform_foreign_profile_404(app, monkeypatch):
    """A waveform for another profile's project is invisible (no IDOR)."""
    application, tmp_path = app
    import mediahub.video.waveform as wf

    monkeypatch.setattr(wf, "extract_peaks", lambda *a, **k: [0.1])
    proj = _project_with_real_source(tmp_path, profile="alpha")
    with application.test_client() as c:
        _pin(c, "beta")
        assert c.get(f"/api/video/projects/{proj.id}/clip/0/waveform").status_code == 404


def test_clip_waveform_engine_unavailable_503(app, monkeypatch):
    application, tmp_path = app
    import mediahub.video.waveform as wf

    def boom(*a, **k):
        raise wf.WaveformUnavailable("no ffmpeg")

    monkeypatch.setattr(wf, "extract_peaks", boom)
    proj = _project_with_real_source(tmp_path)
    with application.test_client() as c:
        _pin(c, "alpha")
        assert c.get(f"/api/video/projects/{proj.id}/clip/0/waveform").status_code == 503


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
            f"/api/video/projects/{proj.id}/enhance",
            json={"enhance_audio": True, "with_music": False},
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
        assert (
            c.post(f"/api/video/projects/{proj.id}/enhance", json={"look": "vivid"}).status_code
            == 404
        )


def test_caption_edit_route_corrects_text_and_reopens_approval(app):
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    track = {"color": "#FFF", "scrim": "#000", "cues": [{"from": 0, "dur": 30, "text": "Maria"}]}
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            status="approved",
            edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)], captions=track),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(
            f"/api/video/projects/{proj.id}/caption",
            json={"op": "edit", "index": 0, "text": "Mariah"},
        )
        assert r.status_code == 200
        assert r.get_json()["cues"][0]["text"] == "Mariah"
        # the correction reopened approval (rule 6)
        assert store.get(proj.id).status == "draft"


def test_caption_edit_route_no_captions_is_400(app):
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
            f"/api/video/projects/{proj.id}/caption", json={"op": "edit", "index": 0, "text": "x"}
        )
        assert r.status_code == 400


def test_caption_bad_params_message_is_clean(app):
    """A missing/non-numeric index fails an int() cast inside the caption op. The
    route answers 400 bad_params with an actionable message — never the raw
    "int() argument must be ... not 'NoneType'" Python cast error leaked verbatim.
    """
    application, _ = app
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject, get_store

    store = get_store()
    track = {"color": "#FFF", "scrim": "#000", "cues": [{"from": 0, "dur": 30, "text": "Maria"}]}
    proj = store.save(
        VideoProject(
            id="",
            profile_id="alpha",
            edl=EDL(clips=[Clip(source="a.mp4", out_ms=3000)], captions=track),
        )
    )
    with application.test_client() as c:
        _pin(c, "alpha")
        r = c.post(f"/api/video/projects/{proj.id}/caption", json={"op": "edit", "text": "x"})
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "bad_params"
        # No Python-internals cast error leaked to the API caller.
        assert "int()" not in body["message"]
        assert "argument must be" not in body["message"]


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


@pytest.mark.skipif(not _ffmpeg_exe(), reason="FFmpeg not available")
def test_clip_waveform_live_real_ffmpeg(app):
    """End-to-end: a real clip's waveform decodes to normalised peaks over the route."""
    application, tmp_path = app
    with application.test_client() as c:
        _pin(c, "alpha")
        asset_id = _upload_real_clip(c, tmp_path).get_json()["asset"]["id"]
        cm = c.post("/api/video/clip-maker", json={"asset_id": asset_id, "format": "story"})
        pid = cm.get_json()["project_id"]
        r = c.get(f"/api/video/projects/{pid}/clip/0/waveform?buckets=64")
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] and len(body["peaks"]) == 64
        assert all(0.0 <= p <= 1.0 for p in body["peaks"])  # normalised
        assert max(body["peaks"]) > 0.5  # the 440Hz sine is plainly audible
        assert body["duration_ms"] > 0
