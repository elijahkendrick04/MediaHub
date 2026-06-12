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

import hmac
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import bcrypt
from argon2 import PasswordHasher as _Argon2Hasher
from flask import session

# argon2id with argon2-cffi defaults (t=3, m=64MiB, p=4) — ASVS L2 V2.4.
_ARGON2 = _Argon2Hasher()

# Tier identifiers. "free" is the always-available default; "club" and
# "federation" are the paid tiers driven by Stripe (see billing.py). These are
# plan *names*, never prices — pricing is unvalidated and lives only in env.
PLAN_FREE = "free"
PLAN_CLUB = "club"
PLAN_FEDERATION = "federation"
# Operator-only "unrestricted" tier — never purchasable and never set by Stripe;
# granted solely by the env-gated developer sign-in (see login_dev_operator).
PLAN_OWNER = "owner"
VALID_PLANS = frozenset({PLAN_FREE, PLAN_CLUB, PLAN_FEDERATION, PLAN_OWNER})

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
    # When the address proved it can receive our mail (PC.14). Empty = not
    # verified; purely informational — no feature gates on it.
    email_verified_at: str = ""
    totp_secret: str = ""  # empty = 2FA off; set via /account/2fa

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
            email_verified_at=str(d.get("email_verified_at", "") or ""),
            totp_secret=str(d.get("totp_secret", "") or ""),
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
    """Return an **argon2id** hash for ``plaintext`` (ASVS L2 V2.4).

    New and re-hashed passwords use argon2id (argon2-cffi defaults:
    t=3, m=64MiB, p=4). Existing ``$2b$`` bcrypt hashes keep verifying —
    they are upgraded transparently on the next successful login
    (see ``UserStore.authenticate``).
    """
    return _ARGON2.hash(plaintext or "")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time check against a stored argon2id OR legacy bcrypt hash.

    Never raises on a malformed/empty stored hash — returns ``False`` so a
    wrong password (or corrupted record) is a clean auth failure, not a 500.
    """
    stored = hashed or ""
    if stored.startswith("$argon2"):
        try:
            return _ARGON2.verify(stored, plaintext or "")
        except Exception:
            return False
    raw = (plaintext or "").encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, stored.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True when the stored hash should be upgraded to current argon2id."""
    stored = hashed or ""
    if not stored.startswith("$argon2"):
        return True  # legacy bcrypt (or unknown) → upgrade on next login
    try:
        return _ARGON2.check_needs_rehash(stored)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Account lockout (ASVS V2.2): per normalised email, in-process. 5 failures
# in 15 minutes locks the ACCOUNT for 15 minutes. Deliberately NOT keyed on
# client address: per-IP volume limiting is the web layer's per-app auth
# limiter (web.py _auth_rate_limited) — an address key here would let one
# bad actor behind a club's shared NAT lock out the whole club (and lets a
# spoofed X-Forwarded-For lock arbitrary keys). In-memory by design (a
# restart clears it); every lockout is written to the security event log so
# a pattern survives restarts as evidence.
# ---------------------------------------------------------------------------

LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECS = 15 * 60
_failed_logins: dict[str, list[float]] = {}
_FAIL_LOCK = threading.Lock()


def login_locked(email: str) -> bool:
    norm = normalize_email(email)
    if not norm:
        return False
    now = time.time()
    with _FAIL_LOCK:
        window = [t for t in _failed_logins.get(norm, []) if now - t < LOGIN_FAILURE_WINDOW_SECS]
        _failed_logins[norm] = window
        return len(window) >= LOGIN_FAILURE_LIMIT


def record_login_failure(email: str) -> bool:
    """Record one failure; returns True when this failure triggers a lockout."""
    norm = normalize_email(email)
    if not norm:
        return False
    now = time.time()
    with _FAIL_LOCK:
        window = [t for t in _failed_logins.get(norm, []) if now - t < LOGIN_FAILURE_WINDOW_SECS]
        window.append(now)
        _failed_logins[norm] = window
        return len(window) == LOGIN_FAILURE_LIMIT


def clear_login_failures(email: str) -> None:
    norm = normalize_email(email)
    if norm:
        with _FAIL_LOCK:
            _failed_logins.pop(norm, None)


# ---------------------------------------------------------------------------
# TOTP (RFC 6238) — optional second factor, stdlib-only (hmac + struct), no
# new dependency. 30s steps, 6 digits, ±1 step of clock skew.
# ---------------------------------------------------------------------------


