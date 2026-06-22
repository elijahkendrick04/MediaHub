"""Roadmap 1.18 build 2 — the collab.threads store (comments / tasks / reactions).

Deterministic CRUD against a temp data.db: comments, replies, tasks (with the
open-task count the approval gate reads), reactions, edit/delete semantics, and
the erasure cascade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import threads as th


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def test_add_and_list_comment(db):
    c = th.add_comment("run1", "card1", "Nice card", author_email="vol@club.org", db_path=db)
    assert c.kind == th.KIND_COMMENT
    assert c.thread_id == c.id and c.parent_id == ""
    rows = th.list_for_card("run1", "card1", db_path=db)
    assert len(rows) == 1 and rows[0].body == "Nice card"


def test_empty_body_rejected(db):
    with pytest.raises(th.ThreadError):
        th.add_comment("run1", "card1", "   ", db_path=db)


def test_reply_inherits_thread_and_card(db):
    root = th.add_comment("run1", "card1", "root", db_path=db)
    reply = th.add_comment(
        "run1", "", "a reply", parent_id=root.id, db_path=db
    )
    assert reply.thread_id == root.id
    assert reply.parent_id == root.id
    assert reply.card_id == "card1"  # inherited from the root


def test_reply_to_foreign_run_rejected(db):
    root = th.add_comment("run1", "card1", "root", db_path=db)
    with pytest.raises(th.ThreadError):
        th.add_comment("run2", "card1", "x", parent_id=root.id, db_path=db)


def test_open_task_count_and_resolve(db):
    th.add_comment("run1", "card1", "just a comment", db_path=db)
    t = th.add_comment("run1", "card1", "check lane 4", kind="task", db_path=db)
    assert th.open_task_count("run1", "card1", db_path=db) == 1
    assert th.open_task_count("run1", db_path=db) == 1  # run-wide
    th.set_resolved(t.id, True, run_id="run1", db_path=db)
    assert th.open_task_count("run1", "card1", db_path=db) == 0
    th.set_resolved(t.id, False, run_id="run1", db_path=db)
    assert th.open_task_count("run1", "card1", db_path=db) == 1


def test_open_task_count_is_per_card(db):
    th.add_comment("run1", "cardA", "task A", kind="task", db_path=db)
    th.add_comment("run1", "cardB", "task B", kind="task", db_path=db)
    assert th.open_task_count("run1", "cardA", db_path=db) == 1
    assert th.open_task_count("run1", "cardB", db_path=db) == 1
    assert th.open_task_count("run1", db_path=db) == 2


def test_edit_body_author_scoped(db):
    c = th.add_comment("run1", "card1", "original", author_email="vol@club.org", db_path=db)
    # wrong author can't edit
    assert th.edit_body(c.id, "hacked", run_id="run1", author_email="other@club.org", db_path=db) is None
    updated = th.edit_body(c.id, "edited", run_id="run1", author_email="vol@club.org", db_path=db)
    assert updated is not None and updated.body == "edited"


def test_delete_root_takes_thread(db):
    root = th.add_comment("run1", "card1", "root", db_path=db)
    th.add_comment("run1", "card1", "reply1", parent_id=root.id, db_path=db)
    th.add_comment("run1", "card1", "reply2", parent_id=root.id, db_path=db)
    removed = th.delete_comment(root.id, run_id="run1", db_path=db)
    assert removed == 3
    assert th.list_for_card("run1", "card1", db_path=db) == []


def test_delete_reply_only(db):
    root = th.add_comment("run1", "card1", "root", db_path=db)
    reply = th.add_comment("run1", "card1", "reply", parent_id=root.id, db_path=db)
    removed = th.delete_comment(reply.id, run_id="run1", db_path=db)
    assert removed == 1
    assert len(th.list_for_card("run1", "card1", db_path=db)) == 1


def test_delete_wrong_run_is_noop(db):
    c = th.add_comment("run1", "card1", "x", db_path=db)
    assert th.delete_comment(c.id, run_id="run2", db_path=db) == 0


def test_reactions_toggle_and_batch(db):
    c = th.add_comment("run1", "card1", "x", db_path=db)
    assert th.toggle_reaction(c.id, "👍", "a@b.com", db_path=db) is True
    assert th.toggle_reaction(c.id, "👍", "c@d.com", db_path=db) is True
    rx = th.reactions_for([c.id], db_path=db)
    assert sorted(rx[c.id]["👍"]) == ["a@b.com", "c@d.com"]
    # toggling off
    assert th.toggle_reaction(c.id, "👍", "a@b.com", db_path=db) is False
    rx = th.reactions_for([c.id], db_path=db)
    assert rx[c.id]["👍"] == ["c@d.com"]


def test_reaction_on_missing_comment_is_false(db):
    assert th.toggle_reaction("nope", "👍", "a@b.com", db_path=db) is False


def test_delete_for_run_cascade(db):
    c = th.add_comment("run1", "card1", "x", db_path=db)
    th.toggle_reaction(c.id, "👍", "a@b.com", db_path=db)
    th.add_comment("run1", "card2", "y", kind="task", db_path=db)
    th.add_comment("run2", "card1", "other run", db_path=db)
    removed = th.delete_for_run("run1", db_path=db)
    assert removed == 2
    assert th.list_for_card("run1", db_path=db) == []
    # reactions gone too
    assert th.reactions_for([c.id], db_path=db) == {}
    # run2 untouched
    assert len(th.list_for_card("run2", db_path=db)) == 1


def test_to_dict_shape(db):
    c = th.add_comment(
        "run1", "card1", "hi @coach", kind="task", assignee_email="coach@club.org",
        mentions=["coach@club.org"], db_path=db,
    )
    d = c.to_dict()
    assert d["kind"] == "task"
    assert d["assignee_email"] == "coach@club.org"
    assert d["mentions"] == ["coach@club.org"]
    assert d["resolved"] is False
