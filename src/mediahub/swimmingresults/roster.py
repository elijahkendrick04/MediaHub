"""
swimmingresults/roster.py — resolve a club's swimmers to their tiref (member id).

swimmingresults.org has no name search (you must already know the member id), but
the event-rankings page lists every ranked swimmer of a club as a link carrying
their tiref. So we query the club's rankings for an event + age group and read
off ``{tiref: "Full Name"}`` — the roster slice the matcher searches.

Two lookups, both cached for a process lifetime:
  * the event-number map (distance+stroke → the site's Stroke code), parsed from
    the rankings form so a site renumber can't silently break us;
  * each roster slice (club, sex, age, event, course), so swimmers sharing an
    event/age don't refetch it.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from .transport import SR_BASE, SRFetchError, fetch

log = logging.getLogger(__name__)

_FORM_URL = SR_BASE + "/eventrankings/"
_RANK_URL = SR_BASE + "/eventrankings/eventrankings.php"

_STROKE_SELECT = re.compile(r'<select[^>]*name=["\']Stroke["\'][^>]*>(.*?)</select>', re.I | re.S)
_OPTION = re.compile(r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>(.*?)</option>', re.I | re.S)
# A ranked swimmer: a tiref link whose anchor text is the swimmer's name.
_TIREF_PAIR = re.compile(r"tiref=(\d+)[^>]*>\s*([^<]+?)\s*<", re.I)

_STROKE_LABEL = re.compile(r"(\d+)\s*m?\s*(freestyle|backstroke|breaststroke|butterfly|.*medley)", re.I)
_LABEL_CODE = {
    "freestyle": "FR", "backstroke": "BK", "breaststroke": "BR",
    "butterfly": "FL", "medley": "IM",
}

_POOL = {"LC": "L", "SC": "S"}

_LOCK = threading.Lock()
_EVENTNO: dict[tuple[int, str], str] = {}
_EVENTNO_AT: float = 0.0
_SLICE_CACHE: dict[tuple, dict[str, str]] = {}
_TTL = 24 * 3600.0


def _load_event_numbers(force: bool = False) -> dict[tuple[int, str], str]:
    """Map (distance, stroke_code) → the site's Stroke <select> value."""
    global _EVENTNO_AT
    with _LOCK:
        if _EVENTNO and (time.time() - _EVENTNO_AT) < _TTL and not force:
            return dict(_EVENTNO)
    try:
        body = fetch(_FORM_URL)
    except SRFetchError as exc:
        log.warning("swimmingresults: could not load event-number map: %s", exc)
        with _LOCK:
            return dict(_EVENTNO)
    sel = _STROKE_SELECT.search(body)
    out: dict[tuple[int, str], str] = {}
    if sel:
        for value, label in _OPTION.findall(sel.group(1)):
            m = _STROKE_LABEL.search(re.sub(r"<[^>]+>", " ", label))
            if not m:
                continue
            dist = int(m.group(1))
            word = m.group(2).lower()
            code = next((c for key, c in _LABEL_CODE.items() if key in word), None)
            if code:
                out[(dist, code)] = value.strip()
    if out:
        with _LOCK:
            _EVENTNO.clear()
            _EVENTNO.update(out)
            _EVENTNO_AT = time.time()
    return out


def event_number(distance: int, stroke_code: str) -> Optional[str]:
    return _load_event_numbers().get((int(distance), (stroke_code or "").upper()))


def _sex_param(gender: str) -> Optional[str]:
    g = (gender or "").strip().upper()
    if g == "F":
        return "F"
    if g == "M":
        return "M"
    return None  # 'X'/unknown: caller decides whether to try both


def roster_slice(
    club_code: str,
    gender: str,
    age: int,
    distance: int,
    stroke_code: str,
    course: str,
    *,
    force_refresh: bool = False,
) -> dict[str, str]:
    """``{tiref: "Full Name"}`` for one club/sex/age/event/course, or ``{}``.

    Cached per slice. A fetch failure returns ``{}`` (a miss — the caller asserts
    no PB rather than guess).
    """
    sex = _sex_param(gender)
    pool = _POOL.get((course or "").upper())
    evno = event_number(distance, stroke_code)
    if not (club_code and sex and pool and evno and age):
        return {}

    key = (club_code, sex, int(age), evno, pool)
    if not force_refresh:
        with _LOCK:
            if key in _SLICE_CACHE:
                return dict(_SLICE_CACHE[key])

    params = (
        f"?Pool={pool}&Stroke={evno}&Sex={sex}&TargetYear=A&AgeGroup={int(age):02d}"
        f"&AgeAt=A&StartNumber=1&RecordsToView=500&Level=O"
        f"&TargetNationality=P&TargetRegion=P&TargetCounty=XXXX&TargetClub={club_code}"
    )
    try:
        body = fetch(_RANK_URL + params)
    except SRFetchError as exc:
        log.info("swimmingresults: roster slice failed (%s age %s): %s", club_code, age, exc)
        return {}

    out: dict[str, str] = {}
    for tiref, name in _TIREF_PAIR.findall(body):
        name = name.strip()
        # Skip non-name anchors (the page also links a few nav items by id).
        if name and not name.isdigit() and len(name) >= 3:
            out.setdefault(tiref, name)
    with _LOCK:
        _SLICE_CACHE[key] = dict(out)
    return out
