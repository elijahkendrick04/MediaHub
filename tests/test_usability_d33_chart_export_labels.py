"""D-33 — chart exports need intent labels + a JS blob download, not raw JSON.

Each chart tile's PNG export was a plain anchor with a bare geometric glyph
("PNG ◫", "▣", "▮") whose meaning lived only in a hover tooltip; when PNG
rasterisation failed the anchor navigated the whole page onto a raw
`{"error":"png_unavailable"}` blob. The buttons are now labelled by intent
("Post 4:5", "Square 1:1", "Story 9:16", "Vector") and fetch via JS so a failure
renders inline with an SVG fallback.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, tmp_path


def _seed_run(tmp_path, run_id="run-1"):
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "meet": {"name": "County Champs"},
                "recognition_report": {
                    "meet_name": "County Champs",
                    "n_swims_analysed": 12,
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "type": "medal_gold",
                                "swimmer_name": "Alex Smith",
                                "swimmer_id": "s1",
                                "event": "100m Free",
                                "swim_id": "a1",
                            }
                        },
                        {
                            "achievement": {
                                "type": "medal_silver",
                                "swimmer_name": "Jo Lee",
                                "swimmer_id": "s2",
                                "event": "200m Free",
                                "swim_id": "a2",
                            }
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return run_id


def test_export_buttons_labelled_by_intent_not_glyphs(app_env):
    app, tmp = app_env
    rid = _seed_run(tmp)
    with app.test_client() as c:
        body = c.get(f"/runs/{rid}/charts").get_data(as_text=True)
    assert "Post 4:5" in body
    assert "Square 1:1" in body
    assert "Story 9:16" in body
    assert ">Vector<" in body
    # The old cryptic glyph labels are gone.
    assert "PNG ◫" not in body
    assert ">▣<" not in body and ">▮<" not in body


def test_png_exports_are_js_fetched_with_svg_fallback(app_env):
    app, tmp = app_env
    rid = _seed_run(tmp)
    with app.test_client() as c:
        body = c.get(f"/runs/{rid}/charts").get_data(as_text=True)
    # PNG exports are buttons carrying the fetch URL + an SVG fallback (not bare
    # anchors that navigate onto a JSON error).
    assert "mh-chart-dl" in body
    assert "data-dl-url=" in body
    assert "data-svg-fallback=" in body
    assert "mh-chart-export-msg" in body


def test_charts_js_downloads_blob_and_falls_back():
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert "closest('.mh-chart-dl')" in src
    assert "URL.createObjectURL(blob)" in src
    assert "Download the vector (SVG) instead" in src
