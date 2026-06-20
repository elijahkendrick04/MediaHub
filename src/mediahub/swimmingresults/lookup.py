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
from .roster import _load_event_numbers, roster_slice
from .transport import SR_BASE, SRFetchError, fetch

log = logging.getLogger(__name__)

SOURCE_DOMAIN = "swimmingresults.org"
_PB_URL = SR_BASE + "/individualbest/personal_best.php?mode=A&tiref={tiref}"

_COURSES = ("LC", "SC")
_FETCH_WORKERS = 8

# Default age sweep when the meet file carries no per-swimmer age (the rankings
# query needs a specific age). 9–19 covers age-group swimming; an all-time
# ranking lists older swimmers under the age they swam too, so most seniors are
# still found via their junior ranks. Widen via env for masters/university meets.
_AGE_MIN_DEFAULT = 9
_AGE_MAX_DEFAULT = 19

# Ceiling on roster-resolution fetches per run. A full club sweep (all events ×
# age range × both courses × both sexes) is a few hundred slices; the in-process
# roster cache makes repeat runs within a worker free.
_DEFAULT_BUDGET = 1500

# In-process club-roster cache: (club_code, sex, ages, events) -> {tiref: name}.
# A club's roster changes slowly, so within a worker's lifetime we build it once.
_ROSTER_CACHE: dict[tuple, dict[str, str]] = {}


def _budget() -> int:
    raw = os.environ.get("MEDIAHUB_SR_MAX_FETCHES", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_BUDGET


def _age_range() -> tuple[int, int]:
    def _env(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        return int(raw) if raw.isdigit() else default

    lo = _env("MEDIAHUB_SR_AGE_MIN", _AGE_MIN_DEFAULT)
    hi = _env("MEDIAHUB_SR_AGE_MAX", _AGE_MAX_DEFAULT)
    return (min(lo, hi), max(lo, hi))


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


def _age_candidates(swimmer, results, meet_year: Optional[int]) -> set[int]:
    """Ages to try in the roster. A swim ranks under the age the swimmer WAS on
    the day, so we include the current age and the one below (they may have only
    ranked younger). Uses age_at_meet, else dob + meet year, else event bands,
    else the default sweep range."""
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
        lo, hi = _age_range()  # no age info anywhere: a bounded sweep
        ages = set(range(lo, hi + 1))
    return ages


def _build_club_roster(
    club_code: str,
    sex: str,
    ages: "list[int]",
    events: "list[tuple[int, str]]",
    *,
    force_refresh: bool,
    budget: int,
) -> "tuple[dict[str, str], int]":
    """The club's full ``{tiref: name}`` roster for one sex — the union across
    every (age, event, course). Cached in-process. Returns (roster, fetches).

    Sweeping the whole roster (not just a few events) is what actually finds the
    swimmers: every ranked swimmer of the club appears here, so a name match is
    reliable. Bounded by ``budget``."""
    cache_key = (club_code, sex, tuple(ages), tuple(events))
    if not force_refresh and cache_key in _ROSTER_CACHE:
        return _ROSTER_CACHE[cache_key], 0

    jobs = [
        (age, dist, stroke, course)
        for age in ages
        for (dist, stroke) in events
        for course in _COURSES
    ][: max(0, budget)]

    roster: dict[str, str] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            for sl in pool.map(
                lambda j: roster_slice(
                    club_code, sex, j[0], j[1], j[2], j[3], force_refresh=force_refresh
                ),
                jobs,
            ):
                roster.update(sl)
    _ROSTER_CACHE[cache_key] = roster
    return roster, len(jobs)


def _resolve_tirefs(
    club_code: str,
    swimmers: "list[tuple[str, object, list]]",
    *,
    meet_year: Optional[int],
    force_refresh: bool,
    budget: int,
) -> dict[str, str]:
    """Resolve ``{swimmer_key: tiref}`` for swimmers without an ASA id.

    Builds the club's COMPLETE online roster per sex (all events across the age
    range), then name-matches each swimmer within it. The comprehensive sweep is
    what finds the ~90%+ of swimmers who are on the rankings; a narrow event/age
    probe missed too many.
    """
    # Per-swimmer candidate sexes. The rankings query needs F or M; when the file
    # doesn't give a usable gender ("X"/blank — common when a PDF's event headers
    # don't parse a sex) we search BOTH rosters. The unique-match requirement
    # still guards against a wrong hit, so this recovers those swimmers safely.
    members: list[tuple[str, str, str, tuple[str, ...]]] = []
    sex_ages: dict[str, set[int]] = {"F": set(), "M": set()}
    for key, sw, results in swimmers:
        first = getattr(sw, "first_name", "") or ""
        last = getattr(sw, "last_name", "") or ""
        if not (first or last):
            continue
        g = (getattr(sw, "gender", "") or "").upper()
        sexes = (g,) if g in ("F", "M") else ("F", "M")
        ages = _age_candidates(sw, results, meet_year)
        for s in sexes:
            sex_ages[s] |= ages
        members.append((key, first, last, sexes))

    events = sorted(_load_event_numbers().keys())
    if not events or not members:
        return {}

    rosters: dict[str, dict[str, str]] = {}
    fetches = 0
    for s in ("F", "M"):
        if not sex_ages[s] or fetches >= budget:
            continue
        rosters[s], used = _build_club_roster(
            club_code,
            s,
            sorted(sex_ages[s]),
            events,
            force_refresh=force_refresh,
            budget=budget - fetches,
        )
        fetches += used

    resolved: dict[str, str] = {}
    for key, first, last, sexes in members:
        pool: dict[str, str] = {}
        for s in sexes:
            pool.update(rosters.get(s, {}))
        hit = _best_name_match(first, last, pool)
        if hit:
            resolved[key] = hit
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
