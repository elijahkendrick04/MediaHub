"""tests/test_notifications_inbox.py — the per-org notifications inbox store (UI 1.14).

Pins the store contract: record + validation/normalisation, newest-first
listing with limits, unread counting, mark-read (own-org only + idempotent),
mark-all-read, multi-tenant isolation, retention prune, the typed convenience
recorders, and the best-effort "never raises" guarantee.

Isolation follows the observability-store convention: point DATA_DIR at a fresh
temp dir and reload the module so it bootstraps a clean data.db per test.
"""
from __future__ import annotations

import importlib
import sqlite3

import pytest


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.notify.inbox as ib

    importlib.reload(ib)
    return ib


class TestRecord:
    def test_returns_id_and_persists(self, inbox):
        nid = inbox.record("org-a", "info", "Hello", "world")
        assert nid and nid.startswith("ntf_")
        items = inbox.list_for("org-a")
        assert len(items) == 1
        assert items[0]["title"] == "Hello"
        assert items[0]["body"] == "world"
        assert items[0]["read"] is False

    def test_empty_org_or_title_writes_nothing(self, inbox):
        assert inbox.record("", "info", "x") is None
        assert inbox.record("   ", "info", "x") is None
        assert inbox.record("org", "info", "") is None
        assert inbox.record("org", "info", "   ") is None
        assert inbox.unread_count("org") == 0

    def test_unknown_kind_and_level_fall_back_to_info(self, inbox):
        inbox.record("o", "not-a-kind", "t", level="purple")
        it = inbox.list_for("o")[0]
        assert it["kind"] == "info"
        assert it["level"] == "info"

    def test_title_and_body_truncated(self, inbox):
        inbox.record("o", "info", "T" * 500, "B" * 5000)
        it = inbox.list_for("o")[0]
        assert len(it["title"]) <= inbox._TITLE_MAX
        assert len(it["body"]) <= inbox._BODY_MAX

    def test_run_id_and_click_url_round_trip(self, inbox):
        inbox.record("o", "info", "t", run_id="run9", click_url="/x")
        it = inbox.list_for("o")[0]
        assert it["run_id"] == "run9"
        assert it["click_url"] == "/x"

    def test_blank_run_id_stored_as_empty(self, inbox):
        inbox.record("o", "info", "t", run_id="   ", click_url="")
        it = inbox.list_for("o")[0]
        assert it["run_id"] == ""
        assert it["click_url"] == ""


class TestListing:
    def test_newest_first(self, inbox):
        for i in range(3):
            inbox.record("o", "info", f"n{i}", ts=f"2026-06-1{i}T00:00:00Z")
        titles = [x["title"] for x in inbox.list_for("o")]
        assert titles == ["n2", "n1", "n0"]

    def test_same_second_inserts_keep_insertion_order(self, inbox):
        for i in range(4):
            inbox.record("o", "info", f"n{i}", ts="2026-06-14T00:00:00Z")
        titles = [x["title"] for x in inbox.list_for("o")]
        assert titles == ["n3", "n2", "n1", "n0"]

    def test_limit_capped(self, inbox):
        for i in range(10):
            inbox.record("o", "info", f"n{i}")
        assert len(inbox.list_for("o", limit=3)) == 3
        assert len(inbox.list_for("o", limit=999)) <= inbox._LIST_LIMIT_MAX

    def test_bad_limit_defaults(self, inbox):
        inbox.record("o", "info", "a")
        assert len(inbox.list_for("o", limit="not-a-number")) == 1

    def test_unread_only(self, inbox):
        a = inbox.record("o", "info", "a")
        inbox.record("o", "info", "b")
        inbox.mark_read("o", a)
        unread = inbox.list_for("o", unread_only=True)
        assert [x["title"] for x in unread] == ["b"]

    def test_empty_org_lists_nothing(self, inbox):
        assert inbox.list_for("") == []


class TestUnreadAndMark:
    def test_unread_count(self, inbox):
        inbox.record("o", "info", "a")
        inbox.record("o", "info", "b")
        assert inbox.unread_count("o") == 2

    def test_mark_read_own_only_and_idempotent(self, inbox):
        a = inbox.record("o", "info", "a")
        assert inbox.mark_read("o", a) is True
        assert inbox.mark_read("o", a) is False  # already read
        assert inbox.unread_count("o") == 0

    def test_mark_read_blank_args(self, inbox):
        assert inbox.mark_read("", "x") is False
        assert inbox.mark_read("o", "") is False

    def test_mark_all_read(self, inbox):
        inbox.record("o", "info", "a")
        inbox.record("o", "info", "b")
        assert inbox.mark_all_read("o") == 2
        assert inbox.unread_count("o") == 0
        assert inbox.mark_all_read("o") == 0


