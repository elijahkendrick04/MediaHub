"""collab/share_tokens.py — expiring, scoped, revocable review-share links (1.18).

A reviewer outside the workspace — a parent confirming their child's name, a
sponsor signing off their logo — can be handed a link that opens *one* run (or
one card) read-only, or with permission to comment, **without an account**. The
link carries an unguessable token; everything else (which run, which card,
view-vs-comment, when it expires, whether it's been revoked) lives in a ledger
in the shared ``data.db``, so a link can be listed, expired and revoked from the
review page.

Design mirrors the public wall (an unguessable ``secrets.token_urlsafe`` looked
up server-side, ADR-0003 isolation enforced at resolve time) rather than a
stateless signed token, precisely so a share can be **revoked before it
expires** — a signed-only token can't be. Conventions match
:mod:`mediahub.collab.threads`: short-lived connection, idempotent schema,
``db_path`` override, ``delete_for_run`` for the erasure cascade.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PERM_VIEW = "view"
PERM_COMMENT = "comment"
_PERMS = {PERM_VIEW, PERM_COMMENT}

# Expiry bounds (days). A share is short-lived by default; never unbounded.
DEFAULT_TTL_DAYS = 7
MAX_TTL_DAYS = 90
_TOKEN_BYTES = 24


class ShareTokenError(ValueError):
    """Invalid share-token input."""


@dataclass
class Share:
    token: str
    run_id: str
    card_id: str
    perm: str
    created_by: str
    created_at: float
    expires_at: float
    revoked: bool

    def to_public_dict(self) -> dict:
        """Metadata for the owner's management UI (the token is included so the
        owner can copy the link; never expose this to the public surface)."""
        return {
            "token": self.token,
            "run_id": self.run_id,
            "card_id": self.card_id,
            "perm": self.perm,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked": bool(self.revoked),
            "expired": self.expires_at < time.time(),
        }


def _default_db_path() -> Path:
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collab_share_tokens (
            token       TEXT PRIMARY KEY,
            run_id      TEXT NOT NULL,
            card_id     TEXT NOT NULL DEFAULT '',
            perm        TEXT NOT NULL DEFAULT 'view',
            created_by  TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            expires_at  REAL NOT NULL,
            revoked     INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_collab_shares_run
            ON collab_share_tokens(run_id, revoked);
        """
    )
    conn.commit()


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()


def _row_to_share(row: sqlite3.Row) -> Share:
    return Share(
        token=row["token"],
        run_id=row["run_id"],
        card_id=row["card_id"] or "",
        perm=row["perm"] or PERM_VIEW,
        created_by=row["created_by"] or "",
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        revoked=bool(row["revoked"]),
    )


def create_share(
    run_id: str,
    *,
    card_id: str = "",
    perm: str = PERM_VIEW,
    created_by: str = "",
    ttl_days: int = DEFAULT_TTL_DAYS,
    db_path: Optional[Path] = None,
) -> Share:
    """Mint a new scoped, expiring share link. Returns the :class:`Share`."""
    run_id = (run_id or "").strip()
    if not run_id:
        raise ShareTokenError("run_id is required")
    perm = (perm or PERM_VIEW).strip().lower()
    if perm not in _PERMS:
        raise ShareTokenError("perm must be 'view' or 'comment'")
    try:
        ttl = int(ttl_days)
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_DAYS
    ttl = max(1, min(MAX_TTL_DAYS, ttl))
    now = time.time()
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    share = Share(
        token=token,
        run_id=run_id,
        card_id=(card_id or "").strip(),
        perm=perm,
        created_by=(created_by or "").strip().lower(),
        created_at=now,
        expires_at=now + ttl * 86400,
        revoked=False,
    )
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO collab_share_tokens"
            "(token,run_id,card_id,perm,created_by,created_at,expires_at,revoked) "
            "VALUES(?,?,?,?,?,?,?,0)",
            (
                share.token,
                share.run_id,
                share.card_id,
                share.perm,
                share.created_by,
                share.created_at,
                share.expires_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return share


def resolve(token: str, *, db_path: Optional[Path] = None) -> Optional[Share]:
    """Resolve a token to its live :class:`Share`, or ``None`` when the token is
    unknown, revoked, or expired — the single gate the public routes call."""
    token = (token or "").strip()
    if not token:
        return None
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM collab_share_tokens WHERE token=?", (token,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    share = _row_to_share(row)
    if share.revoked or share.expires_at < time.time():
        return None
    return share


def list_for_run(
    run_id: str, *, include_revoked: bool = False, db_path: Optional[Path] = None
) -> list[Share]:
    """Active (or all) shares for a run, newest first, for the owner's UI."""
    run_id = (run_id or "").strip()
    if not run_id:
        return []
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT * FROM collab_share_tokens WHERE run_id=?"
        params: list = [run_id]
        if not include_revoked:
            q += " AND revoked=0"
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    return [_row_to_share(r) for r in rows]


def revoke(token: str, *, run_id: Optional[str] = None, db_path: Optional[Path] = None) -> bool:
    """Revoke a share immediately. ``run_id`` scopes the revoke to its run."""
    token = (token or "").strip()
    if not token:
        return False
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if run_id is not None:
            cur = conn.execute(
                "UPDATE collab_share_tokens SET revoked=1 WHERE token=? AND run_id=?",
                (token, run_id),
            )
        else:
            cur = conn.execute("UPDATE collab_share_tokens SET revoked=1 WHERE token=?", (token,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_for_run(run_id: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every share for a run — the erasure cascade calls this."""
    if not (run_id or "").strip():
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM collab_share_tokens WHERE run_id=?", (run_id,))
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


__all__ = [
    "PERM_VIEW",
    "PERM_COMMENT",
    "DEFAULT_TTL_DAYS",
    "MAX_TTL_DAYS",
    "Share",
    "ShareTokenError",
    "init_schema",
    "create_share",
    "resolve",
    "list_for_run",
    "revoke",
    "delete_for_run",
]
