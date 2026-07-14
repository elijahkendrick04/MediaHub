"""Regression tests for finding F25 — warm-cache meet-freshness gate.

The warm swimmer cache used to trust *any* non-empty baseline younger than its
7-day wall-clock TTL. That let a baseline captured before a meet stay
authoritative for a week, so a slower swim at a later meet could be announced
as a "new PB" against a stale prior time (diagnosis PROBE 13: cache warmed
Saturday, the following Friday's meet processed within TTL, a 1:00.50 swim
fired as a new PB even though the swimmer's real PB — set midweek — was faster).

``WarmCache.get`` now also compares the cached baseline's capture time against
the *meet date* being processed. The fix is written so ``now``, the cache
timestamp, and the meet date are all explicit inputs — nothing here relies on
an implicit wall clock, so every case below is fully pinned.
"""

from __future__ import annotations

import calendar
import json
import time
from unittest.mock import patch

import pytest

from mediahub.pb_discovery.cache import WarmCache, make_swimmer_key

# A fixed, arbitrary epoch to anchor every scenario (≈ 2023-11-14T22:13:20Z).
T0 = 1_700_000_000.0
DAY = 24 * 3600
GRACE = WarmCache.MEET_FRESHNESS_GRACE  # 1 day
_PAYLOAD = {"swimmer_query": "Alex Doe (Test SC)", "pbs": [{"event": "100m Freestyle"}]}
_EMPTY = {"swimmer_query": "Alex Doe (Test SC)", "pbs": [], "confidence": 0.0}


@pytest.fixture()
def cache(tmp_path):
    with patch(
        "mediahub.pb_discovery.cache._discovered_root",
        return_value=tmp_path / "discovered",
    ):
        yield WarmCache()


def _write(cache: WarmCache, key: str, payload: dict, saved_at_ts: float) -> None:
    """Write a warm-cache entry with a pinned ``_saved_at_ts`` timestamp."""
    p = cache._base / f"{key}.json"
    p.write_text(
        json.dumps({"_saved_at": "pinned", "_saved_at_ts": saved_at_ts, "payload": payload}),
        encoding="utf-8",
    )


class TestMeetFreshnessGate:
    def test_grace_constant_is_one_day(self):
        """Pin the grace *magnitude* directly. The behavioural boundary test
        re-reads MEET_FRESHNESS_GRACE, so without this a silent widening of the
        constant (e.g. to ~6 days) would keep the suite green while
        reintroducing F25 for 2-5 day staleness."""
        assert WarmCache.MEET_FRESHNESS_GRACE == 24 * 3600

    def test_baseline_captured_before_the_meet_is_rejected(self, cache):
        """The F25 core: a baseline fetched ~6 days before the meet is stale
        for that meet even though the 7-day wall-clock TTL has not expired."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        # Meet is 6 days *after* the cache was captured; wall clock is also
        # only 6 days on (< 7-day TTL) — so age-only would still serve it.
        assert cache.get(key, meet_date=T0 + 6 * DAY, now=T0 + 6 * DAY) is None

    def test_two_day_stale_baseline_is_rejected(self, cache):
        """Magnitude-independent guard: 2 days exceeds any ≤1-day grace, so this
        rejects F25 staleness even if the grace constant is later edited (it
        does not re-read MEET_FRESHNESS_GRACE)."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date=T0 + 2 * DAY, now=T0 + 2 * DAY) is None

    def test_baseline_captured_after_the_meet_is_served(self, cache):
        """Normal flow: discovery warms the cache while *processing* a meet, so
        the baseline is captured on/after the meet date — it must still serve
        (rejecting it would force pointless re-research on every reuse)."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date=T0 - 2 * DAY, now=T0 + 3600) == _PAYLOAD

    def test_within_grace_is_served(self, cache):
        """A cache captured slightly before the meet (< grace, e.g. timezone
        skew / same-day processing) is still trusted."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date=T0 + 12 * 3600, now=T0 + 12 * 3600) == _PAYLOAD

    def test_grace_boundary(self, cache):
        """Exactly at the grace is served; one second past it is rejected."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date=T0 + GRACE, now=T0 + GRACE) == _PAYLOAD
        assert cache.get(key, meet_date=T0 + GRACE + 1, now=T0 + GRACE + 1) is None

    def test_meet_date_none_disables_the_gate(self, cache):
        """No meet date supplied → behaviour is exactly the old age-only gate."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, now=T0 + 6 * DAY) == _PAYLOAD  # within TTL, no meet gate

    def test_unparseable_meet_date_disables_the_gate(self, cache):
        """A garbage meet date must not raise or reject — it just skips the gate."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date="not-a-date", now=T0 + 100) == _PAYLOAD

    def test_non_finite_meet_date_disables_the_gate(self, cache):
        """inf/NaN meet dates coerce to None (gate skipped), never raise."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, meet_date=float("inf"), now=T0 + 100) == _PAYLOAD
        assert cache.get(key, meet_date=float("nan"), now=T0 + 100) == _PAYLOAD


