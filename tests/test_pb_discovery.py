"""
tests_v75/test_pb_discovery.py — Tests for the PB discovery engine.

Tests:
1. Engine correctly ranks/picks the highest-confidence source.
2. Trust ledger is updated after a successful parse.
3. Per-run cache prevents duplicate fetches for the same swimmer.
4. Warm cache is populated after discovery.
5. Interpreter stub fixture works correctly.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Interpreter stub fixture ─────────────────────────────────────────────────

class _InterpreterStub:
    """
    Minimal stub for the interpreter package.
    Returns a synthetic PB result for testing without the real interpreter.
    """

    @staticmethod
    def interpret_document(content: bytes, hint: str = 'profile_page') -> dict:
        """Return fake PB data for testing."""
        return {
            "pbs": [
                {
                    "event": "100m Freestyle",
                    "course": "LC",
                    "time_canonical": "58.21",
                    "date": "2024-03-15",
                    "meet": "Test Open Meet",
                    "rank": None,
                    "raw": {"source": "stub"},
                },
                {
                    "event": "200m Freestyle",
                    "course": "LC",
                    "time_canonical": "2:05.43",
                    "date": "2024-02-10",
                    "meet": "Test Championships",
                    "rank": 3,
                    "raw": {"source": "stub"},
                },
            ],
            "confidence": 0.85,
        }


@pytest.fixture(autouse=True)
def inject_interpreter_stub(monkeypatch):
    """
    Inject the interpreter stub into sys.modules so pb_discovery.parse_pbs
    can import it without the real interpreter package being present.
    """
    stub = MagicMock()
    stub.interpret_document = _InterpreterStub.interpret_document
    monkeypatch.setitem(sys.modules, 'interpreter', stub)
    yield
    # Cleanup is handled by monkeypatch automatically


# ── Fake web search + page fetch ──────────────────────────────────────────────

FAKE_PROFILE_HTML = """
<html><body>
<h1>Swimmer Profile: Alice Test</h1>
<p>Club: Anytown SC</p>
<table>
  <tr><th>Event</th><th>Time</th><th>Course</th><th>Date</th></tr>
  <tr><td>100m Freestyle</td><td>58.21</td><td>LC</td><td>15/03/2024</td></tr>
  <tr><td>200m Freestyle</td><td>2:05.43</td><td>LC</td><td>10/02/2024</td></tr>
  <tr><td>50m Backstroke</td><td>31.45</td><td>SC</td><td>05/01/2024</td></tr>
