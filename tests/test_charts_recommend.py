"""Roadmap 1.11 build 3 — chart recommender (picks from real candidates, no hallucinations)."""

from __future__ import annotations

import pytest

from mediahub.charts.aggregates import compute_aggregates
from mediahub.charts.recommend import recommend_chart
from mediahub.charts.series import build_chart_candidates


def _ctx():
    run = {
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {"s1": {}, "s2": {}},
            "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "n_swims_analysed": 12,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                {"achievement": {"type": "medal_silver", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
            ],
        },
    }
    return build_chart_candidates(run), compute_aggregates(run)


def test_honest_error_when_no_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    cands, agg = _ctx()
    with pytest.raises(_llm.ClaudeUnavailableError):
        recommend_chart(cands, agg)


def test_no_candidates_returns_none_without_calling_llm():
    from mediahub.charts.aggregates import MeetAggregates

    assert recommend_chart([], MeetAggregates()) is None


def test_picks_a_real_candidate_with_reason(monkeypatch):
    from mediahub.media_ai import llm as _llm

    cands, agg = _ctx()
    valid_id = cands[0].chart_id

    def fake_json(prompt, *, system, max_tokens, fallback):
        assert valid_id in prompt  # candidates are listed for the model
        return {
            "chart_id": valid_id,
            "headline": "A weekend of personal bests",
            "reason": "PBs are the broadest story across the squad.",
            "alternatives": [{"chart_id": "medal_split", "reason": "the medal haul also stands out"}],
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = recommend_chart(cands, agg)
    assert out["chart_id"] == valid_id
    assert out["headline"] == "A weekend of personal bests"
    assert out["reason"]
    assert out["provider"] == "gemini-api"


def test_hallucinated_choice_is_rejected(monkeypatch):
    from mediahub.media_ai import llm as _llm

    cands, agg = _ctx()

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {"chart_id": "rainbow_spiral_3d", "headline": "x", "reason": "y"}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)

    with pytest.raises(_llm.ClaudeUnavailableError):
        recommend_chart(cands, agg)


def test_alternatives_filtered_to_real_ids(monkeypatch):
    from mediahub.media_ai import llm as _llm

    cands, agg = _ctx()
    valid_id = cands[0].chart_id

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {
            "chart_id": valid_id,
            "headline": "h",
            "reason": "r",
            "alternatives": [
                {"chart_id": "made_up", "reason": "nope"},
                {"chart_id": cands[1].chart_id, "reason": "real alt"},
            ],
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = recommend_chart(cands, agg)
    alt_ids = {a["chart_id"] for a in out["alternatives"]}
    assert "made_up" not in alt_ids
    assert cands[1].chart_id in alt_ids
