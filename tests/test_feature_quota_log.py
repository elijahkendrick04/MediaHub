"""Tests for the per-org / per-feature AI usage ledger (governance 1.23).

The ledger takes an injectable ``db_path`` so each test runs against its own
throwaway SQLite file — no DATA_DIR juggling, no cross-test pollution.
"""

from __future__ import annotations

import sqlite3

import pytest

import mediahub.observability.feature_quota as fq


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def test_record_and_count(db):
    assert fq.count_for_org("club-a", db_path=db) == 0
    rid = fq.record_use(org_id="club-a", feature="caption", ok=True, provider="gemini", db_path=db)
    assert rid > 0
    assert fq.count_for_org("club-a", db_path=db) == 1
    # A different org is isolated.
    assert fq.count_for_org("club-b", db_path=db) == 0


def test_count_scoped_to_feature(db):
    fq.record_use(org_id="club-a", feature="caption", ok=True, db_path=db)
    fq.record_use(org_id="club-a", feature="caption", ok=True, db_path=db)
    fq.record_use(org_id="club-a", feature="palette", ok=True, db_path=db)
    assert fq.count_for_org("club-a", db_path=db) == 3
    assert fq.count_for_org("club-a", feature="caption", db_path=db) == 2
    assert fq.count_for_org("club-a", feature="palette", db_path=db) == 1
    assert fq.count_for_org("club-a", feature="describe", db_path=db) == 0


def test_failed_calls_not_counted_by_default(db):
    fq.record_use(org_id="club-a", feature="caption", ok=False, db_path=db)
    assert fq.count_for_org("club-a", db_path=db) == 0  # ok_only default
    assert fq.count_for_org("club-a", ok_only=False, db_path=db) == 1


def test_blank_org_or_feature_records_nothing(db):
    assert fq.record_use(org_id="", feature="caption", ok=True, db_path=db) == 0
    assert fq.record_use(org_id="club-a", feature="", ok=True, db_path=db) == 0
    assert fq.count_for_org("club-a", ok_only=False, db_path=db) == 0


def test_feature_is_normalised(db):
    fq.record_use(org_id="club-a", feature="  Caption ", ok=True, db_path=db)
    assert fq.count_for_org("club-a", feature="caption", db_path=db) == 1


def test_usage_breakdown_by_feature(db):
    for feat in ("caption", "caption", "palette"):
        fq.record_use(org_id="club-a", feature=feat, ok=True, db_path=db)
    usage = fq.usage_for_org("club-a", db_path=db)
    assert usage["total"] == 3
    assert usage["by_feature"]["caption"] == 2
    assert usage["by_feature"]["palette"] == 1


def test_window_excludes_old_rows(db):
    old = "2000-01-01T00:00:00+00:00"
    fq.record_use(org_id="club-a", feature="caption", ok=True, ts=old, db_path=db)
    assert fq.count_for_org("club-a", window_hours=24, db_path=db) == 0
    # but visible in a wide window
    assert fq.count_for_org("club-a", window_hours=24 * 365 * 100, db_path=db) == 1


def test_usage_all_orgs_totals_sorted(db):
    fq.record_use(org_id="club-a", feature="caption", ok=True, db_path=db)
    fq.record_use(org_id="club-a", feature="palette", ok=True, db_path=db)
    fq.record_use(org_id="club-b", feature="caption", ok=True, db_path=db)
    rows = fq.usage_all_orgs(db_path=db)
    assert [r["org_id"] for r in rows] == ["club-a", "club-b"]  # busiest first
    assert rows[0]["total"] == 2
    assert rows[0]["by_feature"] == {"caption": 1, "palette": 1}
    assert rows[1]["total"] == 1


def test_usage_all_orgs_respects_limit(db):
    for org in ("a", "b", "c"):
        fq.record_use(org_id=org, feature="caption", ok=True, db_path=db)
    rows = fq.usage_all_orgs(limit=2, db_path=db)
    assert len(rows) == 2


def test_count_on_missing_table_fails_open(db):
    # No record_use yet → the table may not exist; count must return 0, not raise.
    assert fq.count_for_org("club-a", db_path=db) == 0
    assert fq.usage_for_org("club-a", db_path=db)["total"] == 0
    assert fq.usage_all_orgs(db_path=db) == []


def test_retention_sweep(db, monkeypatch):
    monkeypatch.setattr(fq, "_PRUNE_THRESHOLD", 10)
    monkeypatch.setattr(fq, "_PRUNE_TARGET", 5)
    for _ in range(20):
        fq.record_use(org_id="club-a", feature="caption", ok=True, db_path=db)
    conn = sqlite3.connect(str(db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM feature_uses").fetchone()
    finally:
        conn.close()
    # Swept down to roughly the target, never above the threshold.
    assert n <= 10
