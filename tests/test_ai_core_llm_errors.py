"""ai_core.llm error hygiene.

Two regressions pinned here:

* the Gemini API key must never ride a ``ProviderError`` message —
  ``ai_core.llm`` sends the key as a ``?key=…`` query param, and a
  ``requests`` exception repr embeds the failing URL, so an unredacted
  wrap leaks the secret into logs (ai_director) and user-facing errors
  (web/ai_caption's ClaudeUnavailableError).
* ``_is_transient`` must match word-bounded tokens — bare substrings
  misclassified permanent errors ("rate" in 'generateContent', "auth"
  in 'author') as transient, retrying a bad-model-name config error on
  the other provider and burying the real message.
"""
from __future__ import annotations

import pytest
import requests

from mediahub.ai_core import llm as ai_core_llm

SECRET = "AIzaSyTEST-do-not-leak-XYZ789"


# ---------------------------------------------------------------------------
# Key redaction in ProviderError messages
# ---------------------------------------------------------------------------


def _fail_with_key_url(*a, **k):
    raise requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='generativelanguage.googleapis.com'): "
        f"url: /v1beta/models/gemini-2.5-flash:generateContent?key={SECRET}"
    )


def test_ask_gemini_transport_error_redacts_key(monkeypatch):
    monkeypatch.setattr(ai_core_llm, "_key_for", lambda p: SECRET if p == "gemini" else None)
    monkeypatch.setattr(requests, "post", _fail_with_key_url)
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini("sys", "user", 100)
    msg = str(ei.value)
    assert SECRET not in msg
    assert "***REDACTED***" in msg


def test_ask_gemini_http_body_redacts_key(monkeypatch):
    class _Resp:
        status_code = 400
        text = f"invalid request for key {SECRET}"

    monkeypatch.setattr(ai_core_llm, "_key_for", lambda p: SECRET if p == "gemini" else None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini("sys", "user", 100)
    assert SECRET not in str(ei.value)


def test_ask_gemini_with_tools_transport_error_redacts_key(monkeypatch):
    monkeypatch.setattr(ai_core_llm, "_key_for", lambda p: SECRET if p == "gemini" else None)
    monkeypatch.setattr(requests, "post", _fail_with_key_url)
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini_with_tools(
            "sys", "user", tools=[], on_tool_call=lambda n, a: "", max_tokens=100, max_rounds=1
        )
    msg = str(ei.value)
    assert SECRET not in msg
    assert "***REDACTED***" in msg


def test_redacted_message_keeps_failover_signal(monkeypatch):
    """_is_transient must still see the status word after redaction."""

    def fail(*a, **k):
        raise requests.exceptions.ConnectionError(f"503 overloaded url ?key={SECRET}")

    monkeypatch.setattr(ai_core_llm, "_key_for", lambda p: SECRET if p == "gemini" else None)
    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(ai_core_llm.ProviderError) as ei:
        ai_core_llm._ask_gemini("sys", "user", 100)
    assert ai_core_llm._is_transient(str(ei.value)) is True
    assert SECRET not in str(ei.value)


# ---------------------------------------------------------------------------
# _is_transient — word-bounded classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "Gemini HTTP 429: RESOURCE_EXHAUSTED",
        "quota exceeded for this project",
        "rate limit reached, retry later",
        "rate-limited by upstream",
        "HTTP 500 internal error",
        "Gemini HTTP 503: high demand",
        "502 bad gateway",
        "504 gateway timeout",
        "request timed out after 45s",
        "ReadTimeoutError: connection timeout",
        "Error code: 529 - overloaded_error",
        "401 unauthorized",
        "403 forbidden by policy",
        "Unauthorised: bad credentials",
    ],
)
def test_transient_errors_still_match(msg):
    assert ai_core_llm._is_transient(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        # The Gemini 404 body for a bad model name — 'generateContent'
        # contains 'rate' and must NOT be treated as transient.
        "Gemini HTTP 404: models/gemini-9.9-flash is not found or not "
        "supported for generateContent",
        "response written by the author was moderate and accurate",
        "the caption is accurate",
        "invalid JSON in response",
        "HTTP 400: bad request payload",
    ],
)
def test_permanent_errors_do_not_match(msg):
    assert ai_core_llm._is_transient(msg) is False
