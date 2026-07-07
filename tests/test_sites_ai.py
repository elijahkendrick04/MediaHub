"""Microsite engine (roadmap 1.16) — build 1: the grounded AI copy flow."""

from __future__ import annotations

import pytest

from mediahub.sites import draft
from mediahub.sites.grounding import SiteFacts


def _facts():
    return SiteFacts(
        club_name="Otters SC",
        location="Swansea",
        period="June 2026",
        stats=[{"value": "42", "label": "Swims"}, {"value": "6", "label": "PBs"}],
    )


def test_default_outline_keys():
    assert [s["key"] for s in draft.default_outline("club_home")] == ["about"]
    assert draft.default_outline("nonsense") == []


def test_honest_error_without_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.draft_copy(_facts(), "club_home")
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.suggest_seo_description(_facts())
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.suggest_alt_text("a swimmer")
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.generate_site(_facts(), "club_home", with_ai=True)


def test_grounded_copy_kept(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        assert "ONLY" in system
        assert "Swims: 42" in prompt  # grounded on the fact sheet
        return {"about": "Otters SC is a friendly Swansea club."}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    out = draft.draft_copy(_facts(), "club_home")
    assert "about" in out and "Swansea" in out["about"]


def test_ungrounded_number_dropped(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_json(prompt, *, system, max_tokens, fallback):
        return {"about": "We have 9999 members."}  # 9999 not on the fact sheet

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_json)
    assert draft.draft_copy(_facts(), "club_home") == {}  # dropped


def test_unparseable_ai_copy_is_an_honest_error(monkeypatch):
    """A provider that answers but yields no parseable JSON must raise, not
    silently return empty sections that look like a successful draft."""
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", lambda *a, **k: k.get("fallback", {}))
    with pytest.raises(_llm.ClaudeUnavailableError):
        draft.draft_copy(_facts(), "club_home")


def test_seo_and_alt_text(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda prompt, **kw: {
            "description": "Otters SC — Swansea's club.",
            "alt": "A swimmer mid-stroke",
        },
    )
    assert "Otters" in draft.suggest_seo_description(_facts())
    assert draft.suggest_alt_text("swimmer") == "A swimmer mid-stroke"


def test_generate_site_without_ai_needs_no_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    spec = draft.generate_site(_facts(), "club_home", with_ai=False)
    assert spec.archetype == "club_home" and spec.pages


def test_generate_site_with_ai_injects_copy(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm, "generate_json", lambda prompt, **kw: {"about": "A community club for everyone."}
    )
    spec = draft.generate_site(_facts(), "club_home", with_ai=True)
    texts = [
        b.props.get("text", "")
        for p in spec.pages
        for s in p.sections
        for b in s.blocks
        if b.kind == "text"
    ]
    assert any("community club" in t for t in texts)
