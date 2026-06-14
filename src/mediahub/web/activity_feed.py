"""Dashboard activity feed — a unified, server-rendered event stream (UI 1.16).

Inspired by GitHub's dashboard feed, this merges three records MediaHub
*already keeps* into one reverse-chronological stream of cards:

  * **runs**      — the ``runs`` SQLite table (every pipeline run)
  * **approvals** — per-card review decisions in the ``WorkflowStore`` sidecars
                    (approved / rejected / edited)
  * **exports**   — content that left the system: cards marked *posted* in the
                    workflow store, plus publish attempts logged by
                    ``publishing.posting_log``

It introduces **no new data source** — every event is assembled from a store
that already exists. The module is deliberately pure: it takes records that the
caller has already read (DB rows, workflow states, posting-log rows) and returns
structured :class:`ActivityEvent` objects. That keeps the interesting logic —
status mapping, per-run aggregation, merge, sort, date bucketing — fully unit
testable without Flask, a database, or the filesystem. The Flask route does the
I/O and renders the events to HTML.

The renderer (in ``web.py``) maps each event's ``status_tone`` onto the existing
``.tag.<tone>`` CSS and each ``ts`` onto a ``<time class="mh-rel">`` element that
the client-side enhancer turns into "5 min ago".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Event "kind" — the three lanes the feed merges. These double as the values
# of the ?kind= filter and the data-kind attribute the renderer emits.
KIND_RUN = "run"
KIND_APPROVAL = "approval"
KIND_EXPORT = "export"

KINDS = (KIND_RUN, KIND_APPROVAL, KIND_EXPORT)

# Status tone keys map 1:1 onto the existing `.tag.<tone>` CSS classes
# (web.py: .tag.good/.tag.bad/.tag.info/.tag.warn).
TONE_GOOD = "good"
TONE_BAD = "bad"
TONE_INFO = "info"
TONE_WARN = "warn"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# A single recorded value is capped so one runaway error string can't blow the
# detail panel (or the page) out.
_MAX_DETAIL = 600


@dataclass
class ActivityEvent:
    """One card in the feed. Plain data — the renderer escapes every string."""

    kind: str  # KIND_RUN | KIND_APPROVAL | KIND_EXPORT
    subkind: str  # finer label, e.g. "run_done" / "post_failed" — for tests/icons
    ts: str  # ISO-8601 timestamp; the anchor for both sort order and display
    title: str  # primary line (plain text)
    status_label: str  # short badge text, e.g. "completed" / "failed"
    status_tone: str  # TONE_* → .tag.<tone>
    summary: str = ""  # one-line sub-headline under the title (plain text)
    detail: list[tuple[str, str]] = field(default_factory=list)  # (label, value)
    run_id: Optional[str] = None  # drives the "Open run" link when set


# ---------------------------------------------------------------------------
# Small readers — accept either a Mapping (sqlite3.Row / dict) or an object
# (a CardWorkflowState dataclass), so the builder is decoupled from both.
# ---------------------------------------------------------------------------


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a Mapping or an attribute from an object."""
    if record is None:
        return default
    if isinstance(record, Mapping):
        try:
            val = record[key]
        except (KeyError, IndexError):
            return default
        return default if val is None else val
    val = getattr(record, key, default)
    return default if val is None else val


def _status_str(state: Any) -> str:
    """The workflow status of a card as a lowercase string.

    Handles a ``CardWorkflowState`` (``.status`` is a ``CardStatus`` enum or a
    str) and a plain dict (``state["status"]``)."""
    raw = _get(state, "status", "queue")
    val = getattr(raw, "value", raw)  # enum → its .value, else the raw value
    return str(val or "queue").strip().lower()


def _clip(value: Any, limit: int = _MAX_DETAIL) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Time helpers (pure) — bucketing + a server-side relative-time fallback.
# ---------------------------------------------------------------------------


