"""Media library profile isolation tests.

Verifies the two halves of the "library per profile, wired into creator tools"
change:

  1. Profile isolation — one org's media is never reachable from another
     org's session. Covers the file-serve route, the JSON list endpoint,
     the upload endpoint, and the picker rendered into stub forms.

  2. Creator-tool wiring — the active profile's library is offered as a
     picker on every stub creator form, picks survive the POST onto the
     saved pack, and foreign ids are silently dropped (not 500'd).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _tiny_jpeg() -> bytes:
    """A real, decodable JPEG — ingest now verifies uploads actually decode."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG_BYTES = _tiny_jpeg()


@pytest.fixture
def two_org_app(app, tmp_path):
    """A fresh Flask app with two saved profiles + the org gate disabled.

    The org gate is bypassed because these tests focus on the media
    library access rules, not the gate itself.
    """
    # DATA_DIR isolation + web-module reset come from the canonical `app`
    # fixture (conftest.py), replacing the old setenv + importlib.reload preamble.
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))

    return app, tmp_path


def _seed_asset(tmp_path: Path, profile_id: str, filename: str = "p.jpg") -> tuple[str, Path]:
    """Save a real asset file + a media_library row for a given profile."""
    from mediahub.media_library.store import get_store
    from mediahub.media_library.models import MediaAsset

    asset_path = tmp_path / f"{profile_id}_{filename}"
    asset_path.write_bytes(_JPEG_BYTES)
    store = get_store()
    asset = MediaAsset(
        id="",
        filename=filename,
        path=str(asset_path),
        type="athlete_photo",
        profile_id=profile_id,
        permission_status="approved_by_club",
        approval_status="approved",
        linked_athlete_names=[f"{profile_id.title()} Swimmer"],
    )
    saved = store.save(asset)
    return saved.id, asset_path


