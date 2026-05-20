"""Security regression: the Gemini API key must never reach log output.

Pre-fix, ``log.warning("gemini transport failed: %s", e)`` embedded the
failing URL — including the ``?key=…`` query parameter — straight into
stdout, which is the canonical leak path for Render's log aggregator.
The fix runs the exception string through ``_redact_key`` before
logging or storing it on the usage ledger.

We exercise the redaction helper directly rather than provoking a real
network failure, so the test runs offline and deterministically.
"""
from __future__ import annotations

from mediahub.media_ai.llm import _redact_key


SECRET = "AIzaSyTEST-do-not-log-DEF456"


def test_redacts_known_key_anywhere_in_string():
    msg = (
        "HTTPSConnectionPool(host='generativelanguage.googleapis.com', "
        f"port=443): url: ...:generateContent?key={SECRET} (...)"
    )
    cleaned = _redact_key(msg, SECRET)
    assert SECRET not in cleaned
    assert "***REDACTED***" in cleaned


def test_redacts_unknown_key_via_query_param_pattern():
    # Caller may not have the key handy when logging — e.g. logs from a
    # provider library that includes the URL but not the original key
    # value. The query-param fallback strips ``?key=…`` regardless.
    msg = "Got 500 from https://example.com/x?key=somethingsecret&model=foo"
    cleaned = _redact_key(msg, None)
    assert "somethingsecret" not in cleaned
    assert "key=***REDACTED***" in cleaned


def test_redacts_inside_ampersand_chain():
    msg = "...?model=gemini-2.5-flash&key=ANOTHERKEY&extra=1"
    cleaned = _redact_key(msg, None)
    assert "ANOTHERKEY" not in cleaned


def test_empty_input_returns_empty():
    assert _redact_key("", SECRET) == ""
    assert _redact_key("plain text without secrets", SECRET) == "plain text without secrets"
