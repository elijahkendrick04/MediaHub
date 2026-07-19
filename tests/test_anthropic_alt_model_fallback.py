"""Tests for media_ai.llm._call_anthropic's alt-model fallback gating (#45).

The fallback to ALT_MODEL is deliberately narrow: only a model-specific
failure (404 model-not-found / 529 overloaded) can be helped by trying a
different model. For auth / bad-request / rate-limit errors a second
billable call won't succeed, so the loop must stop after one attempt.
And when the operator already pinned the model to ALT_MODEL there is no
different model to fall back to — exactly one attempt, ever.

Offline: the anthropic client is faked; no network, no usage DB.
"""
from __future__ import annotations

import pytest

import mediahub.media_ai.llm as m


class _ApiError(Exception):
    def __init__(self, status_code=None):
        super().__init__(f"api error (status={status_code})")
        if status_code is not None:
            self.status_code = status_code


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = None


class _FakeClient:
    """Yields one scripted outcome per messages.create call, in order.

    An Exception outcome is raised; a str outcome becomes the response text.
    Records the model of every attempt in ``calls``.
    """

    def __init__(self, outcomes):
        self.calls = []
        remaining = list(outcomes)
        client = self

        class _Messages:
            @staticmethod
            def create(**kwargs):
                client.calls.append(kwargs["model"])
                out = remaining.pop(0)
                if isinstance(out, Exception):
                    raise out
                return _Resp(out)

        self.messages = _Messages()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(m, "_has_anthropic_key", lambda: True)
    monkeypatch.setattr(m, "_log_call", lambda **kw: None)
    yield


def _call(monkeypatch, outcomes, model):
    client = _FakeClient(outcomes)
    monkeypatch.setattr(m, "_get_anthropic", lambda: client)
    text = m._call_anthropic([{"role": "user", "content": "hi"}], None, 64, model=model)
    return text, client.calls


PRIMARY = "claude-sonnet-4-6"


def test_529_overloaded_falls_back_to_alt_model(monkeypatch):
    text, calls = _call(monkeypatch, [_ApiError(529), "from-alt"], PRIMARY)
    assert text == "from-alt"
    assert calls == [PRIMARY, m.ALT_MODEL]


def test_404_model_not_found_falls_back_to_alt_model(monkeypatch):
    text, calls = _call(monkeypatch, [_ApiError(404), "from-alt"], PRIMARY)
    assert text == "from-alt"
    assert calls == [PRIMARY, m.ALT_MODEL]


def test_auth_error_does_not_burn_a_second_call(monkeypatch):
    text, calls = _call(monkeypatch, [_ApiError(401), "never-reached"], PRIMARY)
    assert text is None
    assert calls == [PRIMARY]


def test_rate_limit_does_not_burn_a_second_call(monkeypatch):
    text, calls = _call(monkeypatch, [_ApiError(429), "never-reached"], PRIMARY)
    assert text is None
    assert calls == [PRIMARY]


def test_statusless_error_does_not_burn_a_second_call(monkeypatch):
    # e.g. a transport error with no status_code attribute at all.
    text, calls = _call(monkeypatch, [_ApiError(), "never-reached"], PRIMARY)
    assert text is None
    assert calls == [PRIMARY]


def test_model_pinned_to_alt_model_never_retries_itself(monkeypatch):
    # Operator pinned MEDIAHUB_LLM_MODEL to the alt model: even a 529 must
    # not retry the identical model.
    text, calls = _call(monkeypatch, [_ApiError(529), "never-reached"], m.ALT_MODEL)
    assert text is None
    assert calls == [m.ALT_MODEL]


def test_success_on_primary_makes_exactly_one_call(monkeypatch):
    text, calls = _call(monkeypatch, ["from-primary", "never-reached"], PRIMARY)
    assert text == "from-primary"
    assert calls == [PRIMARY]
