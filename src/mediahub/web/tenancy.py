"""
PC.3 — org → workspace membership binding (true multi-tenancy, one shared instance).

This is the schema decided in ADR-0014 (Council-pressure-tested): user accounts
(``users.jsonl``, PC.1) are bound to organisations (``ClubProfile`` JSONs) by a
**membership relation** stored in its own append-only JSON-lines ledger under
``DATA_DIR/memberships.jsonl`` — one object per line ``{email, profile_id,
role, status, invited_by, invited_via_profile_id, created_at, updated_at}``,
last-write-wins per ``(email, profile_id)``, mirroring ``users.jsonl``. No
SQLAlchemy, no coupling into the profile JSON.

The activation model is **per-org binding**, not a global tenancy flip:

  - An org with **≥1 ACTIVE membership is "bound"** — only its active members
    (or the env-gated dev operator) may pin, see, edit, or delete it.
  - An org with **zero active memberships is "unbound"** and behaves exactly
    as it always has (the Step-14 "standalone club" / pilot mode), so
    deployments with no accounts — and the existing test fixtures — are
    untouched.
  - ``invited`` rows do NOT bind an org: the operator can pre-bind a pilot
    club's email and the club keeps working anonymously until that email
    signs up, at which point the invite activates and the org binds — the
    zero-founder-involvement first-claim path.

This module is deliberately session-free (pure storage + predicates); the
Flask side (``web.py``) decides who the current actor is and asks questions
like ``is_bound`` / ``is_active_member``. Enforcement lives at the pinning
choke points and is pinned by ``tests/test_workspace_membership_invariant.py``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .auth import normalize_email

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
# 1.18 — finer collaboration roles layered on the membership ledger. ``owner``
# stays the workspace super-admin (member/role admin, delete, share-token issue,
# approver-rule config); ``member`` is the legacy default and keeps today's
# behaviour (edit + approve, but no org admin). The four below let an owner hand
# out narrower seats — the capability each one grants lives in
# ``collab.permissions`` (the single source of truth), never re-encoded here.
ROLE_EDITOR = "editor"
ROLE_APPROVER = "approver"
ROLE_REVIEWER = "reviewer"
ROLE_VIEWER = "viewer"
VALID_ROLES = frozenset(
    {ROLE_OWNER, ROLE_MEMBER, ROLE_EDITOR, ROLE_APPROVER, ROLE_REVIEWER, ROLE_VIEWER}
)

STATUS_ACTIVE = "active"
STATUS_INVITED = "invited"
STATUS_REMOVED = "removed"
VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_INVITED, STATUS_REMOVED})

# Serialise ledger writes within a process (same rationale as auth._LEDGER_LOCK:
# the file is tiny and append-only; a coarse lock prevents interleaved lines).
_LEDGER_LOCK = threading.Lock()


class TenancyError(Exception):
    """Raised for expected, user-facing membership failures (clean error, not 500)."""


def _coerce_role(role: object) -> str:
    r = str(role or "").strip().lower()
    return r if r in VALID_ROLES else ROLE_MEMBER


def _coerce_status(status: object) -> str:
    s = str(status or "").strip().lower()
    return s if s in VALID_STATUSES else STATUS_ACTIVE


@dataclass
class Membership:
    email: str
    profile_id: str
    role: str = ROLE_MEMBER
    status: str = STATUS_ACTIVE
    invited_by: str = ""
    invited_via_profile_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "Membership":
        return cls(
            email=normalize_email(str(d.get("email", ""))),
            profile_id=str(d.get("profile_id", "") or "").strip(),
            role=_coerce_role(d.get("role")),
            status=_coerce_status(d.get("status")),
            invited_by=str(d.get("invited_by", "") or ""),
            invited_via_profile_id=str(d.get("invited_via_profile_id", "") or ""),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
        )


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    """Resolve DATA_DIR at call time (tests monkeypatch the env var)."""
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _memberships_path() -> Path:
    return _data_dir() / "memberships.jsonl"


class MembershipStore:
    """JSON-lines membership ledger under ``DATA_DIR``.

    Append-only with last-write-wins per ``(email, profile_id)``: changing a
    role or status appends a superseding row rather than rewriting the file,
    which keeps writes crash-safe and leaves an audit trail of every grant,
    invite, and removal in file order.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _memberships_path()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> dict[tuple[str, str], Membership]:
        """Return ``{(email, profile_id): Membership}``, later lines winning."""
        out: dict[tuple[str, str], Membership] = {}
        if not self._path.exists():
            return out
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return out
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn final line; never crash a request
            if not isinstance(rec, dict):
                continue
            m = Membership.from_record(rec)
            if m.email and m.profile_id:
                out[(m.email, m.profile_id)] = m
        return out

    def _append(self, membership: Membership) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(membership.to_record(), ensure_ascii=False) + "\n")
        # Membership rows reveal which emails run which club — owner-only,
        # mirroring the users.jsonl hardening.
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    # ---- reads ----------------------------------------------------------

    def get(self, email: str, profile_id: str) -> Optional[Membership]:
        return self._read_all().get((normalize_email(email), (profile_id or "").strip()))

    def list_for_profile(
        self, profile_id: str, *, include_removed: bool = False
    ) -> list[Membership]:
        pid = (profile_id or "").strip()
        rows = [m for m in self._read_all().values() if m.profile_id == pid]
        if not include_removed:
            rows = [m for m in rows if m.status != STATUS_REMOVED]
        return sorted(rows, key=lambda m: (m.status, m.email))

    def is_bound(self, profile_id: str) -> bool:
        """True when the org has ≥1 ACTIVE membership — the members-only switch.

        ``invited`` rows deliberately do NOT bind: a pre-bound pilot keeps its
        open (legacy) behaviour until the invited owner actually signs up.
        """
        pid = (profile_id or "").strip()
        if not pid:
            return False
        return any(
            m.profile_id == pid and m.status == STATUS_ACTIVE for m in self._read_all().values()
        )

    def is_active_member(self, email: str, profile_id: str) -> bool:
        m = self.get(email, profile_id)
        return bool(m and m.status == STATUS_ACTIVE)

    def is_active_owner(self, email: str, profile_id: str) -> bool:
        m = self.get(email, profile_id)
        return bool(m and m.status == STATUS_ACTIVE and m.role == ROLE_OWNER)

    def member_profile_ids(self, email: str) -> list[str]:
        """Profile ids this email is an ACTIVE member of (the picker set)."""
        norm = normalize_email(email)
        return sorted(
            m.profile_id
            for m in self._read_all().values()
            if m.email == norm and m.status == STATUS_ACTIVE
        )

    # ---- writes ---------------------------------------------------------

    def add(
        self,
        email: str,
        profile_id: str,
        *,
        role: str = ROLE_MEMBER,
        status: str = STATUS_ACTIVE,
        invited_by: str = "",
        invited_via_profile_id: str = "",
    ) -> Membership:
        """Upsert a membership row (append a superseding line).

        Re-adding an existing pair updates role/status while preserving the
        original ``created_at`` (the superseding line carries it forward).
        """
        norm = normalize_email(email)
        pid = (profile_id or "").strip()
        if not norm or "@" not in norm:
            raise TenancyError("Enter a valid email address.")
        if not pid:
            raise TenancyError("Missing organisation id.")
        role = _coerce_role(role)
        status = _coerce_status(status)
        with _LEDGER_LOCK:
            prior = self._read_all().get((norm, pid))
            now = _utc_now_iso()
            m = Membership(
                email=norm,
                profile_id=pid,
                role=role,
                status=status,
                invited_by=normalize_email(invited_by)
                if invited_by
                else (prior.invited_by if prior else ""),
                invited_via_profile_id=(
                    (invited_via_profile_id or "").strip()
                    or (prior.invited_via_profile_id if prior else "")
                ),
                created_at=prior.created_at if prior and prior.created_at else now,
                updated_at=now,
            )
            self._append(m)
        return m

    def remove(self, email: str, profile_id: str) -> Membership:
        """Mark a membership removed (append a tombstone-status row).

        Refuses to remove the **last active owner** of a bound org — transfer
        ownership first (``add`` another member with ``role=owner``) so a
        bound workspace can never become ownerless-but-locked.
        """
        norm = normalize_email(email)
        pid = (profile_id or "").strip()
        with _LEDGER_LOCK:
            rows = self._read_all()
            current = rows.get((norm, pid))
            if current is None or current.status == STATUS_REMOVED:
                raise TenancyError("No such membership.")
            if current.status == STATUS_ACTIVE and current.role == ROLE_OWNER:
                other_active_owners = [
                    m
                    for (e, p), m in rows.items()
                    if p == pid and e != norm and m.status == STATUS_ACTIVE and m.role == ROLE_OWNER
                ]
                if not other_active_owners:
                    raise TenancyError(
                        "Cannot remove the last owner of a workspace — "
                        "make another member an owner first."
                    )
            now = _utc_now_iso()
            m = Membership(
                email=norm,
                profile_id=pid,
                role=current.role,
                status=STATUS_REMOVED,
                invited_by=current.invited_by,
                invited_via_profile_id=current.invited_via_profile_id,
                created_at=current.created_at,
                updated_at=now,
            )
            self._append(m)
        return m

    def erase_email(self, email: str) -> int:
        """Physically erase every membership row for an email (UK GDPR
        Art. 17 account deletion).

        Deliberately different from :meth:`remove`: ``remove`` appends a
        tombstone (which keeps the email on disk) and protects a bound org
        from losing its last owner — both wrong for an erasure request,
        where the email must leave the ledger entirely even if the
        workspace becomes unbound (the documented zero-member model).
        Compacting rewrite; returns rows removed.

        An erasure cannot be refused, so :meth:`remove`'s last-owner guard
        can't apply here — but a bare erase would strand a still-populated
        workspace the erased email *owned* with active members yet no owner
        (``is_bound`` stays true while ``is_active_owner`` is false for
        everyone), permanently locking every remaining member out of member
        admin, role changes, and org deletion. To keep such a workspace
        manageable, ownership passes to its longest-standing remaining active
        member. The erased person's own rows are still removed in full, so
        this is GDPR-consistent; only a *different*, already-trusted member is
        promoted. A workspace left with zero active members still unbinds (the
        documented zero-member model).
        """
        norm = normalize_email(email)
        with _LEDGER_LOCK:
            if not self._path.exists():
                return 0
            kept: list[dict] = []
            removed = 0
            try:
                text = self._path.read_text(encoding="utf-8")
            except OSError:
                return 0
            # Orgs the erased email actively OWNED (pre-erasure, last-write-wins).
            pre = self._read_all()
            owned_orgs = {
                pid
                for (e, pid), m in pre.items()
                if e == norm and m.status == STATUS_ACTIVE and m.role == ROLE_OWNER
            }
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and normalize_email(str(rec.get("email") or "")) == norm:
                    removed += 1
                    continue
                kept.append(rec)
            # Ownership succession: for each org the erased email owned that still
            # has active members but no active owner, promote the earliest-joined
            # remaining active member so the workspace does not become ownerless.
            promotions: list[dict] = []
            if owned_orgs:
                post: dict[tuple[str, str], Membership] = {}
                for rec in kept:
                    if not isinstance(rec, dict):
                        continue
                    m = Membership.from_record(rec)
                    if m.email and m.profile_id:
                        post[(m.email, m.profile_id)] = m
                for pid in owned_orgs:
                    actives = [
                        m for (e, p), m in post.items() if p == pid and m.status == STATUS_ACTIVE
                    ]
                    if not actives or any(m.role == ROLE_OWNER for m in actives):
                        continue
                    heir = min(actives, key=lambda m: (m.created_at or "~", m.email))
                    now = _utc_now_iso()
                    promotions.append(
                        Membership(
                            email=heir.email,
                            profile_id=pid,
                            role=ROLE_OWNER,
                            status=STATUS_ACTIVE,
                            invited_by=heir.invited_by,
                            invited_via_profile_id=heir.invited_via_profile_id,
                            created_at=heir.created_at or now,
                            updated_at=now,
                        ).to_record()
                    )
            if removed:
                tmp = self._path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    for rec in kept + promotions:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                tmp.replace(self._path)
            return removed

    def erase_profile(self, profile_id: str) -> int:
        """Physically erase every membership row for a workspace (PC.13
        whole-org deletion).

        The org is being deleted outright, so the last-owner protection in
        :meth:`remove` does not apply and tombstones would defeat the
        erasure — same compacting-rewrite rationale as :meth:`erase_email`.
        Returns rows removed.
        """
        pid = (profile_id or "").strip()
        if not pid:
            return 0
        with _LEDGER_LOCK:
            if not self._path.exists():
                return 0
            kept: list[dict] = []
            removed = 0
            try:
                text = self._path.read_text(encoding="utf-8")
            except OSError:
                return 0
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and str(rec.get("profile_id") or "").strip() == pid:
                    removed += 1
                    continue
                kept.append(rec)
            if removed:
                tmp = self._path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    for rec in kept:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                tmp.replace(self._path)
            return removed

    def activate_invites(self, email: str) -> list[Membership]:
        """Flip every ``invited`` row for this email to ``active``.

        Called on signup: this is the unattended first-claim path (ADR-0014) —
        the operator pre-binds a pilot club's contact email, and the org binds
        the moment that person creates their account, with no founder action.
        """
        norm = normalize_email(email)
        activated: list[Membership] = []
        with _LEDGER_LOCK:
            rows = self._read_all()
            now = _utc_now_iso()
            for (e, pid), m in rows.items():
                if e != norm or m.status != STATUS_INVITED:
                    continue
                up = Membership(
                    email=e,
                    profile_id=pid,
                    role=m.role,
                    status=STATUS_ACTIVE,
                    invited_by=m.invited_by,
                    invited_via_profile_id=m.invited_via_profile_id,
                    created_at=m.created_at,
                    updated_at=now,
                )
                self._append(up)
                activated.append(up)
        return activated
