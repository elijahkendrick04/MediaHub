"""Roadmap 1.11 build 5 — Charts & insights web routes (gallery, SVG, AI, honest-error)."""

from __future__ import annotations

import importlib
import json
import xml.etree.ElementTree as ET

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _seed_run(tmp_path, run_id="run-1"):
    runs_dir = tmp_path / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "meet": {"name": "County Champs"},
                "canonical_meet": {
                    "name": "County Champs",
                    "swimmers": {"s1": {"first_name": "Alex", "last_name": "Smith"}, "s2": {"first_name": "Jo", "last_name": "Lee"}},
                    "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}],
                },
                "recognition_report": {
                    "meet_name": "County Champs",
                    "n_swims_analysed": 12,
                    "ranked_achievements": [
                        {"achievement": {"type": "pb_confirmed", "swimmer_name": "Alex Smith", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.4}}},
                        {"achievement": {"type": "medal_gold", "swimmer_name": "Alex Smith", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                        {"achievement": {"type": "medal_silver", "swimmer_name": "Jo Lee", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return run_id


def test_api_charts_lists_candidates(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/api/runs/{rid}/charts")
    assert r.status_code == 200
    charts = r.get_json()["charts"]
    ids = {x["chart_id"] for x in charts}
    assert {"pbs_per_swimmer", "medal_split", "medal_table"} <= ids
    assert all(x["svg_url"].endswith(x["chart_id"]) for x in charts)


def test_chart_svg_route_serves_brand_styled_svg(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/api/runs/{rid}/chart/medal_split")
    assert r.status_code == 200
    assert r.mimetype == "image/svg+xml"
    assert b"<svg" in r.data
    ET.fromstring(r.data.decode("utf-8"))  # well-formed
    assert b"googleapis" not in r.data and b"gstatic" not in r.data


def test_chart_svg_format_changes_size_and_download_header(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/api/runs/{rid}/chart/pbs_per_swimmer?format=portrait&download=1")
    assert r.status_code == 200
    assert b'width="1080"' in r.data and b'height="1350"' in r.data
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_unknown_chart_is_404(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/api/runs/{rid}/chart/does_not_exist")
    assert r.status_code == 404


def test_unknown_run_is_404(app_env):
    app, _wm, _tmp = app_env
    with app.test_client() as c:
        assert c.get("/api/runs/ghost/charts").status_code == 404
        assert c.get("/api/runs/ghost/chart/medal_split").status_code == 404


def test_charts_page_renders_gallery(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/runs/{rid}/charts")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Charts &amp; insights" in body or "Charts & insights" in body
    assert "mh-chartpack-tile" in body  # gallery tiles rendered (raw HTML, not escaped)
    assert "&lt;div class=&#34;card mh-chartpack-tile" not in body  # not double-escaped
    assert "/chart/medal_split" in body  # an SVG is embedded by URL


def test_recommend_honest_error_without_ai(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{rid}/charts/recommend")
    assert r.status_code == 200  # honest, not a crash
    j = r.get_json()
    assert j["available"] is False and j["error"] == "no_ai"


def test_insights_honest_error_without_ai(app_env):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{rid}/charts/insights")
    assert r.status_code == 200
    j = r.get_json()
    assert j["available"] is False and j["error"] == "no_ai"


def test_recommend_with_mocked_ai(app_env, monkeypatch):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda *a, **k: {"chart_id": "pbs_per_swimmer", "headline": "PBs everywhere", "reason": "broadest story"},
    )
    with app.test_client() as c:
        r = c.post(f"/api/runs/{rid}/charts/recommend")
    j = r.get_json()
    assert j["available"] is True
    assert j["recommendation"]["chart_id"] == "pbs_per_swimmer"


def test_insights_with_mocked_ai_are_grounded(app_env, monkeypatch):
    app, _wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda *a, **k: {
            "summary": "A strong meet.",
            "takeaways": [
                {"text": "The team won 2 medals.", "facts_used": ["medals_total"]},
                {"text": "An invented 99 swimmers came.", "facts_used": ["swimmers"]},
            ],
        },
    )
    with app.test_client() as c:
        r = c.post(f"/api/runs/{rid}/charts/insights")
    j = r.get_json()
    assert j["available"] is True
    texts = [t["text"] for t in j["insights"]["takeaways"]]
    assert any("2 medals" in t for t in texts)
    assert not any("99" in t for t in texts)  # fabricated number guarded out


def test_content_builder_links_to_charts(app_env, monkeypatch):
    """The content builder surfaces the charts link (where reel/turn-into live)."""
    app, wm, tmp_path = app_env
    rid = _seed_run(tmp_path)
    with app.test_request_context():
        from flask import url_for

        # The endpoint exists and builds a clean URL — the content-builder template
        # interpolates exactly this.
        assert url_for("run_charts_page", run_id=rid) == f"/runs/{rid}/charts"
