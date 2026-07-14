"""Regression test for the Gemini thinking-budget fix.

Gemini 2.5 Flash ships with internal "thinking" enabled by default.
Those tokens count against ``maxOutputTokens`` but never appear in
the visible response, so every JSON-output caller in MediaHub
(palette resolver, block detector, content extractor, voice
imitation, …) silently truncated mid-key when a real key was first
configured in production.

The fix sets ``thinkingConfig.thinkingBudget = 0`` on every Gemini
generateContent call. Since the finding-#43 convergence the config
builder lives once in ``ai_core.gemini_transport`` and both LLM
wrappers use it; these tests pin the builder's rules and then pin the
payload each wrapper actually posts, so a future refactor of the
request path can't re-introduce the regression on either side.
"""
from __future__ import annotations

import pytest

from mediahub.ai_core import gemini_transport


# ---------------------------------------------------------------------------
# gemini_transport.generation_config — the single shared builder
# ---------------------------------------------------------------------------

def test_generation_config_disables_thinking_by_default(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("MEDIAHUB_GEMINI_THINKING_BUDGET", raising=False)
    cfg = gemini_transport.generation_config(600)
    assert cfg["maxOutputTokens"] == 600
    assert cfg["thinkingConfig"] == {"thinkingBudget": 0}


def test_generation_config_sends_no_temperature(monkeypatch):
    """Finding #43 parity: ai_core used to send temperature=0.7 while
    media_ai sent none — the shared builder sends none, so both wrappers
    sample at the API default."""
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
    cfg = gemini_transport.generation_config(600)
    assert "temperature" not in cfg


def test_generation_config_honours_env_override(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("MEDIAHUB_GEMINI_THINKING_BUDGET", "1024")
    cfg = gemini_transport.generation_config(600)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 1024}


def test_generation_config_clamps_pro_to_minimum(monkeypatch):
    """Gemini 2.5 Pro cannot disable thinking — the API rejects
    thinkingBudget below 128 with 400 INVALID_ARGUMENT — so a Pro
    override must clamp to the minimum instead of breaking every call."""
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.delenv("MEDIAHUB_GEMINI_THINKING_BUDGET", raising=False)
    cfg = gemini_transport.generation_config(600)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 128}


def test_generation_config_pro_keeps_larger_budget(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("MEDIAHUB_GEMINI_THINKING_BUDGET", "1024")
    cfg = gemini_transport.generation_config(600)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 1024}


def test_generation_config_skips_thinking_on_older_models(monkeypatch):
    """``thinkingConfig`` is a 2.5+ field — older models reject the
    payload as an unknown field. Gate on the model name."""
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-1.5-flash")
    cfg = gemini_transport.generation_config(600)
    assert "thinkingConfig" not in cfg


def test_generation_config_explicit_model_param_wins(monkeypatch):
    """Callers may pass the model explicitly (media_ai resolves it once
    per call); the env must not override an explicit argument."""
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-1.5-flash")
    cfg = gemini_transport.generation_config(600, model="gemini-2.5-flash")
    assert cfg["thinkingConfig"] == {"thinkingBudget": 0}


# ---------------------------------------------------------------------------
# End-to-end at the requests boundary — both wrappers must post the
# thinkingConfig the shared builder produced.
# ---------------------------------------------------------------------------

def test_media_ai_call_gemini_sends_thinking_budget(monkeypatch):
    from mediahub.media_ai import llm as media_ai_llm

    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("MEDIAHUB_GEMINI_THINKING_BUDGET", raising=False)
    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: "TEST")
    # Ensure the circuit breaker doesn't short-circuit the request.
    gemini_transport.breaker_record_success()

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        ok = True

        def json(self):
            return {
                "candidates": [{
                    "content": {"parts": [{"text": '{"primary":"#000000"}'}]}
                }],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            }

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResp()

    import requests as _requests
    monkeypatch.setattr(_requests, "post", fake_post)

    out = media_ai_llm._call_gemini(
        [{"role": "user", "content": "hi"}],
        system="sys",
        max_tokens=600,
    )
    assert out == '{"primary":"#000000"}'
    cfg = captured["payload"]["generationConfig"]
    assert cfg["maxOutputTokens"] == 600
    assert cfg["thinkingConfig"]["thinkingBudget"] == 0


def test_ai_core_ask_gemini_sends_thinking_budget(monkeypatch):
    from mediahub.ai_core import llm as ai_core_llm

    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("MEDIAHUB_GEMINI_THINKING_BUDGET", raising=False)
    monkeypatch.setattr(ai_core_llm, "_key_for", lambda _name: "TEST")

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "candidates": [{
                    "content": {"parts": [{"text": "ok"}]}
                }],
            }

    def fake_post(url, params=None, json=None, **kwargs):
        captured["payload"] = json
        return _FakeResp()

    import requests as _requests
    monkeypatch.setattr(_requests, "post", fake_post)

    out = ai_core_llm._ask_gemini("sys", "user", 600)
    assert out == "ok"
    cfg = captured["payload"]["generationConfig"]
    assert cfg["maxOutputTokens"] == 600
    assert cfg["thinkingConfig"]["thinkingBudget"] == 0
