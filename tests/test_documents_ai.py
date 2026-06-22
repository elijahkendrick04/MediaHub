"""Document engine (roadmap 1.15) — build 2: the grounded AI drafting flow."""

from __future__ import annotations

import pytest

from mediahub.documents import draft
from mediahub.documents.grounding import facts_from_run


def _run():
    return {
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {"s1": {}, "s2": {}, "s3": {}},
            "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}, {"swimmer_key": "s3"}],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "meet_date": "June 2026",
            "n_swims_analysed": 18,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2", "raw_facts": {"drop_seconds": 2.6}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "swim_id": "a1"}},
            ],
        },
    }


def _facts():
    return facts_from_run(_run(), club_name="Otters SC", run_id="r1")


def test_default_outline_keys():
    keys = [s["key"] for s in draft.default_outline("season_report")]
    assert keys == ["intro", "highlights", "outlook", "thanks"]
    assert draft.default_outline("nope") == []


def test_honest_error_when_no_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.draft_prose(_facts(), "season_report")
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.generate_document(_facts(), "season_report", with_ai=True)


def test_grounded_prose_is_kept(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        assert "ONLY" in system  # the no-invent rule is in the system prompt
        assert "personal_bests" in prompt  # grounded on the fact sheet
        return {
            "intro": "It was a strong season for the club.",
            "thanks": "Thank you to all our swimmers and volunteers.",
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)

    prose = draft.draft_prose(_facts(), "season_report")
    assert "intro" in prose and "thanks" in prose
    assert "strong season" in prose["intro"]


def test_ungrounded_number_is_dropped(monkeypatch):
    """The core guard: a paragraph stating a number we never provided is dropped."""
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {
            "intro": "The club won 99 medals this season.",  # 99 is NOT in the facts → dropped
            "thanks": "Thanks to our 2 standout swimmers.",  # 2 IS in the facts → kept
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)

    prose = draft.draft_prose(_facts(), "season_report")
    assert "intro" not in prose  # fabricated stat rejected
    assert "thanks" in prose  # grounded one kept


def test_generate_document_without_ai_needs_no_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    # Even with no provider, with_ai=False builds from data alone.
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    spec = draft.generate_document(_facts(), "season_report", with_ai=False)
    assert spec.doc_format == "season_report"
    assert spec.sections  # real structure + data, no narrative


def test_generate_document_with_ai_injects_prose(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm, "generate_json", lambda prompt, **kw: {"intro": "A great season for Otters SC."}
    )
    spec = draft.generate_document(_facts(), "season_report", with_ai=True)
    texts = [b.props.get("text", "") for s in spec.sections for b in s.blocks if b.kind == "text"]
    assert any("great season" in t.lower() for t in texts)