def parse_ts(ts: Any) -> Optional[datetime]:
    """Parse an ISO-ish timestamp to an aware UTC datetime, or None.

    Tolerates a trailing ``Z``, a space separator, and the sub-second / offset
    forms the various stores write. Naive timestamps are assumed UTC so the
    whole feed sorts on one timeline."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip()
        if not s:
            return None
        s = s.replace("Z", "+00:00").replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Last resort: the leading "YYYY-MM-DDTHH:MM:SS" slice.
            try:
                dt = datetime.fromisoformat(s[:19])
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def humanize_age(ts: Any, *, now: Optional[datetime] = None) -> str:
    """A compact server-side relative string ("5 min ago", "3 days ago").

    Rendered as the no-JS fallback text inside ``<time class="mh-rel">``; the
    client enhancer (``bindRelTimes``) replaces it with its own phrasing when
    JS is on. Mirrors that enhancer's thresholds so the two never disagree by a
    category."""
    dt = parse_ts(ts)
    if dt is None:
        return ""
    secs = (_now(now) - dt).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 45:
        return "just now"
    if secs < 90:
        return "1 min ago"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 5400:
        return "1 hr ago"
    if secs < 86400:
        return f"{int(secs // 3600)} hr ago"
    days = int(secs // 86400)
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months < 12:
        return "1 month ago" if months == 1 else f"{months} months ago"
    years = days // 365
    return "1 year ago" if years <= 1 else f"{years} years ago"


# Date buckets — same vocabulary as the runs table so the two Activity views
# read consistently.
BUCKET_ORDER = ("today", "yesterday", "this_week", "this_month", "earlier")
BUCKET_LABELS = {
    "today": "Today",
    "yesterday": "Yesterday",
    "this_week": "Earlier this week",
    "this_month": "Earlier this month",
    "earlier": "Earlier",
}


def bucket_for(ts: Any, *, now: Optional[datetime] = None) -> str:
    """Which date bucket a timestamp falls in (``BUCKET_ORDER`` keys)."""
    dt = parse_ts(ts)
    if dt is None:
        return "earlier"
    delta = _now(now) - dt
    if delta.total_seconds() < 0:
        return "today"
    days = delta.days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return "this_week"
    if days < 30:
        return "this_month"
    return "earlier"


# ---------------------------------------------------------------------------
# Workflow aggregation (pure)
# ---------------------------------------------------------------------------


def summarise_workflow(states: Mapping[str, Any]) -> dict:
    """Collapse one run's per-card workflow states into feed-ready figures.

    ``states`` is ``{card_id: state}`` where ``state`` is a ``CardWorkflowState``
    or a dict with ``status`` / ``last_changed_at`` / ``posted_at``. Returns::

        {
          "counts": {queue, approved, rejected, posted, edited, total},
          "review_latest": iso|"",   # newest change among approved/rejected/edited
          "posted_latest": iso|"",   # newest posted_at (else last_changed_at) among posted
        }
    """
    counts = {"queue": 0, "approved": 0, "rejected": 0, "posted": 0, "edited": 0}
    review_latest: Optional[datetime] = None
    review_latest_raw = ""
    posted_latest: Optional[datetime] = None
    posted_latest_raw = ""
    total = 0
    for state in (states or {}).values():
        total += 1
        status = _status_str(state)
        if status in counts:
            counts[status] += 1
        changed_raw = str(_get(state, "last_changed_at", "") or "")
        if status in ("approved", "rejected", "edited"):
            dt = parse_ts(changed_raw)
            if dt is not None and (review_latest is None or dt > review_latest):
                review_latest, review_latest_raw = dt, changed_raw
        if status == "posted":
            posted_raw = str(_get(state, "posted_at", "") or "") or changed_raw
            dt = parse_ts(posted_raw)
            if dt is not None and (posted_latest is None or dt > posted_latest):
                posted_latest, posted_latest_raw = dt, posted_raw
    counts["total"] = total
    return {
        "counts": counts,
        "review_latest": review_latest_raw,
        "posted_latest": posted_latest_raw,
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _join_counts(parts: Sequence[tuple[int, str]]) -> str:
    """ "3 approved · 1 rejected" — omitting any zero-count part."""
    return " · ".join(f"{n} {label}" for n, label in parts if n)


# ---------------------------------------------------------------------------
# Per-source event builders (pure)
# ---------------------------------------------------------------------------


def _run_title(row: Any) -> str:
    return str(_get(row, "meet_name") or _get(row, "file_name") or _get(row, "id") or "Run")


def _run_event(row: Any) -> ActivityEvent:
    status = str(_get(row, "status", "") or "").strip().lower()
    created = str(_get(row, "created_at", "") or "")
    finished = str(_get(row, "finished_at", "") or "")
    swims = int(_get(row, "our_swims", 0) or 0)
    moments = int(_get(row, "n_achievements", 0) or 0)
    queued = int(_get(row, "n_queue", 0) or 0)
    error = str(_get(row, "error", "") or "")

    if status == "error":
        subkind, label, tone = "run_error", "failed", TONE_BAD
        summary = _clip(error) if error else "The pipeline did not finish."
    elif status in ("running", "queued"):
        subkind, label, tone = "run_running", status or "running", TONE_INFO
        summary = "Processing…"
    else:  # done (and any unknown terminal state) reads as completed
        subkind, label, tone = "run_done", "completed", TONE_GOOD
        bits = []
        if swims:
            bits.append(_plural(swims, "swim") + " matched")
        if moments:
            bits.append(_plural(moments, "moment") + " detected")
        summary = " · ".join(bits) if bits else "Run completed."

    # Anchor a terminal run on its finish time (so a long-running job lands at
    # the moment it actually completed); fall back to creation otherwise.
    ts = finished if (status in ("done", "error") and finished) else created

    detail: list[tuple[str, str]] = [("Status", status or "—")]
    if created:
        detail.append(("Started", created))
    if finished:
        detail.append(("Finished", finished))
    fname = str(_get(row, "file_name", "") or "")
    if fname:
        detail.append(("Source file", fname))
    if swims:
        detail.append(("Swims matched", str(swims)))
    if moments:
        detail.append(("Moments detected", str(moments)))
    if queued:
        detail.append(("Cards queued", str(queued)))
    if error:
        detail.append(("Error", _clip(error)))

    return ActivityEvent(
        kind=KIND_RUN,
        subkind=subkind,
        ts=ts,
        title=_run_title(row),
        status_label=label,
        status_tone=tone,
        summary=summary,
        detail=detail,
        run_id=str(_get(row, "id", "") or "") or None,
    )


def _approval_event(run_id: str, meta: Any, summ: dict) -> Optional[ActivityEvent]:
    counts = summ["counts"]
    approved, rejected, edited = (
        counts["approved"],
        counts["rejected"],
        counts["edited"],
    )
    if not (approved or rejected or edited):
        return None
    summary = _join_counts([(approved, "approved"), (rejected, "rejected"), (edited, "edited")])
    if approved:
        label, tone = "approved", TONE_GOOD
    elif rejected:
        label, tone = "rejected", TONE_WARN
    else:
        label, tone = "edited", TONE_INFO
    detail: list[tuple[str, str]] = []
    if approved:
        detail.append(("Approved", str(approved)))
    if rejected:
        detail.append(("Rejected", str(rejected)))
    if edited:
        detail.append(("Edited", str(edited)))
    if summ.get("review_latest"):
        detail.append(("Last change", str(summ["review_latest"])))
    title = str(_get(meta, "meet_name") or _get(meta, "file_name") or run_id or "Review")
    return ActivityEvent(
        kind=KIND_APPROVAL,
        subkind="review",
        ts=str(summ.get("review_latest") or ""),
        title=title,
        status_label=label,
        status_tone=tone,
        summary=f"Reviewed — {summary}" if summary else "Reviewed",
        detail=detail,
        run_id=run_id or None,
    )


def _posted_export_event(run_id: str, meta: Any, summ: dict) -> Optional[ActivityEvent]:
    posted = summ["counts"]["posted"]
    if not posted:
        return None
    title = str(_get(meta, "meet_name") or _get(meta, "file_name") or run_id or "Export")
    detail = [("Cards posted", str(posted))]
    if summ.get("posted_latest"):
        detail.append(("Marked posted", str(summ["posted_latest"])))
    return ActivityEvent(
        kind=KIND_EXPORT,
        subkind="posted",
        ts=str(summ.get("posted_latest") or ""),
        title=title,
        status_label="posted",
        status_tone=TONE_GOOD,
        summary=_plural(posted, "card") + " marked posted",
        detail=detail,
        run_id=run_id or None,
    )


def _export_attempt_event(attempt: Any, meta: Any) -> ActivityEvent:
    status = str(_get(attempt, "status", "") or "").strip().lower()
    channel = str(_get(attempt, "channel_name") or _get(attempt, "channel_id") or "a channel")
    error_kind = str(_get(attempt, "error_kind", "") or "")
    error_msg = str(_get(attempt, "error_message", "") or "")
    excerpt = str(_get(attempt, "caption_excerpt", "") or "")
    run_id = str(_get(attempt, "run_id", "") or "")

    if status == "ok":
        subkind, label, tone = "post_ok", "published", TONE_GOOD
        title = f"Published to {channel}"
        summary = _clip(excerpt, 160) if excerpt else "Posted to the channel."
    else:
        subkind, label, tone = "post_failed", (error_kind or "failed"), TONE_BAD
        title = f"Publish to {channel} failed"
        summary = _clip(error_msg, 160) or "The publish attempt did not succeed."

    detail: list[tuple[str, str]] = [("Channel", channel)]
    service = str(_get(attempt, "service", "") or "")
    if service:
        detail.append(("Service", service))
    detail.append(("Status", status or "—"))
    scheduled = str(_get(attempt, "scheduled_at", "") or "")
    if scheduled:
        detail.append(("Scheduled for", scheduled))
    if excerpt:
        detail.append(("Caption", _clip(excerpt)))
    if error_msg:
        detail.append(("Error", _clip(error_msg)))
    meet = str(_get(meta, "meet_name") or _get(meta, "file_name") or "")
    if meet:
        detail.append(("Run", meet))

    return ActivityEvent(
        kind=KIND_EXPORT,
        subkind=subkind,
        ts=str(_get(attempt, "attempted_at", "") or ""),
        title=title,
        status_label=label,
        status_tone=tone,
        summary=summary,
        detail=detail,
        run_id=run_id or None,
    )


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


def build_activity_feed(
    *,
    runs: Sequence[Any] = (),
    workflow_by_run: Optional[Mapping[str, Mapping[str, Any]]] = None,
    posting_attempts: Sequence[Any] = (),
    run_meta: Optional[Mapping[str, Any]] = None,
    kind: str = "",
    limit: int = 80,
) -> list[ActivityEvent]:
    """Merge the three lanes into one reverse-chronological list of events.

    ``runs`` are run rows (Mappings); ``workflow_by_run`` maps a run id to its
    ``{card_id: state}`` workflow states; ``posting_attempts`` are posting-log
    rows. ``run_meta`` maps a run id to a record carrying ``meet_name`` /
    ``file_name`` (used to title approval / export events and to label posting
    attempts) — runs is used to seed it when not supplied. ``kind`` optionally
    filters to a single lane. Events are sorted newest-first and capped at
    ``limit``.
    """
    workflow_by_run = workflow_by_run or {}
    # Seed run_meta from the run rows so approval/export events can be titled
    # even when the caller doesn't pass a separate map.
    meta: dict[str, Any] = {}
    for row in runs:
        rid = str(_get(row, "id", "") or "")
        if rid:
            meta[rid] = row
    for rid, m in (run_meta or {}).items():
        meta[str(rid)] = m

    want = kind if kind in KINDS else ""

    events: list[ActivityEvent] = []

    if want in ("", KIND_RUN):
        for row in runs:
            events.append(_run_event(row))

    if want in ("", KIND_APPROVAL, KIND_EXPORT):
        for rid, states in workflow_by_run.items():
            summ = summarise_workflow(states)
            if want in ("", KIND_APPROVAL):
                ev = _approval_event(str(rid), meta.get(str(rid)), summ)
                if ev:
                    events.append(ev)
            if want in ("", KIND_EXPORT):
                ev = _posted_export_event(str(rid), meta.get(str(rid)), summ)
                if ev:
                    events.append(ev)

    if want in ("", KIND_EXPORT):
        for attempt in posting_attempts:
            events.append(
                _export_attempt_event(attempt, meta.get(str(_get(attempt, "run_id", ""))))
            )

    events.sort(key=lambda e: (parse_ts(e.ts) or _EPOCH), reverse=True)
    if limit is not None and limit >= 0:
        events = events[:limit]
    return events


def feed_counts(events: Sequence[ActivityEvent]) -> dict:
    """Per-kind tallies for the filter chips: ``{all, run, approval, export}``."""
    out = {"all": len(events), KIND_RUN: 0, KIND_APPROVAL: 0, KIND_EXPORT: 0}
    for ev in events:
        if ev.kind in out:
            out[ev.kind] += 1
    return out


__all__ = [
    "ActivityEvent",
    "KIND_RUN",
    "KIND_APPROVAL",
    "KIND_EXPORT",
    "KINDS",
    "BUCKET_ORDER",
    "BUCKET_LABELS",
    "TONE_GOOD",
    "TONE_BAD",
    "TONE_INFO",
    "TONE_WARN",
    "parse_ts",
    "humanize_age",
    "bucket_for",
    "summarise_workflow",
    "build_activity_feed",
    "feed_counts",
]
