"""
pb_history/store.py — per-tenant accumulating best-times store.

Every uploaded results file contributes its swims here; "is this a PB?" is then
a local lookup against the club's OWN real past results — deterministic, instant,
free at the margin, and more accurate every upload. This is the scalable PB
baseline: returning swimmers never touch the network, so the engine works for a
public, "anyone-anytime" product. It is NOT seed-time inference — every stored
time is a real swum result.

One SQLite file under ``DATA_DIR/pb_history.db`` (separate from data.db, like
memory.db). Rows are keyed by (tenant, meet, swimmer-identity, event) so:
  * the fastest swim of an event WITHIN a meet is kept (heats vs final), and
  * re-uploading a meet REPLACES its rows (idempotent), and
  * "prior best" excludes the current meet (no swim is its own baseline).

Multi-tenant: every row carries ``tenant_id`` and every query filters on it, so
one club's history can never leak into another's.
"""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

# Serialises writes WITHIN a process (gunicorn's threads); ACROSS processes the
# two gunicorn workers are serialised by SQLite's own WAL write-lock + the
# busy_timeout below, with _with_retry as a second layer (see record_meet).
_LOCK = threading.Lock()

# How long SQLite waits for a contended write lock before raising. Generous: a
# pb_history write is a tiny batch (milliseconds), so two workers committing at
# once never come close. Tunable for very busy deployments.
_BUSY_TIMEOUT_MS = 10_000


def _db_path() -> Path:
    env = os.environ.get("DATA_DIR")
    base = Path(env) if env else Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base / "pb_history.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    # WAL lets the two gunicorn workers read concurrently while one writes, and
    # is the multi-process-safe journal mode (same pattern as memory.db / the
    # scheduler). It is a persistent property of the file; setting it per
    # connection is an idempotent no-op after the first.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(conn)
    return conn


def _is_locked_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and ("locked" in msg or "busy" in msg)


