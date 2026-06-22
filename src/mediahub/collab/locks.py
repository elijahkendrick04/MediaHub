"""collab/locks.py — per-card element locks (roadmap 1.18).

"Lock the sponsor strip." A reviewer can pin individual elements of a card's
design so a later copilot edit (or inspector toggle) can't change them. The lock
is *advisory metadata* enforced at edit time — the renderer never sees it; the
patch applier (``assistant.patch.apply_patch``) and the caption/inspector edit
route consult the locked set and refuse a change that would touch a locked
element.

Stored in the shared ``data.db`` beside :mod:`mediahub.collab.threads`, same
conventions (short-lived connection, idempotent schema, ``db_path`` override,
``delete_for_run`` for the erasure cascade). Locks are per ``(run, card,
element)`` — a small, closed vocabulary of element keys the UI exposes.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

# The closed set of lockable elements. Each maps to one or more edit operations
# the patch applier / inspector route check against (see assistant.patch).
LOCKABLE_ELEMENTS: frozenset[str] = frozenset(
    {
        "headline",
        "subhead",
        "hook",
        "palette",
        "layout",
        "accent",
        "photo",
        "sponsor",
        "format",
    }
)

MAX_BY_LEN = 254


class LockError(ValueError):
    """Unknown lockable element."""


def _default_db_path() -> Path:
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collab_locks (
            run_id      TEXT NOT NULL,
            card_id     TEXT NOT NULL,
            element     TEXT NOT NULL,
            locked_by   TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            PRIMARY KEY (run_id, card_id, element)
        );
        CREATE INDEX IF NOT EXISTS idx_collab_locks_run_card
            ON collab_locks(run_id, card_id);
        """
    )
    conn.commit()


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()


def _clean_element(element: Optional[str]) -> str:
    e = (element or "").strip().lower()
    if e not in LOCKABLE_ELEMENTS:
        raise LockError(f"'{element}' is not a lockable element")
    return e


def set_lock(
    run_id: str,
    card_id: str,
    element: str,
    locked: bool,
    *,
    by: str = "",
    db_path: Optional[Path] = None,
) -> bool:
    """Lock or unlock one element of a card. Returns the new locked state."""
    el = _clean_element(element)
    run_id = (run_id or "").strip()
    card_id = (card_id or "").strip()
    if not run_id or not card_id:
        raise LockError("run_id and card_id are required")
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if locked:
            conn.execute(
                "INSERT OR REPLACE INTO collab_locks(run_id,card_id,element,locked_by,created_at) "
                "VALUES(?,?,?,?,?)",
                (run_id, card_id, el, (by or "").strip().lower()[:MAX_BY_LEN], time.time()),
            )
        else:
            conn.execute(
                "DELETE FROM collab_locks WHERE run_id=? AND card_id=? AND element=?",
                (run_id, card_id, el),
            )
        conn.commit()
    finally:
        conn.close()
    return bool(locked)


def locked_elements(run_id: str, card_id: str, *, db_path: Optional[Path] = None) -> set[str]:
    """The set of locked element keys for a card (the patch applier reads this)."""
    run_id = (run_id or "").strip()
    card_id = (card_id or "").strip()
    if not run_id or not card_id:
        return set()
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT element FROM collab_locks WHERE run_id=? AND card_id=?",
            (run_id, card_id),
        ).fetchall()
    finally:
        conn.close()
    return {r["element"] for r in rows}


def is_locked(run_id: str, card_id: str, element: str, *, db_path: Optional[Path] = None) -> bool:
    try:
        el = _clean_element(element)
    except LockError:
        return False
    return el in locked_elements(run_id, card_id, db_path=db_path)


def list_locks(run_id: str, card_id: str, *, db_path: Optional[Path] = None) -> list[dict]:
    """Locked elements for a card with metadata, for the UI."""
    run_id = (run_id or "").strip()
    card_id = (card_id or "").strip()
    if not run_id or not card_id:
        return []
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT element, locked_by, created_at FROM collab_locks "
            "WHERE run_id=? AND card_id=? ORDER BY element ASC",
            (run_id, card_id),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"element": r["element"], "locked_by": r["locked_by"] or "", "at": float(r["created_at"])}
        for r in rows
    ]


def delete_for_run(run_id: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every lock for a run — the erasure cascade calls this."""
    if not (run_id or "").strip():
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM collab_locks WHERE run_id=?", (run_id,))
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


__all__ = [
    "LOCKABLE_ELEMENTS",
    "LockError",
    "init_schema",
    "set_lock",
    "locked_elements",
    "is_locked",
    "list_locks",
    "delete_for_run",
]
