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
    # Some results services list finishing places with a trailing dot
    # ("1." / "2.") — strip it, plus a leading "=" tie marker, before parsing
    # the integer, so a real place column isn't rejected as non-numeric.
    s = raw.strip().lstrip("=").rstrip(".")
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


def _person_name(raw: str) -> str:
    """Tidy a competitor name: collapse spaces and reorder "Lastname, Firstname"
    to "Firstname Lastname" so comma- and space-ordered sources agree.

    Accent-bearing names are preserved (the letter test is Unicode-aware), so
    "José", "Siân" and "Müller" survive intact.
    """
    s = re.sub(r"\s+", " ", str(raw).strip())
    if "," in s:
        last, _, first = s.partition(",")
        last, first = last.strip(), first.strip()
        if first and last and re.search(r"[^\W\d_]", first):
            s = f"{first} {last}"
    return s.strip(" ,")


def _normalise_name(raw: str) -> tuple[str | None, float]:
    s = _person_name(raw)
    # A real competitor name has letters and NO digits — a token like "H-7 L"
    # or "Heat 7" is a heat/lane/relay-leg artifact, not a swimmer, and must not
    # surface as a result. The letter test is Unicode-aware so accented names
    # ("José", "Siân") survive.
    if len(s) >= 3 and re.search(r"[^\W\d_]", s) and not re.search(r"\d", s):
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

# "NT" (No Time) is the seed-time placeholder for an unseeded entry. In a
# "Name AaD Club Seed Finals" row the seed column sits immediately after the
# club, so a club cell built from the tokens between the age and the finals
# time absorbs it ("City of Brighton & Hove NT") — spawning a phantom
# "<Club> NT" club in the picker; a seed cell mis-mapped to the club column can
# also be a bare "NT". A standalone trailing No-Time marker is never part of a
# club name. Anchoring on a preceding word boundary (string start or
# whitespace) means a real name ending in those letters (… Kent, … Trent) is
# never touched.
_CLUB_SEED_NOTIME_SUFFIX = re.compile(r"(?:^|\s+)N\.?T\.?$", re.IGNORECASE)


