"""P6.1 — web surface for the format catalogue + reformat transformer.

Exercises ``/api/formats`` (the catalogue JSON) and
``/api/runs/<run_id>/card/<card_id>/reformat`` (the per-card transformer) via
the Flask test client. The actual PNG render needs Playwright/Chromium, so the
render success path mocks ``render_brief`` and asserts the route assembled the
right transformed brief + served it; every non-render path (auth, validation,
no-design) is exercised for real.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from mediahub.club_platform import format_catalog as fc
from mediahub.creative_brief.generator import CreativeBrief


@pytest.fixture
def app_env(tmp_path, monkeypatch):
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
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _seed_run(tmp_path: Path, run_id: str = "runF") -> str:
    run_dir = tmp_path / "runs_v4" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "recognition_report": {
                    "ranked_achievements": [
                        {"id": "c1", "achievement": {"swim_id": "c1", "swimmer_name": "Alice Lee",
                                                     "event": "100 Free", "headline": "New PB"}},
                    ]
                }
            }
        )
    )
    return run_id


def _seed_brief(tmp_path: Path, run_id: str, card_id: str = "c1", layout="split_diagonal_hero"):
    bdir = tmp_path / "runs_v4" / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    brief = CreativeBrief(
        id="cb_seed1",
        content_item_id=card_id,
        profile_id="p1",
        achievement_summary="New PB",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template=layout,
        inspiration_pattern_id="x",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="b",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="because",
        text_layers={"athlete_full_name": "Alice Lee"},
        palette={"primary": "#A30D2D", "secondary": "#000000", "accent": "#FFFFFF"},
        format_priority=["story"],
    )
    (bdir / f"{brief.id}.json").write_text(json.dumps(brief.to_dict(), default=str))
    return brief


# ---------------------------------------------------------------------------
# /api/formats
# ---------------------------------------------------------------------------


def test_formats_catalog_json(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        r = c.get("/api/formats")
    assert r.status_code == 200
    body = r.get_json()
    assert body["n"] == len(fc.all_formats())
    cats = [g["category"] for g in body["groups"]]
    assert "social_size" in cats
    # every group carries a human label + at least one format with a size
    for g in body["groups"]:
        assert g["label"]
        for f in g["formats"]:
            assert f["width"] > 0 and f["height"] > 0 and f["slug"]


def test_formats_catalog_sport_filter(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        r = c.get("/api/formats?sport=swimming")
    assert r.status_code == 200
    assert r.get_json()["sport"] == "swimming"


# ---------------------------------------------------------------------------
# reformat — validation / auth / no-design paths (no render needed)
# ---------------------------------------------------------------------------


def test_reformat_unknown_run_404(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        r = c.post("/api/runs/nope/card/c1/reformat?format=ig_story", json={})
    assert r.status_code == 404


def test_reformat_missing_format_400(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/reformat", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "unknown_format"


def test_reformat_unknown_format_400(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=not_a_format", json={})
    assert r.status_code == 400


def test_reformat_bad_custom_size_400(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/reformat?w=50&h=50", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "bad_format"


def test_reformat_no_brief_409(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)  # no brief seeded
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=ig_story", json={})
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_design"


# ---------------------------------------------------------------------------
# reformat — render success path (render_brief mocked)
# ---------------------------------------------------------------------------


def _fake_render_brief_factory():
    """A render_brief stub that writes a 1×1 PNG and records the brief it got."""
    captured = {}
    # Smallest valid PNG (1×1 transparent).
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )

    captured["calls"] = 0

    def _fake(brief, *, output_dir, size, format_name, **kw):
        captured["calls"] += 1
        captured["brief"] = brief
        captured["size"] = size
        captured["format_name"] = format_name
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"{format_name}.png"
        png.write_bytes(png_bytes)
        visual = SimpleNamespace(file_path=str(png), id="v1", format_name=format_name)
        return SimpleNamespace(visual=visual)

    return _fake, captured


def test_reformat_transforms_and_serves_png(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id, "c1", layout="split_diagonal_hero")

    fake, captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake):
        with app.test_client() as c:
            r = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=youtube_thumbnail", json={})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["Content-Type"] == "image/png"
    # The route rendered at the format's canvas size and re-laid-out the brief.
    assert captured["size"] == fc.format_for("youtube_thumbnail").size
    assert captured["brief"].layout_template in fc.preferred_archetypes(
        fc.format_for("youtube_thumbnail")
    )
    # source design was split_diagonal_hero (tall) → must have re-laid-out for 16:9
    assert captured["brief"].layout_template != "split_diagonal_hero"


def test_reformat_blank_start_serves_png(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)  # no brief — blank start seeds from brand tokens

    fake, captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake):
        with app.test_client() as c:
            r = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=poster&blank=1", json={})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["Content-Type"] == "image/png"
    assert captured["size"] == fc.format_for("poster").size


def test_reformat_custom_size_serves_png(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id, "c1")

    fake, captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake):
        with app.test_client() as c:
            r = c.post(f"/api/runs/{run_id}/card/c1/reformat?w=1200&h=1500&unit=px", json={})

    assert r.status_code == 200, r.get_data(as_text=True)
    assert captured["size"] == (1200, 1500)


def test_reformat_caches_deterministic_render(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id, "c1")

    fake, captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake):
        with app.test_client() as c:
            r1 = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=ig_square", json={})
            assert r1.status_code == 200
            assert captured["calls"] == 1
            r2 = c.post(f"/api/runs/{run_id}/card/c1/reformat?format=ig_square", json={})
            assert r2.status_code == 200
    # Second identical request is served from the on-disk cache (no re-render).
    assert captured["calls"] == 1


def test_reformat_cache_invalidates_on_brief_edit(app_env):
    """The cache key folds the SOURCE brief's content: an edit that keeps the
    layout template (copilot/headline change persisting a new brief) must
    re-render, never serve the stale pre-edit PNG."""
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id, "c1")

    fake, captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake):
        with app.test_client() as c:
            assert c.post(f"/api/runs/{run_id}/card/c1/reformat?format=ig_square", json={}).status_code == 200
            assert captured["calls"] == 1
            # A later brief version for the same card, same layout, new copy —
            # exactly what a copilot edit persists.
            import os as _os
            import time as _time

            bdir = tmp_path / "runs_v4" / run_id / "briefs"
            bdict = json.loads((bdir / "cb_seed1.json").read_text())
            bdict["id"] = "cb_seed2"
            bdict["primary_hook"] = "CLUB RECORD"
            p2 = bdir / "cb_seed2.json"
            p2.write_text(json.dumps(bdict, default=str))
            # make the new brief unambiguously the most recent
            now = _time.time()
            _os.utime(p2, (now + 5, now + 5))
            assert c.post(f"/api/runs/{run_id}/card/c1/reformat?format=ig_square", json={}).status_code == 200
    # The edited design re-rendered instead of serving the pre-edit cache.
    assert captured["calls"] == 2
