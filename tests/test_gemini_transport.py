"""Unit tests for ai_core.gemini_transport — the single Gemini REST
transport both LLM wrappers consume (deep-review finding #43).

Pins the transport contract the wrappers build their opposite error
philosophies on: classified ``GeminiTransportError`` (kind / status /
transient), key-redacted messages, key-in-header-not-URL, per-call
timeout resolution, and breaker accounting (transport errors + 5xx
count, a decoded 200 clears, 429 doesn't count).
"""
from __future__ import annotations

import pytest
import requests

from mediahub.ai_core import gemini_transport as t

KEY = "AIzaSyTEST-transport-not-real"


class _Resp:
    def __init__(self, status_code: int, body=None, text: str = "err body"):
        self.status_code = status_code
        self.text = text
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _Capture:
    def __init__(self, response=None, exc: BaseException | None = None):
        self.kwargs: dict = {}
        self._response = response or _Resp(200, {"candidates": []})
        self._exc = exc

    def __call__(self, url, **kwargs):
        self.kwargs = {"url": url, **kwargs}
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _closed_breaker():
    t.breaker_record_success()
    yield
    t.breaker_record_success()


# ---------------------------------------------------------------------------
# status classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 408, 409, 425, 429, 529, 500, 502, 503, 599])
def test_status_transient_true(status):
    assert t.status_transient(status) is True


@pytest.mark.parametrize("status", [400, 404, 418, 422, 200])
def test_status_transient_false(status):
    assert t.status_transient(status) is False


# ---------------------------------------------------------------------------
# generate_content — wire shape
# ---------------------------------------------------------------------------


def _payload():
    return {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


def test_key_rides_header_never_url(monkeypatch):
    cap = _Capture(response=_Resp(200, {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}))
    monkeypatch.setattr(requests, "post", cap)
    t.generate_content(_payload(), key=KEY)
    assert cap.kwargs["headers"]["x-goog-api-key"] == KEY
    assert KEY not in cap.kwargs["url"]
    assert "key=" not in cap.kwargs["url"]


def test_timeout_default_and_env_override(monkeypatch):
    cap = _Capture(response=_Resp(200, {"candidates": []}))
    monkeypatch.setattr(requests, "post", cap)
    monkeypatch.delenv("MEDIAHUB_GEMINI_TIMEOUT", raising=False)
    t.generate_content(_payload(), key=KEY, timeout_default=45.0)
    assert cap.kwargs["timeout"] == 45.0
    monkeypatch.setenv("MEDIAHUB_GEMINI_TIMEOUT", "90")
    t.generate_content(_payload(), key=KEY, timeout_default=45.0)
    assert cap.kwargs["timeout"] == 90.0


def test_model_param_overrides_env(monkeypatch):
    cap = _Capture(response=_Resp(200, {"candidates": []}))
    monkeypatch.setattr(requests, "post", cap)
    monkeypatch.setenv("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-pro")
    t.generate_content(_payload(), key=KEY, model="gemini-2.5-flash")
    assert "gemini-2.5-flash:generateContent" in cap.kwargs["url"]


# ---------------------------------------------------------------------------
# generate_content — failure classification + redaction
# ---------------------------------------------------------------------------


def test_transport_error_kind_transient_and_redacted(monkeypatch):
    exc = requests.exceptions.ConnectionError(f"url ...:generateContent?key={KEY} reset")
    monkeypatch.setattr(requests, "post", _Capture(exc=exc))
    with pytest.raises(t.GeminiTransportError) as ei:
        t.generate_content(_payload(), key=KEY)
    e = ei.value
    assert e.kind == "transport"
    assert e.status is None
    assert e.transient is True
    assert KEY not in str(e)
    assert "***REDACTED***" in str(e)


def test_http_error_kind_status_and_body_redaction(monkeypatch):
    monkeypatch.setattr(
        requests, "post", _Capture(response=_Resp(503, text=f"overloaded, key {KEY}"))
    )
    with pytest.raises(t.GeminiTransportError) as ei:
        t.generate_content(_payload(), key=KEY)
    e = ei.value
    assert e.kind == "http_503"
    assert e.status == 503
    assert e.transient is True
    assert KEY not in str(e)


@pytest.mark.parametrize("status,transient", [(429, True), (401, True), (400, False), (404, False)])
def test_http_transience_per_status(monkeypatch, status, transient):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(status)))
    with pytest.raises(t.GeminiTransportError) as ei:
        t.generate_content(_payload(), key=KEY)
    assert ei.value.transient is transient


