"""tests/test_uptime_log.py — Phase 1.5 uptime heartbeat store.

The SQLite uptime log records one row per /healthz and /health hit
so the public /status page can show a real uptime number derived
from heartbeat density. This module is observability-only; failures
must never raise into the caller.

These tests pin the public API contract:
  * record_heartbeat persists rows + survives DB issues
  * uptime_stats returns a sane shape (and an honest has_data=False
    when there are no rows)
  * uptime % computation: 100% when heartbeats are dense, drops
    proportionally with long gaps, drops further when ok=False rows
    are present
  * recent_gaps surfaces silent intervals only when long enough
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def fresh_uptime(tmp_path, monkeypatch):
    """Reload the module against a per-test DATA_DIR so the DB is fresh."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.observability.uptime as u
    importlib.reload(u)
    return u


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()


class TestRecordHeartbeat:
    def test_inserts_and_returns_row_id(self, fresh_uptime):
        rid = fresh_uptime.record_heartbeat(ok=True)
        assert rid > 0
        latest = fresh_uptime.latest_heartbeat()
        assert latest is not None
        assert latest["ok"] is True
        assert latest["source"] == "healthz"

    def test_records_failed_heartbeat_with_error(self, fresh_uptime):
        rid = fresh_uptime.record_heartbeat(
            ok=False, source="health",
            error="database: connection refused",
        )
        assert rid > 0
        latest = fresh_uptime.latest_heartbeat()
        assert latest["ok"] is False
        assert latest["source"] == "health"
        assert "connection refused" in (latest["error"] or "")

    def test_truncates_long_error_to_200_chars(self, fresh_uptime):
        very_long = "x" * 500
        fresh_uptime.record_heartbeat(ok=False, error=very_long)
        latest = fresh_uptime.latest_heartbeat()
        assert len(latest["error"]) <= 200

    def test_clamps_negative_response_ms_to_zero(self, fresh_uptime):
        fresh_uptime.record_heartbeat(ok=True, response_ms=-50)
        latest = fresh_uptime.latest_heartbeat()
        assert latest["response_ms"] == 0

    def test_accepts_explicit_ts_for_seeding(self, fresh_uptime):
        when = "2026-05-01T12:00:00+00:00"
        fresh_uptime.record_heartbeat(ok=True, ts=when)
        latest = fresh_uptime.latest_heartbeat()
        assert latest["ts"] == when


class TestUptimeStatsEmptyTable:
    def test_returns_has_data_false_when_empty(self, fresh_uptime):
        stats = fresh_uptime.uptime_stats(window_hours=24)
        assert stats["has_data"] is False
        assert stats["samples"] == 0
        assert stats["uptime_pct"] == 0.0

    def test_window_hours_normalised_to_positive_int(self, fresh_uptime):
        stats = fresh_uptime.uptime_stats(window_hours=0)
        assert stats["window_hours"] >= 1
        stats = fresh_uptime.uptime_stats(window_hours="not a number")
        assert stats["window_hours"] == 24


class TestUptimeStatsWithData:
    def test_dense_heartbeats_yield_high_uptime(self, fresh_uptime):
        # Seed a heartbeat every minute for the last hour — well within
        # the 5-minute downtime threshold, so uptime should be 100%.
        now = datetime.now(timezone.utc)
        for i in range(60):
            fresh_uptime.record_heartbeat(
                ok=True,
                ts=(now - timedelta(minutes=60 - i)).isoformat(),
            )
        stats = fresh_uptime.uptime_stats(window_hours=24)
        assert stats["has_data"] is True
        assert stats["samples"] == 60
        # Tail gap will exist (no heartbeats older than 1h) so 24h window
        # has a 23h gap → uptime drops, but the recent hour is 100%.
        # Verify the 1h window is perfect.
        stats_1h = fresh_uptime.uptime_stats(window_hours=1)
        assert stats_1h["uptime_pct"] >= 0.99

    def test_long_gap_reduces_uptime_pct(self, fresh_uptime):
        """A 4-hour silence in a 24h window must show up as downtime."""
        now = datetime.now(timezone.utc)
        # Two heartbeats 4 hours apart — gap = 4h, downtime = 4h - 5min.
        fresh_uptime.record_heartbeat(
            ok=True, ts=(now - timedelta(hours=23, minutes=55)).isoformat()
        )
        fresh_uptime.record_heartbeat(
            ok=True, ts=(now - timedelta(hours=19, minutes=55)).isoformat()
        )
        # Then dense heartbeats every minute to "now" so the tail is clean.
        for i in range(1180, 0, -1):
            fresh_uptime.record_heartbeat(
                ok=True, ts=(now - timedelta(minutes=i)).isoformat()
            )
        stats = fresh_uptime.uptime_stats(window_hours=24)
        assert stats["has_data"] is True
        # Downtime should be ≈ (4h - 5min) = 14100s → uptime ≈ 1 - 14100/86400 ≈ 83.6%
        assert 0.80 < stats["uptime_pct"] < 0.86
        assert stats["downtime_seconds"] > 13_000

    def test_failed_heartbeats_count_against_uptime(self, fresh_uptime):
        now = datetime.now(timezone.utc)
        # 60 minutes of dense heartbeats fully inside the 1h window, 10
        # of which are ok=False. We shift back by 30 seconds to make sure
        # the oldest heartbeat sits comfortably inside the window even
        # after a few milliseconds of test-execution slop.
        for i in range(60):
            ok = (i % 6 != 0)  # 10 failures: i=0,6,12,18,24,30,36,42,48,54
            fresh_uptime.record_heartbeat(
                ok=ok,
                ts=(now - timedelta(minutes=59 - i, seconds=30)).isoformat(),
            )
        stats = fresh_uptime.uptime_stats(window_hours=1)
        # Each failed heartbeat counts 60s against uptime → ≈ 10 min in 60.
        assert stats["failed_count"] == 10
        assert stats["uptime_pct"] < 0.90
        assert stats["uptime_pct"] >= 0.80

    def test_uptime_pct_clamped_to_zero_one_range(self, fresh_uptime):
        # Seed only one ancient heartbeat — the tail gap is enormous.
        fresh_uptime.record_heartbeat(
            ok=True, ts="2026-04-01T00:00:00+00:00",
        )
        stats = fresh_uptime.uptime_stats(window_hours=24)
        assert 0.0 <= stats["uptime_pct"] <= 1.0


