"""Tests for the optimised PB-discovery gates (Capability 3, PB convergence).

Covers the deterministic gates added to pb_discovery.discover:
- the identity (same-name) gate — a page that parses but isn't about the target
  athlete must never supply a baseline;
- authority-preferring source selection;
- sport-agnostic query building;
- the SSRF guard on the fetcher;
- the budget-gated research tier: OFF (£0) by default, and when enabled it only
  PROPOSES URLs — the deterministic parser still produces every time.

Offline: web search, page fetch, and deep_research are all faked.
"""

from __future__ import annotations

import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

from mediahub.web_research.deep_research import ResearchResult


# --- interpreter stub (fixed PBs; identity is judged on page text) ----------


class _InterpreterStub:
    @staticmethod
    def interpret_document(content, hint: str = "profile_page") -> dict:
        return {
            "pbs": [
                {
                    "event": "100m Freestyle",
                    "course": "LC",
                    "time_canonical": "58.21",
                    "date": "2024-03-15",
                    "meet": "Test Meet",
                    "rank": None,
                    "raw": {"source": "stub"},
                }
            ],
            "confidence": 0.85,
        }


@pytest.fixture(autouse=True)
def _stub_interpreter(monkeypatch):
    stub = MagicMock()
    stub.interpret_document = _InterpreterStub.interpret_document
    monkeypatch.setitem(sys.modules, "interpreter", stub)
    for k in ("MEDIAHUB_PB_RESEARCH_LIMIT", "MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS"):
        monkeypatch.delenv(k, raising=False)
    yield


def _page(name: str) -> bytes:
    return (
        f"<html><body><h1>{name} — City SC</h1>"
        f"<table><tr><td>100m Freestyle</td><td>58.21</td></tr></table>"
        f"</body></html>"
    ).encode("utf-8")


def _result(url, title="r", snippet="s", source="duckduckgo"):
    from mediahub.web_research.search import SearchResult

    return SearchResult(url=url, title=title, snippet=snippet, source=source)


def _tmp_roots(tmp_path):
    def _root():
        r = tmp_path / "discovered"
        r.mkdir(parents=True, exist_ok=True)
        return r

    return _root


def _patches(tmp_path):
    root = _tmp_roots(tmp_path)
    return (
        patch("mediahub.context_engine.research.WebResearcher.search"),
        patch("mediahub.pb_discovery.fetch_profile._fetch_raw"),
        patch("mediahub.pb_discovery.cache._discovered_root", side_effect=root),
        patch("mediahub.context_engine.cache._discovered_root", side_effect=root),
        patch(
            "mediahub.context_engine.trust._ledger_path",
            return_value=tmp_path / "ledger.jsonl",
        ),
    )


# --- identity gate ----------------------------------------------------------


def test_identity_gate_rejects_wrong_swimmer(tmp_path):
    from mediahub.pb_discovery.discover import discover_swimmer_pbs

    s, f, r, cr, lg = _patches(tmp_path)
    with s as search, f as fetch, r, cr, lg:
        search.return_value = [_result("https://db.example/p/someone")]
        # Page parses (stub) but is about a DIFFERENT person.
        fetch.return_value = _page("John Smith")
        res = discover_swimmer_pbs(name="Jane Doe", club="City SC", run_id=f"r-{uuid.uuid4()}")
    # Tried the source, but it was identity-rejected -> no baseline.
    assert len(res.sources_tried) >= 1
    assert res.chosen_source is None
    assert res.pbs == []


def test_identity_gate_accepts_right_swimmer(tmp_path):
    from mediahub.pb_discovery.discover import discover_swimmer_pbs

    s, f, r, cr, lg = _patches(tmp_path)
    with s as search, f as fetch, r, cr, lg:
        search.return_value = [_result("https://db.example/p/jane")]
        fetch.return_value = _page("Jane Doe")
        res = discover_swimmer_pbs(name="Jane Doe", club="City SC", run_id=f"r-{uuid.uuid4()}")
    assert res.chosen_source is not None
    assert len(res.pbs) == 1
    assert res.pbs[0].time_canonical == "58.21"


# --- authority-preferring selection -----------------------------------------


def test_authority_source_is_preferred(tmp_path):
    from mediahub.pb_discovery.discover import discover_swimmer_pbs

    auth_url = "https://authority.example/jane"
    blog_url = "https://blog.example/jane"
    s, f, r, cr, lg = _patches(tmp_path)
    with (
        s as search,
        f as fetch,
        r,
        cr,
        lg,
        patch(
            "mediahub.pb_discovery.discover._is_authority",
            side_effect=lambda u: u == auth_url,
        ),
    ):
        search.return_value = [_result(blog_url), _result(auth_url)]
        fetch.side_effect = lambda url, timeout=12: _page("Jane Doe")
        res = discover_swimmer_pbs(name="Jane Doe", club="City SC", run_id=f"r-{uuid.uuid4()}")
    # Both pages are about Jane and parse equally; the authority wins.
    assert res.chosen_source is not None
    assert res.chosen_source.url == auth_url


# --- sport-agnostic queries -------------------------------------------------


