"""
Hytek Meet Manager HY3 (and CL2/SDIF) parser.

This is the *deterministic* path for ingesting a real meet. Every field
has a known column position. We treat the format as fixed-width records
keyed by a 2-char record type in columns 0-1.

Record types we use:
    A1  file header (start of file)
    B1  meet header  (name, dates, course)
    C1  club record  (4-letter code, full name, short name)
    D1  swimmer record (gender, ASA member id, last, first, age)
    E1  swim entry (event header) — distance, stroke, course, age band, seed
    E2  swim result (round, finals time, place, date)
    G1  splits

The HY3 file groups records hierarchically by club:
    C1 club
      D1 swimmer (belongs to most recent C1)
        E1+E2 swim (belongs to most recent D1)
          G1 splits (belongs to most recent E1+E2)

Column positions below were verified by character-level inspection of
the actual Swansea Aquatics May LC 2026 meet file. Do NOT change them
without re-verifying against a real file. See _meet_zip/.

CL2 (SDIF) has a similar structure but slightly different column layout
and is not yet supported here — the .cl2 sibling file is redundant when
.hy3 is present.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Iterator


# Stroke codes used in HY3 E1 records, single letter immediately after distance.
HY3_STROKE = {
    'A': 'FR',  # Freestyle
    'B': 'BK',  # Backstroke
    'C': 'BR',  # Breaststroke
    'D': 'FL',  # Butterfly
    'E': 'IM',  # Individual Medley
}


@dataclass
class ParsedClub:
    code: str           # 4-letter Hytek club id, e.g. 'SUNY'
    name: str           # 'Swansea University Swimming Cl' (truncated in HY3)
    short_name: str     # 'Swansea Uni'


@dataclass
class ParsedSwimmer:
    asa_id: str         # canonical Swim England member ID, e.g. '1382076'
    gender: str         # 'M' | 'F'
    last_name: str
    first_name: str
    age: int | None
    club_code: str      # references ParsedClub.code


@dataclass
class ParsedSwim:
    asa_id: str         # who swam
    club_code: str
    distance: int       # metres
    stroke: str         # FR/BK/BR/FL/IM
    course: str         # 'LC' | 'SC'
    gender: str
    age_at_meet: int | None
    age_band: str       # raw band code from HY3 (lo-hi), kept for diagnostics
    finals_time_cs: int | None  # None ⇒ DQ/NS/scratch
    seed_time_cs: int | None
    place: int | None
    round: str          # 'final' | 'timed_final' | 'heat' | 'semi'
    dq: bool
    swim_date: str | None       # ISO yyyy-mm-dd if available
    splits_cs: list[int] = field(default_factory=list)


@dataclass
class ParsedMeet:
    name: str
    venue: str | None
    course: str
    start_date: str | None
    end_date: str | None
    clubs: dict[str, ParsedClub]
    swimmers: dict[str, ParsedSwimmer]   # keyed by asa_id
    swims: list[ParsedSwim]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _hy3_time_to_cs(s: str) -> int | None:
    """HY3 stores times as decimal seconds, e.g. '   36.72', '  537.25'.
    Distances >= 100 m use formats like ' 533.20' (= 8:53.20). We treat
    every value as seconds.fraction. Returns None for blank/scratch/DQ."""
    s = (s or '').strip().rstrip('LS')   # strip trailing course suffix if present
    if not s or s.upper() in ('NS', 'NSL', 'DQ', 'DNS', 'DNF', 'SCR', '0.00'):
        return None
    try:
        secs = float(s)
    except ValueError:
        return None
    if secs <= 0:
        return None
    return round(secs * 100)


def _hy3_date_to_iso(s: str) -> str | None:
    """HY3 dates are 'mmddyyyy' fixed-width."""
    s = (s or '').strip()
    if len(s) != 8 or not s.isdigit():
        return None
    mm, dd, yyyy = s[0:2], s[2:4], s[4:8]
    if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31):
        return None
    return f"{yyyy}-{mm}-{dd}"


def _round_from_flag(flag: str) -> str:
    """E2 col 2 holds the round flag.
        F = final, P = prelim/heat, S = semi.
    Most community LC meets are timed-finals; we treat blank or unknown
    flags as 'timed_final'."""
    code = (flag or '').strip().upper()
    return {'F': 'final', 'P': 'heat', 'S': 'semi'}.get(code, 'timed_final')


def _safe_int(s: str) -> int | None:
    s = (s or '').strip()
    if not s or not s.lstrip('-').isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ----------------------------------------------------------------------
# Main parser
# ----------------------------------------------------------------------

def parse_hy3_text(text: str) -> ParsedMeet:
    """Parse a full HY3 file. The format is record-oriented and stateful
    (clubs scope swimmers; swimmers scope swims; swims scope splits)."""
    meet = ParsedMeet(
        name="(unknown)", venue=None, course="LC",
        start_date=None, end_date=None,
        clubs={}, swimmers={}, swims=[],
    )

    current_club: ParsedClub | None = None
    current_swimmer: ParsedSwimmer | None = None
    current_swim: ParsedSwim | None = None

    for line in text.splitlines():
        if len(line) < 2:
            continue
        rt = line[:2]

        if rt == 'B1':
            # Meet name + venue + dates. Only used for display.
            meet.name = line[2:47].strip() or meet.name
            meet.venue = line[47:92].strip() or None
            meet.start_date = _hy3_date_to_iso(line[92:100])
            meet.end_date = _hy3_date_to_iso(line[100:108])

        elif rt == 'C1':
            # Verified positions:
            #   [2:6]   4-char club code (e.g. 'SUNY'), col 6 is space
            #   [7:37]  club full name (30 chars, can be truncated)
            #   [37:53] short name (16 chars)
            code = line[2:6].strip()
            full = line[7:37].strip()
            short = line[37:53].strip()
            if not code:
                continue
            current_club = ParsedClub(code=code, name=full, short_name=short)
            meet.clubs[code] = current_club
            current_swimmer = None
            current_swim = None

        elif rt == 'D1' and current_club:
            # Verified positions:
            #   [2:3]    gender
            #   [4:8]    internal swimmer id within club (4-digit)
            #   [8:28]   last name (20)
            #   [28:48]  first name (20)
            #   [48:68]  preferred name (20)
            #   [69:84]  ASA member id (right-padded with spaces)
            #   [97:99]  age at meet
            gender = line[2:3].strip()
            last = line[8:28].strip()
            first = line[28:48].strip()
            asa_id = line[69:84].strip()
            age = _safe_int(line[97:99])

            if not asa_id or not last:
                # Unidentified swimmer — skip; we cannot attribute swims.
                current_swimmer = None
                current_swim = None
                continue

            sw = ParsedSwimmer(
                asa_id=asa_id, gender=gender, last_name=last,
                first_name=first, age=age, club_code=current_club.code,
            )
            # If a swimmer somehow appears under multiple clubs, keep first.
            meet.swimmers.setdefault(asa_id, sw)
            current_swimmer = sw
            current_swim = None

        elif rt == 'E1' and current_swimmer:
            # Verified positions:
            #   [2:3]    gender flag (M/F)
            #   [4:8]    swimmer id within club
            #   [8:13]   first 5 chars of surname (decorative)
            #   [13:15]  M+stroke flag pair
            #   [15:21]  distance, right-justified (e.g. '  1500', '   800', '   100', '    50')
            #   [21:22]  stroke letter (A/B/C/D/E)
            #   [22:28]  age band, e.g. ' 18109' = "18 to 109" (open mens)
            #   [43:51]  seed (entry) time, 8 chars right-justified, trailing 'L'/'S' suffix
            distance = _safe_int(line[15:21])
            stroke_letter = line[21:22]
            stroke = HY3_STROKE.get(stroke_letter)
            if distance is None or not stroke:
                current_swim = None
                continue
            seed_cs = _hy3_time_to_cs(line[43:51])
            age_band = line[22:28].strip()

            current_swim = ParsedSwim(
                asa_id=current_swimmer.asa_id,
                club_code=current_swimmer.club_code,
                distance=distance, stroke=stroke,
                course='LC',                   # provisional; overridden by E2
                gender=current_swimmer.gender,
                age_at_meet=current_swimmer.age,
                age_band=age_band,
                finals_time_cs=None,
                seed_time_cs=seed_cs,
                place=None, round='timed_final',
                dq=False, swim_date=None,
            )

        elif rt == 'E2' and current_swim:
            # Verified positions:
            #   [2:3]    round flag (F/P/S, blank => timed_final)
            #   [3:11]   finals time
            #   [11:12]  course flag for this time ('L' / 'S')
            #   [27:30]  overall place (3-char, right-justified) — verified
            #            against three Swansea Uni swims (place 4, 2, 1).
            #   8-digit date 'mmddyyyy' appears around col 87 — extract by regex.
            round_flag = line[2:3]
            current_swim.round = _round_from_flag(round_flag)

            time_str = line[3:11]
            course_flag = line[11:12].strip()
            if course_flag in ('L', 'S'):
                current_swim.course = 'LC' if course_flag == 'L' else 'SC'

            finals_cs = _hy3_time_to_cs(time_str)
            current_swim.finals_time_cs = finals_cs
            current_swim.dq = (finals_cs is None and 'DQ' in line[2:20].upper())

            place = _safe_int(line[27:30])
            if place and place > 0:
                current_swim.place = place

            # Date is at fixed offset [87:95] in mmddyyyy format.
            current_swim.swim_date = _hy3_date_to_iso(line[87:95])

            # Drop swim if no usable result.
            if current_swim.finals_time_cs is None and not current_swim.dq:
                current_swim = None
                continue
            meet.swims.append(current_swim)
            # Don't reset yet — splits (G1) follow

        elif rt == 'G1' and current_swim:
            # Splits — extract every 'd+.dd' float on the line. They alternate
            # cumulative-distance and cumulative-time pairs in HY3, but for
            # detection we only need the time series.
            nums = re.findall(r'(\d+\.\d{2})', line)
            current_swim.splits_cs = [round(float(n) * 100) for n in nums]

    return meet


def parse_hy3_file(path: str) -> ParsedMeet:
    with open(path, encoding='latin-1', errors='ignore') as f:
        return parse_hy3_text(f.read())
