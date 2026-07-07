"""M29 (UX-1) — see before approve: lazy cached card thumbnails.

The review page approves what will actually be posted, so each row carries a
thumbnail of the card's real graphic served by
``GET /api/runs/<run_id>/card/<card_id>/thumb.png``:

* an existing persisted render is served as-is (never re-rendered);
* a first render happens once (through the normal pipeline, deterministic
  seed, render-slot gated) and is cached in the per-run thumb manifest;
* a saturated render gate answers the standard 429 renderer-busy payload;
* cross-tenant requests 404 (house norm — no existence oracle).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _run_payload(profile_id: str, swim_ids: list[str]) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": s,
                    "rank": i + 1,
                    "priority": 0.9 - i * 0.1,
                    "quality_band": "elite",
                    "suggested_post_type": "story",
                    "factors": [],
                    "achievement": {
                        "swim_id": s,
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "type": "pb",
                        "confidence_label": "high",
                        "time": "59.80",
                    },
                }
                for i, s in enumerate(swim_ids)
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

    (wm.RUNS_DIR / "r1.json").write_text(
        json.dumps(_run_payload("alpha", ["swim-1", "swim-2"])), encoding="utf-8"
    )
    return app, wm, tmp_path


def _seed_visual(wm, run_id: str, card_id: str, *, brief_id: str = "cb_seed1") -> Path:
    vdir = wm.RUNS_DIR / run_id / "visuals" / brief_id
    vdir.mkdir(parents=True, exist_ok=True)
    png = vdir / "feed_portrait.png"
    png.write_bytes(PNG)
    (vdir / "visual.json").write_text(
        json.dumps(
            {
                "id": f"vis_{brief_id}",
                "content_item_id": card_id,
                "visual_ids": {f"vis_{brief_id}": "feed_portrait"},
                "layout_template": "story_card",
                "why_this_design": "seeded",
                "sourced_asset_ids": [],
            }
        ),
        encoding="utf-8",
    )
    return png


class TestThumbRoute:
    def test_existing_render_served_without_rendering(self, app_env):
        app, wm, _ = app_env
        _seed_visual(wm, "r1", "swim-1")
        boom = mock.MagicMock(side_effect=AssertionError("must not render"))
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_v8_create_visual_for_item", boom):
                resp = c.get("/api/runs/r1/card/swim-1/thumb.png")
        assert resp.status_code == 200
        assert "image/png" in (resp.headers.get("Content-Type") or "")
        assert resp.data == PNG
        boom.assert_not_called()

    def test_first_render_happens_once_then_cached(self, app_env, tmp_path):
        app, wm, _ = app_env
        out = tmp_path / "rendered.png"

        def _fake_create(item, brand_kit, **kw):
            out.write_bytes(PNG)
            return {"visuals": [{"file_path": str(out)}], "brief": {}, "errors": []}

        fake = mock.MagicMock(side_effect=_fake_create)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_v8_create_visual_for_item", fake):
                first = c.get("/api/runs/r1/card/swim-1/thumb.png")
                second = c.get("/api/runs/r1/card/swim-1/thumb.png")
        assert first.status_code == 200 and second.status_code == 200
        assert fake.call_count == 1  # the second hit is the manifest cache
        # The render is deterministic + non-AI-directed for a triage thumb.
        kwargs = fake.call_args.kwargs
        assert kwargs["formats"] == ["feed_portrait"]
        assert kwargs["use_ai_director"] is False
        # And the manifest records the path for later requests.
        manifest = json.loads((wm.RUNS_DIR / "r1" / "card_thumbs.json").read_text())
        assert manifest["swim-1"] == str(out)

    def test_cross_tenant_is_404(self, app_env):
        app, wm, _ = app_env
        _seed_visual(wm, "r1", "swim-1")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "beta"})
            resp = c.get("/api/runs/r1/card/swim-1/thumb.png")
        assert resp.status_code == 404

    def test_unknown_card_is_404(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/card/nope/thumb.png")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "card_not_found"

    def test_busy_render_gate_answers_429(self, app_env):
        app, wm, _ = app_env

        def _busy(*a, **kw):
            raise wm._RenderBusy("graphic")

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_render_slot", _busy):
                resp = c.get("/api/runs/r1/card/swim-1/thumb.png")
        assert resp.status_code == 429
        body = resp.get_json()
        assert body["error"] == "renderer_busy"
        assert resp.headers.get("Retry-After")

    def test_render_failure_is_honest_503(self, app_env):
        app, wm, _ = app_env
        fake = mock.MagicMock(return_value={"visuals": [], "errors": ["boom"]})
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(wm, "_v8_create_visual_for_item", fake):
                resp = c.get("/api/runs/r1/card/swim-1/thumb.png")
        assert resp.status_code == 503
        assert resp.get_json()["error"] == "no_thumbnail"


class TestReviewPageMarkup:
    def test_rows_carry_lazy_thumb_and_inspector_seed(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/review/r1")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # One lazy thumb per ranked card, pointing at the thumb route.
        assert html.count('class="mh-card-thumb"') == 2
        assert "/api/runs/r1/card/swim-1/thumb.png" in html
        # The IntersectionObserver loader ships with the page.
        assert "img.mh-card-thumb[data-thumb-src]" in html
        # The Inspect button seeds the drawer preview with the same URL.
        assert 'data-thumb-url="/api/runs/r1/card/swim-1/thumb.png"' in html
