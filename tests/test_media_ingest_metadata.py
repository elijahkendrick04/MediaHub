"""PHOTOS-1/6 — the ingest metadata spine on the web upload paths.

Every ingest path (library upload, share-target, per-card) must persist real
measurements (dimensions / orientation / dominant colours / quality metrics),
bake EXIF orientation into the pixels, write canonical asset types, and stamp
``linked_meet_ids`` when the upload happens from an accessible run context.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_ORIENTATION_TAG = 0x0112


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    # Reset the process-level store singleton so each test gets a fresh DB.
    mls._default_store = None

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    return app, wm, tmp_path


def _write_run(wm, run_id: str, profile_id: str = "alpha") -> None:
    run = {"run_id": run_id, "profile_id": profile_id, "meet_name": "Test Open"}
    (wm.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")


def _png_bytes(size=(640, 480), seed=0) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_orientation(size=(600, 400), orientation=6, seed=1) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8), "RGB")
    exif = Image.Exif()
    exif[_ORIENTATION_TAG] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _upload(client, *, data_extra=None, filename="p.png", payload=None):
    data = {
        "file": (io.BytesIO(payload or _png_bytes()), filename, "image/png"),
        "profile_id": "alpha",
    }
    data.update(data_extra or {})
    return client.post(
        "/api/media-library",
        data=data,
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    )


class TestLibraryUploadMeasurement:
    def test_upload_persists_measurements_and_quality(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, data_extra={"asset_type": "athlete_action"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        asset_id = resp.get_json()["asset"]["id"]

        from mediahub.media_library.store import get_store

        a = get_store().get(asset_id)
        assert (a.width, a.height) == (640, 480)
        assert a.orientation == "landscape"
        assert a.dominant_colours  # measured, not the historic []
        q = a.media_meta["quality"]
        assert q["sharpness"] > 0
        assert len(q["dhash"]) == 16
        assert a.has_face is None  # M4: no fake face hint at ingest

    def test_legacy_form_type_normalised_to_canonical(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, data_extra={"asset_type": "athlete_photo"})
        asset_id = resp.get_json()["asset"]["id"]
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id).type == "athlete_action"

    def test_upload_form_offers_canonical_types_only(self, app_env):
        app, wm, tmp_path = app_env
        from mediahub.media_library.models import ASSET_TYPES

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            page = c.get("/media-library").get_data(as_text=True)
        import re as _re

        options = _re.findall(r'<select id="ml-type"[^>]*>(.*?)</select>', page, _re.S)
        assert options, "asset-type select missing from the upload form"
        values = _re.findall(r'<option value="([^"]+)"', options[0])
        assert values
        for v in values:
            assert v in ASSET_TYPES, f"non-canonical form value {v!r}"

    def test_exif_orientation_baked_at_ingest(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(
                c,
                filename="phone.jpg",
                payload=_jpeg_with_orientation((600, 400), orientation=6),
            )
        asset_id = resp.get_json()["asset"]["id"]
        from mediahub.media_library.store import get_store

        a = get_store().get(asset_id)
        # Orientation-6 (rotate to display) 600x400 shows as 400x600 portrait.
        assert (a.width, a.height) == (400, 600)
        assert a.orientation == "portrait"
        with Image.open(a.path) as im:
            assert im.size == (400, 600)  # pixels baked upright…
            assert im.getexif().get(_ORIENTATION_TAG) in (None, 1)  # …tag gone


class TestRunStamping:
    def test_run_context_stamps_linked_meet_ids(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r1", profile_id="alpha")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, data_extra={"run_id": "r1"})
        asset_id = resp.get_json()["asset"]["id"]
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id).linked_meet_ids == ["r1"]

    def test_foreign_orgs_run_never_stamped(self, app_env):
        app, wm, tmp_path = app_env
        _write_run(wm, "r_beta", profile_id="beta")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, data_extra={"run_id": "r_beta"})
        assert resp.status_code == 200  # upload succeeds, just unstamped
        asset_id = resp.get_json()["asset"]["id"]
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id).linked_meet_ids == []

    def test_unknown_run_never_stamped(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = _upload(c, data_extra={"run_id": "nope"})
        asset_id = resp.get_json()["asset"]["id"]
        from mediahub.media_library.store import get_store

        assert get_store().get(asset_id).linked_meet_ids == []


class TestShareTarget:
    def test_share_target_saves_canonical_type_and_measures(self, app_env):
        app, wm, tmp_path = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/share-target",
                data={"photos": (io.BytesIO(_png_bytes((320, 480), seed=3)), "s.png", "image/png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code in (301, 302)
        from mediahub.media_library.store import get_store

        assets = get_store().list(profile_id="alpha")
        assert len(assets) == 1
        a = assets[0]
        assert a.type == "athlete_action"
        assert (a.width, a.height) == (320, 480)
        assert a.orientation == "portrait"
        assert isinstance(a.media_meta.get("quality"), dict)


class TestBackfill:
    def test_backfill_measures_legacy_assets(self, tmp_path):
        from mediahub.media_library.models import MediaAsset
        from mediahub.media_library.store import MediaLibraryStore

        store = MediaLibraryStore(db_path=tmp_path / "m.db", uploads_dir=tmp_path / "up")
        img_path = tmp_path / "legacy.png"
        img_path.write_bytes(_png_bytes((500, 300), seed=4))
        legacy = store.save(
            MediaAsset(
                id="",
                filename="legacy.png",
                path=str(img_path),
                type="athlete_photo",  # legacy alias — canonicalised on read
                profile_id="alpha",
            )
        )
        assert store.get(legacy.id).width == 0  # unmeasured before

        assert store.backfill_measurements(profile_id="alpha") == 1
        a = store.get(legacy.id)
        assert (a.width, a.height) == (500, 300)
        assert a.orientation == "landscape"
        assert isinstance(a.media_meta.get("quality"), dict)
        assert a.type == "athlete_action"  # save() persisted the canonical type

        # Second pass finds nothing left to do.
        assert store.backfill_measurements(profile_id="alpha") == 0

    def test_backfill_skips_missing_files_and_footage(self, tmp_path):
        from mediahub.media_library.models import MediaAsset
        from mediahub.media_library.store import MediaLibraryStore

        store = MediaLibraryStore(db_path=tmp_path / "m.db", uploads_dir=tmp_path / "up")
        store.save(
            MediaAsset(id="", filename="gone.jpg", path=str(tmp_path / "gone.jpg"), profile_id="a")
        )
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"\x00" * 64)
        store.save(
            MediaAsset(
                id="", filename="clip.mp4", path=str(clip), type="footage", profile_id="a"
            )
        )
        assert store.backfill_measurements(profile_id="a") == 0

    def test_backfill_is_profile_scoped(self, tmp_path):
        from mediahub.media_library.models import MediaAsset
        from mediahub.media_library.store import MediaLibraryStore

        store = MediaLibraryStore(db_path=tmp_path / "m.db", uploads_dir=tmp_path / "up")
        img_path = tmp_path / "b.png"
        img_path.write_bytes(_png_bytes((300, 300), seed=5))
        saved = store.save(
            MediaAsset(id="", filename="b.png", path=str(img_path), profile_id="beta")
        )
        assert store.backfill_measurements(profile_id="alpha") == 0
        assert store.get(saved.id).width == 0
        assert store.backfill_measurements(profile_id="beta") == 1