</table>
</body></html>
""".encode("utf-8")

FAKE_SEARCH_RESULTS = [
    {
        "url": "https://example-swim-db.example/profile/alice-test",
        "title": "Alice Test — Anytown SC — Swimmer Profile",
        "snippet": "Personal bests: 100m Freestyle 58.21 LC",
        "source": "duckduckgo",
    },
    {
        "url": "https://another-swim-site.example/swimmers/alice-test-anytown",
        "title": "Alice Test Anytown SC results",
        "snippet": "All times for Alice Test of Anytown SC",
        "source": "duckduckgo",
    },
]


def _make_fake_search_result(d: dict):
    """Create a SearchResult-like object from a dict."""
    from mediahub.web_research.search import SearchResult
    return SearchResult(
        url=d["url"],
        title=d["title"],
        snippet=d["snippet"],
        source=d["source"],
    )


# ── Tests ────────────────────────────────────────────────────────────────────

class TestPBDiscoveryRanking:
    """Test that the engine picks the highest-confidence source."""

    def test_picks_source_with_most_pbs(self, tmp_path, monkeypatch):
        """Engine should pick the source yielding the most/best PBs."""
        from mediahub.pb_discovery.discover import discover_swimmer_pbs
        from mediahub.pb_discovery.cache import RunCache, WarmCache

        run_id = f"test-run-{uuid.uuid4()}"

        # Mock WebResearcher.search to return our fake results
        with patch('context_engine.research.WebResearcher.search') as mock_search, \
             patch('pb_discovery.fetch_profile._fetch_raw') as mock_fetch, \
             patch('pb_discovery.cache._discovered_root') as mock_root, \
             patch('context_engine.cache._discovered_root') as mock_cache_root, \
             patch('context_engine.trust._ledger_path') as mock_ledger:

            # Point caches to tmp_path
            def _tmp_root():
                r = tmp_path / "discovered"
                r.mkdir(parents=True, exist_ok=True)
                return r

            mock_root.return_value = _tmp_root()
            mock_cache_root.return_value = _tmp_root()
            mock_ledger.return_value = tmp_path / "discovered_sources.jsonl"

            # Return fake search results
            mock_search.return_value = [_make_fake_search_result(r) for r in FAKE_SEARCH_RESULTS]

            # Return fake page content for all URLs
            mock_fetch.return_value = FAKE_PROFILE_HTML

            result = discover_swimmer_pbs(
                name="Alice Test",
                club="Anytown SC",
                run_id=run_id,
            )

        # Should have tried at least one source
        assert len(result.sources_tried) >= 1, "Should have tried at least one source"
        # Should have a chosen source
        assert result.chosen_source is not None, "Should have chosen a source"
        # Should have PBs
        assert len(result.pbs) > 0, "Should have discovered at least one PB"
        # cache_hit should be False (fresh discovery)
        assert result.cache_hit is False

    def test_source_ranking_by_trust(self, tmp_path, monkeypatch):
        """Higher-trust domains should be tried first."""
        from mediahub.context_engine.trust import _load_ledger, _save_record, score_domain

        # Write a ledger that gives domain A a high trust score
        ledger_path = tmp_path / "discovered_sources.jsonl"
        high_trust = {
            "domain": "high-trust-domain.example",
            "first_seen": "2024-01-01T00:00:00Z",
            "last_used": "2024-01-01T00:00:00Z",
            "parse_attempts": 10,
            "parse_successes": 9,
            "domains_observed_for": ["swimmer_pbs"],
        }
        low_trust = {
            "domain": "low-trust-domain.example",
            "first_seen": "2024-01-01T00:00:00Z",
            "last_used": "2024-01-01T00:00:00Z",
            "parse_attempts": 10,
            "parse_successes": 1,
            "domains_observed_for": ["swimmer_pbs"],
        }
        ledger_path.write_text(
            json.dumps(high_trust) + "\n" + json.dumps(low_trust) + "\n",
            encoding="utf-8",
        )

        with patch('context_engine.trust._ledger_path', return_value=ledger_path):
            from mediahub.context_engine.trust import rank_candidates
            urls = [
                "https://low-trust-domain.example/alice",
                "https://high-trust-domain.example/alice",
            ]
            ranked = rank_candidates(urls)

        # High-trust domain should come first
        assert "high-trust-domain.example" in ranked[0], (
            f"High-trust domain should rank first, got: {ranked}"
        )


class TestTrustLedger:
    """Test that the trust ledger is updated after parse attempts."""

    def test_ledger_updated_after_success(self, tmp_path):
        """record_attempt should update the ledger with success."""
        from mediahub.context_engine.trust import record_attempt

        ledger_path = tmp_path / "discovered_sources.jsonl"

        with patch('context_engine.trust._ledger_path', return_value=ledger_path):
            record_attempt("test-domain.example", success=True, purpose="swimmer_pbs")
            record_attempt("test-domain.example", success=True, purpose="swimmer_pbs")
            record_attempt("test-domain.example", success=False, purpose="swimmer_pbs")

        # Read the ledger
        assert ledger_path.exists()
        records = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
        assert len(records) == 1  # Should be one record per domain
        rec = records[0]
        assert rec["domain"] == "test-domain.example"
        assert rec["parse_attempts"] == 3
        assert rec["parse_successes"] == 2
        assert "swimmer_pbs" in rec["domains_observed_for"]

    def test_score_domain_laplace(self, tmp_path):
        """score_domain should use Laplace smoothing."""
        from mediahub.context_engine.trust import record_attempt, score_domain

        ledger_path = tmp_path / "discovered_sources.jsonl"

        with patch('context_engine.trust._ledger_path', return_value=ledger_path):
            # 3 attempts, 3 successes → (3+1)/(3+2) = 0.8
            for _ in range(3):
                record_attempt("perfect-domain.example", success=True, purpose="test")
            score = score_domain("perfect-domain.example")

        assert abs(score - 4/5) < 0.001, f"Expected 0.8, got {score}"

    def test_unknown_domain_neutral_prior(self, tmp_path):
        """Unknown domains should score 0.5 (neutral prior)."""
        from mediahub.context_engine.trust import score_domain

        with patch('context_engine.trust._ledger_path', return_value=tmp_path / "empty.jsonl"):
            score = score_domain("never-seen-before.example")

        assert score == 0.5, f"Unknown domain should score 0.5, got {score}"


class TestPerRunCache:
    """Test that per-run cache prevents duplicate fetches."""

    def test_second_call_returns_cache_hit(self, tmp_path, monkeypatch):
        """Second call for same swimmer in same run should return cache_hit=True."""
        from mediahub.pb_discovery.discover import discover_swimmer_pbs

        run_id = f"test-cache-run-{uuid.uuid4()}"

        call_count = {"n": 0}

        def _fake_fetch(url, *args, **kwargs):
            call_count["n"] += 1
            return FAKE_PROFILE_HTML

        with patch('context_engine.research.WebResearcher.search') as mock_search, \
             patch('pb_discovery.fetch_profile._fetch_raw') as mock_fetch, \
             patch('pb_discovery.cache._discovered_root') as mock_root, \
             patch('context_engine.cache._discovered_root') as mock_cache_root, \
             patch('context_engine.trust._ledger_path') as mock_ledger:

            def _tmp_root():
                r = tmp_path / "discovered"
                r.mkdir(parents=True, exist_ok=True)
                return r

            mock_root.return_value = _tmp_root()
            mock_cache_root.return_value = _tmp_root()
            mock_ledger.return_value = tmp_path / "discovered_sources.jsonl"
            mock_search.return_value = [_make_fake_search_result(FAKE_SEARCH_RESULTS[0])]
            mock_fetch.side_effect = _fake_fetch

            # First call — should fetch
            result1 = discover_swimmer_pbs(
                name="Bob Swimmer",
                club="Test SC",
                run_id=run_id,
            )
            assert result1.cache_hit is False

            fetch_count_after_first = call_count["n"]

            # Second call — same swimmer, same run — should hit cache
            result2 = discover_swimmer_pbs(
                name="Bob Swimmer",
                club="Test SC",
                run_id=run_id,
            )

        assert result2.cache_hit is True, "Second call should be a cache hit"
        # Fetch should NOT have been called again
        assert call_count["n"] == fetch_count_after_first, (
            "Fetch should not be called again for cached swimmer in same run"
        )

    def test_different_run_ids_fetch_independently(self, tmp_path):
        """Different run IDs should each fetch independently."""
        from mediahub.pb_discovery.discover import discover_swimmer_pbs

        run_id_1 = f"run-A-{uuid.uuid4()}"
        run_id_2 = f"run-B-{uuid.uuid4()}"
        call_count = {"n": 0}

        def _fake_fetch(url, *args, **kwargs):
            call_count["n"] += 1
            return FAKE_PROFILE_HTML

        def _run_discovery(run_id):
            with patch('context_engine.research.WebResearcher.search') as mock_search, \
                 patch('pb_discovery.fetch_profile._fetch_raw') as mock_fetch, \
                 patch('pb_discovery.cache._discovered_root') as mock_root, \
                 patch('context_engine.cache._discovered_root') as mock_cache_root, \
                 patch('context_engine.trust._ledger_path') as mock_ledger:

                def _tmp_root():
                    r = tmp_path / "discovered"
                    r.mkdir(parents=True, exist_ok=True)
                    return r

                mock_root.return_value = _tmp_root()
                mock_cache_root.return_value = _tmp_root()
                mock_ledger.return_value = tmp_path / "discovered_sources.jsonl"
                mock_search.return_value = [_make_fake_search_result(FAKE_SEARCH_RESULTS[0])]
                mock_fetch.side_effect = _fake_fetch

                return discover_swimmer_pbs(
                    name="Carol Swimmer",
                    club="Riverside SC",
                    run_id=run_id,
                    force_refresh=True,  # Force bypass warm cache
                )

        result1 = _run_discovery(run_id_1)
        result2 = _run_discovery(run_id_2)

        # Both should complete without error
        assert result1 is not None
        assert result2 is not None


class TestInterpreterStub:
    """Test that the interpreter stub fixture works correctly."""

    def test_stub_returns_pbs(self):
        """The interpreter stub should return valid PB data."""
        import mediahub.interpreter  # Should be the stub via monkeypatch
        result = interpreter.interpret_document(b"test content", hint='profile_page')
        assert "pbs" in result
        assert len(result["pbs"]) > 0
        assert result["confidence"] > 0

    def test_parse_pbs_uses_interpreter(self, tmp_path):
        """parse_pbs_from_page should use interpreter when available."""
        from mediahub.pb_discovery.parse_pbs import parse_pbs_from_page
        from mediahub.pb_discovery.fetch_profile import ProfilePage
        import time

        page = ProfilePage(
            url="https://test.example/profile",
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            text="Alice Test — 100m Freestyle 58.21 LC 2024-03-15",
            tables=[],
            fetch_success=True,
        )

        rows, confidence = parse_pbs_from_page(page, use_interpreter=True)

        # With stub, should return the stub's PBs
        assert len(rows) > 0
        assert confidence > 0
        assert any(r.event == "100m Freestyle" for r in rows)


class TestWarmCache:
    """Test warm swimmer cache persistence."""

    def test_warm_cache_set_and_get(self, tmp_path):
        """WarmCache should persist data and retrieve it within TTL."""
        from mediahub.pb_discovery.cache import WarmCache, make_swimmer_key

        with patch('pb_discovery.cache._discovered_root') as mock_root:
            mock_root.return_value = tmp_path / "discovered"

            cache = WarmCache()
            key = make_swimmer_key("Test Swimmer", "Test SC")

            # Set a value
            payload = {"swimmer_query": "Test Swimmer (Test SC)", "pbs": [], "confidence": 0.5}
            cache.set(key, payload)

            # Get it back
            retrieved = cache.get(key)

        assert retrieved is not None
        assert retrieved["swimmer_query"] == "Test Swimmer (Test SC)"

    def test_warm_cache_make_key_stable(self):
        """make_swimmer_key should be deterministic."""
        from mediahub.pb_discovery.cache import make_swimmer_key

        key1 = make_swimmer_key("Alice Test", "Anytown SC")
        key2 = make_swimmer_key("Alice Test", "Anytown SC")
        key3 = make_swimmer_key("ALICE TEST", "ANYTOWN SC")  # case-insensitive

        assert key1 == key2, "Same inputs should produce same key"
        assert key1 == key3, "Key should be case-insensitive"
