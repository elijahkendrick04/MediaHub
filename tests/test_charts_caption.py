"""Roadmap 1.11 quality uplift (I5) — grounded, postable chart captions."""

from __future__ import annotations

import json

import pytest

from mediahub.charts.caption import generate_chart_caption
from mediahub.charts.models import Axis, ChartSpec, DataPoint, Series


def _spec():
    return ChartSpec(
        kind="bar",
        title="Personal bests",
        subtitle="County Champs",
        series=(
            Series(points=(DataPoint("Smith", 3, display="3"), DataPoint("Lee", 6, display="6"))),
        ),
        y_axis=Axis(value_format="integer"),
    )


def test_honest_error_without_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    with pytest.raises(_llm.ClaudeUnavailableError):
        generate_chart_caption(_spec())


def test_grounded_caption_passes(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    monkeypatch.setattr(_llm, "generate", lambda *a, **k: "Lee led with 6 PBs, Smith on 3.")
    out = generate_chart_caption(_spec())
    assert out["caption"] == "Lee led with 6 PBs, Smith on 3."
    assert out["provider"] == "gemini-api"


def test_fabricated_number_is_refused(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    monkeypatch.setattr(_llm, "generate", lambda *a, **k: "An amazing 42 swimmers set PBs!")
    with pytest.raises(_llm.ClaudeUnavailableError):
        generate_chart_caption(_spec())  # 42 is not in the chart → refused


def test_time_displays_are_allowed_numbers(monkeypatch):
    """A caption may cite a time the chart actually shows (e.g. 1:00.98)."""
    from mediahub.media_ai import llm as _llm

    spec = ChartSpec(
        kind="progression",
        title="Jess — 100m Free",
        series=(Series(points=(DataPoint("Jun", 6098, display="1:00.98"),)),),
        y_axis=Axis(value_format="time_cs", lower_is_better=True),
    )
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    monkeypatch.setattr(_llm, "generate", lambda *a, **k: "Jess clocked 1:00.98 in June.")
    out = generate_chart_caption(spec)
    assert "1:00.98" in out["caption"]


def test_empty_spec_returns_empty_without_calling_llm():
    # no provider configured and no data — must not raise, just nothing to say
    assert generate_chart_caption(ChartSpec(kind="bar"))["caption"] == ""


# --------------------------------------------------------------------------- #
# web route
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_env(app, tmp_path, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
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


def test_caption_route_honest_without_ai(app_env):
    with app_env.test_client() as c:
        r = c.post("/api/runs/r/chart/pbs_per_swimmer/caption")
    assert r.status_code == 200
    j = r.get_json()
    assert j["available"] is False and j["error"] == "no_ai"


def test_caption_route_with_mocked_ai(app_env, monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")
    # Grounded (no number the chart doesn't show) → passes the guard and is served.
    monkeypatch.setattr(
        _llm, "generate", lambda *a, **k: "A B led the personal-best charge at County."
    )
    with app_env.test_client() as c:
        r = c.post("/api/runs/r/chart/pbs_per_swimmer/caption")
    j = r.get_json()
    assert j["available"] is True and "personal-best" in j["caption"]


def test_caption_route_unknown_chart_404(app_env):
    with app_env.test_client() as c:
        r = c.post("/api/runs/r/chart/nope/caption")
    assert r.status_code == 404


def test_gallery_has_caption_button(app_env):
    with app_env.test_client() as c:
        body = c.get("/runs/r/charts").data.decode("utf-8")
    assert "mh-cap-btn" in body and "Caption" in body
