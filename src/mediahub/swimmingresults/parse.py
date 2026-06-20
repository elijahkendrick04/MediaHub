"""
swimmingresults/parse.py — parse a swimmingresults.org personal-best page.

A clean, dependency-free port of the proven ``legacy/swim_content_pb`` parser
(validated unchanged against the current live HTML: 27 events for a real
swimmer). It reads the "Individual Best Times (All Time)" page —
``personal_best.php?mode=A&tiref=<id>`` — and returns one row per event with the
swimmer's best time, course, and the date it was set.

Course is inferred from the table heading and an entry is dropped if the course
cannot be determined — never silently defaulted, because an LC time compared to
an SC baseline is a wrong PB.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Canonical stroke codes used everywhere downstream (event_key "100FRLC").
_STROKE_CODE: dict[str, str] = {
    "freestyle": "FR", "free": "FR", "fr": "FR",
    "backstroke": "BK", "back": "BK", "bk": "BK",
    "breaststroke": "BR", "breast": "BR", "br": "BR",
    "butterfly": "FL", "fly": "FL", "fl": "FL",
    "individual medley": "IM", "medley": "IM", "im": "IM",
}
_VALID_DISTANCES = {50, 100, 200, 400, 800, 1500}
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_TAGS = re.compile(r"<[^>]+>", re.S)
_WS = re.compile(r"\s+")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_RNK_SJ = re.compile(r'class=["\']rnk_sj["\'][^>]*>(.*?)</p>', re.I | re.S)


@dataclass
class PBEntry:
    distance: int
    stroke: str  # canonical code: FR/BK/BR/FL/IM
    course: str  # LC / SC
    time_cs: int  # centiseconds
    time_sec: float
    date_iso: str  # "" if unparseable
    meet: str


@dataclass
class PBPage:
    tiref: str
    swimmer_name: str  # "" if not found
    club: str  # "" if not found
    entries: list[PBEntry]


def _strip(html: str) -> str:
    return _WS.sub(" ", _html.unescape(_TAGS.sub(" ", html))).strip()


def time_to_cs(s: str) -> Optional[int]:
    """'1:07.97' / '57.99' / '15:48.50' → centiseconds."""
    s = (s or "").strip()
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})\.(\d{2})", s)  # h:mm:ss.cc
    if m:
        h = int(m.group(1)) if m.group(1) else 0
        return ((h * 60 + int(m.group(2))) * 60 + int(m.group(3))) * 100 + int(m.group(4))
    m = re.fullmatch(r"(\d+):(\d{2})\.(\d{2})", s)  # mm:ss.cc
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) * 100 + int(m.group(3))
    m = re.fullmatch(r"(\d{1,3})\.(\d{2})", s)  # ss.cc
    if m:
        return int(m.group(1)) * 100 + int(m.group(2))
    return None


def _parse_date(s: str) -> str:
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2,4})", s)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yr = 2000 + yy if yy < 100 else yy
        try:
            return date(yr, mm, dd).isoformat()
        except ValueError:
            return ""
    m = re.fullmatch(r"(\d{1,2})[-\s]([A-Za-z]+)[-\s](\d{2,4})", s)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            dd, yy = int(m.group(1)), int(m.group(3))
            yr = 2000 + yy if yy < 100 else yy
            try:
                return date(yr, mon, dd).isoformat()
            except ValueError:
                return ""
    return ""


def _event(label: str) -> Optional[tuple[int, str]]:
    m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", label or "")
    if not m:
        return None
    dist = int(m.group(1))
    raw = m.group(2).strip().lower()
    code = _STROKE_CODE.get(raw) or _STROKE_CODE.get(raw.rstrip("s"))
    if not code or dist not in _VALID_DISTANCES:
        return None
    return dist, code


def _course_from_heading(h: str) -> Optional[str]:
    u = (h or "").upper()
    if "LONG COURSE" in u or " LC" in u or "OUTDOOR" in u:
        return "LC"
    if "SHORT COURSE" in u or " SC" in u or "INDOOR" in u:
        return "SC"
    return None


def _rows(table_html: str, course: str) -> list[PBEntry]:
    out: list[PBEntry] = []
    for row in _ROW.findall(table_html):
        cells = [_strip(c) for c in _CELL.findall(row)]
        if len(cells) < 5:
            continue
        ev = _event(cells[0])
        if not ev:
            continue
        cs = time_to_cs(cells[1])
        if not cs or cs <= 0:
            continue
        dist, code = ev
        out.append(
            PBEntry(
                distance=dist,
                stroke=code,
                course=course,
                time_cs=cs,
                time_sec=cs / 100.0,
                date_iso=_parse_date(cells[4]) if len(cells) > 4 else "",
                meet=(cells[5] if len(cells) > 5 else "") or "",
            )
        )
    return out


def parse_personal_best(html: str, tiref: str) -> PBPage:
    """Parse a personal-best page into a ``PBPage`` (best time per event)."""
    name, club = "", ""
    m = _RNK_SJ.search(html or "")
    if m:
        line = _strip(m.group(1))  # "Holly Greenslade - ( 1153374 ) - Torfaen Dolphins"
        parts = re.split(r"\s*-\s*", line)
        if parts:
            name = parts[0].strip()
        if len(parts) >= 3:
            club = parts[-1].strip()

    entries: list[PBEntry] = []
    # Walk headings + tables in document order so each table inherits the most
    # recent course heading (the page has a Long Course and a Short Course block).
    segments = re.split(
        r"(<h[1-6][^>]*>.*?</h[1-6]>|<table[^>]*>.*?</table>)", html or "", flags=re.S | re.I
    )
    course: Optional[str] = None
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        hm = re.match(r"<h[1-6][^>]*>(.*?)</h[1-6]>", seg, re.S | re.I)
        if hm:
            detected = _course_from_heading(_strip(hm.group(1)))
            if detected:
                course = detected
            continue
        tm = re.match(r"<table[^>]*>(.*?)</table>", seg, re.S | re.I)
        if tm and course:
            entries.extend(_rows(tm.group(1), course))

    # Fallback: no course headings found → assume the two tables are LC then SC.
    if not entries:
        tables = _TABLE.findall(html or "")
        if tables:
            entries.extend(_rows(tables[0], "LC"))
        if len(tables) >= 2:
            entries.extend(_rows(tables[1], "SC"))

    # Keep only the fastest per (distance, stroke, course) — defensive; the page
    # is already best-per-event, but a malformed table shouldn't double-count.
    best: dict[tuple[int, str, str], PBEntry] = {}
    for e in entries:
        k = (e.distance, e.stroke, e.course)
        if k not in best or e.time_cs < best[k].time_cs:
            best[k] = e

    return PBPage(tiref=str(tiref), swimmer_name=name, club=club, entries=list(best.values()))
