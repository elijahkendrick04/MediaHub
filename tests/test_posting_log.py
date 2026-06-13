"""tests/test_posting_log.py — publishing-layer posting attempt log.

The posting log is observability for every publish attempt that goes
through the scheduler (or any future scheduler). It is intentionally lossy
and exception-safe: it must never crash the calling endpoint, never
grow unbounded, and never leak rows across organisations.

This file pins:

  1. Schema bootstrap is idempotent and safe to call repeatedly.
  2. ``record_attempt`` writes every field correctly, returns a row id,
     and truncates long captions to a 200-char excerpt.
  3. Input validation rejects malformed status / missing identifiers
     by returning 0 — nothing is inserted on a bad call.
  4. ``recent_attempts`` returns newest-first, respects ``limit``,
     supports ``run_id`` / ``card_id`` filters, and is strictly scoped
     by ``profile_id`` (no cross-tenant leakage).
  5. ``attempts_summary_for_run`` aggregates ok vs failed counts and
     surfaces the most recent ``attempted_at`` timestamp.
  6. The retention sweep trims the oldest rows once row count crosses
     the prune threshold.
  7. Failure resilience — when the SQLite file cannot be written, the
     public API degrades to safe defaults instead of raising.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.publishing import posting_log as _posting_log  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_log(tmp_path, monkeypatch):
    """Point DATA_DIR at a tmpdir and reload the posting_log module.

    Each test gets a virgin SQLite file at ``tmp_path/data.db`` so we
    never see cross-test pollution.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = importlib.reload(_posting_log)
    # Sanity: the db path must resolve to the tmpdir (per-call resolution).
    assert str(module._db_path()).startswith(str(tmp_path))
    yield module
    # Reload again with the real env so we don't leave a broken module
    # registered for the next test (some tests don't use this fixture).
    monkeypatch.delenv("DATA_DIR", raising=False)
    importlib.reload(_posting_log)


def _insert_ok(module, *, profile_id="org-a", run_id="run-1", card_id="card-1",
               status="ok", caption="hello world", attempted_at=None, **kw):
    """Shortcut to insert a row with sensible defaults."""
    return module.record_attempt(
        profile_id=profile_id,
        run_id=run_id,
        card_id=card_id,
        status=status,
        caption=caption,
        attempted_at=attempted_at,
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. Schema bootstrap
# ---------------------------------------------------------------------------

class TestSchema:
    def test_ensure_schema_is_idempotent(self, fresh_log):
        # Calling it twice in a row must not raise; the second call is
        # effectively a no-op because IF NOT EXISTS guards everything.
        fresh_log._ensure_schema()
        fresh_log._ensure_schema()
        # And the table is queryable after both calls.
        import sqlite3
        conn = sqlite3.connect(str(fresh_log._db_path()))
        try:
            cur = conn.execute("SELECT COUNT(*) FROM posting_attempts")
            assert cur.fetchone()[0] == 0
        finally:
            conn.close()

    def test_schema_creates_indexes(self, fresh_log):
        fresh_log._ensure_schema()
        import sqlite3
        conn = sqlite3.connect(str(fresh_log._db_path()))
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='posting_attempts'"
            )
            names = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
        assert "idx_attempts_profile_at" in names
        assert "idx_attempts_run_card" in names


# ---------------------------------------------------------------------------
# 2. record_attempt writes fields correctly
# ---------------------------------------------------------------------------

