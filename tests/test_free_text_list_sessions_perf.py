"""FT-PERF-1: list_sessions must not parse the whole chat corpus per call.

The free-text landing page calls ``list_sessions(limit=20)`` on every load.
The store is one JSON file per chat and is never pruned, so the old
"glob + json.loads every file, then slice [:limit]" implementation grew
without bound — a cold landing render re-parsed thousands of files to show
20 rows.

The fix orders candidates by mtime (a cheap ``stat``) and parses lazily,
stopping once ``limit`` matching rows are collected. mtime tracks
``updated_at`` because ``save_session`` rewrites the file on every change.
These tests pin both the bound (parses ~limit, not N) and that ordering /
scoping / filtering are unchanged.
"""

from __future__ import annotations

import json
import os

import pytest

import mediahub.free_text_chat.session as sess


def _seed(chats_dir, cid, i, *, profile_id="org-a", mtime=None):
    """Write a chat file directly (bypassing save_session) with a controlled
    updated_at, then stamp a deterministic mtime so ordering is testable."""
    stamp = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}"
    (chats_dir / f"{cid}.json").write_text(
        json.dumps(
            {
                "chat_id": cid,
                "title": f"Chat {i}",
                "created_at": stamp,
                "updated_at": stamp,
                "profile_id": profile_id,
                "messages": [],
                "accepted_brief": None,
            }
        )
    )
    m = 1_000_000 + (i if mtime is None else mtime)
    os.utime(chats_dir / f"{cid}.json", (m, m))


@pytest.fixture
def chats_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    d = sess._sessions_dir()  # reads DATA_DIR fresh; creates the dir
    return d


@pytest.fixture
def count_parses(monkeypatch):
    """Count json.loads calls made while listing (one per file actually read)."""
    calls = {"n": 0}
    real = sess.json.loads

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(sess.json, "loads", counting)
    return calls


def test_parses_at_most_limit_files_not_the_whole_store(chats_dir, count_parses):
    N, limit = 40, 10
    for i in range(N):
        _seed(chats_dir, f"chat{i:02d}", i)

    count_parses["n"] = 0  # measure only the list_sessions call below
    rows = sess.list_sessions(limit=limit, profile_id="org-a")

    # The bound: it parsed exactly `limit` files, NOT all N.
    assert count_parses["n"] == limit
    assert count_parses["n"] < N
    # And it returned the newest `limit` chats, newest-first.
    assert [r["chat_id"] for r in rows] == [f"chat{i:02d}" for i in range(39, 29, -1)]


def test_returns_all_when_under_limit(chats_dir):
    for i in range(3):
        _seed(chats_dir, f"chat{i}", i)
    rows = sess.list_sessions(limit=20, profile_id="org-a")
    assert {r["chat_id"] for r in rows} == {"chat0", "chat1", "chat2"}
    # Newest first.
    assert rows[0]["chat_id"] == "chat2"


def test_scoping_still_filters_foreign_orgs(chats_dir):
    # Interleave two orgs; the newest files belong to org-b.
    for i in range(10):
        _seed(chats_dir, f"a{i}", i, profile_id="org-a")
    for i in range(10, 20):
        _seed(chats_dir, f"b{i}", i, profile_id="org-b")
    rows = sess.list_sessions(limit=5, profile_id="org-a")
    assert all(r["profile_id"] == "org-a" for r in rows)
    # Even though org-b's files are newer (parsed first), org-a's newest 5
    # are still found and returned.
    assert [r["chat_id"] for r in rows] == [f"a{i}" for i in range(9, 4, -1)]


def test_legacy_ownerless_chats_included_when_scoped(chats_dir):
    _seed(chats_dir, "owned", 1, profile_id="org-a")
    _seed(chats_dir, "legacy", 2, profile_id="")  # ownerless
    rows = sess.list_sessions(limit=20, profile_id="org-a")
    assert {r["chat_id"] for r in rows} == {"owned", "legacy"}


def test_unscoped_lists_every_workspace(chats_dir):
    _seed(chats_dir, "a", 1, profile_id="org-a")
    _seed(chats_dir, "b", 2, profile_id="org-b")
    rows = sess.list_sessions(profile_id=None)
    assert {r["chat_id"] for r in rows} == {"a", "b"}


def test_zero_or_negative_limit_returns_empty(chats_dir):
    _seed(chats_dir, "a", 1)
    assert sess.list_sessions(limit=0, profile_id="org-a") == []
    assert sess.list_sessions(limit=-5, profile_id="org-a") == []


def test_missing_store_dir_returns_empty(tmp_path, monkeypatch):
    # Point DATA_DIR somewhere with no free_text_chats dir yet — no crash.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nonexistent"))
    # _sessions_dir() would create it, so call list_sessions on a truly empty one.
    assert sess.list_sessions(profile_id="org-a") == []


def test_malformed_file_is_skipped_not_fatal(chats_dir):
    _seed(chats_dir, "good", 1, profile_id="org-a")
    (chats_dir / "bad.json").write_text("{ not valid json ")
    os.utime(chats_dir / "bad.json", (2_000_000, 2_000_000))  # newest by mtime
    rows = sess.list_sessions(limit=20, profile_id="org-a")
    # The malformed newest file is skipped; the good one still lists.
    assert [r["chat_id"] for r in rows] == ["good"]