def test_queries_are_sport_agnostic():
    from mediahub.pb_discovery.discover import _athlete_word, _build_queries

    assert _athlete_word("swimming") == "swimmer"
    assert _athlete_word("athletics") == "athlete"
    assert _athlete_word("cycling") == "cyclist"
    swim = _build_queries("Jane Doe", "City SC", None)
    assert "swimming" in swim[0] and "swimmer" in swim[1]
    ath = _build_queries("Jane Doe", "City AC", None, "athletics")
    assert "athletics" in ath[0] and "athlete" in ath[1]


# --- SSRF guard on the fetcher ----------------------------------------------


def test_fetcher_blocks_internal_addresses():
    from mediahub.pb_discovery.fetch_profile import _fetch_raw

    # Cloud-metadata, loopback, and RFC-1918 must be refused before any socket.
    assert _fetch_raw("http://169.254.169.254/latest/meta-data/") is None
    assert _fetch_raw("http://127.0.0.1:8080/") is None
    assert _fetch_raw("http://10.1.2.3/profile") is None


# --- budget-gated research tier ---------------------------------------------


def test_research_tier_off_by_default(tmp_path):
    from mediahub.pb_discovery.discover import discover_swimmer_pbs

    s, f, r, cr, lg = _patches(tmp_path)
    spy = MagicMock()
    with (
        s as search,
        f as fetch,
        r,
        cr,
        lg,
        patch("mediahub.web_research.deep_research.deep_research", spy),
    ):
        # Deterministic pass finds a page that isn't the target -> no baseline.
        search.return_value = [_result("https://db.example/p/someone")]
        fetch.return_value = _page("John Smith")
        res = discover_swimmer_pbs(name="Jane Doe", club="City SC", run_id=f"r-{uuid.uuid4()}")
    # £0 default: research must NOT have been invoked.
    spy.assert_not_called()
    assert res.pbs == []


def test_research_tier_proposes_urls_when_enabled(tmp_path, monkeypatch):
    from mediahub.pb_discovery.discover import discover_swimmer_pbs

    monkeypatch.setenv("MEDIAHUB_PB_RESEARCH_LIMIT", "2")
    found_url = "https://authority.example/jane-doe"

    def _fake_deep_research(question, **_):
        # Model PROPOSES URLs (+ a prose answer that must be ignored as data).
        return ResearchResult(
            answer="Jane's 100m Free PB is 9.99 (do not trust this number).",
            sources=[found_url],
            authority_sources=[found_url],
            complete=True,
            rounds=1,
            tool_calls=2,
        )

    def _fake_fetch(url, timeout=12):
        # Only the researched URL is actually about Jane.
        return _page("Jane Doe") if url == found_url else _page("John Smith")

    s, f, r, cr, lg = _patches(tmp_path)
    with (
        s as search,
        f as fetch,
        r,
        cr,
        lg,
        patch(
            "mediahub.web_research.deep_research.deep_research", side_effect=_fake_deep_research
        ) as spy,
    ):
        search.return_value = [_result("https://db.example/p/someone")]
        fetch.side_effect = _fake_fetch
        res = discover_swimmer_pbs(name="Jane Doe", club="City SC", run_id=f"r-{uuid.uuid4()}")

    spy.assert_called_once()
    # The researched URL supplied the baseline...
    assert res.chosen_source is not None
    assert res.chosen_source.url == found_url
    # ...and the TIME came from the deterministic parser, NOT the model's prose.
    assert len(res.pbs) == 1
    assert res.pbs[0].time_canonical == "58.21"
    assert all(pb.time_canonical != "9.99" for pb in res.pbs)


def test_fetcher_fails_closed_when_guard_errors(monkeypatch):
    """If the SSRF guard itself raises, the fetch must be refused — never
    performed unchecked (the guard previously failed open via except: pass)."""
    import urllib.request

    from mediahub.pb_discovery import fetch_profile as fp
    import mediahub.web_research.safe_fetch as sf

    def _guard_boom(url):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(sf, "is_url_safe", _guard_boom)

    opened = []

    def _no_network(*handlers):
        opener = MagicMock()
        opener.open.side_effect = lambda *a, **k: opened.append(a) or None
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", _no_network)
    assert fp._fetch_raw("https://results.example/profile") is None
    assert not opened, "no connection may be opened when the guard errors"


def test_fetcher_revalidates_every_redirect_hop(monkeypatch):
    """A public host 302-ing to a cloud-metadata address must be refused: each
    redirect hop goes back through the SSRF guard (urllib's default auto-follow
    bypassed it)."""
    import email.message
    import urllib.error
    import urllib.request

    from mediahub.pb_discovery import fetch_profile as fp
    import mediahub.web_research.safe_fetch as sf

    checked = []

    def _guard(url):
        checked.append(url)
        return "169.254.169.254" not in url

    monkeypatch.setattr(sf, "is_url_safe", _guard)

    hdrs = email.message.Message()
    hdrs["Location"] = "http://169.254.169.254/latest/meta-data/"
    redirect = urllib.error.HTTPError(
        "https://results.example/profile", 302, "Found", hdrs, None
    )

    opener = MagicMock()
    opener.open.side_effect = redirect

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: opener)
    assert fp._fetch_raw("https://results.example/profile") is None
    # The metadata hop was validated (and refused) — not silently followed.
    assert any("169.254.169.254" in u for u in checked)
    assert opener.open.call_count == 1