class TestBackwardCompat:
    def test_no_kwargs_call_serves_fresh(self, cache):
        """The exact production call shape (discover.py: ``get(swimmer_key)``,
        no kwargs) still works: it pins the keyword-only ``*`` marker and the
        ``now=None`` → wall-clock fallthrough."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=time.time())
        assert cache.get(key) == _PAYLOAD

    def test_missing_saved_at_ts_expires_via_ttl(self, cache):
        """A legacy entry with no ``_saved_at_ts`` (saved_at → 0) is treated as
        long-expired by the age gate and never reaches the meet gate."""
        key = make_swimmer_key("Legacy", "Test SC")
        p = cache._base / f"{key}.json"
        p.write_text(json.dumps({"_saved_at": "old", "payload": _PAYLOAD}), encoding="utf-8")
        assert cache.get(key, meet_date=T0, now=T0) is None

    def test_nan_now_does_not_serve_expired_entry(self, cache):
        """A non-finite ``now`` must fall back to the wall clock, not silently
        serve an entry the arithmetic can't expire (nan - saved_at > ttl)."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)  # T0 is ~2023, long past any TTL vs wall clock
        assert cache.get(key, now=float("nan")) is None


class TestIsoStringMeetDate:
    def test_iso_date_string_after_cache_is_rejected(self, cache):
        key = make_swimmer_key("Alex Doe", "Test SC")
        saved = float(calendar.timegm((2026, 7, 1, 0, 0, 0, 0, 0, 0)))
        _write(cache, key, _PAYLOAD, saved_at_ts=saved)
        # Meet 9 days after the cache snapshot → stale.
        assert cache.get(key, meet_date="2026-07-10", now=saved + 100) is None

    def test_iso_date_string_before_cache_is_served(self, cache):
        key = make_swimmer_key("Alex Doe", "Test SC")
        saved = float(calendar.timegm((2026, 7, 1, 0, 0, 0, 0, 0, 0)))
        _write(cache, key, _PAYLOAD, saved_at_ts=saved)
        assert cache.get(key, meet_date="2026-06-30", now=saved + 100) is not None

    def test_iso_timestamp_with_z_suffix_parses(self, cache):
        key = make_swimmer_key("Alex Doe", "Test SC")
        saved = float(calendar.timegm((2026, 7, 1, 0, 0, 0, 0, 0, 0)))
        _write(cache, key, _PAYLOAD, saved_at_ts=saved)
        assert cache.get(key, meet_date="2026-07-10T09:30:00Z", now=saved + 100) is None


class TestInjectableNow:
    def test_now_is_used_for_the_ttl_check(self, cache):
        """The TTL check honours the injected ``now`` instead of the wall
        clock, so freshness is pinnable in tests."""
        key = make_swimmer_key("Alex Doe", "Test SC")
        _write(cache, key, _PAYLOAD, saved_at_ts=T0)
        assert cache.get(key, now=T0 + 100) is not None
        assert cache.get(key, now=T0 + WarmCache.TTL + 60) is None

    def test_empty_payload_still_uses_short_ttl_with_injected_now(self, cache):
        key = make_swimmer_key("Empty", "Test SC")
        _write(cache, key, _EMPTY, saved_at_ts=T0)
        assert cache.get(key, now=T0 + 100) is not None
        assert cache.get(key, now=T0 + WarmCache.EMPTY_TTL + 60) is None


class TestRealisticScenario:
    def test_probe13_stale_baseline_no_longer_serves(self, cache):
        """End-to-end shape of PROBE 13: cache warmed Saturday, the following
        Friday's meet (6 days on, inside TTL) must not reuse the stale
        baseline — get() returns None so discovery re-researches."""
        key = make_swimmer_key("Alex Doe", "Riverside SC")
        saturday = float(calendar.timegm((2026, 6, 6, 12, 0, 0, 0, 0, 0)))
        next_friday = float(calendar.timegm((2026, 6, 12, 12, 0, 0, 0, 0, 0)))
        _write(cache, key, _PAYLOAD, saved_at_ts=saturday)
        assert cache.get(key, meet_date=next_friday, now=next_friday) is None