def _normalise_club(raw: str) -> tuple[str | None, float]:
    s = raw.strip()
    if not s:
        return None, 0.0
    # Reject race data (split times, distances) that slipped into the club cell.
    if _CLUB_RACE_DATA.search(s):
        return None, 0.0
    # Strip a leading year-of-birth token if one slipped into the club cell.
    cleaned = _CLUB_YOB_PREFIX.sub("", s).strip()
    # Strip a trailing "NT" (No-Time seed marker) absorbed from the seed column,
    # so an unseeded entry never spawns a phantom "<Club> NT" club.
    cleaned = _CLUB_SEED_NOTIME_SUFFIX.sub("", cleaned).strip()
    # Para-classification suffix: a results "Class" column ("14" = S14/SM14) sits
    # between the club and the time and gets absorbed into the club cell
    # ("Co Cardiff 14"). Strip the trailing class so a club's para swimmers fold
    # into the parent club instead of becoming a separate club. Para classes
    # only run 1-15 (S1-S14, SB1-SB14, SM1-SM15), so the strip is bounded to
    # that range: a club legitimately named with a trailing number outside it
    # ("Otter 79", "SV Neptun 08") survives intact.
    cleaned = re.sub(r"\s+(?:1[0-5]|[1-9])$", "", cleaned).strip()
    # Collapsed "Name AaD Club" row (e.g. relay/AaD-format events) where the
    # whole row landed in the club cell: the actual club is the text AFTER the
    # age number. "Dion Edwards 19 Swansea Uni" -> "Swansea Uni".
    m = re.search(r"[A-Za-z].*?\s\d{1,2}\s+([A-Za-z].*)$", cleaned)
    if m:
        cleaned = m.group(1).strip()
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
    # The seed/entry-time column normalises identically to a result time but is
    # kept under its own type so it is never selected as the swum result. The
    # header-driven schema (priority Finals Time > Prelim Time; never Seed Time)
    # assigns "time" to the result column and "seed_time" to the entry column.
    "seed_time": _normalise_time,
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
                _eff = conf * schema.confidence
                # When two columns claim the same type — a real time plus a
                # lap-split column, or a place plus a separate points column —
                # keep the HIGHEST-confidence one instead of letting the
                # rightmost column overwrite (which clobbered the real time with
                # the split, and the place with the points).
                if _eff >= field_conf.get(schema.col_type, -1.0):
                    field_vals[schema.col_type] = value
                    field_conf[schema.col_type] = _eff
        else:
            # Unknown column type — store raw (highest-confidence wins too).
            _eff = schema.confidence * 0.5
            if _eff >= field_conf.get(schema.col_type, -1.0):
                field_vals[schema.col_type] = raw
                field_conf[schema.col_type] = _eff

    # A disqualified / non-finish row carries a DSQ marker cell (DQ/DNS/DNF/…)
    # alongside — or instead of — a printed time. The printed time on a DQ swim
    # is struck out and must NOT surface as a valid result, so let the marker BE
    # the time: the bridge maps a non-numeric time to finals_time_cs=None /
    # dq=True, which excludes the swim from PB & moment detection. Match a cell
    # whose first token is a DSQ marker so "DQ", "DNS" and rule-coded "DQ 8.2"
    # forms are all caught.
    for cell in cells:
        head = cell.strip().split()[:1]
        if head and head[0].upper() in _DSQ_VALUES:
            field_vals["time"] = head[0].upper()
            field_conf["time"] = max(field_conf.get("time", 0.0), 0.85)
            break

    # QA-012: a finals-qualification marker ("q"/"Q"/"q430") on the row means it
    # is a heat/preliminary swim that advanced to a final — NOT a final-round
    # result. The token path (_record_to_swim) already sets round_hint="prelim"
    # for this; mirror it here so a structured-table prelim row can never
    # surface as a fabricated final/medal. Match a standalone qualifier cell, or
    # a qualifier token trailing a time-shaped token inside a cell (anchored so
    # ordinary words are never mistaken for a marker).
    qualified = False
    for cell in cells:
        toks = cell.strip().split()
        if len(toks) == 1 and _is_qualifier(toks[0]):
            qualified = True
            break
        if len(toks) >= 2 and _is_qualifier(toks[-1]) and _is_time_like(toks[-2]):
            qualified = True
            break

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
        seed_time=field_vals.get("seed_time"),  # type: ignore[arg-type]
        reaction=field_vals.get("reaction"),  # type: ignore[arg-type]
        confidence=round(min(row_conf, 1.0), 4),
        raw_row="\t".join(cells),
        field_confidence=field_conf,
        round_hint="prelim" if qualified else None,
    )


# ---------------------------------------------------------------------------
# Assign rows to events
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Multi-record line parser (no swim vocabulary)
# ---------------------------------------------------------------------------
#
# A printed results line carries one OR MORE competitor records. Multi-column
# templates put several complete records on one baseline::
#
#   1 Arthur, Andrew 23 UoAPS 28.73     33 Warner, Liam 16 East Lothian 32.82
#
# We split a line into records by anchoring on the TIME token (the one token
# whose shape is unambiguous), then classify each record's tokens as::
#
#   [place]  name…  [age|yob]  [club…]  time
#
# This is layout-independent: 1-, 2- and 3-column pages, with or without a
# place / age / club column, all reduce to the same record grammar — so the
# common two-swimmers-per-line layout no longer loses half of every event.

# Unicode letter (accented names — José, Siân, Müller — must survive).
_LETTER = r"[^\W\d_]"
# Time token: optional J/X/R judged-or-marker prefix, then mm:ss.cc or ss.cc.
_TIME_TOKEN = re.compile(r"^[JXRjxr]?\d{0,3}:?\d{1,2}\.\d{2}$")
# Disqualification / no-time markers that occupy the time column.
_DSQ_TOKEN = re.compile(r"^(?:DQ|DNS|DNF|DNC|NS|SCR|WD)$", re.IGNORECASE)
# Rank token starting a record: 1, 1., =1, *1 (ties), or --- (no place / DQ).
_PLACE_TOKEN = re.compile(r"^=?\*?\d{1,3}\.?$|^-{2,}$")
# Age (AaD) or year-of-birth token between name and club, optionally in parens.
_AGEYOB_TOKEN = re.compile(r"^\(?\d{1,4}\)?$")
_DSQ_VALUES = {"DQ", "DNS", "DNF", "DNC", "NS", "SCR", "WD"}

