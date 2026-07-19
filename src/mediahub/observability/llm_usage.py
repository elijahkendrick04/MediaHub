"""LLM call usage log — SQLite store backing the operator usage dashboard.

Every call into ``media_ai.llm`` (Gemini, Anthropic) records one row.
The store powers the operator-facing ``/healthz/usage`` page, which
answers the three questions a single-instance operator actually has:

  1. How many LLM calls have I made today?
  2. Am I close to the Gemini free-tier daily ceiling?
  3. What does my Anthropic spend look like this month?

The store is observability-only:

* Recording is best-effort. A DB failure never blocks an LLM call.
* The retention sweep trims to ~27k rows when the table crosses 30k.
* Cost estimates are coarse — derived from published per-MTok rates,
  not from real billing data. The dashboard labels them as estimates.

Public API:

    record_call(...)                 — insert one call row
    usage_for_window(window_hours)   — aggregate counts + cost estimate
    daily_usage(days)                — per-day breakdown
    last_error()                     — most recent failed call

Every public function is exception-safe — DB issues yield a safe default.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage paths — same convention as the rest of the SQLite stores.
# ---------------------------------------------------------------------------


def _db_path() -> Path:
    """Resolve ``DATA_DIR/data.db`` at CALL time (deep-review #101).

    Freezing this at import let a late ``DATA_DIR`` (set after this module was
    imported) split writes across two DBs; resolving per call keeps every store
    on one DB. Mirrors ``feature_quota._db_path`` / ``approval_telemetry._db_path``.
    """
    data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return data_dir / "data.db"


def __getattr__(name: str):
    # Back-compat: ``DATA_DIR`` / ``DB_PATH`` were module-level constants. Serve
    # them lazily so external readers always see the current DATA_DIR, never an
    # import-time freeze.
    if name == "DB_PATH":
        return _db_path()
    if name == "DATA_DIR":
        return _db_path().parent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Retention thresholds — overridable from tests via monkeypatch.
# ---------------------------------------------------------------------------

_PRUNE_THRESHOLD = 30_000
_PRUNE_TARGET = 27_000


# ---------------------------------------------------------------------------
# Provider cost rates — published list pricing in USD per million tokens.
# Coarse on purpose: the goal is "rough monthly cost estimate", not a
# billing audit. Rates are reviewable in one place and labelled clearly
# on the dashboard so operators don't mistake them for real bills.
# ---------------------------------------------------------------------------

# Anthropic Claude — public list, May 2026.
# (sonnet-4-6 + opus-4-7 + haiku-4-5)
_ANTHROPIC_RATES_USD_PER_MTOK = {
    "input": 3.00,  # Sonnet input — conservative midpoint
    "output": 15.00,  # Sonnet output — conservative midpoint
}

# Google Gemini — free tier covers MediaHub small-club usage entirely.
# These rates apply only if the operator has exceeded the free tier
# and moved to paid billing (rare for the target audience).
_GEMINI_RATES_USD_PER_MTOK = {
    "input": 0.075,
    "output": 0.30,
}

# Gemini free-tier daily request ceiling — used to render a headroom bar.
GEMINI_FREE_TIER_DAILY_REQ = 1_500


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    provider      TEXT    NOT NULL,
    model         TEXT,
    ok            INTEGER NOT NULL,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    duration_ms   INTEGER,
    error_kind    TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts
    ON llm_calls(ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_provider_ts
    ON llm_calls(provider, ts DESC);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


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
        log.warning("llm_usage: schema bootstrap failed: %s", exc)
    except OSError as exc:
        log.warning("llm_usage: schema bootstrap OS error: %s", exc)


# No import-time schema bootstrap (deep-review #101): building the schema at
# import created it in the default-DATA_DIR DB, which a late DATA_DIR then
# diverges from. Each write calls _ensure_schema() first (targeting the lazily
# resolved DB); every read degrades gracefully on a missing table.


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_call(
    *,
    provider: str,
    ok: bool,
    model: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    duration_ms: Optional[float] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
    ts: Optional[str] = None,
) -> int:
    """Insert one LLM call row. Returns the new id (0 on any failure).

    Parameters
    ----------
    provider : str
        ``gemini``, ``anthropic``, or any free-form tag. Normalised to
        lowercase. Empty string returns 0 (no row written) so a caller
        that lost track of its provider doesn't pollute the log.
    ok : bool
        True on a successful call, False on any failure (network,
        rate limit, parse error, etc).
    model : str, optional
        Specific model identifier if known.
    tokens_in / tokens_out : int, optional
        Token counts. If the provider returns them, pass them. If
        unknown, leave None — the cost estimator falls back to a
        heuristic based on call count.
    duration_ms : float, optional
        Wall-clock duration of the call.
    error_kind / error_message : str, optional
        Truncated to 50 / 500 chars respectively.

    Never raises.
    """
    p = (provider or "").strip().lower()
    if not p:
        return 0
    when = ts or datetime.now(timezone.utc).isoformat()
    m = None if model is None else str(model)[:80]
    ti = None if tokens_in is None else max(0, int(tokens_in))
    to = None if tokens_out is None else max(0, int(tokens_out))
    dms = None if duration_ms is None else max(0, int(duration_ms))
    ek = None if error_kind is None else str(error_kind)[:50]
    em = None if error_message is None else str(error_message)[:500]

    sql = (
        "INSERT INTO llm_calls "
        "(ts, provider, model, ok, tokens_in, tokens_out, duration_ms, "
        " error_kind, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        _ensure_schema()
        conn = _connect()
        try:
            cur = conn.execute(sql, (when, p, m, 1 if ok else 0, ti, to, dms, ek, em))
            new_id = int(cur.lastrowid or 0)
            conn.commit()
            _maybe_prune(conn)
            return new_id
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("llm_usage: record_call failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("llm_usage: record_call OS error: %s", exc)
        return 0


def _gemini_calls_last_24h() -> int:
    """Gemini call count over a FIXED trailing 24h — the free-tier daily reset.

    Kept separate from the summary's ``window_hours`` so a 7- or 30-day dashboard
    window can't subtract a week/month of calls from the 1,500/day ceiling and
    understate (often to zero) the real headroom."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM llm_calls WHERE provider = 'gemini' AND ts >= ?",
                (cutoff,),
            ).fetchone()
            return int(row["c"] or 0) if row else 0
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        log.warning("llm_usage: 24h gemini count failed: %s", exc)
        return 0


