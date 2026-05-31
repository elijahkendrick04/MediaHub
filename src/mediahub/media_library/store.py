"""SQLite-backed CRUD for MediaAsset rows. File blobs live alongside in uploads/.

Schema is created lazily; all reads tolerate older row shapes by routing through
MediaAsset.from_dict.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from .models import MediaAsset

log = logging.getLogger(__name__)


_DEFAULT_DB = Path(__file__).resolve().parents[1] / "data.db"
_DEFAULT_UPLOADS = Path(__file__).resolve().parents[1] / "uploads_v4" / "media_library"


_lock = threading.Lock()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    filename TEXT,
    path TEXT,
    type TEXT,
    description_raw TEXT,
    description_parsed TEXT,
    linked_athlete_ids TEXT,
    linked_athlete_names TEXT,
    linked_meet_ids TEXT,
    linked_venue TEXT,
    linked_event TEXT,
    profile_id TEXT,
    permission_status TEXT,
    approval_status TEXT,
    width INTEGER,
    height INTEGER,
    orientation TEXT,
    dominant_colours TEXT,
    has_face INTEGER,
    safe_for_minors INTEGER,
    cutout_path TEXT,
    source_url TEXT,
    source_attribution TEXT,
    source_licence TEXT,
    photographer TEXT,
    uploaded_at TEXT,
    uploaded_by TEXT,
    used_in TEXT,
    notes TEXT,
    tags TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_profile ON media_assets(profile_id);
CREATE INDEX IF NOT EXISTS idx_media_type ON media_assets(type);
"""


_LIST_FIELDS = {
    "linked_athlete_ids",
    "linked_athlete_names",
    "linked_meet_ids",
    "dominant_colours",
    "used_in",
    "tags",
}
_DICT_FIELDS = {"description_parsed"}


class MediaLibraryStore:
    """Thread-safe SQLite-backed media asset store."""

    def __init__(self, db_path: Optional[Path] = None, uploads_dir: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.uploads_dir = Path(uploads_dir) if uploads_dir else _DEFAULT_UPLOADS
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with _lock, _connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    # ------------------------------------------------------------------
    # Insert / update
    # ------------------------------------------------------------------

    def save(self, asset: MediaAsset) -> MediaAsset:
        if not asset.id:
            asset.id = "ma_" + uuid.uuid4().hex[:12]
        row = asset.to_dict()
        # Serialise lists/dicts to JSON
        for k in _LIST_FIELDS | _DICT_FIELDS:
            row[k] = json.dumps(row.get(k) or ([] if k in _LIST_FIELDS else {}))
        # Booleans → ints
        row["safe_for_minors"] = 1 if row.get("safe_for_minors") else 0
        row["has_face"] = None if row.get("has_face") is None else (1 if row["has_face"] else 0)

        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        sql = (
            f"INSERT INTO media_assets ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {update_clause}"
        )
        with _lock, _connect(self.db_path) as conn:
            conn.execute(sql, [row[c] for c in cols])
            conn.commit()
        return asset

    def update_fields(self, asset_id: str, fields: dict) -> Optional[MediaAsset]:
        existing = self.get(asset_id)
        if not existing:
            return None
        for k, v in fields.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        return self.save(existing)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> Optional[MediaAsset]:
        with _lock, _connect(self.db_path) as conn:
            cur = conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,))
            row = cur.fetchone()
        return self._row_to_asset(row) if row else None

    def list(
        self,
        *,
        profile_id: Optional[str] = None,
        asset_type: Optional[str] = None,
        athlete_id: Optional[str] = None,
        athlete_name: Optional[str] = None,
        venue: Optional[str] = None,
        limit: int = 500,
    ) -> list[MediaAsset]:
        sql = "SELECT * FROM media_assets WHERE 1=1"
        args: list = []
        if profile_id:
            sql += " AND profile_id=?"
            args.append(profile_id)
        if asset_type:
            sql += " AND type=?"
            args.append(asset_type)
        if venue:
            sql += " AND linked_venue LIKE ?"
            args.append(f"%{venue}%")
        sql += " ORDER BY uploaded_at DESC LIMIT ?"
        args.append(limit)
        with _lock, _connect(self.db_path) as conn:
            cur = conn.execute(sql, args)
            rows = cur.fetchall()
        assets = [self._row_to_asset(r) for r in rows]
        # Post-filter for athlete (stored as JSON list)
        if athlete_id:
            assets = [a for a in assets if athlete_id in a.linked_athlete_ids]
        if athlete_name:
            needle = athlete_name.lower()
            assets = [
                a
                for a in assets
                if any(needle in (n or "").lower() for n in a.linked_athlete_names)
                or needle in (a.description_raw or "").lower()
            ]
        return assets

    def delete(self, asset_id: str) -> bool:
        asset = self.get(asset_id)
        if not asset:
            return False
        with _lock, _connect(self.db_path) as conn:
            conn.execute("DELETE FROM media_assets WHERE id=?", (asset_id,))
            conn.commit()
        # Remove file blobs (best-effort)
        for p in (asset.path, asset.cutout_path):
            if p and os.path.exists(p) and self.uploads_dir.resolve() in Path(p).resolve().parents:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        return True

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def store_blob(
        self, src_bytes: bytes, original_filename: str, profile_id: Optional[str] = None
    ) -> Path:
        """Save raw bytes under uploads/media_library/<profile>/<id>_<name>."""
        suffix = Path(original_filename).suffix or ".bin"
        target_dir = self.uploads_dir / (profile_id or "_shared")
        target_dir.mkdir(parents=True, exist_ok=True)
        unique = f"{uuid.uuid4().hex[:10]}_{Path(original_filename).stem}{suffix}"
        target = target_dir / unique
        target.write_bytes(src_bytes)
        return target

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _row_to_asset(self, row: sqlite3.Row) -> MediaAsset:
        d = dict(row)
        # Booleans
        if d.get("safe_for_minors") is not None:
            d["safe_for_minors"] = bool(d["safe_for_minors"])
        if d.get("has_face") is not None:
            d["has_face"] = bool(d["has_face"])
        return MediaAsset.from_dict(d)


# Module-level convenience singleton (lazy)
_default_store: Optional[MediaLibraryStore] = None


def get_store() -> MediaLibraryStore:
    global _default_store
    if _default_store is None:
        _default_store = MediaLibraryStore()
    return _default_store


__all__ = ["MediaLibraryStore", "get_store"]
