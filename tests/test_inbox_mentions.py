"""Roadmap 1.18 build 2 — per-user inbox targeting + mention/task recorders.

The inbox gains an optional ``user_email`` so a mention or task notification
reaches one member's bell, not the whole org's, while org-wide rows (the
pre-1.18 behaviour) still surface for everyone.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.notify import inbox as _inbox

    importlib.reload(_inbox)
    return _inbox


def test_org_wide_visible_to_all(inbox):
    inbox.record("org1", inbox.KIND_INFO, "Pack ready")
    # No user filter → sees it; any user → also sees it (NULL is org-wide).
    assert len(inbox.list_for("org1")) == 1
    assert len(inbox.list_for("org1", user_email="anyone@club.org")) == 1


def test_personal_mention_only_to_target(inbox):
    inbox.record_mention("org1", "coach@club.org", "Jane", "a comment")
    # The target sees it…
    coach = inbox.list_for("org1", user_email="coach@club.org")
    assert len(coach) == 1 and coach[0]["kind"] == "mention"
    # …another member does not.
    other = inbox.list_for("org1", user_email="chair@club.org")
    assert other == []
    # operator-style unfiltered view sees everything.
    assert len(inbox.list_for("org1")) == 1


def test_unread_count_respects_user(inbox):
    inbox.record("org1", inbox.KIND_INFO, "org wide")
    inbox.record_mention("org1", "coach@club.org", "Jane", "x")
    assert inbox.unread_count("org1", user_email="coach@club.org") == 2  # org-wide + own
    assert inbox.unread_count("org1", user_email="chair@club.org") == 1  # org-wide only


def test_mark_all_read_scoped_to_user(inbox):
    inbox.record_mention("org1", "coach@club.org", "Jane", "x")
    inbox.record_mention("org1", "chair@club.org", "Sam", "y")
    n = inbox.mark_all_read("org1", user_email="coach@club.org")
    assert n == 1
    # chair's mention is still unread
    assert inbox.unread_count("org1", user_email="chair@club.org") == 1


def test_task_assigned_recorder(inbox):
    nid = inbox.record_task_assigned(
        "org1", "coach@club.org", "Jane", "check lane 4", run_id="run1"
    )
    assert nid
    rows = inbox.list_for("org1", user_email="coach@club.org")
    assert rows and rows[0]["kind"] == "task"
    assert rows[0]["level"] == "warning"


def test_cross_tenant_isolation_holds(inbox):
    inbox.record_mention("org1", "coach@club.org", "Jane", "x")
    assert inbox.list_for("org2", user_email="coach@club.org") == []


def test_migration_adds_user_email_column(tmp_path, monkeypatch):
    # Simulate a pre-1.18 data.db: a notifications table without user_email.
    import sqlite3

    db = tmp_path / "data.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE notifications (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'info', title TEXT NOT NULL, "
        "body TEXT NOT NULL DEFAULT '', run_id TEXT, click_url TEXT, created_at TEXT NOT NULL, "
        "read_at TEXT);"
    )
    conn.execute(
        "INSERT INTO notifications (id, org_id, kind, title, created_at) "
        "VALUES ('old1','org1','info','Legacy', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib

    from mediahub.notify import inbox as _inbox

    importlib.reload(_inbox)
    # The old row still lists (org-wide), and a new personal mention works.
    assert len(_inbox.list_for("org1", user_email="coach@club.org")) == 1
    _inbox.record_mention("org1", "coach@club.org", "Jane", "x")
    assert len(_inbox.list_for("org1", user_email="coach@club.org")) == 2
    assert len(_inbox.list_for("org1", user_email="other@club.org")) == 1
