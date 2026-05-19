"""Regression tests for BoundedCache.

The class is the backing store for ``web._active_runs`` and
``web._turn_into_jobs``. It must support the dict-like interface
those call sites rely on — including ``.values()``, which was
missing and crashed ``/healthz/memory`` whenever an active run
existed.
"""
from __future__ import annotations

import pytest

from mediahub.web.bounded_cache import BoundedCache


def test_set_and_get_round_trip():
    c = BoundedCache(max_size=4)
    c["a"] = {"status": "running"}
    assert c["a"] == {"status": "running"}
    assert c.get("a") == {"status": "running"}
    assert c.get("missing") is None


def test_lru_evicts_oldest_on_overflow():
    c = BoundedCache(max_size=2)
    c["a"] = 1
    c["b"] = 2
    c["c"] = 3                # evicts "a"
    assert "a" not in c
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_items_keys_values_return_lists():
    c = BoundedCache(max_size=4)
    c["a"] = {"status": "running"}
    c["b"] = {"status": "done"}
    keys = c.keys()
    items = c.items()
    values = c.values()
    assert sorted(keys) == ["a", "b"]
    assert sorted(items) == [
        ("a", {"status": "running"}),
        ("b", {"status": "done"}),
    ]
    assert {"status": "running"} in values
    assert {"status": "done"} in values


def test_values_returns_independent_snapshot():
    """``.values()`` must not leak the internal OrderedDict view —
    callers iterate while holding ``_active_lock`` but the snapshot
    needs to survive subsequent mutations under the same lock."""
    c = BoundedCache(max_size=4)
    c["a"] = {"status": "running"}
    snapshot = c.values()
    c["a"] = {"status": "done"}
    # Snapshot reflects the moment .values() was called.
    assert snapshot == [{"status": "running"}]


def test_pop_with_default():
    c = BoundedCache(max_size=4)
    c["a"] = 1
    assert c.pop("a", None) == 1
    assert c.pop("a", None) is None
    with pytest.raises(KeyError):
        c.pop("missing")
