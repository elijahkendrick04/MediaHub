"""Microsite engine (roadmap 1.16) — build 1: the deterministic fact base."""

from __future__ import annotations

from dataclasses import dataclass, field

from mediahub.sites.grounding import (
    SiteFacts,
    site_facts_with_performance,
    stats_from_doc_facts,
)


def test_allowed_numbers_from_stats_and_period():
    facts = SiteFacts(
        period="2025/2026 season",
        stats=[{"value": "42", "label": "Swims"}, {"value": "1,200", "label": "Members"}],
    )
    allowed = facts.allowed_numbers()
    assert 42.0 in allowed
    assert 1200.0 in allowed  # comma stripped
    assert 2025.0 in allowed and 2026.0 in allowed
    assert {1.0, 2.0, 3.0} <= allowed


def test_facts_block_lists_identity_and_numbers():
    facts = SiteFacts(
        club_name="Otters SC",
        location="Swansea",
        stats=[{"value": "42", "label": "Swims"}],
        event_name="County Champs",
    )
    block = facts.facts_block()
    assert "club: Otters SC" in block
    assert "location: Swansea" in block
    assert "Swims: 42" in block
    assert "event: County Champs" in block


def test_is_empty():
    assert SiteFacts(club_name="X").is_empty()
    assert not SiteFacts(stats=[{"value": "1", "label": "y"}]).is_empty()


@dataclass
class _DocFactsLike:
    headline_stats: list = field(default_factory=list)
    period: str = ""
    source_refs: list = field(default_factory=list)


def test_stats_from_doc_facts():
    df = _DocFactsLike(
        headline_stats=[
            {"value": 18, "label": "Swims"},
            {"value": 6, "label": "PBs", "sublabel": "30%"},
            {"bad": "no value"},
        ]
    )
    stats = stats_from_doc_facts(df)
    assert stats == [
        {"value": "18", "label": "Swims", "sublabel": ""},
        {"value": "6", "label": "PBs", "sublabel": "30%"},
    ]


def test_site_facts_with_performance_merges():
    facts = SiteFacts(club_name="Otters")
    df = _DocFactsLike(
        headline_stats=[{"value": 9, "label": "Medals"}],
        period="June 2026",
        source_refs=["run:r1"],
    )
    out = site_facts_with_performance(facts, df)
    assert out.stats == [{"value": "9", "label": "Medals", "sublabel": ""}]
    assert out.period == "June 2026"
    assert "run:r1" in out.source_refs
    # None doc_facts is a no-op
    assert site_facts_with_performance(SiteFacts(), None).stats == []
