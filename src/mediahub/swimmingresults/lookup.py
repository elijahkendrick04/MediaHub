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

from .names import first_lead, fold, name_match, split_full_name, surname_match
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

# In-process club-roster cache: (club_code, sex, ages, events) ->
# {tiref: {"name", "times"}}. A club's roster changes slowly, so within a
# worker's lifetime we build it once.
_ROSTER_CACHE: dict[tuple, dict[str, dict]] = {}


def _budget() -> int:
    raw = os.environ.get("MEDIAHUB_SR_MAX_FETCHES", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_BUDGET


def _age_range() -> tuple[int, int]:
    def _as_int(raw: str, default: int) -> int:
        raw = (raw or "").strip()
        return int(raw) if raw.isdigit() else default

    lo = _as_int(os.environ.get("MEDIAHUB_SR_AGE_MIN", ""), _AGE_MIN_DEFAULT)
    hi = _as_int(os.environ.get("MEDIAHUB_SR_AGE_MAX", ""), _AGE_MAX_DEFAULT)
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
) -> "tuple[dict[str, dict], int]":
    """The club's full roster for one sex — ``{tiref: {"name", "times"}}`` where
    ``times`` is ``{event_key: best_time_cs}`` across every (age, event, course).
    Cached in-process. Returns (roster, fetches).

    Sweeping the whole roster (not just a few events) is what actually finds the
    swimmers; capturing each swimmer's times lets us tell same-surname siblings
    apart by performance instead of a hand-maintained nickname list. Bounded by
    ``budget``."""
    cache_key = (club_code, sex, tuple(ages), tuple(events))
    if not force_refresh and cache_key in _ROSTER_CACHE:
        return _ROSTER_CACHE[cache_key], 0

    jobs = [
        (age, dist, stroke, course)
        for age in ages
        for (dist, stroke) in events
        for course in _COURSES
    ][: max(0, budget)]

    def _one(j: tuple) -> "tuple[str, dict[str, tuple[str, Optional[int]]]]":
        age, dist, stroke, course = j
        event_key = f"{dist}{stroke}{course}"
        return event_key, roster_slice(
            club_code, sex, age, dist, stroke, course, force_refresh=force_refresh
        )

    roster: dict[str, dict] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            for event_key, sl in pool.map(_one, jobs):
                for tiref, (name, time_cs, date_iso, meet) in sl.items():
                    info = roster.setdefault(tiref, {"name": name, "events": {}})
                    if time_cs is not None:
                        prev = info["events"].get(event_key)
                        if prev is None or time_cs < prev["time_cs"]:
                            info["events"][event_key] = {
                                "time_cs": time_cs,
                                "date_iso": date_iso,
                                "meet": meet,
                            }
    _ROSTER_CACHE[cache_key] = roster
    return roster, len(jobs)


def _times_of(info: dict) -> dict[str, int]:
    """``{event_key: time_cs}`` view of a roster entry's events."""
    return {ek: e["time_cs"] for ek, e in info.get("events", {}).items() if e.get("time_cs")}


def _resolve_tirefs(
    club_code: str,
    swimmers: "list[tuple[str, object, list]]",
    *,
    meet_year: Optional[int],
    force_refresh: bool,
    budget: int,
) -> "tuple[dict[str, str], dict[str, dict]]":
    """Resolve swimmers to tirefs off the club's online roster.

    Returns ``({swimmer_key: tiref}, {tiref: roster_entry})`` — the second map
    lets the caller build a PB snapshot straight from the all-time rankings (the
    only place a swimmer with a lapsed membership still has times). Builds the
    club's COMPLETE roster per sex (all events across the age range), then
    name+time-matches each swimmer within it.
    """
    # Per-swimmer candidate sexes. The rankings query needs F or M; when the file
    # doesn't give a usable gender ("X"/blank — common when a PDF's event headers
    # don't parse a sex) we search BOTH rosters.
    members: list[tuple[str, str, str, tuple[str, ...], dict[str, int]]] = []
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
        members.append((key, first, last, sexes, _meet_times(results)))

    events = sorted(_load_event_numbers().keys())
    if not events or not members:
        return {}

    rosters: dict[str, dict[str, dict]] = {}
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

    merged: dict[str, dict] = {}
    for s in ("F", "M"):
        merged.update(rosters.get(s, {}))

    resolved: dict[str, str] = {}
    for key, first, last, sexes, meet_times in members:
        pool: dict[str, dict] = {}
        for s in sexes:
            pool.update(rosters.get(s, {}))
        hit = _match_one(first, last, meet_times, pool)
        if hit:
            resolved[key] = hit
    return resolved, merged


def _meet_times(results) -> dict[str, int]:
    """``{event_key: best finals time_cs}`` for one swimmer's swims at this meet."""
    out: dict[str, int] = {}
    for r in results:
        cs = getattr(r, "finals_time_cs", None)
        if not cs or cs <= 0:
            continue
        ek = f"{getattr(r, 'distance', '')}{getattr(r, 'stroke', '')}{getattr(r, 'course', '')}"
        if ek and (ek not in out or cs < out[ek]):
            out[ek] = int(cs)
    return out


