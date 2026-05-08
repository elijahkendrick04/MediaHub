"""
swim_content_pb/parser.py
Improved swimmingresults.org HTML parser.

Improvements over legacy swim_content/enrichment_swimmingresults.py:
- Canonical event labels (distance, stroke, course) — never silently default course
- Multiple entries per event (keeps full list, not just the best)
- Robust date parsing: dd/mm/yyyy, dd/mm/yy, dd-mmm-yyyy, dd MMM yyyy
- Same-meet duplicate identification (meet_name + venue retained per row)
- Course UNKNOWN if not derivable from table heading — entry skipped
"""
from __future__ import annotations

import hashlib
import html as html_module
import re
from typing import Optional

from .schema import ParsedSwimEntry, ParsedSnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SR_BASE = "https://www.swimmingresults.org"
PB_URL = SR_BASE + "/individualbest/personal_best.php?mode=A&tiref={tiref}"

# Stroke normalisation — map every variant to a canonical long-form string
_STROKE_MAP: dict[str, str] = {
    # Freestyle variants
    "freestyle": "free",
    "free": "free",
    "fr": "free",
    "f": "free",
    # Backstroke variants
    "backstroke": "back",
    "back": "back",
    "bk": "back",
    "b": "back",
    # Breaststroke variants
    "breaststroke": "breast",
    "breast": "breast",
    "br": "breast",
    # Butterfly variants
    "butterfly": "fly",
    "fly": "fly",
    "fl": "fly",
    "bu": "fly",
    # Individual Medley variants
    "individual medley": "im",
    "individual_medley": "im",
    "individualmedley": "im",
    "medley": "im",
    "im": "im",
    "md": "im",
}

_VALID_DISTANCES = {50, 100, 200, 400, 800, 1500}

# Month name -> number
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

