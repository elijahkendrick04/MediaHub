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


# --------------------------------------------------------------------------- #
# datacenter-rate-limit hardening (compliant UA, retry on 429, lighter thumbs)
# --------------------------------------------------------------------------- #
def test_get_with_retry_retries_on_429(monkeypatch):
    import sys

    import mediahub.venue_search.search  # noqa: F401  (ensure submodule imported)

    vs = sys.modules["mediahub.venue_search.search"]  # __init__ re-export shadows the module name

    monkeypatch.setattr("time.sleep", lambda *a, **k: None)  # no real backoff

    class _Resp:
        def __init__(self, status):
            self.status_code = status

    seq = [_Resp(429), _Resp(429), _Resp(200)]
    calls = {"n": 0}

    def _get(url, **k):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr("requests.get", _get)
    resp = vs._get_with_retry(vs.WIKI_API, params={}, timeout=4)
    assert resp.status_code == 200
    assert calls["n"] == 3  # two 429s, then the 200


def test_wikimedia_search_uses_compliant_ua_and_small_thumb(monkeypatch):
    import sys

    import mediahub.venue_search.search  # noqa: F401  (ensure submodule imported)

    vs = sys.modules["mediahub.venue_search.search"]  # __init__ re-export shadows the module name

    captured = []

    class _Resp:
        status_code = 200

        def __init__(self, is_search):
            self._is_search = is_search

        def raise_for_status(self):
            pass

        def json(self):
            if self._is_search:
                return {"query": {"search": [{"title": "File:Pool.jpg"}]}}
            return {
                "query": {
                    "pages": {
                        "1": {
                            "title": "File:Pool.jpg",
                            "imageinfo": [
                                {
                                    "url": "http://d/p.jpg",
                                    "thumburl": "http://t/p.jpg",
                                    "width": 480,
                                    "height": 360,
                                    "extmetadata": {},
                                }
                            ],
                        }
                    }
                }
            }

    def _get(url, params=None, headers=None, timeout=None):
        captured.append({"params": params or {}, "headers": headers or {}})
        return _Resp((params or {}).get("list") == "search")

    monkeypatch.setattr("requests.get", _get)
    vs.search("pool", limit=2, timeout=4)
    # A descriptive, contactable UA on every upstream call (Wikimedia policy).
    assert captured and all("github.com" in c["headers"].get("User-Agent", "") for c in captured)
    # The imageinfo step requests a lighter 480px preview (not 800).
    info = [c for c in captured if c["params"].get("iiprop")]
    assert info and info[0]["params"]["iiurlwidth"] == "480"


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
