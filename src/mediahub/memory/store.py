"""mediahub/memory/store.py — sqlite-vec vector store for semantic memory.

Lives in its OWN ``DATA_DIR/memory.db`` (NOT the shared ``data.db``) so a
failure to load the sqlite-vec C extension (a young v0.1.x extension) isolates
to the memory feature and never touches the critical app state in ``data.db``.

Every row carries ``tenant_id`` (the ClubProfile slug) so one club's memory is
never compared against another's, and ``embedder_model_id`` so vectors from
different embedding models are never mixed. Because a vec0 table fixes its
vector dimension at creation, vectors are partitioned into one table per
dimension (``vec_dim_<N>``); model and tenant are applied as scoping filters on
every query, so even two models sharing a dimension stay separated.

Brute-force exact KNN — 100% recall, ample at MediaHub's scale (far below the
~100k–1M-vector point where this would slow down). Kept behind this interface
so the backend stays swappable.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
DB_PATH = DATA_DIR / "memory.db"

_lock = threading.Lock()

_TABLE_RE = re.compile(r"vec_dim_(\d+)")


class MemoryStoreUnavailable(RuntimeError):
    """Raised when the sqlite-vec extension cannot be loaded."""


@dataclass(frozen=True)
class MemoryHit:
    distance: float
    caption: str
    event_context: str
    card_id: str
    run_id: str
    created_at: str


def _table_for_dim(dim: int) -> str:
    return f"vec_dim_{int(dim)}"


def _entry_rowid(tenant_id: str, entry_id: str) -> int:
    """Deterministic 56-bit positive rowid → idempotent upsert (re-storing the
    same (tenant, entry) overwrites instead of duplicating)."""
    h = hashlib.blake2b(f"{tenant_id}:{entry_id}".encode("utf-8"), digest_size=7)
    return int.from_bytes(h.digest(), "big")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        import sqlite_vec  # noqa: PLC0415 - optional native extension, lazy

        sqlite_vec.load(conn)
    except Exception as e:
        conn.close()
        raise MemoryStoreUnavailable(f"sqlite-vec extension could not be loaded: {e}") from e
    finally:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
    return conn


def is_available() -> bool:
    """True when sqlite-vec loads in this environment (best-effort, no raise)."""
    try:
        _connect().close()
        return True
    except Exception:
        return False


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _known_dims(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vec_dim_%'"
    ).fetchall()
    dims: list[int] = []
    for row in rows:
        m = _TABLE_RE.fullmatch(row[0])
        if m:
            dims.append(int(m.group(1)))
    return dims


def _ensure_table(conn: sqlite3.Connection, dim: int) -> str:
    name = _table_for_dim(dim)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0("
        f"embedding float[{int(dim)}], "
        "tenant_id text, embedder_model_id text, embedding_dim integer, "
        "card_id text, created_at text, "
        "+caption text, +event_context text, +run_id text)"
    )
    return name


def upsert(
    *,
    tenant_id: str,
    vector,
    model_id: str,
    caption: str,
    event_context: str,
    entry_id: Optional[str] = None,
    card_id: Optional[str] = None,
    run_id: str = "",
    created_at: Optional[str] = None,
) -> None:
    """Store (or replace) one memory row. Idempotent on (tenant_id, entry_id).

    The vector's length determines which ``vec_dim_<N>`` table it lands in.
    """
    from sqlite_vec import serialize_float32  # noqa: PLC0415

    vec = [float(x) for x in vector]
    dim = len(vec)
    if dim == 0:
        raise ValueError("cannot store an empty vector")
    eid = str(entry_id or card_id or "")
    if not tenant_id or not eid:
        raise ValueError("tenant_id and entry_id/card_id are required")
    created = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rid = _entry_rowid(str(tenant_id), eid)
    with _lock:
        conn = _connect()
        try:
            tbl = _ensure_table(conn, dim)
            conn.execute(f"DELETE FROM {tbl} WHERE rowid=?", (rid,))
            conn.execute(
                f"INSERT INTO {tbl}(rowid, embedding, tenant_id, embedder_model_id, "
                "embedding_dim, card_id, created_at, caption, event_context, run_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    serialize_float32(vec),
                    str(tenant_id),
                    str(model_id),
                    dim,
                    str(card_id or eid),
                    created,
                    str(caption),
                    str(event_context),
                    str(run_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def query(*, tenant_id: str, vector, model_id: str, k: int = 5) -> list[MemoryHit]:
    """Return up to ``k`` nearest prior memories for this tenant + model.

    Empty list when nothing is stored for the vector's dimension yet (never
    raises for a cold/empty store).
    """
    from sqlite_vec import serialize_float32  # noqa: PLC0415

    vec = [float(x) for x in vector]
    dim = len(vec)
    if dim == 0 or not tenant_id or not model_id:
        return []
    tbl = _table_for_dim(dim)
    kk = int(max(1, k))
    with _lock:
        conn = _connect()
        try:
            if not _table_exists(conn, tbl):
                return []
            rows = conn.execute(
                f"SELECT distance, caption, event_context, card_id, run_id, created_at "
                f"FROM {tbl} WHERE embedding MATCH ? AND tenant_id=? AND embedder_model_id=? "
                f"AND k={kk} ORDER BY distance",
                (serialize_float32(vec), str(tenant_id), str(model_id)),
            ).fetchall()
        finally:
            conn.close()
    return [
        MemoryHit(
            distance=float(r["distance"]),
            caption=r["caption"] or "",
            event_context=r["event_context"] or "",
            card_id=r["card_id"] or "",
            run_id=r["run_id"] or "",
            created_at=r["created_at"] or "",
        )
        for r in rows
    ]


def count(*, tenant_id: str, model_id: Optional[str] = None) -> int:
    """Number of stored memories for a tenant (optionally model-scoped)."""
    with _lock:
        conn = _connect()
        try:
            total = 0
            for d in _known_dims(conn):
                tbl = _table_for_dim(d)
                if model_id:
                    q = f"SELECT count(*) FROM {tbl} WHERE tenant_id=? AND embedder_model_id=?"
                    args: tuple = (str(tenant_id), str(model_id))
                else:
                    q = f"SELECT count(*) FROM {tbl} WHERE tenant_id=?"
                    args = (str(tenant_id),)
                total += conn.execute(q, args).fetchone()[0]
            return total
        finally:
            conn.close()


def clear(*, tenant_id: Optional[str] = None) -> None:
    """Delete memories — a single tenant's, or all. Admin/test helper."""
    with _lock:
        conn = _connect()
        try:
            for d in _known_dims(conn):
                tbl = _table_for_dim(d)
                if tenant_id:
                    conn.execute(f"DELETE FROM {tbl} WHERE tenant_id=?", (str(tenant_id),))
                else:
                    conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()


__all__ = [
    "MemoryStoreUnavailable",
    "MemoryHit",
    "DB_PATH",
    "is_available",
    "upsert",
    "query",
    "count",
    "clear",
]
