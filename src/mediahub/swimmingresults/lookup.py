"""
swimmingresults/lookup.py — meet swimmers → official PB baselines.

The public entry point the pipeline calls. For each of the club's swimmers it:

  1. resolves a tiref — directly from the swimmer's ASA id when the file carries
     one (HY3/SDIF), else from the club's online rankings roster matched by
     name within the right club + age (the maintainer's "same club + same age +
     close name = same person" rule);
  2. fetches that swimmer's official personal-best page and parses it;
  3. emits a ``BridgedSnapshot`` keyed by the canonical swimmer_key — the exact
     shape the existing deterministic PB detectors already consume.

This is the authoritative baseline: a swimmer's COMPLETE licensed-meet best, not
a partial record of what happened to be uploaded to MediaHub. A swimmer we can't
resolve gets NO snapshot (an honest miss the secondary lookup may still cover) —
never a guessed baseline that could manufacture a false PB.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

from mediahub.pipeline.pb_bridge import BridgedSnapshot

from .names import name_match, split_full_name
from .parse import parse_personal_best
from .roster import roster_slice
from .transport import SR_BASE, SRFetchError, fetch

log = logging.getLogger(__name__)

SOURCE_DOMAIN = "swimmingresults.org"
_PB_URL = SR_BASE + "/individualbest/personal_best.php?mode=A&tiref={tiref}"

# High-participation events: almost every ranked swimmer appears in at least one,
# so they're enough to find a swimmer in their club's roster without sweeping all
# 19 events. Ordered roughly by participation.
_ANCHOR_EVENTS: list[tuple[int, str]] = [
    (50, "FR"),
    (100, "FR"),
    (200, "FR"),
    (100, "BK"),
    (100, "BR"),
    (100, "FL"),
    (200, "IM"),
    (50, "BK"),
    (50, "BR"),
    (50, "FL"),
]
_COURSES = ("LC", "SC")
_FETCH_WORKERS = 6

# Hard ceiling on roster-resolution fetches per run so a huge meet with no age
# data can't run away. The slice cache makes re-runs cheap. Tunable.
_DEFAULT_BUDGET = 600


def _budget() -> int:
    raw = os.environ.get("MEDIAHUB_SR_MAX_FETCHES", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_BUDGET


def _meet_year(meet) -> Optional[int]:
    for attr in ("start_date", "end_date"):
        d = getattr(meet, attr, None)
        if d and len(str(d)) >= 4 and str(d)[:4].isdigit():
            return int(str(d)[:4])
    return None


def _ages_from_band(band: str) -> set[int]:
    """Pull plausible ages from an event age band ("13", "13-14", "13/Under")."""
    nums = [int(n) for n in re.findall(r"\d{1,2}", band or "") if 5 <= int(n) <= 25]
    if not nums:
        return set()
    if len(nums) == 1:
        return {nums[0]}
    lo, hi = min(nums), max(nums)
    if hi - lo <= 6:  # a real age band, not "0-99"/"OPEN"
        return set(range(lo, hi + 1))
    return set()


def _age_candidates(swimmer, results, meet_year: Optional[int]) -> list[int]:
    """Ages to try in the roster. A swim ranks under the age the swimmer WAS on
    the day, so we include the current age and the one below (they may have only
    ranked younger). Uses age_at_meet, else dob + meet year, else event bands,
    else a bounded default sweep."""
    ages: set[int] = set()
    a = getattr(swimmer, "age_at_meet", None)
    if isinstance(a, int) and a > 0:
        ages.update({a, a - 1})
    dob = getattr(swimmer, "dob", None)
    if not ages and dob and str(dob)[:4].isdigit() and meet_year:
        derived = meet_year - int(str(dob)[:4])
        if 5 <= derived <= 25:
            ages.update({derived, derived - 1})
    for r in results:
        ages |= _ages_from_band(getattr(r, "age_band", "") or "")
    ages = {x for x in ages if 5 <= x <= 25}
    if not ages:
        ages = set(range(9, 19))  # no age info anywhere: a bounded sweep
    return sorted(ages)


def _resolve_tirefs(
    club_code: str,
    swimmers: "list[tuple[str, object, list]]",
    *,
    meet_year: Optional[int],
    force_refresh: bool,
    budget: int,
) -> dict[str, str]:
    """Resolve ``{swimmer_key: tiref}`` for swimmers without an ASA id.

    Buckets swimmers by (sex, candidate age), fetches the club's anchor-event
    roster slices for each bucket (in parallel, within budget), and name-matches
    each swimmer inside its own club+age pool.
    """
    # bucket[(sex, age)] = list of (swimmer_key, first, last)
    buckets: dict[tuple[str, int], list[tuple[str, str, str]]] = {}
    for key, sw, results in swimmers:
        sex = (getattr(sw, "gender", "") or "").upper()
        if sex not in ("F", "M"):
            continue  # need a sex for the rankings query
        first = getattr(sw, "first_name", "") or ""
        last = getattr(sw, "last_name", "") or ""
        if not (first or last):
            continue
        for age in _age_candidates(sw, results, meet_year):
            buckets.setdefault((sex, age), []).append((key, first, last))

    resolved: dict[str, str] = {}
    fetches = 0
    for (sex, age), members in buckets.items():
        pending = [m for m in members if m[0] not in resolved]
        if not pending:
            continue
        index: dict[str, str] = {}  # tiref -> full name
        for dist, stroke in _ANCHOR_EVENTS:
            if not pending or fetches >= budget:
                break
            jobs = [(dist, stroke, course) for course in _COURSES]
            with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
                slices = list(
                    pool.map(
                        lambda j: roster_slice(
                            club_code,
                            sex,
                            age,
                            j[0],
                            stroke,
                            j[2],
                            force_refresh=force_refresh,
                        ),
                        jobs,
                    )
                )
            fetches += len(jobs)
            for sl in slices:
                index.update(sl)
            if not index:
                continue
            still: list[tuple[str, str, str]] = []
            for key, first, last in pending:
                hit = _best_name_match(first, last, index)
                if hit:
                    resolved[key] = hit
                else:
                    still.append((key, first, last))
            pending = still
    return resolved


def _best_name_match(first: str, last: str, index: dict[str, str]) -> Optional[str]:
    """Return the tiref whose roster name matches (first,last), if unambiguous."""
    hits = []
    for tiref, full in index.items():
        rf, rl = split_full_name(full)
        if name_match(first, last, rf, rl):
            hits.append(tiref)
    # Unique match only — within one club+age pool a name should resolve to one
    # person; if two roster entries match, refuse rather than risk the wrong id.
    if len(set(hits)) == 1:
        return hits[0]
    return None


def _fetch_snapshot(
    swimmer_key: str, tiref: str, *, force_refresh: bool
) -> Optional[BridgedSnapshot]:
    url = _PB_URL.format(tiref=tiref)
    try:
        html = fetch(url)
    except SRFetchError as exc:
        log.info("swimmingresults: PB fetch failed for tiref=%s: %s", tiref, exc)
        return None  # transport failure → no snapshot (miss, not a guess)
    page = parse_personal_best(html, tiref)
    now = datetime.now(timezone.utc).isoformat()
    snap = BridgedSnapshot(
        tiref=swimmer_key,
        fetch_ok=True,
        no_history=not page.entries,
        from_cache=False,
        source_url=url,
        retrieved_at=now,
        source_domain=SOURCE_DOMAIN,
    )
    for e in page.entries:
        key = f"{e.distance}{e.stroke}{e.course}"
        snap.pb_times.setdefault(key, []).append(
            {
                "time_sec": e.time_sec,
                "date_iso": e.date_iso,
                "source_url": url,
                "retrieved_at": now,
                "meet": e.meet,
            }
        )
    return snap


def lookup_official_pbs(
    meet,
    our_swimmer_keys,
    club_name: str,
    *,
    force_refresh: bool = False,
    step: Optional[Callable[[str], None]] = None,
) -> dict[str, BridgedSnapshot]:
    """Build ``{swimmer_key: BridgedSnapshot}`` of official PBs for the club's
    swimmers, looked up fresh from swimmingresults.org every run."""
    from .clubs import resolve_club_code

    emit = step or (lambda _m: None)
    swimmers_by_key = getattr(meet, "swimmers", {}) or {}
    results = getattr(meet, "results", []) or []
    our = set(our_swimmer_keys)

    results_by_key: dict[str, list] = {}
    for r in results:
        k = getattr(r, "swimmer_key", None)
        if k in our:
            results_by_key.setdefault(k, []).append(r)

    # 1. tiref fast path: swimmers whose file carries an ASA member id.
    tirefs: dict[str, str] = {}
    need_roster: list[tuple[str, object, list]] = []
    for key in our:
        sw = swimmers_by_key.get(key)
        if sw is None:
            continue
        asa = (getattr(sw, "asa_id", "") or "").strip()
        if asa.isdigit():
            tirefs[key] = asa
        else:
            need_roster.append((key, sw, results_by_key.get(key, [])))

    # 2. roster resolution for the rest (needs the club code).
    n_by_id = len(tirefs)
    n_by_roster = 0
    club_code = resolve_club_code(club_name, force_refresh=force_refresh) if need_roster else None
    if need_roster and not club_code:
        emit(
            f"PB lookup: '{club_name}' isn't on swimmingresults.org — skipping online PBs for unmatched swimmers."
        )
    elif need_roster:
        roster_tirefs = _resolve_tirefs(
            club_code,
            need_roster,
            meet_year=_meet_year(meet),
            force_refresh=force_refresh,
            budget=_budget(),
        )
        n_by_roster = len(roster_tirefs)
        tirefs.update(roster_tirefs)

    if not tirefs:
        return {}

    # 3. fetch + parse each swimmer's official PB page, in parallel.
    snapshots: dict[str, BridgedSnapshot] = {}
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_snapshot, key, tiref, force_refresh=force_refresh): key
            for key, tiref in tirefs.items()
        }
        for fut in futures:
            key = futures[fut]
            try:
                snap = fut.result()
            except Exception as exc:  # never let one swimmer fail the run
                log.info("swimmingresults: snapshot error for %s: %s", key, exc)
                snap = None
            if snap is not None:
                snapshots[key] = snap

    with_pbs = sum(1 for s in snapshots.values() if s.pb_times)
    emit(
        f"PB baseline: looked up {len(tirefs)} swimmer(s) on swimmingresults.org "
        f"— {with_pbs} with official PBs "
        f"({n_by_roster} matched by name+club+age, {n_by_id} by member id)."
    )
    return snapshots
