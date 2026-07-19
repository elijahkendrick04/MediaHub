"""Regression tests for deep-review batch 11b (ai_core provider-call reliability).

#32 Provider failover fires on transport-level errors too — a ProviderError's
    explicit ``transient`` flag drives failover, not a regex over the message
    string (which never matched a ConnectionError, DNS failure, or 529).
#38 An empty provider response (candidates but no text / safety block) raises a
    transient ProviderError instead of silently returning "".
"""

from __future__ import annotations

import pytest

from mediahub.ai_core import llm


class _StatusErr(Exception):
    def __init__(self, status=None):
        self.status_code = status


def test_exc_transient_classification():
    assert llm._exc_transient(_StatusErr(None)) is True  # transport-level
    assert llm._exc_transient(_StatusErr(429)) is True
    assert llm._exc_transient(_StatusErr(503)) is True
    assert llm._exc_transient(_StatusErr(529)) is True  # Anthropic overload
    assert llm._exc_transient(_StatusErr(401)) is True  # another provider may hold a key
    assert llm._exc_transient(_StatusErr(400)) is False
    assert llm._exc_transient(_StatusErr(404)) is False


def _wire_chain(monkeypatch, gemini_fn, claude_fn):
    monkeypatch.setattr(
        llm, "_DISPATCH", {"gemini": (gemini_fn, None), "claude": (claude_fn, None)}
    )
    monkeypatch.setattr(llm, "_fallback_chain", lambda primary: ["gemini", "claude"])
    monkeypatch.setattr(llm, "active_provider", lambda: "gemini")


def test_transient_transport_error_fails_over(monkeypatch):
    calls = []

    def gemini(system, user, mt):
        calls.append("gemini")
        # A transport error carries no HTTP code in its text — the old regex
        # missed it; the transient flag now drives the failover.
        raise llm.ProviderError("Gemini HTTP error: Connection refused", transient=True)

    def claude(system, user, mt):
        calls.append("claude")
        return "answer from claude"

    _wire_chain(monkeypatch, gemini, claude)
    assert llm.ask("s", "u") == "answer from claude"
    assert calls == ["gemini", "claude"]


def test_permanent_error_does_not_fail_over(monkeypatch):
    calls = []

    def gemini(system, user, mt):
        calls.append("gemini")
        raise llm.ProviderError("Gemini HTTP 400: bad request", transient=False)

    def claude(system, user, mt):  # pragma: no cover - must NOT be reached
        calls.append("claude")
        return "should not happen"

    _wire_chain(monkeypatch, gemini, claude)
    with pytest.raises(llm.ProviderError):
        llm.ask("s", "u")
    assert calls == ["gemini"]  # a definite 400 is not retried elsewhere


def test_gemini_transport_error_is_marked_transient(monkeypatch):
    import requests

    monkeypatch.setattr(llm, "_key_for", lambda p: "test-key")

    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("connection reset")

    monkeypatch.setattr(requests, "post", _boom)
    with pytest.raises(llm.ProviderError) as ei:
        llm._ask_gemini("s", "u", 100)
    assert ei.value.transient is True


def test_gemini_empty_text_raises(monkeypatch):
    import requests

    monkeypatch.setattr(llm, "_key_for", lambda p: "test-key")

    class _Resp:
        status_code = 200

        def json(self):
            # Candidate present but no text parts (safety block / MAX_TOKENS).
            return {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    with pytest.raises(llm.ProviderError) as ei:
        llm._ask_gemini("s", "u", 100)
    assert ei.value.transient is True
    assert "no text" in str(ei.value).lower()