def _time_plausible(meet_times: dict[str, int], cand_times: dict[str, int]) -> bool:
    """A meet swim can't be much faster than that swimmer's own lifetime best, so
    if the meet time is >7% faster than the candidate's ranked best in any shared
    event, it's a different (faster) person — rule the candidate out. With no
    shared event we can't judge, so we don't rule out."""
    for ek, mt in meet_times.items():
        ct = cand_times.get(ek)
        if ct and mt and mt < ct * 0.93:
            return False
    return True


def _closest_by_time(
    meet_times: dict[str, int], cands: list[str], roster: dict[str, dict]
) -> Optional[str]:
    """Among same-surname candidates, the one whose ranked times best match this
    swimmer's meet times — a clear winner identifies the right sibling without
    any first-name nickname rule."""
    scored: list[tuple[float, str]] = []
    for t in cands:
        ct = _times_of(roster[t])
        gaps = [abs(mt - ct[ek]) / ct[ek] for ek, mt in meet_times.items() if ct.get(ek) and mt]
        if gaps:
            scored.append((min(gaps), t))
    if not scored:
        return None
    scored.sort()
    # Accept only a decisive winner (best gap clearly tighter than the runner-up).
    if len(scored) == 1 or scored[0][0] <= 0.02 or scored[0][0] < scored[1][0] * 0.5:
        return scored[0][1]
    return None


def _match_one(
    first: str, last: str, meet_times: dict[str, int], roster: dict[str, dict]
) -> Optional[str]:
    """Resolve one swimmer to a tiref within a club roster, WITHOUT relying on a
    hand-maintained nickname list:

      1. exact surname + leading-first-name → win (the reliable common case);
      2. else surname match (+ time sanity) — if unique, it's them regardless of
         the first name (so "Lotty"→Charlotte, "JJ"→Jonathan just work);
      3. else same-surname siblings → the closest race time picks the right one;
      4. else the nickname/spelling-tolerant fuzzy match, only if unique.
    """
    fl = fold(last)
    f_lead = first_lead(first)

    # 1) exact surname + leading first name.
    exact = [
        t
        for t, info in roster.items()
        if fl
        and f_lead
        and fold(split_full_name(info["name"])[1]) == fl
        and first_lead(split_full_name(info["name"])[0]) == f_lead
    ]
    if len(set(exact)) == 1:
        return exact[0]

    # 2/3) surname candidates, ruled by time.
    surname_cands = [
        t for t, info in roster.items() if surname_match(last, split_full_name(info["name"])[1])
    ]
    plausible = [t for t in surname_cands if _time_plausible(meet_times, _times_of(roster[t]))]
    pool = plausible or surname_cands
    if len(set(pool)) == 1:
        return pool[0]
    if len(pool) > 1:
        winner = _closest_by_time(meet_times, pool, roster)
        if winner:
            return winner

    # 4) fuzzy first-name fallback (nickname/spelling), only if unique.
    fuzzy = [
        t for t, info in roster.items() if name_match(first, last, *split_full_name(info["name"]))
    ]
    if len(set(fuzzy)) == 1:
        return fuzzy[0]
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


def _snapshot_from_roster(swimmer_key: str, tiref: str, entry: dict) -> BridgedSnapshot:
    """Build a PB snapshot from the all-time rankings rows we already swept.

    This is the path that covers swimmers who have left the sport: their
    membership lapses and ``personal_best.php`` 404/400s, but their times remain
    in the event rankings. Less complete than the personal-best page (limited to
    the swept age range), but real and provenance-tagged."""
    now = datetime.now(timezone.utc).isoformat()
    url = _PB_URL.format(tiref=tiref)
    events = entry.get("events", {})
    snap = BridgedSnapshot(
        tiref=swimmer_key,
        fetch_ok=True,
        no_history=not events,
        from_cache=False,
        source_url=url,
        retrieved_at=now,
        source_domain=SOURCE_DOMAIN,
    )
    for ek, e in events.items():
        if not e.get("time_cs"):
            continue
        snap.pb_times.setdefault(ek, []).append(
            {
                "time_sec": e["time_cs"] / 100.0,
                "date_iso": e.get("date_iso", ""),
                "source_url": url,
                "retrieved_at": now,
                "meet": e.get("meet", ""),
            }
        )
    return snap