def totp_generate_secret() -> str:
    import base64
    import secrets as _secrets

    return base64.b32encode(_secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_code(secret: str, counter: int) -> str:
    import base64
    import hashlib
    import struct

    pad = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode((secret + pad).upper())
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_verify(secret: str, code: str, *, at: Optional[float] = None) -> bool:
    if not secret or not code:
        return False
    cleaned = str(code).strip().replace(" ", "")
    if not cleaned.isdigit() or len(cleaned) != 6:
        return False
    counter = int((at if at is not None else time.time()) // 30)
    for skew in (-1, 0, 1):
        if hmac.compare_digest(_totp_code(secret, counter + skew), cleaned):
            return True
    return False


def totp_provisioning_uri(secret: str, email: str, issuer: str = "MediaHub") -> str:
    from urllib.parse import quote

    label = quote(f"{issuer}:{normalize_email(email)}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


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
        # Transparent upgrade: a verified legacy bcrypt (or stale-parameter
        # argon2) hash is re-hashed with current argon2id and re-appended.
        if password_needs_rehash(user.hashed_password):
            try:
                with _LEDGER_LOCK:
                    user.hashed_password = hash_password(plaintext_password)
                    self._append(user)
            except OSError:
                pass  # upgrade is best-effort; login still succeeds
        return user

    def set_totp(self, email: str, secret: str) -> Optional[User]:
        """Set (or clear, with "") the user's TOTP secret."""
        with _LEDGER_LOCK:
            users = self._read_all()
            user = users.get(normalize_email(email))
            if user is None:
                return None
            user.totp_secret = str(secret or "")
            self._append(user)
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

    def set_password(self, email: str, new_plaintext: str) -> Optional[User]:
        """Replace an account's password (PC.14 reset flow). Returns the
        user, or None for an unknown email. Raises AuthError on a weak
        password — same rule as signup."""
        if len(new_plaintext or "") < 8:
            raise AuthError("Password must be at least 8 characters.")
        with _LEDGER_LOCK:
            user = self._read_all().get(normalize_email(email))
            if user is None:
                return None
            user.hashed_password = hash_password(new_plaintext)
            self._append(user)
            return user

    def mark_email_verified(self, email: str) -> Optional[User]:
        """Stamp the account as having received our verification mail."""
        with _LEDGER_LOCK:
            user = self._read_all().get(normalize_email(email))
            if user is None:
                return None
            user.email_verified_at = _utc_now_iso()
            self._append(user)
            return user

    def all_emails(self) -> list[str]:
        """Every account email (the operator breach-notice audience)."""
        return sorted(self._read_all().keys())

    def delete(self, email: str) -> bool:
        """Erase an account from the ledger entirely (UK GDPR Art. 17).

        Unlike every other write this is a compacting rewrite, not an
        append — a tombstone line would keep the email on disk, defeating
        the erasure. Returns True when a record was removed.
        """
        norm = normalize_email(email)
        with _LEDGER_LOCK:
            users = self._read_all()
            if norm not in users:
                return False
            del users[norm]
            tmp = self._path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for user in users.values():
                    fh.write(json.dumps(user.to_record(), ensure_ascii=False) + "\n")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self._path)
            return True

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

# ---- Operator / developer access ---------------------------------------
# An env-gated, no-paywall sign-in for the operator running the deployment. It
# does not exist unless MEDIAHUB_DEV_KEY is set in the environment, so it is
# never a public backdoor. The key is read from the environment only — never
# hardcoded, never logged — matching the project's API-keys-in-env rule.
_DEV_SESSION_KEY = "dev_operator"


def dev_login_enabled() -> bool:
    """True only when the operator has configured MEDIAHUB_DEV_KEY in env."""
    return bool((os.environ.get("MEDIAHUB_DEV_KEY") or "").strip())


def _dev_operator_email() -> str:
    """The synthetic operator identity's email (configurable, never logged)."""
    return normalize_email(os.environ.get("MEDIAHUB_DEV_EMAIL") or "developer@mediahub.local")


def verify_dev_key(candidate: object) -> bool:
    """Constant-time check of a submitted key against MEDIAHUB_DEV_KEY.

    Always False when no key is configured, so the route cannot be coerced into
    granting access on an unconfigured deployment.
    """
    key = (os.environ.get("MEDIAHUB_DEV_KEY") or "").strip()
    if not key:
        return False
    return hmac.compare_digest(key, str(candidate or "").strip())


def login_dev_operator() -> None:
    """Establish an unrestricted operator session (Flask signed cookie)."""
    session[_DEV_SESSION_KEY] = True


def is_dev_operator() -> bool:
    """True when the session is the operator AND the key is still configured.

    Re-checking the env means removing MEDIAHUB_DEV_KEY instantly revokes every
    outstanding operator session.
    """
    return bool(session.get(_DEV_SESSION_KEY)) and dev_login_enabled()


def login_user(user: User) -> None:
    session[_SESSION_KEY] = user.email


def logout_user() -> None:
    session.pop(_SESSION_KEY, None)
    session.pop(_DEV_SESSION_KEY, None)


def current_user_email() -> Optional[str]:
    email = session.get(_SESSION_KEY)
    return normalize_email(email) if email else None


def current_user(store: Optional[UserStore] = None) -> Optional[User]:
    # Operator developer session — a synthetic, non-persisted unrestricted
    # identity. Checked first so it never depends on the users.jsonl ledger.
    if is_dev_operator():
        return User(email=_dev_operator_email(), hashed_password="", plan=PLAN_OWNER)
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
    """True when the plan unlocks paid features (Club, Federation, or the
    operator-only Owner tier)."""
    p = plan if plan is not None else current_plan()
    return p in (PLAN_CLUB, PLAN_FEDERATION, PLAN_OWNER)


def plan_label(plan: str) -> str:
    return {
        PLAN_FREE: "Free",
        PLAN_CLUB: "Club",
        PLAN_FEDERATION: "Federation",
        PLAN_OWNER: "Developer",
    }.get(_coerce_plan(plan), "Free")