def test_undecodable_200_is_parse_kind(monkeypatch):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(200, body=None)))
    with pytest.raises(t.GeminiTransportError) as ei:
        t.generate_content(_payload(), key=KEY)
    assert ei.value.kind == "parse"
    assert ei.value.transient is True


# ---------------------------------------------------------------------------
# breaker accounting — the bidirectional half of finding #43
# ---------------------------------------------------------------------------


def _failures() -> int:
    return t.breaker_snapshot()["consecutive_failures"]


def test_transport_error_counts_toward_breaker(monkeypatch):
    monkeypatch.setattr(
        requests, "post", _Capture(exc=requests.exceptions.Timeout("timed out"))
    )
    with pytest.raises(t.GeminiTransportError):
        t.generate_content(_payload(), key=KEY)
    assert _failures() == 1


def test_5xx_counts_toward_breaker(monkeypatch):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(500)))
    with pytest.raises(t.GeminiTransportError):
        t.generate_content(_payload(), key=KEY)
    assert _failures() == 1


def test_429_does_not_count(monkeypatch):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(429)))
    with pytest.raises(t.GeminiTransportError):
        t.generate_content(_payload(), key=KEY)
    assert _failures() == 0


def test_decoded_200_clears_breaker(monkeypatch):
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(500)))
    for _ in range(2):
        with pytest.raises(t.GeminiTransportError):
            t.generate_content(_payload(), key=KEY)
    assert _failures() == 2
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(200, {"candidates": []})))
    t.generate_content(_payload(), key=KEY)
    assert _failures() == 0


def test_breaker_snapshot_shape():
    snap = t.breaker_snapshot()
    assert set(snap) == {
        "open",
        "consecutive_failures",
        "seconds_until_reset",
        "threshold",
        "cooldown_seconds",
    }


# ---------------------------------------------------------------------------
# response-shape helpers
# ---------------------------------------------------------------------------


def test_first_candidate_parts_happy_path():
    data = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    parts = t.first_candidate_parts(data)
    assert t.text_from_parts(parts) == "ab"


def test_first_candidate_parts_no_candidates():
    with pytest.raises(t.GeminiTransportError) as ei:
        t.first_candidate_parts({"promptFeedback": {"blockReason": "SAFETY"}})
    assert ei.value.kind == "no_candidates"
    assert ei.value.transient is True


@pytest.mark.parametrize(
    "data",
    [
        {"candidates": ["not-a-dict"]},
        {"candidates": [{"content": {"parts": "not-a-list"}}]},
    ],
)
def test_first_candidate_parts_malformed(data):
    with pytest.raises(t.GeminiTransportError) as ei:
        t.first_candidate_parts(data)
    assert ei.value.kind == "malformed"


def test_missing_parts_is_empty_output_not_malformed():
    """The documented empty-output shape — a candidate whose content has no
    parts key (safety block / MAX_TOKENS eaten by thinking) — must come back
    as [] so wrappers raise their honest finishReason-citing empty error
    instead of mislabelling the response 'malformed'."""
    data = {"candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}]}
    assert t.first_candidate_parts(data) == []
    assert t.finish_reason(data) == "MAX_TOKENS"


def test_error_body_redacted_before_truncation(monkeypatch):
    """A key straddling the 300-char truncation boundary must not leave an
    un-redacted fragment: redaction runs on the full body, then truncates."""
    body = "x" * 290 + f"denied for key {KEY} end"
    monkeypatch.setattr(requests, "post", _Capture(response=_Resp(403, text=body)))
    with pytest.raises(t.GeminiTransportError) as ei:
        t.generate_content(_payload(), key=KEY)
    msg = str(ei.value)
    assert KEY not in msg
    assert KEY[:12] not in msg  # no partial fragment either


def test_finish_reason_from_candidate_then_prompt_feedback():
    assert t.finish_reason({"candidates": [{"finishReason": "MAX_TOKENS"}]}) == "MAX_TOKENS"
    assert (
        t.finish_reason({"candidates": [{}], "promptFeedback": {"blockReason": "SAFETY"}})
        == "SAFETY"
    )
    assert t.finish_reason({}) is None


def test_usage_tokens():
    data = {"usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7}}
    assert t.usage_tokens(data) == (11, 7)
    assert t.usage_tokens({}) == (None, None)
