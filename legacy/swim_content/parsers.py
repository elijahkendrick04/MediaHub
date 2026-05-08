"""
Ingestion adapters. Each parser converts a source into an in-memory
list of dicts shaped like:

    {
        'swimmer_name': str,
        'gender': 'M'|'F'|None,
        'club': str|None,
        'event_code': str,           # canonical, see events.py
        'round': 'heat'|'final'|...,
        'place': int|None,
        'time_cs': int,              # required
        'entry_time_cs': int|None,
        'dq': bool,
    }

The parser MUST refuse to emit a row if event_code or time_cs cannot be set.
This is what stops bad data corrupting the canonical store.
"""

from __future__ import annotations
import csv
import io
import re
from pathlib import Path
from typing import Iterable, Iterator

from .events import canonical_event, parse_time_to_cs


# -------------------------------------------------------------------------
# CSV parser (the friendliest format — what we use for the prototype demo)
#
# Expected columns (case-insensitive, whitespace-tolerant):
#   Swimmer | Gender | Club | Event | Round | Place | Time | Entry Time
#
# Example row:
#   Sarah Jones, F, Swansea Uni, 100m Freestyle, Final, 1, 56.42, 57.10
# -------------------------------------------------------------------------

def parse_csv(text: str, course_hint: str = "LC") -> Iterator[dict]:
    reader = csv.DictReader(io.StringIO(text))
    field_map = {k.lower().strip(): k for k in (reader.fieldnames or [])}

    def get(row, *names):
        for n in names:
            if n in field_map:
                v = row[field_map[n]]
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
        return None

    for row in reader:
        name = get(row, "swimmer", "name", "athlete")
        if not name:
            continue
        gender = get(row, "gender", "sex")
        club = get(row, "club", "team")
        event_raw = get(row, "event")
        if not event_raw:
            continue
        event_code = canonical_event(event_raw, gender_hint=gender, course_hint=course_hint)
        if not event_code:
            continue
        time_cs = parse_time_to_cs(get(row, "time", "result", "final time"))
        if time_cs is None:
            # DQ/DNF rows are allowed but we mark dq
            dq_flag = (get(row, "time", "result") or "").upper() in ("DQ", "DNS", "DNF", "SCR")
            if not dq_flag:
                continue
            time_cs = 0
            dq = True
        else:
            dq = False
        entry_time_cs = parse_time_to_cs(get(row, "entry time", "entry", "seed"))
        place_raw = get(row, "place", "rank", "position")
        place = int(place_raw) if place_raw and place_raw.isdigit() else None
        rnd = (get(row, "round", "phase") or "timed_final").lower()
        if "final" in rnd and "semi" not in rnd:
            rnd = "final"
        elif "semi" in rnd:
            rnd = "semi"
        elif "heat" in rnd or "prelim" in rnd:
            rnd = "heat"
        else:
            rnd = "timed_final"

        yield {
            "swimmer_name": name,
            "gender": (gender or "").upper()[:1] if gender else None,
            "club": club,
            "event_code": event_code,
            "round": rnd,
            "place": place,
            "time_cs": time_cs,
            "entry_time_cs": entry_time_cs,
            "dq": dq,
        }


# -------------------------------------------------------------------------
# Hytek-style flat text parser (CL2-like / Meet Manager export-style)
#
# Many community result exports look like:
#   Event 12  Women 100 Freestyle
#   1  Jones, Sarah         20  Swansea Uni       57.10    56.42
#   2  Williams, Emma       21  Cardiff Uni       57.55    57.41
#
# This parser extracts events by header line, then rows by columnar text.
# It's intentionally permissive — if a row doesn't parse, skip silently.
# -------------------------------------------------------------------------

EVENT_HEADER_RE = re.compile(
    r"event\s*\d+\s+(?P<gender>women|men|girls|boys|mixed|female|male)\s+"
    r"(?P<distance>\d{2,4})\s*m?\s*"
    r"(?P<stroke>free(?:style)?|back(?:stroke)?|breast(?:stroke)?|fly|butterfly|im|individual\s+medley)",
    re.IGNORECASE,
)

ROW_RE = re.compile(
    r"^\s*(?P<place>\d+|---|DQ|DNS|DNF)\s+"
    r"(?P<name>[A-Za-z'\-\.,\s]+?)\s{2,}"
    r"(?:(?P<age>\d{1,3})\s+)?"
    r"(?P<club>[A-Za-z][A-Za-z0-9\.\s&'\-]+?)\s{2,}"
    r"(?P<seed>\d{0,2}:?\d{1,2}\.\d{1,2}|NT|---)\s+"
    r"(?P<final>\d{0,2}:?\d{1,2}\.\d{1,2}|DQ|DNF|DNS)\s*$"
)


def parse_hytek_text(text: str, course_hint: str = "LC") -> Iterator[dict]:
    current_event = None  # (gender, raw_event)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        h = EVENT_HEADER_RE.search(line)
        if h:
            current_event = (h.group("gender"), f"{h.group('distance')}m {h.group('stroke')}")
            continue
        if current_event is None:
            continue
        m = ROW_RE.match(raw_line)
        if not m:
            continue
        gender_raw, event_raw = current_event
        event_code = canonical_event(event_raw, gender_hint=gender_raw, course_hint=course_hint)
        if not event_code:
            continue
        place_str = m.group("place")
        place = int(place_str) if place_str.isdigit() else None
        final_str = m.group("final")
        if final_str.upper() in ("DQ", "DNF", "DNS"):
            time_cs, dq = 0, True
        else:
            tc = parse_time_to_cs(final_str)
            if tc is None:
                continue
            time_cs, dq = tc, False
        seed_str = m.group("seed")
        entry_cs = parse_time_to_cs(seed_str) if seed_str.upper() not in ("NT", "---") else None
        yield {
            "swimmer_name": m.group("name").strip().rstrip(","),
            "gender": "M" if gender_raw.lower().startswith(("m", "b")) else "F",
            "club": m.group("club").strip(),
            "event_code": event_code,
            "round": "timed_final",
            "place": place,
            "time_cs": time_cs,
            "entry_time_cs": entry_cs,
            "dq": dq,
        }


# -------------------------------------------------------------------------
# Public dispatcher
# -------------------------------------------------------------------------

def parse_any(content: bytes | str, filename: str, course_hint: str = "LC") -> list[dict]:
    """Top-level dispatcher. Returns a list (materialised for safety)."""
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="ignore")
    else:
        text = content

    name = (filename or "").lower()
    if name.endswith(".csv"):
        return list(parse_csv(text, course_hint=course_hint))
    if name.endswith(".txt") or name.endswith(".cl2") or name.endswith(".hy3"):
        return list(parse_hytek_text(text, course_hint=course_hint))
    # Heuristic fallback: looks like CSV?
    if "," in text.splitlines()[0] if text.splitlines() else False:
        try:
            return list(parse_csv(text, course_hint=course_hint))
        except Exception:
            pass
    return list(parse_hytek_text(text, course_hint=course_hint))
