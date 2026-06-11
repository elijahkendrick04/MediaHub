"""Unit tests for the PC.3 membership ledger (`mediahub.web.tenancy`).

Pure-store tests — no Flask app. The request-level enforcement built on top
of this store is pinned separately by test_workspace_membership_invariant.py.
"""

from __future__ import annotations

import json

import pytest

from mediahub.web.tenancy import (
    ROLE_MEMBER,
    ROLE_OWNER,
    STATUS_ACTIVE,
    STATUS_INVITED,
    STATUS_REMOVED,
    Membership,
    MembershipStore,
    TenancyError,
)


@pytest.fixture
def store(tmp_path):
    return MembershipStore(path=tmp_path / "memberships.jsonl")


def test_missing_ledger_reads_empty(store):
    assert store.list_for_profile("club-a") == []
    assert store.is_bound("club-a") is False
    assert store.get("a@b.com", "club-a") is None
    assert store.member_profile_ids("a@b.com") == []


def test_add_creates_active_owner_and_binds_org(store):
    m = store.add("Coach@Club.org", "club-a", role=ROLE_OWNER)
    assert m.email == "coach@club.org"  # normalised
    assert m.role == ROLE_OWNER
    assert m.status == STATUS_ACTIVE
    assert store.is_bound("club-a") is True
    assert store.is_active_member("coach@club.org", "club-a") is True
    assert store.is_active_owner("coach@club.org", "club-a") is True
    assert store.member_profile_ids("coach@club.org") == ["club-a"]


def test_invited_row_does_not_bind_the_org(store):
    store.add("pilot@club.org", "club-a", role=ROLE_OWNER, status=STATUS_INVITED)
    assert store.is_bound("club-a") is False
    assert store.is_active_member("pilot@club.org", "club-a") is False


def test_activate_invites_flips_only_that_email(store):
    store.add("pilot@club.org", "club-a", role=ROLE_OWNER, status=STATUS_INVITED)
    store.add("other@club.org", "club-b", role=ROLE_OWNER, status=STATUS_INVITED)
    activated = store.activate_invites("pilot@club.org")
    assert [m.profile_id for m in activated] == ["club-a"]
    assert store.is_bound("club-a") is True
    assert store.is_bound("club-b") is False
    assert store.is_active_owner("pilot@club.org", "club-a") is True


def test_ledger_is_append_only_last_write_wins(store):
    store.add("a@b.com", "club-a", role=ROLE_MEMBER)
    store.add("a@b.com", "club-a", role=ROLE_OWNER)  # upsert via append
    lines = store.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # superseded, not rewritten
    assert store.get("a@b.com", "club-a").role == ROLE_OWNER
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert second["created_at"] == first["created_at"]  # creation time carried forward


def test_invited_by_stamps_persist(store):
    store.add(
        "vol@club.org",
        "club-a",
        role=ROLE_MEMBER,
        status=STATUS_INVITED,
        invited_by="coach@club.org",
        invited_via_profile_id="club-a",
    )
    m = store.get("vol@club.org", "club-a")
    assert m.invited_by == "coach@club.org"
    assert m.invited_via_profile_id == "club-a"
    # A later upsert without the stamps keeps them.
    store.activate_invites("vol@club.org")
    m2 = store.get("vol@club.org", "club-a")
    assert m2.status == STATUS_ACTIVE
    assert m2.invited_by == "coach@club.org"
    assert m2.invited_via_profile_id == "club-a"


def test_remove_appends_tombstone_and_unbinds_when_last(store):
    store.add("coach@club.org", "club-a", role=ROLE_OWNER)
    store.add("vol@club.org", "club-a", role=ROLE_MEMBER)
    removed = store.remove("vol@club.org", "club-a")
    assert removed.status == STATUS_REMOVED
    assert store.is_active_member("vol@club.org", "club-a") is False
    assert store.is_bound("club-a") is True  # owner remains


def test_cannot_remove_last_active_owner(store):
    store.add("coach@club.org", "club-a", role=ROLE_OWNER)
    store.add("vol@club.org", "club-a", role=ROLE_MEMBER)
    with pytest.raises(TenancyError):
        store.remove("coach@club.org", "club-a")
    # Transfer ownership, then removal works.
    store.add("vol@club.org", "club-a", role=ROLE_OWNER)
    store.remove("coach@club.org", "club-a")
    assert store.is_active_owner("vol@club.org", "club-a") is True
    assert store.is_bound("club-a") is True


def test_remove_unknown_membership_raises(store):
    with pytest.raises(TenancyError):
        store.remove("ghost@club.org", "club-a")


def test_add_rejects_bad_input(store):
    with pytest.raises(TenancyError):
        store.add("not-an-email", "club-a")
    with pytest.raises(TenancyError):
        store.add("a@b.com", "")


def test_torn_final_line_is_tolerated(store):
    store.add("a@b.com", "club-a", role=ROLE_OWNER)
    with store.path.open("a", encoding="utf-8") as fh:
        fh.write('{"email": "torn@club.org", "profile_id": "club-a"')  # no newline, invalid JSON
    assert store.is_active_owner("a@b.com", "club-a") is True
    assert store.get("torn@club.org", "club-a") is None


def test_ledger_file_is_owner_readable_only(store):
    store.add("a@b.com", "club-a")
    mode = store.path.stat().st_mode & 0o777
    assert mode == 0o600


def test_unknown_role_and_status_coerce_safely():
    m = Membership.from_record(
        {"email": "A@B.com", "profile_id": "club-a", "role": "superadmin", "status": "weird"}
    )
    assert m.role == ROLE_MEMBER
    assert m.status == STATUS_ACTIVE
    assert m.email == "a@b.com"
