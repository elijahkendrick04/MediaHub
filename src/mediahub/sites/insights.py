"""sites.insights — privacy-respecting page-view counts (roadmap 1.16).

First-party, **counts not tracking**: a public page view increments a coarse
``(profile_id, site_id, page_slug, day)`` counter and nothing else — no IP, no user
agent, no cookie, no cross-site identifier, no per-visitor record. That keeps the
feature lawful-by-design (no consent banner needed) while still giving a club the
"how many people saw it" number that 1.14 analytics will surface. Storage is SQLite
under ``DATA_DIR``, org+site scoped.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return Path(os.environ.get("DATA_DIR", ".")).resolve() / "site_insights.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = _db_path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS site_views ("
        "profile_id TEXT NOT NULL, site_id TEXT NOT NULL, page_slug TEXT NOT NULL, "
        "day TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (profile_id, site_id, page_slug, day))"
    )
    return conn


def record_view(
    profile_id: str,
    site_id: str,
    page_slug: str,
    *,
    day: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Count one view of a page. Best-effort: never raises into the request path."""
    d = day or date.today().isoformat()
    slug = page_slug or "index"
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO site_views (profile_id, site_id, page_slug, day, views) "
                "VALUES (?,?,?,?,1) "
                "ON CONFLICT(profile_id, site_id, page_slug, day) DO UPDATE SET views=views+1",
                (profile_id, site_id, slug, d),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def view_counts(
    profile_id: str,
    site_id: str,
    *,
    db_path: Optional[Path] = None,
) -> dict:
    """Aggregated view counts for a site: total + by-page + by-day (org+site scoped)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT page_slug, day, views FROM site_views WHERE profile_id=? AND site_id=?",
            (profile_id, site_id),
        ).fetchall()
    finally:
        conn.close()
    total = 0
    by_page: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for r in rows:
        v = int(r["views"])
        total += v
        by_page[r["page_slug"]] = by_page.get(r["page_slug"], 0) + v
        by_day[r["day"]] = by_day.get(r["day"], 0) + v
    return {"total": total, "by_page": by_page, "by_day": by_day}


__all__ = ["record_view", "view_counts"]
