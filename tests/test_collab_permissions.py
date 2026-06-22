"""Roadmap 1.18 build 1 — the role → capability matrix (collab.permissions).

Pure, deterministic table: no I/O, no Flask. Pins exactly what each workspace
seat can do, that the legacy ``member`` seat keeps its pre-1.18 powers, and that
an unrecognised role falls to least privilege.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import permissions as perms
from mediahub.web import tenancy as t


def test_owner_has_everything():
    caps = perms.capabilities_for(t.ROLE_OWNER)
    assert caps == perms.ALL_CAPABILITIES
    for cap in perms.ALL_CAPABILITIES:
        assert perms.can(t.ROLE_OWNER, cap)


def test_legacy_member_keeps_edit_and_approve_but_not_manage():
    # Back-compat: every workspace that pre-dates 1.18 behaves unchanged —
    # a member could edit and approve, and that must still hold.
    assert perms.can_edit(t.ROLE_MEMBER)
    assert perms.can_approve(t.ROLE_MEMBER)
    assert perms.can_comment(t.ROLE_MEMBER)
    assert perms.can_view(t.ROLE_MEMBER)
    assert not perms.can_manage(t.ROLE_MEMBER)


def test_editor_edits_but_cannot_approve():
    assert perms.can_edit(t.ROLE_EDITOR)
    assert perms.can_comment(t.ROLE_EDITOR)
    assert not perms.can_approve(t.ROLE_EDITOR)
    assert not perms.can_manage(t.ROLE_EDITOR)


def test_approver_approves_but_cannot_edit():
    assert perms.can_approve(t.ROLE_APPROVER)
    assert perms.can_comment(t.ROLE_APPROVER)
    assert not perms.can_edit(t.ROLE_APPROVER)
    assert not perms.can_manage(t.ROLE_APPROVER)


def test_reviewer_comments_only():
    assert perms.can_comment(t.ROLE_REVIEWER)
    assert perms.can_view(t.ROLE_REVIEWER)
    assert not perms.can_edit(t.ROLE_REVIEWER)
    assert not perms.can_approve(t.ROLE_REVIEWER)


def test_viewer_is_read_only():
    assert perms.capabilities_for(t.ROLE_VIEWER) == frozenset({perms.CAP_VIEW})
    assert perms.can_view(t.ROLE_VIEWER)
    assert not perms.can_comment(t.ROLE_VIEWER)


def test_unknown_role_falls_to_least_privilege():
    for junk in ("", None, "superadmin", "  ", 123, "OWNERish"):
        assert perms.capabilities_for(junk) == frozenset({perms.CAP_VIEW})
        assert not perms.can_edit(junk)
        assert not perms.can_approve(junk)


def test_role_label_and_description_present_for_all_assignable():
    for r in perms.assignable_roles():
        assert perms.role_label(r) and isinstance(perms.role_label(r), str)
        assert perms.role_description(r) and isinstance(perms.role_description(r), str)


def test_assignable_roles_are_all_valid_ledger_roles():
    for r in perms.assignable_roles():
        assert r in t.VALID_ROLES


def test_highest_role_picks_most_capable():
    assert perms.highest_role([t.ROLE_VIEWER, t.ROLE_OWNER, t.ROLE_EDITOR]) == t.ROLE_OWNER
    assert perms.highest_role([t.ROLE_VIEWER, t.ROLE_REVIEWER]) == t.ROLE_REVIEWER
    assert perms.highest_role([]) == t.ROLE_VIEWER


def test_capability_ordering_is_monotone_by_seat():
    # Each broader seat is a strict (or equal) superset of the narrower one
    # below it — no seat accidentally grants something a broader one lacks.
    order = [t.ROLE_VIEWER, t.ROLE_REVIEWER, t.ROLE_EDITOR, t.ROLE_MEMBER, t.ROLE_OWNER]
    for narrow, broad in zip(order, order[1:]):
        assert perms.capabilities_for(narrow) <= perms.capabilities_for(broad)
