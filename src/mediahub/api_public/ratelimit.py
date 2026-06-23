"""mediahub/api_public/ratelimit.py — lightweight per-token rate limiting.

A fixed-window counter keyed by token id (or client IP for unauthenticated
hits). It stays inside MediaHub's "no new infrastructure" discipline: pure
in-process state behind a lock, no Redis, no external limiter.

Honest limitation: the window is **per worker process**. Under multi-worker
gunicorn the effective ceiling is ``limit × workers``; this is documented in
``docs/PUBLIC_API.md`` and is fine for the protect-against-runaway-loops goal
here (a precise global limit would require the shared store we deliberately
avoid). The limit is operator-tunable via ``MEDIAHUB_API_RATELIMIT_PER_MIN``.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

DEFAULT_PER_MIN = 120
_WINDOW = 60.0


def _limit_per_min() -> int:
    raw = os.environ.get("MEDIAHUB_API_RATELIMIT_PER_MIN", "").strip()
    try:
        # 0 (or negative) disables limiting entirely — an explicit operator opt-out.
        return max(0, int(raw)) if raw else DEFAULT_PER_MIN
    except ValueError:
        return DEFAULT_PER_MIN


@dataclass
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after: int  # whole seconds until the current window rolls over


class RateLimiter:
    """Fixed-window counter. One instance per app; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (window_start_epoch, count)
        self._hits: dict[str, tuple[float, int]] = {}

    def check(self, key: str, *, now: float | None = None) -> RateDecision:
        limit = _limit_per_min()
        ts = now if now is not None else time.time()
        if limit <= 0:
            return RateDecision(True, 0, 0, 0)
        with self._lock:
            start, count = self._hits.get(key, (ts, 0))
            if ts - start >= _WINDOW:
                # New window.
                start, count = ts, 0
            count += 1
            self._hits[key] = (start, count)
            # Opportunistic eviction so the dict can't grow unbounded for a
            # long-lived process seeing many distinct keys.
            if len(self._hits) > 8192:
                self._evict(ts)
            remaining = max(0, limit - count)
            reset_after = max(0, int(round(start + _WINDOW - ts)))
            return RateDecision(count <= limit, limit, remaining, reset_after)

    def _evict(self, ts: float) -> None:
        stale = [k for k, (start, _) in self._hits.items() if ts - start >= _WINDOW]
        for k in stale:
            self._hits.pop(k, None)

    def reset(self) -> None:
        """Clear all counters (used by tests)."""
        with self._lock:
            self._hits.clear()


__all__ = ["RateLimiter", "RateDecision"]
