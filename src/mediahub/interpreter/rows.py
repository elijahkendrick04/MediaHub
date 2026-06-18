"""
rows.py — extract InterpretedSwim rows using the induced ColumnSchema.

For each table row (or structured line group), maps cells to typed fields,
normalises values, and assigns per-row and per-field confidence scores.

No swim-vocabulary literals.
"""

from __future__ import annotations

import logging
import re

from .schema_dataclasses import (
    ColumnSchema,
    IngestStream,
    InterpretedEvent,
    InterpretedSwim,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Value normalisation helpers
# ---------------------------------------------------------------------------

_TIME_COLON = re.compile(r"^(\d{1,2}):(\d{2})\.(\d{2})$")
_TIME_PLAIN = re.compile(r"^(\d{1,3})\.(\d{2})$")


def _normalise_time(raw: str) -> tuple[str | None, float]:
    """Return (canonical_time, confidence)."""
    s = raw.strip()
    m = _TIME_COLON.match(s)
    if m:
        return s, 0.95
    m = _TIME_PLAIN.match(s)
    if m:
        return s, 0.85
    return None, 0.0


def _normalise_place(raw: str) -> tuple[int | None, float]:
    s = raw.strip().lstrip("=")
    if s.isdigit():
        return int(s), 0.90
    return None, 0.0


def _normalise_yob(raw: str) -> tuple[int | None, float]:
    s = raw.strip()
    if re.match(r"^(19[4-9]\d|20[0-3]\d)$", s):
        return int(s), 0.90
    if re.match(r"^\d{2}$", s):
        yr = int(s)
        # Disambiguate 2-digit year: assume born between 1940-current
        year_4 = 2000 + yr if yr <= 30 else 1900 + yr
        return year_4, 0.70
    return None, 0.0


def _normalise_reaction(raw: str) -> tuple[str | None, float]:
    s = raw.strip()
    if re.match(r"^0\.\d{2,3}$", s):
        return s, 0.90
    return None, 0.0


def _normalise_name(raw: str) -> tuple[str | None, float]:
    s = raw.strip()
    # A real competitor name has letters and NO digits — a token like "H-7 L"
    # or "Heat 7" is a heat/lane/relay-leg artifact, not a swimmer, and must not
    # surface as a result.
    if len(s) >= 3 and re.search(r"[A-Za-z]", s) and not re.search(r"\d", s):
        return s, 0.80
    return None, 0.0


# A leading year-of-birth token that has slipped into the club field. British
# results print "Name (YoB) Club" (e.g. "Tom DAVIES (04) City of Sheffield"),
# and a column slip or an AI extraction without a dedicated year column can push
# the "(04)" into the club cell — either alone ("(04)") or as a prefix on the
# real club ("(04) City of Sheffield"). The token is an optional-paren 2- or
# 4-digit year, anchored so it only matches a whole leading token (so a real
# name like "100 Club" or "1st City SC" is never truncated).
_CLUB_YOB_PREFIX = re.compile(r"^\(?\s*(?:19|20)?\d{2}\s*\)?(?=\s|$)")

# Race data that can slip into the club cell when a results page is mostly a
# split/lap table (e.g. a 1500m event) and an AI extraction has no clean club
# column: lap/cumulative times ("13:53.80") or distance markers ("1350m").
# A club name never contains a lap time or a distance token.
_CLUB_RACE_DATA = re.compile(
    r"\d{1,3}:\d{2}\.\d{2}"  # lap/cumulative time mm:ss.cc
    r"|\b\d{1,4}\s*m\b"  # a distance token like '1350m' / '50 m'
)


def _normalise_club(raw: str) -> tuple[str | None, float]:
    s = raw.strip()
    if not s:
        return None, 0.0
    # Reject race data (split times, distances) that slipped into the club cell.
    if _CLUB_RACE_DATA.search(s):
        return None, 0.0
    # Strip a leading year-of-birth token if one slipped into the club cell.
    cleaned = _CLUB_YOB_PREFIX.sub("", s).strip()
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        # Nothing club-like remains (the cell carried only a year-of-birth, e.g.
        # "(04)") — not a club, so don't surface it in the club picker.
        return None, 0.0
    # A leading bracket marker ("[M", "[pull]", "(M") left after the year strip
    # is a stroke/leg marker, not a club.
    if cleaned[:1] in "[(":
        return None, 0.0
    return cleaned, 0.75


_NORMALISERS = {
    "time": _normalise_time,
    "place": _normalise_place,
    "yob": _normalise_yob,
    "reaction": _normalise_reaction,
    "name": _normalise_name,
    "club": _normalise_club,
}


# ---------------------------------------------------------------------------
# Row extraction from table candidate
# ---------------------------------------------------------------------------


def _extract_swim_from_cells(
    cells: list[str],
    schemas: list[ColumnSchema],
) -> InterpretedSwim | None:
    field_vals: dict[str, object] = {}
    field_conf: dict[str, float] = {}

    for schema in schemas:
        idx = schema.col_index
        if idx is None or idx >= len(cells):
            continue
        raw = cells[idx].strip()
        if not raw:
            continue
        normaliser = _NORMALISERS.get(schema.col_type)
        if normaliser:
            value, conf = normaliser(raw)
            if value is not None:
                field_vals[schema.col_type] = value
                field_conf[schema.col_type] = conf * schema.confidence
        else:
            # Unknown column type — store raw
            field_vals[schema.col_type] = raw
            field_conf[schema.col_type] = schema.confidence * 0.5

    # A competition result must identify a competitor. A row with a time but no
    # name is a split/continuation line (cumulative lap times listed under a
    # swimmer on a distance event), not a result — dropping it keeps overall
    # times only and prevents phantom, nameless "results" from the splits table.
    if "name" not in field_vals:
        return None

    # Overall per-swim confidence: mean of field confidences
    row_conf = sum(field_conf.values()) / len(field_conf) if field_conf else 0.0

    return InterpretedSwim(
        swimmer_name=str(field_vals.get("name", "")),
        yob=field_vals.get("yob"),  # type: ignore[arg-type]
        club=field_vals.get("club"),  # type: ignore[arg-type]
        place=field_vals.get("place"),  # type: ignore[arg-type]
        time=field_vals.get("time"),  # type: ignore[arg-type]
        reaction=field_vals.get("reaction"),  # type: ignore[arg-type]
        confidence=round(min(row_conf, 1.0), 4),
        raw_row="\t".join(cells),
        field_confidence=field_conf,
    )


# ---------------------------------------------------------------------------
# Assign rows to events
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Structural row regex (no swim vocabulary; place / name / age / club / time)
# ---------------------------------------------------------------------------

# Place tokens: 1, 1., =1, *1, *1., ---, DQ, DNS, DNF, NS
_PLACE = r"(?P<place>=?\*?\d{1,3}\.?|---|DQ|DNS|DNF|NS)"
# Name: words including letters, hyphens, apostrophes, periods, commas; min 3 chars
_NAME = r"(?P<name>[A-Za-z][A-Za-z'\-\.\, ]{2,}?[A-Za-z\.\)])"
# Age / YOB: 1-4 digits, optionally parenthesised. British results print the
# year of birth in parentheses between the name and the club
# ("Tom DAVIES (04) City of Sheffield 50.12"); without the optional parens none
# of the row patterns matched that format and every such line was dropped.
_AGE = r"(?P<age>\(?\d{1,4}\)?)"
# Club: any printable run
_CLUB = r"(?P<club>[A-Za-z][A-Za-z0-9'\-\.\,\& /]{1,}?)"
# Time: mm:ss.cc or ss.cc; optional X-prefix; or DQ/DNS/DNF/NS
_TIME = r"(?P<time>X?\d{1,2}:\d{2}\.\d{2}|X?\d{1,3}\.\d{2}|DQ|DNS|DNF|NS)"

# Full row: place + name + age + club + time (most permissive ordering)
_ROW_RE = re.compile(
    r"^\s*"
    + _PLACE
    + r"\s+"
    + _NAME
    + r"\s+"
    + _AGE
    + r"\s+"
    + _CLUB
    + r"\s+"
    + _TIME
    + r"(?:\s|$)"
)
# Variant without leading place (place column may be missing or merged)
_ROW_RE_NO_PLACE = re.compile(
    r"^\s*" + _NAME + r"\s+" + _AGE + r"\s+" + _CLUB + r"\s+" + _TIME + r"(?:\s|$)"
)
# Variant: place + name + club + time (no age column visible — common in some
# narrow templates)
_ROW_RE_NO_AGE = re.compile(
    r"^\s*" + _PLACE + r"\s+" + _NAME + r"\s+" + _CLUB + r"\s+" + _TIME + r"(?:\s|$)"
)

_TIME_SHAPE = re.compile(r"^\d{1,2}:\d{2}\.\d{2}$|^\d{1,3}\.\d{2}$")
_DSQ_TOKENS = {"DQ", "DNS", "DNF", "NS"}


def _structural_swim_from_match(m: re.Match, raw: str) -> InterpretedSwim | None:
    """Build an InterpretedSwim from a regex Match against a row."""
    gd = m.groupdict()
    raw_place = gd.get("place")
    raw_name = (gd.get("name") or "").strip()
    # The age/YOB may arrive parenthesised (British "Name (04) Club") — unwrap
    # before the digit checks below so "(04)" is read as the year 2004.
    raw_age = gd.get("age")
    if raw_age:
        raw_age = raw_age.strip("()")
    raw_club = (gd.get("club") or "").strip()
    raw_time = (gd.get("time") or "").strip()

    field_conf: dict[str, float] = {}

    # Time normalisation (strip leading X for marker times)
    time_val: str | None = None
    time_clean = raw_time.lstrip("X")
    if time_clean.upper() in _DSQ_TOKENS:
        time_val = time_clean.upper()
        field_conf["time"] = 0.85
    else:
        t_norm, t_conf = _normalise_time(time_clean)
        if t_norm is not None:
            time_val = t_norm
            field_conf["time"] = t_conf

    # Place normalisation
    place_val: int | None = None
    if raw_place:
        cleaned = raw_place.lstrip("=").lstrip("*").rstrip(".")
        if cleaned.isdigit():
            place_val = int(cleaned)
            field_conf["place"] = 0.90

    # YOB / age disambiguation
    yob_val: int | None = None
    if raw_age:
        if len(raw_age) == 4 and raw_age.isdigit():
            y = int(raw_age)
            if 1940 <= y <= 2030:
                yob_val = y
                field_conf["yob"] = 0.90
        elif len(raw_age) == 2 and raw_age.isdigit():
            y = int(raw_age)
            yob_val = 2000 + y if y <= 30 else 1900 + y
            field_conf["yob"] = 0.70
        elif raw_age.isdigit():
            # 1-3 digit number is most likely an age, not a YOB
            field_conf["age_raw"] = 0.6

    # Name confidence
    if len(raw_name) >= 3 and re.search(r"[A-Za-z]", raw_name):
        field_conf["name"] = 0.80
    else:
        return None

    # Club
    club_val: str | None = raw_club if raw_club else None
    if club_val:
        field_conf["club"] = 0.75

    if not (field_conf.get("name") and field_conf.get("time")):
        return None

    row_conf = sum(field_conf.values()) / len(field_conf)

    return InterpretedSwim(
        swimmer_name=raw_name,
        yob=yob_val,
        club=club_val,
        place=place_val,
        time=time_val,
        reaction=None,
        confidence=round(min(row_conf, 1.0), 4),
        raw_row=raw.strip(),
        field_confidence=field_conf,
    )


def _structural_extract_lines(
    stream: IngestStream,
) -> list[tuple[int, InterpretedSwim]]:
    """Extract swim rows from stream.lines via structural regex.

    Returns list of (line_index, swim) tuples so callers can map swims to
    nearby event headers.
    """
    out: list[tuple[int, InterpretedSwim]] = []
    for idx, line in enumerate(stream.lines):
        text = getattr(line, "text", str(line))
        if not text.strip():
            continue
        # Try the most informative pattern first
        for pat in (_ROW_RE, _ROW_RE_NO_PLACE, _ROW_RE_NO_AGE):
            m = pat.match(text)
            if m:
                swim = _structural_swim_from_match(m, text)
                if swim is not None:
                    out.append((idx, swim))
                    break
    return out


def _find_event_line_indices(
    stream: IngestStream,
    events: list[InterpretedEvent],
) -> list[int]:
    """Return the line index in stream.lines that produced each event header.

    Falls back to evenly-spaced positions if a header text cannot be located.
    """
    indices: list[int] = []
    cursor = 0
    line_texts = [getattr(ln, "text", "").strip() for ln in stream.lines]
    for ev in events:
        target = (ev.raw_header or "").strip()
        found = -1
        if target:
            for j in range(cursor, len(line_texts)):
                if line_texts[j] == target:
                    found = j
                    break
        if found < 0:
            # Fallback: assume sequential placement
            found = cursor
        indices.append(found)
        cursor = max(cursor, found + 1)
    return indices


def _assign_swims_by_line_index(
    swims_with_idx: list[tuple[int, InterpretedSwim]],
    events: list[InterpretedEvent],
    event_line_indices: list[int],
) -> None:
    """Bucket each swim into the most-recent event by line index."""
    if not events:
        return
    if not event_line_indices:
        # All to first event
        events[0].swims = [s for _, s in swims_with_idx]
        return
    for ev in events:
        ev.swims = []
    for line_idx, swim in swims_with_idx:
        # Find the latest event header at or before this line
        target = 0
        for ei, hi in enumerate(event_line_indices):
            if hi <= line_idx:
                target = ei
            else:
                break
        events[target].swims.append(swim)


def assign_rows_to_events(
    stream: IngestStream,
    events: list[InterpretedEvent],
    schemas: list[ColumnSchema],
) -> None:
    """
    Populate each InterpretedEvent.swims using the strongest of two paths:

      A. Schema-based extraction over stream.tables (induced ColumnSchema).
      B. Structural row-regex extraction over stream.lines.

    The path that yields more swims wins.  When path B wins, swims are
    assigned by line index to the most recently seen event header (rather
    than evenly chunked).  This makes the interpreter robust to PDFs whose
    column structure is fragile (variable token counts across rows).
    """
    # ---- Path A: schema/table-based extraction (existing behaviour) ------
    schema_swims: list[InterpretedSwim] = []
    if schemas:
        for table in stream.tables:
            rows_to_process = table.rows
            if rows_to_process:
                first = rows_to_process[0]
                num_pat = re.compile(r"^\d")
                is_header = all(not num_pat.match(c) for c in first if c.strip())
                if is_header:
                    rows_to_process = rows_to_process[1:]
            for cells in rows_to_process:
                swim = _extract_swim_from_cells(cells, schemas)
                if swim is not None:
                    schema_swims.append(swim)
        if not schema_swims:
            schema_swims = _extract_from_lines(stream, schemas)

    # ---- Path B: structural row-regex over stream.lines ------------------
    structural_with_idx = _structural_extract_lines(stream)
    structural_swims = [s for _, s in structural_with_idx]

    # Pick the winning path.  We prefer the path that yields more swims with
    # a real *time* value, because the schema path can otherwise produce many
    # rows containing only a name token ("Session", "Female", header words).
    schema_with_time = sum(1 for s in schema_swims if s.time)
    structural_with_time = sum(1 for s in structural_swims if s.time)
    use_structural = structural_with_time > schema_with_time
    all_swims = structural_swims if use_structural else schema_swims

    if not events:
        # No headers found — create a single synthetic event
        if all_swims:
            synthetic = InterpretedEvent(
                gender=None,
                distance_m=None,
                stroke=None,
                course=None,
                age_band=None,
                swims=all_swims,
                confidence=0.5,
                raw_header="(synthetic)",
            )
            events.append(synthetic)
        return

    if use_structural:
        ev_line_idx = _find_event_line_indices(stream, events)
        _assign_swims_by_line_index(structural_with_idx, events, ev_line_idx)
    else:
        # Sequential chunk assignment for the schema path
        if len(events) == 1:
            events[0].swims = all_swims
        else:
            chunk = max(1, len(all_swims) // len(events))
            for i, ev in enumerate(events):
                ev.swims = all_swims[i * chunk : (i + 1) * chunk]
            if events:
                events[-1].swims += all_swims[len(events) * chunk :]


def _extract_from_lines(
    stream: IngestStream,
    schemas: list[ColumnSchema],
) -> list[InterpretedSwim]:
    """Last-resort line-based extraction using schema col positions."""
    swims: list[InterpretedSwim] = []
    _multi_space = re.compile(r"\s{2,}|\t")
    for line in stream.lines:
        text = getattr(line, "text", str(line)).strip()
        cells = [c.strip() for c in _multi_space.split(text) if c.strip()]
        if len(cells) >= 2:
            swim = _extract_swim_from_cells(cells, schemas)
            if swim is not None:
                swims.append(swim)
    return swims
