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
from typing import Optional, Iterable

from mediahub.interpreter.schema_dataclasses import (
    InterpretedMeet,
    InterpretedEvent,
    InterpretedSwim,
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


def _stroke_code(stroke: Optional[str]) -> str:
    if not stroke:
        return "FR"
    s = stroke.strip().lower()
    if s in _CANONICAL_STROKE_TO_CODE:
        return _CANONICAL_STROKE_TO_CODE[s]
    # Substring fallback for compound labels
    for key, code in _CANONICAL_STROKE_TO_CODE.items():
        if key in s:
            return code
    return "FR"


def _course_code(course: Optional[str]) -> str:
    if not course:
        return "LC"
    c = course.strip().upper()
    if c in ("LC", "SC", "Y"):
        return c
    if "LONG" in c:
        return "LC"
    if "SHORT" in c:
        return "SC"
    return "LC"


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

_TIME_RE = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2})[.:](\d{1,2})\s*$"
)


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
        course=course_default,
        start_date=start_date,
        end_date=end_date,
        host_club_code=None,
        governing_body=interpreted.governing_body_hint,
        source_format=fmt,
        source_filename=source_filename,
    )

    # Per-key swimmer cache to preserve identity across events.
    swimmer_lookup: dict[tuple[str, str, str], str] = {}

    for event in interpreted.events or []:
        ev_distance = _coerce_distance(event.distance_m)
        ev_stroke = _stroke_code(event.stroke)
        ev_course = _course_code(event.course) if event.course else course_default
        ev_gender = _gender_code(event.gender)
        ev_age_band = event.age_band or ""

        for swim in event.swims or []:
            time_cs = _time_to_cs(swim.time)
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
                    age_at_meet=None,
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

            result = RaceResult(
                swimmer_key=swimmer_key,
                club_code=club_code or None,
                distance=ev_distance,
                stroke=ev_stroke,
                course=ev_course,
                gender=ev_gender,
                age_band=ev_age_band,
                finals_time_cs=time_cs,
                seed_time_cs=None,
                place=place_int,
                round="timed_final",
                dq=time_cs is None,
                status="completed" if time_cs else "dq",
                swim_date=start_date,
                splits=[],
                extra={
                    "interpreter_confidence": swim.confidence,
                    "raw_row": swim.raw_row,
                    "field_confidence": dict(swim.field_confidence or {}),
                },
            )
            meet.results.append(result)

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


def _name_tokens_match(target: str, candidate: str) -> bool:
    """
    Decide whether *candidate* refers to the same club as *target*.
    A match requires either:
      - identical normalised forms, OR
      - one set of significant tokens contains the other (subset), OR
      - shared 'core' tokens (length ≥ 4) that overlap substantially.
    """
    a = _normalise_tokens(target)
    b = _normalise_tokens(candidate)
    if not a or not b:
        return False
    if a == b:
        return True
    if a.issubset(b) or b.issubset(a):
        return True
    # Significant tokens (length ≥ 4) — require overlap of all the
    # shorter side's significant tokens.
    sig_a = {t for t in a if len(t) >= 4}
    sig_b = {t for t in b if len(t) >= 4}
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
