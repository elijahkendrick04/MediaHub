"""PB discovery resilience: cache honesty, search politeness, run guards.

Covers the failure modes that made a real meet-recap run "take a while and
then not work":

* a throttled/offline run's empty results must not poison the warm cache for
  7 days (short TTL for empty payloads);
* the legacy doubled ``data/data/discovered`` cache root migrates once to
  ``<DATA_DIR>/discovered``;
* DuckDuckGo throttling gets one polite retry then a global cooldown instead
  of a burst of doomed requests;
* the discovery phase honours ``force_refresh`` (the configure form's
  "use PB cache" toggle), a wall-clock budget, and emits heartbeat lines so
  the stale-run watchdog can tell slow from dead.
"""

from __future__ import annotations

import json
import time
import urllib.error
from types import SimpleNamespace as NS
from unittest.mock import patch

from mediahub.pb_discovery.cache import WarmCache, make_swimmer_key
from mediahub.pb_discovery.discover import PBDiscovery
from mediahub.pipeline.pipeline_v4 import _enrich_pbs_via_discovery


# ---------------------------------------------------------------------------
# Warm cache: empty results expire fast
# ---------------------------------------------------------------------------


class TestWarmCacheEmptyTtl:
    def _aged(self, cache: WarmCache, key: str, age_s: float) -> None:
        p = cache._base / f"{key}.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["_saved_at_ts"] = time.time() - age_s
        p.write_text(json.dumps(data), encoding="utf-8")

    def test_empty_payload_expires_after_short_ttl(self, tmp_path):
        with patch(
            "mediahub.pb_discovery.cache._discovered_root",
            return_value=tmp_path / "discovered",
        ):
            cache = WarmCache()
            key = make_swimmer_key("Empty Result", "Test SC")
            cache.set(key, {"swimmer_query": "x", "pbs": [], "confidence": 0.0})
            assert cache.get(key) is not None, "fresh empty result is still served"

            self._aged(cache, key, WarmCache.EMPTY_TTL + 60)
            assert cache.get(key) is None, (
                "an empty discovery must expire after EMPTY_TTL — a throttled "
                "run must not poison the swimmer's lookup for a week"
            )

    def test_non_empty_payload_keeps_the_long_ttl(self, tmp_path):
        with patch(
            "mediahub.pb_discovery.cache._discovered_root",
            return_value=tmp_path / "discovered",
        ):
            cache = WarmCache()
            key = make_swimmer_key("Full Result", "Test SC")
            cache.set(key, {"swimmer_query": "x", "pbs": [{"event": "100m Freestyle"}]})
            self._aged(cache, key, WarmCache.EMPTY_TTL + 60)
            assert cache.get(key) is not None, "found PBs stay cached past EMPTY_TTL"
            self._aged(cache, key, WarmCache.TTL + 60)
            assert cache.get(key) is None, "the 7-day TTL still applies"


# ---------------------------------------------------------------------------
# Cache root: the doubled `data` segment migrates once
# ---------------------------------------------------------------------------


class TestDiscoveredRootMigration:
    def test_legacy_doubled_data_path_is_renamed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        legacy = tmp_path / "data" / "discovered" / "swimmers"
        legacy.mkdir(parents=True)
        (legacy / "abc.json").write_text("{}", encoding="utf-8")

        from mediahub.context_engine.cache import _discovered_root

        root = _discovered_root()
        assert root == tmp_path / "discovered"
        assert (root / "swimmers" / "abc.json").exists(), "warm cache survives the move"
        assert not (tmp_path / "data" / "discovered").exists()

    def test_fresh_environment_uses_canonical_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.context_engine.cache import _discovered_root

        assert _discovered_root() == tmp_path / "discovered"

    def test_pb_discovery_cache_shares_the_same_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.pb_discovery.cache import _discovered_root as pb_root
        from mediahub.context_engine.cache import _discovered_root as ctx_root

        assert pb_root() == ctx_root()


# ---------------------------------------------------------------------------
# DuckDuckGo politeness: retry once, then cool down
# ---------------------------------------------------------------------------


def _throttle_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://html.duckduckgo.com/html/", code=code, msg="throttled", hdrs=None, fp=None
    )


