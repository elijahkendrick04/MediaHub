"""mediahub/api_public/_db.py — shared SQLite helpers for the public-API layer.

Tokens (and, in roadmap 1.21's webhook half, delivery state) live in the same
``DATA_DIR/data.db`` the rest of the monolith uses. This mirrors the lazy,
once-per-distinct-db bootstrap that ``notify.inbox`` uses so the schema is
created on first touch and a per-test ``DATA_DIR`` override is always honoured.

Path is resolved **live** (call time), never cached at import, so tests that
monkeypatch ``DATA_DIR`` to a fresh temp dir get an isolated database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Default when DATA_DIR is unset: the mediahub package root (src/mediahub),
# matching notify.inbox / observability.llm_usage so dev runs share one data.db.
_PKG_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(_PKG_ROOT)))


def db_path() -> Path:
    return data_dir() / "data.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,        -- public token id (mht_<hex>), safe to show
    token_hash   TEXT NOT NULL UNIQUE,    -- sha256 of the full secret; the secret is never stored
    token_prefix TEXT NOT NULL,           -- first chars of the secret, for at-a-glance identification
    profile_id   TEXT NOT NULL,           -- the org this token acts as (tenant)
    name         TEXT NOT NULL DEFAULT '',-- human label ("Mobile app", "Zapier")
    scopes       TEXT NOT NULL DEFAULT '',-- space-separated granted scopes
    created_by   TEXT NOT NULL DEFAULT '',-- creator's email (audit)
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    expires_at   TEXT,                     -- optional ISO expiry; NULL = no expiry
    revoked_at   TEXT                      -- NULL = active
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_profile
    ON api_tokens(profile_id) WHERE revoked_at IS NULL;
"""

# Paths whose schema we've ensured this process — bootstrap runs once per
# distinct data.db (incl. once per fresh test DATA_DIR), not per connection.
_initialized: set[str] = set()


def connect() -> sqlite3.Connection:
    p = db_path()
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
    key = str(p)
    if key not in _initialized:
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            _initialized.add(key)
        except sqlite3.Error as exc:
            log.warning("api_public._db: schema bootstrap failed: %s", exc)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["data_dir", "db_path", "connect", "now"]