def usage_for_window(window_hours: int = 24) -> dict:
    """Aggregate stats for the trailing ``window_hours`` window.

    Returns a dict shaped for direct rendering on the usage dashboard:

      * ``window_hours``
      * ``window_start``        — ISO timestamp
      * ``total_calls``
      * ``ok_count``
      * ``failed_count``
      * ``by_provider``         — list of dicts (one per provider):
            {provider, calls, ok, failed, tokens_in, tokens_out,
             est_cost_usd}
      * ``est_cost_usd_total``  — sum of est_cost_usd across providers
      * ``gemini_free_tier_headroom`` — int, requests remaining today
        against the published 1,500/day free-tier ceiling. None when
        no Gemini calls have happened today.
    """
    try:
        window_hours = max(1, int(window_hours))
    except (TypeError, ValueError):
        window_hours = 24
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    default = {
        "window_hours": window_hours,
        "window_start": window_start.isoformat(),
        "total_calls": 0,
        "ok_count": 0,
        "failed_count": 0,
        "by_provider": [],
        "est_cost_usd_total": 0.0,
        "gemini_free_tier_headroom": None,
    }

    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT provider, ok, "
                "       COALESCE(tokens_in, 0)  AS tokens_in, "
                "       COALESCE(tokens_out, 0) AS tokens_out "
                "FROM llm_calls WHERE ts >= ?",
                (window_start.isoformat(),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("llm_usage: usage query failed: %s", exc)
        return default
    except OSError as exc:
        log.warning("llm_usage: usage OS error: %s", exc)
        return default

    if not rows:
        return default

    per_provider: dict[str, dict] = {}
    for r in rows:
        p = r["provider"] or "unknown"
        bucket = per_provider.setdefault(
            p,
            {
                "provider": p,
                "calls": 0,
                "ok": 0,
                "failed": 0,
                "tokens_in": 0,
                "tokens_out": 0,
            },
        )
        bucket["calls"] += 1
        if r["ok"]:
            bucket["ok"] += 1
        else:
            bucket["failed"] += 1
        bucket["tokens_in"] += int(r["tokens_in"] or 0)
        bucket["tokens_out"] += int(r["tokens_out"] or 0)

    by_provider = []
    est_cost_total = 0.0
    for bucket in per_provider.values():
        cost = _estimate_cost_usd(
            bucket["provider"],
            bucket["calls"],
            bucket["tokens_in"],
            bucket["tokens_out"],
        )
        bucket["est_cost_usd"] = round(cost, 4)
        est_cost_total += cost
        by_provider.append(bucket)
    by_provider.sort(key=lambda b: b["calls"], reverse=True)

    total = sum(b["calls"] for b in by_provider)
    ok = sum(b["ok"] for b in by_provider)
    failed = sum(b["failed"] for b in by_provider)

    # Gemini free-tier headroom is measured over a FIXED trailing 24h (the daily
    # reset) — NOT this summary's window_hours, which for a 7/30-day view would
    # subtract far more than a day's calls and understate the headroom.
    gemini_calls_24h = _gemini_calls_last_24h()
    headroom = None
    if gemini_calls_24h > 0:
        headroom = max(0, GEMINI_FREE_TIER_DAILY_REQ - gemini_calls_24h)

    return {
        "window_hours": window_hours,
        "window_start": window_start.isoformat(),
        "total_calls": total,
        "ok_count": ok,
        "failed_count": failed,
        "by_provider": by_provider,
        "est_cost_usd_total": round(est_cost_total, 4),
        "gemini_free_tier_headroom": headroom,
    }


def daily_usage(days: int = 30) -> list[dict]:
    """Per-UTC-day breakdown for the trailing ``days`` days, oldest first.

    Returns a list of dicts: ``{date, calls, ok, failed, est_cost_usd}``.
    Each provider's calls are folded into the same row; if breakdown by
    provider is needed, call ``usage_for_window`` with a short window.

    Used by the dashboard's 30-day sparkline / table.
    """
    try:
        days = max(1, int(days))
    except (TypeError, ValueError):
        days = 30
    window_start = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT substr(ts, 1, 10) AS day, provider, ok, "
                "       COALESCE(tokens_in, 0)  AS tokens_in, "
                "       COALESCE(tokens_out, 0) AS tokens_out "
                "FROM llm_calls WHERE ts >= ? "
                "ORDER BY ts ASC",
                (window_start.isoformat(),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("llm_usage: daily query failed: %s", exc)
        return []
    except OSError as exc:
        log.warning("llm_usage: daily OS error: %s", exc)
        return []

    by_day: dict[str, dict] = {}
    for r in rows:
        day = r["day"]
        bucket = by_day.setdefault(
            day,
            {
                "date": day,
                "calls": 0,
                "ok": 0,
                "failed": 0,
                "_per_provider": {},
            },
        )
        bucket["calls"] += 1
        if r["ok"]:
            bucket["ok"] += 1
        else:
            bucket["failed"] += 1
        pp = bucket["_per_provider"].setdefault(
            r["provider"] or "unknown",
            {"calls": 0, "tokens_in": 0, "tokens_out": 0},
        )
        pp["calls"] += 1
        pp["tokens_in"] += int(r["tokens_in"] or 0)
        pp["tokens_out"] += int(r["tokens_out"] or 0)

    out: list[dict] = []
    for day, bucket in sorted(by_day.items()):
        cost = 0.0
        for provider, pp in bucket["_per_provider"].items():
            cost += _estimate_cost_usd(provider, pp["calls"], pp["tokens_in"], pp["tokens_out"])
        out.append(
            {
                "date": day,
                "calls": bucket["calls"],
                "ok": bucket["ok"],
                "failed": bucket["failed"],
                "est_cost_usd": round(cost, 4),
            }
        )
    return out


def last_error() -> Optional[dict]:
    """Return the most recent failed LLM call, or None.

    Used by the dashboard so the operator can see the actual error
    message of the most recent provider failure without trawling logs.
    """
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, ts, provider, model, error_kind, error_message "
                "FROM llm_calls WHERE ok = 0 "
                "ORDER BY ts DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("llm_usage: last_error failed: %s", exc)
        return None
    except OSError as exc:
        log.warning("llm_usage: last_error OS error: %s", exc)
        return None
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "ts": row["ts"],
        "provider": row["provider"],
        "model": row["model"],
        "error_kind": row["error_kind"],
        "error_message": row["error_message"],
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _estimate_cost_usd(provider: str, calls: int, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for a provider given call/token counts.

    Uses published list pricing for Anthropic. Returns 0 for Gemini
    inside the free tier (default assumption for MediaHub deployments).
    Falls back to a per-call heuristic when token counts are missing —
    crude, but a missing-token estimate is still more useful than a
    zero on the dashboard.
    """
    p = (provider or "").lower()
    if p == "gemini":
        return 0.0
    if p == "anthropic":
        rates = _ANTHROPIC_RATES_USD_PER_MTOK
        if tokens_in or tokens_out:
            return (tokens_in / 1_000_000.0) * rates["input"] + (tokens_out / 1_000_000.0) * rates[
                "output"
            ]
        # Heuristic: assume 1.5k tokens in + 0.5k tokens out per call.
        return calls * (
            (1500 / 1_000_000.0) * rates["input"] + (500 / 1_000_000.0) * rates["output"]
        )
    return 0.0


def _maybe_prune(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.execute("SELECT COUNT(*) FROM llm_calls")
        n = int(cur.fetchone()[0])
        if n <= _PRUNE_THRESHOLD:
            return
        to_delete = n - _PRUNE_TARGET
        if to_delete <= 0:
            return
        conn.execute(
            "DELETE FROM llm_calls WHERE id IN ("
            "  SELECT id FROM llm_calls ORDER BY ts ASC, id ASC LIMIT ?"
            ")",
            (to_delete,),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("llm_usage: retention sweep failed: %s", exc)


__all__ = [
    # DATA_DIR / DB_PATH remain accessible (served lazily via __getattr__) but
    # are no longer star-exported constants — they resolve per access now (#101).
    "GEMINI_FREE_TIER_DAILY_REQ",
    "record_call",
    "usage_for_window",
    "daily_usage",
    "last_error",
    "_ensure_schema",
]
