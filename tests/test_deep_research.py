"""Tests for web_research.deep_research and verify (the bounded research loop).

Offline: ask_with_tools, WebResearcher.search and safe_fetch are all faked, so
no real LLM or network happens. Covers tool dispatch + source collection, the
'discard partial synthesis when incomplete' rule, the structural authority
annotation, the round-cap clamp, and honest provider errors.
"""
from __future__ import annotations

import pytest

from mediahub.ai_core.llm import ProviderNotConfigured, ToolCallRecord, ToolConversation
from mediahub.web_research import deep_research as dr
from mediahub.web_research import search as searchmod
from mediahub.web_research import verify
from mediahub.web_research.search import SearchResult


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        searchmod.WebResearcher,
        "search",
        lambda self, q, num=5: [
            SearchResult("https://swimmingresults.org/r", "PB page", "snippet", "searxng"),
            SearchResult("https://blog.test/x", "Blog", "snip", "duckduckgo"),
        ],
    )
    monkeypatch.setattr(
        "mediahub.web_research.deep_research.safe_fetch",
        lambda url, **k: "page text confirming the PB is 25.10",
    )
    for k in ("MEDIAHUB_RESEARCH_MAX_ROUNDS", "MEDIAHUB_RESEARCH_MAX_TOKENS",
              "MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS"):
        monkeypatch.delenv(k, raising=False)
    # Neutral learned-trust by default so authority comes only from the explicit
    # config a test sets.
    monkeypatch.setattr("mediahub.context_engine.trust.score_domain", lambda d: 0.5)
    yield


def _fake_loop(answer, *, drive_tools=True):
    def _aw(system, user, *, tools, on_tool_call, max_tokens, max_rounds, provider=None):
        calls = []
        if drive_tools:
            calls.append(
                ToolCallRecord("search", {"query": "swimmer pb"},
                               on_tool_call("search", {"query": "swimmer pb"}), "gemini")
            )
            calls.append(
                ToolCallRecord("fetch_url", {"url": "https://swimmingresults.org/r"},
                               on_tool_call("fetch_url", {"url": "https://swimmingresults.org/r"}),
                               "gemini")
            )
        return ToolConversation(text=answer, provider="gemini", tool_calls=calls)

    return _aw


def test_happy_path_complete(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS", "swimmingresults.org")
    monkeypatch.setattr(
        "mediahub.ai_core.llm.ask_with_tools",
        _fake_loop("The PB is 25.10s, confirmed via swimmingresults.org."),
    )
    res = dr.deep_research("what is the swimmer's pb")
    assert res.complete is True
    assert "25.10" in res.answer
    assert "https://swimmingresults.org/r" in res.sources
    assert "https://blog.test/x" in res.sources
    assert res.authority_sources == ["https://swimmingresults.org/r"]
    assert res.tool_calls == 2


def test_incomplete_is_discarded(monkeypatch):
    monkeypatch.setattr(
        "mediahub.ai_core.llm.ask_with_tools",
        _fake_loop("(the model is still gathering evidence; try a smaller question.)"),
    )
    res = dr.deep_research("hard question")
    assert res.complete is False
    assert res.answer == ""  # partial synthesis discarded, not returned
    assert res.sources  # but the sources it touched are still surfaced


def test_empty_question_makes_no_llm_call(monkeypatch):
    def _must_not(*a, **k):
        raise AssertionError("ask_with_tools must not be called for an empty question")

    monkeypatch.setattr("mediahub.ai_core.llm.ask_with_tools", _must_not)
    res = dr.deep_research("   ")
    assert res.complete is False
    assert res.answer == ""
    assert res.sources == []


def test_provider_not_configured_propagates(monkeypatch):
    def _raise(*a, **k):
        raise ProviderNotConfigured("no AI provider")

    monkeypatch.setattr("mediahub.ai_core.llm.ask_with_tools", _raise)
    with pytest.raises(ProviderNotConfigured):
        dr.deep_research("question")


def test_round_cap_is_clamped(monkeypatch):
    captured = {}

    def _aw(system, user, *, tools, on_tool_call, max_tokens, max_rounds, provider=None):
        captured["max_rounds"] = max_rounds
        return ToolConversation(text="done", provider="gemini", tool_calls=[])

    monkeypatch.setattr("mediahub.ai_core.llm.ask_with_tools", _aw)
    dr.deep_research("q", max_rounds=99)
    assert captured["max_rounds"] == 8  # clamped to the hard ceiling


# --- verify primitives ------------------------------------------------------

def test_is_authority_source_operator_configured(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS", "authority.test")
    monkeypatch.setattr("mediahub.context_engine.trust.score_domain", lambda d: 0.5)
    assert verify.is_authority_source("https://www.authority.test/x") is True
    assert verify.is_authority_source("https://authority.test") is True
    # subdomain-spoofing must NOT pass
    assert verify.is_authority_source("https://authority.test.attacker.test/x") is False
    assert verify.is_authority_source("https://random.test/x") is False
    assert verify.is_authority_source("") is False


def test_is_authority_source_learned_trust(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS", raising=False)
    monkeypatch.setattr("mediahub.context_engine.trust.score_domain", lambda d: 0.95)
    assert verify.is_authority_source("https://earned.test/x") is True
    monkeypatch.setattr("mediahub.context_engine.trust.score_domain", lambda d: 0.4)
    assert verify.is_authority_source("https://earned.test/x") is False


def test_configured_domains_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS", "alpha.test, beta.test")
    assert "alpha.test" in verify.configured_domains()
    assert "beta.test" in verify.configured_domains()
