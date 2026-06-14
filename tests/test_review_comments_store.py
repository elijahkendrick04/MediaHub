"""Unit tests for the reel review-comments store (UI 1.8).

Frame.io-style timestamp-anchored markers, persisted per run/target in the
shared SQLite db. These tests drive the store directly with an explicit
``db_path`` (temp db per test) the way test_scheduler.py does — no web layer,
no network. They pin the contract the routes and front-end depend on:
ordering by timestamp, target scoping, resolve/edit/delete, run-scoped
mutation, input validation, the per-target cap, and run-deletion cleanup.
"""
from __future__ import annotations

import pytest

from mediahub.workflow import review_comments as rc


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


# ---------------------------------------------------------------------------
# Create + read
# ---------------------------------------------------------------------------


def test_add_and_get_roundtrip(db):
    c = rc.add_comment("run1", "reel", 3200, "Trim the intro", author="Coach", db_path=db)
    assert c.id and len(c.id) == 32
    assert c.run_id == "run1"
    assert c.target == "reel"
    assert c.t_ms == 3200
    assert c.body == "Trim the intro"
    assert c.author == "Coach"
    assert c.resolved is False
    assert c.created_at == c.updated_at

    got = rc.get_comment(c.id, db_path=db)
    assert got is not None
    assert got.to_dict() == c.to_dict()


def test_to_dict_shape_and_types(db):
    c = rc.add_comment("run1", "reel", 1000.6, "Note", db_path=db)
    d = c.to_dict()
    assert set(d) == {
        "id",
        "run_id",
        "target",
        "t_ms",
        "body",
        "author",
        "resolved",
        "created_at",
        "updated_at",
    }
    assert isinstance(d["t_ms"], int) and d["t_ms"] == 1001  # rounded
    assert d["resolved"] is False
    assert d["author"] == rc.DEFAULT_AUTHOR  # defaulted


def test_list_orders_by_timestamp(db):
    rc.add_comment("run1", "reel", 5000, "third", db_path=db)
    rc.add_comment("run1", "reel", 1000, "first", db_path=db)
    rc.add_comment("run1", "reel", 3000, "second", db_path=db)
    bodies = [c.body for c in rc.list_comments("run1", db_path=db)]
    assert bodies == ["first", "second", "third"]


def test_list_and_count_scoped_by_run(db):
    rc.add_comment("runA", "reel", 100, "a", db_path=db)
    rc.add_comment("runB", "reel", 100, "b", db_path=db)
    assert [c.body for c in rc.list_comments("runA", db_path=db)] == ["a"]
    assert rc.count_comments("runA", db_path=db) == 1
    assert rc.count_comments("runB", db_path=db) == 1
    assert rc.count_comments("nope", db_path=db) == 0


def test_target_separates_reel_from_card(db):
    rc.add_comment("run1", "reel", 100, "on the reel", db_path=db)
    rc.add_comment("run1", "card:swim-9", 100, "on the card", db_path=db)
    assert len(rc.list_comments("run1", db_path=db)) == 2  # both, no target filter
    reel = rc.list_comments("run1", "reel", db_path=db)
    card = rc.list_comments("run1", "card:swim-9", db_path=db)
    assert [c.body for c in reel] == ["on the reel"]
    assert [c.body for c in card] == ["on the card"]


# ---------------------------------------------------------------------------
# Update: resolve / reopen / edit, with run scoping
# ---------------------------------------------------------------------------


def test_resolve_then_reopen(db):
    c = rc.add_comment("run1", "reel", 100, "fix this", db_path=db)
    upd = rc.update_comment(c.id, resolved=True, db_path=db)
    assert upd is not None and upd.resolved is True
    assert upd.updated_at >= c.created_at
    again = rc.update_comment(c.id, resolved=False, db_path=db)
    assert again is not None and again.resolved is False


def test_include_resolved_filter(db):
    a = rc.add_comment("run1", "reel", 100, "open", db_path=db)
    b = rc.add_comment("run1", "reel", 200, "closing", db_path=db)
    rc.update_comment(b.id, resolved=True, db_path=db)
    all_ = rc.list_comments("run1", db_path=db)
    open_only = rc.list_comments("run1", include_resolved=False, db_path=db)
    assert {c.id for c in all_} == {a.id, b.id}
    assert {c.id for c in open_only} == {a.id}
    assert rc.count_comments("run1", include_resolved=False, db_path=db) == 1


def test_edit_body(db):
    c = rc.add_comment("run1", "reel", 100, "old", db_path=db)
    upd = rc.update_comment(c.id, body="new and improved", db_path=db)
    assert upd is not None and upd.body == "new and improved"


def test_edit_rejects_empty_body(db):
    c = rc.add_comment("run1", "reel", 100, "keep me", db_path=db)
    with pytest.raises(rc.ReelCommentError):
        rc.update_comment(c.id, body="   ", db_path=db)
    # unchanged
    assert rc.get_comment(c.id, db_path=db).body == "keep me"


def test_update_run_scope_blocks_cross_run(db):
    c = rc.add_comment("run1", "reel", 100, "mine", db_path=db)
    # Wrong run id must not match — returns None, leaves the row untouched.
    assert rc.update_comment(c.id, resolved=True, run_id="other", db_path=db) is None
    assert rc.get_comment(c.id, db_path=db).resolved is False


def test_update_missing_comment_returns_none(db):
    assert rc.update_comment("deadbeef", resolved=True, db_path=db) is None


