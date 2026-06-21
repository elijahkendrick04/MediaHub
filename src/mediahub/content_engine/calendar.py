"""The Plan calendar — a date-anchored body for the planner (roadmap 1.14).

The cross-source planner (``planner.py``) ranks *what* to post; this module lays
the club's content life out *on a calendar*: planned drafts, curated key dates,
operator events, blackout dates, meet anniversaries and already-posted cards, all
anchored to real dates in a window.

It is the calendar's read model — **pure, deterministic, read-only and
URL-free** (the web layer adds links with ``url_for``). It reuses the same stores
the planner reads, so the calendar and the ranked plan can never disagree about
the club's data:

* planned drafts  — ``stub_packs/*.json`` carrying a ``planned_date`` (1.14)
* key dates       — the curated packs (``content_engine.key_dates``)
* events/blackouts— operator direct inputs (``content_engine.inputs``)
* anniversaries   — meet dates × the queried window (``runs_v4``)
* posted history  — ``workflow`` card states with a ``posted_at`` in window

Tenant isolation: every read filters by ``profile_id``; another org's records
never produce a calendar entry. Honesty: nothing is invented — an empty window
says so in ``notes`` rather than inventing context, mirroring the planner.

**Scheduling is planning, not publishing.** A draft's ``planned_date`` is the
day the club intends to *post it manually*; MediaHub never places content on a
social account (standing rule). Moving a draft re-evaluates the soft gate
(blackout-date warnings); it never publishes.
"""

from __future__ import annotations

import calendar as _calmod
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.content_engine.inputs import load_planner_inputs
from mediahub.content_engine.key_dates import key_dates_in_range

# Kinds an entry can carry, in the order they stack on a day cell.
ENTRY_ORDER = (
    "blackout",
    "key_date",
    "event",
    "anniversary",
    "planned_draft",
    "posted",
)


@dataclass
class CalendarEntry:
    """One thing anchored to one date on the Plan calendar."""

    date: str  # ISO YYYY-MM-DD
    kind: str  # one of ENTRY_ORDER
    title: str
    ref: str = ""  # pack_id / run_id / "" — what the web layer links to
    movable: bool = False  # only planned drafts can be dragged to a new day
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "kind": self.kind,
            "title": self.title,
            "ref": self.ref,
            "movable": self.movable,
            "meta": dict(self.meta),
        }


@dataclass
class CalendarModel:
    """The assembled calendar for one org + window."""

    profile_id: str
    sport: str
    start: str  # ISO
    end: str  # ISO
    entries: list[CalendarEntry] = field(default_factory=list)
    unscheduled_drafts: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {k: 0 for k in ENTRY_ORDER}
        for e in self.entries:
            if e.kind in c:
                c[e.kind] += 1
        return c

    def entries_by_date(self) -> dict[str, list[CalendarEntry]]:
        out: dict[str, list[CalendarEntry]] = {}
        for e in self.entries:
            out.setdefault(e.date, []).append(e)
        return out

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "sport": self.sport,
            "start": self.start,
            "end": self.end,
            "entries": [e.to_dict() for e in self.entries],
            "unscheduled_drafts": list(self.unscheduled_drafts),
            "counts": self.counts(),
            "notes": list(self.notes),
        }


def _data_dir(data_dir: Optional[Path]) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    return Path(os.environ.get("DATA_DIR", "."))


def _runs_dir(data_dir: Optional[Path]) -> Path:
    env = os.environ.get("RUNS_DIR")
    if env and data_dir is None:
        return Path(env)
    return _data_dir(data_dir) / "runs_v4"


def _parse_date(value: object) -> Optional[date]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def _in(d: Optional[date], start: date, end: date) -> bool:
    return d is not None and start <= d <= end


# ---------------------------------------------------------------------------
# Source scanners — each org-scoped + read-only
# ---------------------------------------------------------------------------


def _iter_org_packs(profile_id: str, data_dir: Optional[Path]) -> list[dict]:
    """Every draft pack owned by this org (newest first)."""
    packs_dir = _data_dir(data_dir) / "stub_packs"
    if not packs_dir.is_dir():
        return []
    out: list[dict] = []
    for p in packs_dir.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        if (rec.get("profile_id") or "") != profile_id:
            continue
        out.append(rec)
    out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return out


