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

Beyond the wall-clock TTL, ``WarmCache.get`` also applies a *meet-freshness*
gate when the caller supplies the date of the meet being processed: a warm
baseline captured before that meet may be missing PBs the swimmer set at
competitions in between, so it must not be trusted to decide whether a swim
at this meet is a new PB (finding F25).
"""

from __future__ import annotations

import calendar
import datetime
import hashlib
import json
import math
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


def _coerce_epoch(value: Any) -> Optional[float]:
    """Best-effort convert a meet date to epoch seconds (UTC).

    Accepts epoch seconds (``int``/``float``), an ISO ``YYYY-MM-DD`` date, or
    an ISO-8601 timestamp string; naive values are read as UTC. Returns
    ``None`` for ``None`` or anything unparseable, so a caller can simply skip
    the meet-freshness gate instead of guarding against an exception. Kept
    deterministic (no implicit "now") so the gate is fully pinnable in tests.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (OverflowError, ValueError):  # e.g. an int too large for a float
            return None
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.datetime.fromisoformat(iso)
        except ValueError:
            try:
                dt = datetime.datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
        if dt.tzinfo is None:
            return float(calendar.timegm(dt.timetuple()))
        return dt.timestamp()
    return None


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

    Independently of the wall-clock TTL, an entry is also rejected when it was
    captured more than ``MEET_FRESHNESS_GRACE`` seconds *before* the meet being
    processed (see ``get``): such a baseline may pre-date PBs the swimmer set at
    an intervening competition, and would otherwise mark a slower swim as a new
    PB (finding F25).
    """

    TTL = 7 * 24 * 3600
    EMPTY_TTL = 3600
    # A warm baseline captured up to a day before the meet is still trusted
    # (timezone skew / same-day processing of a multi-session meet); captured
    # earlier than that relative to the meet, it may miss an intervening PB and
    # is treated as stale for this meet.
    MEET_FRESHNESS_GRACE = 24 * 3600

    def __init__(self):
        self._base = _discovered_root() / "swimmers"
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_empty_payload(payload: Any) -> bool:
        return not (isinstance(payload, dict) and payload.get("pbs"))

    @staticmethod
    def _resolve_now(now: Optional[float]) -> float:
        """The reference clock for the TTL check: the caller-supplied ``now``
        when it is a real finite number, else the wall clock. Rejecting bools
        and non-finite values (NaN/inf) keeps a bad ``now`` from silently
        serving an expired entry (``nan - saved_at > ttl`` is always False)."""
        if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
            return float(now)
        return time.time()

    def get(
        self,
        swimmer_key: str,
        *,
        meet_date: Any = None,
        now: Optional[float] = None,
    ) -> Optional[dict]:
        """Return the warm-cached payload for ``swimmer_key`` if it is still
        trustworthy, else ``None``.

        Two independent freshness gates apply:

        * **Wall-clock TTL** — the entry expires ``TTL`` seconds after it was
          written (``EMPTY_TTL`` for empty discoveries). Pass ``now`` (epoch
          seconds) to override the reference clock instead of relying on an
          implicit ``time.time()`` — this keeps the check pinnable in tests.
        * **Meet freshness** (only when ``meet_date`` is supplied) — a cached
          baseline reflects the swimmer's PBs *only up to the moment it was
          fetched*. If it was captured more than ``MEET_FRESHNESS_GRACE`` before
          the meet being processed, the swimmer may have set faster PBs at
          competitions in between that this baseline never saw; comparing the
          meet's swims against it would announce a slower-than-true-PB swim as a
          "new PB" (finding F25). Such an entry is treated as stale and rejected
          here so discovery re-researches a current baseline.

        ``meet_date`` accepts epoch seconds or an ISO ``YYYY-MM-DD`` /
        ISO-8601 timestamp string (assumed UTC when naive); anything
        unparseable simply disables the meet gate rather than raising.
        """
        p = self._base / f"{swimmer_key}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = data.get("_saved_at_ts", 0)
            payload = data.get("payload")
            ttl = self.EMPTY_TTL if self._is_empty_payload(payload) else self.TTL
            now_ts = self._resolve_now(now)
            if now_ts - saved_at > ttl:
                return None
            meet_ts = _coerce_epoch(meet_date)
            if meet_ts is not None and saved_at and meet_ts - saved_at > self.MEET_FRESHNESS_GRACE:
                # Baseline pre-dates the meet — it may miss PBs set at an
                # intervening competition; do not serve it as a pre-meet
                # baseline (finding F25).
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
