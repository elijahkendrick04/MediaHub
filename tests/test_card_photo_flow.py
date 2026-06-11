"""Per-card photo flow: upload-on-the-card, athlete memory, delete.

The configure-step photo drop was replaced by a per-graphic control:
each card's panel uploads a photo OF that card's athlete via
POST /api/runs/<run_id>/cards/<card_id>/photo. The photo lands in the
organisation's media library linked to the athlete by name, so the
picker can suggest it again at the next meet, and any asset can be
deleted via POST /api/media-library/<asset_id>/delete.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Tiny valid JPEG header — enough for upload plumbing (no decode happens).
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64


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
    return app, wm, tmp_path


def _write_run(wm, run_id: str, profile_id: str = "alpha") -> None:
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
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
    (wm.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")


class TestCardPhotoUpload:
    def test_upload_links_athlete_and_returns_asset(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r1")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/r1/cards/swim-1/photo",
                data={"photo": (io.BytesIO(_JPEG), "eira.jpg", "image/jpeg")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        j = resp.get_json()
        assert j["ok"] is True
        assert j["asset"]["label"] == "Eira Hughes"
        assert j["asset"]["suggested"] is True

        # The library remembers WHO is in the photo, under the ORG profile
        # (not a run-scoped id) so it carries to the next meet.
        from mediahub.media_library.store import get_store

        a = get_store().get(j["asset"]["id"])
        assert a is not None
        assert a.profile_id == "alpha"
        assert a.linked_athlete_names == ["Eira Hughes"]
        assert a.linked_meet_ids == ["r1"]
        assert a.permission_status == "user_owned"
        assert Path(a.path).exists()

    def test_non_image_rejected(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r1")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/r1/cards/swim-1/photo",
                data={"photo": (io.BytesIO(b"not an image"), "x.txt", "text/plain")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "not_an_image"

    def test_unknown_card_404(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r1")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/r1/cards/nope/photo",
                data={"photo": (io.BytesIO(_JPEG), "p.jpg", "image/jpeg")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 404

    def test_foreign_session_cannot_upload(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r1", profile_id="alpha")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "beta"})
            resp = c.post(
                "/api/runs/r1/cards/swim-1/photo",
                data={"photo": (io.BytesIO(_JPEG), "p.jpg", "image/jpeg")},
                content_type="multipart/form-data",
            )
        # The run gate hides the run entirely from the wrong org.
        assert resp.status_code == 404


class TestMediaAssetDelete:
    def _seed(self, tmp_path, profile_id="alpha"):
        from mediahub.media_library.models import MediaAsset
        from mediahub.media_library.store import get_store

        p = tmp_path / f"{profile_id}_x.jpg"
        p.write_bytes(_JPEG)
        a = get_store().save(
            MediaAsset(
                id="",
                filename="x.jpg",
                path=str(p),
                type="athlete_action",
                profile_id=profile_id,
            )
        )
        return a.id, p

    def test_delete_removes_record_and_file(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            asset_id, path = self._seed(tmp_path)
            resp = c.post(
                f"/api/media-library/{asset_id}/delete",
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id) is None
        assert not path.exists()

    def test_cannot_delete_other_orgs_asset(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "beta"})
            asset_id, path = self._seed(tmp_path, profile_id="alpha")
            resp = c.post(
                f"/api/media-library/{asset_id}/delete",
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 403
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id) is not None
        assert path.exists()

    def test_delete_unknown_404(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library/ma_doesnotexist/delete",
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 404
