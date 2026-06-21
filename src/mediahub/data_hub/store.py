"""data_hub.store — the club's own editable tables (roadmap 1.13).

The canonical views in ``tables.py`` are read-only mirrors of the engine. This
module holds the tables a club *owns and edits*: rosters, sponsor facts, form
responses, and any custom sheet. They live in the shared SQLite store
(``DATA_DIR/data.db``) and are **org-scoped by ``profile_id``** like every other
tenant store (ADR-0014) — one club can never see another's tables.

A table is two rows of storage: its definition (title, columns) and its rows
(each a JSON blob of ``{column_key: DataCell}``). Storing rows as JSON keeps the
per-cell provenance intact through a round-trip, and lets columns change without
a schema migration. Everything takes an optional ``db_path`` so tests run
against a throwaway database.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import DataCell, DataColumn, DataTable


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return data_dir / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = _db_path(db_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_hub_tables (
    table_id    TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'org',
    columns_json TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dh_tables_profile
    ON data_hub_tables(profile_id);

CREATE TABLE IF NOT EXISTS data_hub_rows (
    table_id   TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    row_id     TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    cells_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (table_id, row_id)
);
CREATE INDEX IF NOT EXISTS idx_dh_rows_table
    ON data_hub_rows(profile_id, table_id, position);
"""


def ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------


def create_table(
    profile_id: str,
    title: str,
    columns: list[DataColumn],
    *,
    kind: str = "org",
    description: str = "",
    db_path: Optional[Path] = None,
) -> str:
    """Create an empty org table; return its ``table_id`` (``org<hex>``)."""
    ensure_schema(db_path)
    table_id = _new_id("org")
    now = _now()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO data_hub_tables "
            "(table_id, profile_id, title, kind, columns_json, description, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                table_id,
                profile_id,
                title.strip() or "Untitled table",
                "org",
                json.dumps([c.to_dict() for c in columns]),
                description,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return table_id


