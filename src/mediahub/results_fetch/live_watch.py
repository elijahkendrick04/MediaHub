"""mediahub/results_fetch/live_watch.py — W.7 live meet mode, engine core.

A **watch** is a stored results URL polled on a polite interval for the
duration of one meet, feeding incremental results into a single run. This
module is the deterministic engine seam only: SQLite persistence
(``DATA_DIR/data.db``), polling/diffing semantics, and the scheduler task
type. The web layer wires the run pipeline in as the injectable ``runner``
(cards are queue-only by construction there) and never lives here.

Tables (in the shared ``data.db``):

    live_watches      one row per watch, org-scoped by ``profile_id``
    live_watch_swims  sidecar: every per-swim dedupe key ever carded for a
                      watch (cumulative — rows are only ever added, so a
                      swim that vanishes and reappears never cards twice)

ToS posture (ADR-0012, unchanged): Meet Mobile / Active Network app
endpoints and swimrankings.net are **prohibited** watch targets and are
rejected at creation. Host-club "Real-Time Results" pages and
results.swimming.org are the intended targets.

Poll semantics (all-or-nothing, deterministic) — see :func:`poll_watch`:

    expire check → fetch → full-document parse (never partial rows) →
    digest short-circuit → exact key-set diff → runner → commit → notify

Injection contracts
-------------------

``fetcher(url) -> bytes | None``
    Returns the page bytes, or ``None`` / raises on failure. Failure is
    transient: the watch stays active and retries on the next interval.
    The default is the tier-A polite fetch (:class:`StaticBackend` —
    SSRF-validated, content-type allowlisted, byte-capped, MediaHub UA).

``runner(watch, data, new_swim_keys) -> None``
    Called exactly when the poll found genuinely new swims, with the raw
    fetched bytes and the sorted list of new dedupe keys. The web layer
    wires this to re-run the pipeline into ``watch.run_id``. **Contract:**
    the stored key set is committed only after the runner returns — a
    runner exception leaves the key set untouched, so the next poll
    retries the *same* diff. Exactly-once carding therefore requires the
    runner to be idempotent per swim key (re-processing a key it already
    carded must be a no-op), which the pipeline's per-swim dedupe gives
    for free.

``notifier(watch, new_swim_keys) -> None``
    Called after a successful runner commit (with the new keys) and once
    at expiry (with ``[]``). Always wrapped in try/except — notification
    failure never fails a poll. The default builds a
    :class:`mediahub.notify.channels.Notification` ("N new results in
    <label>", click-through to ``watch.review_url`` when set) and sends it
    via every configured channel.

Every public function takes an optional ``db_path`` so tests run against a
throwaway database (same convention as ``athletes/registry.py``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from mediahub.athletes.registry import normalise_name

log = logging.getLogger(__name__)

__all__ = [
    "Watch",
    "PollResult",
    "TASK_TYPE",
    "MIN_INTERVAL_MINUTES",
    "DEFAULT_INTERVAL_MINUTES",
    "MAX_INTERVAL_MINUTES",
    "DEFAULT_EXPIRE_HOURS",
    "MAX_EXPIRE_HOURS",
    "create_watch",
    "list_watches",
    "get_watch",
    "stop_watch",
    "due_watches",
    "poll_watch",
    "swim_keys_for_meet",
    "register_live_watch_task",
    "ensure_schema",
]

TASK_TYPE = "live_meet_poll"

MIN_INTERVAL_MINUTES = 2  # politeness floor — never hammer a host club's site
DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_EXPIRE_HOURS = 12  # a long gala day; watches ALWAYS auto-expire
MAX_EXPIRE_HOURS = 48
# Ceiling on the poll interval. A watch lives at most MAX_EXPIRE_HOURS, so an
# interval beyond that would never poll; clamping here also stops an absurd or
# malformed value overflowing the SQLite INTEGER column on insert.
MAX_INTERVAL_MINUTES = MAX_EXPIRE_HOURS * 60

# ADR-0012 posture: Meet Mobile (an Active Network app) and rankings
# scraping are prohibited. Matched against the URL host, suffix-wise.
_PROHIBITED_HOST_SUFFIXES: tuple[str, ...] = (
    "swimrankings.net",
    "active.com",  # Meet Mobile's app/API endpoints live under active.com
    "meetmobile.com",
)
_PROHIBITED_MESSAGE = (
    "This source cannot be watched: Meet Mobile / Active app endpoints and "
    "swimrankings.net are prohibited (ADR-0012 — their terms forbid scraping). "
    "Watch the host club's own live-results page or results.swimming.org instead."
)

Fetcher = Callable[[str], Optional[bytes]]
Runner = Callable[["Watch", bytes, list[str]], None]
Notifier = Callable[["Watch", list[str]], None]


# ---------------------------------------------------------------------------
# Persistence plumbing (registry.py conventions)
# ---------------------------------------------------------------------------


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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_watches (
    id               TEXT PRIMARY KEY,
    profile_id       TEXT NOT NULL,
    url              TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    run_id           TEXT NOT NULL DEFAULT '',
    label            TEXT NOT NULL DEFAULT '',
    review_url       TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'active',
    expires_at       TEXT NOT NULL,
    last_polled_at   TEXT,
    last_swim_count  INTEGER NOT NULL DEFAULT 0,
    last_digest      TEXT NOT NULL DEFAULT '',
    polls            INTEGER NOT NULL DEFAULT 0,
    new_swims_total  INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_watches_profile
    ON live_watches(profile_id, status);
CREATE INDEX IF NOT EXISTS idx_live_watches_status
    ON live_watches(status, expires_at);

CREATE TABLE IF NOT EXISTS live_watch_swims (
    watch_id TEXT NOT NULL,
    swim_key TEXT NOT NULL,
    PRIMARY KEY (watch_id, swim_key)
);
"""


def ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Watch:
    """One live-results watch. ``status`` ∈ active | expired | stopped | error."""

    id: str
    profile_id: str
    url: str
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    run_id: str = ""
    label: str = ""
    review_url: str = ""
    status: str = "active"
    expires_at: str = ""
    last_polled_at: Optional[str] = None
    last_swim_count: int = 0
    last_digest: str = ""
    polls: int = 0
    new_swims_total: int = 0
    last_error: str = ""
    created_at: str = ""


@dataclass
class PollResult:
    """The outcome of one :func:`poll_watch` call.

    ``changed`` is True only when a genuine diff was found AND committed
    (runner succeeded). A runner failure reports ``changed=False`` with the
    error set; the same diff is retried next poll.
    """

    watch_id: str
    status: str
    changed: bool = False
    new_swim_keys: list[str] = field(default_factory=list)
    swim_count: int = 0
    error: str = ""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        profile_id=row["profile_id"],
        url=row["url"],
        interval_minutes=int(row["interval_minutes"]),
        run_id=row["run_id"],
        label=row["label"],
        review_url=row["review_url"],
        status=row["status"],
        expires_at=row["expires_at"],
        last_polled_at=row["last_polled_at"],
        last_swim_count=int(row["last_swim_count"]),
        last_digest=row["last_digest"],
        polls=int(row["polls"]),
        new_swims_total=int(row["new_swims_total"]),
        last_error=row["last_error"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# URL validation — scheme + ADR-0012 prohibited sources
# ---------------------------------------------------------------------------


def _validate_url(url: str) -> str:
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("A live watch needs a full http:// or https:// results URL.")
    host = parsed.hostname.lower()
    if "meetmobile" in host:
        raise ValueError(_PROHIBITED_MESSAGE)
    for suffix in _PROHIBITED_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            raise ValueError(_PROHIBITED_MESSAGE)
    return u


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_watch(
    profile_id: str,
    url: str,
    *,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    expires_at: Optional[str | datetime] = None,
    label: str = "",
    run_id: str = "",
    review_url: str = "",
    db_path: Optional[Path] = None,
) -> Watch:
    """Create an active watch. Validates the URL (http/https only; ADR-0012
    prohibited hosts rejected), clamps the interval to the politeness floor,
    and enforces auto-expiry: default now+12h, hard cap now+48h."""
    if not (profile_id or "").strip():
        raise ValueError("A live watch must belong to a workspace (profile_id).")
    url = _validate_url(url)
    interval = min(
        MAX_INTERVAL_MINUTES,
        max(MIN_INTERVAL_MINUTES, int(interval_minutes or DEFAULT_INTERVAL_MINUTES)),
    )

    now = _now_utc()
    if expires_at is None:
        expiry = now + timedelta(hours=DEFAULT_EXPIRE_HOURS)
    else:
        expiry = expires_at if isinstance(expires_at, datetime) else _parse_iso(str(expires_at))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expiry = expiry.astimezone(timezone.utc)
    if expiry <= now:
        raise ValueError("expires_at must be in the future — a watch always auto-expires.")
    cap = now + timedelta(hours=MAX_EXPIRE_HOURS)
    if expiry > cap:
        expiry = cap  # watches never outlive a meet weekend

    ensure_schema(db_path)
    watch = Watch(
        id=uuid.uuid4().hex[:12],
        profile_id=profile_id.strip(),
        url=url,
        interval_minutes=interval,
        run_id=(run_id or "").strip(),
        label=(label or "").strip(),
        review_url=(review_url or "").strip(),
        status="active",
        expires_at=_iso(expiry),
        created_at=_iso(now),
    )
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO live_watches (id, profile_id, url, interval_minutes, run_id,"
            " label, review_url, status, expires_at, last_polled_at, last_swim_count,"
            " last_digest, polls, new_swims_total, last_error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,NULL,0,'',0,0,'',?)",
            (
                watch.id,
                watch.profile_id,
                watch.url,
                watch.interval_minutes,
                watch.run_id,
                watch.label,
                watch.review_url,
                watch.status,
                watch.expires_at,
                watch.created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return watch


def list_watches(profile_id: str, db_path: Optional[Path] = None) -> list[Watch]:
    """All of one workspace's watches, newest first (org-scoped)."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM live_watches WHERE profile_id = ? ORDER BY created_at DESC, id",
            (profile_id,),
        ).fetchall()
        return [_row_to_watch(r) for r in rows]
    finally:
        conn.close()


def get_watch(
    watch_id: str,
    profile_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[Watch]:
    """Fetch one watch by id. When ``profile_id`` is given, the watch must
    belong to that workspace (org isolation) — otherwise ``None``."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM live_watches WHERE id = ?", (watch_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    watch = _row_to_watch(row)
    if profile_id is not None and watch.profile_id != profile_id:
        return None
    return watch


def stop_watch(profile_id: str, watch_id: str, db_path: Optional[Path] = None) -> bool:
    """Manually end a watch (org-scoped). Idempotent; True iff a row changed."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE live_watches SET status = 'stopped'"
            " WHERE id = ? AND profile_id = ? AND status = 'active'",
            (watch_id, profile_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def due_watches(now: Optional[datetime] = None, db_path: Optional[Path] = None) -> list[Watch]:
    """Active watches whose poll interval has elapsed (or never polled).

    A watch past its ``expires_at`` but still marked active IS returned —
    its next :func:`poll_watch` is the one that flips it to 'expired' and
    sends the final "watch ended" notification, so the watch stops itself.
    """
    now = now or _now_utc()
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM live_watches WHERE status = 'active' ORDER BY created_at, id"
        ).fetchall()
    finally:
        conn.close()
    due: list[Watch] = []
    for row in rows:
        watch = _row_to_watch(row)
        if watch.last_polled_at:
            try:
                last = _parse_iso(watch.last_polled_at)
            except ValueError:
                last = None
            if last is not None and now < last + timedelta(minutes=watch.interval_minutes):
                continue
        due.append(watch)
    return due


# ---------------------------------------------------------------------------
# Dedupe keys — deterministic, derived from the full-document parse
# ---------------------------------------------------------------------------


def swim_keys_for_meet(meet) -> set[str]:
    """Per-swim dedupe keys from an ``InterpretedMeet``.

    ``normalised name|gender,distance,stroke,course|time`` for every swim
    that has a time (DQ/NS/no-time rows carry nothing to card). The event
    course falls back to the meet-level course default. Deterministic by
    construction — same parse, same keys.
    """
    keys: set[str] = set()
    for event in meet.events or []:
        course = event.course or meet.course_default or ""
        identity = f"{event.gender or ''},{event.distance_m or ''},{event.stroke or ''},{course}"
        for swim in event.swims or []:
            if not swim.time:
                continue
            name = normalise_name(swim.swimmer_name or "")
            if not name:
                continue
            keys.add(f"{name}|{identity}|{swim.time}")
    return keys


def _digest(keys: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()


def _stored_keys(watch_id: str, db_path: Optional[Path]) -> set[str]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT swim_key FROM live_watch_swims WHERE watch_id = ?", (watch_id,)
        ).fetchall()
        return {r["swim_key"] for r in rows}
    finally:
        conn.close()


def _update_watch(watch_id: str, db_path: Optional[Path], **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = _connect(db_path)
    try:
        conn.execute(
            f"UPDATE live_watches SET {sets} WHERE id = ?",
            (*fields.values(), watch_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Default fetcher / notifier
# ---------------------------------------------------------------------------


def _default_fetcher(url: str) -> Optional[bytes]:
    """Tier-A polite fetch: SSRF-validated, allowlisted, byte-capped, 15s
    timeout, MediaHub User-Agent (the same hardened door the results-from-a-
    link crawl uses). Returns ``None`` on any failure — transient by design."""
    from .fetch import FetchLimits, StaticBackend  # noqa: PLC0415

    page = StaticBackend(limits=FetchLimits.from_env()).fetch(url)
    return page.content if page is not None else None


def _default_notifier(watch: Watch, new_swim_keys: list[str]) -> None:
    """Push "N new results" (or "watch ended") via every configured channel.

    Unconfigured channels are inert, so this costs nothing by default. The
    click-through lands the volunteer straight in review when the web layer
    set ``review_url`` on the watch."""
    from mediahub.notify.channels import Notification, all_channels  # noqa: PLC0415

    where = watch.label or watch.url
    if new_swim_keys:
        n = len(new_swim_keys)
        note = Notification(
            title=f"{n} new result{'s' if n != 1 else ''} in {where}",
            message="New swims detected — cards are queued for your approval.",
            tags=("stopwatch",),
            click_url=watch.review_url or None,
        )
    else:
        note = Notification(
            title=f"Live watch ended: {where}",
            message=f"The watch expired after {watch.polls} polls"
            f" and {watch.new_swims_total} new swims.",
            tags=("checkered_flag",),
            click_url=watch.review_url or None,
        )
    for channel in all_channels():
        if channel.configured():
            channel.send(note)


def _safe_notify(notifier: Notifier, watch: Watch, keys: list[str]) -> None:
    try:
        notifier(watch, keys)
    except Exception as e:  # notification failure never fails a poll
        log.warning("live watch %s notify failed: %s", watch.id, e)


# ---------------------------------------------------------------------------
# The heart — one poll
# ---------------------------------------------------------------------------


def poll_watch(
    watch_id: str,
    *,
    fetcher: Optional[Fetcher] = None,
    runner: Optional[Runner] = None,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
    db_path: Optional[Path] = None,
) -> PollResult:
    """Poll one watch once. All-or-nothing and deterministic:

    1. Past ``expires_at`` → status 'expired', final "watch ended" notify.
    2. Fetch (injectable). Failure is transient: error recorded, watch
       stays active, retried next interval.
    3. Full-document parse via ``interpret_document`` — never partial rows.
       Parse failure / zero confidence → "parse failed; will retry".
    4. Digest short-circuit: same key-set hash as last poll → no work.
    5. Exact diff against the cumulative stored key set (sidecar table) →
       ``runner(watch, data, new_swim_keys)``. A runner exception leaves
       the key set AND digest untouched, so the next poll retries the same
       diff — exactly-once carding rests on the runner being idempotent
       per swim key (see module docstring).
    6. On runner success: commit keys + digest + counters, then notify
       (failure swallowed).
    """
    now = now or _now_utc()
    ensure_schema(db_path)
    watch = get_watch(watch_id, db_path=db_path)
    if watch is None:
        return PollResult(watch_id=watch_id, status="missing", error="watch not found")
    if watch.status != "active":
        return PollResult(watch_id=watch_id, status=watch.status)

    fetcher = fetcher or _default_fetcher
    notifier = notifier or _default_notifier
    now_iso = _iso(now)

    # 1 — auto-expiry. The watch stops itself; volunteers never have to.
    try:
        expired = now >= _parse_iso(watch.expires_at)
    except ValueError:
        expired = True  # an unreadable expiry must never mean "poll forever"
    if expired:
        _update_watch(watch.id, db_path, status="expired", last_polled_at=now_iso)
        watch.status = "expired"
        _safe_notify(notifier, watch, [])
        return PollResult(watch_id=watch.id, status="expired")

    # 2 — fetch (transient failure keeps the watch alive)
    try:
        data = fetcher(watch.url)
    except Exception as e:
        data = None
        # Log the raw reason for the operator; keep the persisted/displayed
        # last_error a short, stable phrase (no internal exception text).
        log.warning("live watch %s fetch error: %s", watch.id, e)
        fetch_err = "fetch failed: could not reach the page"
    else:
        fetch_err = "fetch failed: no content"
    if not data:
        _update_watch(
            watch.id,
            db_path,
            last_polled_at=now_iso,
            polls=watch.polls + 1,
            last_error=fetch_err,
        )
        return PollResult(watch_id=watch.id, status="active", error=fetch_err)

    # 3 — full-document parse; NEVER emit partial rows
    from mediahub.interpreter import interpret_document  # noqa: PLC0415

    try:
        meet = interpret_document(data)
    except Exception as e:
        meet = None
        parse_detail = str(e)
    else:
        parse_detail = ""
    if meet is None or meet.overall_confidence <= 0.0:
        if parse_detail:
            log.warning("live watch %s parse error: %s", watch.id, parse_detail)
        # Stable, internal-detail-free phrase for the operator-facing field.
        err = "parse failed; will retry"
        _update_watch(
            watch.id,
            db_path,
            last_polled_at=now_iso,
            polls=watch.polls + 1,
            last_error=err,
        )
        return PollResult(watch_id=watch.id, status="active", error=err)

    keys = swim_keys_for_meet(meet)
    digest = _digest(keys)

    # 4 — digest short-circuit: nothing new on the page
    if digest == watch.last_digest:
        _update_watch(
            watch.id,
            db_path,
            last_polled_at=now_iso,
            polls=watch.polls + 1,
            last_swim_count=len(keys),
            last_error="",
        )
        return PollResult(watch_id=watch.id, status="active", swim_count=len(keys))

    # 5 — exact diff against the cumulative ever-seen key set
    previous = _stored_keys(watch.id, db_path)
    new_keys = sorted(keys - previous)

    if new_keys and runner is not None:
        try:
            runner(watch, data, new_keys)
        except Exception as e:
            # Key set + digest deliberately NOT advanced: next poll retries
            # the exact same diff. (Exactly-once carding = idempotent runner.)
            # Log the raw reason; keep last_error a short, stable phrase.
            log.warning("live watch %s runner failed: %s", watch.id, e)
            err = "runner failed; will retry"
            _update_watch(
                watch.id,
                db_path,
                last_polled_at=now_iso,
                polls=watch.polls + 1,
                last_error=err,
            )
            return PollResult(
                watch_id=watch.id,
                status="active",
                new_swim_keys=new_keys,
                swim_count=len(keys),
                error=err,
            )

    # 6 — commit: cumulative key set (rows only ever added), digest, counters
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO live_watch_swims (watch_id, swim_key) VALUES (?,?)",
            [(watch.id, k) for k in new_keys],
        )
        conn.execute(
            "UPDATE live_watches SET last_polled_at = ?, polls = ?, last_digest = ?,"
            " last_swim_count = ?, new_swims_total = ?, last_error = '' WHERE id = ?",
            (
                now_iso,
                watch.polls + 1,
                digest,
                len(keys),
                watch.new_swims_total + len(new_keys),
                watch.id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if new_keys:
        watch.new_swims_total += len(new_keys)
        _safe_notify(notifier, watch, new_keys)

    return PollResult(
        watch_id=watch.id,
        status="active",
        changed=bool(new_keys),
        new_swim_keys=new_keys,
        swim_count=len(keys),
    )


# ---------------------------------------------------------------------------
# Scheduler task type
# ---------------------------------------------------------------------------


def _make_task_handler(
    runner: Optional[Runner],
    fetcher: Optional[Fetcher],
    notifier: Optional[Notifier],
):
    def _live_meet_poll_handler(params: dict) -> None:
        """Scheduler handler: poll every due watch once. One watch's failure
        never stops the rest; poll_watch itself never raises for transient
        trouble. ``params['db_path']`` is a test seam only."""
        db = params.get("db_path") or None
        for watch in due_watches(db_path=db):
            try:
                poll_watch(
                    watch.id,
                    fetcher=fetcher,
                    runner=runner,
                    notifier=notifier,
                    db_path=db,
                )
            except Exception as e:
                log.warning("live watch %s poll failed: %s", watch.id, e)

    return _live_meet_poll_handler


def register_live_watch_task(
    runner: Optional[Runner] = None,
    fetcher: Optional[Fetcher] = None,
    notifier: Optional[Notifier] = None,
) -> None:
    """Register the ``live_meet_poll`` scheduler task type (idempotent).

    The web layer calls this at startup with its pipeline ``runner`` (which
    feeds ``watch.run_id`` and queues cards for approval — by construction
    nothing here can publish). Same convention as the other scheduler tasks
    (season wrap, retention purge)."""
    try:
        from mediahub.scheduler import register_task_type  # noqa: PLC0415

        register_task_type(TASK_TYPE, _make_task_handler(runner, fetcher, notifier))
    except Exception as e:  # never block app startup on this
        log.warning("could not register %s task type: %s", TASK_TYPE, e)
