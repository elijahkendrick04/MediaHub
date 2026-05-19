"""LRU-bounded, lock-guarded mapping used by web.py to cap in-process
caches well below the Render Standard tier's 2 GB ceiling (and the
old 512 MB Starter ceiling it was originally sized for).

Why a tiny custom class instead of functools.lru_cache or cachetools:
  - functools.lru_cache wraps a callable; we need a plain mapping you
    can read by key and write into (the cache key is computed
    application-side from a tuple of swim attributes).
  - cachetools would work but adds a dependency for ~80 lines of code.

Thread-safety: every public method takes a re-entrant lock. The
underlying OrderedDict.move_to_end mutates on read, so even pure
`get()` calls must hold the lock. This matters because /review/<id>
runs under Flask's threaded server (gunicorn --threads 4) and the
background pipeline worker also reaches these caches indirectly.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Iterator, Optional


_SENTINEL = object()


class BoundedCache:
    """Fixed-capacity LRU mapping. Evicts least-recently-used on insert."""

    __slots__ = ("_max", "_data", "_lock")

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max = int(max_size)
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            val = self._data.get(key, _SENTINEL)
            if val is _SENTINEL:
                return default
            self._data.move_to_end(key)
            return val

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            val = self._data[key]
            self._data.move_to_end(key)
            return val

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._data[key]

    def pop(self, key: str, default: Any = _SENTINEL) -> Any:
        with self._lock:
            if default is _SENTINEL:
                return self._data.pop(key)
            return self._data.pop(key, default)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._data.items())

    def values(self) -> list[Any]:
        with self._lock:
            return list(self._data.values())

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def copy_value(self, key: str) -> Optional[Any]:
        """Return a shallow copy of the stored value under one lock acquire.

        For dict values (the common case for run/job registries) returns
        ``dict(stored)`` so callers can safely jsonify the snapshot without
        racing the background worker. For non-dict values returns the value
        as-is.
        """
        with self._lock:
            val = self._data.get(key)
            if val is None:
                return None
            self._data.move_to_end(key)
            return dict(val) if isinstance(val, dict) else val
