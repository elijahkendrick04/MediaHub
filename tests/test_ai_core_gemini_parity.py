"""ai_core ↔ media_ai Gemini parity (deep-review finding #43, stage A).

The two LLM wrappers had drifted on three operator-visible behaviours;
these tests pin the fixes:

* ``ai_core`` honours ``MEDIAHUB_GEMINI_TIMEOUT`` per call (the call-site
  defaults — 45s plain ask, 60s tool rounds — are preserved when unset).
* ``ai_core`` sends no ``temperature`` to Gemini — both wrappers sample at
  the API default, so the same surface can't drift in output character
  depending on which wrapper served it.
* ``ai_core`` records Gemini outcomes into the shared overload circuit
  breaker. It used to read the breaker but never record, so a Gemini
  outage seen only via chat / copilot / deep-research never tripped it.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.ai_core import gemini_transport
from mediahub.ai_core import llm as ai_core_llm
from mediahub.media_ai import llm as media_ai_llm

KEY = "AIzaSyTEST-parity-not-a-real-key"


class _OkResp:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}


class _Resp:
    def __init__(self, status_code: int, text: str = "err body"):
        self.status_code = status_code
        self.text = text

    @staticmethod
    def json():
        return {}


class _Capture:
    """Stand-in for requests.post that records the call kwargs."""

    def __init__(self, response=None, exc: BaseException | None = None):
        self.kwargs: dict = {}
        self.calls = 0
        self._response = response or _OkResp()
        self._exc = exc

    def __call__(self, url, **kwargs):
        self.calls += 1
        self.kwargs = {"url": url, **kwargs}
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _clean_breaker():
    """Breaker state is module-global; make every test start and end closed."""
    gemini_transport.breaker_record_success()
    yield
    gemini_transport.breaker_record_success()


@pytest.fixture
def gemini_only(monkeypatch):
    monkeypatch.setattr(ai_core_llm, "_key_for", lambda p: KEY if p == "gemini" else None)
    monkeypatch.delenv("MEDIAHUB_GEMINI_TIMEOUT", raising=False)


def _run_tool_loop(max_tokens: int = 64):
    return ai_core_llm._ask_gemini_with_tools(
        "sys", "user", tools=[], on_tool_call=lambda n, a: "", max_tokens=max_tokens, max_rounds=1
    )


# ---------------------------------------------------------------------------
# MEDIAHUB_GEMINI_TIMEOUT — honoured per call, defaults preserved
# ---------------------------------------------------------------------------


def test_ask_gemini_default_timeout_is_45(gemini_only, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    assert ai_core_llm._ask_gemini("sys", "user", 64) == "hello"
    assert cap.kwargs["timeout"] == 45.0


def test_ask_gemini_honours_env_timeout(gemini_only, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_TIMEOUT", "90")
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    ai_core_llm._ask_gemini("sys", "user", 64)
    assert cap.kwargs["timeout"] == 90.0


def test_tool_loop_default_timeout_is_60(gemini_only, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    convo = _run_tool_loop()
    assert convo.text == "hello"
    assert cap.kwargs["timeout"] == 60.0


def test_tool_loop_honours_env_timeout(gemini_only, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_TIMEOUT", "120")
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    _run_tool_loop()
    assert cap.kwargs["timeout"] == 120.0


def test_unparseable_env_timeout_falls_back_to_default(gemini_only, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEMINI_TIMEOUT", "not-a-number")
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    ai_core_llm._ask_gemini("sys", "user", 64)
    assert cap.kwargs["timeout"] == 45.0


# ---------------------------------------------------------------------------
# generationConfig — no temperature, key in header not URL
# ---------------------------------------------------------------------------


def test_no_temperature_in_generation_config(gemini_only, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    ai_core_llm._ask_gemini("sys", "user", 64)
    gen_cfg = cap.kwargs["json"]["generationConfig"]
    assert "temperature" not in gen_cfg
    assert gen_cfg["maxOutputTokens"] == 64


def test_tool_loop_sends_no_temperature(gemini_only, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    _run_tool_loop(max_tokens=99)
    gen_cfg = cap.kwargs["json"]["generationConfig"]
    assert "temperature" not in gen_cfg
    assert gen_cfg["maxOutputTokens"] == 99


def test_key_rides_header_not_url(gemini_only, monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(requests, "post", cap)
    ai_core_llm._ask_gemini("sys", "user", 64)
    assert cap.kwargs["headers"]["x-goog-api-key"] == KEY
    assert "key=" not in cap.kwargs["url"]


# ---------------------------------------------------------------------------
# Breaker recording — ai_core outcomes now count
# ---------------------------------------------------------------------------


def _failures() -> int:
    return gemini_transport.breaker_snapshot()["consecutive_failures"]


def test_transport_error_records_breaker_failure(gemini_only, monkeypatch):
    monkeypatch.setattr(
        requests, "post", _Capture(exc=requests.exceptions.ConnectionError("reset"))
    )
    with pytest.raises(ai_core_llm.ProviderError):
        ai_core_llm._ask_gemini("sys", "user", 64)
    assert _failures() == 1


def test_5xx_records_breaker_failure(gemini_only, monkeypatch):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(503)))
    with pytest.raises(ai_core_llm.ProviderError):
        ai_core_llm._ask_gemini("sys", "user", 64)
    assert _failures() == 1


def test_429_does_not_record_breaker_failure(gemini_only, monkeypatch):
    """A rate limit is not an outage — same policy as media_ai._call_gemini."""
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(429)))
    with pytest.raises(ai_core_llm.ProviderError):
        ai_core_llm._ask_gemini("sys", "user", 64)
    assert _failures() == 0


def test_success_clears_breaker_failures(gemini_only, monkeypatch):
    monkeypatch.setattr(
        requests, "post", _Capture(exc=requests.exceptions.ConnectionError("reset"))
    )
    for _ in range(2):
        with pytest.raises(ai_core_llm.ProviderError):
            ai_core_llm._ask_gemini("sys", "user", 64)
    assert _failures() == 2
    monkeypatch.setattr(requests, "post", _Capture())
    ai_core_llm._ask_gemini("sys", "user", 64)
    assert _failures() == 0


def test_tool_loop_transport_error_records_breaker_failure(gemini_only, monkeypatch):
    monkeypatch.setattr(
        requests, "post", _Capture(exc=requests.exceptions.ConnectionError("reset"))
    )
    with pytest.raises(ai_core_llm.ProviderError):
        _run_tool_loop()
    assert _failures() == 1


def test_no_parts_empty_shape_cites_finish_reason(gemini_only, monkeypatch):
    """The documented MAX_TOKENS/SAFETY shape — candidate present, no parts
    key — must surface the honest finishReason-citing error, not a
    'malformed' mislabel (adversarial-review fix on finding #43 B)."""

    class _NoPartsResp:
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {"candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}]}

    monkeypatch.setattr(requests, "post", _Capture(response=_NoPartsResp()))
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini("sys", "user", 64)
    assert "no text" in str(ei.value).lower()
    assert "MAX_TOKENS" in str(ei.value)
    assert ei.value.transient is True


def test_tool_loop_empty_conversation_raises_honestly(gemini_only, monkeypatch):
    """A tool conversation that produced no tool calls AND no text must
    raise the same honest empty-output error as the plain-ask path, not
    return a silent empty ToolConversation."""

    class _NoPartsResp:
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {"candidates": [{"content": {"role": "model"}, "finishReason": "SAFETY"}]}

    monkeypatch.setattr(requests, "post", _Capture(response=_NoPartsResp()))
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini_with_tools(
            "sys", "user", tools=[], on_tool_call=lambda n, a: "", max_tokens=64, max_rounds=2
        )
    assert "no text" in str(ei.value).lower()
    assert "SAFETY" in str(ei.value)


def test_ai_core_outage_trips_breaker_for_media_ai(gemini_only, monkeypatch):
    """The cross-wrapper point of finding #43: an outage seen only by
    ai_core (chat / copilot / deep-research) must trip the breaker that
    media_ai's hot path consults, so caption calls skip the doomed
    round-trip instead of each eating the full timeout."""
    monkeypatch.setattr(
        requests, "post", _Capture(exc=requests.exceptions.ConnectionError("reset"))
    )
    for _ in range(gemini_transport._BREAKER_THRESHOLD):
        with pytest.raises(ai_core_llm.ProviderError):
            ai_core_llm._ask_gemini("sys", "user", 64)
    assert gemini_transport.breaker_is_open() is True

    # media_ai must now short-circuit without any HTTP round-trip.
    def _must_not_post(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("breaker open: media_ai should not hit the network")

    monkeypatch.setattr(requests, "post", _must_not_post)
    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: KEY)
    assert media_ai_llm._call_gemini([{"role": "user", "content": "x"}], None, 16) is None
