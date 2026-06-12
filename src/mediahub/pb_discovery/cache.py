"""
pb_discovery/cache.py — Per-swimmer-per-run cache layer.

Cache layout (under ``<DATA_DIR>/discovered``, shared with context_engine):
  discovered/pbs/<run_id>/<swimmer_key>.json  — per-run (no TTL, scoped to run)
  discovered/swimmers/<swimmer_key>.json       — warm long-lived cache (7 days TTL)

The per-run cache ensures that within a single recognition run, each swimmer
is researched only once, even if they appear in multiple achievements.

Empty discoveries (no PBs found) are warm-cached with a much shorter TTL:
a throttled or offline run must not poison a swimmer's lookup for a week —
re-running the meet an hour later genuinely re-researches them.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _discovered_root() -> Path:
    """Shared ``discovered/`` store. Late lookup so tests can patch either
    this name or context_engine's."""
    from mediahub.context_engine import cache as _ctx_cache

    return _ctx_cache._discovered_root()


def make_swimmer_key(name: str, club: str) -> str:
    """Create a stable, filesystem-safe key for a swimmer."""
    raw = f"{name.lower().strip()}|{club.lower().strip()}"
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:20]


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp + os.replace so a concurrent reader (another
    gunicorn worker mid-run) can never see a half-written file."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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
            _write_json_atomic(p, {"_saved_at": _now(), "payload": payload})
        except Exception:
            pass

    def has(self, swimmer_key: str) -> bool:
        return self.get(swimmer_key) is not None


class WarmCache:
    """
    Warm long-lived swimmer cache (7-day TTL).
    Keyed by swimmer_key; shared across runs.

    Entries whose payload found no PBs expire after ``EMPTY_TTL`` instead:
    "nothing found" is often transient (search throttled, site down), so it
    must never be served for a week.
    """

    TTL = 7 * 24 * 3600
    EMPTY_TTL = 3600

    def __init__(self):
        self._base = _discovered_root() / "swimmers"
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_empty_payload(payload: Any) -> bool:
        return not (isinstance(payload, dict) and payload.get("pbs"))

    def get(self, swimmer_key: str) -> Optional[dict]:
        p = self._base / f"{swimmer_key}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = data.get("_saved_at_ts", 0)
            payload = data.get("payload")
            ttl = self.EMPTY_TTL if self._is_empty_payload(payload) else self.TTL
            if time.time() - saved_at > ttl:
                return None
            return payload
        except Exception:
            return None

    def set(self, swimmer_key: str, payload: Any) -> None:
        p = self._base / f"{swimmer_key}.json"
        try:
            _write_json_atomic(
                p,
                {"_saved_at": _now(), "_saved_at_ts": time.time(), "payload": payload},
            )
        except Exception:
            pass


def _safe(s: str) -> str:
    """Make a string safe for filesystem use."""
    import re

    return re.sub(r"[^\w\-]", "_", s)[:40]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
