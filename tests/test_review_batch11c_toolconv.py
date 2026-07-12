"""Regression tests for deep-review batch 11c (tool-conversation semantics).

#37 ask_with_tools does NOT fail over to another provider once a tool call has
    already run — otherwise the tool's side effects would replay on the restart.
#39 The round-cap sentinel sets ToolConversation.exhausted (asserted via
    deep_research in test_deep_research.py); here we assert the flag directly.
"""

from __future__ import annotations

import pytest

from mediahub.ai_core import llm


def test_no_failover_after_a_tool_call_ran(monkeypatch):
    side_effects = []

    def gemini_tools(system, user, tools, on_tool_call, max_tokens, max_rounds):
        # Run one tool call (a lasting side effect) THEN fail transiently.
        on_tool_call("apply", {"op": "x"})
        raise llm.ProviderError("Gemini HTTP 503: overloaded", transient=True)

    def claude_tools(system, user, tools, on_tool_call, max_tokens, max_rounds):  # pragma: no cover
        raise AssertionError("must not fail over after a tool call has run")

    monkeypatch.setattr(
        llm, "_DISPATCH", {"gemini": (None, gemini_tools), "claude": (None, claude_tools)}
    )
    monkeypatch.setattr(llm, "_fallback_chain", lambda primary: ["gemini", "claude"])
    monkeypatch.setattr(llm, "active_provider", lambda: "gemini")

    def on_tool(name, inp):
        side_effects.append((name, inp))
        return "done"

    with pytest.raises(llm.ProviderError):
        llm.ask_with_tools("s", "u", tools=[], on_tool_call=on_tool)
    # The side effect ran exactly once — no replay on a second provider.
    assert side_effects == [("apply", {"op": "x"})]


def test_no_tool_call_still_fails_over(monkeypatch):
    # Symmetry: if the FIRST request fails before any tool runs, failover is fine.
    def gemini_tools(system, user, tools, on_tool_call, max_tokens, max_rounds):
        raise llm.ProviderError("Gemini HTTP error: connection refused", transient=True)

    def claude_tools(system, user, tools, on_tool_call, max_tokens, max_rounds):
        return llm.ToolConversation(text="ok from claude", provider="claude")

    monkeypatch.setattr(
        llm, "_DISPATCH", {"gemini": (None, gemini_tools), "claude": (None, claude_tools)}
    )
    monkeypatch.setattr(llm, "_fallback_chain", lambda primary: ["gemini", "claude"])
    monkeypatch.setattr(llm, "active_provider", lambda: "gemini")

    convo = llm.ask_with_tools("s", "u", tools=[], on_tool_call=lambda n, i: "x")
    assert convo.text == "ok from claude"


def test_toolconversation_exhausted_default_false():
    assert llm.ToolConversation(text="hi").exhausted is False