class TestRecordAttempt:
    def test_writes_all_fields(self, fresh_log):
        new_id = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="run-42",
            card_id="card-7",
            channel_id="buf-channel-1",
            channel_name="@city_aquatics",
            service="instagram",
            status="ok",
            update_id="buf-update-abc",
            caption="Big PB for the squad today!",
            media_url="https://cdn.example/card-7.png",
            scheduled_at="2026-05-18T12:00:00+00:00",
            attempted_at="2026-05-17T09:00:00+00:00",
        )
        assert isinstance(new_id, int)
        assert new_id > 0

        rows = fresh_log.recent_attempts("org-a")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == new_id
        assert row["profile_id"] == "org-a"
        assert row["run_id"] == "run-42"
        assert row["card_id"] == "card-7"
        assert row["channel_id"] == "buf-channel-1"
        assert row["channel_name"] == "@city_aquatics"
        assert row["service"] == "instagram"
        assert row["status"] == "ok"
        assert row["update_id"] == "buf-update-abc"
        assert row["caption_excerpt"] == "Big PB for the squad today!"
        assert row["media_url"] == "https://cdn.example/card-7.png"
        assert row["scheduled_at"] == "2026-05-18T12:00:00+00:00"
        assert row["attempted_at"] == "2026-05-17T09:00:00+00:00"
        # Optional error fields default to None on success
        assert row["error_kind"] is None
        assert row["error_message"] is None

    def test_failure_records_error_fields(self, fresh_log):
        new_id = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="run-1",
            card_id="card-1",
            status="failed",
            error_kind="auth",
            error_message="missing scheduling token",
            caption="(would have posted)",
        )
        assert new_id > 0
        row = fresh_log.recent_attempts("org-a")[0]
        assert row["status"] == "failed"
        assert row["error_kind"] == "auth"
        assert row["error_message"] == "missing scheduling token"
        # update_id remains null on failure
        assert row["update_id"] is None

    def test_attempted_at_defaults_to_now(self, fresh_log):
        new_id = _insert_ok(fresh_log)
        assert new_id > 0
        row = fresh_log.recent_attempts("org-a")[0]
        # Default uses an ISO-8601 UTC timestamp (must contain a "T")
        assert "T" in row["attempted_at"]
        assert row["attempted_at"]  # non-empty

    def test_long_caption_truncated_to_200_chars(self, fresh_log):
        long_caption = "x" * 1000
        new_id = _insert_ok(fresh_log, caption=long_caption)
        assert new_id > 0
        row = fresh_log.recent_attempts("org-a")[0]
        assert len(row["caption_excerpt"]) == 200
        assert row["caption_excerpt"] == "x" * 200

    def test_empty_caption_persists_as_empty(self, fresh_log):
        _insert_ok(fresh_log, caption="")
        row = fresh_log.recent_attempts("org-a")[0]
        # Empty string is fine — never None for caption_excerpt.
        assert row["caption_excerpt"] == ""


# ---------------------------------------------------------------------------
# 3. Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_status_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="run-1",
            card_id="card-1",
            status="pending",  # not in {ok, failed}
        )
        assert result == 0
        assert fresh_log.recent_attempts("org-a") == []

    def test_empty_status_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="run-1",
            card_id="card-1",
            status="",
        )
        assert result == 0

    def test_missing_profile_id_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="",
            run_id="run-1",
            card_id="card-1",
            status="ok",
        )
        assert result == 0

    def test_whitespace_profile_id_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="   ",
            run_id="run-1",
            card_id="card-1",
            status="ok",
        )
        assert result == 0

    def test_missing_run_id_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="",
            card_id="card-1",
            status="ok",
        )
        assert result == 0

    def test_missing_card_id_returns_zero(self, fresh_log):
        result = fresh_log.record_attempt(
            profile_id="org-a",
            run_id="run-1",
            card_id="",
            status="ok",
        )
        assert result == 0


# ---------------------------------------------------------------------------
# 4. recent_attempts
# ---------------------------------------------------------------------------