# ---------------------------------------------------------------------------
# Delete, with run scoping + run-wide cleanup
# ---------------------------------------------------------------------------


def test_delete_comment(db):
    c = rc.add_comment("run1", "reel", 100, "bye", db_path=db)
    assert rc.delete_comment(c.id, db_path=db) is True
    assert rc.get_comment(c.id, db_path=db) is None
    assert rc.delete_comment(c.id, db_path=db) is False  # already gone


def test_delete_run_scope_blocks_cross_run(db):
    c = rc.add_comment("run1", "reel", 100, "mine", db_path=db)
    assert rc.delete_comment(c.id, run_id="other", db_path=db) is False
    assert rc.get_comment(c.id, db_path=db) is not None  # survived


def test_delete_comments_for_run(db):
    rc.add_comment("run1", "reel", 100, "a", db_path=db)
    rc.add_comment("run1", "card:x", 200, "b", db_path=db)
    rc.add_comment("run2", "reel", 100, "keep", db_path=db)
    removed = rc.delete_comments_for_run("run1", db_path=db)
    assert removed == 2
    assert rc.count_comments("run1", db_path=db) == 0
    assert rc.count_comments("run2", db_path=db) == 1  # untouched
    assert rc.delete_comments_for_run("", db_path=db) == 0  # no-op on blank id


# ---------------------------------------------------------------------------
# Validation + bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
def test_empty_body_rejected(db, bad):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", 100, bad, db_path=db)


def test_body_length_cap(db):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", 100, "x" * (rc.MAX_BODY_LEN + 1), db_path=db)
    # exactly at the limit is fine
    ok = rc.add_comment("run1", "reel", 100, "x" * rc.MAX_BODY_LEN, db_path=db)
    assert len(ok.body) == rc.MAX_BODY_LEN


@pytest.mark.parametrize("bad", [-1, -50, rc.MAX_TIME_MS + 1, "abc", None, float("nan")])
def test_bad_timestamps_rejected(db, bad):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", bad, "body", db_path=db)


def test_timestamp_zero_is_allowed(db):
    c = rc.add_comment("run1", "reel", 0, "right at the start", db_path=db)
    assert c.t_ms == 0


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 1e400, "inf", True])
def test_non_finite_or_bool_timestamps_rejected(db, bad):
    # inf/nan would crash int(round(...)); bool would be silently read as 1ms.
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", bad, "body", db_path=db)


@pytest.mark.parametrize("bad", [123, ["a"], {"x": 1}, 4.5])
def test_non_string_body_rejected(db, bad):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", 100, bad, db_path=db)


def test_non_string_target_rejected(db):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", 123, 100, "body", db_path=db)


def test_non_string_author_falls_back_to_default(db):
    c = rc.add_comment("run1", "reel", 100, "body", author=42, db_path=db)
    assert c.author == rc.DEFAULT_AUTHOR


def test_subms_negative_rounds_to_zero(db):
    # currentTime*1000 can yield tiny negative float noise; round it to 0
    # rather than reject a click at the very start of the reel.
    c = rc.add_comment("run1", "reel", -0.4, "start", db_path=db)
    assert c.t_ms == 0


def test_blank_run_id_rejected(db):
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("  ", "reel", 100, "body", db_path=db)


def test_author_defaults_and_truncates(db):
    a = rc.add_comment("run1", "reel", 100, "b", author=None, db_path=db)
    assert a.author == rc.DEFAULT_AUTHOR
    b = rc.add_comment("run1", "reel", 100, "b", author="  ", db_path=db)
    assert b.author == rc.DEFAULT_AUTHOR
    c = rc.add_comment("run1", "reel", 100, "b", author="z" * 500, db_path=db)
    assert len(c.author) == rc.MAX_AUTHOR_LEN


def test_target_defaults_and_length_cap(db):
    a = rc.add_comment("run1", None, 100, "b", db_path=db)
    assert a.target == rc.REEL_TARGET
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "t" * (rc.MAX_TARGET_LEN + 1), 100, "b", db_path=db)


def test_per_target_cap(db, monkeypatch):
    monkeypatch.setattr(rc, "MAX_COMMENTS_PER_TARGET", 2)
    rc.add_comment("run1", "reel", 100, "1", db_path=db)
    rc.add_comment("run1", "reel", 200, "2", db_path=db)
    with pytest.raises(rc.ReelCommentError):
        rc.add_comment("run1", "reel", 300, "3", db_path=db)
    # a different target on the same run is unaffected by the reel's cap
    assert rc.add_comment("run1", "card:x", 100, "ok", db_path=db) is not None


# ---------------------------------------------------------------------------
# Schema / persistence hygiene
# ---------------------------------------------------------------------------


def test_schema_is_idempotent(db):
    conn = rc._connect(db)
    try:
        rc.init_schema(conn)
        rc.init_schema(conn)  # second call must not raise
    finally:
        conn.close()
    # store still works after re-init
    assert rc.add_comment("run1", "reel", 100, "b", db_path=db) is not None


def test_persists_across_connections(db):
    c = rc.add_comment("run1", "reel", 100, "durable", db_path=db)
    # A fresh call opens a brand-new connection to the same file.
    assert rc.get_comment(c.id, db_path=db).body == "durable"


def test_default_db_path_follows_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert rc._default_db_path() == tmp_path / "data.db"