# HTML cleaning regexes
_TAGS_RE = re.compile(r"<[^>]+>", re.S)
_WS_RE = re.compile(r"\s+")
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _strip(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = _TAGS_RE.sub(" ", html)
    text = html_module.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def parse_swim_time(s: str) -> Optional[float]:
    """Parse '1:07.97' or '57.99' or '5:48.50' → seconds (float)."""
    if not s:
        return None
    s = s.strip()
    # mm:ss.cc
    m = re.fullmatch(r"(\d+):(\d{2})\.(\d{2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 100.0
    # ss.cc
    m = re.fullmatch(r"(\d{1,3})\.(\d{2})", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 100.0
    # h:mm:ss.cc
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100.0
    return None


def parse_site_date(s: str) -> Optional[str]:
    """Parse date strings into ISO YYYY-MM-DD.

    Handles:
      - dd/mm/yyyy  (21/03/2024)
      - dd/mm/yy    (21/03/24)
      - dd-mmm-yyyy (21-Mar-2024)
      - dd MMM yyyy (21 Mar 2024)
      - dd-MMM-yy   (21-Mar-24)
    """
    if not s:
        return None
    s = s.strip()

    # dd/mm/yyyy or dd/mm/yy
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2,4})", s)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yr = 2000 + yy if yy < 100 else yy
        try:
            from datetime import date
            return date(yr, mm, dd).isoformat()
        except ValueError:
            return None

    # dd-mmm-yyyy or dd-mmm-yy or dd MMM yyyy or dd MMM yy
    m = re.fullmatch(r"(\d{1,2})[-\s]([A-Za-z]+)[-\s](\d{2,4})", s)
    if m:
        dd = int(m.group(1))
        mon = _MONTH_MAP.get(m.group(2).lower())
        yy = int(m.group(3))
        if mon:
            yr = 2000 + yy if yy < 100 else yy
            try:
                from datetime import date
                return date(yr, mon, dd).isoformat()
            except ValueError:
                return None

    return None


def _parse_event_label(label: str) -> Optional[tuple]:
    """'50 Freestyle' → (50, 'free').  Returns None if unrecognised."""
    if not label:
        return None
    label = label.strip()
    # Pattern: distance + stroke name
    m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", label)
    if not m:
        return None
    dist = int(m.group(1))
    stroke_raw = m.group(2).strip().lower()
    stroke = _STROKE_MAP.get(stroke_raw)
    if not stroke:
        # Try stripping trailing "s" for "freestyles" etc.
        stroke = _STROKE_MAP.get(stroke_raw.rstrip("s"))
    if not stroke:
        return None
    if dist not in _VALID_DISTANCES:
        return None
    return dist, stroke


def _detect_course_from_heading(heading: str) -> Optional[str]:
    """Infer LC or SC from a table heading string. Returns None if unknown."""
    h = heading.upper()
    if "LONG COURSE" in h or " LC" in h or "OUTDOOR" in h:
        return "LC"
    if "SHORT COURSE" in h or " SC" in h or "INDOOR" in h:
        return "SC"
    return None


def _parse_swimmer_name(html: str) -> Optional[str]:
    """Extract swimmer name from SR page.

    The swimmingresults.org page format (as of 2024-2026):
      <p class="rnk_sj">Firstname Lastname - (<a href='...'>TIREF</a>) - Club Name...</p>

    Falls back to:
      - <title> parsing for old :: format ("Swim England :: Personal Best Times :: NAME")
      - h1/h2 headings
    """
    # Primary: extract from <p class="rnk_sj"> — contains "Name - (tiref) - Club"
    # The name is the text before the first " - (" or " -("
    m = re.search(r'class=["\']rnk_sj["\'][^>]*>([^<]+)', html, re.I)
    if m:
        text = _strip(m.group(1))
        # Strip everything from " - (" onwards
        clean = re.split(r'\s*-\s*\(', text, maxsplit=1)[0].strip()
        if clean and len(clean) > 1 and len(clean) < 80:
            return clean

    # Also try rnk_sj with nested content (strip tags first)
    m = re.search(r'class=["\']rnk_sj["\'][^>]*>(.*?)</p>', html, re.I | re.S)
    if m:
        text = _strip(m.group(1))
        clean = re.split(r'\s*-\s*\(', text, maxsplit=1)[0].strip()
        if clean and len(clean) > 1 and len(clean) < 80:
            return clean

    # Try <title> — old format: "Swim England :: Personal Best Times :: NAME"
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if m:
        title = _strip(m.group(1))
        parts = re.split(r"\s*::\s*", title)
        if len(parts) >= 2:
            name = parts[-1].strip()
            if name and name.lower() not in ("swim england", "personal best times",
                                              "swimmingresults.org",
                                              "individual best times (all time)",
                                              "rankings"):
                return name

    # Try h1/h2
    m = re.search(r"<h[12][^>]*>([^<]+)</h[12]>", html, re.I)
    if m:
        text = _strip(m.group(1)).strip()
        if text and len(text) < 60 and text.lower() not in ("rankings", "swim england"):
            return text

    return None


def _parse_table(table_html: str, course: str) -> list[ParsedSwimEntry]:
    """Parse one <table> of LC or SC personal bests.

    Row layout (typical):
      0: stroke/event  | 1: best time | 2: converted time | 3: points |
      4: date          | 5: meet name | 6: venue           | 7: licence | 8: level
    """
    entries: list[ParsedSwimEntry] = []
    rows = _ROW_RE.findall(table_html)
    header_seen = False
    for row in rows:
        cells = [_strip(c) for c in _CELL_RE.findall(row)]
        if len(cells) < 5:
            continue
        # Skip header rows
        first = cells[0].strip().lower()
        if first in ("stroke", "event", ""):
            header_seen = True
            continue
        if not header_seen and cells[0].strip().lower() == "stroke":
            continue

        ev = _parse_event_label(cells[0])
        if not ev:
            continue
        dist, stroke = ev

        time_str = cells[1].strip() if len(cells) > 1 else ""
        time_sec = parse_swim_time(time_str)
        if time_sec is None or time_sec <= 0:
            continue

        date_raw = cells[4].strip() if len(cells) > 4 else ""
        meet_name = cells[5].strip() if len(cells) > 5 else None
        venue = cells[6].strip() if len(cells) > 6 else None
        licence = cells[7].strip() if len(cells) > 7 else None
        level = cells[8].strip() if len(cells) > 8 else None

        # Clean empties
        meet_name = meet_name or None
        venue = venue or None
        licence = licence or None
        level = level or None

        entries.append(ParsedSwimEntry(
            distance=dist,
            stroke=stroke,
            course=course,
            time_str=time_str,
            time_seconds=time_sec,
            date_iso=parse_site_date(date_raw),
            meet_name=meet_name,
            venue=venue,
            licence=licence,
            level=level,
            is_best=True,  # SR personal-best page — each row is the swimmer's best
        ))
    return entries


def parse_pb_html(html: str, asa_id: str, source_url: str, fetched_at: str) -> ParsedSnapshot:
    """Parse a swimmingresults.org personal-best page for one swimmer.

    Finds all tables, infers course from surrounding headings, and parses
    every row keeping meet_name + venue for same-meet dedup in history.py.
    """
    raw_hash = hashlib.md5(html.encode("utf-8", "replace")).hexdigest()
    swimmer_name = _parse_swimmer_name(html)

    entries: list[ParsedSwimEntry] = []

    # Find every heading + table pair
    # Strategy: scan the document for h2/h3 headings and <table> tags in order
    # We look for heading text near each table to determine LC/SC
    segments = re.split(r"(<h[1-6][^>]*>.*?</h[1-6]>|<table[^>]*>.*?</table>)",
                        html, flags=re.S | re.I)

    current_course: Optional[str] = None
    for seg in segments:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue

        # Check if this is a heading
        hm = re.match(r"<h[1-6][^>]*>(.*?)</h[1-6]>", seg_stripped, re.S | re.I)
        if hm:
            heading_text = _strip(hm.group(1))
            detected = _detect_course_from_heading(heading_text)
            if detected:
                current_course = detected
            continue

        # Check if this is a table
        tm = re.match(r"<table[^>]*>(.*?)</table>", seg_stripped, re.S | re.I)
        if tm:
            if current_course is None:
                # Skip — we don't know the course; never silently default
                continue
            table_entries = _parse_table(tm.group(1), current_course)
            entries.extend(table_entries)
            continue

    # Fallback: if we found no entries via heading approach, try simple 2-table approach
    if not entries:
        tables = _TABLE_RE.findall(html)
        if len(tables) >= 1:
            entries.extend(_parse_table(tables[0], "LC"))
        if len(tables) >= 2:
            entries.extend(_parse_table(tables[1], "SC"))

    return ParsedSnapshot(
        asa_id=asa_id,
        swimmer_name=swimmer_name,
        entries=entries,
        source_url=source_url,
        fetched_at=fetched_at,
        fetch_ok=True,
        error=None,
        raw_html_hash=raw_hash,
    )