class TestTenantIsolation:
    def test_orgs_are_separate(self, inbox):
        a = inbox.record("org-a", "info", "secret-a")
        inbox.record("org-b", "info", "b")
        assert inbox.unread_count("org-a") == 1
        assert inbox.unread_count("org-b") == 1
        assert [x["title"] for x in inbox.list_for("org-b")] == ["b"]
        # org-b cannot read / mark org-a's notification
        assert inbox.mark_read("org-b", a) is False
        assert inbox.unread_count("org-a") == 1

    def test_mark_all_is_per_org(self, inbox):
        inbox.record("org-a", "info", "a")
        inbox.record("org-b", "info", "b")
        inbox.mark_all_read("org-a")
        assert inbox.unread_count("org-a") == 0
        assert inbox.unread_count("org-b") == 1


class TestRetention:
    def test_record_self_trims_to_cap(self, inbox, monkeypatch):
        monkeypatch.setattr(inbox, "_MAX_PER_ORG", 5)
        for i in range(12):
            inbox.record("o", "info", f"n{i}", ts=f"2026-06-14T00:00:{i:02d}Z")
        items = inbox.list_for("o", limit=50)
        assert len(items) == 5
        assert items[0]["title"] == "n11"  # newest survives

    def test_prune_all_orgs(self, inbox):
        for i in range(8):
            inbox.record("a", "info", f"a{i}", ts=f"2026-06-14T00:00:{i:02d}Z")
            inbox.record("b", "info", f"b{i}", ts=f"2026-06-14T00:00:{i:02d}Z")
        inbox.prune(max_per_org=3)
        assert len(inbox.list_for("a", limit=50)) == 3
        assert len(inbox.list_for("b", limit=50)) == 3


class TestConvenienceRecorders:
    def test_pack_ready_plural(self, inbox):
        inbox.record_pack_ready("o", "run1", count=3)
        it = inbox.list_for("o")[0]
        assert it["kind"] == inbox.KIND_PACK_READY
        assert it["level"] == inbox.LEVEL_SUCCESS
        assert "3 cards ready" in it["body"]
        assert it["run_id"] == "run1"

    def test_pack_ready_singular(self, inbox):
        inbox.record_pack_ready("o", "run1", count=1)
        assert "1 card ready" in inbox.list_for("o")[0]["body"]

    def test_pack_ready_no_count(self, inbox):
        inbox.record_pack_ready("o", "run1")
        assert "ready for review" in inbox.list_for("o")[0]["body"]

    def test_render_complete(self, inbox):
        inbox.record_render_complete("o", run_id="run1", label="reel")
        it = inbox.list_for("o")[0]
        assert it["kind"] == inbox.KIND_RENDER_COMPLETE
        assert it["level"] == inbox.LEVEL_SUCCESS
        assert it["title"].lower().startswith("reel")
        assert it["run_id"] == "run1"

    def test_error(self, inbox):
        inbox.record_error("o", "Boom", "details", run_id="r")
        it = inbox.list_for("o")[0]
        assert it["kind"] == inbox.KIND_ERROR
        assert it["level"] == inbox.LEVEL_ERROR
        assert it["title"] == "Boom"
        assert it["body"] == "details"

    def test_recorders_inert_for_signed_out_org(self, inbox):
        # An empty org id (e.g. an unowned background job) writes nothing.
        assert inbox.record_render_complete("", run_id="r") is None
        assert inbox.record_pack_ready("", "r") is None
        assert inbox.record_error("", "x") is None


class TestBestEffort:
    def test_never_raises_on_db_error(self, inbox, monkeypatch):
        def boom(*a, **k):
            raise sqlite3.OperationalError("disk gone")

        monkeypatch.setattr(inbox, "_connect", boom)
        # None of these may raise — a notification must never break its caller.
        assert inbox.record("o", "info", "t") is None
        assert inbox.list_for("o") == []
        assert inbox.unread_count("o") == 0
        assert inbox.mark_read("o", "x") is False
        assert inbox.mark_all_read("o") == 0
        assert inbox.prune() == 0
