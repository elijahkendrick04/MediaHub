"""End-to-end wiring: the openai provider plugs into BOTH LLM stacks, stays
inert when unconfigured, and honours failover + premium escalation.

Offline — requests.post is faked. The fixture configures a single endpoint and
prefers openai so the provider is first in both chains; individual tests add
gemini/anthropic or premium models as needed.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.ai_core import llm as ai_core_llm
from mediahub.media_ai import llm as media_ai_llm


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or ""

    def json(self):
        return self._payload


def _chat(text, model="m"):
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }


@pytest.fixture
def openai_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "https://host/v1")
    monkeypatch.setenv("MEDIAHUB_LLM_MODEL_CHEAP", "cheap-m")
    monkeypatch.setenv("MEDIAHUB_LLM_API_KEY", "test-key")
    monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "openai")
    # Make gemini/anthropic look unconfigured unless a test says otherwise.
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    return monkeypatch


def test_media_ai_generate_routes_through_openai(openai_env):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["url"] = url
        captured["model"] = json["model"]
        return _FakeResp(200, _chat("openai says hi"))

    openai_env.setattr(requests, "post", fake_post)
    out = media_ai_llm.generate("hello", system="sys")
    assert out == "openai says hi"
    assert captured["url"] == "https://host/v1/chat/completions"
    assert captured["model"] == "cheap-m"


def test_generate_content_type_routes_hero_to_premium(openai_env):
    """generate(content_type='caption') must reach select_model — hero
    surfaces earn the premium model when one is configured."""
    openai_env.setenv("MEDIAHUB_LLM_MODEL_PREMIUM", "prem-m")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["model"] = json["model"]
        return _FakeResp(200, _chat("hero copy", model=json["model"]))

    openai_env.setattr(requests, "post", fake_post)
    out = media_ai_llm.generate("write the caption", content_type="caption")
    assert out == "hero copy"
    assert captured["model"] == "prem-m"


def test_generate_content_type_honours_override(openai_env):
    openai_env.setenv("MEDIAHUB_LLM_MODEL_OVERRIDES", "caption=special-m")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["model"] = json["model"]
        return _FakeResp(200, _chat("hero copy", model=json["model"]))

    openai_env.setattr(requests, "post", fake_post)
    media_ai_llm.generate("write the caption", content_type="caption")
    assert captured["model"] == "special-m"


def test_generate_json_threads_content_type(openai_env):
    openai_env.setenv("MEDIAHUB_LLM_MODEL_PREMIUM", "prem-m")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["model"] = json["model"]
        return _FakeResp(200, _chat('{"k": "v"}'))

    openai_env.setattr(requests, "post", fake_post)
    assert media_ai_llm.generate_json("json please", content_type="brand_voice") == {"k": "v"}
    assert captured["model"] == "prem-m"


def test_media_ai_generate_json_through_openai(openai_env):
    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(200, _chat('{"k": "v"}'))

    openai_env.setattr(requests, "post", fake_post)
    assert media_ai_llm.generate_json("give me json") == {"k": "v"}


def test_ai_core_ask_through_openai(openai_env):
    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(200, _chat("core answer"))

    openai_env.setattr(requests, "post", fake_post)
    out = ai_core_llm.ask("system", "question", provider="openai")
    assert out == "core answer"


def test_ask_with_tools_drives_tool_loop(openai_env):
    # Tool-capable model name short-circuits the /models probe.
    openai_env.setenv("MEDIAHUB_LLM_MODEL_CHEAP", "llama-3.3-70b-versatile")
    responses = [
        _FakeResp(200, {
            "model": "llama-3.3-70b-versatile",
            "choices": [{"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q": "pb"}'},
                }],
            }}],
        }),
        _FakeResp(200, _chat("final answer")),
    ]
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        sent.append(json)
        return responses.pop(0)

    openai_env.setattr(requests, "post", fake_post)

    seen = {}

    def on_tool(name, args):
        seen["name"] = name
        seen["args"] = args
        return "tool result text"

    tools = [{
        "name": "lookup",
        "description": "look it up",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }]
    convo = ai_core_llm.ask_with_tools(
        "sys", "find the pb", tools=tools, on_tool_call=on_tool, provider="openai"
    )

    assert convo.text == "final answer"
    assert convo.provider == "openai"
    assert seen["name"] == "lookup"
    assert seen["args"] == {"q": "pb"}
    # Round 1 translated the Anthropic-shape tool into OpenAI's schema.
    tool0 = sent[0]["tools"][0]
    assert tool0["type"] == "function"
    assert tool0["function"]["name"] == "lookup"
    assert tool0["function"]["parameters"]["type"] == "object"
    # Round 2 echoed the assistant tool_calls plus a tool-result message.
    roles = [m["role"] for m in sent[1]["messages"]]
    assert "assistant" in roles and "tool" in roles
    assert convo.tool_calls[0].name == "lookup"
    assert convo.tool_calls[0].provider == "openai"


def test_premium_escalation_on_transient(openai_env):
    openai_env.setenv("MEDIAHUB_LLM_MODEL_PREMIUM", "prem-m")
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(json["model"])
        if json["model"] == "cheap-m":
            return _FakeResp(503, text="overloaded")
        return _FakeResp(200, _chat("premium answer", model="prem-m"))

    openai_env.setattr(requests, "post", fake_post)
    from mediahub.media_ai.llm_providers import call_openai

    # 'tagging' is non-hero => starts cheap, escalates to premium on failure.
    out = call_openai(
        [{"role": "user", "content": "x"}], None, 100, content_type="tagging"
    )
    assert out == "premium answer"
    assert calls == ["cheap-m", "prem-m"]


def test_cross_provider_failover_openai_to_gemini(openai_env):
    openai_env.setenv("GEMINI_API_KEY", "g-key")

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(500, text="boom")  # the openai endpoint always 5xx

    openai_env.setattr(requests, "post", fake_post)
    # Stub gemini so we can assert the chain fell through to it.
    openai_env.setattr(media_ai_llm, "_call_gemini", lambda *a, **k: "gemini answer")
    assert media_ai_llm.generate("hello") == "gemini answer"


def test_call_openai_returns_none_without_model(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "https://host/v1")
    for k in ("MEDIAHUB_LLM_MODEL_CHEAP", "MEDIAHUB_LLM_MODEL_PREMIUM",
              "MEDIAHUB_LLM_MODEL_OVERRIDES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    from mediahub.media_ai.llm_providers import call_openai

    # Endpoints configured but no model name => can't route, returns None.
    assert call_openai([{"role": "user", "content": "x"}], None, 10) is None


def test_openai_inert_when_unconfigured(monkeypatch):
    for k in ("MEDIAHUB_LLM_ENDPOINTS", "MEDIAHUB_LLM_PROVIDER", "MEDIAHUB_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)

    assert media_ai_llm._provider_order() == ("gemini", "anthropic")
    assert "openai" not in ai_core_llm._fallback_chain("gemini")
    assert media_ai_llm._is_openai_on() is False

    from mediahub.media_ai.llm_providers import call_openai, is_openai_configured
    assert is_openai_configured() is False
    assert call_openai([{"role": "user", "content": "x"}], None, 10) is None
