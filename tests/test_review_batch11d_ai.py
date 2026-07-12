"""Regression tests for deep-review batch 11d (AI-wrapper honesty + observability).

#35 media_ai.generate raises an HONEST error on all-provider failure — "attempted
    … / failed", not a false "not configured" — matching generate_vision.
#36 ai_core.ask / ask_with_tools record every provider call to observability so
    copilot / chat / research calls are visible on /healthz/usage and count
    against the Gemini free-tier RPD tracker.
"""

from __future__ import annotations

import pytest


# ── #35 honest error vs "not configured" ────────────────────────────────────


def test_generate_reports_attempt_failure_not_misconfiguration(monkeypatch):
    from mediahub.media_ai import llm

    monkeypatch.setattr(llm, "_provider_order", lambda: ["gemini"])
    monkeypatch.setattr(llm, "_has_gemini_key", lambda: True)
    monkeypatch.setattr(llm, "_call_gemini", lambda *a, **k: None)  # call made, no output
    with pytest.raises(llm.ClaudeUnavailableError) as ei:
        llm.generate("hi")
    msg = str(ei.value).lower()
    assert "attempted" in msg or "failed" in msg
    assert "not configured" not in msg  # would be a false reason


def test_generate_reports_not_configured_when_no_keys(monkeypatch):
    from mediahub.media_ai import llm

    monkeypatch.setattr(llm, "_provider_order", lambda: ["gemini", "anthropic"])
    monkeypatch.setattr(llm, "_has_gemini_key", lambda: False)
    monkeypatch.setattr(llm, "_has_anthropic_key", lambda: False)
    monkeypatch.setattr(llm, "_is_openai_on", lambda: False)
    with pytest.raises(llm.ClaudeUnavailableError) as ei:
        llm.generate("hi")
    assert "not configured" in str(ei.value).lower()


# ── #36 ai_core records usage ───────────────────────────────────────────────


def _wire_single(monkeypatch, ask_fn):
    from mediahub.ai_core import llm

    monkeypatch.setattr(llm, "_DISPATCH", {"gemini": (ask_fn, None)})
    monkeypatch.setattr(llm, "_fallback_chain", lambda primary: ["gemini"])
    monkeypatch.setattr(llm, "active_provider", lambda: "gemini")
    return llm


def test_ask_records_successful_call(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "mediahub.observability.llm_usage.record_call", lambda **kw: recorded.append(kw)
    )
    llm = _wire_single(monkeypatch, lambda s, u, mt: "hello")
    assert llm.ask("s", "u") == "hello"
    assert len(recorded) == 1
    assert recorded[0]["provider"] == "gemini"
    assert recorded[0]["ok"] is True


def test_ask_records_failed_call(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "mediahub.observability.llm_usage.record_call", lambda **kw: recorded.append(kw)
    )
    from mediahub.ai_core import llm as _llm

    def _boom(s, u, mt):
        raise _llm.ProviderError("Gemini HTTP 400: bad request", transient=False)

    llm = _wire_single(monkeypatch, _boom)
    with pytest.raises(llm.ProviderError):
        llm.ask("s", "u")
    assert recorded and recorded[0]["ok"] is False
    assert recorded[0]["provider"] == "gemini"


def test_usage_recording_failure_never_sinks_the_call(monkeypatch):
    # A broken usage store must not break the LLM call.
    def _explode(**kw):
        raise RuntimeError("usage DB down")

    monkeypatch.setattr("mediahub.observability.llm_usage.record_call", _explode)
    llm = _wire_single(monkeypatch, lambda s, u, mt: "still works")
    assert llm.ask("s", "u") == "still works"
