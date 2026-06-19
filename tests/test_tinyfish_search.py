"""TinyFish search backend (free tier) — the preferred backend when configured.

Mocks the HTTP call (no live network). Verifies the JSON → SearchResult parse,
that ``search()`` prefers TinyFish when ``TINYFISH_API_KEY`` is set, and that it
is a clean no-op (skipped) when the key is unset.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mediahub.web_research import search as search_mod  # noqa: E402


class _FakeResp:
    def __init__(self, payload: dict):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_TINYFISH_PAYLOAD = {
    "results": [
        {"position": 1, "site_name": "swimrankings", "title": "Effy Johnson — profile",
         "snippet": "Personal bests for Effy Johnson", "url": "https://example.org/effy"},
        {"position": 2, "title": "Brighton Dolphins results", "snippet": "Club results",
         "url": "https://example.org/club"},
        {"position": 3, "title": "junk", "snippet": "no url here"},  # dropped (no http url)
    ]
}


def test_parses_tinyfish_json(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-test")
    monkeypatch.setattr(search_mod.urllib.request, "urlopen", lambda *a, **k: _FakeResp(_TINYFISH_PAYLOAD))
    out = search_mod.WebResearcher()._search_tinyfish("Effy Johnson swimmer", 5)
    assert [r.url for r in out] == ["https://example.org/effy", "https://example.org/club"]
    assert out[0].source == "tinyfish"
    assert out[0].title == "Effy Johnson — profile"


def test_search_prefers_tinyfish_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(search_mod, "_CACHE_DIR", None, raising=False)
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-test")
    monkeypatch.delenv("MEDIAHUB_SEARCH_ENDPOINT", raising=False)

    calls = {"tf": 0, "ddg": 0}

    def _fake_urlopen(*a, **k):
        calls["tf"] += 1
        return _FakeResp(_TINYFISH_PAYLOAD)

    monkeypatch.setattr(search_mod.urllib.request, "urlopen", _fake_urlopen)
    # DDG must NOT be reached when TinyFish answers.
    monkeypatch.setattr(
        search_mod.WebResearcher, "_search_duckduckgo",
        lambda self, q, n: calls.__setitem__("ddg", calls["ddg"] + 1) or [],
    )

    res = search_mod.WebResearcher().search("a unique query xyzzy", num=5)
    assert res and res[0].source == "tinyfish"
    assert calls["tf"] >= 1 and calls["ddg"] == 0


def test_no_key_is_skipped(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    assert search_mod._tinyfish_key() is None
    assert search_mod.WebResearcher()._search_tinyfish("q", 5) == []
