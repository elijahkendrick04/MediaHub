"""Tests for the Gemini overload circuit breaker.

When Gemini returns repeated 5xx responses (the May 2026 "high demand /
UNAVAILABLE" pattern that hit production for ~80s during
``POST /organisation/setup/capture``), every subsequent LLM call still
paid the round-trip cost before falling through to Anthropic. With ~24
sequential AI calls in the org-setup capture step this turned a normal
~10s capture into a 60-80s hang.

The breaker is a tiny in-process trip switch: N consecutive Gemini 5xx
responses open it and we skip Gemini for a cool-off period. Since the
finding-#43 convergence the state lives in ``ai_core.gemini_transport``
(one copy for both LLM wrappers): media_ai's hot path short-circuits to
``None`` while it's open, ai_core demotes Gemini to the tail of its
provider chain, and *both* wrappers' outcomes record into it.
"""
from __future__ import annotations

import time

import pytest

from mediahub.ai_core import gemini_transport
from mediahub.media_ai import llm as media_ai_llm


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Each test starts with a closed breaker."""
    with gemini_transport._breaker_lock:
        gemini_transport._breaker_state["consecutive_failures"] = 0
        gemini_transport._breaker_state["tripped_until"] = 0.0
    yield
    with gemini_transport._breaker_lock:
        gemini_transport._breaker_state["consecutive_failures"] = 0
        gemini_transport._breaker_state["tripped_until"] = 0.0


def test_breaker_closed_by_default():
    assert gemini_transport.breaker_is_open() is False


def test_breaker_trips_after_threshold_failures(monkeypatch):
    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(gemini_transport, "_BREAKER_COOLDOWN_S", 60)
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is False
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is False
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is True


def test_breaker_resets_on_success(monkeypatch):
    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 3)
    gemini_transport.breaker_record_failure()
    gemini_transport.breaker_record_failure()
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is True

    gemini_transport.breaker_record_success()
    assert gemini_transport.breaker_is_open() is False
    assert gemini_transport._breaker_state["consecutive_failures"] == 0


def test_breaker_closes_after_cooldown(monkeypatch):
    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 1)
    # Trip the breaker
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is True
    # Force the trip into the past
    with gemini_transport._breaker_lock:
        gemini_transport._breaker_state["tripped_until"] = time.monotonic() - 1
    assert gemini_transport.breaker_is_open() is False


def test_call_gemini_short_circuits_when_breaker_open(monkeypatch):
    """The breaker is open → ``_call_gemini`` must return None
    *without* making an HTTP request. We verify by tripping the
    breaker and then asserting ``requests.post`` is never called."""
    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 1)
    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: "fake-key")
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is True

    called = {"count": 0}

    def _no_call(*a, **k):
        called["count"] += 1
        raise AssertionError("requests.post must not be called when breaker is open")

    import requests

    monkeypatch.setattr(requests, "post", _no_call)
    out = media_ai_llm._call_gemini(
        [{"role": "user", "content": "hi"}], system=None, max_tokens=10
    )
    assert out is None
    assert called["count"] == 0


def test_breaker_trips_on_transport_timeouts(monkeypatch):
    """Transport failures (timeout / connection refused) are the breaker's
    most expensive case — each one eats the full request timeout — so
    consecutive timeouts must trip it just like 5xx responses do."""
    import requests

    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: "fake-key")

    def timeout_post(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(requests, "post", timeout_post)
    for _ in range(3):
        out = media_ai_llm._call_gemini(
            [{"role": "user", "content": "hi"}], system=None, max_tokens=10
        )
        assert out is None
    assert gemini_transport.breaker_is_open() is True


def test_breaker_trips_on_vision_transport_failures(monkeypatch):
    import requests

    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(media_ai_llm, "_resolve_gemini_key", lambda: "fake-key")

    def refuse_post(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", refuse_post)
    for _ in range(3):
        out = media_ai_llm._call_gemini_vision([], "describe", system=None, max_tokens=10)
        assert out is None
    assert gemini_transport.breaker_is_open() is True


def test_ai_core_demotes_gemini_when_breaker_open(monkeypatch):
    """``ai_core.llm._fallback_chain`` must move Gemini to the tail
    so Anthropic (or whatever else is configured) gets first shot
    while the breaker is open."""
    from mediahub.ai_core import llm as ai_core_llm

    monkeypatch.setattr(gemini_transport, "_BREAKER_THRESHOLD", 1)
    # Pretend both providers are configured
    monkeypatch.setattr(
        ai_core_llm, "_key_for",
        lambda p: "k" if p in ("gemini", "claude") else None,
    )

    # Closed → primary first
    chain = ai_core_llm._fallback_chain("gemini")
    assert chain[0] == "gemini"

    # Open → Gemini demoted to tail
    gemini_transport.breaker_record_failure()
    assert gemini_transport.breaker_is_open() is True
    chain = ai_core_llm._fallback_chain("gemini")
    assert chain[-1] == "gemini"
    assert chain[0] != "gemini"