def _draft_entries(
    profile_id: str, start: date, end: date, data_dir: Optional[Path]
) -> tuple[list[CalendarEntry], list[dict]]:
    """Planned-draft entries in window + the unscheduled drafts (side rail)."""
    entries: list[CalendarEntry] = []
    unscheduled: list[dict] = []
    for rec in _iter_org_packs(profile_id, data_dir):
        pack_id = str(rec.get("pack_id") or "")
        title = str(rec.get("title") or "Draft")
        stub_type = str(rec.get("stub_type") or "")
        n_cards = len(rec.get("cards") or [])
        planned = _parse_date(rec.get("planned_date"))
        if planned is None:
            unscheduled.append(
                {
                    "pack_id": pack_id,
                    "title": title,
                    "stub_type": stub_type,
                    "n_cards": n_cards,
                    "created_at": str(rec.get("created_at") or ""),
                }
            )
            continue
        if not _in(planned, start, end):
            continue
        entries.append(
            CalendarEntry(
                date=planned.isoformat(),
                kind="planned_draft",
                title=title,
                ref=pack_id,
                movable=True,
                meta={
                    "stub_type": stub_type,
                    "n_cards": n_cards,
                    "channel": str(rec.get("planned_channel") or ""),
                },
            )
        )
    return entries, unscheduled


def _posted_entries(
    profile_id: str, start: date, end: date, data_dir: Optional[Path]
) -> list[CalendarEntry]:
    """Already-posted cards whose posted_at falls in window (read-only history)."""
    runs_dir = _runs_dir(data_dir)
    if not runs_dir.is_dir():
        return []
    try:
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore
    except Exception:  # pragma: no cover - core modules
        return []
    store = WorkflowStore(runs_dir)
    # Map run_id → meet name, org-scoped.
    run_names: dict[str, str] = {}
    for p in runs_dir.glob("*.json"):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict) or (rec.get("profile_id") or "") != profile_id:
            continue
        run_id = str(rec.get("run_id") or p.stem)
        meet = rec.get("meet") or {}
        run_names[run_id] = str(meet.get("name") or rec.get("file_name") or "a meet")

    entries: list[CalendarEntry] = []
    for run_id, meet_name in run_names.items():
        try:
            states = store.load(run_id)
        except Exception:
            continue
        posted_on: dict[str, int] = {}
        for st in states.values():
            if st.status != CardStatus.POSTED:
                continue
            d = _parse_date(getattr(st, "posted_at", None))
            if _in(d, start, end):
                key = d.isoformat()
                posted_on[key] = posted_on.get(key, 0) + 1
        for day, n in posted_on.items():
            entries.append(
                CalendarEntry(
                    date=day,
                    kind="posted",
                    title=f"{n} card{'s' if n != 1 else ''} posted — {meet_name}",
                    ref=run_id,
                    meta={"n_cards": n, "meet_name": meet_name},
                )
            )
    return entries