class TestRecentAttempts:
    def test_newest_first(self, fresh_log):
        # Use explicit ascending timestamps so ordering is unambiguous.
        _insert_ok(fresh_log, card_id="c1", attempted_at="2026-05-17T08:00:00+00:00")
        _insert_ok(fresh_log, card_id="c2", attempted_at="2026-05-17T09:00:00+00:00")
        _insert_ok(fresh_log, card_id="c3", attempted_at="2026-05-17T10:00:00+00:00")
        rows = fresh_log.recent_attempts("org-a")
        assert [r["card_id"] for r in rows] == ["c3", "c2", "c1"]

    def test_respects_limit(self, fresh_log):
        for i in range(5):
            _insert_ok(
                fresh_log,
                card_id=f"c{i}",
                attempted_at=f"2026-05-17T0{i}:00:00+00:00",
            )
        rows = fresh_log.recent_attempts("org-a", limit=2)
        assert len(rows) == 2
        # Newest two: c4 then c3.
        assert [r["card_id"] for r in rows] == ["c4", "c3"]

    def test_filter_by_run_id(self, fresh_log):
        _insert_ok(fresh_log, run_id="run-A", card_id="c1")
        _insert_ok(fresh_log, run_id="run-B", card_id="c2")
        _insert_ok(fresh_log, run_id="run-A", card_id="c3")
        rows = fresh_log.recent_attempts("org-a", run_id="run-A")
        assert len(rows) == 2
        assert {r["card_id"] for r in rows} == {"c1", "c3"}

    def test_filter_by_card_id(self, fresh_log):
        _insert_ok(fresh_log, card_id="c1")
        _insert_ok(fresh_log, card_id="c1")  # same card, two attempts
        _insert_ok(fresh_log, card_id="c2")
        rows = fresh_log.recent_attempts("org-a", card_id="c1")
        assert len(rows) == 2
        assert all(r["card_id"] == "c1" for r in rows)

    def test_filter_by_run_and_card(self, fresh_log):
        _insert_ok(fresh_log, run_id="run-A", card_id="c1")
        _insert_ok(fresh_log, run_id="run-A", card_id="c2")
        _insert_ok(fresh_log, run_id="run-B", card_id="c1")
        rows = fresh_log.recent_attempts("org-a", run_id="run-A", card_id="c1")
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run-A"
        assert rows[0]["card_id"] == "c1"

    def test_scoped_by_profile_id(self, fresh_log):
        # Two different orgs must never see each other's attempts.
        _insert_ok(fresh_log, profile_id="org-a", card_id="card-a1")
        _insert_ok(fresh_log, profile_id="org-a", card_id="card-a2")
        _insert_ok(fresh_log, profile_id="org-b", card_id="card-b1")

        a_rows = fresh_log.recent_attempts("org-a")
        b_rows = fresh_log.recent_attempts("org-b")
        assert len(a_rows) == 2
        assert len(b_rows) == 1
        assert all(r["profile_id"] == "org-a" for r in a_rows)
        assert all(r["profile_id"] == "org-b" for r in b_rows)
        # And vice versa — no leakage in either direction.
        assert {r["card_id"] for r in a_rows} == {"card-a1", "card-a2"}
        assert {r["card_id"] for r in b_rows} == {"card-b1"}

    def test_empty_profile_returns_empty(self, fresh_log):
        _insert_ok(fresh_log)
        assert fresh_log.recent_attempts("") == []
        assert fresh_log.recent_attempts("   ") == []

    def test_unknown_profile_returns_empty(self, fresh_log):
        _insert_ok(fresh_log, profile_id="org-a")
        assert fresh_log.recent_attempts("org-zzz") == []


# ---------------------------------------------------------------------------
# 5. attempts_summary_for_run
# ---------------------------------------------------------------------------

class TestAttemptsSummaryForRun:
    def test_counts_ok_and_failed(self, fresh_log):
        _insert_ok(fresh_log, run_id="run-1", card_id="c1", status="ok",
                   attempted_at="2026-05-17T08:00:00+00:00")
        _insert_ok(fresh_log, run_id="run-1", card_id="c2", status="ok",
                   attempted_at="2026-05-17T09:00:00+00:00")
        _insert_ok(fresh_log, run_id="run-1", card_id="c3", status="failed",
                   attempted_at="2026-05-17T10:00:00+00:00")
        summary = fresh_log.attempts_summary_for_run("org-a", "run-1")
        assert summary["ok"] == 2
        assert summary["failed"] == 1
        assert summary["last_attempted_at"] == "2026-05-17T10:00:00+00:00"

    def test_no_attempts_returns_zeros(self, fresh_log):
        summary = fresh_log.attempts_summary_for_run("org-a", "run-empty")
        assert summary == {"ok": 0, "failed": 0, "last_attempted_at": None}

    def test_only_failures(self, fresh_log):
        _insert_ok(fresh_log, run_id="run-2", card_id="c1", status="failed",
                   error_kind="api", error_message="500",
                   attempted_at="2026-05-17T11:00:00+00:00")
        _insert_ok(fresh_log, run_id="run-2", card_id="c2", status="failed",
                   error_kind="network", error_message="timeout",
                   attempted_at="2026-05-17T12:00:00+00:00")
        summary = fresh_log.attempts_summary_for_run("org-a", "run-2")
        assert summary["ok"] == 0
        assert summary["failed"] == 2
        assert summary["last_attempted_at"] == "2026-05-17T12:00:00+00:00"

    def test_scoped_by_profile(self, fresh_log):
        # Same run_id under two different profiles must not bleed into
        # each other's summary.
        _insert_ok(fresh_log, profile_id="org-a", run_id="run-x",
                   card_id="c1", status="ok")
        _insert_ok(fresh_log, profile_id="org-b", run_id="run-x",
                   card_id="c1", status="failed")
        a = fresh_log.attempts_summary_for_run("org-a", "run-x")
        b = fresh_log.attempts_summary_for_run("org-b", "run-x")
        assert a["ok"] == 1 and a["failed"] == 0
        assert b["ok"] == 0 and b["failed"] == 1

    def test_missing_ids_returns_default(self, fresh_log):
        default = {"ok": 0, "failed": 0, "last_attempted_at": None}
        assert fresh_log.attempts_summary_for_run("", "run-1") == default
        assert fresh_log.attempts_summary_for_run("org-a", "") == default


