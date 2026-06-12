"""season_wrap/aggregate.py — deterministic cross-run aggregation (W.8).

Reads persisted ``runs_v4`` snapshots from disk and adds up what happened
for one workspace inside a date window: total PBs, medals (per colour),
club records, debuts, milestones, qualifying hits, busiest swimmer,
biggest improver, and a per-swimmer leaderboard.

Pure counting over stored recognition output — no LLM calls, no network,
same input → same ``WrapStats`` every time. Tenant isolation: only runs
whose ``profile_id`` matches are read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Achievement-type families. PB types are prefixed ``pb_`` except the
# officially-confirmed variant, which has its own historic name.
_PB_EXTRA_TYPES = ("official_pb_confirmed",)
_MEDAL_TYPES = ("medal_gold", "medal_silver", "medal_bronze")
_TOP_ACHIEVEMENTS_CAP = 16
_LEADERBOARD_SIZE = 5
_MAX_CHIPS = 6


@dataclass
class WrapStats:
    """Everything a wrap/recap pack needs, already added up."""

    profile_id: str
    start: str
    end: str
    n_runs: int = 0
    meet_names: list[str] = field(default_factory=list)
    total_achievements: int = 0
    n_pbs: int = 0
    n_medals: int = 0
    medals_by_colour: dict[str, int] = field(
        default_factory=lambda: {"gold": 0, "silver": 0, "bronze": 0}
    )
    n_club_records: int = 0
    n_debuts: int = 0
    n_milestones: int = 0
    n_qual_hits: int = 0
    busiest_swimmer: Optional[dict] = None  # {"name", "swims"}
    biggest_improver: Optional[dict] = None  # {"swimmer", "event", "drop_pct"}
    fastest_club_record: Optional[dict] = None  # {"swimmer", "event", "time_cs"?, "headline"}
    leaderboard: list[dict] = field(default_factory=list)  # [{"swimmer", "achievements"}]
    top_achievements: list[dict] = field(default_factory=list)  # rank/priority-ordered

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "start": self.start,
            "end": self.end,
            "n_runs": self.n_runs,
            "meet_names": list(self.meet_names),
            "total_achievements": self.total_achievements,
            "n_pbs": self.n_pbs,
            "n_medals": self.n_medals,
            "medals_by_colour": dict(self.medals_by_colour),
            "n_club_records": self.n_club_records,
            "n_debuts": self.n_debuts,
            "n_milestones": self.n_milestones,
            "n_qual_hits": self.n_qual_hits,
            "busiest_swimmer": dict(self.busiest_swimmer) if self.busiest_swimmer else None,
            "biggest_improver": dict(self.biggest_improver) if self.biggest_improver else None,
            "fastest_club_record": (
                dict(self.fastest_club_record) if self.fastest_club_record else None
            ),
            "leaderboard": [dict(r) for r in self.leaderboard],
            "top_achievements": [dict(a) for a in self.top_achievements],
        }

    def headline_stats(self) -> list[tuple[str, str]]:
        """Poster/cover stat chips: non-zero only, fixed order, max 6."""
        ordered = [
            ("PBs", self.n_pbs),
            ("Medals", self.n_medals),
            ("Club records", self.n_club_records),
            ("Debuts", self.n_debuts),
            ("Milestones", self.n_milestones),
            ("Qualifying times", self.n_qual_hits),
        ]
        return [(label, str(n)) for label, n in ordered if n > 0][:_MAX_CHIPS]


def _is_pb_type(atype: str) -> bool:
    return atype.startswith("pb_") or atype in _PB_EXTRA_TYPES


def _run_date(payload: dict) -> str:
    """ISO date (YYYY-MM-DD) a run belongs to: meet start_date, else the
    date part of started_at, else empty (never in any window)."""
    meet = payload.get("meet") or {}
    raw = meet.get("start_date") or payload.get("started_at") or ""
    return str(raw)[:10]


def _iter_window_runs(profile_id: str, runs_dir: Path, start: str, end: str):
    """Yield the org's run payloads dated inside [start, end], in stable
    filename order. Workflow sidecars and unreadable files are skipped."""
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return
    for p in sorted(runs_dir.glob("*.json")):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if (payload.get("profile_id") or "") != profile_id:
            continue
        when = _run_date(payload)
        if not when or not (start[:10] <= when <= end[:10]):
            continue
        yield payload


def aggregate_window(profile_id: str, runs_dir: Path, *, start: str, end: str) -> WrapStats:
    """Add up one workspace's stored runs inside [start, end] (inclusive
    ISO date strings). Deterministic: ties break alphabetically, ordering
    follows stored rank/priority."""
    stats = WrapStats(profile_id=profile_id, start=start[:10], end=end[:10])
    swims_by_swimmer: dict[str, int] = {}
    achievements_by_swimmer: dict[str, int] = {}
    best_drop: Optional[dict] = None
    best_drop_key: tuple = ()
    club_records: list[dict] = []
    candidates: list[dict] = []

    for payload in _iter_window_runs(profile_id, runs_dir, start, end):
        stats.n_runs += 1
        meet = payload.get("meet") or {}
        name = str(meet.get("name") or payload.get("run_id") or "").strip()
        if name:
            stats.meet_names.append(name)

        rr = payload.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []

        # Busiest swimmer: swim traces are the true swim count when present;
        # achievements per swimmer are the fallback signal.
        traces = rr.get("swim_traces") or []
        if traces:
            for t in traces:
                who = str(t.get("swimmer_name") or "").strip()
                if who:
                    swims_by_swimmer[who] = swims_by_swimmer.get(who, 0) + 1
        else:
            for ra in ranked:
                ach = ra.get("achievement") or {}
                who = str(ach.get("swimmer_name") or "").strip()
                if who:
                    swims_by_swimmer[who] = swims_by_swimmer.get(who, 0) + 1

        for ra in ranked:
            if not isinstance(ra, dict):
                continue
            ach = ra.get("achievement") or {}
            atype = str(ach.get("type") or "")
            swimmer = str(ach.get("swimmer_name") or "").strip()
            event = str(ach.get("event") or "").strip()
            raw = ach.get("raw_facts") or {}

            stats.total_achievements += 1
            if swimmer:
                achievements_by_swimmer[swimmer] = achievements_by_swimmer.get(swimmer, 0) + 1

            if _is_pb_type(atype):
                stats.n_pbs += 1
            elif atype in _MEDAL_TYPES:
                stats.n_medals += 1
                colour = atype.removeprefix("medal_")
                stats.medals_by_colour[colour] = stats.medals_by_colour.get(colour, 0) + 1
            elif atype == "club_record":
                stats.n_club_records += 1
                club_records.append(
                    {
                        "swimmer": swimmer,
                        "event": event,
                        "time_cs": raw.get("time_cs"),
                        "headline": str(ach.get("headline") or ""),
                        "_priority": float(ra.get("priority") or 0.0),
                    }
                )
            elif atype == "club_debut":
                stats.n_debuts += 1
            elif atype.startswith("race_milestone_"):
                stats.n_milestones += 1
            elif atype.startswith("qual_hit_"):
                stats.n_qual_hits += 1

            drop_pct = raw.get("drop_pct")
            if isinstance(drop_pct, (int, float)) and swimmer:
                # Largest drop wins; ties break alphabetically.
                key = (-float(drop_pct), swimmer, event)
                if best_drop is None or key < best_drop_key:
                    best_drop = {"swimmer": swimmer, "event": event, "drop_pct": float(drop_pct)}
                    best_drop_key = key

            candidates.append(
                {
                    "swimmer": swimmer,
                    "event": event,
                    "headline": str(ach.get("headline") or ""),
                    "type": atype,
                    "priority": float(ra.get("priority") or 0.0),
                    "rank": int(ra.get("rank") or 0),
                    "meet": name,
                }
            )

    stats.biggest_improver = best_drop

    if swims_by_swimmer:
        top = sorted(swims_by_swimmer.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        stats.busiest_swimmer = {"name": top[0], "swims": top[1]}

    if club_records:
        timed = [r for r in club_records if isinstance(r.get("time_cs"), (int, float))]
        if timed:
            pick = min(timed, key=lambda r: (r["time_cs"], r["swimmer"], r["event"]))
        else:
            pick = sorted(club_records, key=lambda r: (-r["_priority"], r["swimmer"], r["event"]))[0]
        stats.fastest_club_record = {k: v for k, v in pick.items() if k != "_priority"}

    stats.leaderboard = [
        {"swimmer": who, "achievements": n}
        for who, n in sorted(achievements_by_swimmer.items(), key=lambda kv: (-kv[1], kv[0]))[
            :_LEADERBOARD_SIZE
        ]
    ]

    stats.top_achievements = sorted(
        candidates, key=lambda c: (-c["priority"], c["rank"], c["swimmer"], c["event"])
    )[:_TOP_ACHIEVEMENTS_CAP]

    return stats


__all__ = ["WrapStats", "aggregate_window"]
