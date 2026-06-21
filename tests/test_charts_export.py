"""Roadmap 1.11 quality uplift (I2) — postable PNG export at social formats."""

from __future__ import annotations

import importlib
import json

import pytest

from mediahub.charts.export import EXPORT_FORMATS, chart_png_path
from mediahub.charts.models import Axis, ChartSpec, DataPoint, Series

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-secondary": "#2B6CB0",
    "--mh-surface": "#0B1B2E",
    "--mh-accent": "#F2C14E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.2)",
}


def _spec():
    return ChartSpec(
        kind="bar",
        title="Personal bests",
        series=(Series(points=(DataPoint("A", 3), DataPoint("B", 6, emphasis=True))),),
        y_axis=Axis(value_format="integer"),
        source_note="Source: meet results file",
    )


def _png_or_skip(spec, fmt, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    try:
        return chart_png_path(spec, fmt=fmt, role_vars=_RV)
    except Exception as e:  # noqa: BLE001
        if any(t in str(e).lower() for t in ("playwright", "chromium", "executable", "browser")):
            pytest.skip(f"PNG render needs Playwright/Chromium: {e}")
        raise


def test_export_formats_are_real_social_sizes():
    assert EXPORT_FORMATS["square"] == (1080, 1080)
    assert EXPORT_FORMATS["portrait"] == (1080, 1350)
    assert EXPORT_FORMATS["story"] == (1080, 1920)
    assert EXPORT_FORMATS["landscape"] == (1920, 1080)


def test_png_renders_at_each_format_and_caches(tmp_path, monkeypatch):
    from PIL import Image

    spec = _spec()
    for fmt, size in (("square", (1080, 1080)), ("portrait", (1080, 1350))):
        p = _png_or_skip(spec, fmt, tmp_path, monkeypatch)
        assert p.exists() and p.read_bytes()[:4] == b"\x89PNG"
        with Image.open(p) as im:
            assert im.size == size
        # content-addressed cache: a second call returns the same path
        assert chart_png_path(spec, fmt=fmt, role_vars=_RV) == p


def test_png_cache_key_separates_sizes(tmp_path, monkeypatch):
    spec = _spec()
    sq = _png_or_skip(spec, "square", tmp_path, monkeypatch)
    pt = chart_png_path(spec, fmt="portrait", role_vars=_RV)
    assert sq != pt  # different sizes → different cache files


# --------------------------------------------------------------------------- #
# web route
# --------------------------------------------------------------------------- #
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
    (tmp_path / "runs_v4" / "r.json").write_text(
        json.dumps(
            {
                "run_id": "r",
                "meet": {"name": "County"},
                "canonical_meet": {
                    "name": "County",
                    "swimmers": {"s1": {"first_name": "A", "last_name": "B"}, "s2": {}},
                    "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}],
                },
                "recognition_report": {
                    "meet_name": "County",
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "type": "pb_confirmed",
                                "swimmer_name": "A B",
                                "swimmer_id": "s1",
                                "event": "100 Free",
                                "swim_id": "a1",
                                "raw_facts": {"drop_seconds": 1.4},
                            }
                        },
                        {
                            "achievement": {
                                "type": "medal_gold",
                                "swimmer_name": "A B",
                                "swimmer_id": "s1",
                                "event": "100 Free",
                                "swim_id": "a1",
                            }
                        },
                    ],
                },
            }
        )
    )
    return app


def test_png_route_is_honest_png_or_503(app_env):
    """With Chromium present the route serves image/png; without it, an honest 503
    (never a broken or fake image)."""
    with app_env.test_client() as c:
        r = c.get("/api/runs/r/chart/pbs_per_swimmer?fmt=png&format=portrait")
    if r.status_code == 200:
        assert r.mimetype == "image/png"
        assert r.data[:4] == b"\x89PNG"
    else:
        assert r.status_code == 503
        assert r.get_json()["error"] == "png_unavailable"


def test_svg_route_still_default(app_env):
    with app_env.test_client() as c:
        r = c.get("/api/runs/r/chart/pbs_per_swimmer")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"


def test_gallery_offers_png_downloads(app_env):
    with app_env.test_client() as c:
        body = c.get("/runs/r/charts").data.decode("utf-8")
    assert "fmt=png&amp;format=portrait" in body or "fmt=png&format=portrait" in body