class TestDdgThrottlePoliteness:
    def test_throttle_retries_once_then_cools_down(self, monkeypatch):
        from mediahub.web_research import search as search_mod

        calls = {"n": 0}

        def fake_request(self, query, num):
            calls["n"] += 1
            raise _throttle_error(429)

        monkeypatch.setattr(search_mod.WebResearcher, "_ddg_request", fake_request)
        monkeypatch.setattr(search_mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(search_mod, "_ddg_cooldown_until", 0.0)

        wr = search_mod.WebResearcher()
        assert wr._search_duckduckgo("query one", 5) == []
        assert calls["n"] == 2, "one initial attempt + exactly one polite retry"

        # Cooldown is now active: the next search must skip DDG entirely
        # rather than hammer a server that already said no.
        assert wr._search_duckduckgo("query two", 5) == []
        assert calls["n"] == 2

    def test_non_throttle_http_error_propagates(self, monkeypatch):
        from mediahub.web_research import search as search_mod

        def fake_request(self, query, num):
            raise _throttle_error(500)

        monkeypatch.setattr(search_mod.WebResearcher, "_ddg_request", fake_request)
        monkeypatch.setattr(search_mod, "_ddg_cooldown_until", 0.0)

        wr = search_mod.WebResearcher()
        try:
            wr._search_duckduckgo("query", 5)
            raised = False
        except urllib.error.HTTPError:
            raised = True
        assert raised, "a 500 is not a throttle — it must propagate to search()'s fallback"

    def test_single_throttle_then_success_recovers(self, monkeypatch):
        from mediahub.web_research import search as search_mod

        calls = {"n": 0}
        hit = search_mod.SearchResult(url="https://x", title="X", snippet="s", source="duckduckgo")

        def fake_request(self, query, num):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _throttle_error(403)
            return [hit]

        monkeypatch.setattr(search_mod.WebResearcher, "_ddg_request", fake_request)
        monkeypatch.setattr(search_mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(search_mod, "_ddg_cooldown_until", 0.0)

        wr = search_mod.WebResearcher()
        out = wr._search_duckduckgo("query", 5)
        assert out == [hit], "a transient throttle is absorbed by the retry"
        assert not search_mod._ddg_in_cooldown()


# ---------------------------------------------------------------------------
# Discovery phase guards: force_refresh, budget, heartbeat
# ---------------------------------------------------------------------------


def _mini_meet(n: int = 3):
    names = [("A", "One"), ("B", "Two"), ("C", "Three")][:n]
    return NS(
        swimmers={f"k{i + 1}": NS(first_name=f, last_name=l) for i, (f, l) in enumerate(names)}
    )


class TestEnrichPbsGuards:
    def test_force_refresh_flows_into_discovery(self, monkeypatch):
        monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
        monkeypatch.delenv("MEDIAHUB_PB_FETCH_BUDGET_S", raising=False)
        seen: list[bool] = []

        def fake_discover(*, name, club, run_id, force_refresh=False):
            seen.append(force_refresh)
            return PBDiscovery(swimmer_query=name)

        monkeypatch.setattr("mediahub.pb_discovery.discover_swimmer_pbs", fake_discover)
        snaps, exceeded = _enrich_pbs_via_discovery(
            meet=_mini_meet(1),
            our_swimmer_keys={"k1"},
            club_name="Club",
            run_id="r-force",
            step=lambda m: None,
            force_refresh=True,
        )
        assert seen == [True], "use_pb_cache=False must reach discovery as force_refresh=True"
        assert exceeded is False
        assert set(snaps) == {"k1"}

    def test_serial_budget_skips_remaining_swimmers(self, monkeypatch):
        monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
        monkeypatch.setenv("MEDIAHUB_PB_FETCH_BUDGET_S", "0.05")

        def slow_discover(*, name, club, run_id, force_refresh=False):
            time.sleep(0.08)
            return PBDiscovery(swimmer_query=name)

        monkeypatch.setattr("mediahub.pb_discovery.discover_swimmer_pbs", slow_discover)
        steps: list[str] = []
        snaps, exceeded = _enrich_pbs_via_discovery(
            meet=_mini_meet(3),
            our_swimmer_keys={"k1", "k2", "k3"},
            club_name="Club",
            run_id="r-budget",
            step=steps.append,
        )
        assert exceeded is True
        assert len(snaps) < 3, "swimmers past the budget are skipped, not researched"
        assert any("budget" in s.lower() for s in steps), "the skip is surfaced in the log"

    def test_parallel_budget_cancels_queued_lookups(self, monkeypatch):
        monkeypatch.delenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", raising=False)
        monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_WORKERS", "1")
        monkeypatch.setenv("MEDIAHUB_PB_FETCH_BUDGET_S", "0.1")
        monkeypatch.setenv("MEDIAHUB_PB_PROGRESS_TICK_S", "0.05")

        def slow_discover(*, name, club, run_id, force_refresh=False):
            time.sleep(0.2)
            return PBDiscovery(swimmer_query=name)

        monkeypatch.setattr("mediahub.pb_discovery.discover_swimmer_pbs", slow_discover)
        steps: list[str] = []
        snaps, exceeded = _enrich_pbs_via_discovery(
            meet=_mini_meet(3),
            our_swimmer_keys={"k1", "k2", "k3"},
            club_name="Club",
            run_id="r-budget-par",
            step=steps.append,
        )
        assert exceeded is True
        assert len(snaps) == 1, "in-flight lookup finishes; queued ones are cancelled"
        assert any("budget" in s.lower() for s in steps)

    def test_parallel_heartbeat_tick_when_nothing_completes(self, monkeypatch):
        monkeypatch.delenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", raising=False)
        monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_WORKERS", "2")
        monkeypatch.delenv("MEDIAHUB_PB_FETCH_BUDGET_S", raising=False)
        monkeypatch.setenv("MEDIAHUB_PB_PROGRESS_TICK_S", "0.05")

        def slow_discover(*, name, club, run_id, force_refresh=False):
            time.sleep(0.25)
            return PBDiscovery(swimmer_query=name)

        monkeypatch.setattr("mediahub.pb_discovery.discover_swimmer_pbs", slow_discover)
        steps: list[str] = []
        snaps, exceeded = _enrich_pbs_via_discovery(
            meet=_mini_meet(2),
            our_swimmer_keys={"k1", "k2"},
            club_name="Club",
            run_id="r-tick",
            step=steps.append,
        )
        assert len(snaps) == 2
        assert exceeded is False
        assert any("Still researching personal bests" in s for s in steps), (
            "a tick line must land between completions so the 180s stale-run "
            "watchdog never declares a slow-but-alive discovery phase dead"
        )