class TestFileServeIsolation:
    """The /api/media-library/file/<id> route must enforce profile scope."""

    def test_same_profile_can_view(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha")
            resp = c.get(f"/api/media-library/file/{alpha_id}")
        assert resp.status_code == 200, "session pinned to alpha must see its own asset"

    def test_other_profile_is_forbidden(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _alpha_id, _ = _seed_asset(tmp_path, "alpha")
            beta_id, _ = _seed_asset(tmp_path, "beta")
            resp = c.get(f"/api/media-library/file/{beta_id}")
        assert resp.status_code == 403, (
            "session pinned to alpha must not be able to read beta's "
            f"asset; got {resp.status_code} {resp.data!r}"
        )

    def test_run_scoped_profile_is_allowed(self, two_org_app):
        # A _run_ asset whose run has no owner on file (ownerless/legacy)
        # inherits the run routes' ownerless-readable policy — still 200.
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            run_id, _ = _seed_asset(tmp_path, "_run_abcdef123")
            resp = c.get(f"/api/media-library/file/{run_id}")
        assert resp.status_code == 200, (
            "an ownerless run-scoped asset is allowed because privacy "
            "is enforced at the run level — got 403 unexpectedly"
        )

    def test_run_scoped_asset_for_foreign_run_is_blocked(self, two_org_app):
        """IDOR regression: a _run_<id> asset must inherit its run's access
        policy, not blanket-allow. An asset tied to a run owned by beta must
        NOT be readable from an alpha-pinned session even if its id leaks."""
        app, tmp_path = two_org_app
        run_dir = tmp_path / "runs_v4"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "runbeta9.json").write_text(
            json.dumps({"run_id": "runbeta9", "profile_id": "beta"})
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            asset_id, _ = _seed_asset(tmp_path, "_run_runbeta9")
            resp = c.get(f"/api/media-library/file/{asset_id}")
        assert resp.status_code in (403, 404), (
            "a _run_ asset tied to beta's run must not be readable from an "
            f"alpha session; got {resp.status_code} {resp.data!r}"
        )

    def test_served_file_carries_image_mime_and_nosniff(self, two_org_app):
        """Served library files must never trust the uploader: image/* type
        derived from the stored file, nosniff, inline disposition."""
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha")
            resp = c.get(f"/api/media-library/file/{alpha_id}")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("image/jpeg")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Content-Disposition"].startswith("inline;")

    def test_legacy_active_content_downloads_never_renders(self, two_org_app):
        """A pre-allowlist legacy asset with an active-content suffix (.svg)
        must come back as a plain download, never image/svg+xml inline."""
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            svg_id, _ = _seed_asset(tmp_path, "alpha", filename="legacy.svg")
            resp = c.get(f"/api/media-library/file/{svg_id}")
        assert resp.status_code == 200
        ctype = resp.headers["Content-Type"]
        assert "svg" not in ctype and "html" not in ctype, ctype
        assert ctype.startswith("application/octet-stream")
        assert resp.headers["Content-Disposition"].startswith("attachment")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"


class TestListJsonIsolation:
    """The /api/media-library/list.json route must scope to the active profile."""

    def test_list_returns_active_profile_assets(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            a_id, _ = _seed_asset(tmp_path, "alpha", filename="a.jpg")
            _b_id, _ = _seed_asset(tmp_path, "beta", filename="b.jpg")
            resp = c.get("/api/media-library/list.json")
        assert resp.status_code == 200
        body = json.loads(resp.data.decode("utf-8"))
        assert body["profile_id"] == "alpha"
        returned_ids = {a["id"] for a in body["assets"]}
        assert a_id in returned_ids
        assert all(
            a["id"] != _b_id for a in body["assets"]
        ), "beta's asset must not appear in alpha's list"

    def test_explicit_foreign_profile_id_rejected(self, two_org_app):
        app, _ = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/media-library/list.json?profile_id=beta")
        assert resp.status_code == 403, (
            "asking the JSON endpoint for another org's library must be "
            f"rejected; got {resp.status_code} {resp.data!r}"
        )


class TestUploadIsolation:
    """POST /api/media-library must reject uploads aimed at another org."""

    def test_upload_to_active_profile_succeeds(self, two_org_app):
        app, _ = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={
                    "file": (io.BytesIO(_JPEG_BYTES), "x.jpg"),
                    "profile_id": "alpha",
                    "description": "test asset",
                    "asset_type": "athlete_photo",
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code in (200, 302), (
            f"alpha session uploading to alpha must be allowed; " f"got {resp.status_code}"
        )

    def test_upload_disallowed_extension_rejected(self, two_org_app):
        """Active-content types (.svg/.html) must never enter the library —
        files are served back same-origin, so a stored SVG/HTML would be a
        stored-XSS vector. Nothing may be left on disk after rejection."""
        app, tmp_path = two_org_app
        payloads = [
            (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.svg"),
            (b"<html><script>alert(1)</script></html>", "x.html"),
        ]
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            for raw, name in payloads:
                resp = c.post(
                    "/api/media-library",
                    data={
                        "file": (io.BytesIO(raw), name),
                        "profile_id": "alpha",
                        "asset_type": "athlete_photo",
                    },
                    content_type="multipart/form-data",
                    headers={"Accept": "application/json"},
                )
                assert resp.status_code == 415, (name, resp.status_code, resp.data)
                assert json.loads(resp.data)["error"] == "unsupported_type"
        leftovers = (
            list((tmp_path / "uploads_v4" / "media_library").rglob("*"))
            if (tmp_path / "uploads_v4" / "media_library").exists()
            else []
        )
        assert not [p for p in leftovers if p.is_file()], leftovers

    def test_upload_renamed_nonimage_rejected(self, two_org_app):
        """A non-image renamed to .jpg fails the decode check (415), and the
        rejected file is not left orphaned on disk."""
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={
                    "file": (io.BytesIO(b"<html><script>alert(1)</script></html>"), "x.jpg"),
                    "profile_id": "alpha",
                    "asset_type": "athlete_photo",
                },
                content_type="multipart/form-data",
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 415, (resp.status_code, resp.data)
        assert json.loads(resp.data)["error"] == "unreadable_photo"
        lib_dir = tmp_path / "uploads_v4" / "media_library"
        leftovers = [p for p in lib_dir.rglob("*") if p.is_file()] if lib_dir.exists() else []
        assert not leftovers, leftovers

    def test_upload_corrupt_heic_rejected_no_orphan(self, two_org_app):
        """A corrupt/truncated .heic must 415 honestly (never 500) and must
        not leave the saved asset_*.heic orphaned in the uploads dir."""
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={
                    "file": (io.BytesIO(b"truncated-heic-bytes"), "IMG_0001.heic"),
                    "profile_id": "alpha",
                    "asset_type": "athlete_photo",
                },
                content_type="multipart/form-data",
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 415, (resp.status_code, resp.data)
        # Decoder present → unreadable bytes; decoder absent → heic support.
        assert json.loads(resp.data)["error"] in ("unreadable_photo", "heic_unsupported")
        lib_dir = tmp_path / "uploads_v4" / "media_library"
        leftovers = [p for p in lib_dir.rglob("*") if p.is_file()] if lib_dir.exists() else []
        assert not leftovers, leftovers

    def test_upload_to_foreign_profile_is_forbidden(self, two_org_app):
        app, _ = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/media-library",
                data={
                    "file": (io.BytesIO(_JPEG_BYTES), "x.jpg"),
                    "profile_id": "beta",
                    "description": "should be blocked",
                    "asset_type": "athlete_photo",
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code == 403, (
            "alpha session must not be able to upload into beta's "
            f"library; got {resp.status_code} {resp.data!r}"
        )


class TestLibraryPageScope:
    """The /media-library page must honour the active org pin."""

    def test_default_shows_active_profile(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")
            resp = c.get("/media-library")
        body = resp.get_data(as_text=True)
        assert "alpha" in body, "library page should default to the session's active profile"

    def test_query_string_for_foreign_profile_redirects(self, two_org_app):
        app, _ = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/media-library?profile_id=beta", follow_redirects=False)
        assert resp.status_code == 302, (
            "asking /media-library to render another org's library must "
            "redirect back to the active org's library, not silently show "
            "the foreign assets"
        )


class TestStubLibraryPicker:
    """Stub creator forms must expose the active profile's library."""

    def test_picker_renders_active_library_thumbnails(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")
            resp = c.get("/weekend-preview")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert (
            "Pick from your library" in body
        ), "weekend-preview must render the library picker section"
        assert alpha_id in body, "the picker should list the active org's asset by id"

    def test_picker_does_not_show_foreign_assets(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")
            beta_id, _ = _seed_asset(tmp_path, "beta", filename="beta_pic.jpg")
            resp = c.get("/weekend-preview")
        body = resp.get_data(as_text=True)
        assert beta_id not in body, (
            "the picker on alpha's weekend-preview must NEVER show " "beta's asset id"
        )

    def test_picker_appears_on_all_stub_forms(self, two_org_app):
        # C-11: /sponsor-post and /session-update no longer render forms —
        # they redirect into the free-text landing (which has its own
        # picker-equivalent photo attach) — so only the live stub forms
        # are asserted here.
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            _seed_asset(tmp_path, "alpha")
            for url in ("/weekend-preview", "/free-text/quick"):
                resp = c.get(url)
                assert resp.status_code == 200, f"{url} returned {resp.status_code}"
                assert "Pick from your library" in resp.get_data(as_text=True), (
                    f"{url} is missing the media-library picker — content "
                    "creator tools must be wired to the library"
                )


class TestStubPickPersistence:
    """Selected library_asset_id values must be carried onto the saved pack."""

    def test_selected_id_persists_on_saved_pack(self, two_org_app, monkeypatch):
        # Force the LLM path to return one deterministic card so we don't
        # need a real provider just to verify the persistence behaviour.
        import mediahub.club_platform.stubs as _stubs

        def _stub_generate(*args, **kwargs):
            return {
                "cards": [
                    {
                        "platform": "Instagram",
                        "caption": "Test caption",
                        "hashtags": ["test"],
                        "confidence": 0.7,
                        "notes": "from test",
                    }
                ]
            }

        monkeypatch.setattr(_stubs, "_generate_cards_via_llm", _stub_generate)

        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")
            resp = c.post(
                "/weekend-preview",
                data={
                    "meet_name": "Test Meet",
                    "date_venue": "today, here",
                    "athletes": "Alex — 50 Free",
                    "library_asset_id": alpha_id,
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code == 200

        # The saved pack JSON should now mention this asset id.
        packs_dir = tmp_path / "stub_packs"
        all_files = list(packs_dir.glob("*.json"))
        assert all_files, f"no stub_packs persisted under {packs_dir}"
        pack = json.loads(all_files[0].read_text())
        form_data = pack.get("form_data") or {}
        assert alpha_id in (form_data.get("library_asset_ids") or ""), (
            f"saved pack must carry library_asset_ids that include the "
            f"picked id {alpha_id}; got {form_data!r}"
        )

    def test_foreign_id_dropped_silently(self, two_org_app, monkeypatch):
        import mediahub.club_platform.stubs as _stubs

        def _stub_generate(*args, **kwargs):
            return {
                "cards": [
                    {
                        "platform": "Instagram",
                        "caption": "Test",
                        "hashtags": [],
                        "confidence": 0.5,
                        "notes": "",
                    }
                ]
            }

        monkeypatch.setattr(_stubs, "_generate_cards_via_llm", _stub_generate)

        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            beta_id, _ = _seed_asset(tmp_path, "beta", filename="beta_pic.jpg")
            resp = c.post(
                "/weekend-preview",
                data={
                    "meet_name": "Test Meet",
                    "library_asset_id": beta_id,
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code == 200, (
            "submitting a foreign asset id must not 500; the server "
            "should silently drop the id and persist the pack regardless"
        )

        packs_dir = tmp_path / "stub_packs"
        all_files = list(packs_dir.glob("*.json"))
        assert all_files
        pack = json.loads(all_files[0].read_text())
        form_data = pack.get("form_data") or {}
        assert beta_id not in (form_data.get("library_asset_ids") or ""), (
            "alpha's session must not be able to attach beta's asset id " "to a saved pack"
        )


class TestFreeTextChatPicker:
    """The /free-text/chat brief-builder must also expose the library."""

    def test_picker_renders_on_accepted_brief(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")

            from mediahub.free_text_chat.session import create_session, save_session

            s = create_session()
            s.accepted_brief = {
                "headline": "Test headline",
                "body": "Test body content.",
                "platform": "Instagram",
                "hashtags": ["test"],
            }
            save_session(s)

            resp = c.get(f"/free-text/chat/{s.chat_id}")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert (
            "Pick from your library" in body
        ), "free-text chat accepted-brief panel must offer the library picker"
        assert alpha_id in body, "the chat picker should list the active org's asset id"

    def test_chat_generate_carries_library_pick(self, two_org_app):
        app, tmp_path = two_org_app
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            alpha_id, _ = _seed_asset(tmp_path, "alpha", filename="alpha_pic.jpg")

            from mediahub.free_text_chat.session import create_session, save_session

            s = create_session()
            s.accepted_brief = {
                "headline": "Test headline",
                "body": "Test body.",
                "platform": "Instagram",
            }
            save_session(s)

            resp = c.post(
                f"/free-text/chat/{s.chat_id}/generate",
                data={"library_asset_id": alpha_id},
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code == 302, (
            f"chat-generate must redirect to the saved pack; " f"got {resp.status_code}"
        )
        packs_dir = tmp_path / "stub_packs"
        all_files = list(packs_dir.glob("*.json"))
        assert all_files
        pack = json.loads(all_files[0].read_text())
        form_data = pack.get("form_data") or {}
        assert alpha_id in (form_data.get("library_asset_ids") or ""), (
            "chat-generate must persist the picked library_asset_id onto "
            f"the saved pack; got form_data={form_data!r}"
        )


class TestRunGraphicDefenseInDepth:
    """Cross-org access to a run's library via the graphic-creation route."""

    def _seed_run(self, tmp_path: Path, run_id: str, profile_id: str) -> None:
        """Write a minimal run JSON pinned to a specific organisation."""
        run_dir = tmp_path / "runs_v4"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "profile_id": profile_id,
                    "meet": {"name": "Test Meet"},
                    "recognition_report": {
                        "ranked_achievements": [
                            {
                                "achievement": {
                                    "swim_id": "card1",
                                    "swimmer_name": "Test Swimmer",
                                    "event": "100 Free",
                                    "headline": "PB!",
                                },
                                "safe_to_post": {"level": "safe"},
                            }
                        ],
                    },
                }
            )
        )

    def test_foreign_session_cannot_render_run_graphic(self, two_org_app):
        app, tmp_path = two_org_app
        # Run pinned to beta. Alpha session must NOT be able to render
        # a graphic that would pull beta's library into the output.
        self._seed_run(tmp_path, "run_beta_1", "beta")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/run_beta_1/cards/card1/create-graphic",
            )
        # The tenant-isolation guard returns 404 (existence oracle
        # prevention) before the older 403 per-profile gate is reached;
        # either is acceptable as long as the request is refused.
        assert resp.status_code in (403, 404), (
            f"alpha session must not be able to render a graphic for a run "
            f"pinned to beta; got {resp.status_code} {resp.data!r}"
        )

    def test_same_session_can_render_run_graphic(self, two_org_app, web_module, monkeypatch):
        app, tmp_path = two_org_app
        self._seed_run(tmp_path, "run_alpha_1", "alpha")

        # Stub the visual generator so we don't have to set up the
        # full creative-brief + renderer stack just to check the gate.
        wm = web_module

        def _fake_visual(item, brand_kit, **kwargs):
            return {"visuals": [], "brief": None, "errors": []}

        # The create-graphic route resolves _v8_create_visual_for_item from the
        # module namespace, so patch it before building the app for this test.
        monkeypatch.setattr(wm, "_v8_create_visual_for_item", _fake_visual, raising=False)
        app2 = wm.create_app()
        app2.config["TESTING"] = True

        # Re-seed the asset/run for the fresh app context
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
        save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
        self._seed_run(tmp_path, "run_alpha_1", "alpha")

        with app2.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post(
                "/api/runs/run_alpha_1/cards/card1/create-graphic",
            )
        # The route may return 200/500 depending on whether the visual
        # pipeline could fully execute, but it must NOT return 403.
        assert resp.status_code != 403, (
            f"alpha session must be allowed to render its own run's "
            f"graphic; got {resp.status_code} {resp.data!r}"
        )
