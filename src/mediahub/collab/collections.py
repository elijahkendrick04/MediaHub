"""collab/collections.py — org-level collections over runs & packs (1.18).

"Folders" for a workspace: a club groups its meets/packs into named collections
("Summer League 2026", "County Champs") so a year's content isn't one flat list.
Deliberately a *join table*, not a field stamped onto each run/pack JSON — so
nothing in the run/pack persistence has to migrate, and one run can sit in
several collections.

Org-scoped (every collection belongs to one ``org_id``); the web layer gates on
the active workspace. Same data.db conventions as the rest of ``collab``, with
``delete_for_org`` (PC.13 whole-org deletion) and ``delete_run_everywhere`` (the
run-erasure cascade) so a collection never points at data that's gone.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

MAX_NAME_LEN = 120
ITEM_RUN = "run"
ITEM_PACK = "pack"
_ITEM_TYPES = {ITEM_RUN, ITEM_PACK}


class CollectionError(ValueError):
    """Invalid collection input."""


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
        CREATE TABLE IF NOT EXISTS collab_collections (
            id          TEXT PRIMARY KEY,
            org_id      TEXT NOT NULL,
            name        TEXT NOT NULL,
            created_at  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_collab_collections_org
            ON collab_collections(org_id, created_at);
        CREATE TABLE IF NOT EXISTS collab_collection_items (
            collection_id TEXT NOT NULL,
            item_type     TEXT NOT NULL,
            item_id       TEXT NOT NULL,
            added_at      REAL NOT NULL,
            PRIMARY KEY (collection_id, item_type, item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_collab_collection_items_lookup
            ON collab_collection_items(item_type, item_id);
        """
    )
    conn.commit()


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()


def _clean_name(name: Optional[str]) -> str:
    n = (name or "").strip()
    if not n:
        raise CollectionError("a collection needs a name")
    return n[:MAX_NAME_LEN]


def _clean_item_type(item_type: Optional[str]) -> str:
    t = (item_type or "").strip().lower()
    if t not in _ITEM_TYPES:
        raise CollectionError("item_type must be 'run' or 'pack'")
    return t


def create_collection(org_id: str, name: str, *, db_path: Optional[Path] = None) -> dict:
    org_id = (org_id or "").strip()
    if not org_id:
        raise CollectionError("org_id is required")
    name = _clean_name(name)
    cid = "col_" + uuid.uuid4().hex[:12]
    now = time.time()
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO collab_collections(id,org_id,name,created_at) VALUES(?,?,?,?)",
            (cid, org_id, name, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "org_id": org_id, "name": name, "created_at": now, "count": 0}


def rename_collection(
    org_id: str, collection_id: str, name: str, *, db_path: Optional[Path] = None
) -> bool:
    name = _clean_name(name)
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE collab_collections SET name=? WHERE id=? AND org_id=?",
            (name, collection_id, (org_id or "").strip()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_collection(org_id: str, collection_id: str, *, db_path: Optional[Path] = None) -> bool:
    """Delete a collection and its membership rows (the runs/packs themselves are
    untouched — a collection is only a grouping)."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        owns = conn.execute(
            "SELECT 1 FROM collab_collections WHERE id=? AND org_id=?",
            (collection_id, (org_id or "").strip()),
        ).fetchone()
        if owns is None:
            return False
        conn.execute("DELETE FROM collab_collection_items WHERE collection_id=?", (collection_id,))
        conn.execute("DELETE FROM collab_collections WHERE id=?", (collection_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def list_collections(org_id: str, *, db_path: Optional[Path] = None) -> list[dict]:
    """Org's collections, newest first, each with its item count."""
    org_id = (org_id or "").strip()
    if not org_id:
        return []
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, c.created_at, "
            "  (SELECT COUNT(*) FROM collab_collection_items i WHERE i.collection_id=c.id) AS count "
            "FROM collab_collections c WHERE c.org_id=? ORDER BY c.created_at DESC",
            (org_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "created_at": float(r["created_at"]),
            "count": int(r["count"]),
        }
        for r in rows
    ]


def _owns(conn: sqlite3.Connection, org_id: str, collection_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM collab_collections WHERE id=? AND org_id=?",
            (collection_id, (org_id or "").strip()),
        ).fetchone()
        is not None
    )


def add_item(
    org_id: str,
    collection_id: str,
    item_type: str,
    item_id: str,
    *,
    db_path: Optional[Path] = None,
) -> bool:
    item_type = _clean_item_type(item_type)
    item_id = (item_id or "").strip()
    if not item_id:
        raise CollectionError("item_id is required")
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if not _owns(conn, org_id, collection_id):
            return False  # can't add to another org's collection (isolation)
        conn.execute(
            "INSERT OR IGNORE INTO collab_collection_items"
            "(collection_id,item_type,item_id,added_at) VALUES(?,?,?,?)",
            (collection_id, item_type, item_id, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_item(
    org_id: str,
    collection_id: str,
    item_type: str,
    item_id: str,
    *,
    db_path: Optional[Path] = None,
) -> bool:
    item_type = _clean_item_type(item_type)
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if not _owns(conn, org_id, collection_id):
            return False
        cur = conn.execute(
            "DELETE FROM collab_collection_items "
            "WHERE collection_id=? AND item_type=? AND item_id=?",
            (collection_id, item_type, (item_id or "").strip()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_items(
    org_id: str, collection_id: str, *, db_path: Optional[Path] = None
) -> Optional[list[dict]]:
    """Items in a collection, or ``None`` when the collection isn't this org's."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if not _owns(conn, org_id, collection_id):
            return None
        rows = conn.execute(
            "SELECT item_type, item_id, added_at FROM collab_collection_items "
            "WHERE collection_id=? ORDER BY added_at DESC",
            (collection_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"item_type": r["item_type"], "item_id": r["item_id"], "added_at": float(r["added_at"])}
        for r in rows
    ]


def collections_for_item(
    org_id: str, item_type: str, item_id: str, *, db_path: Optional[Path] = None
) -> list[dict]:
    """Which of the org's collections an item is in (for an 'in collections' badge)."""
    item_type = _clean_item_type(item_type)
    org_id = (org_id or "").strip()
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT c.id, c.name FROM collab_collections c "
            "JOIN collab_collection_items i ON i.collection_id=c.id "
            "WHERE c.org_id=? AND i.item_type=? AND i.item_id=? ORDER BY c.name ASC",
            (org_id, item_type, (item_id or "").strip()),
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def delete_run_everywhere(run_id: str, *, db_path: Optional[Path] = None) -> int:
    """Remove a run from every collection — the run-erasure cascade calls this."""
    run_id = (run_id or "").strip()
    if not run_id:
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM collab_collection_items WHERE item_type=? AND item_id=?",
            (ITEM_RUN, run_id),
        )
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


def delete_for_org(org_id: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every collection (and its items) for an org — whole-org deletion."""
    org_id = (org_id or "").strip()
    if not org_id:
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM collab_collections WHERE org_id=?", (org_id,)
            ).fetchall()
        ]
        if ids:
            qmarks = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM collab_collection_items WHERE collection_id IN ({qmarks})", ids
            )
        cur = conn.execute("DELETE FROM collab_collections WHERE org_id=?", (org_id,))
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


__all__ = [
    "ITEM_RUN",
    "ITEM_PACK",
    "CollectionError",
    "init_schema",
    "create_collection",
    "rename_collection",
    "delete_collection",
    "list_collections",
    "add_item",
    "remove_item",
    "list_items",
    "collections_for_item",
    "delete_run_everywhere",
    "delete_for_org",
]
