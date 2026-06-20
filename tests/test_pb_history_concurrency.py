"""Concurrency guard for the PB-history store.

Production runs gunicorn with two worker PROCESSES sharing one SQLite file
(`pb_history.db`). Two processes writing one SQLite file is the classic source
of "database is locked" / lost writes — so this test proves the store survives
it: WAL + busy_timeout + a lock-retry mean concurrent writers neither error nor
drop a row, and the ON CONFLICT min() upsert stays correct under contention.

Uses real OS processes (not threads) to exercise the cross-process path, plus a
threads case for the within-worker path.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mediahub.pb_history.store import PBHistoryStore  # noqa: E402


# Module-level workers so they are picklable for the fork/spawn pool.
def _write_distinct(args):
    db, wid, n = args
    store = PBHistoryStore(db_path=Path(db))
    ok = 0
    for i in range(n):
        ok += store.record_meet(
            "clubA", f"meet-{wid}-{i}",
            [(f"id-{wid}-{i}", "nk", "100FRLC", 6000 + i, "2026-01-01", "M")],
        )
    return ok


def _write_same_row(args):
    db, wid, n = args
    store = PBHistoryStore(db_path=Path(db))
    for i in range(n):
        # Everyone upserts the SAME (tenant, meet, identity, event); fastest=5000.
        store.record_meet(
            "clubA", "shared-meet",
            [("shared-id", "nk", "100FRLC", 5000 + (wid * 1000 + i) % 4000, "d", "M")],
        )
    return 1


def test_concurrent_processes_no_lost_writes(tmp_path):
    db = str(tmp_path / "pb_history.db")
    nproc, n = 4, 80  # 2x prod's worker count, 320 distinct writes
    with mp.get_context("fork").Pool(nproc) as pool:
        written = sum(pool.map(_write_distinct, [(db, w, n) for w in range(nproc)]))
    store = PBHistoryStore(db_path=Path(db))
    idents = [f"id-{w}-{i}" for w in range(nproc) for i in range(n)]
    present = len(store.prior_bests("clubA", idents, exclude_meet_key="zzz"))
    assert written == nproc * n, f"record path lost writes: {written} != {nproc * n}"
    assert present == nproc * n, f"rows lost: {present} != {nproc * n}"


def test_concurrent_processes_contended_min_wins(tmp_path):
    db = str(tmp_path / "pb_history.db")
    nproc, n = 4, 100
    with mp.get_context("fork").Pool(nproc) as pool:
        pool.map(_write_same_row, [(db, w, n) for w in range(nproc)])
    store = PBHistoryStore(db_path=Path(db))
    best = store.prior_bests("clubA", ["shared-id"], exclude_meet_key="zzz")
    assert best["shared-id"]["100FRLC"]["time_cs"] == 5000, "min() held under write contention"


def test_concurrent_threads_no_lost_writes(tmp_path):
    """Within one worker process, gunicorn threads share the store too."""
    db = str(tmp_path / "pb_history.db")
    nthreads, n = 8, 60
    errors: list = []

    def run(wid):
        try:
            _write_distinct((db, wid, n))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=run, args=(w,)) for w in range(nthreads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"thread writes raised: {errors}"
    store = PBHistoryStore(db_path=Path(db))
    idents = [f"id-{w}-{i}" for w in range(nthreads) for i in range(n)]
    assert len(store.prior_bests("clubA", idents, exclude_meet_key="zzz")) == nthreads * n
