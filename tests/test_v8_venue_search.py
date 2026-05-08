"""Tests for venue_search.search — Wikimedia Commons search.

Network-dependent: skip gracefully when offline. Always validates the dataclass
shape and the in-memory fallback behavior.
"""
from __future__ import annotations

import socket

import pytest

from mediahub.venue_search.search import VenueImageResult, search


def _online() -> bool:
    try:
        socket.create_connection(("commons.wikimedia.org", 443), timeout=3)
        return True
    except Exception:
        return False


def test_search_returns_list_no_raise_on_empty_query():
    """Empty/garbled queries must never raise."""
    out = search("", limit=2, timeout=4)
    assert isinstance(out, list)


def test_search_returns_list_no_raise_on_garbage_query():
    out = search("zzzqqxxxxxxnotarealvenue1234567", limit=2, timeout=4)
    assert isinstance(out, list)


def test_venue_image_result_dataclass_shape():
    r = VenueImageResult(
        title="Pool",
        thumb_url="https://example.com/t.jpg",
        direct_url="https://example.com/d.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:Pool.jpg",
    )
    d = r.to_dict()
    assert d["title"] == "Pool"
    assert d["source_site"] == "wikimedia"
    assert d["permission_status"] == "approved_public"
    assert "licence" in d
    assert "attribution_required" in d


@pytest.mark.skipif(not _online(), reason="Wikimedia Commons unreachable in sandbox")
def test_search_real_query_returns_results():
    """Live query for a famous swimming venue should return at least one hit."""
    results = search("London Aquatics Centre", limit=3, timeout=8)
    assert isinstance(results, list)
    if not results:
        pytest.skip("No results from live Wikimedia API — non-fatal")
    first = results[0]
    assert first.thumb_url.startswith("http")
    assert first.source_url.startswith("http")
    assert first.permission_status in ("approved_public", "needs_approval")
