"""
pb_discovery/cache.py — Per-swimmer-per-run cache layer.

Cache layout:
  data/discovered/pbs/<run_id>/<swimmer_key>.json  — per-run (no TTL, scoped to run)
  data/discovered/swimmers/<swimmer_key>.json       — warm long-lived cache (7 days TTL)

The per-run cache ensures that within a single recognition run, each swimmer
is researched only once, even if they appear in multiple achievements.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _repo_root() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _discovered_root() -> Path:
    root = _repo_root() / "data" / "discovered"
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_swimmer_key(name: str, club: str) -> str:
    """Create a stable, filesystem-safe key for a swimmer."""
    raw = f"{name.lower().strip()}|{club.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:20]


class RunCache:
    """
    Per-run cache. Keyed by (run_id, swimmer_key).
    No TTL — persists for the lifetime of the run only (not cleaned up automatically).
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._base = _discovered_root() / "pbs" / _safe(run_id)
        self._base.mkdir(parents=True, exist_ok=True)

    def get(self, swimmer_key: str) -> Optional[dict]:
        p = self._base / f"{swimmer_key}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("payload")
        except Exception:
            return None

    def set(self, swimmer_key: str, payload: Any) -> None:
        p = self._base / f"{swimmer_key}.json"
        try:
            p.write_text(
                json.dumps({"_saved_at": _now(), "payload": payload}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def has(self, swimmer_key: str) -> bool:
        return self.get(swimmer_key) is not None


class WarmCache:
    """
    Warm long-lived swimmer cache (7-day TTL).
    Keyed by swimmer_key; shared across runs.
    """

    TTL = 7 * 24 * 3600

    def __init__(self):
        self._base = _discovered_root() / "swimmers"
        self._base.mkdir(parents=True, exist_ok=True)

    def get(self, swimmer_key: str) -> Optional[dict]:
        p = self._base / f"{swimmer_key}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = data.get("_saved_at_ts", 0)
            if time.time() - saved_at > self.TTL:
                return None
            return data.get("payload")
        except Exception:
            return None

    def set(self, swimmer_key: str, payload: Any) -> None:
        p = self._base / f"{swimmer_key}.json"
        try:
            p.write_text(
                json.dumps(
                    {"_saved_at": _now(), "_saved_at_ts": time.time(), "payload": payload},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass


def _safe(s: str) -> str:
    """Make a string safe for filesystem use."""
    import re

    return re.sub(r"[^\w\-]", "_", s)[:40]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
