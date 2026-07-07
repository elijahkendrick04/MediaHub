"""Tests for ai_core.llm_client — the OpenAI-compatible transport.

All offline: requests.post / requests.get are monkeypatched with fakes, the
same pattern as tests/test_gemini_circuit_breaker.py. Covers request shape,
multi-endpoint failover, transient-vs-fatal status handling, streaming, the
best-effort tool-support probe, embeddings, and env-driven construction.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.ai_core import llm_client as lc


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text="", lines=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or ""
        self._lines = lines or []

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        for ln in self._lines:
            yield ln


def _chat_payload(text, model="m", pin=7, pout=11):
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": pin, "completion_tokens": pout},
    }


# --- chat() request shape ---------------------------------------------------

def test_chat_posts_expected_request(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResp(200, _chat_payload("hello"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://host/v1"], "secret-key", default_model="m1")
    res = client.chat([{"role": "user", "content": "hi"}], max_completion_tokens=5)

    assert res.text == "hello"
    assert res.tokens_in == 7 and res.tokens_out == 11
    assert captured["url"] == "https://host/v1/chat/completions"
    assert captured["json"]["model"] == "m1"
    # max_completion_tokens is clamped to a floor of 16, and the cap is sent
    # under BOTH names by default so legacy servers (OpenRouter / Together /
    # llama.cpp document only max_tokens) still honour it.
    assert captured["json"]["max_completion_tokens"] == 16
    assert captured["json"]["max_tokens"] == 16
    assert captured["headers"]["Authorization"] == "Bearer secret-key"


@pytest.mark.parametrize(
    "mode,expect_completion,expect_legacy",
    [
        ("both", True, True),
        ("completion", True, False),
        ("legacy", False, True),
        ("", True, True),  # unset/empty => default 'both'
    ],
)
def test_chat_token_param_knob(monkeypatch, mode, expect_completion, expect_legacy):
    """MEDIAHUB_LLM_TOKEN_PARAM picks which output-cap field(s) ride the
    payload — strict endpoints (OpenAI reasoning models) reject the
    deprecated max_tokens, so 'completion' must suppress it."""
    if mode:
        monkeypatch.setenv("MEDIAHUB_LLM_TOKEN_PARAM", mode)
    else:
        monkeypatch.delenv("MEDIAHUB_LLM_TOKEN_PARAM", raising=False)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["json"] = json
        return _FakeResp(200, _chat_payload("x"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://host/v1"], None, default_model="m")
    client.chat([{"role": "user", "content": "hi"}], max_completion_tokens=64)
    assert ("max_completion_tokens" in captured["json"]) is expect_completion
    assert ("max_tokens" in captured["json"]) is expect_legacy
    for field in ("max_completion_tokens", "max_tokens"):
        if field in captured["json"]:
            assert captured["json"][field] == 64


def test_chat_omits_auth_header_when_keyless(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["headers"] = headers
        return _FakeResp(200, _chat_payload("x"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://host/v1"], None, default_model="m")
    client.chat([{"role": "user", "content": "hi"}])
    assert "Authorization" not in captured["headers"]


def test_chat_injects_system_message(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["json"] = json
        return _FakeResp(200, _chat_payload("x"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://host/v1"], "k", default_model="m")
    client.chat([{"role": "user", "content": "hi"}], system="be terse")
    msgs = captured["json"]["messages"]
    assert msgs[0] == {"role": "system", "content": "be terse"}
    assert msgs[1]["role"] == "user"


def test_chat_raises_without_model(monkeypatch):
    client = lc.OpenAICompatClient(["https://a/v1"], "k")  # no default model
    with pytest.raises(lc.OpenAICompatError):
        client.chat([{"role": "user", "content": "hi"}])


# --- failover semantics -----------------------------------------------------

def test_failover_advances_on_5xx(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(url)
        if "first" in url:
            return _FakeResp(503, text="overloaded")
        return _FakeResp(200, _chat_payload("recovered"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(
        ["https://first/v1", "https://second/v1"], "k", default_model="m"
    )
    res = client.chat([{"role": "user", "content": "hi"}])
    assert res.text == "recovered"
    assert len(calls) == 2
    assert calls[0].startswith("https://first")
    assert calls[1].startswith("https://second")


def test_non_transient_400_raises_immediately(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(url)
        return _FakeResp(400, text="bad request")

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(
        ["https://first/v1", "https://second/v1"], "k", default_model="m"
    )
    with pytest.raises(lc.OpenAICompatError):
        client.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1  # did NOT try the second endpoint


def test_all_endpoints_transient_raises(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp(429, text="rate limited")

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://a/v1", "https://b/v1"], "k", default_model="m")
    with pytest.raises(lc.OpenAICompatError):
        client.chat([{"role": "user", "content": "hi"}])


def test_transport_error_fails_over(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(url)
        if "//a/" in url:
            raise OSError("connection refused")
        return _FakeResp(200, _chat_payload("ok"))

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://a/v1", "https://b/v1"], "k", default_model="m")
    res = client.chat([{"role": "user", "content": "hi"}])
    assert res.text == "ok"
    assert len(calls) == 2


# --- streaming --------------------------------------------------------------

def test_stream_chat_concatenates_deltas(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "",
        'data: {"choices":[{"delta":{}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"IGNORED"}}]}',
    ]

    def fake_post(url, json=None, headers=None, timeout=None, stream=False, **kw):
        assert stream is True
        assert json["stream"] is True
        return _FakeResp(200, lines=lines)

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://a/v1"], "k", default_model="m")
    out = "".join(client.stream_chat([{"role": "user", "content": "hi"}]))
    assert out == "Hello"  # stops at [DONE]; trailing chunk ignored


def test_stream_chat_raises_on_error_status(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, stream=False, **kw):
        return _FakeResp(500, text="boom")

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://a/v1"], "k", default_model="m")
    with pytest.raises(lc.OpenAICompatError):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))


# --- supports_tools ---------------------------------------------------------

def test_supports_tools_by_name():
    client = lc.OpenAICompatClient(["https://a/v1"], "k")
    assert client.supports_tools("llama-3.3-70b-versatile") is True
    assert client.supports_tools("gpt-4o-mini") is True


def test_supports_tools_probe_success(monkeypatch):
    def fake_get(url, headers=None, timeout=None, **kw):
        assert url == "https://a/v1/models"
        return _FakeResp(200, {"data": [{"id": "some-exotic-model"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    client = lc.OpenAICompatClient(["https://a/v1"], "k")
    assert client.supports_tools("some-exotic-model") is True


def test_supports_tools_probe_failure_returns_false(monkeypatch):
    def fake_get(url, headers=None, timeout=None, **kw):
        raise OSError("no /models endpoint")

    monkeypatch.setattr(requests, "get", fake_get)
    client = lc.OpenAICompatClient(["https://a/v1"], "k")
    assert client.supports_tools("unknown-weird-model") is False


def test_models_probe_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None, **kw):
        calls["n"] += 1
        return _FakeResp(200, {"data": [{"id": "m"}]})

    monkeypatch.setattr(requests, "get", fake_get)
    client = lc.OpenAICompatClient(["https://a/v1"], "k")
    client.supports_tools("unknown-1")
    client.supports_tools("unknown-2")
    assert calls["n"] == 1  # probed once, then cached


# --- embeddings -------------------------------------------------------------

def test_embeddings(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        assert url == "https://a/v1/embeddings"
        assert json["input"] == ["a", "b"]
        return _FakeResp(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]})

    monkeypatch.setattr(requests, "post", fake_post)
    client = lc.OpenAICompatClient(["https://a/v1"], "k", default_model="emb")
    assert client.embeddings(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


# --- env helpers ------------------------------------------------------------

def test_endpoints_from_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", " https://a/v1 , https://b/v1/ ,")
    assert lc.endpoints_from_env() == ["https://a/v1", "https://b/v1"]


def test_endpoints_from_env_unset(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LLM_ENDPOINTS", raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    assert lc.endpoints_from_env() == []


def test_client_from_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LLM_ENDPOINTS", raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    assert lc.client_from_env() is None


def test_client_from_env_builds(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "https://a/v1")
    monkeypatch.setenv("MEDIAHUB_LLM_API_KEY", "k")
    monkeypatch.setenv("MEDIAHUB_LLM_TIMEOUT", "12.5")
    client = lc.client_from_env(default_model="m")
    assert client is not None
    assert client.endpoints == ["https://a/v1"]
    assert client.api_key == "k"
    assert client.timeout == 12.5
    assert client.default_model == "m"
