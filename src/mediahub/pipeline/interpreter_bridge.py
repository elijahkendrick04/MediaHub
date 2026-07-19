"""
interpreter_bridge.py — Convert V7.5 `InterpretedMeet` to canonical V4 `Meet`.

The interpreter package emits domain-agnostic data (`InterpretedMeet`,
`InterpretedEvent`, `InterpretedSwim`). The rest of the V4/V5 pipeline
(detectors, ranker, content pack, recognition) consumes the canonical
`Meet` object defined in `swim_content_v4.canonical`.

This module is the only seam between those two worlds. It performs:

1. Stroke / course canonicalisation via the runtime ontology (delegated to
   `interpreter.ontology_loader.OntologyLoader` rather than a hard-coded
   map).
2. Time canonicalisation: "mm:ss.cc" / "ss.cc" → centiseconds.
3. Swimmer keying: stable keys derived from (club_code, last, first), so
   the same swimmer across multiple events gets the same key.
4. Club registration: every club name observed becomes a canonical
   `Club` with a deterministic short code.

No domain literals (governing bodies, source domains) are introduced
here — the caller is responsible for choosing how to enrich those
fields.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from mediahub.interpreter.schema_dataclasses import (
    InterpretedMeet,
)

from mediahub.web.canonical import (
    Meet,
    Club,
    Swimmer,
    RaceResult,
)


# ---------------------------------------------------------------------------
# Stroke + course canonicalisation
# ---------------------------------------------------------------------------
#
# The interpreter writes back the canonical stroke names from its
# ontology (e.g. "Freestyle", "Butterfly"). The downstream V3/V5 pipeline
# expects two-letter codes (FR, BK, BR, FL, IM). We map by lowercased
# substring lookup so future ontology entries work without code change.

_CANONICAL_STROKE_TO_CODE: dict[str, str] = {
    "freestyle": "FR",
    "free": "FR",
    "backstroke": "BK",
    "back": "BK",
    "breaststroke": "BR",
    "breast": "BR",
    "butterfly": "FL",
    "fly": "FL",
    "individual medley": "IM",
    "medley": "IM",
    "im": "IM",
}


def _stroke_code(stroke: Optional[str]) -> Optional[str]:
    # Unresolved input (missing, or a label the ontology map does not cover)
    # returns None — never a silent "FR" guess. The caller stores an honest-empty
    # stroke and flags the swim for review, so PB/medal comparison never runs
    # under a fabricated event key.
    if not stroke:
        return None
    s = stroke.strip().lower()
    if s in _CANONICAL_STROKE_TO_CODE:
        return _CANONICAL_STROKE_TO_CODE[s]
    # Substring fallback for compound labels
    for key, code in _CANONICAL_STROKE_TO_CODE.items():
        if key in s:
            return code
    return None


def _course_code(course: Optional[str]) -> Optional[str]:
    # Unresolved input returns None — never a silent "LC" guess (see _stroke_code).
    if not course:
        return None
    c = course.strip().upper()
    if c in ("LC", "SC", "Y"):
        return c
    if "LONG" in c:
        return "LC"
    if "SHORT" in c:
        return "SC"
    return None


def _gender_code(gender: Optional[str]) -> str:
    if not gender:
        return ""
    g = gender.strip().upper()
    if g in ("M", "F", "X"):
        return g
    if g.startswith("MAL"):
        return "M"
    if g.startswith("FEM"):
        return "F"
    if g.startswith("MIX") or g == "OPEN":
        return "X"
    return ""


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------

# The fraction separator is a period ONLY. A colon is the minutes:seconds
# separator (the optional leading group), so accepting `:` before the fraction
# too (the old `[.:]`) parsed a bare mm:ss like "23:45" as 23.45s — a ~60x error.
# A time with no centiseconds no longer matches and is rejected (None → the swim
# is flagged) rather than silently mis-read.
_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2})\.(\d{1,2})\s*$")


def _time_to_cs(time_str: Optional[str]) -> Optional[int]:
    """Convert "1:23.45" or "23.45" → centiseconds."""
    if not time_str:
        return None
    s = str(time_str).strip()
    if not s:
        return None
    m = _TIME_RE.match(s)
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    secs = int(m.group(2))
    frac = m.group(3)
    if len(frac) == 1:
        frac_cs = int(frac) * 10
    else:
        frac_cs = int(frac[:2])
    cs = mins * 6000 + secs * 100 + frac_cs
    return cs if cs > 0 else None


# Non-numeric time-column markers -> canonical (dq, status). Only "DQ" is an
# actual disqualification; DNS/NS/DNC are non-starts (the swimmer never raced),
# SCR/WD are scratches/withdrawals, and DNF is a did-not-finish -- none of them
# is a DQ, so collapsing them all to "dq" erased the distinction (deep-review
# #51). Every one of them still has finals_time_cs=None, so the shared
# `dq or finals_time_cs is None` gate the detectors use keeps them out of PB /
# record / milestone detection exactly as before; only the human-facing status
# label changes. Any unknown/blank marker stays the conservative "dq".
_NO_TIME_MARKER_STATUS: dict[str, tuple[bool, str]] = {
    "DQ": (True, "dq"),
    "DNS": (False, "dns"),
    "NS": (False, "dns"),
    "DNC": (False, "dns"),
    "DNF": (False, "dnf"),
    "SCR": (False, "scratch"),
    "WD": (False, "scratch"),
}


def _no_time_status(marker: Optional[str]) -> tuple[bool, str]:
    """Map a non-numeric time-column marker to (dq, canonical status)."""
    key = (marker or "").strip().upper()
    return _NO_TIME_MARKER_STATUS.get(key, (True, "dq"))


# ---------------------------------------------------------------------------
# Name + club helpers
# ---------------------------------------------------------------------------

_NAME_SPLIT_RE = re.compile(r"[\s,]+")


def _split_name(full: str) -> tuple[str, str]:
    """
    Split a swimmer name into (first, last). Accepts:
      "Smith, John"     → ("John", "Smith")
      "John Smith"      → ("John", "Smith")
      "John James Smith"→ ("John James", "Smith")
    """
    if not full:
        return ("", "")
    s = full.strip()
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[1], parts[0])
    parts = s.split()
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


def _slugify(value: str) -> str:
    """Produce a deterministic ASCII slug from a free-form club name."""
    if not value:
        return ""
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_")
    return cleaned.lower() or "club"


# SportSystems encodes finals in the event header: "EVENT 132 B FINAL OF EVENT
# 101 …" (B final), "EVENT 131 FINAL OF EVENT 101 …" (the A/main final). Heats
# carry no "FINAL" token. We surface the round so the summary can say which final
# a result came from, and rank the A-final above the B/C-final for posting.
_FINAL_LETTER_RE = re.compile(r"\b([ABC])\s+FINAL\b", re.IGNORECASE)
_FINAL_OF_RE = re.compile(r"\bFINAL\s+OF\s+EVENT\b|\bFINAL\b", re.IGNORECASE)
# Headers whose FINAL token does NOT mean the A/main final: a "Timed Final(s)"
# is the single all-in final (rank 0, per the docstring below) and a
# "Semi-Final" is not a final at all — neither may be mislabelled "A Final".
_NOT_A_FINAL_RE = re.compile(r"\bSEMI[- ]?FINALS?\b|\bTIMED\s+FINALS?\b", re.IGNORECASE)

# Meet event number from a header line, e.g. "Event 202  Female 10-13 200 LC
# Meter Freestyle" → "202". HY-TEK reprints the same physical swim under several
# overlapping age-band sub-headers that all share ONE event number, so the
# number anchors the de-dup identity to the event rather than the printed band.
_EVENT_NUM_RE = re.compile(r"\bevent\s+(\d+)\b", re.IGNORECASE)


def _event_number(raw_header: Optional[str]) -> str:
    """Return the meet event number printed in an event header, or "".

    Used as a de-dup anchor: two age-band sub-headers of the same event
    ("Event 202 Female 10-13" / "Event 202 Female 13 Year Olds") share the
    number, so the same swim listed under both collapses to one result.
    """
    m = _EVENT_NUM_RE.search(raw_header or "")
    return m.group(1) if m else ""


def _detect_final_round(raw_header: Optional[str]) -> tuple[str, int]:
    """Return ``(label, rank)`` for an event header.

    rank: 1 = A/main final (highest posting priority), 2 = B final, 3 = C final,
    0 = heat / single timed final (no explicit final round).
    """
    h = (raw_header or "").strip()
    if not h:
        return "", 0
    m = _FINAL_LETTER_RE.search(h)
    if m:
        letter = m.group(1).upper()
        return f"{letter} Final", {"A": 1, "B": 2, "C": 3}[letter]
    if _NOT_A_FINAL_RE.search(h):
        # "Timed Final(s)" / "Semi-Final" carry the FINAL token but are not the
        # A/main final — they keep the single-timed-final reading (rank 0).
        return "", 0
    if _FINAL_OF_RE.search(h):
        # "FINAL OF EVENT …" with no A/B/C qualifier is the main (A) final.
        return "A Final", 1
    return "", 0


def _club_code(club_name: Optional[str]) -> str:
    """
    Derive a short stable code for a club from its name.

    For interpreter-sourced data we have only free-form names — no
    Hytek 4-letter codes — so the slug IS the code. Downstream
    detectors compare codes by equality, so any deterministic
    transformation works.
    """
    if not club_name:
        return ""
    slug = _slugify(club_name)
    return slug


# ---------------------------------------------------------------------------
# Distance handling
# ---------------------------------------------------------------------------


def _coerce_distance(d) -> int:
    if d is None:
        return 0
    try:
        return int(d)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _canonical_result_identity(r: RaceResult) -> tuple:
    """Stable identity for a parsed swim — used to drop reprints.

    HY-TEK MEET MANAGER reprints the SAME physical swim two ways: an event
    header repeated across a page break (identical rows), AND the same event
    re-listed under overlapping age-band sub-headers ("Event 202 Female 10-13"
    then "Event 202 Female 13 Year Olds") — where the only things that change
    are the age-band banner and the place WITHIN that band. So the identity is
    the physical swim: (event number + swimmer + final time), plus the
    distance/stroke/course/gender that pin the event when no number is printed,
    and the round / A-B-final label that genuinely separate a heat from a final
    of the same event. It deliberately EXCLUDES age_band and place — the two
    fields the age-band reprint mutates — so one swim is never queued twice.

    Known limitation (deliberate): when the reprints carry different
    band-relative places (3rd in "10-13", 1st in "13 Year Olds"), the FIRST
    printing in document order survives, so the kept ``(age_band, place)``
    pair is print-order dependent and a later band's award place is dropped.
    No tiebreak (min place / narrowest band) is applied because which band's
    place is award-bearing depends on the meet's award structure, which the
    file does not state — either choice under-reports a real award in some
    meet shapes. The survivor is always one coherent printed pair, never a
    stitched hybrid.
    """
    extra = r.extra or {}
    return (
        r.swimmer_key,
        extra.get("event_number", ""),
        r.distance,
        r.stroke,
        r.course,
        r.gender,
        r.finals_time_cs,
        r.round,
        r.status,
        r.swim_date,
        extra.get("final_label", ""),
        extra.get("final_rank", 0),
    )


def interpreted_to_canonical(
    interpreted: InterpretedMeet,
    *,
    source_filename: str,
    source_format: Optional[str] = None,
) -> Meet:
    """
    Convert an `InterpretedMeet` into a canonical `Meet` ready for the
    rest of the pipeline.

    Parameters
    ----------
    interpreted:
        Output of `interpreter.interpret_document(...)`.
    source_filename:
        The original filename (passed through for audit).
    source_format:
        Override for `Meet.source_format`. If None, derives from
        `interpreted.sources_used` (which contains `format:<X>` strings).
    """
    fmt = source_format
    if fmt is None:
        for src in interpreted.sources_used or []:
            if isinstance(src, str) and src.startswith("format:"):
                fmt = src.split(":", 1)[1] or None
                break
    fmt = fmt or "unknown"

    course_default = _course_code(interpreted.course_default)

    start_date = None
    end_date = None
    if interpreted.dates:
        start_date = interpreted.dates[0]
        end_date = interpreted.dates[1] if len(interpreted.dates) > 1 else interpreted.dates[0]

    meet = Meet(
        name=interpreted.meet_name or "(unknown)",
        venue=interpreted.venue,
        course=course_default or "LC",
        start_date=start_date,
        end_date=end_date,
        host_club_code=None,
        governing_body=interpreted.governing_body_hint,
        source_format=fmt,
        source_filename=source_filename,
    )

    # Per-key swimmer cache to preserve identity across events.
    swimmer_lookup: dict[tuple[str, str, str], str] = {}
    # Exact-reprint guard. HY-TEK MEET MANAGER printouts repeat an event's
    # header and its result rows whenever the event spills onto a new page, so
    # the same physical swim gets parsed twice. Left unchecked it surfaces as
    # duplicate cards downstream — and breaks per-card approval, since every
    # card keyed by that one swim_id flips together. Collapse the reprints here,
    # at the single seam every parse path funnels through.
    seen_result_keys: set[tuple] = set()
    duplicate_rows_dropped = 0
    # Swims whose stroke or course could not be resolved: kept in the meet for an
    # honest count/provenance, but with empty ("") stroke/course so no PB/medal
    # comparison runs under a guessed event key. Surfaced as a needs-review warning.
    unresolved_event_swims = 0

    for event in interpreted.events or []:
        # A relay event ("4 x 100m Freestyle Relay") is not an individual swim.
        # The free-text inducer reuses individual distance/stroke vocabulary for
        # relay headers, so without this guard a relay leg would seed a bogus
        # individual RaceResult (e.g. "100m Freestyle") and pollute PB / medal
        # detection (finding #65). Relays are not modelled as individual results.
        if getattr(event, "is_relay", False):
            continue
        ev_distance = _coerce_distance(event.distance_m)
        ev_stroke = _stroke_code(event.stroke)
        ev_course = _course_code(event.course) if event.course else course_default
        # Either code unresolved ⇒ we cannot classify this event; the swim is
        # stored with empty stroke/course (an unmatchable PB key) and counted so a
        # meet-level needs-review warning can be raised after the loop.
        ev_unresolved = ev_stroke is None or ev_course is None
        ev_gender = _gender_code(event.gender)
        ev_age_band = event.age_band or ""
        ev_final_label, ev_final_rank = _detect_final_round(event.raw_header)
        ev_event_number = _event_number(event.raw_header)

        for swim in event.swims or []:
            time_cs = _time_to_cs(swim.time)
            race_dq, race_status = (
                (False, "completed") if time_cs is not None else _no_time_status(swim.time)
            )
            club_name = (swim.club or "").strip()
            club_code = _club_code(club_name)

            if club_code and club_code not in meet.clubs:
                meet.clubs[club_code] = Club(
                    code=club_code,
                    name=club_name or club_code,
                    short_name=club_name or club_code,
                )

            first, last = _split_name(swim.swimmer_name or "")
            key_tuple = (first.lower(), last.lower(), club_code)
            if key_tuple in swimmer_lookup:
                swimmer_key = swimmer_lookup[key_tuple]
                # A later swim may carry the member id / age the first one lacked.
                _sw = meet.swimmers.get(swimmer_key)
                if _sw is not None:
                    if not getattr(_sw, "asa_id", None) and getattr(swim, "asa_id", None):
                        _sw.asa_id = swim.asa_id
                    if getattr(_sw, "age_at_meet", None) is None and getattr(swim, "age", None):
                        _sw.age_at_meet = swim.age
            else:
                base = f"{club_code}:{last},{first}".replace(" ", "_")
                if not base.strip(":,"):
                    # Fully empty name — synthesise from raw row.
                    base = f"{club_code}:row{len(meet.swimmers)}"
                swimmer_key = base
                while swimmer_key in meet.swimmers:
                    swimmer_key = f"{base}_{len(swimmer_lookup)}"
                meet.swimmers[swimmer_key] = Swimmer(
                    swimmer_key=swimmer_key,
                    first_name=first,
                    last_name=last,
                    gender=ev_gender,
                    age_at_meet=getattr(swim, "age", None),
                    asa_id=(getattr(swim, "asa_id", None) or None),
                    club_code=club_code,
                    club_name=club_name or club_code,
                    identity_confidence="medium",
                )
                swimmer_lookup[key_tuple] = swimmer_key

            place = swim.place
            try:
                place_int: Optional[int] = int(place) if place is not None else None
            except (TypeError, ValueError):
                place_int = None

            # Round: a row carrying a finals-qualification marker ("q") is a
            # heat/preliminary swim, so it must NOT be read as a final-round
            # result (the medal detector awards medals only from finals). Every
            # other row keeps the default timed-final reading. Mapping prelim →
            # the canonical "heat" code is what keeps a heat place-1 from
            # surfacing as a fabricated gold while the genuine final still wins
            # its medal with the final time.
            swim_round = "heat" if getattr(swim, "round_hint", None) == "prelim" else "timed_final"

            result = RaceResult(
                swimmer_key=swimmer_key,
                club_code=club_code or None,
                distance=ev_distance,
                stroke=ev_stroke or "",
                course=ev_course or "",
                gender=ev_gender,
                age_band=ev_age_band,
                finals_time_cs=time_cs,
                seed_time_cs=None,
                place=place_int,
                round=swim_round,
                dq=race_dq,
                status=race_status,
                swim_date=start_date,
                splits=[],
                extra={
                    "interpreter_confidence": swim.confidence,
                    "raw_row": swim.raw_row,
                    "field_confidence": dict(swim.field_confidence or {}),
                    # Round/final provenance: a swim from a B-final must read
                    # as "B Final", not be confused with the A-final win, and
                    # the A-final (rank 1) outranks the B-final (rank 2) for
                    # posting. Empty label / rank 0 = heat or single timed final.
                    "final_label": ev_final_label,
                    "final_rank": ev_final_rank,
                    # Meet event number ("202"), parsed from the header. Anchors
                    # the de-dup identity so the same swim reprinted under
                    # overlapping age-band sub-headers of one event collapses.
                    "event_number": ev_event_number,
                },
            )
            ident = _canonical_result_identity(result)
            if ident in seen_result_keys:
                duplicate_rows_dropped += 1
                continue
            seen_result_keys.add(ident)
            meet.results.append(result)
            if ev_unresolved:
                unresolved_event_swims += 1

    if duplicate_rows_dropped:
        meet.add_warning(
            "duplicate_results_collapsed",
            f"{duplicate_rows_dropped} duplicate result row(s) were collapsed "
            "— the source repeated identical swims (e.g. an event header "
            "reprinted across a page break).",
            severity="info",
        )

    if unresolved_event_swims:
        meet.add_warning(
            "unresolved_event",
            f"{unresolved_event_swims} swim(s) had an unrecognised stroke or "
            "course and were left unclassified (no event bucket). Their PB "
            "comparison was skipped and they need review against the source file.",
            severity="warn",
        )

    return meet


# ---------------------------------------------------------------------------
# Club extraction (used by the universal club picker)
# ---------------------------------------------------------------------------


_CLUB_NOISE_RE = re.compile(r"^\s*\d+m\s|^\s*\d+:\d+\b|^\s*\d+\.\d+\s*$")
_TIME_TOKEN_RE = re.compile(r"\d+[:.]\d+")
_DISTANCE_TOKEN_RE = re.compile(r"\b\d{2,4}m\b", re.IGNORECASE)


def _looks_like_club_name(value: str) -> bool:
    """Heuristic: drop entries that are obviously split times / numerics
    rather than club names. The interpreter occasionally mis-aligns the
    'club' column on rows where a long-distance split bleeds over.
    """
    if not value:
        return False
    if _CLUB_NOISE_RE.match(value):
        return False
    # Reject anything that contains a time token (split times bleeding over)
    if _TIME_TOKEN_RE.search(value):
        return False
    # Reject anything that contains a distance token like "1000m" or "50m"
    if _DISTANCE_TOKEN_RE.search(value):
        return False
    # A club name must contain at least two consecutive alphabetic characters
    if not re.search(r"[A-Za-z]{2,}", value):
        return False
    # Drop pure time-looking strings like "12:34.56".
    if re.fullmatch(r"\s*\d+[:.]\d+(?:[.:]\d+)?\s*", value):
        return False
    # Reject bare 1-2 token abbreviations of <=4 chars total ("Aq", "Club")
    # which are almost always row-misalignment artifacts, not real club names.
    cleaned = value.strip()
    if len(cleaned) <= 4 and " " not in cleaned:
        return False
    return True


def extract_clubs_from_interpreted(interpreted: InterpretedMeet) -> list[str]:
    """
    Return the unique list of club names that appear in any swim of the
    interpreted document, sorted alphabetically. Obvious noise rows
    (split times mis-classified as club names) are filtered out.
    """
    seen: set[str] = set()
    for event in interpreted.events or []:
        for swim in event.swims or []:
            club = (swim.club or "").strip()
            if club and _looks_like_club_name(club):
                seen.add(club)
    return sorted(seen)


# Common short-form abbreviations used in printed result lists. These are
# *not* a fixed taxonomy of clubs — they are generic morphology rules
# that let "Co Manch Aq" expand into tokens equivalent to
# "City of Manchester Aquatics". The list is a learning surface: new
# abbreviations encountered in real files can be added here without
# touching detection logic.
_TOKEN_ALIASES: dict[str, str] = {
    "co": "city",
    "city": "city",
    "manch": "manchester",
    "manchester": "manchester",
    "aq": "aquatics",
    "aquatics": "aquatics",
    "aqu": "aquatics",
    "swim": "swimming",
    "swimming": "swimming",
    "sc": "club",
    "club": "club",
    "asc": "swimming",
    "univ": "university",
    "uni": "university",
    "university": "university",
    "of": "of",
}


def _normalise_tokens(value: str) -> set[str]:
    """
    Lower-case, strip punctuation, split into tokens, expand common
    abbreviations to their long form. Used for fuzzy club matching.
    """
    if not value:
        return set()
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", value.lower()).strip()
    if not cleaned:
        return set()
    out: set[str] = set()
    for tok in cleaned.split():
        tok = tok.strip()
        if not tok or tok in ("the", "of", "and", "&"):
            continue
        out.add(_TOKEN_ALIASES.get(tok, tok))
    return out


# Organisation-type words that the aliases above normalise TO. They appear in
# almost every club name ("City of …", "… Swimming Club", "… Aquatics") so they
# describe the *kind* of club, not its identity — the identity is the place name
# (cardiff, brighton, manchester). They must NOT count as a distinguishing token,
# or every "Co …" club would match every other (e.g. "Co Brighton" matching
# "City of Cardiff" on the shared token "city").
_GENERIC_CLUB_TOKENS: frozenset[str] = frozenset(
    {"city", "swimming", "club", "aquatics", "university", "of"}
)


def _name_tokens_match(target: str, candidate: str) -> bool:
    """
    Decide whether *candidate* refers to the same club as *target*.
    A match requires either:
      - identical normalised forms, OR
      - one set of significant tokens contains the other (subset), OR
      - shared identity tokens (length ≥ 4, not generic org-type words).
    """
    a = _normalise_tokens(target)
    b = _normalise_tokens(candidate)
    if not a or not b:
        return False
    if a == b:
        return True
    # Subset match — but only when the smaller set carries at least one
    # NON-generic identity token. A candidate normalising to only org-type
    # words ("Co" → {city}, "Co Aq" → {city, aquatics}) is a subset of nearly
    # every club name and would leak the wrong club's swimmers in.
    subset = a if a.issubset(b) else (b if b.issubset(a) else None)
    if subset is not None and any(t not in _GENERIC_CLUB_TOKENS for t in subset):
        return True
    # Identity tokens: significant (length ≥ 4) AND not a generic org-type word,
    # so the match turns on the distinctive place name, not "city"/"swimming".
    sig_a = {t for t in a if len(t) >= 4 and t not in _GENERIC_CLUB_TOKENS}
    sig_b = {t for t in b if len(t) >= 4 and t not in _GENERIC_CLUB_TOKENS}
    if not sig_a or not sig_b:
        return False
    smaller, larger = (sig_a, sig_b) if len(sig_a) <= len(sig_b) else (sig_b, sig_a)
    return bool(smaller) and smaller.issubset(larger)


def filter_meet_by_club_name(meet: Meet, club_filter: str) -> tuple[list[RaceResult], set[str]]:
    """
    Return (our_results, our_swimmer_keys) for the given club name.
    Matching is fuzzy and tokenised so user-typed names and printed
    abbreviations both work (e.g. "City of Manchester Aquatics" matches
    "Co Manch Aq").
    """
    if not club_filter:
        return [], set()

    target_code = _club_code(club_filter)
    target_lower = club_filter.strip().lower()

    our_results: list[RaceResult] = []
    our_keys: set[str] = set()

    for r in meet.results:
        cc = (r.club_code or "").lower()
        sw = meet.swimmers.get(r.swimmer_key)
        cname = (getattr(sw, "club_name", "") or "").lower() if sw else ""

        match = False
        if cc == target_code or cc == target_lower:
            match = True
        elif cname == target_lower:
            match = True
        elif _name_tokens_match(target_lower, cname):
            match = True

        if match:
            our_results.append(r)
            our_keys.add(r.swimmer_key)

    return our_results, our_keys
