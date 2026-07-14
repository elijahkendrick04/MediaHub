"""O(1) ``vid → (run_id, brief_id)`` index for the ``/api/visual/<vid>`` routes.

Both visual-serving routes (``GET /api/visual/<vid>`` and its
``/png/<format_name>`` sibling) used to locate a visual by nested-walking every
run directory under ``RUNS_DIR`` and ``json.loads``-ing every ``visual.json``
until ``vid`` matched — ``O(all-tenant-runs × visuals-per-run)`` on hot
``<img src>`` routes emitted many-per-page. This module keeps a tiny SQLite
index in the *same* ``data.db`` the runs table lives in, so the lookup is a
single indexed ``SELECT``.

``persist_visual`` stamps the index the moment a visual is written; the routes
also backfill it lazily on a miss, so runs created before the index existed (or
left stale by a torn write) still resolve without any migration step — the
first request for such a run walks once and self-heals to O(1) thereafter.

The index stores only opaque ids (``vid``, ``run_id``, ``brief_id``) — never a
caption, name or path — so it carries no personal data and is safe to rebuild
from the sidecars at any time. It is deliberately *not* the source of truth for
the response bytes: the routes always re-read the ``visual.json`` sidecar the
index points at (a single O(1) file read), so a stale index row can never serve
the wrong bytes — it simply degrades to the walk.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional


def _db_path() -> Path:
    """Resolve ``data.db`` the same way ``web.web.DB_PATH`` does.

    ``web.py``: ``DATA_DIR = env DATA_DIR or <src/mediahub>`` and
    ``DB_PATH = DATA_DIR / "data.db"`` — the ``RUNS_DIR`` override does **not**
    move the DB. Mirror that exactly (resolved per call, never cached, so a
    test that repoints ``DATA_DIR`` mid-process hits the right file). This file
    lives at ``src/mediahub/content_pack_visual/visual_index.py``, so
    ``parents[1]`` is ``src/mediahub`` — the local-dev default DATA_DIR.
    """
    data_env = os.environ.get("DATA_DIR")
    if data_env:
        return Path(data_env) / "data.db"
    return Path(__file__).resolve().parents[1] / "data.db"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the ``visual_index`` table + its run index if absent.

    Idempotent ``CREATE ... IF NOT EXISTS`` — re-applied on every connection
    (the pattern the other per-feature stores use). Also invoked from
    ``web._init_db`` so the run-erasure cascade ``DELETE`` never meets a missing
    table on a fresh DB. The schema is owned here, single-source.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS visual_index (
            vid      TEXT PRIMARY KEY,
            run_id   TEXT NOT NULL,
            brief_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_visual_index_run ON visual_index(run_id);
        """
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    ensure_schema(conn)
    return conn


def _vids_from_payload(payload: dict) -> set[str]:
    """Every ``vid`` that must resolve to this sidecar.

    A ``visual.json`` records a primary ``id`` plus a ``visual_ids`` map (one
    per rendered format). The routes match ``payload["id"] == vid or vid in
    visual_ids``, so both forms must land in the index.
    """
    vids: set[str] = set()
    for k in payload.get("visual_ids") or {}:
        if k:
            vids.add(str(k))
    pid = payload.get("id")
    if pid:
        vids.add(str(pid))
    return vids


def index_visual(run_id: str, brief_id: str, payload: dict) -> None:
    """Point every vid in ``payload`` at ``(run_id, brief_id)``.

    ``INSERT OR REPLACE`` so a re-render (which rewrites the sidecar) refreshes
    the mapping. Best-effort at call sites — callers wrap this so a DB hiccup
    never sinks a persist or a request.
    """
    if not run_id or not brief_id:
        return
    vids = _vids_from_payload(payload if isinstance(payload, dict) else {})
    if not vids:
        return
    conn = _connect()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO visual_index (vid, run_id, brief_id) VALUES (?, ?, ?)",
            [(vid, run_id, brief_id) for vid in vids],
        )
        conn.commit()
    finally:
        conn.close()


def lookup(vid: str) -> Optional[tuple[str, str]]:
    """Return ``(run_id, brief_id)`` for ``vid``, or ``None`` if unknown."""
    if not vid:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_id, brief_id FROM visual_index WHERE vid = ?", (vid,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return str(row[0]), str(row[1])


def forget(vid: str) -> None:
    """Drop a stale row (its sidecar is gone or no longer carries ``vid``)."""
    if not vid:
        return
    conn = _connect()
    try:
        conn.execute("DELETE FROM visual_index WHERE vid = ?", (vid,))
        conn.commit()
    finally:
        conn.close()