def _anniversary_entries(
    profile_id: str, start: date, end: date, data_dir: Optional[Path]
) -> list[CalendarEntry]:
    """Anniversaries of the club's own meets landing in window."""
    runs_dir = _runs_dir(data_dir)
    if not runs_dir.is_dir():
        return []
    entries: list[CalendarEntry] = []
    seen: set[tuple[str, str]] = set()
    for p in runs_dir.glob("*.json"):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict) or (rec.get("profile_id") or "") != profile_id:
            continue
        meet = rec.get("meet") or {}
        meet_name = str(meet.get("name") or "").strip()
        finished = _parse_date(rec.get("finished_at"))
        if not meet_name or finished is None:
            continue
        for year in range(start.year, end.year + 1):
            years = year - finished.year
            if years < 1:
                continue
            try:
                anniv = finished.replace(year=year)
            except ValueError:  # 29 Feb
                anniv = date(year, 3, 1)
            if not _in(anniv, start, end):
                continue
            key = (anniv.isoformat(), meet_name)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                CalendarEntry(
                    date=anniv.isoformat(),
                    kind="anniversary",
                    title=f"{years} year{'s' if years != 1 else ''} since {meet_name}",
                    ref=str(rec.get("run_id") or ""),
                    meta={"meet_name": meet_name, "years": years},
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_calendar(
    profile_id: str,
    sport: str,
    *,
    start: date,
    end: date,
    data_dir: Optional[Path] = None,
) -> CalendarModel:
    """Assemble the calendar for ``profile_id`` over ``[start, end]`` (inclusive).

    Deterministic and read-only for fixed inputs. ``sport`` selects the curated
    key-date pack (honestly empty when no pack ships for it).
    """
    if start > end:
        start, end = end, start

    entries: list[CalendarEntry] = []

    # Operator direct inputs — events + blackouts.
    inputs = load_planner_inputs(profile_id, data_dir=data_dir)
    for ev in inputs.get("upcoming_events") or []:
        d = _parse_date(ev.get("date"))
        if not _in(d, start, end):
            continue
        venue = str(ev.get("venue") or "")
        entries.append(
            CalendarEntry(
                date=d.isoformat(),
                kind="event",
                title=str(ev.get("name") or "Event"),
                meta={"venue": venue},
            )
        )
    blackout_set = set(inputs.get("blackout_dates") or [])
    for b in inputs.get("blackout_dates") or []:
        d = _parse_date(b)
        if not _in(d, start, end):
            continue
        entries.append(
            CalendarEntry(
                date=d.isoformat(),
                kind="blackout",
                title="Blackout — hold posts",
                meta={},
            )
        )

    # Curated key dates for the sport.
    for kd in key_dates_in_range(sport, start, end):
        entries.append(
            CalendarEntry(
                date=kd.on.isoformat(),
                kind="key_date",
                title=kd.name,
                meta={"kd_kind": kd.kind, "note": kd.note, "source": kd.source},
            )
        )

    # Planned drafts (+ the unscheduled side rail) and posted history.
    draft_entries, unscheduled = _draft_entries(profile_id, start, end, data_dir)
    entries.extend(draft_entries)
    entries.extend(_posted_entries(profile_id, start, end, data_dir))
    entries.extend(_anniversary_entries(profile_id, start, end, data_dir))

    # A planned draft landing on a blackout day is the soft-gate warning the
    # web layer surfaces — flag it here so the model carries it deterministically.
    for e in entries:
        if e.kind == "planned_draft" and e.date in blackout_set:
            e.meta["on_blackout"] = True

    order = {k: i for i, k in enumerate(ENTRY_ORDER)}
    entries.sort(key=lambda e: (e.date, order.get(e.kind, 99), e.title))

    notes: list[str] = []
    if not entries:
        notes.append(
            "Nothing on the calendar in this window yet — schedule a draft, add an "
            "event on the Plan page, or move to a month with key dates. Honest blank, "
            "not invented context."
        )
    if not unscheduled and not draft_entries:
        notes.append("No drafts saved yet — create content first, then plan when to post it.")

    return CalendarModel(
        profile_id=profile_id,
        sport=sport,
        start=start.isoformat(),
        end=end.isoformat(),
        entries=entries,
        unscheduled_drafts=unscheduled,
        notes=notes,
    )


def month_matrix(year: int, month: int) -> list[list[date]]:
    """The Monday-first 6×7 (or 5×7) week matrix of ``date``s covering ``month``
    — including the leading/trailing days from adjacent months that fill the
    grid. Deterministic; used by the web layer to lay out the month view."""
    cal = _calmod.Calendar(firstweekday=0)  # Monday
    weeks = cal.monthdatescalendar(year, month)
    return [list(week) for week in weeks]


def grid_bounds(year: int, month: int) -> tuple[date, date]:
    """The first and last *grid* day for ``month`` (Monday-first), i.e. the span
    the month view actually shows including spill days from adjacent months."""
    weeks = month_matrix(year, month)
    return weeks[0][0], weeks[-1][-1]


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


__all__ = [
    "CalendarEntry",
    "CalendarModel",
    "ENTRY_ORDER",
    "build_calendar",
    "month_matrix",
    "grid_bounds",
    "today_utc",
]
