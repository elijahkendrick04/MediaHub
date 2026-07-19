"""Unit tests for mediahub._atomic_io (atomic writes + cross-process lock)."""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

from mediahub._atomic_io import atomic_write_json, atomic_write_text, cross_process_lock


def test_atomic_write_text_roundtrip(tmp_path: Path):
    p = tmp_path / "sub" / "file.txt"  # parent dir does not exist yet
    atomic_write_text(p, "hello world")
    assert p.read_text() == "hello world"
    # No temp litter left behind.
    assert list(p.parent.glob("*.tmp")) == []


def test_atomic_write_json_overwrites(tmp_path: Path):
    p = tmp_path / "d.json"
    atomic_write_json(p, {"a": 1})
    atomic_write_json(p, {"b": 2})
    assert json.loads(p.read_text()) == {"b": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def _locked_append(args):
    lock_path, target, value = args
    # load -> mutate -> save under the cross-process lock. Without the lock two
    # workers read the same list and one append is lost.
    with cross_process_lock(Path(lock_path)):
        cur = json.loads(Path(target).read_text()) if Path(target).exists() else []
        cur.append(value)
        atomic_write_json(Path(target), cur)


def test_cross_process_lock_serialises_read_modify_write(tmp_path: Path):
    target = tmp_path / "list.json"
    lock = tmp_path / "list.lock"
    n = 16
    ctx = mp.get_context("fork")
    with ctx.Pool(4) as pool:
        pool.map(_locked_append, [(str(lock), str(target), i) for i in range(n)])
    got = sorted(json.loads(target.read_text()))
    assert got == list(range(n)), f"lost updates under contention: {got}"
