"""video/projects.py — persistence for footage timelines (roadmap 1.6).

A **video project** is a saved EDL the operator is editing: the timeline plus
its name, the footage it came from, and its approval state. It is the footage
path's equivalent of a content-pack card row — and like every other tenant
artefact, it is **scoped to a profile** (ADR-0003 isolation): a list is always
filtered by ``profile_id``, and a fetch returns the row so the *route* can
enforce that the caller's active profile matches before handing it over.

SQLite under ``DATA_DIR`` (the same ``data.db`` the rest of the app uses), lazy
schema, thread-safe — mirroring ``media_library.store``. Approval state is here
because **a human approves before export** (rule 6): a project renders for
preview at any time, but the export surface checks ``status == "approved"``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mediahub.video.edl import EDL

_lock = threading.Lock()

STATUSES = ("draft", "approved", "rejected")


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1]


def _db_path() -> Path:
    return _data_dir() / "data.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS video_projects (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    name TEXT,
    edl_json TEXT,
    source_asset_id TEXT,
    status TEXT,
    format_name TEXT,
    created_at REAL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_video_projects_profile ON video_projects(profile_id);
"""


@dataclass
class VideoProject:
    """One saved timeline + its metadata and approval state."""

    id: str
    profile_id: Optional[str]
    name: str = "Untitled clip"
    edl: EDL = field(default_factory=EDL)
    source_asset_id: Optional[str] = None
    status: str = "draft"
    format_name: str = "story"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "name": self.name,
            "edl": self.edl.to_dict(),
            "source_asset_id": self.source_asset_id,
            "status": self.status,
            "format_name": self.format_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _connect() -> sqlite3.Connection:
    """Open the DATA_DIR ``data.db`` and ensure the schema exists.

    The schema is (re)applied on every connection — ``CREATE TABLE IF NOT
    EXISTS`` is idempotent and microsecond-cheap — so the store stays correct
    even though ``DATA_DIR`` is resolved per connection (the process-level
    singleton must not pin a stale path).
    """
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


class VideoProjectStore:
    """Thread-safe SQLite CRUD for video projects, scoped per profile."""

    def __init__(self) -> None:
        with _lock, _connect() as conn:
            conn.commit()

    def save(self, project: VideoProject) -> VideoProject:
        if not project.id:
            project.id = "vid_" + uuid.uuid4().hex[:12]
        now = time.time()
        if not project.created_at:
            project.created_at = now
        project.updated_at = now
        if project.status not in STATUSES:
            project.status = "draft"
        row = (
            project.id,
            project.profile_id,
            project.name,
            json.dumps(project.edl.to_dict()),
            project.source_asset_id,
            project.status,
            project.format_name,
            project.created_at,
            project.updated_at,
        )
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO video_projects "
                "(id, profile_id, name, edl_json, source_asset_id, status, format_name, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET profile_id=excluded.profile_id, "
                "name=excluded.name, edl_json=excluded.edl_json, "
                "source_asset_id=excluded.source_asset_id, status=excluded.status, "
                "format_name=excluded.format_name, updated_at=excluded.updated_at",
                row,
            )
            conn.commit()
        return project

    def get(self, project_id: str) -> Optional[VideoProject]:
        with _lock, _connect() as conn:
            cur = conn.execute("SELECT * FROM video_projects WHERE id=?", (project_id,))
            row = cur.fetchone()
        return self._row_to_project(row) if row else None

    def list(self, *, profile_id: Optional[str], limit: int = 200) -> list[VideoProject]:
        with _lock, _connect() as conn:
            cur = conn.execute(
                "SELECT * FROM video_projects WHERE profile_id IS ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (profile_id, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_project(r) for r in rows]

    def set_status(self, project_id: str, status: str) -> Optional[VideoProject]:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}; valid: {STATUSES}")
        p = self.get(project_id)
        if not p:
            return None
        p.status = status
        return self.save(p)

    def delete(self, project_id: str) -> bool:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM video_projects WHERE id=?", (project_id,))
            conn.commit()
            return cur.rowcount > 0

    def _row_to_project(self, row: sqlite3.Row) -> VideoProject:
        d = dict(row)
        try:
            edl = EDL.from_dict(json.loads(d.get("edl_json") or "{}"))
        except (ValueError, TypeError):
            edl = EDL()
        return VideoProject(
            id=d.get("id", ""),
            profile_id=d.get("profile_id"),
            name=d.get("name") or "Untitled clip",
            edl=edl,
            source_asset_id=d.get("source_asset_id"),
            status=d.get("status") or "draft",
            format_name=d.get("format_name") or "story",
            created_at=d.get("created_at") or 0.0,
            updated_at=d.get("updated_at") or 0.0,
        )


_store: Optional[VideoProjectStore] = None


def get_store() -> VideoProjectStore:
    global _store
    if _store is None:
        _store = VideoProjectStore()
    return _store


__all__ = ["VideoProject", "VideoProjectStore", "get_store", "STATUSES"]
