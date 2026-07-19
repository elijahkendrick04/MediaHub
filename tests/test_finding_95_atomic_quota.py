"""Finding #95 — quota enforcement is an atomic reserve, not check-then-act.

The old path read the count (enforce), ran the work, then inserted (record), so N
concurrent requests at ``limit - 1`` all passed the read and all executed — the
quota was exceeded under concurrency. ``feature_quota.reserve_use`` now inserts a
usage row IFF the org is under the limit, evaluated inside a ``BEGIN IMMEDIATE``
write transaction, so concurrent reservers serialise and at most ``limit`` succeed.
``finalize_use`` releases a reservation on failure; ``governance.quota.reserve`` /
``finalize`` and ``feature_scope`` wrap this with fail-open + guaranteed cleanup.
"""

from __future__ import annotations

import threading

import pytest

from mediahub.governance import context as gov_context
from mediahub.governance import quota as gov_quota
from mediahub.observability import feature_quota


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    feature_quota.ensure_schema()
    yield


def test_reserve_use_is_atomic_under_concurrency():
    """The heart of #95: with limit=5 and 40 threads racing, EXACTLY 5 reserve a
    slot — never more. A check-then-act gate would admit far more than 5."""
    limit = 5
    n_threads = 40
    results: list = []
    barrier = threading.Barrier(n_threads)
    lock = threading.Lock()

    def worker():
        barrier.wait()  # maximise contention — everyone reserves at once
        rid = feature_quota.reserve_use(
            org_id="org-a", feature="caption", limit=limit, window_hours=720
        )
        with lock:
            results.append(rid)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    reserved = [r for r in results if r is not None]
    denied = [r for r in results if r is None]
    assert len(reserved) == limit, f"atomic reserve must cap at {limit}, got {len(reserved)}"
    assert len(denied) == n_threads - limit
    # And the ledger holds exactly `limit` ok=1 rows.
    assert feature_quota.count_for_org("org-a", feature="caption", window_hours=720) == limit


def test_finalize_release_frees_the_slot():
    # Reserve the single available slot, then release it on failure — a later
    # reserve must succeed because the released row no longer counts.
    rid = feature_quota.reserve_use(org_id="o", feature="f", limit=1, window_hours=720)
    assert rid is not None
    assert feature_quota.reserve_use(org_id="o", feature="f", limit=1, window_hours=720) is None
    feature_quota.finalize_use(rid, ok=False)  # released
    assert feature_quota.count_for_org("o", feature="f", window_hours=720) == 0
    # A slot is free again.
    assert feature_quota.reserve_use(org_id="o", feature="f", limit=1, window_hours=720) is not None


def test_finalize_success_keeps_the_slot_and_metadata():
    rid = feature_quota.reserve_use(org_id="o", feature="f", limit=3, window_hours=720)
    feature_quota.finalize_use(rid, ok=True, provider="gemini", detail="x")
    assert feature_quota.count_for_org("o", feature="f", window_hours=720) == 1


def test_reserve_returns_none_when_unmetered(monkeypatch):
    # Default build is UNLIMITED — reserve() reserves nothing and returns None.
    monkeypatch.delenv("MEDIAHUB_QUOTA_CAPTION", raising=False)
    assert gov_quota.reserve("org-x", gov_quota_feature()) is None


def gov_quota_feature():
    from mediahub.governance import features

    return features.FEATURE_CAPTION


def test_reserve_raises_quota_exceeded_at_limit(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")
    feat = gov_quota_feature()
    rid = gov_quota.reserve("org-y", feat)
    assert rid is not None
    with pytest.raises(gov_quota.QuotaExceeded):
        gov_quota.reserve("org-y", feat)


def test_reserve_fails_open_on_db_error(monkeypatch):
    # A DB failure must NOT block a paying club — reserve returns None (proceed).
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")

    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(feature_quota, "reserve_use", boom)
    assert gov_quota.reserve("org-z", gov_quota_feature()) is None


def test_feature_scope_reserves_and_finalizes(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "2")
    feat = gov_quota_feature()
    # Two scopes succeed; the third is over the limit and raises on entry.
    with gov_context.feature_scope(feat, org_id="org-s"):
        pass
    with gov_context.feature_scope(feat, org_id="org-s"):
        pass
    assert feature_quota.count_for_org("org-s", feature="caption", window_hours=720) == 2
    with pytest.raises(gov_quota.QuotaExceeded):
        with gov_context.feature_scope(feat, org_id="org-s"):
            pass


def test_feature_scope_body_failure_releases_slot(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")
    feat = gov_quota_feature()
    with pytest.raises(ValueError):
        with gov_context.feature_scope(feat, org_id="org-f"):
            raise ValueError("body failed")
    # The failed body released its reservation — the slot is free again.
    assert feature_quota.count_for_org("org-f", feature="caption", window_hours=720) == 0
    with gov_context.feature_scope(feat, org_id="org-f"):
        pass
    assert feature_quota.count_for_org("org-f", feature="caption", window_hours=720) == 1
