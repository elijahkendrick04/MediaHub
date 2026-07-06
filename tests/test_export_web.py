"""Web surface for the export & conversion engine (roadmap 1.19).

Covers the capability API, the Export Center pages, the media-library
quick-action route, and the background bulk-export job (kick → poll → download)
including the unified 1.18-token share link and multi-tenant isolation.

No Playwright/FFmpeg needed: bulk export and quick actions are driven with image
formats over tiny real PNGs, exactly as the renderer would have written them.
"""

from __future__ import annotations

import importlib
import json
import struct
import time
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

import pytest


def _make_png(width: int, height: int, *, fill: int = 0xC0) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = (b"\x00" + bytes([fill, 0x30, 0x80]) * width) * height
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A", brand_voice_summary="Friendly."))
    save_profile(ClubProfile(profile_id="club-b", display_name="Club B", brand_voice_summary="Serious."))

    with app.test_client() as c:
        yield c, wm, tmp_path


def _pin(c, profile_id: str):
    resp = c.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


def _seed_run(runs_dir: Path, run_id: str, profile_id: str, *, with_visuals=True):
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {"run_id": run_id, "profile_id": profile_id, "meet": {"name": "Manchester Open"}}
        ),
        encoding="utf-8",
    )
    if with_visuals:
        for brief, cid in (("brief_a", "card-A"), ("brief_b", "card-B")):
            d = runs_dir / run_id / "visuals" / brief
            d.mkdir(parents=True, exist_ok=True)
            (d / "feed_portrait.png").write_bytes(_make_png(120, 150))


def _add_asset(wm, tmp_path: Path, profile_id: str, *, name="photo.png") -> str:
    from mediahub.media_library.models import MediaAsset

    img = tmp_path / "uploads_v4" / name
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(_make_png(200, 120))
    store = wm._v8_get_media_store()
    asset = MediaAsset(id="", filename=name, path=str(img), type="other", profile_id=profile_id)
    saved = store.save(asset)
    return saved.id


