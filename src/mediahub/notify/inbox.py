"""mediahub.notify.inbox — the per-organisation in-app notifications inbox.

UI 1.14. A persistent, multi-tenant store of the milestone events a club's
operators want to see *without* configuring an external channel: a content pack
became ready for review, a reel finished rendering, or a run / render hit an
error. It backs the bell-icon dropdown in the app chrome — the unread-count
badge, the dropdown list, and mark-as-read.

This is the always-on, no-config companion to the fire-and-forget push layer in
:mod:`mediahub.notify` (ntfy / webhook). Every milestone is *recorded* here, so
it shows up in the bell even when no push channel is configured, and is
*additionally* pushed to whatever channel the operator opted into. Neither path
blocks the pipeline: recording is best-effort and **never raises** — a logging
warning is the worst that happens.

Storage is the shared ``DATA_DIR/data.db`` SQLite file, following the same
connection / idempotent-schema convention as :mod:`mediahub.observability`
and the scheduler. Every row is scoped by ``org_id`` (the active ClubProfile
id), so one club's notifications can never surface in another's inbox — the
same multi-tenant isolation the run routes enforce. The ``DATA_DIR`` is
resolved live on each connection (not cached at import) so the store always
agrees with the web layer's ``data.db``, including under test isolation that
points ``DATA_DIR`` at a fresh temp dir per test.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary — kinds drive the dropdown icon; levels drive the dot / toast tint.
# ---------------------------------------------------------------------------

KIND_PACK_READY = "pack_ready"
KIND_RENDER_COMPLETE = "render_complete"
KIND_ERROR = "error"
KIND_INFO = "info"
_KINDS = {KIND_PACK_READY, KIND_RENDER_COMPLETE, KIND_ERROR, KIND_INFO}

LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"
_LEVELS = {LEVEL_INFO, LEVEL_SUCCESS, LEVEL_WARNING, LEVEL_ERROR}

_TITLE_MAX = 200
_BODY_MAX = 1000

# Bound the table so a busy org can't grow it without limit — we keep only the
# newest N rows per org. Overridable from tests via monkeypatch.
_MAX_PER_ORG = 200

_LIST_LIMIT_DEFAULT = 20
_LIST_LIMIT_MAX = 50


# ---------------------------------------------------------------------------
# Storage paths — same convention as the rest of the SQLite stores, but
# resolved live so a per-test DATA_DIR override is always honoured.
# ---------------------------------------------------------------------------

# Default when DATA_DIR is unset: the mediahub package root (src/mediahub),
# matching observability.llm_usage so dev runs share one data.db.
_PKG_ROOT = Path(__file__).resolve().parents[1]


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(_PKG_ROOT)))


def _db_path() -> Path:
    return _data_dir() / "data.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT 'info',
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    run_id      TEXT,
    click_url   TEXT,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_org_created
    ON notifications(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_org_unread
    ON notifications(org_id, read_at);
"""

# Paths whose schema we've already ensured this process — so the idempotent
# bootstrap runs once per distinct data.db (incl. once per fresh test DATA_DIR)
# rather than on every connection.
_initialized: set[str] = set()


def _connect() -> sqlite3.Connection:
    p = _db_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    key = str(p)
    if key not in _initialized:
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            _initialized.add(key)
        except sqlite3.Error as exc:
            log.warning("notify.inbox: schema bootstrap failed: %s", exc)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def record(
    org_id: str,
    kind: str,
    title: str,
    body: str = "",
    *,
    level: str = LEVEL_INFO,
    run_id: Optional[str] = None,
    click_url: Optional[str] = None,
    ts: Optional[str] = None,
) -> Optional[str]:
    """Append one notification to ``org_id``'s inbox. Returns its id, or
    ``None`` when nothing was written (missing org / title, or a DB error).

    Never raises — a notification must never break the run that triggered it.
    ``kind`` and ``level`` are normalised to the known vocabulary (unknown
    values fall back to ``info``); ``title`` / ``body`` are trimmed and capped.
    """
    org_id = (org_id or "").strip()
    title = (title or "").strip()
    if not org_id or not title:
        return None

    kind = (kind or "").strip().lower()
    if kind not in _KINDS:
        kind = KIND_INFO
    level = (level or "").strip().lower()
    if level not in _LEVELS:
        level = LEVEL_INFO

    title = title[:_TITLE_MAX]
    body = (body or "").strip()[:_BODY_MAX]
    run_id = (run_id or "").strip() or None
    click_url = (click_url or "").strip() or None
    nid = "ntf_" + uuid.uuid4().hex
    created = (ts or "").strip() or _now()

    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO notifications "
                "(id, org_id, kind, level, title, body, run_id, click_url, created_at, read_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (nid, org_id, kind, level, title, body, run_id, click_url, created),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("notify.inbox: record failed: %s", exc)
        return None

    # Keep the table bounded — a cheap, self-limiting trim (no-op below the cap).
    try:
        _prune_org(org_id)
    except sqlite3.Error:
        pass
    return nid