# ---------------------------------------------------------------------------
# 6. Retention sweep
# ---------------------------------------------------------------------------

class TestRetentionSweep:
    def test_prune_triggers_when_threshold_exceeded(self, fresh_log, monkeypatch):
        """Patch the prune thresholds to tiny numbers so we can exercise
        the sweep without inserting 5,000 rows in real time.

        With threshold=10 / target=8, the sweep fires on insert #11
        (when the row count crosses 10), trims back to 8, then inserts
        12+ continue to trip the sweep one at a time. After 12 inserts
        we should be sitting at target+1 = 9 surviving rows, with the
        oldest rows gone.
        """
        monkeypatch.setattr(fresh_log, "_PRUNE_THRESHOLD", 10)
        monkeypatch.setattr(fresh_log, "_PRUNE_TARGET", 8)

        # Insert 12 rows with strictly increasing timestamps so the
        # oldest rows are unambiguous and the sweep is deterministic.
        for i in range(12):
            _insert_ok(
                fresh_log,
                card_id=f"c{i:02d}",
                attempted_at=f"2026-05-17T{i:02d}:00:00+00:00",
            )

        rows = fresh_log.recent_attempts("org-a", limit=100)
        # After the sweep we must be strictly below the threshold —
        # the post-insert count cannot stay above 10 once we've
        # crossed it.
        assert len(rows) < 10
        # And we must be at or above the target (sweep trims TO target,
        # not below it) — additional rows after target+1 may exist if
        # more inserts happened post-sweep.
        assert len(rows) >= 8
        # The newest row (c11) must survive.
        card_ids = {r["card_id"] for r in rows}
        assert "c11" in card_ids
        # The oldest rows must have been pruned.
        assert "c00" not in card_ids
        assert "c01" not in card_ids


# ---------------------------------------------------------------------------
# 7. Failure resilience — unwritable DB path
# ---------------------------------------------------------------------------

class TestFailureResilience:
    @pytest.fixture
    def broken_log(self, tmp_path, monkeypatch):
        """Point DATA_DIR at a path that cannot host a SQLite database.

        We use a regular file (not a directory) as DATA_DIR so the
        ``DATA_DIR / "data.db"`` derivation creates an unusable path
        (sqlite3 cannot open a database inside a regular file).
        """
        blocker = tmp_path / "blocker_file"
        blocker.write_text("not a directory")
        # Now DATA_DIR points at a file, so DATA_DIR/data.db is invalid.
        monkeypatch.setenv("DATA_DIR", str(blocker))
        module = importlib.reload(_posting_log)
        yield module
        monkeypatch.delenv("DATA_DIR", raising=False)
        importlib.reload(_posting_log)

    def test_record_attempt_returns_zero_on_db_error(self, broken_log):
        # Must not raise — must return 0 instead.
        result = broken_log.record_attempt(
            profile_id="org-a",
            run_id="run-1",
            card_id="card-1",
            status="ok",
            caption="hello",
        )
        assert result == 0

    def test_recent_attempts_returns_empty_on_db_error(self, broken_log):
        rows = broken_log.recent_attempts("org-a")
        assert rows == []

    def test_summary_returns_default_on_db_error(self, broken_log):
        summary = broken_log.attempts_summary_for_run("org-a", "run-1")
        assert summary == {"ok": 0, "failed": 0, "last_attempted_at": None}