def set_columns(
    profile_id: str,
    table_id: str,
    columns: list[DataColumn],
    *,
    db_path: Optional[Path] = None,
) -> bool:
    """Replace a table's column definitions (e.g. after adding a derived column)."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE data_hub_tables SET columns_json=?, updated_at=? "
            "WHERE table_id=? AND profile_id=?",
            (json.dumps([c.to_dict() for c in columns]), _now(), table_id, profile_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def rename_table(
    profile_id: str, table_id: str, title: str, *, db_path: Optional[Path] = None
) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE data_hub_tables SET title=?, updated_at=? WHERE table_id=? AND profile_id=?",
            (title.strip() or "Untitled table", _now(), table_id, profile_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_table(profile_id: str, table_id: str, *, db_path: Optional[Path] = None) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM data_hub_tables WHERE table_id=? AND profile_id=?",
            (table_id, profile_id),
        )
        conn.execute(
            "DELETE FROM data_hub_rows WHERE table_id=? AND profile_id=?",
            (table_id, profile_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_org_tables(profile_id: str, *, db_path: Optional[Path] = None) -> list[dict]:
    """Summaries of this org's editable tables (no row payloads loaded)."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT t.table_id, t.title, t.kind, t.description, t.columns_json, "
            "(SELECT COUNT(*) FROM data_hub_rows r WHERE r.table_id=t.table_id) AS n_rows "
            "FROM data_hub_tables t WHERE t.profile_id=? ORDER BY t.updated_at DESC",
            (profile_id,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        try:
            cols = json.loads(r["columns_json"]) or []
        except ValueError:
            cols = []
        out.append(
            {
                "table_id": r["table_id"],
                "title": r["title"],
                "kind": r["kind"] or "org",
                "editable": True,
                "n_columns": len(cols),
                "n_rows": int(r["n_rows"] or 0),
                "n_flagged": 0,
                "n_warnings": 0,
                "source": "club table",
                "description": r["description"] or "",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def upsert_row(
    profile_id: str,
    table_id: str,
    cells: dict,
    *,
    row_id: Optional[str] = None,
    position: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> str:
    """Insert or replace one row; return its ``row_id``.

    ``cells`` is ``{column_key: DataCell | dict}``.
    """
    payload = {
        k: (v.to_dict() if isinstance(v, DataCell) else DataCell.from_dict(v).to_dict())
        for k, v in cells.items()
    }
    rid = row_id or _new_id("row")
    conn = _connect(db_path)
    try:
        if position is None:
            cur = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM data_hub_rows "
                "WHERE table_id=? AND profile_id=?",
                (table_id, profile_id),
            ).fetchone()
            position = int(cur["pos"]) if cur else 0
        conn.execute(
            "INSERT INTO data_hub_rows (table_id, profile_id, row_id, position, cells_json, updated_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(table_id, row_id) DO UPDATE SET "
            "cells_json=excluded.cells_json, position=excluded.position, updated_at=excluded.updated_at",
            (table_id, profile_id, rid, int(position), json.dumps(payload), _now()),
        )
        conn.execute(
            "UPDATE data_hub_tables SET updated_at=? WHERE table_id=? AND profile_id=?",
            (_now(), table_id, profile_id),
        )
        conn.commit()
    finally:
        conn.close()
    return rid


def set_cell(
    profile_id: str,
    table_id: str,
    row_id: str,
    column_key: str,
    cell: DataCell,
    *,
    db_path: Optional[Path] = None,
) -> bool:
    """Update one cell in one row, preserving the rest of the row."""
    conn = _connect(db_path)
    try:
        r = conn.execute(
            "SELECT cells_json FROM data_hub_rows WHERE table_id=? AND profile_id=? AND row_id=?",
            (table_id, profile_id, row_id),
        ).fetchone()
        if not r:
            return False
        try:
            cells = json.loads(r["cells_json"]) or {}
        except ValueError:
            cells = {}
        cells[column_key] = cell.to_dict()
        conn.execute(
            "UPDATE data_hub_rows SET cells_json=?, updated_at=? "
            "WHERE table_id=? AND profile_id=? AND row_id=?",
            (json.dumps(cells), _now(), table_id, profile_id, row_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_row(
    profile_id: str, table_id: str, row_id: str, *, db_path: Optional[Path] = None
) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM data_hub_rows WHERE table_id=? AND profile_id=? AND row_id=?",
            (table_id, profile_id, row_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_org_table(
    profile_id: str, table_id: str, *, db_path: Optional[Path] = None
) -> Optional[DataTable]:
    """Load a full editable table (definition + rows) as a :class:`DataTable`."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        meta = conn.execute(
            "SELECT title, kind, description, columns_json FROM data_hub_tables "
            "WHERE table_id=? AND profile_id=?",
            (table_id, profile_id),
        ).fetchone()
        if not meta:
            return None
        row_rows = conn.execute(
            "SELECT row_id, cells_json FROM data_hub_rows "
            "WHERE table_id=? AND profile_id=? ORDER BY position, row_id",
            (table_id, profile_id),
        ).fetchall()
    finally:
        conn.close()

    try:
        col_defs = json.loads(meta["columns_json"]) or []
    except ValueError:
        col_defs = []
    columns = [DataColumn.from_dict(c) for c in col_defs if isinstance(c, dict)]

    rows: list[dict] = []
    row_ids: list[str] = []
    for rr in row_rows:
        try:
            cells = json.loads(rr["cells_json"]) or {}
        except ValueError:
            cells = {}
        rows.append({k: DataCell.from_dict(v) for k, v in cells.items()})
        row_ids.append(rr["row_id"])

    table = DataTable(
        table_id=table_id,
        title=meta["title"],
        kind="org",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=True,
        source="club table",
        description=meta["description"] or "",
    )
    # Stash the parallel row-id list so callers can address rows for edits.
    table.__dict__["_row_ids"] = row_ids
    return table


def row_ids_for(table: DataTable) -> list[str]:
    """The DB row ids that back a table loaded via :func:`get_org_table`."""
    return list(table.__dict__.get("_row_ids", []))


__all__ = [
    "ensure_schema",
    "create_table",
    "set_columns",
    "rename_table",
    "delete_table",
    "list_org_tables",
    "upsert_row",
    "set_cell",
    "delete_row",
    "get_org_table",
    "row_ids_for",
]
