"""SQLite-backed CRUD for MediaAsset rows. File blobs live alongside in uploads/.

Schema is created lazily; all reads tolerate older row shapes by routing through
MediaAsset.from_dict.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import BinaryIO, Optional

from .models import MediaAsset

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    """Runtime data root, resolved from ``DATA_DIR`` at call time.

    The same convention ``video/projects.py`` and the rest of the app follow:
    storage lives under the ``DATA_DIR`` persistent disk (``/var/mediahub`` on the
    deploy), falling back to the package dir only when ``DATA_DIR`` is unset (dev /
    bare sandboxes). Hardcoding the package dir here wrote asset blobs and the
    ``data.db`` under the deployed code tree, which is root-owned and not writable
    by the runtime user (uid 10001) — so every footage/photo upload raised
    ``PermissionError`` → HTTP 500, and anything that did land there was lost on
    redeploy. Resolved per call (not at import) so a process that sets ``DATA_DIR``
    before first use — and the test suite — gets the right root.
    """
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1]


def _default_db_path() -> Path:
    return _data_dir() / "data.db"


def _default_uploads_dir() -> Path:
    return _data_dir() / "uploads_v4" / "media_library"


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
    edit_recipe TEXT,
    media_meta TEXT,
    annotation TEXT,
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
_DICT_FIELDS = {"description_parsed", "edit_recipe", "media_meta", "annotation"}

# Columns added after the original schema shipped — applied lazily to existing
# DBs so an older data.db keeps loading (additive, never destructive).
_ADDED_COLUMNS = (("edit_recipe", "TEXT"), ("media_meta", "TEXT"), ("annotation", "TEXT"))


class MediaLibraryStore:
    """Thread-safe SQLite-backed media asset store."""

    def __init__(self, db_path: Optional[Path] = None, uploads_dir: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.uploads_dir = Path(uploads_dir) if uploads_dir else _default_uploads_dir()
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with _lock, _connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            # Lazy migration: add any column introduced after the table first
            # shipped, so an older data.db upgrades in place on open.
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(media_assets)")}
            for col, decl in _ADDED_COLUMNS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE media_assets ADD COLUMN {col} {decl}")
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

    def merge_links(
        self,
        asset_id: str,
        *,
        athlete_names: Optional[list[str]] = None,
        meet_ids: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[MediaAsset]:
        """Additively merge link metadata onto an asset (never removes).

        The M4 write-back seam: a per-card picker confirm (or the M34 vision
        pass) remembers "this photo is OF this athlete / FROM this meet" by
        merging into ``linked_athlete_names`` / ``linked_meet_ids`` / ``tags``
        without duplicates (athlete names case-insensitively). Existing values
        always survive — human-entered links are never overwritten. Returns
        the saved asset, or ``None`` when the id is unknown.
        """
        asset = self.get(asset_id)
        if asset is None:
            return None

        def _merge(existing: list[str], extra: list[str], *, ci: bool) -> list[str]:
            out = list(existing or [])
            seen = {(v.lower() if ci else v) for v in out}
            for raw in extra or []:
                v = str(raw).strip()
                key = v.lower() if ci else v
                if v and key not in seen:
                    seen.add(key)
                    out.append(v)
            return out

        if athlete_names:
            asset.linked_athlete_names = _merge(asset.linked_athlete_names, athlete_names, ci=True)
        if meet_ids:
            asset.linked_meet_ids = _merge(asset.linked_meet_ids, meet_ids, ci=False)
        if tags:
            asset.tags = _merge(asset.tags, [str(t).lower() for t in tags], ci=False)
        return self.save(asset)

    def list_untagged(
        self, *, profile_id: Optional[str] = None, limit: int = 500
    ) -> list[MediaAsset]:
        """Photo assets with no athlete link, no tags, and no vision record.

        The M34 bulk "Describe N untagged photos" pass targets exactly these:
        image assets (footage and logos excluded) that neither a human
        description nor a previous vision pass has tagged yet.
        """
        skip_types = {"footage", "logo", "sponsor_logo", "brand_pattern"}
        out: list[MediaAsset] = []
        for a in self.list(profile_id=profile_id, limit=limit):
            if a.type in skip_types:
                continue
            vision = (
                a.description_parsed.get("vision")
                if isinstance(a.description_parsed, dict)
                else None
            )
            if a.linked_athlete_names or a.tags or vision:
                continue
            out.append(a)
        return out

    def backfill_measurements(
        self,
        *,
        profile_id: Optional[str] = None,
        force: bool = False,
        limit: int = 500,
    ) -> int:
        """One-shot re-measure of existing image assets (PHOTOS-1 backfill).

        Assets saved before the ingest metadata spine landed carry width=0 /
        orientation="unknown" and no ``media_meta["quality"]`` metrics, which
        pins the selector's quality and orientation axes. This walks stored
        assets (profile-scoped when ``profile_id`` is given) and re-measures
        any image whose measurements are missing — or every image when
        ``force=True``. Measurement is EXIF-aware in memory; the stored file
        bytes are never rewritten here (only fresh uploads get orientation
        baked in). Returns the number of assets updated. Call on demand (an
        operator/maintenance action), it is not run automatically.
        """
        from .tagger import measure_asset

        updated = 0
        for asset in self.list(profile_id=profile_id, limit=limit):
            if asset.type == "footage":
                continue
            has_quality = isinstance(asset.media_meta, dict) and isinstance(
                asset.media_meta.get("quality"), dict
            )
            if not force and asset.width > 0 and asset.height > 0 and has_quality:
                continue
            if not asset.path or not os.path.exists(asset.path):
                continue
            if measure_asset(asset):
                self.save(asset)
                updated += 1
        return updated

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
        target = self._new_blob_path(original_filename, profile_id)
        target.write_bytes(src_bytes)
        return target

    def store_blob_stream(
        self, fileobj: BinaryIO, original_filename: str, profile_id: Optional[str] = None
    ) -> Path:
        """Stream a file-like object to the blob path without buffering it in memory.

        ``shutil.copyfileobj`` copies in fixed-size chunks, so peak memory is the
        copy buffer, not the whole file — the difference between holding a 500 MB
        clip in RAM and not. Used by the footage-upload path, where the uploaded
        part is already a temp file on disk (Werkzeug spools large parts), so this
        is a bounded disk→disk copy.
        """
        target = self._new_blob_path(original_filename, profile_id)
        try:
            with open(target, "wb") as dst:
                shutil.copyfileobj(fileobj, dst)
        except BaseException:
            # A mid-copy failure (disk full, I/O error) must not leave an
            # orphaned partial blob no DB row references.
            target.unlink(missing_ok=True)
            raise
        return target

    def _new_blob_path(self, original_filename: str, profile_id: Optional[str]) -> Path:
        """Build a unique blob path under uploads/media_library/<profile>/."""
        suffix = Path(original_filename).suffix or ".bin"
        target_dir = self.uploads_dir / (profile_id or "_shared")
        target_dir.mkdir(parents=True, exist_ok=True)
        unique = f"{uuid.uuid4().hex[:10]}_{Path(original_filename).stem}{suffix}"
        return target_dir / unique

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
