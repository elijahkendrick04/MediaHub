"""
context_engine/cache.py — Persistent cache layer for discovered context data.

Stores JSON blobs under <DATA_DIR>/discovered/ with simple key-based lookup.
Cache files are stored as:
  discovered/meets/<key>.json
  discovered/swimmers/<key>.json
  discovered/pbs/<run_id>/<swimmer_key>.json

``_discovered_root()`` is the single resolver for this tree — pb_discovery's
cache delegates here so both packages always share one store.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _data_root() -> Path:
    """The writable data root: ``DATA_DIR`` when set (Render's persistent
    disk), else the same ``src/mediahub`` dev default ``web.py`` uses."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _discovered_root() -> Path:
    """``<data root>/discovered``, consistent with the other DATA_DIR
    siblings (runs_v4, research, …).

    Earlier versions wrote to ``<data root>/data/discovered`` (a doubled
    ``data`` segment); migrate that tree once, by rename, so warm caches
    and trust history survive the path fix. If the rename fails (e.g.
    cross-device), keep using the legacy root rather than splitting the
    store across two trees.
    """
    base = _data_root()
    root = base / "discovered"
    legacy = base / "data" / "discovered"
    if not root.exists() and legacy.is_dir():
        try:
            root.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(root)
        except OSError:
            root = legacy
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_key(text: str) -> str:
    """Create a short filesystem-safe cache key from arbitrary text."""
    return hashlib.md5(text.lower().strip().encode(), usedforsecurity=False).hexdigest()[:20]


class DiscoveryCache:
    """
    Persistent JSON cache for discovered context objects.

    All data lives under data/discovered/<namespace>/<key>.json.
    """

    def __init__(self, namespace: str, ttl_seconds: int = 30 * 24 * 3600):
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self._base = _discovered_root() / namespace
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._base / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        """Return cached dict if present and not expired, else None."""
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            stored_at = data.get("_cached_at", 0)
            if self.ttl_seconds > 0 and time.time() - stored_at > self.ttl_seconds:
                return None
            return data.get("payload")
        except Exception:
            return None

    def set(self, key: str, payload: Any) -> None:
        """Persist payload under key."""
        p = self._path(key)
        try:
            p.write_text(
                json.dumps({"_cached_at": time.time(), "payload": payload}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def make_key(self, *parts: str) -> str:
        return _make_key(" ".join(str(p) for p in parts))


class SubpathCache(DiscoveryCache):
    """
    Cache that stores under a sub-directory (e.g. pbs/<run_id>/<swimmer_key>.json).
    """

    def __init__(self, namespace: str, sub: str, ttl_seconds: int = 0):
        super().__init__(namespace, ttl_seconds=ttl_seconds)
        self._base = _discovered_root() / namespace / sub
        self._base.mkdir(parents=True, exist_ok=True)
