"""mediahub/webhooks/_db.py — SQLite helpers for the outbound-webhook layer.

Two tables in the shared ``DATA_DIR/data.db``: ``webhook_endpoints`` (the
per-org registry of subscriber URLs) and ``webhook_deliveries`` (the durable
attempt log + retry queue). Same lazy, once-per-distinct-db bootstrap as the
rest of the SQLite stores, with the path resolved live so a per-test ``DATA_DIR``
override is honoured.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_PKG_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(_PKG_ROOT)))


def db_path() -> Path:
    return data_dir() / "data.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id               TEXT PRIMARY KEY,          -- whe_<hex>
    profile_id       TEXT NOT NULL,             -- owning org (tenant)
    url              TEXT NOT NULL,             -- subscriber endpoint
    secret           TEXT NOT NULL,             -- shared HMAC signing secret (whsec_...)
    events           TEXT NOT NULL DEFAULT '',  -- space-separated subscribed event names
    description      TEXT NOT NULL DEFAULT '',
    active           INTEGER NOT NULL DEFAULT 1,
    created_by       TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    last_delivery_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_profile
    ON webhook_endpoints(profile_id) WHERE active = 1;

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              TEXT PRIMARY KEY,           -- whd_<hex>
    endpoint_id     TEXT NOT NULL,
    profile_id      TEXT NOT NULL,
    event           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    response_code   INTEGER,
    error           TEXT,
    created_at      TEXT NOT NULL,
    last_attempt_at TEXT,
    next_attempt_at TEXT,                        -- when a pending delivery is due again
    delivered_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_due
    ON webhook_deliveries(next_attempt_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_endpoint
    ON webhook_deliveries(endpoint_id, created_at DESC);
"""

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
            log.warning("webhooks._db: schema bootstrap failed: %s", exc)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["data_dir", "db_path", "connect", "now"]