def record_pack_ready(
    org_id: str,
    run_id: str,
    *,
    count: Optional[int] = None,
    click_url: Optional[str] = None,
) -> Optional[str]:
    """The "content pack is ready for review" event, fired when a run finishes."""
    if count is not None:
        try:
            n = int(count)
            body = f"{n} card{'s' if n != 1 else ''} ready for review."
        except (TypeError, ValueError):
            body = "Your content pack is ready for review."
    else:
        body = "Your content pack is ready for review."
    return record(
        org_id,
        KIND_PACK_READY,
        "Pack ready for review",
        body,
        level=LEVEL_SUCCESS,
        run_id=run_id,
        click_url=click_url,
    )


def record_render_complete(
    org_id: str,
    *,
    run_id: Optional[str] = None,
    label: str = "reel",
    click_url: Optional[str] = None,
) -> Optional[str]:
    """A motion render (reel / story) finished and is ready to download."""
    label = (label or "reel").strip() or "reel"
    title = f"{label[:1].upper()}{label[1:]} ready"
    return record(
        org_id,
        KIND_RENDER_COMPLETE,
        title,
        f"Your {label} finished rendering and is ready to download.",
        level=LEVEL_SUCCESS,
        run_id=run_id,
        click_url=click_url,
    )


def record_error(
    org_id: str,
    title: str,
    body: str = "",
    *,
    run_id: Optional[str] = None,
    click_url: Optional[str] = None,
) -> Optional[str]:
    """A run or render failed — surfaced so the operator isn't left guessing."""
    return record(
        org_id,
        KIND_ERROR,
        title or "Something went wrong",
        body,
        level=LEVEL_ERROR,
        run_id=run_id,
        click_url=click_url,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_for(
    org_id: str,
    *,
    limit: int = _LIST_LIMIT_DEFAULT,
    unread_only: bool = False,
) -> list[dict]:
    """Newest-first notifications for ``org_id`` (capped at ``_LIST_LIMIT_MAX``)."""
    org_id = (org_id or "").strip()
    if not org_id:
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = _LIST_LIMIT_DEFAULT
    limit = max(1, min(_LIST_LIMIT_MAX, limit))

    sql = (
        "SELECT id, kind, level, title, body, run_id, click_url, created_at, read_at "
        "FROM notifications WHERE org_id = ?"
    )
    params: list = [org_id]
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(limit)

    try:
        conn = _connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("notify.inbox: list failed: %s", exc)
        return []

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "level": r["level"],
                "title": r["title"],
                "body": r["body"] or "",
                "run_id": r["run_id"] or "",
                "click_url": r["click_url"] or "",
                "created_at": r["created_at"],
                "read": r["read_at"] is not None,
            }
        )
    return out


def unread_count(org_id: str) -> int:
    """How many unread notifications ``org_id`` has (0 on any error)."""
    org_id = (org_id or "").strip()
    if not org_id:
        return 0
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM notifications WHERE org_id = ? AND read_at IS NULL",
                (org_id,),
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("notify.inbox: unread_count failed: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


def mark_read(org_id: str, notif_id: str) -> bool:
    """Mark one notification read. Returns ``True`` only when a row changed —
    the ``org_id`` guard makes this a no-op for another org's id (tenant
    isolation), and the ``read_at IS NULL`` guard makes it idempotent."""
    org_id = (org_id or "").strip()
    notif_id = (notif_id or "").strip()
    if not org_id or not notif_id:
        return False
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read_at = ? "
                "WHERE id = ? AND org_id = ? AND read_at IS NULL",
                (_now(), notif_id, org_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("notify.inbox: mark_read failed: %s", exc)
        return False


def mark_all_read(org_id: str) -> int:
    """Mark every unread notification for ``org_id`` read; returns the count."""
    org_id = (org_id or "").strip()
    if not org_id:
        return 0
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read_at = ? WHERE org_id = ? AND read_at IS NULL",
                (_now(), org_id),
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("notify.inbox: mark_all_read failed: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _prune_org(org_id: str, cap: Optional[int] = None) -> int:
    """Trim ``org_id`` to its newest ``cap`` rows. Caller handles errors."""
    keep = _MAX_PER_ORG if cap is None else int(cap)
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM notifications WHERE org_id = ? AND rowid NOT IN ("
            "  SELECT rowid FROM notifications WHERE org_id = ? "
            "  ORDER BY created_at DESC, rowid DESC LIMIT ?"
            ")",
            (org_id, org_id, keep),
        )
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


def prune(*, max_per_org: Optional[int] = None) -> int:
    """Trim every org to its newest ``max_per_org`` rows. Returns rows removed."""
    cap = _MAX_PER_ORG if max_per_org is None else int(max_per_org)
    removed = 0
    try:
        conn = _connect()
        try:
            orgs = [
                r["org_id"]
                for r in conn.execute("SELECT DISTINCT org_id FROM notifications").fetchall()
            ]
        finally:
            conn.close()
        for o in orgs:
            removed += _prune_org(o, cap)
    except sqlite3.Error as exc:
        log.warning("notify.inbox: prune failed: %s", exc)
    return removed


__all__ = [
    "record",
    "record_pack_ready",
    "record_render_complete",
    "record_error",
    "list_for",
    "unread_count",
    "mark_read",
    "mark_all_read",
    "prune",
    "KIND_PACK_READY",
    "KIND_RENDER_COMPLETE",
    "KIND_ERROR",
    "KIND_INFO",
    "LEVEL_INFO",
    "LEVEL_SUCCESS",
    "LEVEL_WARNING",
    "LEVEL_ERROR",
]
