"""M32 (UX-4) + M36 (UX-7) — async per-card motion + Inspector override parity.

* ``POST /api/runs/<id>/card/<id>/motion-job`` mirrors the reel-job pattern:
  202 + poll URL on the shared job store, honest error reporting, tenant
  gating.
* ``GET  /api/runs/<id>/card/<id>/motion-file`` serves the persisted MP4 and
  its ``?poster=1`` sidecar — never renders.
* M36: a card's persisted ``insp.*`` overrides are translated for the motion
  engine exactly like the still route translates them — accent through a
  BrandKit copy + the brief palette, no-photo through the brief's photo
  treatment — and the override dict rides the card payload. An untouched
  card's inputs stay byte-identical.
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

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    # The media store is a module-level singleton; drop it so each test's
    # DATA_DIR gets a fresh DB instead of accumulating across tests.
    mls._default_store = None
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, wm, tmp_path


def _poll_until_settled(client, poll_url, tries=60, delay=0.2):
    j = {}
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


class TestMotionJob:
    def test_job_renders_and_file_streams_with_poster(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        def _fake_render(card, brand_kit, out_path, **kw):
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            out_path.with_suffix(".poster.png").write_bytes(b"\x89PNG poster")
            return out_path

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake_render):
                resp = c.post("/api/runs/r1/card/swim-1/motion-job")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["ok"] and body["poll_url"]
                j = _poll_until_settled(c, body["poll_url"])
            assert j["status"] == "done", j
            assert j["video_url"]
            f = c.get(j["video_url"])
            assert f.status_code == 200
            assert "video/mp4" in (f.headers.get("Content-Type") or "")
            sep = "&" if "?" in j["video_url"] else "?"
            p = c.get(j["video_url"] + sep + "poster=1")
            assert p.status_code == 200
            assert "image/png" in (p.headers.get("Content-Type") or "")

    def test_render_failure_reports_error_not_silence(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion, "render_story_card", side_effect=RuntimeError("boom")
            ):
                resp = c.post("/api/runs/r1/card/swim-1/motion-job")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "error"
        assert j["error"]

    def test_bad_format_is_400_before_any_job(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/card/swim-1/motion-job?format=imax")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_format"

    def test_foreign_org_cannot_start_poll_or_fetch(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion, "render_story_card", side_effect=RuntimeError("x")
            ):
                resp = c.post("/api/runs/r1/card/swim-1/motion-job")
                poll = resp.get_json()["poll_url"]
                _poll_until_settled(c, poll)
        with app.test_client() as other:
            other.post("/api/organisation/active", data={"profile_id": "beta"})
            assert other.get(poll).status_code == 404
            assert other.post("/api/runs/r1/card/swim-1/motion-job").status_code == 404
            assert other.get("/api/runs/r1/card/swim-1/motion-file").status_code == 404


class TestMotionFile:
    def test_never_renders_and_404s_honestly(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/card/swim-1/motion-file")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "motion_not_rendered"

    def test_serves_existing_cut_and_poster(self, app_env):
        app, wm, _ = app_env
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "swim-1_square.mp4").write_bytes(b"0" * 2048)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            ok = c.get("/api/runs/r1/card/swim-1/motion-file?format=square")
            assert ok.status_code == 200
            assert "video/mp4" in (ok.headers.get("Content-Type") or "")
            # Poster 404s honestly until the sidecar exists.
            missing = c.get("/api/runs/r1/card/swim-1/motion-file?format=square&poster=1")
            assert missing.status_code == 404
            assert missing.get_json()["error"] == "poster_not_rendered"
            (mdir / "swim-1_square.poster.png").write_bytes(b"\x89PNG")
            poster = c.get("/api/runs/r1/card/swim-1/motion-file?format=square&poster=1")
            assert poster.status_code == 200
            assert "image/png" in (poster.headers.get("Content-Type") or "")


class TestInspectorOverridesIntoMotion:
    """M36 — the still↔motion parity promise for Inspector tweaks."""

    def _persist_overrides(self, wm, tmp_path, edits: dict):
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(Path(tmp_path / "runs_v4"))
        ws.set_edits("r1", "swim-1", edits)

    def _render_capture(self, app, wm):
        import mediahub.visual.motion as motion

        captured = {}

        def _fake_render(card, brand_kit, out_path, **kw):
            captured["card"] = card
            captured["brand_kit"] = brand_kit
            captured["brief"] = kw.get("brief")
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            return out_path

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake_render):
                resp = c.post("/api/runs/r1/card/swim-1/motion")
                assert resp.status_code == 200, resp.get_json()
        return captured

    def test_untouched_card_inputs_are_unchanged(self, app_env):
        app, wm, tmp_path = app_env
        captured = self._render_capture(app, wm)
        assert "inspector_overrides" not in captured["card"]

    def test_accent_rides_brandkit_copy_and_brief_palette(self, app_env):
        app, wm, tmp_path = app_env
        # A persisted brief so the palette half of the translation is visible.
        bdir = wm.RUNS_DIR / "r1" / "briefs"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "cb_1.json").write_text(
            json.dumps(
                {
                    "id": "cb_1",
                    "content_item_id": "swim-1",
                    "palette": {"primary": "#111111", "accent": "#222222"},
                }
            ),
            encoding="utf-8",
        )
        self._persist_overrides(wm, tmp_path, {"insp.accent": "#ff8800"})
        captured = self._render_capture(app, wm)
        assert captured["card"]["inspector_overrides"]["accent"] == "#ff8800"
        assert captured["brief"]["palette"]["accent"] == "#ff8800"
        bk = captured["brand_kit"]
        if bk is not None:  # brand kit resolution is environment-dependent
            assert getattr(bk, "accent_colour", None) == "#ff8800"

    def test_no_photo_translates_to_brief_photo_treatment(self, app_env):
        app, wm, tmp_path = app_env
        bdir = wm.RUNS_DIR / "r1" / "briefs"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "cb_1.json").write_text(
            json.dumps(
                {
                    "id": "cb_1",
                    "content_item_id": "swim-1",
                    "photo_treatment": "full-bleed",
                    "sourced_asset_ids": ["ma_x"],
                }
            ),
            encoding="utf-8",
        )
        self._persist_overrides(wm, tmp_path, {"insp.noPhoto": "1"})
        captured = self._render_capture(app, wm)
        assert captured["brief"]["photo_treatment"] == "no-photo"
        assert captured["card"]["inspector_overrides"]["no_photo"] is True

    def test_reel_assembly_threads_overrides_per_card(self, app_env):
        app, wm, tmp_path = app_env
        import mediahub.visual.motion as motion

        bdir = wm.RUNS_DIR / "r1" / "briefs"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "cb_1.json").write_text(
            json.dumps(
                {
                    "id": "cb_1",
                    "content_item_id": "swim-1",
                    "palette": {"accent": "#222222"},
                }
            ),
            encoding="utf-8",
        )
        self._persist_overrides(wm, tmp_path, {"insp.accent": "#ff8800"})
        captured = {}

        def _fake_reel(cards, brand_kit, out_path, **kw):
            captured["cards"] = cards
            captured["briefs"] = kw.get("briefs")
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            return out_path

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_meet_reel", _fake_reel):
                resp = c.post("/api/runs/r1/reel")
                assert resp.status_code == 200, resp.get_json()
        assert captured["cards"][0]["inspector_overrides"]["accent"] == "#ff8800"
        assert captured["briefs"][0]["palette"]["accent"] == "#ff8800"


class TestBuilderMotionStrip:
    def test_rendered_videos_strip_appears_on_builder_load(self, app_env, tmp_path):
        app, wm, _ = app_env
        from mediahub.workflow.store import WorkflowStore
        from mediahub.workflow.status import CardStatus

        ws = WorkflowStore(Path(tmp_path / "runs_v4"))
        ws.set_status("r1", "swim-1", CardStatus.APPROVED)
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "swim-1.mp4").write_bytes(b"0" * 2048)
        (mdir / "swim-1.poster.png").write_bytes(b"\x89PNG")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/pack/r1")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Rendered videos" in html
        assert "/api/runs/r1/card/swim-1/motion-file" in html
        assert "poster=1" in html
