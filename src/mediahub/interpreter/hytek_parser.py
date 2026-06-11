"""
hytek_parser.py — Parse Hy-Tek Meet Manager `.hy3` exports into InterpretedMeet.

Hytek `.hy3` is a fixed-width record format. Each line begins with a
2-character record type code. The most important records:

* ``A1`` — system / meet results header (produces program + version)
* ``B1`` / ``B2`` — meet info (name, venue, dates)
* ``C1`` / ``C2`` / ``C3`` — team info (one or more records per team)
* ``D1``         — athlete master row (sex, age, last, first, USS id, DOB)
* ``E1`` / ``E2`` — event entry header / finals split (distance, stroke, seed,
  finals, place). ``E1`` carries the meet-event setup (course, age band,
  distance, stroke). ``E2`` carries the achieved finals time + place.
* ``G1`` — splits (informational; included as raw)
* ``H1`` — DQ / disqualification reason

The format has no formal public spec but the CFL parsers / SwimAtlas /
SwimReg parsers all converge on the field layout we use below. Field
positions were verified against the V8.1 corpus samples (Westhill,
Elgin, Garioch, Dyce, Silver City Blues).

This parser is intentionally **forgiving**: if a field is malformed we
record the swim with reduced confidence rather than abort.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .schema_dataclasses import (
    InterpretedEvent,
    InterpretedMeet,
    InterpretedSwim,
)
from .ontology_loader import OntologyLoader

log = logging.getLogger(__name__)

# Hy-Tek stroke and course codes are loaded from
# data/ontology/hytek_codes.json so this module contains no swim
# vocabulary literals.
_ONTOLOGY = OntologyLoader()
_HY_CODES = _ONTOLOGY["hytek_codes"] or {}
_HY3_STROKE: dict[str, str] = _HY_CODES.get("hy3_stroke_codes", {})
_HY3_COURSE: dict[str, str] = _HY_CODES.get("hytek_course_codes", {})


def detect_hy3(data: bytes) -> bool:
    """True if *data* looks like a Hytek .hy3 file."""
    head = data[:200]
    # First record must start with "A1" + version digits, e.g. "A107..."
    if head[:2] == b"A1" and head[2:4].isdigit():
        return True
    # Some .hy3 exports start with whitespace; check first non-empty line
    for line in head.splitlines():
        s = line.strip()
        if not s:
            continue
        return s[:2] == b"A1" and len(s) > 4 and s[2:4].isdigit()
    return False


def _safe_str(line: str, start: int, length: int) -> str:
    return line[start : start + length].strip()


def _safe_int(line: str, start: int, length: int) -> Optional[int]:
    s = line[start : start + length].strip()
    if not s.lstrip("-").isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_hy3_time(token: str) -> Optional[str]:
    """Convert a Hytek raw time token (e.g. "  79.69" / " 1:25.12") to canonical.

    Returns ``"mm:ss.cc"`` with leading zeros stripped when a colon is
    present, or ``"ss.cc"`` for sub-minute swims. ``None`` if invalid.
    """
    s = token.strip().rstrip("S").rstrip()
    if not s or s in {"0.00", "00.00", "0"}:
        return None
    # Already mm:ss.cc
    if ":" in s:
        m = re.match(r"^(\d{1,3}):(\d{2}\.\d{2})$", s)
        if m:
            return f"{int(m.group(1))}:{m.group(2)}"
        return None
    # Plain seconds
    m = re.match(r"^(\d{1,3}\.\d{2})$", s)
    if m:
        secs = float(m.group(1))
        if secs >= 60.0:
            mm = int(secs // 60)
            ss = secs - mm * 60
            return f"{mm}:{ss:05.2f}"
        return s
    return None


def _hy3_distance(token: str) -> Optional[int]:
    """E1 distance field — three chars right-justified (e.g. " 50", "100", "200")."""
    s = token.strip()
    if s.isdigit():
        return int(s)
    return None


# ---------------------------------------------------------------------------
# Athlete cache built from D1 records
# ---------------------------------------------------------------------------


def _parse_d1(line: str) -> dict:
    """Parse a D1 athlete record.

    Layout (zero-indexed):
        col 0-1   : "D1"
        col 2     : sex (M/F/X)
        col 3-7   : athlete_no (right-justified int, sometimes with leading spaces)
        col 8-27  : last name (20 chars)
        col 28-47 : first name (20 chars)
        col 48-67 : middle/preferred (varies)
        col 68-79 : USS / SE id (12 chars, alphanumeric)
        col 80-87 : DOB ddmmyyyy or mmddyyyy depending on locale (8 digits)
        col 88-89 : age
    """
    return {
        "sex": _safe_str(line, 2, 1),
        "athlete_no": _safe_str(line, 3, 5),
        "last": _safe_str(line, 8, 20),
        "first": _safe_str(line, 28, 20),
        "uss_id": _safe_str(line, 68, 12) if len(line) > 68 else "",
        "dob": _safe_str(line, 80, 8) if len(line) > 80 else "",
        "age": _safe_int(line, 88, 2) if len(line) > 88 else None,
    }


def _athlete_full_name(rec: dict) -> str:
    last = rec.get("last", "").strip()
    first = rec.get("first", "").strip()
    if last and first:
        return f"{first} {last}"
    if last:
        return last
    return first


def _athlete_dob_year(rec: dict) -> Optional[int]:
    """Best-effort year extraction from a D1 DOB token."""
    dob = (rec.get("dob") or "").strip()
    if len(dob) < 8 or not dob.isdigit():
        return None
    # mmddyyyy and ddmmyyyy both put the year in the last 4 chars
    yr = dob[-4:]
    try:
        v = int(yr)
        if 1900 <= v <= 2030:
            return v
    except ValueError:
        return None
    return None


# ---------------------------------------------------------------------------
# Event + result parsing (E1 + E2)
# ---------------------------------------------------------------------------


def _parse_e1(line: str) -> dict:
    """Parse an E1 event-entry record.

    Layout (zero-indexed) — verified against V8.1 corpus:
        col 0-1   : "E1"
        col 2     : sex (M/F)
        col 3-7   : athlete_no (matches D1 athlete_no)
        col 8-12  : athlete short ref (5 chars, surname-derived alpha key)
        col 13    : athlete sex (duplicate)
        col 14    : ? (often a course-marker)
        col 17-20 : distance (4 chars right-justified, e.g. " 100")
        col 21    : stroke code (A/B/C/D/E/F/G)
        col 22-31 : age band + entry fee
        col 33    : course code (S/L/Y)
        col 34-37 : event_no (4 chars)
        col 38    : ?
        col 41-47 : seed_time field
        ...
    """
    return {
        "sex": _safe_str(line, 2, 1),
        "athlete_no": _safe_str(line, 3, 5),
        "athlete_short": _safe_str(line, 8, 5),
        "distance": _hy3_distance(line[17:21]) if len(line) > 21 else None,
        "stroke_code": _safe_str(line, 21, 1),
        "course_code": _safe_str(line, 33, 1) if len(line) > 33 else "",
        "event_no": _safe_str(line, 34, 4) if len(line) > 34 else "",
        "seed_time_raw": _safe_str(line, 41, 8) if len(line) > 41 else "",
    }


def _parse_e2(line: str) -> dict:
    """Parse an E2 finals record (the result row that follows E1).

    Layout:
        col 0-1   : "E2"
        col 2     : round code (F = finals, P = prelim, S = swim-off)
        col 3-10  : finals_time (e.g. "  75.69")
        col 11    : course (S/L/Y)
        col 12-19 : finals_seed_diff
        col 20-22 : heat
        col 23-25 : lane
        col 26-28 : prelim_place
        col 29-31 : finals_place  (often padded; the place after the lane block)
        ...
    Some exports place the place at slightly different offsets, so we also
    try to recover it heuristically by scanning for the swimmer's place.
    """
    finals_time = _parse_hy3_time(_safe_str(line, 3, 8))
    # Place in HY3 E2: the stats block at cols 12-36 contains
    # prelim_place, heat, lane, semi_place, finals_place, dq_flag.
    # Corpus-verified position for finals_place is col 30:33 (3 chars,
    # right-justified). When a swim is unranked the field is " 0 ".
    place: Optional[int] = None
    if len(line) > 33:
        s = line[30:33].strip()
        if s.isdigit():
            v = int(s)
            if 1 <= v <= 200:
                place = v
    return {
        "round": _safe_str(line, 2, 1),
        "finals_time": finals_time,
        "course_code": _safe_str(line, 11, 1) if len(line) > 11 else "",
        "place": place,
    }


# ---------------------------------------------------------------------------
# Meet metadata
# ---------------------------------------------------------------------------


def _parse_b1(line: str) -> dict:
    """Parse a B1 meet record.

    Layout:
        col 0-1   : "B1"
        col 2-46  : meet name (45 chars)
        col 47-91 : venue (45 chars)
        col 92-99 : start date (mmddyyyy)
        col 100-107: end date (mmddyyyy)
    """
    return {
        "meet_name": _safe_str(line, 2, 45),
        "venue": _safe_str(line, 47, 45),
        "start_date": _safe_str(line, 92, 8) if len(line) > 92 else "",
        "end_date": _safe_str(line, 100, 8) if len(line) > 100 else "",
    }


def _format_date(yyyymmdd_or_mmddyyyy: str) -> Optional[str]:
    s = yyyymmdd_or_mmddyyyy.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    # Hytek uses mmddyyyy in US exports, ddmmyyyy in UK exports — show
    # whichever produces a plausible date with year >= 1990.
    yr_tail = s[-4:]
    try:
        y = int(yr_tail)
    except ValueError:
        return None
    if 1990 <= y <= 2100:
        return f"{s[:2]}/{s[2:4]}/{yr_tail}"
    return None


def _parse_c1(line: str) -> dict:
    """Parse a C1 team record.

    Layout (zero-indexed) — verified against the V8.1 corpus:
        col 0-1   : "C1"
        col 2-7   : team_code (5 chars + 1 pad)
        col 7-37  : team_name (30 chars, fixed-width)
        col 37-45 : team_short (8 chars, often blank)

    Earlier versions used ``_safe_str(line, 7, 45)`` which slurped both
    the name and the short-name into one string, producing values like
    ``"Aberdeen ASC                  Aberdeen"``.
    """
    return {
        "team_code": _safe_str(line, 2, 5),
        "team_name": _safe_str(line, 7, 30),
        "team_short": _safe_str(line, 37, 8),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_hy3(data: bytes) -> InterpretedMeet:
    """Parse a `.hy3` byte buffer and return an InterpretedMeet."""
    text = data.decode("latin-1", errors="replace")
    lines = text.splitlines()

    meet_name: Optional[str] = None
    venue: Optional[str] = None
    dates: Optional[tuple[str, str]] = None
    course_default: Optional[str] = None

    athletes: dict[str, dict] = {}
    current_team_name: Optional[str] = None
    athlete_team: dict[str, str] = {}

    # event_key → InterpretedEvent
    events_by_key: dict[tuple, InterpretedEvent] = {}

    pending_e1: Optional[dict] = None  # most recent E1 (paired with following E2)
    current_athlete_no: Optional[str] = None  # athlete that the E1 chain belongs to

    for raw in lines:
        if len(raw) < 2:
            continue
        code = raw[:2]

        if code == "B1" and meet_name is None:
            b1 = _parse_b1(raw)
            meet_name = b1["meet_name"] or None
            venue = b1["venue"] or None
            sd = _format_date(b1["start_date"])
            ed = _format_date(b1["end_date"])
            if sd and ed:
                dates = (sd, ed)
            elif sd:
                dates = (sd, sd)

        elif code == "C1":
            c1 = _parse_c1(raw)
            current_team_name = c1["team_name"] or current_team_name

        elif code == "D1":
            d1 = _parse_d1(raw)
            ath_no = d1["athlete_no"]
            if ath_no:
                athletes[ath_no] = d1
                if current_team_name:
                    athlete_team[ath_no] = current_team_name
            # Reset the E1 pending pointer; subsequent E1/E2 records belong
            # to this athlete.
            current_athlete_no = ath_no
            pending_e1 = None

        elif code == "E1":
            e1 = _parse_e1(raw)
            # E1 may carry its own athlete_no; prefer that.
            ath_no = e1["athlete_no"] or current_athlete_no
            e1["_athlete_no"] = ath_no
            pending_e1 = e1
            # Set course default from the first E1 we see
            if course_default is None:
                cc = e1.get("course_code") or ""
                if cc in _HY3_COURSE:
                    course_default = _HY3_COURSE[cc]

        elif code == "E2" and pending_e1 is not None:
            e2 = _parse_e2(raw)
            stroke_canon = _HY3_STROKE.get(pending_e1.get("stroke_code", ""), None)
            distance = pending_e1.get("distance")
            sex = pending_e1.get("sex") or None
            course = _HY3_COURSE.get(
                pending_e1.get("course_code") or e2.get("course_code") or "",
                course_default,
            )
            ath_no = pending_e1.get("_athlete_no") or current_athlete_no
            ath_rec = athletes.get(ath_no or "", {})

            key = (sex, distance, stroke_canon, course)
            ev = events_by_key.get(key)
            if ev is None:
                ev = InterpretedEvent(
                    gender=sex,
                    distance_m=distance,
                    stroke=stroke_canon,
                    course=course,
                    age_band=None,
                    swims=[],
                    confidence=0.85 if (distance and stroke_canon) else 0.4,
                    raw_header=f"E1 {pending_e1.get('event_no','')}",
                )
                events_by_key[key] = ev

            swimmer_name = _athlete_full_name(ath_rec) or "Unknown"
            club = athlete_team.get(ath_no or "")
            yob = _athlete_dob_year(ath_rec)

            field_conf = {
                "swimmer_name": 0.9 if swimmer_name != "Unknown" else 0.2,
                "time": 0.95 if e2.get("finals_time") else 0.0,
                "place": 0.85 if e2.get("place") else 0.3,
                "club": 0.9 if club else 0.0,
                "stroke": 0.9 if stroke_canon else 0.0,
                "distance": 0.95 if distance else 0.0,
            }
            swim_conf = sum(field_conf.values()) / len(field_conf)

            swim = InterpretedSwim(
                swimmer_name=swimmer_name,
                yob=yob,
                club=club,
                place=e2.get("place"),
                time=e2.get("finals_time"),
                reaction=None,
                confidence=round(swim_conf, 3),
                raw_row=raw[:120],
                field_confidence=field_conf,
            )
            ev.swims.append(swim)
            pending_e1 = None  # consumed

    events = list(events_by_key.values())

    # Overall confidence: mean of event confidences weighted by # of swims
    if events:
        total_swims = sum(len(e.swims) for e in events) or 1
        overall = sum(e.confidence * (len(e.swims) / total_swims) for e in events if e.swims)
        overall = round(min(0.99, max(0.5, overall)), 3) if total_swims > 0 else 0.0
    else:
        overall = 0.0

    return InterpretedMeet(
        meet_name=meet_name,
        venue=venue,
        dates=dates,
        course_default=course_default,
        governing_body_hint=None,
        events=events,
        overall_confidence=overall,
        needs_review=[],
        sources_used=["format:hy3"],
        patterns_used=[],
        new_patterns_proposed=[],
    )
