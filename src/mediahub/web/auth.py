"""
PC.1 — minimal self-serve email + password authentication.

This is the signup/login/session half of Phase C (Appendix B Step 7). It is
deliberately small and dependency-light:

  - Users live in a JSON-lines ledger under ``DATA_DIR/users.jsonl`` — one
    object per line ``{email, hashed_password, plan, stripe_customer_id,
    created_at}``. No SQLAlchemy, no new database; the existing ``DATA_DIR``
    persistence convention is reused (mirrors ``club_profile._profiles_dir``).
  - Passwords are hashed with **bcrypt** (the maintained ``bcrypt`` package).
    The Step 7 prompt says "passlib bcrypt"; passlib 1.7.x cannot load a
    bcrypt 4.1+/5.x backend (it reads the removed ``bcrypt.__about__``), so we
    call ``bcrypt`` directly. Same algorithm, same ``$2b$`` hashes, no broken
    indirection. Documented as a deviation in the PR.
  - Sessions ride Flask's **signed** session cookie (``app.secret_key``); we
    only stash the user's email under ``session["user_email"]``. Cookie
    hardening (HttpOnly always, Secure when HTTPS, signed) is configured in
    ``web.create_app``.

Auth is **optional**: a self-hosted deployment with no billing configured and
no accounts simply never sends anyone here, and every existing route stays
open. Nothing in this module imports Stripe or requires any billing env var.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import bcrypt
from flask import session

# Tier identifiers. "free" is the always-available default; "club" and
# "federation" are the paid tiers driven by Stripe (see billing.py). These are
# plan *names*, never prices — pricing is unvalidated and lives only in env.
PLAN_FREE = "free"
PLAN_CLUB = "club"
PLAN_FEDERATION = "federation"
VALID_PLANS = frozenset({PLAN_FREE, PLAN_CLUB, PLAN_FEDERATION})

# bcrypt truncates silently at 72 bytes in older releases and *raises* in
# 5.x. We cap explicitly so a long passphrase is handled identically on every
# bcrypt version rather than 500-ing.
_BCRYPT_MAX_BYTES = 72

# Free-tier soft limit (PC.4 / Step 7): runs per calendar month. This drives a
# UI banner only — never a hard lockout. Not a price; a usage allowance.
FREE_TIER_RUNS_PER_MONTH = 3

# Serialise ledger writes within a process. The ledger is append/rewrite only
# and tiny, so a coarse lock is plenty and avoids interleaved writes when two
# requests sign up at once on the threaded dev server.
_LEDGER_LOCK = threading.Lock()


class AuthError(Exception):
    """Raised for expected, user-facing auth failures (clean error, not 500)."""


@dataclass
class User:
    email: str
    hashed_password: str
    plan: str = PLAN_FREE
    stripe_customer_id: str = ""
    created_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "User":
        return cls(
            email=str(d.get("email", "")).strip().lower(),
            hashed_password=str(d.get("hashed_password", "")),
            plan=_coerce_plan(d.get("plan")),
            stripe_customer_id=str(d.get("stripe_customer_id", "") or ""),
            created_at=str(d.get("created_at", "") or ""),
        )


def _coerce_plan(plan: object) -> str:
    p = str(plan or "").strip().lower()
    return p if p in VALID_PLANS else PLAN_FREE


def normalize_email(email: str) -> str:
    """Canonical form used as the ledger key: trimmed + lowercased."""
    return (email or "").strip().lower()


def _looks_like_email(email: str) -> bool:
    # Deliberately liberal — one ``@`` with non-empty local + domain parts and
    # a dot in the domain. We are not RFC-validating; we are catching obvious
    # typos before they become an un-loginnable account.
    if not email or email.count("@") != 1:
        return False
    if email.strip() != email:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and bool(domain) and "." in domain


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash string for ``plaintext`` (``$2b$`` format)."""
    raw = (plaintext or "").encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time check of ``plaintext`` against a stored bcrypt hash.

    Never raises on a malformed/empty stored hash — returns ``False`` so a
    wrong password (or corrupted record) is a clean auth failure, not a 500.
    """
    raw = (plaintext or "").encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, (hashed or "").encode("utf-8"))
    except (ValueError, TypeError):
        return False


class UserStore:
    """JSON-lines user ledger under ``DATA_DIR``.

    Last-write-wins on email: a re-saved user appends a new line and reads
    coalesce to the latest record for a given email. This keeps writes append
    only (crash-safe) while letting plan/customer-id updates land without an
    in-place rewrite of the whole file.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _users_path()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> dict[str, User]:
        """Return ``{email: User}`` with later lines overriding earlier ones."""
        out: dict[str, User] = {}
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
                continue  # tolerate a torn final line; never crash login
            if not isinstance(rec, dict):
                continue
            u = User.from_record(rec)
            if u.email:
                out[u.email] = u
        return out

    def get(self, email: str) -> Optional[User]:
        return self._read_all().get(normalize_email(email))

    def exists(self, email: str) -> bool:
        return normalize_email(email) in self._read_all()

    def _append(self, user: User) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(user.to_record(), ensure_ascii=False) + "\n")
        # The ledger holds password hashes — keep it owner-readable only so a
        # co-tenant on a shared host can't read it (mirrors the .secret_key
        # hardening in web.create_app).
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def create(self, email: str, plaintext_password: str) -> User:
        """Create + persist a new user. Raises ``AuthError`` on bad input/dup."""
        norm = normalize_email(email)
        if not _looks_like_email(norm):
            raise AuthError("Enter a valid email address.")
        if len(plaintext_password or "") < 8:
            raise AuthError("Password must be at least 8 characters.")
        with _LEDGER_LOCK:
            if norm in self._read_all():
                raise AuthError("An account with that email already exists.")
            user = User(
                email=norm,
                hashed_password=hash_password(plaintext_password),
                plan=PLAN_FREE,
                stripe_customer_id="",
                created_at=_utc_now_iso(),
            )
            self._append(user)
        return user

    def authenticate(self, email: str, plaintext_password: str) -> User:
        """Return the user on a correct password, else raise ``AuthError``.

        The same generic message is used for both unknown-email and
        wrong-password so we don't leak which emails are registered.
        """
        user = self.get(email)
        # Always run a verify (against the real or a throwaway hash) so the
        # response time doesn't betray whether the email exists.
        reference = user.hashed_password if user else _DUMMY_HASH
        ok = verify_password(plaintext_password, reference)
        if not user or not ok:
            raise AuthError("Incorrect email or password.")
        return user

    def set_plan(
        self,
        email: str,
        plan: str,
        *,
        stripe_customer_id: Optional[str] = None,
    ) -> Optional[User]:
        """Update a user's plan (+ optional customer id). Returns the user or None."""
        with _LEDGER_LOCK:
            users = self._read_all()
            user = users.get(normalize_email(email))
            if user is None:
                return None
            user.plan = _coerce_plan(plan)
            if stripe_customer_id is not None:
                user.stripe_customer_id = str(stripe_customer_id or "")
            self._append(user)
            return user

    def find_by_customer_id(self, customer_id: str) -> Optional[User]:
        """Look a user up by their Stripe customer id (webhook reconciliation)."""
        cid = str(customer_id or "").strip()
        if not cid:
            return None
        for user in self._read_all().values():
            if user.stripe_customer_id == cid:
                return user
        return None