# Finals-qualification marker trailing a heat/prelim time: "q", "Q" or the FINA-
# points form "q430". HY-TEK stamps it only on a preliminary swim that advanced
# to a final, so a row carrying it is a heat, not a final-round result. It is
# report furniture (like the DSQ markers above), not swim ontology.
_QUALIFIER_TOKEN = re.compile(r"^[qQ]\d*$")

# A reaction time is a sub-second value ("0.63", "+0.71") printed after the swim
# time in some layouts. It is never the achieved race result (no pool race is
# under a second), so it must not be mistaken for the time when a row prints
# several time-shaped tokens.
_REACTION_TOKEN = re.compile(r"^[+\-]?0\.\d{2,3}$")


def _is_time_like(tok: str) -> bool:
    return bool(_TIME_TOKEN.match(tok) or _DSQ_TOKEN.match(tok))


def _is_qualifier(tok: str) -> bool:
    return bool(_QUALIFIER_TOKEN.match(tok))


def _is_reaction_like(tok: str) -> bool:
    return bool(_REACTION_TOKEN.match(tok))


def _tokenise_with_gaps(text: str) -> list[tuple[str, bool]]:
    """Split text into (token, big_gap_before) pairs.

    A "big gap" is a run of 2+ spaces — a column break preserved by the PDF
    extractor (or present in space-aligned text). It is a secondary cue used to
    separate name from club when a row has no age/yob column.
    """
    out: list[tuple[str, bool]] = []
    prev_end = 0
    for m in re.finditer(r"\S+", text):
        gap = text[prev_end : m.start()]
        out.append((m.group(0), prev_end != 0 and len(gap) >= 2))
        prev_end = m.end()
    return out


def _split_into_records(
    tokens: list[tuple[str, bool]],
) -> list[list[tuple[str, bool]]]:
    """Break a tokenised line into one record per competitor.

    A record runs from a competitor's leading token up to AND INCLUDING their
    achieved time. Crucially, several time columns for ONE competitor stay in
    the same record: a "Seed Finals" or "Prelim Finals" layout prints two times
    on the row, and a finals-qualification marker ("q"/"q430") trails the time
    on a heat. A new record only begins when a non-time, non-qualifier token
    appears AFTER a time has been seen — i.e. the next competitor's place/name.

    This fixes two faults of the old "split at the first time token" rule, which
    truncated every row at its first time: it surfaced the SEED time as the
    result (discarding the achieved final time), and it threw away the trailing
    "q" marker that distinguishes a heat from a final. The multi-competitor
    per-line layout still works, because the next competitor starts with a
    place/name token (never time-shaped).
    """
    records: list[list[tuple[str, bool]]] = []
    cur: list[tuple[str, bool]] = []
    seen_time = False
    for tok, big in tokens:
        if seen_time and not _is_time_like(tok) and not _is_qualifier(tok):
            # First non-time, non-qualifier token after a time → the previous
            # competitor's record is complete; this token begins the next one.
            records.append(cur)
            cur = [(tok, big)]
            seen_time = False
            continue
        cur.append((tok, big))
        if _is_time_like(tok):
            seen_time = True
    # Close the final record only if it actually carries a time (a trailing
    # fragment of points/markers with no time is not a competitor). A real time
    # immediately followed by a DSQ marker ("3:29.20 DQ") stays in one record:
    # the marker is time-like too, so it is the record's terminal (achieved)
    # token and the struck-out time is dropped as the body boundary below — the
    # swim then carries the DSQ status, not a fabricated valid result (QA-013).
    if cur and any(_is_time_like(t) for t, _ in cur):
        records.append(cur)
    return records


