"""collab/permissions.py — role → capability matrix (roadmap 1.18).

The membership ledger (``web.tenancy``) decides *who* belongs to a workspace and
carries their ``role`` string. This module is the single, deterministic source of
truth for *what that role can do* — pure data + predicates, no I/O and no Flask,
so it is trivially testable and every gate in ``web.py`` asks it the same
question rather than re-deriving rules inline.

Five capabilities, deliberately coarse (a committee, not an enterprise IAM):

  - ``view``     — see runs, cards, packs, the review surface
  - ``comment``  — add comments / @mentions / reactions / tasks, request changes
  - ``edit``     — edit captions, apply spec patches, set element locks, restore
                   a prior version
  - ``approve``  — approve / reject a card (the sign-off authority)
  - ``manage``   — workspace admin: members & roles, delete, share-token issue &
                   revoke, approver-rule config (owner-only)

Role → capability mapping. ``member`` is the legacy seat and maps to
edit+approve so every workspace that pre-dates 1.18 behaves exactly as before;
the four narrower seats are opt-in refinements an owner hands out:

  owner    : view comment edit approve manage
  member   : view comment edit approve            (legacy default — unchanged)
  editor   : view comment edit
  approver : view comment         approve
  reviewer : view comment
  viewer   : view

Anything unrecognised falls to ``viewer`` (least privilege) — a torn/garbage
role string can never silently grant edit or approve.
"""

from __future__ import annotations

from typing import Iterable

from ..web.tenancy import (
    ROLE_APPROVER,
    ROLE_EDITOR,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_REVIEWER,
    ROLE_VIEWER,
)

# ---- capabilities ---------------------------------------------------------

CAP_VIEW = "view"
CAP_COMMENT = "comment"
CAP_EDIT = "edit"
CAP_APPROVE = "approve"
CAP_MANAGE = "manage"

ALL_CAPABILITIES: frozenset[str] = frozenset(
    {CAP_VIEW, CAP_COMMENT, CAP_EDIT, CAP_APPROVE, CAP_MANAGE}
)

# ---- the matrix -----------------------------------------------------------

_MATRIX: dict[str, frozenset[str]] = {
    ROLE_OWNER: frozenset({CAP_VIEW, CAP_COMMENT, CAP_EDIT, CAP_APPROVE, CAP_MANAGE}),
    ROLE_MEMBER: frozenset({CAP_VIEW, CAP_COMMENT, CAP_EDIT, CAP_APPROVE}),
    ROLE_EDITOR: frozenset({CAP_VIEW, CAP_COMMENT, CAP_EDIT}),
    ROLE_APPROVER: frozenset({CAP_VIEW, CAP_COMMENT, CAP_APPROVE}),
    ROLE_REVIEWER: frozenset({CAP_VIEW, CAP_COMMENT}),
    ROLE_VIEWER: frozenset({CAP_VIEW}),
}

# Human-facing labels + one-line descriptions for the members admin UI.
_LABELS: dict[str, str] = {
    ROLE_OWNER: "Owner",
    ROLE_MEMBER: "Member",
    ROLE_EDITOR: "Editor",
    ROLE_APPROVER: "Approver",
    ROLE_REVIEWER: "Reviewer",
    ROLE_VIEWER: "Viewer",
}

_DESCRIPTIONS: dict[str, str] = {
    ROLE_OWNER: "Full control — edit, approve, and manage members, roles & sharing.",
    ROLE_MEMBER: "Edit and approve content (the original team seat).",
    ROLE_EDITOR: "Draft and edit content and captions, but can't approve.",
    ROLE_APPROVER: "Review and approve content, but can't edit it.",
    ROLE_REVIEWER: "Comment, mention, raise tasks and request changes — no edits.",
    ROLE_VIEWER: "Read-only access to the workspace.",
}

# The order roles are offered in the picker — broadest first.
_ASSIGNABLE_ORDER = (
    ROLE_OWNER,
    ROLE_MEMBER,
    ROLE_EDITOR,
    ROLE_APPROVER,
    ROLE_REVIEWER,
    ROLE_VIEWER,
)


def _norm(role: object) -> str:
    return str(role or "").strip().lower()


def capabilities_for(role: object) -> frozenset[str]:
    """Return the capability set a role grants (least-privilege on unknowns)."""
    return _MATRIX.get(_norm(role), _MATRIX[ROLE_VIEWER])


def can(role: object, capability: str) -> bool:
    """True when ``role`` is granted ``capability``."""
    return capability in capabilities_for(role)


def can_view(role: object) -> bool:
    return can(role, CAP_VIEW)


def can_comment(role: object) -> bool:
    return can(role, CAP_COMMENT)


def can_edit(role: object) -> bool:
    return can(role, CAP_EDIT)


def can_approve(role: object) -> bool:
    return can(role, CAP_APPROVE)


def can_manage(role: object) -> bool:
    return can(role, CAP_MANAGE)


def role_label(role: object) -> str:
    """Human label for a role, falling back to a title-cased raw value."""
    r = _norm(role)
    return _LABELS.get(r, r.title() or _LABELS[ROLE_VIEWER])


def role_description(role: object) -> str:
    return _DESCRIPTIONS.get(_norm(role), _DESCRIPTIONS[ROLE_VIEWER])


def assignable_roles() -> list[str]:
    """Roles an owner can hand out, broadest first (for the picker)."""
    return list(_ASSIGNABLE_ORDER)


def highest_role(roles: Iterable[object]) -> str:
    """Pick the most-capable role from several (most capabilities wins).

    Used when an actor could be matched more than one way; ties resolve to the
    earlier entry in the assignable order so ``owner`` always wins.
    """
    best = ROLE_VIEWER
    best_n = -1
    for r in roles:
        n = len(capabilities_for(r))
        if n > best_n:
            best, best_n = _norm(r), n
    return best


__all__ = [
    "CAP_VIEW",
    "CAP_COMMENT",
    "CAP_EDIT",
    "CAP_APPROVE",
    "CAP_MANAGE",
    "ALL_CAPABILITIES",
    "capabilities_for",
    "can",
    "can_view",
    "can_comment",
    "can_edit",
    "can_approve",
    "can_manage",
    "role_label",
    "role_description",
    "assignable_roles",
    "highest_role",
]