def _with_retry(op: "Callable[[], object]", *, attempts: int = 5) -> object:
    """Run a DB op, retrying on a transient 'database is locked/busy'.

    busy_timeout already makes SQLite WAIT for the lock rather than fail, so this
    only ever fires in a pathological stall (e.g. a long WAL checkpoint while
    both workers commit). It exists so a concurrent worker's write is never
    SILENTLY dropped — the failure mode that loses PB history under load.
    """
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return op()
        except sqlite3.OperationalError as e:
            if not _is_locked_error(e):
                raise
            last = e
            time.sleep(min(0.4, 0.05 * (2**i)) + random.random() * 0.05)
    assert last is not None
    raise last


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pb_history (
            tenant_id   TEXT NOT NULL,
            meet_key    TEXT NOT NULL,
            identity    TEXT NOT NULL,
            event_key   TEXT NOT NULL,
            time_cs     INTEGER NOT NULL,
            swim_date   TEXT,
            meet_name   TEXT,
            name_key    TEXT NOT NULL DEFAULT '',
            inserted_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, meet_key, identity, event_key)
        );
        CREATE INDEX IF NOT EXISTS idx_pbh_lookup
            ON pb_history (tenant_id, identity, event_key);
        CREATE INDEX IF NOT EXISTS idx_pbh_subject
            ON pb_history (tenant_id, name_key);
        """
    )
    conn.commit()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PBHistoryStore:
    """Accumulating per-tenant best-times store. Construct once per use; cheap."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    # -- write -------------------------------------------------------------
    def record_meet(
        self,
        tenant_id: str,
        meet_key: str,
        rows: "Iterable[tuple[str, str, str, int, Optional[str], Optional[str]]]",
    ) -> int:
        """Record one meet's swims.

        ``rows`` is an iterable of ``(identity, name_key, event_key, time_cs,
        swim_date, meet_name)``. Within a (tenant, meet, identity, event) the
        FASTEST time is kept, so re-running a meet or a heats+final pair never
        inflates a baseline. ``name_key`` is stored so a data-subject erasure can
        find the swimmer's rows. Returns the number of rows written. Never raises
        — a history write must never break a run.
        """
        tenant_id = (tenant_id or "").strip()
        if not tenant_id or not meet_key:
            return 0
        payload = [
            (
                tenant_id,
                meet_key,
                ident,
                ev,
                int(cs),
                date or None,
                meet or None,
                nkey or "",
                _now(),
            )
            for (ident, nkey, ev, cs, date, meet) in rows
            if ident and ev and cs and int(cs) > 0
        ]
        if not payload:
            return 0

        def _write() -> int:
            with _LOCK:
                conn = _connect(self._db_path)
                try:
                    conn.executemany(
                        """
                        INSERT INTO pb_history
                            (tenant_id, meet_key, identity, event_key,
                             time_cs, swim_date, meet_name, name_key, inserted_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(tenant_id, meet_key, identity, event_key)
                        DO UPDATE SET
                            time_cs   = min(time_cs, excluded.time_cs),
                            swim_date = CASE WHEN excluded.time_cs < time_cs
                                            THEN excluded.swim_date ELSE swim_date END,
                            inserted_at = excluded.inserted_at
                        """,
                        payload,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return len(payload)

        try:
            return int(_with_retry(_write))
        except Exception as exc:
            # Surface the rare lost write instead of dropping it silently, so the
            # operator can see it rather than wonder why a baseline is thin.
            log.warning(
                "pb_history: could not record %d row(s) for tenant=%r meet=%r: %s",
                len(payload),
                tenant_id,
                meet_key,
                exc,
            )
            return 0

    # -- erasure (privacy) -------------------------------------------------
    def purge_subject(self, tenant_id: str, name_key: str) -> int:
        """Delete every row for one swimmer (by order-independent name key) within
        a tenant — the data-subject "forget me" right. Returns rows deleted."""
        tenant_id = (tenant_id or "").strip()
        name_key = (name_key or "").strip()
        if not tenant_id or not name_key:
            return 0
        return self._delete("WHERE tenant_id=? AND name_key=?", (tenant_id, name_key))

    def purge_tenant(self, tenant_id: str) -> int:
        """Delete all of a tenant's PB history (account/club deletion)."""
        tenant_id = (tenant_id or "").strip()
        if not tenant_id:
            return 0
        return self._delete("WHERE tenant_id=?", (tenant_id,))

    def _delete(self, where: str, params: tuple) -> int:
        def _do() -> int:
            with _LOCK:
                conn = _connect(self._db_path)
                try:
                    cur = conn.execute(f"DELETE FROM pb_history {where}", params)
                    conn.commit()
                    return cur.rowcount or 0
                finally:
                    conn.close()

        try:
            return int(_with_retry(_do))
        except Exception as exc:
            log.warning("pb_history: delete failed (%s): %s", where, exc)
            return 0

    # -- read --------------------------------------------------------------
    def prior_bests(
        self,
        tenant_id: str,
        identities: "Iterable[str]",
        exclude_meet_key: Optional[str] = None,
    ) -> "dict[str, dict[str, dict]]":
        """Best prior time per (identity, event), EXCLUDING ``exclude_meet_key``.

        Returns ``{identity: {event_key: {"time_cs", "date_iso", "meet"}}}``.
        Excluding the current meet means a swim is never its own baseline, so a
        PB is only ever asserted against a genuinely earlier result.
        """
        tenant_id = (tenant_id or "").strip()
        idents = [i for i in dict.fromkeys(identities) if i]
        if not tenant_id or not idents:
            return {}

        def _read() -> "dict[str, dict[str, dict]]":
            out: "dict[str, dict[str, dict]]" = {}
            conn = _connect(self._db_path)
            try:
                # Chunk the IN list to stay well under SQLite's variable cap.
                for start in range(0, len(idents), 400):
                    chunk = idents[start : start + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    params: list = [tenant_id, *chunk]
                    exclude_clause = ""
                    if exclude_meet_key:
                        exclude_clause = "AND meet_key != ?"
                        params.append(exclude_meet_key)
                    cur = conn.execute(
                        f"""
                        SELECT identity, event_key,
                               MIN(time_cs) AS best_cs
                        FROM pb_history
                        WHERE tenant_id = ?
                          AND identity IN ({placeholders})
                          {exclude_clause}
                        GROUP BY identity, event_key
                        """,
                        params,
                    )
                    rows = cur.fetchall()
                    # Second pass to recover the date/meet of each winning row.
                    for r in rows:
                        ident, ev, best_cs = r["identity"], r["event_key"], r["best_cs"]
                        meta = conn.execute(
                            """
                            SELECT swim_date, meet_name FROM pb_history
                            WHERE tenant_id=? AND identity=? AND event_key=? AND time_cs=?
                            """
                            + (" AND meet_key != ?" if exclude_meet_key else ""),
                            (
                                [tenant_id, ident, ev, best_cs, exclude_meet_key]
                                if exclude_meet_key
                                else [tenant_id, ident, ev, best_cs]
                            ),
                        ).fetchone()
                        out.setdefault(ident, {})[ev] = {
                            "time_cs": int(best_cs),
                            "date_iso": (meta["swim_date"] if meta else None) or "",
                            "meet": (meta["meet_name"] if meta else None) or "",
                        }
            finally:
                conn.close()
            return out

        try:
            return _with_retry(_read)  # type: ignore[return-value]
        except Exception as exc:
            log.warning("pb_history: prior_bests read failed for tenant=%r: %s", tenant_id, exc)
            return {}
