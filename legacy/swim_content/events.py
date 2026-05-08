"""
Event code normalisation and time parsing.

A canonical event_code looks like: M_50_FR_LC
                                    | |  |  |
                                    | |  |  course (LC=50m, SC=25m)
                                    | |  stroke (FR/BK/BR/FL/IM)
                                    | distance (m)
                                    gender (M/F/X)

This module is the single source of truth for what a 50m freestyle LC means,
across all parsers. If the parser can't produce a canonical event_code, the
result must NOT enter the system.
"""

from __future__ import annotations
import re
from typing import Optional

STROKES = {
    "free": "FR", "freestyle": "FR", "fr": "FR",
    "back": "BK", "backstroke": "BK", "bk": "BK",
    "breast": "BR", "breaststroke": "BR", "br": "BR",
    "fly": "FL", "butterfly": "FL", "fl": "FL",
    "im": "IM", "medley": "IM", "individual medley": "IM",
}

GENDERS = {
    "m": "M", "male": "M", "men": "M", "mens": "M", "boys": "M", "boy": "M",
    "f": "F", "female": "F", "women": "F", "womens": "F", "girls": "F", "girl": "F",
    "x": "X", "mixed": "X",
}

COURSES = {
    "lc": "LC", "lcm": "LC", "long": "LC", "50m": "LC", "long course": "LC",
    "sc": "SC", "scm": "SC", "short": "SC", "25m": "SC", "short course": "SC",
}

EVENT_RE = re.compile(
    r"(?P<gender>m|f|men|women|mens|womens|male|female|boys|girls|mixed)?\s*"
    r"(?P<distance>\d{2,4})\s*m?\s*"
    r"(?P<stroke>free(?:style)?|back(?:stroke)?|breast(?:stroke)?|fly|butterfly|im|medley|individual\s+medley|fr|bk|br|fl)",
    re.IGNORECASE,
)


def canonical_event(raw: str, gender_hint: Optional[str] = None,
                    course_hint: Optional[str] = None) -> Optional[str]:
    """Return canonical event code, or None if unparseable."""
    if not raw:
        return None
    s = raw.lower().strip()

    # Course
    course = None
    for k, v in COURSES.items():
        if k in s:
            course = v
            break
    if course is None and course_hint:
        course = COURSES.get(course_hint.lower(), course_hint.upper() if course_hint.upper() in ("LC", "SC") else None)

    m = EVENT_RE.search(s)
    if not m:
        return None
    distance = int(m.group("distance"))
    stroke = STROKES.get(m.group("stroke").lower().replace(" ", ""))
    if stroke is None:
        # try without trailing 'stroke' etc.
        for k, v in STROKES.items():
            if k in m.group("stroke").lower():
                stroke = v
                break
    if stroke is None:
        return None

    gender = None
    if m.group("gender"):
        gender = GENDERS.get(m.group("gender").lower().replace(" ", ""))
    if gender is None and gender_hint:
        gender = GENDERS.get(gender_hint.lower())
    if gender is None:
        gender = "X"

    if course is None:
        course = "LC"  # default; should be overridden by meet metadata

    return f"{gender}_{distance}_{stroke}_{course}"


def parse_time_to_cs(s: str) -> Optional[int]:
    """Parse '1:02.34' or '57.81' or '57.8' into centiseconds (int)."""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s.upper() in ("DQ", "DNS", "DNF", "NT", "NS", "SCR"):
        return None
    s = s.replace(",", ".")
    m = re.match(r"^(?:(\d+):)?(\d{1,2})\.(\d{1,2})$", s)
    if not m:
        m = re.match(r"^(?:(\d+):)?(\d{1,2})$", s)  # rare, no fraction
        if not m:
            return None
        mins = int(m.group(1) or 0)
        secs = int(m.group(2))
        return (mins * 60 + secs) * 100
    mins = int(m.group(1) or 0)
    secs = int(m.group(2))
    frac = m.group(3)
    if len(frac) == 1:
        frac_cs = int(frac) * 10
    else:
        frac_cs = int(frac)
    return (mins * 60 + secs) * 100 + frac_cs


def cs_to_str(cs: int) -> str:
    """Centiseconds -> '1:02.34' or '57.81'."""
    if cs is None:
        return ""
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def event_human(event_code: str) -> str:
    """M_50_FR_LC -> '50m Freestyle (LC)'"""
    try:
        g, d, s, c = event_code.split("_")
    except ValueError:
        return event_code
    stroke_name = {"FR": "Freestyle", "BK": "Backstroke", "BR": "Breaststroke",
                   "FL": "Butterfly", "IM": "Individual Medley"}.get(s, s)
    return f"{d}m {stroke_name} ({c})"
