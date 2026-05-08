"""
swim_content_pb/cache.py
Versioned, source-stamped disk cache for PB snapshots.

V6 cache files include a schema_version field.
Old v3-cache files (without schema_version) are cache misses — never trusted.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schema import ParsedSnapshot, ParsedSwimEntry

SCHEMA_VERSION = "v6.0"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "swimmingresults_v6"


class PBCache:
    """Versioned, source-stamped disk cache for swimmer PB snapshots."""

    def __init__(self, cache_dir: Optional[Path] = None, schema_version: str = SCHEMA_VERSION):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.schema_version = schema_version

    def _path(self, asa_id: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Sanitise the id so it's safe as a filename
        safe = "".join(c for c in asa_id if c.isalnum() or c in "-_")
        return self.cache_dir / f"{safe}.json"

    def get(self, asa_id: str, max_age_days: int = 7) -> Optional[ParsedSnapshot]:
        """Return cached snapshot if exists, fresh, and schema_version matches.
        Returns None otherwise — caller must re-fetch.

        Old v3-cache files (no schema_version key) always return None.
        """
        p = self._path(asa_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

        # Schema version check — V3 files have no schema_version → cache miss
        if data.get("schema_version") != self.schema_version:
            return None

        # Staleness check
        fetched_at = data.get("fetched_at", "")
        if fetched_at:
            try:
                ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
                if age_days > max_age_days:
                    return None
            except Exception:
                # If we can't parse the timestamp, treat as stale
                return None

        return self._deserialise(data)

    def put(self, asa_id: str, snapshot: ParsedSnapshot) -> None:
        """Store snapshot with schema_version, fetched_at, source_url, raw_html_hash."""
        p = self._path(asa_id)
        data = self._serialise(snapshot)
        data["schema_version"] = self.schema_version
        try:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Cache failures are non-fatal

    def invalidate(self, asa_id: str) -> None:
        """Manual refresh path — delete the cached file."""
        p = self._path(asa_id)
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialise(snapshot: ParsedSnapshot) -> dict:
        entries = []
        for e in snapshot.entries:
            entries.append({
                "distance": e.distance,
                "stroke": e.stroke,
                "course": e.course,
                "time_str": e.time_str,
                "time_seconds": e.time_seconds,
                "date_iso": e.date_iso,
                "meet_name": e.meet_name,
                "venue": e.venue,
                "licence": e.licence,
                "level": e.level,
                "is_best": e.is_best,
            })
        return {
            "asa_id": snapshot.asa_id,
            "swimmer_name": snapshot.swimmer_name,
            "entries": entries,
            "source_url": snapshot.source_url,
            "fetched_at": snapshot.fetched_at,
            "fetch_ok": snapshot.fetch_ok,
            "error": snapshot.error,
            "raw_html_hash": snapshot.raw_html_hash,
        }

    @staticmethod
    def _deserialise(data: dict) -> ParsedSnapshot:
        entries = []
        for e in data.get("entries", []):
            try:
                entries.append(ParsedSwimEntry(
                    distance=e["distance"],
                    stroke=e["stroke"],
                    course=e["course"],
                    time_str=e.get("time_str", ""),
                    time_seconds=float(e["time_seconds"]),
                    date_iso=e.get("date_iso"),
                    meet_name=e.get("meet_name"),
                    venue=e.get("venue"),
                    licence=e.get("licence"),
                    level=e.get("level"),
                    is_best=e.get("is_best", True),
                ))
            except Exception:
                continue
        return ParsedSnapshot(
            asa_id=data["asa_id"],
            swimmer_name=data.get("swimmer_name"),
            entries=entries,
            source_url=data.get("source_url", ""),
            fetched_at=data.get("fetched_at", ""),
            fetch_ok=data.get("fetch_ok", True),
            error=data.get("error"),
            raw_html_hash=data.get("raw_html_hash"),
        )
