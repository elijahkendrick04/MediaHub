"""Security regression: the Gemini API key must never reach log output.

Pre-fix, ``log.warning("gemini transport failed: %s", e)`` embedded the
failing URL — including the ``?key=…`` query parameter — straight into
stdout, which is the canonical leak path for Render's log aggregator.
The fix runs the exception string through the shared transport's
``redact_key`` before logging or storing it on the usage ledger (the
helper lives in ``ai_core.gemini_transport`` — one copy for both LLM
wrappers, finding #43).

We exercise the redaction helper directly rather than provoking a real
network failure, so the test runs offline and deterministically.
"""
from __future__ import annotations

from mediahub.ai_core import gemini_transport
from mediahub.ai_core.gemini_transport import redact_key as _redact_key


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


def test_call_gemini_sends_key_in_header_not_url(monkeypatch):
    """_call_gemini must put the key in the x-goog-api-key header — a
    URL-borne key rides into every exception repr / access log."""
    import requests

    from mediahub.media_ai import llm as media_ai_llm

    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: SECRET)
    gemini_transport.breaker_record_success()  # start closed
    seen = {}

    class _Resp:
        status_code = 200
        ok = True

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

    def fake_post(url, headers=None, **kw):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    out = media_ai_llm._call_gemini([{"role": "user", "content": "x"}], None, 10)
    assert out == "hi"
    assert SECRET not in seen["url"]
    assert seen["headers"].get("x-goog-api-key") == SECRET


def test_call_gemini_vision_sends_key_in_header_not_url(monkeypatch):
    import requests

    from mediahub.media_ai import llm as media_ai_llm

    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: SECRET)
    gemini_transport.breaker_record_success()  # start closed
    seen = {}

    class _Resp:
        status_code = 200
        ok = True

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "seen"}]}}]}

    def fake_post(url, headers=None, **kw):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    out = media_ai_llm._call_gemini_vision([], "describe", None, 10)
    assert out == "seen"
    assert SECRET not in seen["url"]
    assert seen["headers"].get("x-goog-api-key") == SECRET


def test_imagen_predict_url_and_logs_carry_no_key(monkeypatch, caplog):
    """The Imagen ``:predict`` client must send the key in the
    ``x-goog-api-key`` header, never the URL, and its transport-failure
    log line must be redacted — a requests exception repr embeds the
    failing URL, so a URL-borne key would land straight in the logs."""
    import logging

    import requests

    from mediahub.media_ai.imagine_providers import gemini_imagine

    monkeypatch.setattr(gemini_imagine, "resolve_gemini_key", lambda: SECRET)
    seen = {}

    def boom(url, headers=None, **kw):
        seen["url"] = url
        seen["headers"] = headers or {}
        raise requests.exceptions.ConnectionError(f"failed for url: {url}?key={SECRET}")

    monkeypatch.setattr(requests, "post", boom)
    with caplog.at_level(logging.DEBUG, logger="mediahub.media_ai.imagine_providers.gemini_imagine"):
        out = gemini_imagine.imagen_predict("a poolside backdrop")
    assert out == []
    assert SECRET not in seen["url"]
    assert seen["headers"].get("x-goog-api-key") == SECRET
    assert SECRET not in caplog.text
    assert "***REDACTED***" in caplog.text


def test_imagen_predict_non_200_body_redacted(monkeypatch, caplog):
    import logging

    import requests

    from mediahub.media_ai.imagine_providers import gemini_imagine

    class _Resp:
        status_code = 403
        text = f"denied for key {SECRET}"

    monkeypatch.setattr(gemini_imagine, "resolve_gemini_key", lambda: SECRET)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    with caplog.at_level(logging.DEBUG, logger="mediahub.media_ai.imagine_providers.gemini_imagine"):
        out = gemini_imagine.imagen_predict("a poolside backdrop")
    assert out == []
    assert SECRET not in caplog.text
