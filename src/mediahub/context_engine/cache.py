"""
context_engine/cache.py — Persistent cache layer for discovered context data.

Stores JSON blobs under data/discovered/ with simple key-based lookup.
Cache files are stored as:
  data/discovered/meets/<key>.json
  data/discovered/swimmers/<key>.json
  data/discovered/pbs/<run_id>/<swimmer_key>.json
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _repo_root() -> Path:
    """Resolve the repository root relative to this file."""
    return Path(__file__).resolve().parent.parent


def _discovered_root() -> Path:
    root = _repo_root() / "data" / "discovered"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_key(text: str) -> str:
    """Create a short filesystem-safe cache key from arbitrary text."""
    return hashlib.md5(text.lower().strip().encode()).hexdigest()[:20]


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
