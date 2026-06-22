"""sites.widget_state — vote tallies for the poll/Q&A widget (roadmap 1.16).

The only widget with server-side state is the poll: it stores **counts per option**
and nothing else — no voter identity, no IP, no tracking (privacy-respecting, like
the insights layer). Counts are org+site+widget scoped and incremented atomically in
SQLite under ``DATA_DIR``. A coarse per-option ceiling guards against a runaway
single option from automated spam.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

_MAX_VOTES_PER_OPTION = 1_000_000  # sanity ceiling; real spam control is at the web layer


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return Path(os.environ.get("DATA_DIR", ".")).resolve() / "site_widgets.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = _db_path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS site_poll_votes ("
        "profile_id TEXT NOT NULL, site_id TEXT NOT NULL, widget_id TEXT NOT NULL, "
        "option TEXT NOT NULL, votes INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, "
        "PRIMARY KEY (profile_id, site_id, widget_id, option))"
    )
    return conn


def record_vote(
    profile_id: str,
    site_id: str,
    widget_id: str,
    option: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """Increment ``option`` by one and return the full count map for the widget."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO site_poll_votes (profile_id, site_id, widget_id, option, votes, updated_at) "
            "VALUES (?,?,?,?,1,?) "
            "ON CONFLICT(profile_id, site_id, widget_id, option) "
            "DO UPDATE SET votes=MIN(votes+1, ?), updated_at=?",
            (
                profile_id,
                site_id,
                widget_id,
                option,
                time.time(),
                _MAX_VOTES_PER_OPTION,
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return vote_counts(profile_id, site_id, widget_id, db_path=db_path)


def vote_counts(
    profile_id: str,
    site_id: str,
    widget_id: str,
    *,
    db_path: Optional[Path] = None,
) -> dict[str, int]:
    """The current count per option for one poll widget (org+site scoped)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT option, votes FROM site_poll_votes "
            "WHERE profile_id=? AND site_id=? AND widget_id=?",
            (profile_id, site_id, widget_id),
        ).fetchall()
    finally:
        conn.close()
    return {r["option"]: int(r["votes"]) for r in rows}


__all__ = ["record_vote", "vote_counts"]
