"""Phase D route coverage — M24 (per-card race-clip upload + chip), M26
(consent gates on clip-maker / reel / render / export + permission editor),
M27 (?poster=1 on the asset file route), and the clip-unlink affordance.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _run_payload(profile_id: str) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
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

    from mediahub.media_library import store as mls

    mls._default_store = mls.MediaLibraryStore(
        db_path=tmp_path / "media.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )
    from mediahub.video import projects as vproj

    vproj._store = None

    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, wm, tmp_path, mls._default_store


def _pin(client, pid):
    client.post("/api/organisation/active", data={"profile_id": pid})


def _add_footage(store, tmp_path, *, asset_id="ft_1", profile_id="alpha",
                 permission="approved_by_club", meta=None, links=True):
    from mediahub.media_library.models import MediaAsset

    src = tmp_path / f"{asset_id}.mp4"
    src.write_bytes(b"\x00" * 4096)
    asset = MediaAsset(
        id=asset_id,
        filename=f"{asset_id}.mp4",
        path=str(src),
        type="footage",
        profile_id=profile_id,
        linked_athlete_names=["Eira Hughes"] if links else [],
        linked_meet_ids=["r1"] if links else [],
        permission_status=permission,
        approval_status="approved",
        width=1920,
        height=1080,
        media_meta=meta if meta is not None else {"duration_ms": 12000, "has_audio": True},
    )
    return store.save(asset)


def _make_project(store, tmp_path, *, source_path, profile_id="alpha", status="draft"):
    from mediahub.video.edl import EDL, Clip
    from mediahub.video.projects import VideoProject
    from mediahub.video.projects import get_store as vp_store

    proj = VideoProject(
        id="",
        profile_id=profile_id,
        name="Race cut",
        edl=EDL(width=1080, height=1920, fps=30, clips=[Clip(source=str(source_path), in_ms=0, out_ms=4000)]),
        source_asset_id="ft_1",
        format_name="story",
    )
    proj = vp_store().save(proj)
    if status != "draft":
        vp_store().set_status(proj.id, status)
        proj = vp_store().get(proj.id)
    return proj


# ---------------------------------------------------------------------------
# M24 — per-card upload accepts video/*
# ---------------------------------------------------------------------------


class TestCardClipUpload:
    def test_video_upload_ingests_linked_footage(self, app_env, monkeypatch):
        app, wm, tmp_path, store = app_env
        from mediahub.video.probe import ClipProbe

        monkeypatch.setattr(
            "mediahub.video.probe.probe_clip",
            lambda p: ClipProbe(
                duration_ms=9000, width=1280, height=720, fps=30.0,
                has_video=True, has_audio=True, video_codec="h264", audio_codec="aac",
            ),
        )
        # Poster extraction would shell FFmpeg against fake bytes — keep it
        # honest-off for this test.
        monkeypatch.setattr("mediahub.video.ingest.extract_poster", lambda *a, **k: None)

        from mediahub.media_library.models import MediaAsset

        fake_frame = MediaAsset(
            id="ma_frame", filename="frame.jpg", path=str(tmp_path / "frame.jpg"),
            type="athlete_action", permission_status="needs_approval",
        )
        with app.test_client() as c:
            _pin(c, "alpha")
            with mock.patch("mediahub.video.best_frame.extract_best_frame", return_value=fake_frame):
                r = c.post(
                    "/api/runs/r1/cards/swim-1/photo",
                    data={"photo": (io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"v" * 4096), "race.mp4")},
                    content_type="multipart/form-data",
                )
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body["ok"] and body["asset"]["kind"] == "clip"
        assert body["asset"]["duration_ms"] == 9000
        assert body["asset"]["permission_status"] == "needs_approval"  # default preserved
        assert body["asset"]["frame_asset"]["id"] == "ma_frame"
        # The stored footage carries the card's athlete + meet links (M23 seam).
        clip = store.get(body["asset"]["id"])
        assert clip.type == "footage"
        assert clip.linked_athlete_names == ["Eira Hughes"]
        assert clip.linked_meet_ids == ["r1"]

    def test_non_media_upload_still_rejected(self, app_env):
        app, wm, tmp_path, store = app_env
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post(
                "/api/runs/r1/cards/swim-1/photo",
                data={"photo": (io.BytesIO(b"hello"), "notes.txt")},
                content_type="multipart/form-data",
            )
        assert r.status_code == 400
        assert r.get_json()["error"] == "not_an_image"

    def test_review_panel_carries_race_clip_chip_js(self, app_env):
        _, wm, _, _ = app_env
        src = Path(wm.__file__).read_text(encoding="utf-8")
        assert "race_clips" in src
        assert "mhClipUnlink" in src
        assert "Race clip &middot; backs the motion video" in src


class TestClipUnlink:
    def test_unlink_removes_card_links_only(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/runs/r1/cards/swim-1/clip-unlink", json={"asset_id": "ft_1"})
        assert r.status_code == 200 and r.get_json()["ok"]
        a = store.get("ft_1")
        assert a is not None  # never deleted
        assert a.linked_meet_ids == []
        assert a.linked_athlete_names == []

    def test_unlink_is_tenant_gated(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, profile_id="beta")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/runs/r1/cards/swim-1/clip-unlink", json={"asset_id": "ft_1"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# M26 — consent gates at every footage exit
# ---------------------------------------------------------------------------


BLOCKED = ["do_not_use", "needs_parental_consent"]


class TestConsentGates:
    @pytest.mark.parametrize("status", BLOCKED)
    def test_clip_maker_blocks(self, app_env, status):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, permission=status)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/clip-maker", json={"asset_id": "ft_1"})
        assert r.status_code == 403
        body = r.get_json()
        assert body["error"] == "footage_blocked"
        assert body["message"]  # plain-language, actionable

    @pytest.mark.parametrize("status", BLOCKED)
    def test_reel_blocks(self, app_env, status):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, asset_id="ok_1")
        _add_footage(store, tmp_path, asset_id="bad_1", permission=status)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/reel", json={"asset_ids": ["ok_1", "bad_1"]})
        assert r.status_code == 403
        assert r.get_json()["error"] == "footage_blocked"
        assert r.get_json()["asset_id"] == "bad_1"

    @pytest.mark.parametrize("status", BLOCKED)
    def test_project_render_blocks_on_regression(self, app_env, status):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(store, tmp_path)
        proj = _make_project(store, tmp_path, source_path=asset.path)
        # Permission regresses AFTER the project was created.
        store.update_fields("ft_1", {"permission_status": status})
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post(f"/api/video/projects/{proj.id}/render", json={})
        assert r.status_code == 403
        assert r.get_json()["error"] == "footage_blocked"

    @pytest.mark.parametrize("status", BLOCKED)
    def test_project_export_blocks_even_when_approved(self, app_env, status):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(store, tmp_path)
        proj = _make_project(store, tmp_path, source_path=asset.path, status="approved")
        # A rendered file exists; then the source's permission regresses.
        out = wm.DATA_DIR / "video_projects" / proj.id / "story.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        store.update_fields("ft_1", {"permission_status": status})
        with app.test_client() as c:
            _pin(c, "alpha")
            preview = c.get(f"/api/video/projects/{proj.id}/file")
            blocked = c.get(f"/api/video/projects/{proj.id}/file?download=1")
        assert preview.status_code == 200  # review stays possible
        assert blocked.status_code == 403
        assert blocked.get_json()["error"] == "footage_blocked"

    def test_project_export_allowed_when_sources_clear(self, app_env):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(store, tmp_path)
        proj = _make_project(store, tmp_path, source_path=asset.path, status="approved")
        out = wm.DATA_DIR / "video_projects" / proj.id / "story.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get(f"/api/video/projects/{proj.id}/file?download=1")
        assert r.status_code == 200

    def test_project_get_lists_source_permission_states(self, app_env):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(store, tmp_path, permission="needs_parental_consent")
        proj = _make_project(store, tmp_path, source_path=asset.path)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get(f"/api/video/projects/{proj.id}")
        body = r.get_json()
        assert body["ok"]
        states = body["source_permissions"]
        assert states == [
            {
                "asset_id": "ft_1",
                "filename": "ft_1.mp4",
                "permission_status": "needs_parental_consent",
                "approval_status": "approved",
                "usable": False,
            }
        ]


class TestPermissionEditor:
    def test_one_tap_permission_update(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, permission="needs_approval")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post(
                "/api/video/footage/ft_1/permission",
                json={"permission_status": "approved_by_club"},
            )
        assert r.status_code == 200
        assert r.get_json()["asset"]["permission_status"] == "approved_by_club"
        assert r.get_json()["asset"]["usable"] is True
        assert store.get("ft_1").permission_status == "approved_by_club"

    def test_vocabulary_is_validated(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/footage/ft_1/permission", json={"permission_status": "yolo"})
        assert r.status_code == 400
        assert store.get("ft_1").permission_status == "approved_by_club"

    def test_tenant_gated(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, profile_id="beta")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post(
                "/api/video/footage/ft_1/permission",
                json={"permission_status": "do_not_use"},
            )
        assert r.status_code == 403

    def test_footage_summary_carries_badge_signals(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, permission="needs_parental_consent")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get("/api/video/footage")
        item = r.get_json()["footage"][0]
        assert item["permission_status"] == "needs_parental_consent"
        assert item["usable"] is False
        assert item["poster_url"] == ""  # no poster recorded → honest blank


# ---------------------------------------------------------------------------
# M25 — best-frame route
# ---------------------------------------------------------------------------


class TestBestFrameRoute:
    def test_best_frame_route_saves_inherited_photo(self, app_env, monkeypatch):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, permission="needs_approval")
        from mediahub.video.moments import Moment

        monkeypatch.setattr(
            "mediahub.video.moments.detect_moments",
            lambda p, *, duration_ms, target_len_ms, max_moments: [
                Moment(2000, 8000, 0.9, "energy", "cheer")
            ],
        )
        monkeypatch.setattr(
            "mediahub.video.best_frame._ffmpeg_frame", lambda src, at_ms: b"\xff\xd8\xffjpeg"
        )
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/footage/ft_1/best-frame", json={})
        assert r.status_code == 200, r.get_json()
        frame_id = r.get_json()["asset"]["id"]
        frame = store.get(frame_id)
        assert frame.type == "athlete_action"
        assert frame.permission_status == "needs_approval"  # inherited, never wider
        assert frame.linked_athlete_names == ["Eira Hughes"]
        assert frame.media_meta["source_footage_id"] == "ft_1"

    def test_best_frame_honest_when_engine_missing(self, app_env, monkeypatch):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, meta={})  # unmeasured clip
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/footage/ft_1/best-frame", json={})
        assert r.status_code == 503
        assert r.get_json()["error"] == "best_frame_unavailable"

    def test_best_frame_tenant_gated(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, profile_id="beta")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.post("/api/video/footage/ft_1/best-frame", json={})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# M27 — poster served via the asset file route
# ---------------------------------------------------------------------------


class TestPosterRoute:
    def test_poster_served_when_recorded(self, app_env):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(
            store, tmp_path, meta={"duration_ms": 9000, "poster": "ft_1.poster.png"}
        )
        (Path(asset.path).parent / "ft_1.poster.png").write_bytes(b"\x89PNG poster")
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get("/api/media-library/file/ft_1?poster=1")
        assert r.status_code == 200
        assert "image/png" in (r.headers.get("Content-Type") or "")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_poster_honest_404_when_absent(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path)
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get("/api/media-library/file/ft_1?poster=1")
        assert r.status_code == 404

    def test_poster_tenant_gated(self, app_env):
        app, wm, tmp_path, store = app_env
        _add_footage(store, tmp_path, profile_id="beta",
                     meta={"duration_ms": 9000, "poster": "ft_1.poster.png"})
        with app.test_client() as c:
            _pin(c, "alpha")
            r = c.get("/api/media-library/file/ft_1?poster=1")
        assert r.status_code == 403

    def test_footage_summary_links_poster(self, app_env):
        app, wm, tmp_path, store = app_env
        asset = _add_footage(
            store, tmp_path, meta={"duration_ms": 9000, "poster": "ft_1.poster.png"}
        )
        (Path(asset.path).parent / "ft_1.poster.png").write_bytes(b"\x89PNG poster")
        with app.test_client() as c:
            _pin(c, "alpha")
            item = c.get("/api/video/footage").get_json()["footage"][0]
        assert "poster=1" in item["poster_url"]
