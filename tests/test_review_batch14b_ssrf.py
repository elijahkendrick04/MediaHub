"""Regression tests for review batch 14b — SSRF / egress hardening.

Covers the offline-checkable parts of findings:

* #34  — ``context_engine.research.ResearchClient.fetch_text`` / ``fetch_bytes``
         delegate to the SSRF-hardened ``safe_fetch`` / ``safe_fetch_bytes``
         (instead of raw ``urllib.request.urlopen``), and the caller-less
         ``WebResearcher.fetch_url`` is gone.
* #120 — the CSV-URL connector routes its fetch through ``safe_fetch_bytes``
         and honest-errors when the guard blocks the URL.
* #124 — ``results_fetch.fetch.StaticBackend`` pins every hop via
         ``safe_fetch._pinned_open`` (no independent re-resolve).
* #126 — ``_read_capped`` enforces a monotonic total-read deadline (slowloris).

Everything is offline — no test makes a real network call.
"""

from __future__ import annotations

import pytest

import mediahub.web_research.safe_fetch as safe_fetch_mod
from mediahub.context_engine.research import ResearchClient
from mediahub.data_hub.connectors.base import ConnectorNotConfigured
from mediahub.data_hub.connectors.builtin import CsvUrlConnector
from mediahub.results_fetch import fetch as fetchmod
from mediahub.web_research.search import WebResearcher


# ---------------------------------------------------------------------------
# #34 — context_engine routes through the hardened door
# ---------------------------------------------------------------------------


def test_fetch_text_delegates_to_safe_fetch(monkeypatch):
    seen = {}

    def fake_safe_fetch(url, *, max_chars, timeout, max_bytes):
        seen.update(url=url, max_chars=max_chars, timeout=timeout, max_bytes=max_bytes)
        return "CLEAN TEXT"

    monkeypatch.setattr(safe_fetch_mod, "safe_fetch", fake_safe_fetch)

    out = ResearchClient().fetch_text("https://example.org/p", max_chars=1234)

    assert out == "CLEAN TEXT"
    assert seen["url"] == "https://example.org/p"
    assert seen["max_chars"] == 1234
    assert seen["max_bytes"] == 200_000
    assert seen["timeout"] == ResearchClient._DEFAULT_TIMEOUT


def test_fetch_text_threads_none_through(monkeypatch):
    monkeypatch.setattr(safe_fetch_mod, "safe_fetch", lambda *a, **k: None)
    assert ResearchClient().fetch_text("https://example.org/p") is None


def test_fetch_bytes_delegates_to_safe_fetch_bytes(monkeypatch):
    seen = {}

    def fake_bytes(url, *, max_bytes, timeout):
        seen.update(url=url, max_bytes=max_bytes, timeout=timeout)
        return ("application/pdf", b"%PDF-1.7 payload")

    monkeypatch.setattr(safe_fetch_mod, "safe_fetch_bytes", fake_bytes)

    out = ResearchClient().fetch_bytes("https://example.org/f.pdf")

    assert out == b"%PDF-1.7 payload"  # the bytes half of the (ctype, bytes) tuple
    assert seen["url"] == "https://example.org/f.pdf"
    assert seen["max_bytes"] == 500_000
    assert seen["timeout"] == ResearchClient._DEFAULT_TIMEOUT


def test_fetch_bytes_threads_none_through(monkeypatch):
    monkeypatch.setattr(safe_fetch_mod, "safe_fetch_bytes", lambda *a, **k: None)
    assert ResearchClient().fetch_bytes("https://example.org/f.pdf") is None


def test_webresearcher_fetch_url_is_removed():
    # The third, unhardened, caller-less raw-urllib fetch method is gone (#34).
    assert not hasattr(WebResearcher, "fetch_url")


# ---------------------------------------------------------------------------
# #120 — CSV-URL connector routes through the guard
# ---------------------------------------------------------------------------