def _marker_or_time(tok: str) -> tuple[str | None, float]:
    """Normalise a time-column token (strip J/X/R prefix; accept DSQ markers)."""
    clean = re.sub(r"^[JXRjxr]", "", tok)
    if clean.upper() in _DSQ_VALUES:
        return clean.upper(), 0.85
    return _normalise_time(clean)


def _looks_like_relay(name_toks: list[str]) -> bool:
    """A team name ending in a single-letter leg ("… A" / "… B"), with no age
    and no club, is a relay squad — not an individual. Skip it so it never
    surfaces as a phantom swimmer."""
    return len(name_toks) >= 2 and len(name_toks[-1]) == 1 and name_toks[-1].isalpha()


def _record_to_swim(rec: list[tuple[str, bool]]) -> InterpretedSwim | None:
    """Classify one competitor record's tokens into an InterpretedSwim."""
    if not rec:
        return None

    # Locate the time column(s). A row may print several time-shaped tokens —
    # seed + finals, or prelim + finals (+ a reaction time, + a "q" marker). The
    # ACHIEVED race time is the LAST real race time on the row; a sub-second
    # value is a reaction time, never the result; and the body (place/name/club)
    # is everything BEFORE the first time. Falling back to the first time only
    # if every time-shaped token is reaction-shaped keeps degenerate rows alive.
    time_idxs = [i for i, (t, _) in enumerate(rec) if _is_time_like(t)]
    if not time_idxs:
        return None
    first_time_idx = time_idxs[0]
    achieved_candidates = [i for i in time_idxs if not _is_reaction_like(rec[i][0])]
    achieved_idx = achieved_candidates[-1] if achieved_candidates else time_idxs[-1]
    time_tok = rec[achieved_idx][0]
    body = rec[:first_time_idx]

    # The Seed/entry time is the FIRST real race time when a row prints more than
    # one (Seed before Finals/Prelim). Kept separately (never read as the result)
    # so raw extraction stays distinct from the canonical swum time and a swim
    # slower than its seed can never be mistaken for a PB. For a DQ'd swim
    # ("… 2:55.80 DQ") the achieved time is the marker and this is the seed.
    seed_tok = rec[achieved_candidates[0]][0] if len(achieved_candidates) >= 2 else None

    # A finals-qualification marker ("q"/"q430") trailing the achieved time means
    # this row is a heat/preliminary swim that qualified to a final — not a
    # final-round result. Surface it so the canonical bridge marks the round.
    qualified = any(_is_qualifier(t) for t, _ in rec[achieved_idx + 1 :])

    # A disqualified swim ("… 3:29.20 DQ") needs no special-casing here: the DSQ
    # marker is time-like, so it is the LAST time token and becomes the achieved
    # `time_tok` (the bridge maps a non-numeric time to dq=True / no PB), while
    # `body` — everything before the FIRST time — already excludes the struck-out
    # void time so it is never mis-read as club/age data (QA-013).

    # Place (optional leading rank).
    place_val: int | None = None
    start = 0
    if body and _PLACE_TOKEN.match(body[0][0]):
        cleaned = body[0][0].lstrip("=*").rstrip(".")
        if cleaned.isdigit():
            place_val = int(cleaned)
        start = 1
    middle = body[start:]
    if not middle:
        return None  # a "place time" line with no competitor is a total/header

    # Age / year-of-birth separator: the first standalone numeric token after at
    # least one name token splits the name (before) from the club (after).
    sep: int | None = None
    for j in range(1, len(middle)):
        if _AGEYOB_TOKEN.match(middle[j][0]):
            sep = j
            break

    age_tok: str | None = None
    if sep is not None:
        name_toks = [t for t, _ in middle[:sep]]
        age_tok = middle[sep][0]
        club_toks = [t for t, _ in middle[sep + 1 :]]
    else:
        # No age column — split name|club at the first column break, if any.
        brk = next((j for j in range(1, len(middle)) if middle[j][1]), None)
        if brk is not None:
            name_toks = [t for t, _ in middle[:brk]]
            club_toks = [t for t, _ in middle[brk:]]
        else:
            name_toks = [t for t, _ in middle]
            club_toks = []

    time_val, time_conf = _marker_or_time(time_tok)
    if time_val is None:
        return None

    # Seed/entry time (the column before the result), kept separately so it is
    # never confused with the swum result or a prior best. Drop any J/X/R marker
    # prefix exactly as the result token does.
    seed_val: str | None = None
    if seed_tok is not None:
        seed_val, _seed_conf = _normalise_time(re.sub(r"^[JXRjxr]", "", seed_tok))

    # Drop leading lane / heat numbers sitting before the name (the place was
    # already consumed, and a competitor name never begins with a bare number).
    while name_toks and name_toks[0].strip("()").isdigit():
        name_toks.pop(0)
    name = _person_name(" ".join(name_toks))
    if len(name) < 3 or not re.search(_LETTER, name):
        return None
    if age_tok is None and not club_toks and _looks_like_relay(name_toks):
        return None

    field_conf: dict[str, float] = {"name": 0.80, "time": time_conf}
    if place_val is not None:
        field_conf["place"] = 0.90

    # The parens are the disambiguation signal between age and year-of-birth:
    # British results print YOB parenthesised ("(04)"), while the Hy-Tek AaD
    # column prints a bare 1-2 digit AGE ("… Arthur, Andrew 23 UoAPS 28.73").
    # Only a parenthesised or 4-digit token is a YOB; a bare 2-digit token is
    # the swimmer's age at the meet and must never be stored as a 20xx year.
    yob_val: int | None = None
    age_val: int | None = None
    if age_tok is not None:
        bare = age_tok.strip("()")
        if age_tok != bare or len(bare) == 4:
            yob_val, yconf = _normalise_yob(bare)
            if yob_val is not None:
                field_conf["yob"] = yconf
        elif re.match(r"^\d{2}$", bare):
            age_val = int(bare)
            field_conf["age"] = 0.70

    club_val: str | None = None
    if club_toks:
        club_val, cconf = _normalise_club(" ".join(club_toks))
        if club_val is not None:
            field_conf["club"] = cconf

    if seed_val is not None:
        field_conf["seed_time"] = 0.80

    row_conf = sum(field_conf.values()) / len(field_conf)
    return InterpretedSwim(
        swimmer_name=name,
        yob=yob_val,
        age=age_val,
        club=club_val,
        place=place_val,
        time=time_val,
        seed_time=seed_val,
        reaction=None,
        confidence=round(min(row_conf, 1.0), 4),
        raw_row=" ".join(t for t, _ in rec),
        field_confidence=field_conf,
        round_hint="prelim" if qualified else None,
    )