# A valid-but-unmatchable bcrypt hash, computed once, for timing-equalised
# authentication of unknown emails.
_DUMMY_HASH = hash_password("mediahub-timing-equaliser-not-a-real-password")


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    """Resolve DATA_DIR at call time (tests monkeypatch the env var)."""
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _users_path() -> Path:
    return _data_dir() / "users.jsonl"


# ---- Session helpers ----------------------------------------------------
#
# Sessions carry only the user's email; the record is reloaded from the ledger
# so a plan change (via webhook) is reflected on the next request without
# re-login.

_SESSION_KEY = "user_email"


def login_user(user: User) -> None:
    session[_SESSION_KEY] = user.email


def logout_user() -> None:
    session.pop(_SESSION_KEY, None)


def current_user_email() -> Optional[str]:
    email = session.get(_SESSION_KEY)
    return normalize_email(email) if email else None


def current_user(store: Optional[UserStore] = None) -> Optional[User]:
    email = current_user_email()
    if not email:
        return None
    store = store or UserStore()
    user = store.get(email)
    if user is None:
        # Stale session (account removed) — drop it so we report signed-out.
        session.pop(_SESSION_KEY, None)
    return user


def current_plan(store: Optional[UserStore] = None) -> str:
    """The signed-in user's plan, or ``free`` when signed out.

    Signed-out (no accounts / self-host) deliberately resolves to ``free`` so
    premium gates are *closed* for anonymous visitors while every existing
    open route still works — the soft-limit banner is the only consequence.
    """
    user = current_user(store)
    return user.plan if user else PLAN_FREE


def is_premium(plan: Optional[str] = None) -> bool:
    """True when the plan unlocks paid features (Club or Federation)."""
    p = plan if plan is not None else current_plan()
    return p in (PLAN_CLUB, PLAN_FEDERATION)


def plan_label(plan: str) -> str:
    return {
        PLAN_FREE: "Free",
        PLAN_CLUB: "Club",
        PLAN_FEDERATION: "Federation",
    }.get(_coerce_plan(plan), "Free")
