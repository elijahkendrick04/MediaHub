"""
sdif_parser.py — Parse Hy-Tek SDIF (`.cl2`/`.sd3`) files into InterpretedMeet.

SDIF (Swim Data Interchange Format) is the public US-Swimming-defined
standard that Hy-Tek `.cl2` exports follow. Records are 162 columns
wide; the first 2 columns are a record-type code.

Records of interest (zero-indexed column ranges):

* ``A0`` — File description / system header (program, version)
* ``B1`` — Meet info:
    - col 11-58  meet name (47 chars)
    - col 58-93  meet address1 (35 chars)
    - col 93-128 meet address2 (35 chars)
    - col 128-148 city (20 chars), state(2), pcode(10), country(3)
    - col 148-156 start date (mmddyyyy)
    - col 156-164 end date (mmddyyyy)
* ``C1`` — Team info:
    - col 11-13  team code (LSC + suffix)
    - col 15-45  team name (30 chars)
* ``D0`` — Individual event / result:
    - col 11-39  swimmer name "Last, First M" (28 chars)
    - col 40-51  USS / SE id (12 chars)
    - col 52     swim attached code (A=Attached, U=Unattached)
    - col 56-57  swimmer age
    - col 58     sex (M/F)
    - col 59-61  event sex code
    - col 62-66  distance (5 digits, right-justified)
    - col 66     stroke code (1=Free 2=Back 3=Breast 4=Fly 5=IM 6=FreeRelay 7=MedleyRelay)
    - col 67-71  event number
    - col 71-72  event age range (low age, 2 chars)
    - col 73-74  event age range (high age, 2 chars)
    - col 75-83  date of swim (mmddyyyy)
    - col 83-91  seed time (8 chars: " m:ss.cc" or "  ss.cc ")
    - col 91     seed course
    - col 94-102 prelim time (8 chars)
    - col 102    prelim course
    - col 110-118 finals time (8 chars)
    - col 118    finals course
    - col 124-126 finals heat
    - col 126-128 finals lane
    - col 130-133 finals place

Field positions verified against V8.1 corpus samples (Westhill, Elgin,
Garioch, Dyce). Different Hy-Tek versions can shift columns by ±1; we
parse defensively.
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

# SDIF stroke + course codes are loaded from
# data/ontology/hytek_codes.json so this module contains no swim
# vocabulary literals.
_ONTOLOGY = OntologyLoader()
_HY_CODES = _ONTOLOGY["hytek_codes"] or {}
_SDIF_STROKE: dict[str, str] = _HY_CODES.get("sdif_stroke_codes", {})
_SDIF_COURSE: dict[str, str] = _HY_CODES.get("hytek_course_codes", {})


def detect_sdif(data: bytes) -> bool:
    """True if *data* looks like SDIF (.cl2/.sd3)."""
    head = data[:200]
    # SDIF first record is "A0" (file description) or "A1"
    s = head.lstrip()
    if s[:2] in (b"A0", b"A1") and len(s) > 4:
        return True
    return False


def _safe_str(line: str, start: int, length: int) -> str:
    if start >= len(line):
        return ""
    return line[start:start + length].strip()


def _safe_int(line: str, start: int, length: int) -> Optional[int]:
    s = _safe_str(line, start, length)
    if not s.lstrip("-").isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_sdif_time(token: str) -> Optional[str]:
    """Parse an SDIF 8-char time field.

    Examples seen in corpus: ``"1:19.69 "`` ``" 36.71  "`` ``"  1:25.12"``.
    Returns canonical ``mm:ss.cc`` or ``ss.cc``; None if invalid/zero.
    """
    s = token.strip()
    if not s or s in {"0.00", "00.00", "0", ""}:
        return None
    # Strip trailing course-code letter if present (S/L/Y)
    if s and s[-1] in "SLYsly":
        s = s[:-1].strip()
    if ":" in s:
        m = re.match(r"^(\d{1,3}):(\d{2}\.\d{2})$", s)
        if m:
            return f"{int(m.group(1))}:{m.group(2)}"
        return None
    m = re.match(r"^(\d{1,3}\.\d{2})$", s)
    if m:
        return s
    return None


def _format_date(s: str) -> Optional[str]:
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    yr = s[-4:]
    try:
        y = int(yr)
    except ValueError:
        return None
    if 1990 <= y <= 2100:
        return f"{s[:2]}/{s[2:4]}/{yr}"
    return None


def _normalise_swimmer_name(s: str) -> str:
    """Convert "Last, First M" → "First Last"; preserve unicode case."""
    s = s.strip()
    if "," in s:
        last, first = s.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return s


def _parse_b1(line: str) -> dict:
    """Parse SDIF B1 meet record."""
    return {
        "meet_name": _safe_str(line, 11, 47),
        "venue": _safe_str(line, 58, 35) or _safe_str(line, 93, 35),
        "city": _safe_str(line, 128, 20),
        "start_date": _safe_str(line, 148, 8),
        "end_date": _safe_str(line, 156, 8),
    }


def _parse_c1(line: str) -> dict:
    """Parse SDIF C1 team record.

    cols 11-17 = team code (6 chars: LSC + suffix)
    cols 17-47 = team name (30 chars)
    """
    return {
        "team_code": _safe_str(line, 11, 6),
        "team_name": _safe_str(line, 17, 30),
    }


def _parse_d0(line: str) -> dict:
    """Parse a Hy-Tek SDIF / `.cl2` D0 individual-result record.

    Column positions verified on the V8.1 corpus. Hy-Tek's extended
    `.cl2` uses these offsets:
        col 11-39 : swimmer name "Last, First" (28 chars)
        col 38-50 : USS / SE id (12 chars)
        col 52    : attached flag (A/U)
        col 56-64 : DOB ddmmyyyy (8 chars)
        col 64-66 : age (2 digits)
        col 66    : event sex (M/F)
        col 67    : swimmer sex (M/F)
        col 67-71 : distance (4 chars right-justified, e.g. " 100")
        col 71    : stroke code (1=Free 2=Back 3=Breast 4=Fly 5=IM)
        col 72-75 : event_no (3 chars + 1 char age band letter)
        col 79-87 : date of swim mmddyyyy (8 chars)
        col 88-96 : seed time (8 chars + course)
        col 115-123: finals time (8 chars)
        col 123   : course code
        col 134-140: finals place (6 chars right-justified)
    """
    name_raw = _safe_str(line, 11, 28)
    swimmer_name = _normalise_swimmer_name(name_raw) if name_raw else ""

    # Distance: try the canonical 4-char field at col 67:71 first; fall
    # back to a few common variants for older / non-Hytek SDIFs.
    distance: Optional[int] = None
    for span in ((67, 4), (66, 4), (62, 5), (63, 4)):
        if span[0] + span[1] > len(line):
            continue
        s = line[span[0]:span[0] + span[1]].strip()
        if s.isdigit():
            v = int(s)
            if 25 <= v <= 1500:
                distance = v
                break

    # Stroke code lives one char after the distance.
    stroke_code = ""
    for col in (71, 70, 67):
        if col < len(line):
            ch = line[col]
            if ch in _SDIF_STROKE:
                stroke_code = ch
                break
    stroke = _SDIF_STROKE.get(stroke_code)

    # Sex: col 66 (event sex) and col 67 (swimmer sex). Use col 66 if
    # it's a valid letter, else fall back.
    sex: Optional[str] = None
    for col in (66, 67, 64, 65):
        if col < len(line):
            ch = line[col]
            if ch in ("M", "F", "X"):
                sex = ch
                break

    # Date of swim mmddyyyy
    date_swam = _format_date(_safe_str(line, 79, 8))

    # Times: corpus-verified positions.
    seed_time = _parse_sdif_time(line[88:96]) if len(line) > 96 else None
    finals_time = _parse_sdif_time(line[115:123]) if len(line) > 123 else None
    finals_course_raw = _safe_str(line, 123, 1) if len(line) > 123 else ""

    # Place at col 134:140 (6 chars right-justified)
    place: Optional[int] = None
    if len(line) > 140:
        s = line[134:140].strip()
        if s.isdigit():
            v = int(s)
            if 1 <= v <= 200:
                place = v

    age = _safe_int(line, 64, 2) or _safe_int(line, 56, 2)

    return {
        "swimmer_name": swimmer_name,
        "sex": sex,
        "age": age,
        "distance": distance,
        "stroke": stroke,
        "course": _SDIF_COURSE.get(finals_course_raw),
        "seed_time": seed_time,
        "prelim_time": None,
        "finals_time": finals_time,
        "place": place,
        "date_swam": date_swam,
    }


def parse_sdif(data: bytes) -> InterpretedMeet:
    """Parse a `.cl2` / `.sd3` byte buffer and return an InterpretedMeet."""
    text = data.decode("latin-1", errors="replace")
    lines = text.splitlines()

    meet_name: Optional[str] = None
    venue: Optional[str] = None
    dates: Optional[tuple[str, str]] = None
    course_default: Optional[str] = None

    current_team: Optional[str] = None
    events_by_key: dict[tuple, InterpretedEvent] = {}

    for raw in lines:
        if len(raw) < 3:
            continue
        code = raw[:2]

        if code == "B1" and meet_name is None:
            b1 = _parse_b1(raw)
            meet_name = b1["meet_name"] or None
            venue = b1["venue"] or b1["city"] or None
            sd = _format_date(b1["start_date"])
            ed = _format_date(b1["end_date"])
            if sd and ed:
                dates = (sd, ed)
            elif sd:
                dates = (sd, sd)

        elif code == "C1":
            c1 = _parse_c1(raw)
            if c1["team_name"]:
                current_team = c1["team_name"]

        elif code == "D0":
            d0 = _parse_d0(raw)
            sex = d0.get("sex")
            distance = d0.get("distance")
            stroke = d0.get("stroke")
            course = d0.get("course") or course_default
            if course and course_default is None:
                course_default = course

            key = (sex, distance, stroke, course)
            ev = events_by_key.get(key)
            if ev is None:
                ev = InterpretedEvent(
                    gender=sex,
                    distance_m=distance,
                    stroke=stroke,
                    course=course,
                    age_band=None,
                    swims=[],
                    confidence=0.85 if (distance and stroke) else 0.4,
                    raw_header=f"D0 {distance or '?'} {stroke or '?'}",
                )
                events_by_key[key] = ev

            time_value = d0.get("finals_time") or d0.get("prelim_time")

            yob: Optional[int] = None
            if d0.get("age") and d0.get("date_swam"):
                # date_swam format mm/dd/yyyy
                try:
                    swim_year = int(d0["date_swam"].split("/")[-1])
                    yob = swim_year - int(d0["age"])
                except (ValueError, IndexError):
                    yob = None

            field_conf = {
                "swimmer_name": 0.95 if d0.get("swimmer_name") else 0.0,
                "time": 0.95 if time_value else 0.0,
                "place": 0.85 if d0.get("place") else 0.3,
                "club": 0.9 if current_team else 0.0,
                "stroke": 0.95 if stroke else 0.0,
                "distance": 0.95 if distance else 0.0,
            }
            swim_conf = sum(field_conf.values()) / len(field_conf)

            swim = InterpretedSwim(
                swimmer_name=d0.get("swimmer_name") or "Unknown",
                yob=yob,
                club=current_team,
                place=d0.get("place"),
                time=time_value,
                reaction=None,
                confidence=round(swim_conf, 3),
                raw_row=raw[:120],
                field_confidence=field_conf,
            )
            ev.swims.append(swim)

    events = list(events_by_key.values())
    if events:
        total_swims = sum(len(e.swims) for e in events) or 1
        overall = sum(
            e.confidence * (len(e.swims) / total_swims)
            for e in events
            if e.swims
        )
        overall = round(min(0.99, max(0.5, overall)), 3)
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
        sources_used=["format:sdif"],
        patterns_used=[],
        new_patterns_proposed=[],
    )