class TestRecentGaps:
    def test_returns_empty_when_under_two_heartbeats(self, fresh_uptime):
        assert fresh_uptime.recent_gaps() == []
        fresh_uptime.record_heartbeat(ok=True)
        assert fresh_uptime.recent_gaps() == []

    def test_surfaces_long_gaps_newest_first(self, fresh_uptime):
        now = datetime.now(timezone.utc)
        ts_list = [
            now - timedelta(hours=20),
            now - timedelta(hours=20) + timedelta(seconds=30),
            # 30-min gap
            now - timedelta(hours=19, minutes=30),
            # Another 45-min gap
            now - timedelta(hours=18, minutes=45),
            now - timedelta(hours=18, minutes=44),
        ]
        for ts in ts_list:
            fresh_uptime.record_heartbeat(ok=True, ts=ts.isoformat())
        gaps = fresh_uptime.recent_gaps(window_hours=24, limit=10)
        assert len(gaps) >= 2
        # Newest first.
        assert gaps[0]["to_ts"] >= gaps[-1]["to_ts"]
        # All durations meet the 5-minute floor.
        for g in gaps:
            assert g["duration_seconds"] >= 300

    def test_ignores_gaps_below_minimum(self, fresh_uptime):
        # Three back-to-back heartbeats with only 1-minute gaps.
        now = datetime.now(timezone.utc)
        for i in range(3):
            fresh_uptime.record_heartbeat(
                ok=True, ts=(now - timedelta(minutes=i)).isoformat()
            )
        gaps = fresh_uptime.recent_gaps()
        assert gaps == []


class TestRetentionSweep:
    def test_sweep_trips_above_threshold(self, fresh_uptime, monkeypatch):
        """When more than _PRUNE_THRESHOLD rows exist, retention sweep
        trims the table back to _PRUNE_TARGET.

        The sweep runs inside record_attempt after each successful
        insert, so once we cross the threshold the table tracks the
        target +1 per insert. Inserting 21 rows with threshold=20 /
        target=15 produces exactly 15 (first 20 inserts stay below the
        threshold; row 21 trips the sweep and lands at target).
        """
        monkeypatch.setattr(fresh_uptime, "_PRUNE_THRESHOLD", 20)
        monkeypatch.setattr(fresh_uptime, "_PRUNE_TARGET", 15)
        now = datetime.now(timezone.utc)
        for i in range(21):
            fresh_uptime.record_heartbeat(
                ok=True, ts=(now - timedelta(seconds=25 - i)).isoformat()
            )
        import sqlite3
        conn = sqlite3.connect(str(fresh_uptime.DB_PATH))
        n = conn.execute("SELECT COUNT(*) FROM uptime_heartbeats").fetchone()[0]
        conn.close()
        # After the sweep ran on row 21, the table holds 15 rows. Even
        # rounding for arithmetic, we should be at or below target.
        assert n <= 15

    def test_sweep_does_not_run_below_threshold(self, fresh_uptime, monkeypatch):
        """Inserts below the threshold leave the table intact."""
        monkeypatch.setattr(fresh_uptime, "_PRUNE_THRESHOLD", 1000)
        monkeypatch.setattr(fresh_uptime, "_PRUNE_TARGET", 500)
        for _ in range(10):
            fresh_uptime.record_heartbeat(ok=True)
        import sqlite3
        conn = sqlite3.connect(str(fresh_uptime.DB_PATH))
        n = conn.execute("SELECT COUNT(*) FROM uptime_heartbeats").fetchone()[0]
        conn.close()
        assert n == 10
