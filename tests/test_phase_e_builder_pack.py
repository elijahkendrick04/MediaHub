"""M30 (UX-2) + M33 (UX-5) + M35 (UX-6) — build the whole pack.

* persisted visuals pre-render each card's panel on builder load (no
  re-render), the export ZIP buttons carry the live rendered count, and a
  "Pack preview" wall shows the rendered PNGs as a 3-column feed grid;
* the "Create all graphics" background job renders every approved card still
  missing a graphic with per-card progress, honest errors, tenant gating;
* the photo-coverage panel reports "N of M swimmers have a photo" with a
  per-missing-athlete add button;
* the per-card toolbar keeps Create graphic / Generate motion / Copy caption
  inline and folds the power features into one "More" overflow, with the
  caption actions docked under the tone panel;
* the export routes' stale "recognition page" copy now points at the builder.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _run_payload(profile_id: str, n: int = 3) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": f"swim-{i + 1}",
                    "rank": i + 1,
                    "priority": 0.9 - i * 0.1,
                    "achievement": {
                        "swim_id": f"swim-{i + 1}",
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "type": "pb",
                        "confidence_label": "high",
                        "time": "59.80",
                    },
                }
                for i in range(n)
            ]
        },
    }


@pytest.fixture
def app_env(app, web_module, tmp_path):
    # The media store is a module-level singleton; drop it so each test's
    # DATA_DIR gets a fresh DB instead of accumulating across tests.
    import mediahub.media_library.store as mls

    mls._default_store = None

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (web_module.RUNS_DIR / "r1.json").write_text(
        json.dumps(_run_payload("alpha")), encoding="utf-8"
    )
    return app, web_module, tmp_path


def _approve(tmp_path, *card_ids):
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(Path(tmp_path / "runs_v4"))
    for cid in card_ids:
        ws.set_status("r1", cid, CardStatus.APPROVED)


def _seed_visual(wm, card_id: str, brief_id: str) -> None:
    vdir = wm.RUNS_DIR / "r1" / "visuals" / brief_id
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "feed_portrait.png").write_bytes(PNG)
    (vdir / "visual.json").write_text(
        json.dumps(
            {
                "id": f"vis_{brief_id}",
                "content_item_id": card_id,
                "visual_ids": {f"vis_{brief_id}": "feed_portrait"},
                "layout_template": "story_card",
                "why_this_design": "seeded design",
                "sourced_asset_ids": [],
            }
        ),
        encoding="utf-8",
    )


def _poll(client, url, tries=80, delay=0.2):
    j = {}
    for _ in range(tries):
        j = client.get(url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


class TestRenderAllJob:
    def test_no_approved_cards_is_honest_400(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/render-all-job")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "no_approved_cards"

    def test_everything_rendered_reports_done_without_a_job(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/render-all-job")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "done" and body["total"] == 0
        assert "already have graphics" in body["message"]

    def test_job_renders_missing_cards_with_progress(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2", "swim-3")
        _seed_visual(wm, "swim-1", "cb_a")  # already rendered — must be skipped

        rendered_ids = []

        def _fake_create(item, brand_kit, **kw):
            rendered_ids.append(item["id"])
            out = wm.RUNS_DIR / "r1" / "visuals" / f"cb_{item['id']}"
            out.mkdir(parents=True, exist_ok=True)
            p = out / "feed_portrait.png"
            p.write_bytes(PNG)
            return {
                "visuals": [{"file_path": str(p), "sourced_asset_ids": []}],
                "brief": {"variation_signature": f"sig-{item['id']}"},
                "errors": [],
            }

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_v8_create_visual_for_item", _fake_create):
                resp = c.post("/api/runs/r1/render-all-job")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["total"] == 2  # only the missing two
                j = _poll(c, body["poll_url"])
        assert j["status"] == "done", j
        assert j["total"] == 2 and j["done"] == 2
        assert sorted(rendered_ids) == ["swim-2", "swim-3"]

    def test_per_card_failure_is_reported_not_hidden(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")

        def _fake_create(item, brand_kit, **kw):
            if item["id"] == "swim-2":
                raise RuntimeError("chromium exploded")
            out = wm.RUNS_DIR / "r1" / "visuals" / "cb_ok"
            out.mkdir(parents=True, exist_ok=True)
            p = out / "feed_portrait.png"
            p.write_bytes(PNG)
            return {"visuals": [{"file_path": str(p)}], "brief": {}, "errors": []}

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_v8_create_visual_for_item", _fake_create):
                resp = c.post("/api/runs/r1/render-all-job")
                j = _poll(c, resp.get_json()["poll_url"])
        assert j["status"] == "done"  # partial success is success
        assert "chromium exploded" in (j["errors"].get("swim-2") or "")

    def test_cross_tenant_is_404(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "beta"})
            assert c.post("/api/runs/r1/render-all-job").status_code == 404


class TestBuilderPageSurfaces:
    def _html(self, app, seed=True):
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/pack/r1")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_persisted_visual_prefills_panel_without_render(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")
        _seed_visual(wm, "swim-1", "cb_a")
        html = self._html(app)
        # The rendered card's panel is pre-filled server-side…
        assert "Already rendered" in html
        assert "seeded design" in html
        assert "/api/visual/vis_cb_a/png/feed_portrait" in html
        # …and the count annotation is honest.
        assert "1 of 2" in html

    def test_pack_preview_wall_and_export_gating(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")
        # Zero rendered: no wall, exports gated with plain copy.
        gated = 'href="/pack/r1/export.zip" aria-disabled="true"'
        html = self._html(app)
        assert "Pack preview" not in html
        assert "Nothing rendered yet" in html
        assert gated in html
        # One rendered: wall appears, partial-count note, gate lifted.
        _seed_visual(wm, "swim-1", "cb_a")
        html = self._html(app)
        assert "Pack preview" in html
        assert "1 of 2 approved cards have graphics" in html
        assert gated not in html

    def test_create_all_button_present(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        html = self._html(app)
        assert 'id="mh-renderall-go"' in html
        assert "/api/runs/r1/render-all-job" in html
        assert "Create all graphics" in html

    def test_photo_coverage_panel_lists_missing_athletes(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")
        # Give Swimmer 1 a linked library photo; Swimmer 2 has none.
        from mediahub.media_library.models import MediaAsset

        store = wm._v8_get_media_store()
        store.save(
            MediaAsset(
                id="",
                filename="a.jpg",
                path=str(tmp_path / "a.jpg"),
                type="athlete_action",
                profile_id="alpha",
                linked_athlete_names=["Swimmer 1"],
            )
        )
        html = self._html(app)
        assert "Photo coverage" in html
        assert "1 of 2" in html and "swimmers in" in html
        assert "+ Add photo of Swimmer" in html
        assert "mhCardPhotoUpload" in html

    def test_toolbar_primary_overflow_split(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        html = self._html(app)
        # Primary actions inline.
        assert "Create graphic" in html and "Generate motion" in html
        assert "Copy caption" in html
        # The power features live inside the More overflow…
        more = html.split('class="mh-card-more"', 1)[1].split("</details>", 1)[0]
        for label in ("Reformat", "Copilot", "Comments", "History", "Locks", "Share"):
            assert label in more, label
        # …and the per-card Elements (add-to-card) entry point lives there too,
        # scoped to this run + card so a placement lands on this card's brief.
        assert "Elements" in more
        assert "/elements?" in more and "card_id=swim-1" in more
        # …with the unresolved-comments badge on the More trigger.
        assert '<summary class="btn secondary"' in more
        assert 'class="comments-count"' in more.split("mh-card-more-menu")[0]
        # Caption actions dock under the tone panel.
        assert 'class="mh-caption-actions"' in html
        cap_dock = html.split('class="mh-caption-actions"', 1)[1].split("</div>", 2)[0]
        assert "Regenerate caption" in cap_dock
        # Handlers unchanged — same functions, new layout.
        assert "reformatToggle(this" in html and "commentsToggle(this" in html

    def test_thumbnails_feed_the_reel_composer(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        html = self._html(app)
        assert "/api/runs/r1/card/swim-1/thumb.png" in html


class TestExportCopyFixed:
    def test_zip_routes_point_at_the_builder_not_recognition(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            for url in ("/pack/r1/zip", "/pack/r1/export.zip"):
                resp = c.get(url)
                assert resp.status_code == 404  # nothing rendered yet
                html = resp.get_data(as_text=True)
                assert "recognition page" not in html
                assert "/pack/r1" in html
                assert "Content builder" in html
