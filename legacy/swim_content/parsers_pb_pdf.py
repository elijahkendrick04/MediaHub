"""
Parser for SPORTSYSTEMS Club Rankings PDFs ("Current Best Times").

Each PDF is a single gender + course combination, e.g.
    Current-Best-Times-Female.pdf       (LC, female)
    Current-Best-Times-Female-SC.pdf    (SC, female)
    Current-Best-Times-Male.pdf         (LC, male)
    Current-Best-Times-Male-SC.pdf      (SC, male)

Within a PDF, swimmers are listed for each event (e.g. "Female 50 Freestyle"),
sorted by FINA points (best first). Each row contains:

    rank | name | DoB | ranked club | ASA member id | date | meet | time | FINA pts

Critical notes:
1. The "Ranked" column is the swimmer's club AT THE TIME of that swim, not
   their current club. So an ASA ID may show "Penzance" for an old PB even
   though the swimmer is currently at Swansea Uni. For PB matching we key
   exclusively on ASA member ID; the ranked club is informational only.

2. We extract using positional word coordinates (pdfplumber) because plain
   text extraction can interleave the time and meet name columns (the time
   '00:27.12' renders as fragments '0','0',':27.12' due to Acrobat kerning).

3. We do not infer the swimmer's CURRENT club from this PDF. The current
   roster is established from the HY3 file at meet ingest time.

The output of import_pb_pdfs() is a PB store keyed by
    (asa_id, distance, stroke, course)
holding the swimmer's all-time best for that event.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


# Column anchors observed in SPORTSYSTEMS PDFs (page x-coordinate, points).
# We bucket each word into a column by nearest anchor with a small slack.
COL_ANCHORS = {
    'rank':   27,
    'name':   60,     # spans 55-145ish; we group all words in [40, 160)
    'dob':    168,
    'club':   220,    # spans 211-260
    'member': 268,
    'date':   317,
    'meet':   400,    # spans 360-490
    'time':   505,    # spans 500-540 (often fragmented)
    'fina':   547,
}

EVENT_HEADER_RE = re.compile(
    r'^(?P<gender>Female|Male)\s+(?P<dist>\d{2,4})\s+(?P<stroke>Freestyle|Backstroke|Breaststroke|Butterfly|Individual\s+Medley)$',
    re.IGNORECASE,
)

STROKE_NORMALIZE = {
    'freestyle': 'FR',
    'backstroke': 'BK',
    'breaststroke': 'BR',
    'butterfly': 'FL',
    'individual medley': 'IM',
}


@dataclass
class PBRow:
    asa_id: str
    name: str
    dob: str | None        # ISO yyyy-mm-dd
    distance: int
    stroke: str            # FR / BK / BR / FL / IM
    course: str            # 'LC' | 'SC'
    gender: str            # 'F' | 'M'
    time_cs: int           # PB time in centiseconds
    pb_date: str | None    # ISO yyyy-mm-dd
    pb_meet: str           # meet name (truncated as in PDF)
    pb_club: str           # the "Ranked" club at time of swim (informational)
    fina_points: int | None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _ddmmyyyy_to_iso(s: str) -> str | None:
    s = (s or '').strip()
    m = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', s)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{mm}-{dd}"


def _time_to_cs(s: str) -> int | None:
    """Parse '00:26.13' or '02:15.07' or '17:06.77' into centiseconds.
    Also accepts '26.13' or '01:26.13' if the minutes block is missing."""
    s = (s or '').strip()
    # Acrobat sometimes drops the leading '0:' so we accept several forms.
    m = re.fullmatch(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\.(\d{2})', s)
    if m:
        hh, mm, ss, cc = m.groups()
        total = (int(hh or 0) * 3600) + (int(mm) * 60) + int(ss)
        return total * 100 + int(cc)
    m = re.fullmatch(r'(\d{1,2}):(\d{2})\.(\d{2})', s)
    if m:
        mm, ss, cc = m.groups()
        return (int(mm) * 60 + int(ss)) * 100 + int(cc)
    m = re.fullmatch(r'(\d{1,2})\.(\d{2})', s)
    if m:
        ss, cc = m.groups()
        return int(ss) * 100 + int(cc)
    return None


def _bucket_column(x: float) -> str | None:
    """Return the column name for a given x-coordinate, or None if outside."""
    # Rough buckets; some columns span wide so we use ranges.
    if x < 45:
        return 'rank'
    if x < 160:
        return 'name'
    if x < 200:
        return 'dob'
    if x < 260:
        return 'club'
    if x < 310:
        return 'member'
    if x < 350:
        return 'date'
    if x < 495:
        return 'meet'
    if x < 540:
        return 'time'
    return 'fina'


# ----------------------------------------------------------------------
# Main parser
# ----------------------------------------------------------------------

def parse_pb_pdf(path: str | Path, course: str) -> list[PBRow]:
    """Parse a single PB PDF.

    Args:
        path:   path to the PDF
        course: 'LC' or 'SC' (the file naming tells us which)

    Returns one PBRow per (swimmer, event) — i.e. the best time only.
    Multiple PBs for the same (swimmer, event) inside one PDF should not
    happen, but if they do we keep the fastest.
    """
    rows: list[PBRow] = []
    current_event: tuple[int, str, str] | None = None  # (distance, stroke, gender)

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            # Group by row (y-coordinate, rounded to nearest 2 to absorb tiny jitter)
            by_y: dict[int, list[dict]] = {}
            for w in words:
                y = round(w['top'] / 2) * 2
                by_y.setdefault(y, []).append(w)

            for y in sorted(by_y):
                line_words = sorted(by_y[y], key=lambda w: w['x0'])
                line_text = ' '.join(w['text'] for w in line_words).strip()

                # Event header? "Female 50 Freestyle" / "Male 200 Individual Medley"
                m = EVENT_HEADER_RE.match(line_text)
                if m:
                    distance = int(m.group('dist'))
                    stroke = STROKE_NORMALIZE[m.group('stroke').lower().strip()]
                    gender = 'F' if m.group('gender').lower() == 'female' else 'M'
                    current_event = (distance, stroke, gender)
                    continue

                # Skip column headers, page footers, repeated banners.
                if not current_event:
                    continue
                if any(tok in line_text for tok in (
                    'Powered By SPORTSYSTEMS', 'Page', 'Member', 'FINA',
                    'All Time Best', 'Open Long Course', 'Open Short Course',
                )):
                    continue

                # Bucket words by column
                buckets: dict[str, list[str]] = {}
                for w in line_words:
                    col = _bucket_column(w['x0'])
                    if col:
                        buckets.setdefault(col, []).append(w['text'])

                if 'member' not in buckets or 'name' not in buckets:
                    continue

                asa_id = ''.join(buckets['member']).strip()
                if not asa_id.isdigit():
                    continue

                name = ' '.join(buckets['name']).strip()
                dob_raw = ' '.join(buckets.get('dob', [])).strip()
                club = ' '.join(buckets.get('club', [])).strip()
                date_raw = ' '.join(buckets.get('date', [])).strip()
                meet_name = ' '.join(buckets.get('meet', [])).strip()

                # Time may be fragmented into multiple word tokens that get
                # bucketed across 'meet' and 'time' due to Acrobat kerning.
                # Strategy: take everything in the 'time' bucket, plus any
                # trailing time-like fragment from 'meet', and reassemble.
                time_tokens = buckets.get('time', [])
                time_str = ''.join(time_tokens).strip()
                if not _time_to_cs(time_str):
                    # try concatenating last fragment of meet bucket if it
                    # looks like a time leading char
                    cand = re.sub(r'\s+', '', time_str)
                    if not _time_to_cs(cand):
                        # fall back: search for a HH:MM.cc / MM:SS.cc / SS.cc anywhere
                        joined = ''.join(w['text'] for w in line_words if w['x0'] >= 480)
                        joined = re.sub(r'[^\d:.]', '', joined)
                        cand = joined
                    time_cs = _time_to_cs(cand)
                else:
                    time_cs = _time_to_cs(time_str)

                if time_cs is None:
                    continue

                fina_str = ''.join(buckets.get('fina', [])).strip()
                fina_pts = int(fina_str) if fina_str.isdigit() else None

                distance, stroke, gender = current_event
                row = PBRow(
                    asa_id=asa_id,
                    name=name,
                    dob=_ddmmyyyy_to_iso(dob_raw),
                    distance=distance, stroke=stroke, course=course,
                    gender=gender,
                    time_cs=time_cs,
                    pb_date=_ddmmyyyy_to_iso(date_raw),
                    pb_meet=meet_name,
                    pb_club=club,
                    fina_points=fina_pts,
                )
                rows.append(row)

    return rows


# ----------------------------------------------------------------------
# Aggregation: build a PB store keyed by (asa_id, dist, stroke, course)
# ----------------------------------------------------------------------

PBKey = tuple[str, int, str, str]  # (asa_id, distance, stroke, course)


@dataclass
class PBStore:
    pbs: dict[PBKey, PBRow]
    by_asa: dict[str, list[PBRow]]    # all of a swimmer's PBs across events

    def get(self, asa_id: str, distance: int, stroke: str, course: str) -> PBRow | None:
        return self.pbs.get((asa_id, distance, stroke, course))


def import_pb_pdfs(paths: dict[str, str]) -> PBStore:
    """Import a set of PB PDFs and return a unified PB store.

    Args:
        paths: mapping of course-code ('LC'|'SC') doesn't matter — pass a
               dict like {'female_lc': 'path.pdf', 'female_sc': '...'}
               and we'll detect the course from the filename or rely on
               an explicit naming convention. For now the caller passes:
               {'female_lc': p, 'female_sc': p, 'male_lc': p, 'male_sc': p}.

    The fastest time for a given (asa, dist, stroke, course) wins.
    """
    pbs: dict[PBKey, PBRow] = {}
    by_asa: dict[str, list[PBRow]] = {}

    for label, p in paths.items():
        if not p or not Path(p).exists():
            continue
        course = 'LC' if 'lc' in label.lower() else 'SC'
        for row in parse_pb_pdf(p, course):
            key: PBKey = (row.asa_id, row.distance, row.stroke, row.course)
            existing = pbs.get(key)
            if existing is None or row.time_cs < existing.time_cs:
                pbs[key] = row
            by_asa.setdefault(row.asa_id, []).append(row)

    return PBStore(pbs=pbs, by_asa=by_asa)
