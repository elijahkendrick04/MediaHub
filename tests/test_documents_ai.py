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
                {
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_name": "Tunde Adeyemi",
                        "swimmer_id": "s1",
                        "event": "100m Free",
                        "swim_id": "a1",
                        "raw_facts": {"drop_seconds": 1.42},
                    }
                },
                {
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_name": "Jess Smith",
                        "swimmer_id": "s2",
                        "event": "200m Free",
                        "swim_id": "a2",
                        "raw_facts": {"drop_seconds": 2.6},
                    }
                },
                {
                    "achievement": {
                        "type": "medal_gold",
                        "swimmer_name": "Tunde Adeyemi",
                        "swimmer_id": "s1",
                        "swim_id": "a1",
                    }
                },
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


def test_numbers_grounded_rejects_misstated_and_fabricated_numbers():
    """The sacred-numbers guard must reject a number that is not a fact — even
    one *close* to a fact (a misstated swim time) — while still allowing genuine
    rounding of a real fact. Regresses the old 0.6 window / int()==int() slop."""
    allowed = {1.0, 2.0, 3.0, 2.30, 5.0, 49.7, 2026.0}
    reject = [
        "took 2.8s off",  # misstates the real 2.30s drop (old 0.6 window let it pass)
        "2.9 medals",  # not 2 (old int()==int() let it pass)
        "5.5 golds",  # near 5 but not 5
        "the club won 99 medals",  # pure fabrication
    ]
    keep = [
        "took 2.30s off",  # exact fact
        "took 2.3s off",  # one-decimal rounding of 2.30
        "won 5 medals",  # exact integer fact
        "50% of swimmers",  # 49.7 rounded to a whole number
        "our 2 standout swimmers",  # small ordinal
        "a strong season for the club",  # no numbers at all
        "the 2026 season",  # period year
    ]
    for txt in reject:
        assert draft._numbers_grounded(txt, allowed) is False, txt
    for txt in keep:
        assert draft._numbers_grounded(txt, allowed) is True, txt


def test_misstated_swim_time_is_dropped_from_prose(monkeypatch):
    """End-to-end: a paragraph that misstates a real drop time is dropped."""
    from mediahub.media_ai import llm as _llm

    facts = _facts()

    # The real biggest drop in _run() is 2.6s (Jess Smith). A misstated 2.9s must
    # not survive; a grounded, number-free line must.
    def fake_json(prompt, *, system, max_tokens, fallback):
        return {
            "highlights": "The biggest drop of the day was a huge 2.9s.",  # misstated
            "intro": "A season the whole club can be proud of.",  # no number -> kept
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    prose = draft.draft_prose(facts, "season_report")
    assert "highlights" not in prose
    assert "intro" in prose