def _wait_done(c, poll_url: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(0.1)
    raise AssertionError("bulk export job did not finish in time")


# ---------------------------------------------------------------------------


class TestFormatsApi:
    def test_catalogue(self, client):
        c, _wm, _tp = client
        _pin(c, "club-a")
        j = c.get("/api/export/formats").get_json()
        assert j["ok"] is True
        assert "image" in j["categories"]
        keys = {f["key"] for fams in j["categories"].values() for f in fams}
        assert {"png", "jpg", "svg", "gif", "webm", "pptx", "docx", "wav", "zip"} <= keys
        assert "video" in j["quick_actions"]
        assert "status" in j

    def test_jpeg_advertises_quality_option(self, client):
        c, _wm, _tp = client
        _pin(c, "club-a")
        j = c.get("/api/export/formats").get_json()
        jpg = next(f for f in j["categories"]["image"] if f["key"] == "jpg")
        assert "quality" in jpg["accepts"]


class TestExportCenterPage:
    def test_landing_renders(self, client):
        c, _wm, _tp = client
        _pin(c, "club-a")
        resp = c.get("/export")
        assert resp.status_code == 200
        assert b"Export" in resp.data

    def test_run_tool_renders_for_owner(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        resp = c.get("/export/run-a1")
        assert resp.status_code == 200
        assert b"Bulk export" in resp.data

    def test_run_tool_404_for_other_org(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-b")
        assert c.get("/export/run-a1").status_code == 404


class TestQuickAction:
    def test_convert_image_streams_jpeg(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        aid = _add_asset(wm, tmp, "club-a")
        resp = c.post(
            f"/api/media-library/{aid}/quick-action",
            json={"action": "convert", "format": "jpg", "options": {"quality": 70}},
        )
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert resp.data[:2] == b"\xff\xd8"  # JPEG magic

    def test_resize_image(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        aid = _add_asset(wm, tmp, "club-a")
        resp = c.post(
            f"/api/media-library/{aid}/quick-action",
            json={"action": "resize", "width": 100},
        )
        assert resp.status_code == 200
        from PIL import Image

        assert Image.open(BytesIO(resp.data)).size == (100, 60)

    def test_unknown_action_is_400(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        aid = _add_asset(wm, tmp, "club-a")
        resp = c.post(f"/api/media-library/{aid}/quick-action", json={"action": "frobnicate"})
        assert resp.status_code == 400

    def test_other_org_forbidden(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        aid = _add_asset(wm, tmp, "club-a")
        _pin(c, "club-b")
        resp = c.post(f"/api/media-library/{aid}/quick-action", json={"action": "convert", "format": "png"})
        assert resp.status_code == 403

    def test_missing_asset_404(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        resp = c.post("/api/media-library/ma_doesnotexist/quick-action", json={"action": "convert"})
        assert resp.status_code == 404


class TestBulkExport:
    def test_kick_poll_download(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        kick = c.post("/api/runs/run-a1/bulk-export", json={"formats": ["jpg", "webp"], "options": {"quality": 80}})
        assert kick.status_code == 202
        kj = kick.get_json()
        assert kj["ok"] and kj["job_id"]
        done = _wait_done(c, kj["poll_url"])
        assert done["status"] == "done"
        assert done["file_count"] == 4  # 2 cards × 2 formats
        # Download the finished ZIP.
        resp = c.get(done["file_url"])
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"
        with zipfile.ZipFile(BytesIO(resp.data)) as zf:
            names = zf.namelist()
        assert any(n.endswith(".jpg") for n in names)
        assert any(n.endswith(".webp") for n in names)
        assert any(n.endswith("manifest.json") for n in names)

    def test_no_visuals_404(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-empty", "club-a", with_visuals=False)
        _pin(c, "club-a")
        resp = c.post("/api/runs/run-empty/bulk-export", json={"formats": ["jpg"]})
        assert resp.status_code == 404

    def test_invalid_formats_400(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        resp = c.post("/api/runs/run-a1/bulk-export", json={"formats": ["nonsense"]})
        assert resp.status_code == 400

    def test_tenant_isolation(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-b")
        resp = c.post("/api/runs/run-a1/bulk-export", json={"formats": ["jpg"]})
        assert resp.status_code == 404

    def test_share_link_grants_token_download(self, client):
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        kick = c.post("/api/runs/run-a1/bulk-export", json={"formats": ["jpg"]}).get_json()
        done = _wait_done(c, kick["poll_url"])
        assert done["status"] == "done"
        share = c.post("/api/runs/run-a1/export-share", json={"job": kick["job_id"]})
        assert share.status_code == 200
        sj = share.get_json()
        assert sj["ok"] and sj["token"] and sj["url"]
        # A signed-out client (fresh session) can fetch via the token link.
        anon = c.application.test_client()
        resp = anon.get(sj["url"])
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"

    def test_status_unknown_job_404(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        assert c.get("/api/export-jobs/" + "f" * 32).status_code == 404

    def test_card_scoped_token_cannot_download_run_zip(self, client):
        """A 1.18 share token minted for ONE card must not unlock the whole
        run's export ZIP — only run-wide tokens (no card_id) may."""
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        kick = c.post("/api/runs/run-a1/bulk-export", json={"formats": ["jpg"]}).get_json()
        done = _wait_done(c, kick["poll_url"])
        assert done["status"] == "done"
        from mediahub.collab import share_tokens as st

        card_share = st.create_share(
            run_id="run-a1", card_id="card-A", perm=st.PERM_VIEW, created_by="owner"
        )
        run_share = st.create_share(run_id="run-a1", perm=st.PERM_VIEW, created_by="owner")
        anon = c.application.test_client()
        url = f"/api/runs/run-a1/bulk-export/file?job={kick['job_id']}"
        # anonymous with no token at all is refused (session OR token contract)
        assert anon.get(url).status_code == 404
        assert anon.get(f"{url}&token={card_share.token}").status_code == 404
        ok = anon.get(f"{url}&token={run_share.token}")
        assert ok.status_code == 200
        assert ok.mimetype == "application/zip"

    def test_malformed_formats_and_options_are_not_500(self, client):
        """Junk client JSON must be a clean 4xx / defaulted request, never an
        AttributeError 500 inside normalise_key / ExportOptions.from_dict."""
        c, wm, tmp = client
        _seed_run(tmp / "runs_v4", "run-a1", "club-a")
        _pin(c, "club-a")
        # non-string format entries → filtered out → honest 400
        resp = c.post("/api/runs/run-a1/bulk-export", json={"formats": [5]})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "no_valid_formats"
        # a non-dict options blob falls back to defaults; the job still kicks
        resp = c.post(
            "/api/runs/run-a1/bulk-export", json={"formats": ["jpg"], "options": "junk"}
        )
        assert resp.status_code == 202
        assert _wait_done(c, resp.get_json()["poll_url"])["status"] == "done"
        # same guard on the quick-action route
        aid = _add_asset(wm, tmp, "club-a")
        r = c.post(
            f"/api/media-library/{aid}/quick-action",
            json={"action": "convert", "format": "png", "options": "junk"},
        )
        assert r.status_code == 200


class TestUiEntryPoints:
    """The 1.19 surfaces are reachable from the product (not API-only)."""

    def test_media_library_rows_carry_quick_action_menu(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        _add_asset(wm, tmp, "club-a")
        page = c.get("/media-library")
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert "mh-ml-qa" in body  # the per-row Convert control + its JS
        assert "/quick-action" in body
        assert 'data-formats-url="/api/export/formats"' in body

    def test_help_page_links_export_and_print_centres(self, client):
        c, wm, tmp = client
        _pin(c, "club-a")
        body = c.get("/help").get_data(as_text=True)
        assert 'href="/export"' in body
        assert 'href="/print"' in body