def test_csv_connector_routes_through_safe_fetch_bytes(monkeypatch):
    seen = {}

    def fake_bytes(url, *, max_bytes, timeout):
        seen.update(url=url, max_bytes=max_bytes, timeout=timeout)
        return ("text/csv", b"name,time\nAda,58.21\nBo,59.10\n")

    monkeypatch.setattr(safe_fetch_mod, "safe_fetch_bytes", fake_bytes)

    res = CsvUrlConnector().fetch("prof", {"url": "https://example.org/feed.csv"})

    assert seen["url"] == "https://example.org/feed.csv"
    assert res.rows  # the CSV parsed into rows — behaviour preserved for a valid URL
    assert res.trust.source_url == "https://example.org/feed.csv"


def test_csv_connector_blocked_url_honest_errors(monkeypatch):
    # safe_fetch_bytes returns None for a blocked/failed fetch; the connector must
    # surface that on its existing error path, not silently succeed.
    monkeypatch.setattr(safe_fetch_mod, "safe_fetch_bytes", lambda *a, **k: None)

    with pytest.raises(ConnectorNotConfigured):
        CsvUrlConnector().fetch("prof", {"url": "http://169.254.169.254/latest/meta-data/"})


# ---------------------------------------------------------------------------
# #124 — StaticBackend pins every hop via _pinned_open
# ---------------------------------------------------------------------------


class _FakePinnedResponse:
    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def stream(self, amt=65536, decode_content=None):
        for i in range(0, len(self._body), amt):
            yield self._body[i : i + amt]

    def close(self):
        pass


class _FakePool:
    def close(self):
        pass


def test_static_backend_pins_via_pinned_open(monkeypatch):
    used = {}

    def fake_open(url, *, timeout):
        used["url"] = url
        used["timeout"] = timeout
        body = b"<html><body>1st 2nd 58.21</body></html>"
        return _FakePinnedResponse(200, {"Content-Type": "text/html"}, body), _FakePool()

    monkeypatch.setattr(fetchmod, "_pinned_open", fake_open)

    page = fetchmod.StaticBackend().fetch("https://x.example/r.htm")

    assert page is not None
    assert page.content_type == "text/html"
    assert used["url"] == "https://x.example/r.htm"  # the exact URL was pinned+opened


def test_static_backend_refuses_when_pin_raises(monkeypatch):
    # _pinned_open raises ValueError("unsafe_url") for a refused host — the
    # backend must swallow it and return None (never raise).
    def boom(url, *, timeout):
        raise ValueError("unsafe_url")

    monkeypatch.setattr(fetchmod, "_pinned_open", boom)
    assert fetchmod.StaticBackend().fetch("https://x.example/r.htm") is None


# ---------------------------------------------------------------------------
# #126 — _read_capped has a monotonic total-read deadline (slowloris)
# ---------------------------------------------------------------------------


class _DribbleResponse:
    """A response that never stops yielding — models a slowloris drip."""

    def stream(self, amt=65536, decode_content=None):
        while True:
            yield b"x"


def test_read_capped_aborts_on_total_deadline(monkeypatch):
    # Drive a controlled monotonic clock: the first read sets the deadline (t=0),
    # the next check jumps well past it, so the drip is aborted at once (None) —
    # rather than looping forever under a purely between-bytes socket timeout.
    ticks = iter([0.0] + [10_000.0] * 1000)
    monkeypatch.setattr(fetchmod.time, "monotonic", lambda: next(ticks))

    out = fetchmod._read_capped(_DribbleResponse(), cap=10_000_000, timeout=5.0)

    assert out is None


def test_read_capped_signature_takes_timeout():
    # The deadline is derived from the passed timeout — the third positional
    # parameter must exist (guards against a silent revert to the 2-arg form).
    import inspect

    params = list(inspect.signature(fetchmod._read_capped).parameters)
    assert params == ["response", "cap", "timeout"]