def _fetch_snapshots(
    tirefs: dict[str, str], *, force_refresh: bool
) -> dict[str, Optional[BridgedSnapshot]]:
    """Fetch each ``{swimmer_key: tiref}`` PB page in parallel. Value is the
    snapshot, or None when the page couldn't be fetched (e.g. HTTP 400 — the
    tiref isn't valid)."""
    out: dict[str, Optional[BridgedSnapshot]] = {}
    if not tirefs:
        return out
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_snapshot, key, tiref, force_refresh=force_refresh): key
            for key, tiref in tirefs.items()
        }
        for fut in futures:
            key = futures[fut]
            try:
                out[key] = fut.result()
            except Exception as exc:  # never let one swimmer fail the run
                log.info("swimmingresults: snapshot error for %s: %s", key, exc)
                out[key] = None
    return out


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

    snapshots: dict[str, BridgedSnapshot] = {}

    # 1. Fast path: swimmers whose file carries a member id → fetch directly.
    asa_tirefs: dict[str, str] = {}
    need_roster: list[tuple[str, object, list]] = []
    for key in our:
        sw = swimmers_by_key.get(key)
        if sw is None:
            continue
        asa = (getattr(sw, "asa_id", "") or "").strip()
        if asa.isdigit():
            asa_tirefs[key] = asa
        else:
            need_roster.append((key, sw, results_by_key.get(key, [])))

    n_by_id = 0
    for key, snap in _fetch_snapshots(asa_tirefs, force_refresh=force_refresh).items():
        if snap is not None:
            snapshots[key] = snap
            n_by_id += 1
        else:
            # The file's number isn't this swimmer's swimmingresults.org tiref
            # (HTTP 400 — common for Welsh/older/international registrations).
            # Fall back to resolving them by name + time off the club roster.
            sw = swimmers_by_key.get(key)
            if sw is not None:
                need_roster.append((key, sw, results_by_key.get(key, [])))

    # 2. Roster resolution (no-id swimmers + those whose id was rejected).
    n_by_roster = 0
    roster_by_tiref: dict[str, dict] = {}
    club_code = resolve_club_code(club_name, force_refresh=force_refresh) if need_roster else None
    if need_roster and not club_code:
        emit(
            f"PB lookup: '{club_name}' isn't on swimmingresults.org — skipping online PBs for unmatched swimmers."
        )
    elif need_roster:
        roster_tirefs, roster_by_tiref = _resolve_tirefs(
            club_code,
            need_roster,
            meet_year=_meet_year(meet),
            force_refresh=force_refresh,
            budget=_budget(),
        )
        # Build PBs straight from the all-time rankings we already swept — no
        # per-swimmer personal_best.php fetch (fewer requests) and it covers
        # swimmers whose membership has lapsed (no personal-best page).
        for key, tiref in roster_tirefs.items():
            entry = roster_by_tiref.get(tiref)
            if not entry:
                continue
            snap = _snapshot_from_roster(key, tiref, entry)
            if snap.pb_times:
                snapshots[key] = snap
                n_by_roster += 1

    with_pbs = sum(1 for s in snapshots.values() if s.pb_times)
    summary = (
        f"PB baseline: {with_pbs} of {len(our)} swimmer(s) matched on "
        f"swimmingresults.org with official PBs "
        f"({n_by_id} by member id, {n_by_roster} by name+club+age)."
    )
    emit(summary)
    # Also log it: emit() only drives the in-UI progress stream, so without this
    # the resolution rate never reaches the platform logs (Render), where the
    # operator checks coverage after a run.
    log.info("%s", summary)

    # Name the swimmers we could NOT match, each with a data-grounded reason, so
    # the exact gaps are visible in the platform logs instead of only a count.
    # The operator can then tell a genuine "no ranked time" miss (nothing to fix)
    # apart from a name/age quirk worth recovering — without guessing.
    unmatched = _unmatched_report(our, snapshots, swimmers_by_key, roster_by_tiref)
    if unmatched:
        detail = "; ".join(f"{name} [{reason}]" for name, reason in unmatched)
        line = f"PB baseline: {len(unmatched)} unmatched — {detail}"
        emit(line)
        log.info("%s", line)
    return snapshots


def _unmatched_report(
    our: set,
    snapshots: dict,
    swimmers_by_key: dict,
    roster_by_tiref: dict,
) -> "list[tuple[str, str]]":
    """``[(swimmer_name, reason), …]`` for every requested swimmer with no PB
    snapshot, sorted by name. The reason is derived from the roster we already
    swept: whether any ranked swimmer shares the surname (so a true "not ranked
    for this club" miss is distinguishable from a same-surname disambiguation
    that fell through). Never raises — diagnostics must not fail a run."""
    matched = {k for k, s in snapshots.items() if getattr(s, "pb_times", None)}
    roster_surnames = [
        split_full_name(e.get("name", ""))[1] for e in roster_by_tiref.values()
    ]
    out: list[tuple[str, str]] = []
    for key in our:
        if key in matched:
            continue
        sw = swimmers_by_key.get(key)
        if sw is None:
            continue
        first = (getattr(sw, "first_name", "") or "").strip()
        last = (getattr(sw, "last_name", "") or "").strip()
        name = (f"{first} {last}").strip() or str(key)
        if not roster_by_tiref:
            reason = "no club roster available"
        elif not last:
            reason = "no surname parsed from the file"
        else:
            n_same = sum(1 for rs in roster_surnames if rs and surname_match(last, rs))
            if n_same == 0:
                reason = "no ranked swimmer with that surname in the club's all-time rankings"
            else:
                reason = (
                    f"{n_same} same-surname candidate(s), none uniquely resolved "
                    "(first-name/age/time)"
                )
        out.append((name, reason))
    out.sort(key=lambda t: t[0].lower())
    return out
