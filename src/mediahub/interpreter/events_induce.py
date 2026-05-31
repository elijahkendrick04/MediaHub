"""
events_induce.py — locate event-header lines and parse their fields.

Reads all vocabulary from data/ontology/ — no swim-term literals in this file.

Detection strategy:
  1. Load regex patterns for gender/distance/stroke/course from ontology.
  2. Scan lines for section breaks (blank lines, font-size jumps, "Event N").
  3. For each candidate header line, attempt to extract all four fields.
  4. Build InterpretedEvent stubs (swims filled in by rows.py).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .ontology_loader import OntologyLoader
from .schema_dataclasses import IngestStream, InterpretedEvent, Line

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled pattern helpers (built from ontology at runtime)
# ---------------------------------------------------------------------------

# Strict distance: number must be followed by a unit OR appear adjacent to a stroke keyword.
# We try the strict (with-unit) form first, then a positional fallback that rejects digits
# adjacent to event-numbering words like "Event 101".
_DISTANCE_RE_STRICT = re.compile(r"\b(\d{2,4})\s*(?:m\b|meters?\b|metres?\b)", re.IGNORECASE)
_DISTANCE_RE_LOOSE = re.compile(r"\b(\d{2,4})\b", re.IGNORECASE)
# Lookbehind set: words/keywords that mean the following number is NOT a distance.
_NOT_DISTANCE_PRE = re.compile(r"(?:event|race|heat|session|day)\s*$", re.IGNORECASE)
_DISTANCE_RE = _DISTANCE_RE_STRICT  # back-compat alias for any external import
_EVENT_NUM_RE = re.compile(r"\bevent\s+(\d+)\b", re.IGNORECASE)
_AGE_BAND_RE = re.compile(
    r"\b(under\s*\d+|u\s*\d+|age\s+\d+[\-–]\d+|\d+[\-–]\d+|open|senior|junior|masters?)\b",
    re.IGNORECASE,
)


@dataclass
class _EventContext:
    line: Line
    raw_header: str
    gender: Optional[str] = None
    distance_m: Optional[int] = None
    stroke: Optional[str] = None
    course: Optional[str] = None
    age_band: Optional[str] = None
    confidence: float = 0.0


def _build_ontology_patterns(
    ontology: OntologyLoader,
) -> tuple[re.Pattern, dict[str, str], re.Pattern, dict[str, str], re.Pattern, dict[str, str]]:
    """Build compiled regex + canonical-map for strokes, courses, genders."""
    stroke_map = ontology.canonical_map("strokes")
    course_map = ontology.canonical_map("courses")
    gender_map = ontology.canonical_map("genders")

    def make_pattern(mapping: dict[str, str]) -> re.Pattern:
        aliases = sorted(mapping.keys(), key=len, reverse=True)
        if not aliases:
            return re.compile(r"(?!x)x")  # never-matches placeholder
        escaped = [re.escape(a) for a in aliases]
        return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)

    return (
        make_pattern(stroke_map),
        stroke_map,
        make_pattern(course_map),
        course_map,
        make_pattern(gender_map),
        gender_map,
    )


# ---------------------------------------------------------------------------
# Header-line scoring
# ---------------------------------------------------------------------------


def _score_header_line(
    text: str,
    stroke_re: re.Pattern,
    course_re: re.Pattern,
    gender_re: re.Pattern,
) -> float:
    """
    Return a confidence score for how likely this line is an event header.
    Criteria:
      - Contains a distance (number followed by optional unit)
      - Contains a stroke term
      - May contain gender / course / event number
    """
    score = 0.0
    has_distance = bool(_DISTANCE_RE.search(text))
    has_stroke = bool(stroke_re.search(text))
    has_gender = bool(gender_re.search(text))
    has_course = bool(course_re.search(text))
    has_event_num = bool(_EVENT_NUM_RE.search(text))

    if has_stroke:
        score += 0.50
    if has_distance:
        score += 0.30
    if has_gender:
        score += 0.10
    if has_course:
        score += 0.05
    if has_event_num:
        score += 0.05

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def _extract_fields(
    text: str,
    stroke_re: re.Pattern,
    stroke_map: dict[str, str],
    course_re: re.Pattern,
    course_map: dict[str, str],
    gender_re: re.Pattern,
    gender_map: dict[str, str],
) -> dict:
    fields: dict = {}

    # Stroke
    sm = stroke_re.search(text)
    if sm:
        fields["stroke"] = stroke_map.get(sm.group(0).lower())

    # Course
    cm = course_re.search(text)
    if cm:
        fields["course"] = course_map.get(cm.group(0).lower())

    # Gender
    gm = gender_re.search(text)
    if gm:
        fields["gender"] = gender_map.get(gm.group(0).lower())

    # Distance — prefer strictly-unitted matches first.
    dm = _DISTANCE_RE_STRICT.search(text)
    if not dm:
        # Fallback: scan all bare numbers, skip ones immediately preceded by
        # event-numbering words like "Event 101".
        for m in _DISTANCE_RE_LOOSE.finditer(text):
            preceding = text[: m.start()]
            if _NOT_DISTANCE_PRE.search(preceding):
                continue
            val = int(m.group(1))
            if 25 <= val <= 2000 and val % 25 == 0:
                # Plausible distance: standard pool distances are multiples of 25.
                fields["distance_m"] = val
                break
    else:
        val = int(dm.group(1))
        if 25 <= val <= 2000:
            fields["distance_m"] = val

    # Age band
    am = _AGE_BAND_RE.search(text)
    if am:
        fields["age_band"] = am.group(0).strip()

    return fields


# ---------------------------------------------------------------------------
# Section-break detection
# ---------------------------------------------------------------------------


def _is_section_break(
    line: Line,
    prev_line: Optional[Line],
    event_num_re: re.Pattern = _EVENT_NUM_RE,
) -> bool:
    """Heuristic: blank lines, big font-size jumps, or 'Event N' markers."""
    text = line.text.strip()
    if not text:
        return True
    if event_num_re.search(text):
        return True
    # Font-size jump (only for PDF lines with hints)
    if (
        prev_line is not None
        and line.font_size_hint is not None
        and prev_line.font_size_hint is not None
        and line.font_size_hint > prev_line.font_size_hint * 1.4
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def induce_events(
    stream: IngestStream,
    ontology: OntologyLoader | None = None,
    header_threshold: float = 0.55,
) -> list[InterpretedEvent]:
    """
    Scan *stream* and return a list of InterpretedEvent stubs.

    Swims are left empty; rows.py fills them in.
    """
    if ontology is None:
        ontology = OntologyLoader()

    (
        stroke_re,
        stroke_map,
        course_re,
        course_map,
        gender_re,
        gender_map,
    ) = _build_ontology_patterns(ontology)

    events: list[InterpretedEvent] = []
    prev_line: Optional[Line] = None

    for line in stream.lines:
        text = line.text.strip()
        if not text:
            prev_line = line
            continue

        score = _score_header_line(text, stroke_re, course_re, gender_re)
        if score >= header_threshold:
            fields = _extract_fields(
                text, stroke_re, stroke_map, course_re, course_map, gender_re, gender_map
            )
            ev = InterpretedEvent(
                gender=fields.get("gender"),
                distance_m=fields.get("distance_m"),
                stroke=fields.get("stroke"),
                course=fields.get("course"),
                age_band=fields.get("age_band"),
                swims=[],
                confidence=score,
                raw_header=text,
            )
            events.append(ev)
            log.debug("Event detected (conf=%.2f): %s", score, text[:80])

        prev_line = line

    log.info("Induced %d events from %d lines", len(events), len(stream.lines))
    return events