def _parse_records_from_line(text: str) -> list[InterpretedSwim]:
    """Parse every competitor record carried by one printed line."""
    swims: list[InterpretedSwim] = []
    for rec in _split_into_records(_tokenise_with_gaps(text)):
        swim = _record_to_swim(rec)
        if swim is not None:
            swims.append(swim)
    return swims


def _structural_extract_lines(
    stream: IngestStream,
) -> list[tuple[int, InterpretedSwim]]:
    """Extract swim records from stream.lines via the multi-record parser.

    Returns (line_index, swim) tuples so callers map swims to nearby event
    headers; one line may yield several swims (multi-column layouts).
    """
    out: list[tuple[int, InterpretedSwim]] = []
    for idx, line in enumerate(stream.lines):
        text = getattr(line, "text", str(line))
        if not text.strip():
            continue
        for swim in _parse_records_from_line(text):
            out.append((idx, swim))
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
      B. Multi-record line parsing over stream.lines.

    The path that yields more swims wins.  When path B wins, swims are
    assigned by line index to the most recently seen event header (rather
    than evenly chunked).  This makes the interpreter robust to PDFs whose
    column structure is fragile (variable token counts across rows) and to
    multi-column layouts where one printed line carries several records.
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

    # ---- Path B: multi-record line parser over stream.lines --------------
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
