"""Magic-link mobile approvals — W.9 token layer.

HMAC-signed, expiring, run-scoped review tokens (itsdangerous, keyed off
the app SECRET_KEY). A token lets an approver on a phone open ONE run's
lite review surface with no login. Tokens are revocable per run: every
run has a version counter in ``data.db``; revoking bumps the counter and
every previously minted token for that run dies instantly.

Also closes the KNOWN_ISSUES unsigned-run-id gap for this surface: the
run id inside the token is signed, so it can't be tampered into another
org's run.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "mediahub-magic-review-link-v1"

DEFAULT_MAX_AGE_HOURS = 72


class MagicLinkError(Exception):
    """Base — invalid token."""


class MagicLinkExpired(MagicLinkError):
    """Token older than its max age."""


class MagicLinkRevoked(MagicLinkError):
    """Token version superseded by a revocation."""


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return data_dir / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = _db_path(db_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS magic_link_versions (
                run_id  TEXT PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _current_version(run_id: str, db_path: Optional[Path] = None) -> int:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT version FROM magic_link_versions WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row["version"]) if row else 1
    finally:
        conn.close()


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise MagicLinkError("no signing secret configured")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def mint_review_token(
    secret: str, run_id: str, profile_id: str, *, db_path: Optional[Path] = None
) -> str:
    """Mint a signed, expiring, revocable review token for one run."""
    if not run_id:
        raise MagicLinkError("run_id required")
    payload = {
        "r": run_id,
        "p": profile_id or "",
        "v": _current_version(run_id, db_path),
    }
    return _serializer(secret).dumps(payload)


def verify_review_token(
    secret: str,
    token: str,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    db_path: Optional[Path] = None,
) -> dict:
    """Validate a token → ``{"run_id", "profile_id"}``.

    Raises MagicLinkExpired / MagicLinkRevoked / MagicLinkError. Callers
    must treat all three as access denial (with honest copy for each).
    """
    try:
        payload = _serializer(secret).loads(token, max_age=int(max_age_hours * 3600))
    except SignatureExpired as e:
        raise MagicLinkExpired("this review link has expired") from e
    except BadSignature as e:
        raise MagicLinkError("invalid review link") from e
    if not isinstance(payload, dict) or not payload.get("r"):
        raise MagicLinkError("invalid review link")
    run_id = str(payload["r"])
    if int(payload.get("v") or 0) != _current_version(run_id, db_path):
        raise MagicLinkRevoked("this review link has been revoked")
    return {"run_id": run_id, "profile_id": str(payload.get("p") or "")}


def revoke_run_tokens(run_id: str, db_path: Optional[Path] = None) -> int:
    """Kill every outstanding link for a run. Returns the new version."""
    _ensure_schema(db_path)
    new_version = _current_version(run_id, db_path) + 1
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO magic_link_versions (run_id, version) VALUES (?,?)"
            " ON CONFLICT(run_id) DO UPDATE SET version = excluded.version",
            (run_id, new_version),
        )
        conn.commit()
    finally:
        conn.close()
    return new_version
