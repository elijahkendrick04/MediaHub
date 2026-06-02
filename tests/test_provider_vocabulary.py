"""MEDIAHUB_LLM_PROVIDER means the same thing in both LLM stacks, and the two
stacks agree on the unset default Anthropic model.

Historically MEDIAHUB_LLM_PROVIDER=claude was honoured only by ai_core and
=anthropic only by media_ai, and the two disagreed on the unset default model
(claude-sonnet-4-5-* vs claude-sonnet-4-6). Both are reconciled here.
"""
from __future__ import annotations

from mediahub.ai_core import llm as ai_core_llm
from mediahub.media_ai import llm as media_ai_llm


def test_anthropic_alias_in_ai_core(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "anthropic")
    assert ai_core_llm._preferred_pref() == "claude"


def test_claude_value_in_ai_core(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "claude")
    assert ai_core_llm._preferred_pref() == "claude"


def test_anthropic_and_claude_equivalent_in_media_ai(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "anthropic")
    assert media_ai_llm._preferred_provider() == "anthropic"
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "claude")
    assert media_ai_llm._preferred_provider() == "anthropic"


def test_openai_recognized_in_both(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "openai")
    assert ai_core_llm._preferred_pref() == "openai"
    assert media_ai_llm._preferred_provider() == "openai"


def test_gemini_default_in_both(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LLM_PROVIDER", raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    # ai_core uses 'auto' (= first configured); media_ai names gemini outright.
    assert ai_core_llm._preferred_pref() == "auto"
    assert media_ai_llm._preferred_provider() == "gemini"


def test_fix_b_default_model_aligned(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LLM_MODEL", raising=False)
    assert ai_core_llm._anthropic_model() == "claude-sonnet-4-6"
    assert media_ai_llm.DEFAULT_MODEL == "claude-sonnet-4-6"
