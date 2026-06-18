"""Generative-imagery usage ledger — per-org quota accounting for P6.3.

Every generative-image operation (generate / edit / expand / remove / upscale /
similar / style_match) records one row here, tagged with the org that ran it.
The ledger backs the per-org quota the AI-governance work package (P6.22) calls
for: a cloud image call costs real money, so a club's monthly generation count
is metered and honest-erroring ("quota reached") rather than an open tab.

Mirrors :mod:`mediahub.observability.llm_usage` exactly:

* Recording is best-effort — a DB failure never blocks (or silently allows) an
  operation; the quota check fails *open* only when it genuinely cannot read,
  and that is logged.
* Stored in the same ``DATA_DIR/data.db`` SQLite file, WAL mode.
* Retention sweep trims to ~27k rows past 30k.

Deterministic subject-lift (cutout + saliency) is **not** metered here — it
spends no provider budget — only provider-backed operations are.

Public API:

    record_use(...)                  — insert one usage row
    count_for_org(org_id, ...)       — count rows in a trailing window
    usage_for_org(org_id, ...)       — per-operation breakdown
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
DB_PATH = DATA_DIR / "data.db"

_PRUNE_THRESHOLD = 30_000
_PRUNE_TARGET = 27_000

# A trailing 30-day window expressed in hours — the default "monthly" quota
# window. Calendar months vary; 30 days is a stable, explainable approximation.
MONTHLY_WINDOW_HOURS = 24 * 30


_SCHEMA = """
CREATE TABLE IF NOT EXISTS imagine_uses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    org_id        TEXT    NOT NULL,
    op            TEXT    NOT NULL,
    provider      TEXT,
    model         TEXT,
    ok            INTEGER NOT NULL,
    error_kind    TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_imagine_uses_org_ts
    ON imagine_uses(org_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_imagine_uses_ts
    ON imagine_uses(ts DESC);
"""


def _connect() -> sqlite3.Connection:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def _ensure_schema() -> None:
    try:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("imagine_usage: schema bootstrap failed: %s", exc)
    except OSError as exc:
        log.warning("imagine_usage: schema bootstrap OS error: %s", exc)


_ensure_schema()


def _maybe_prune(conn: sqlite3.Connection) -> None:
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM imagine_uses").fetchone()
        if count and count > _PRUNE_THRESHOLD:
            cutoff_id = conn.execute(
                "SELECT id FROM imagine_uses ORDER BY id DESC LIMIT 1 OFFSET ?",
                (_PRUNE_TARGET,),
            ).fetchone()
            if cutoff_id:
                conn.execute("DELETE FROM imagine_uses WHERE id <= ?", (cutoff_id[0],))
                conn.commit()
    except sqlite3.Error as exc:  # pragma: no cover - prune is best-effort
        log.debug("imagine_usage: prune skipped: %s", exc)


def record_use(
    *,
    org_id: str,
    op: str,
    ok: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
    ts: Optional[str] = None,
) -> int:
    """Insert one generative-imagery usage row. Returns the new id (0 on failure).

    ``org_id`` is required — an unattributed call returns 0 (no row) so a caller
    that lost track of its tenant cannot quietly consume a shared quota. Never
    raises.
    """
    org = (org_id or "").strip()
    operation = (op or "").strip().lower()
    if not org or not operation:
        return 0
    when = ts or datetime.now(timezone.utc).isoformat()
    prov = None if provider is None else str(provider)[:40]
    mdl = None if model is None else str(model)[:80]
    ek = None if error_kind is None else str(error_kind)[:50]
    em = None if error_message is None else str(error_message)[:500]
    sql = (
        "INSERT INTO imagine_uses "
        "(ts, org_id, op, provider, model, ok, error_kind, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        _ensure_schema()
        conn = _connect()
        try:
            cur = conn.execute(sql, (when, org, operation, prov, mdl, 1 if ok else 0, ek, em))
            new_id = int(cur.lastrowid or 0)
            conn.commit()
            _maybe_prune(conn)
            return new_id
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("imagine_usage: record_use failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("imagine_usage: record_use OS error: %s", exc)
        return 0


def count_for_org(
    org_id: str,
    *,
    window_hours: int = MONTHLY_WINDOW_HOURS,
    ok_only: bool = True,
) -> int:
    """Count an org's usage rows in the trailing ``window_hours`` window.

    Only successful operations count against quota by default (a failed billed
    call still costs, but charging the customer's quota for our provider's error
    would be unfair). Returns 0 on any read error — the quota check is designed
    to fail *open* so a transient DB hiccup never wrongly blocks a paying club.
    """
    org = (org_id or "").strip()
    if not org:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    sql = "SELECT COUNT(*) FROM imagine_uses WHERE org_id=? AND ts>=?"
    args: list = [org, cutoff]
    if ok_only:
        sql += " AND ok=1"
    try:
        conn = _connect()
        try:
            (count,) = conn.execute(sql, args).fetchone()
            return int(count or 0)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("imagine_usage: count_for_org failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("imagine_usage: count_for_org OS error: %s", exc)
        return 0


def usage_for_org(
    org_id: str,
    *,
    window_hours: int = MONTHLY_WINDOW_HOURS,
) -> dict:
    """Per-operation breakdown for an org over the trailing window.

    Returns ``{"org_id", "window_hours", "total", "by_op": {op: count}}`` —
    shaped for a usage panel. Counts successful operations only.
    """
    org = (org_id or "").strip()
    out = {"org_id": org, "window_hours": window_hours, "total": 0, "by_op": {}}
    if not org:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT op, COUNT(*) AS c FROM imagine_uses "
                "WHERE org_id=? AND ts>=? AND ok=1 GROUP BY op",
                (org, cutoff),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        log.warning("imagine_usage: usage_for_org failed: %s", exc)
        return out
    by_op = {str(r["op"]): int(r["c"]) for r in rows}
    out["by_op"] = by_op
    out["total"] = sum(by_op.values())
    return out


__all__ = [
    "record_use",
    "count_for_org",
    "usage_for_org",
    "MONTHLY_WINDOW_HOURS",
    "DB_PATH",
]
