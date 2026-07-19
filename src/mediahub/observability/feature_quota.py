"""Per-org / per-feature AI usage ledger — the metering spine of AI governance (1.23).

Every metered AI *feature invocation* (a caption generation, a brand
interpretation, a palette resolve, a media-description tag …) records one row
here, tagged with the org that ran it and the feature it exercised. The
governance policy layer (:mod:`mediahub.governance.quota`) reads these counts to
answer two questions a club and an operator both care about:

  1. How much of feature X has this org used this month?
  2. Is the org over a limit the operator has set for that feature?

This module is the raw store; the *policy* (limits, plan tiers, enforce-or-not)
lives in :mod:`mediahub.governance.quota`. Splitting them keeps the counting
deterministic and dumb, and the decision-making in one reviewable place.

It mirrors :mod:`mediahub.observability.imagine_usage` (which meters generative
imagery the same way) and the rest of the observability stores:

* Recording is best-effort — a DB failure never blocks an AI call, and a failed
  call is recorded but does not consume quota (``ok_only=True`` on counts).
* Stored in the same ``DATA_DIR/data.db`` SQLite file, WAL mode.
* Retention sweep trims to ~27k rows past 30k.
* ``db_path`` is injectable so tests run against a throwaway database.

Generative imagery keeps its own dedicated ``imagine_uses`` ledger (already
shipped and tested); the governance dashboard reads both and presents one
unified per-org picture.

Public API:

    record_use(...)                      — insert one feature-use row
    count_for_org(org_id, ...)           — count rows in a trailing window
    usage_for_org(org_id, ...)           — per-feature breakdown for one org
    usage_all_orgs(...)                  — per-org totals (operator dashboard)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_PRUNE_THRESHOLD = 30_000
_PRUNE_TARGET = 27_000

# A trailing 30-day window expressed in hours — the default "monthly" quota
# window, matching imagine_usage. Calendar months vary; 30 days is a stable,
# explainable approximation that resets on a rolling basis.
MONTHLY_WINDOW_HOURS = 24 * 30


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_uses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    org_id        TEXT    NOT NULL,
    feature       TEXT    NOT NULL,
    ok            INTEGER NOT NULL,
    provider      TEXT,
    model         TEXT,
    detail        TEXT,
    error_kind    TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_feature_uses_org_feat_ts
    ON feature_uses(org_id, feature, ts DESC);
CREATE INDEX IF NOT EXISTS idx_feature_uses_org_ts
    ON feature_uses(org_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_feature_uses_ts
    ON feature_uses(ts DESC);
"""


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
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def ensure_schema(db_path: Optional[Path] = None) -> None:
    try:
        conn = _connect(db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("feature_quota: schema bootstrap failed: %s", exc)
    except OSError as exc:
        log.warning("feature_quota: schema bootstrap OS error: %s", exc)


# Bootstrap the default-DATA_DIR schema at import time so the very first
# record_use never races a missing table. Tests pass an explicit db_path.
ensure_schema()


def _maybe_prune(conn: sqlite3.Connection) -> None:
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM feature_uses").fetchone()
        if count and count > _PRUNE_THRESHOLD:
            cutoff_id = conn.execute(
                "SELECT id FROM feature_uses ORDER BY id DESC LIMIT 1 OFFSET ?",
                (_PRUNE_TARGET,),
            ).fetchone()
            if cutoff_id:
                conn.execute("DELETE FROM feature_uses WHERE id <= ?", (cutoff_id[0],))
                conn.commit()
    except sqlite3.Error as exc:  # pragma: no cover - prune is best-effort
        log.debug("feature_quota: prune skipped: %s", exc)


def record_use(
    *,
    org_id: str,
    feature: str,
    ok: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    detail: Optional[str] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
    ts: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert one feature-use row. Returns the new id (0 on any failure).

    ``org_id`` and ``feature`` are both required — an unattributed call returns 0
    (no row) so a caller that lost track of its tenant or its feature cannot
    quietly consume a shared quota. Never raises.
    """
    org = (org_id or "").strip()
    feat = (feature or "").strip().lower()
    if not org or not feat:
        return 0
    when = ts or datetime.now(timezone.utc).isoformat()
    prov = None if provider is None else str(provider)[:40]
    mdl = None if model is None else str(model)[:80]
    det = None if detail is None else str(detail)[:200]
    ek = None if error_kind is None else str(error_kind)[:50]
    em = None if error_message is None else str(error_message)[:500]
    sql = (
        "INSERT INTO feature_uses "
        "(ts, org_id, feature, ok, provider, model, detail, error_kind, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        ensure_schema(db_path)
        conn = _connect(db_path)
        try:
            cur = conn.execute(sql, (when, org, feat, 1 if ok else 0, prov, mdl, det, ek, em))
            new_id = int(cur.lastrowid or 0)
            conn.commit()
            _maybe_prune(conn)
            return new_id
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("feature_quota: record_use failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("feature_quota: record_use OS error: %s", exc)
        return 0


def reserve_use(
    *,
    org_id: str,
    feature: str,
    limit: int,
    window_hours: int = MONTHLY_WINDOW_HOURS,
    ts: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[int]:
    """Atomically reserve one quota slot (deep-review #95).

    Inserts a usage row (ok=1) IFF the org is currently under ``limit`` for this
    feature in the trailing window, evaluated INSIDE a ``BEGIN IMMEDIATE`` write
    transaction so concurrent reservers serialise on the DB write lock rather than
    racing a read-then-insert. Returns the new row id (the reservation) if a slot
    was taken, or ``None`` if the org is already at the limit.

    Raises ``sqlite3.Error`` / ``OSError`` on a genuine DB failure so the caller
    can fail OPEN (a transient DB hiccup must never wrongly block a paying club).
    A negative ``limit`` (unmetered) reserves nothing and returns ``None``.
    """
    org = (org_id or "").strip()
    feat = (feature or "").strip().lower()
    if not org or not feat or limit < 0:
        return None
    when = ts or datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        # BEGIN IMMEDIATE takes the write lock up front; the conditional INSERT
        # then sees a committed, consistent count including any concurrent
        # reservation that has already committed.
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO feature_uses (ts, org_id, feature, ok) "
            "SELECT ?, ?, ?, 1 WHERE ("
            "  SELECT COUNT(*) FROM feature_uses "
            "  WHERE org_id=? AND feature=? AND ts>=? AND ok=1"
            ") < ?",
            (when, org, feat, org, feat, cutoff, int(limit)),
        )
        reserved = cur.rowcount == 1
        new_id = int(cur.lastrowid or 0) if reserved else None
        conn.commit()
        return new_id
    finally:
        conn.close()


def finalize_use(
    row_id: Optional[int],
    *,
    ok: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    detail: Optional[str] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Finalize a slot reserved by :func:`reserve_use` (deep-review #95).

    On success keeps ``ok=1`` and attaches the call metadata; on failure sets
    ``ok=0`` so the reservation no longer counts against quota (a failed billed
    call is not charged to the customer's quota — mirrors ``record_use``). The
    trailing-window prune still applies via the next write. Best-effort: never
    raises, so a finalize failure cannot fail the request.
    """
    if not row_id:
        return
    prov = None if provider is None else str(provider)[:40]
    mdl = None if model is None else str(model)[:80]
    det = None if detail is None else str(detail)[:200]
    ek = None if error_kind is None else str(error_kind)[:50]
    em = None if error_message is None else str(error_message)[:500]
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                "UPDATE feature_uses SET ok=?, provider=?, model=?, detail=?, "
                "error_kind=?, error_message=? WHERE id=?",
                (1 if ok else 0, prov, mdl, det, ek, em, int(row_id)),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("feature_quota: finalize_use failed: %s", exc)
    except OSError as exc:
        log.warning("feature_quota: finalize_use OS error: %s", exc)


def count_for_org(
    org_id: str,
    *,
    feature: Optional[str] = None,
    window_hours: int = MONTHLY_WINDOW_HOURS,
    ok_only: bool = True,
    db_path: Optional[Path] = None,
) -> int:
    """Count an org's feature-use rows in the trailing ``window_hours`` window.

    Pass ``feature`` to scope to one feature (the quota check does this); leave
    it None to count every metered feature. Only successful invocations count by
    default — a failed call is logged but never charged to the customer's quota.
    Returns 0 on any read error so the quota check fails *open*: a transient DB
    hiccup never wrongly blocks a paying club.
    """
    org = (org_id or "").strip()
    if not org:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    sql = "SELECT COUNT(*) FROM feature_uses WHERE org_id=? AND ts>=?"
    args: list = [org, cutoff]
    feat = (feature or "").strip().lower()
    if feat:
        sql += " AND feature=?"
        args.append(feat)
    if ok_only:
        sql += " AND ok=1"
    try:
        conn = _connect(db_path)
        try:
            (count,) = conn.execute(sql, args).fetchone()
            return int(count or 0)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("feature_quota: count_for_org failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("feature_quota: count_for_org OS error: %s", exc)
        return 0


def usage_for_org(
    org_id: str,
    *,
    window_hours: int = MONTHLY_WINDOW_HOURS,
    db_path: Optional[Path] = None,
) -> dict:
    """Per-feature breakdown for an org over the trailing window.

    Returns ``{"org_id", "window_hours", "total", "by_feature": {feature: count}}``
    — shaped for a usage panel. Counts successful invocations only.
    """
    org = (org_id or "").strip()
    out = {"org_id": org, "window_hours": window_hours, "total": 0, "by_feature": {}}
    if not org:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    try:
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                "SELECT feature, COUNT(*) AS c FROM feature_uses "
                "WHERE org_id=? AND ts>=? AND ok=1 GROUP BY feature",
                (org, cutoff),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        log.warning("feature_quota: usage_for_org failed: %s", exc)
        return out
    by_feature = {str(r["feature"]): int(r["c"]) for r in rows}
    out["by_feature"] = by_feature
    out["total"] = sum(by_feature.values())
    return out


def usage_all_orgs(
    *,
    window_hours: int = MONTHLY_WINDOW_HOURS,
    ok_only: bool = True,
    limit: int = 200,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Per-org totals over the trailing window, busiest first.

    Returns a list of ``{"org_id", "total", "by_feature": {feature: count}}``
    capped at ``limit`` orgs — the data behind the operator governance
    dashboard. Counts successful invocations only by default.
    """
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 200
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    sql = "SELECT org_id, feature, COUNT(*) AS c FROM feature_uses WHERE ts>=?"
    args: list = [cutoff]
    if ok_only:
        sql += " AND ok=1"
    sql += " GROUP BY org_id, feature"
    try:
        conn = _connect(db_path)
        try:
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        log.warning("feature_quota: usage_all_orgs failed: %s", exc)
        return []

    per_org: dict[str, dict] = {}
    for r in rows:
        org = str(r["org_id"])
        bucket = per_org.setdefault(org, {"org_id": org, "total": 0, "by_feature": {}})
        c = int(r["c"])
        bucket["by_feature"][str(r["feature"])] = c
        bucket["total"] += c
    ordered = sorted(per_org.values(), key=lambda b: b["total"], reverse=True)
    return ordered[:limit]


__all__ = [
    "record_use",
    "count_for_org",
    "usage_for_org",
    "usage_all_orgs",
    "ensure_schema",
    "MONTHLY_WINDOW_HOURS",
]
