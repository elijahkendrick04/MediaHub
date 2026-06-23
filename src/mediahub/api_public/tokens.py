"""mediahub/api_public/tokens.py — org-scoped API tokens (bearer auth).

The public API authenticates with **bearer tokens** instead of session cookies.
Each token is bound to exactly one organisation (``profile_id``) and carries an
explicit scope set (see ``scopes.py``). This is the access mechanism the REST
blueprint and the MCP server both ride on.

Security posture:
- **Only the hash is stored.** The full secret (``mhk_…``) is shown to the
  operator exactly once at creation; we persist ``sha256(secret)`` and verify by
  hashing the presented value, so a database leak never yields a usable token.
- **Lookup is O(1) and timing-flat.** Verification hashes the presented secret
  and selects on the indexed ``token_hash`` — there is no secret-dependent
  branch to time.
- **Revocation is tenant-scoped.** A token can only be revoked from within its
  own org, and revocation is a tombstone (``revoked_at``), preserving the audit
  trail.
- **Expiry is honoured at verify time** (optional per token).

Storage is ``DATA_DIR/data.db`` (table ``api_tokens``), bootstrapped lazily by
``_db.connect`` so it always agrees with the web layer and per-test isolation.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import _db
from .scopes import validate_scopes

# Secret prefix makes a leaked token grep-able (secret-scanning rules) and tells
# a reader at a glance what it is. The management-handle prefix is distinct so
# the two are never confused.
_SECRET_PREFIX = "mhk_"  # the bearer value the client sends
_ID_PREFIX = "mht_"  # the public, non-secret management handle
_SECRET_BYTES = 24  # 48 hex chars of entropy after the prefix


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _now() -> str:
    return _db.now()


@dataclass
class ApiToken:
    """A persisted token row, minus the secret (which is never retrievable)."""

    id: str
    profile_id: str
    name: str
    scopes: list[str] = field(default_factory=list)
    token_prefix: str = ""
    created_by: str = ""
    created_at: str = ""
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None

    def is_expired(self, *, at: Optional[datetime] = None) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            # An unparseable expiry is treated as expired — fail closed.
            return True
        ref = at or datetime.now(timezone.utc)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return ref >= exp

    def is_active(self) -> bool:
        return self.revoked_at is None and not self.is_expired()

    def to_public_dict(self) -> dict:
        """Safe to return over the API / show in the UI — never the secret."""
        return {
            "id": self.id,
            "name": self.name,
            "scopes": list(self.scopes),
            "token_prefix": self.token_prefix,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "active": self.is_active(),
        }


def _row_to_token(row) -> ApiToken:
    return ApiToken(
        id=row["id"],
        profile_id=row["profile_id"],
        name=row["name"] or "",
        scopes=(row["scopes"] or "").split(),
        token_prefix=row["token_prefix"] or "",
        created_by=row["created_by"] or "",
        created_at=row["created_at"] or "",
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


class ApiTokenStore:
    """CRUD over the ``api_tokens`` table. Stateless; opens a connection per call
    (matching the monolith's non-pooled SQLite convention)."""

    def create(
        self,
        profile_id: str,
        *,
        name: str = "",
        scopes=None,
        created_by: str = "",
        expires_at: Optional[str] = None,
    ) -> tuple[ApiToken, str]:
        """Mint a token. Returns ``(ApiToken, secret)`` — the secret is shown to
        the operator once and is unrecoverable thereafter."""
        profile_id = (profile_id or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required to mint a token")
        secret = _SECRET_PREFIX + secrets.token_hex(_SECRET_BYTES)
        token_id = _ID_PREFIX + uuid.uuid4().hex[:16]
        granted = validate_scopes(scopes)
        created = _now()
        tok = ApiToken(
            id=token_id,
            profile_id=profile_id,
            name=(name or "").strip()[:120],
            scopes=granted,
            token_prefix=secret[: len(_SECRET_PREFIX) + 8],
            created_by=(created_by or "").strip(),
            created_at=created,
            expires_at=(expires_at or None),
        )
        conn = _db.connect()
        try:
            conn.execute(
                """INSERT INTO api_tokens
                   (id, token_hash, token_prefix, profile_id, name, scopes,
                    created_by, created_at, last_used_at, expires_at, revoked_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tok.id,
                    _hash(secret),
                    tok.token_prefix,
                    tok.profile_id,
                    tok.name,
                    " ".join(tok.scopes),
                    tok.created_by,
                    tok.created_at,
                    None,
                    tok.expires_at,
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return tok, secret

    def verify(self, presented: str, *, touch: bool = True) -> Optional[ApiToken]:
        """Resolve a presented bearer secret to its token, or None.

        Returns None for unknown / revoked / expired tokens. On success updates
        ``last_used_at`` (best-effort; a write failure never fails the request)."""
        if not presented or not presented.startswith(_SECRET_PREFIX):
            return None
        conn = _db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM api_tokens WHERE token_hash=?", (_hash(presented),)
            ).fetchone()
            if row is None:
                return None
            tok = _row_to_token(row)
            if not tok.is_active():
                return None
            if touch:
                try:
                    conn.execute(
                        "UPDATE api_tokens SET last_used_at=? WHERE id=?",
                        (_now(), tok.id),
                    )
                    conn.commit()
                except Exception:
                    pass
            return tok
        finally:
            conn.close()

    def get(self, token_id: str) -> Optional[ApiToken]:
        conn = _db.connect()
        try:
            row = conn.execute("SELECT * FROM api_tokens WHERE id=?", (token_id,)).fetchone()
            return _row_to_token(row) if row else None
        finally:
            conn.close()

    def list_for_profile(self, profile_id: str, *, include_revoked: bool = False) -> list[ApiToken]:
        conn = _db.connect()
        try:
            if include_revoked:
                rows = conn.execute(
                    "SELECT * FROM api_tokens WHERE profile_id=? ORDER BY created_at DESC",
                    (profile_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM api_tokens WHERE profile_id=? AND revoked_at IS NULL "
                    "ORDER BY created_at DESC",
                    (profile_id,),
                ).fetchall()
            return [_row_to_token(r) for r in rows]
        finally:
            conn.close()

    def revoke(self, token_id: str, profile_id: str) -> bool:
        """Tombstone a token. Tenant-scoped: a token can only be revoked from
        within its own org. Returns True iff a row was revoked."""
        conn = _db.connect()
        try:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked_at=? "
                "WHERE id=? AND profile_id=? AND revoked_at IS NULL",
                (_now(), token_id, profile_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


__all__ = ["ApiToken", "ApiTokenStore"]
