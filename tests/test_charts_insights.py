"""Roadmap 1.11 build 3 — grounded, source-linked insights (LLM phrases, never computes)."""

from __future__ import annotations

import pytest

from mediahub.charts.aggregates import compute_aggregates
from mediahub.charts.insights import generate_insights


def _agg():
    run = {
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {"s1": {}, "s2": {}, "s3": {}},
            "results": [
                {"swimmer_key": "s1"}, {"swimmer_key": "s2"}, {"swimmer_key": "s3"},
            ],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "n_swims_analysed": 18,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2", "raw_facts": {"drop_seconds": 2.6}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                {"achievement": {"type": "medal_silver", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
            ],
        },
    }
    return compute_aggregates(run)


def test_honest_error_when_no_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    with pytest.raises(_llm.ClaudeUnavailableError):
        generate_insights(_agg())


def test_grounded_takeaways_carry_sources(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        # Sanity: the fact sheet and the rule are in the prompt/system.
        assert "personal_bests" in prompt
        assert "ONLY" in system
        return {
            "summary": "2 swimmers set personal bests at County Champs.",
            "takeaways": [
                {"text": "2 of 3 swimmers set a personal best.", "facts_used": ["swimmers_with_pb", "swimmers"]},
                {"text": "The team brought home 2 medals.", "facts_used": ["medals_total"]},
            ],
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = generate_insights(_agg())
    assert out["provider"] == "gemini-api"
    assert len(out["takeaways"]) == 2
    # the medals takeaway cites the medal source rows (explainability)
    medal_t = [t for t in out["takeaways"] if "medal" in t["text"].lower()][0]
    assert set(medal_t["sources"]) == {"a1", "a2"}


def test_fabricated_number_is_dropped(monkeypatch):
    """The core guard: a takeaway with a number we never provided is rejected."""
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {
            "summary": "",
            "takeaways": [
                {"text": "2 swimmers set personal bests.", "facts_used": ["swimmers_with_pb"]},
                {"text": "A club-record 47 swimmers competed.", "facts_used": ["swimmers"]},  # 47 is invented
            ],
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = generate_insights(_agg())
    texts = [t["text"] for t in out["takeaways"]]
    assert any("2 swimmers" in t for t in texts)
    assert not any("47" in t for t in texts)  # the fabricated stat was dropped


def test_rounded_percent_is_allowed(monkeypatch):
    from mediahub.media_ai import llm as _llm

    # pb_conversion_percent is 66.7; "67%" is a fair rounding and must pass.
    def fake_json(prompt, *, system, max_tokens, fallback):
        return {"summary": "", "takeaways": [{"text": "67% of swimmers set a PB.", "facts_used": ["pb_conversion_percent"]}]}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = generate_insights(_agg())
    assert len(out["takeaways"]) == 1


def test_unknown_fact_key_dropped_but_takeaway_kept(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {"summary": "", "takeaways": [{"text": "2 medals won.", "facts_used": ["medals_total", "made_up_key"]}]}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    monkeypatch.setattr(_llm, "active_provider", lambda: "gemini-api")

    out = generate_insights(_agg())
    assert out["takeaways"][0]["facts_used"] == ["medals_total"]  # bogus key filtered


def test_empty_aggregates_returns_no_takeaways_without_calling_llm(monkeypatch):
    from mediahub.charts.aggregates import MeetAggregates

    # Should not raise even with no provider — there's simply nothing to say.
    out = generate_insights(MeetAggregates())
    assert out["takeaways"] == [] and out["summary"] == ""
