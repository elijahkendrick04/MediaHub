"""
pb_discovery/parse_pbs.py — Parse PB rows from any layout via the interpreter.

The interpreter package is imported lazily to handle the case where it hasn't
been built yet (parallel subagent is building it).

At runtime expects:
    interpreter.interpret_document(bytes, hint='profile_page') -> dict

The returned dict is expected to contain a 'pbs' key with a list of PB rows,
or a 'rows' key with table-like data that can be mapped to PBRow objects.

Falls back to heuristic regex extraction if the interpreter is not available
or if its output doesn't contain structured PB data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .fetch_profile import ProfilePage

log = logging.getLogger(__name__)


@dataclass
class PBRow:
    """A single personal best entry."""

    event: str  # Canonical event name, e.g. "100m Freestyle"
    course: str  # "LC" (long course) or "SC" (short course)
    time_canonical: str  # e.g. "1:02.34"
    date: Optional[str] = None
    meet: Optional[str] = None
    rank: Optional[int] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "course": self.course,
            "time_canonical": self.time_canonical,
            "date": self.date,
            "meet": self.meet,
            "rank": self.rank,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PBRow":
        return cls(
            event=d.get("event", ""),
            course=d.get("course", ""),
            time_canonical=d.get("time_canonical", ""),
            date=d.get("date"),
            meet=d.get("meet"),
            rank=d.get("rank"),
            raw=d.get("raw", {}),
        )


# ── Heuristic extraction patterns ────────────────────────────────────────────

# Time pattern: matches formats like 1:02.34, 59.87, 2:01:02.34
_TIME_RE = re.compile(
    r"\b(?:\d{1,2}:)?\d{1,2}:\d{2}\.\d{1,2}\b"  # MM:SS.ss or HH:MM:SS.ss
    r"|\b\d{2,3}\.\d{2}\b"  # SS.ss (e.g. 59.87)
)

# Event distance patterns
_DISTANCE_RE = re.compile(r"\b(50|100|200|400|800|1500|1650)\s*m?\b", re.IGNORECASE)

# Stroke name patterns (canonical form detection)
_STROKE_PATTERNS = [
    (re.compile(r"\b(free(?:style)?)\b", re.IGNORECASE), "Freestyle"),
    (re.compile(r"\b(back(?:stroke)?)\b", re.IGNORECASE), "Backstroke"),
    (re.compile(r"\b(breast(?:stroke)?)\b", re.IGNORECASE), "Breaststroke"),
    (re.compile(r"\b(butt?erfly|fly)\b", re.IGNORECASE), "Butterfly"),
    (re.compile(r"\b(i\.?m\.?|individual\s+medley|medley)\b", re.IGNORECASE), "Individual Medley"),
]

# Course detection
_LC_RE = re.compile(r"\b(?:LC|LCM|long\s+course|50\s*m\s+pool)\b", re.IGNORECASE)
_SC_RE = re.compile(r"\b(?:SC|SCM|short\s+course|25\s*m\s+pool)\b", re.IGNORECASE)

# Date pattern
_DATE_RE = re.compile(
    r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})\b"
)

# Relay pattern. A relay split ("4 x 100m Freestyle Relay 3:45.00") must never
# seed an individual-event PB baseline — it would make every real individual swim
# look like a huge new PB (F01). Two independent signals:
#   * an "N x DIST" leg count ("4 x 100", "4×100", "4X50") — always a relay;
#   * the word "relay" *adjacent to the event descriptor* (a stroke or an "Nm"
#     distance, either order). Requiring adjacency stops a meet/venue name that
#     merely contains "Relays" (e.g. "Manchester Relays") from suppressing a real
#     individual PB on the heuristic path, which scans the whole row including the
#     meet column. "×" is the Unicode multiplication sign for "4 × 100" layouts.
_STROKE_WORD = (
    r"(?:free(?:style)?|back(?:stroke)?|breast(?:stroke)?|butt?erfly|fly|medley|i\.?m\.?)"
)
_DIST_TOKEN = r"(?:\d{2,4}\s*m)"
_RELAY_RE = re.compile(
    r"\b\d+\s*[x×]\s*\d"  # "N x DIST" leg count
    r"|(?:" + _DIST_TOKEN + "|" + _STROKE_WORD + r")\s+relays?\b"  # "<distance|stroke> relay"
    r"|\brelays?\s+(?:leg|split|team|" + _DIST_TOKEN + "|" + _STROKE_WORD + r")",  # "relay <…>"
    re.IGNORECASE,
)


def _detect_course(text: str) -> Optional[str]:
    """Detect pool course from surrounding text.

    Returns ``"LC"`` or ``"SC"`` only when the text unambiguously names one
    course. Text carrying BOTH long- and short-course markers (a mixed profile
    page) is ambiguous and returns ``None`` so the caller resolves course per
    row/section rather than flattening the whole page to whichever marker was
    matched first (F09). Absent any marker it also returns ``None``; the caller
    supplies the final fallback.
    """
    has_lc = bool(_LC_RE.search(text))
    has_sc = bool(_SC_RE.search(text))
    if has_lc and not has_sc:
        return "LC"
    if has_sc and not has_lc:
        return "SC"
    return None


# A row/line that is *only* a pool-length marker ("50m" / "25 m" / "50m pool").
# The bare distance would otherwise slip past _detect_course (which requires the
# word "pool"); scoped to the whole stripped cell so a genuine event row like
# "50m Freestyle 24.10" (which carries a stroke) is never mistaken for a heading.
_COURSE_LENGTH_ONLY_RE = re.compile(
    r"^\s*(?:(50)|(25))\s*m?(?:\s*pool)?\s*$", re.IGNORECASE
)


def _section_course(text: str) -> Optional[str]:
    """Course implied by a *section-heading* row/line, else ``None``.

    A heading is a row/line that is (mostly) just a course marker — "Long
    Course" / "Short Course" / "LC" / "SC" / a bare "50m"/"25m" pool length —
    carrying no swim time of its own. Such a row updates the running "current
    section course" the extractor applies to the data rows that follow it (F09:
    a page laid out as an LC heading + its data rows, then an SC heading + its
    data rows, so the two sections file under distinct courses instead of both
    flattening to the page/default course).

    Returns ``None`` for any row that carries a swim time — a data row resolves
    its own course (inline marker → section → page → "LC") and must never be
    treated as a heading.
    """
    if _extract_times(text):
        return None  # a data row, not a heading
    c = _detect_course(text)
    if c is not None:
        return c
    m = _COURSE_LENGTH_ONLY_RE.match(text or "")
    if m:
        return "LC" if m.group(1) else "SC"
    return None


def _detect_stroke_match(text: str) -> tuple[Optional[str], Optional[re.Match]]:
    """Return ``(canonical stroke, match)`` for the first stroke pattern that hits."""
    for pattern, canonical in _STROKE_PATTERNS:
        m = pattern.search(text)
        if m:
            return canonical, m
    return None, None


def _detect_stroke(text: str) -> Optional[str]:
    """Detect stroke name from text."""
    return _detect_stroke_match(text)[0]


def _normalise_time(t: str) -> str:
    """Normalise a time string to MM:SS.ss or SS.ss format."""
    t = t.strip()
    # Already in good format
    return t


def _is_relay_row(text: str) -> bool:
    """True if ``text`` describes a relay leg rather than an individual swim.

    A relay split ("4 x 100m Freestyle Relay 3:45.00") otherwise parses into a
    bogus individual-event baseline ("100m Freestyle" @ 3:45.00) that makes
    every real individual swim look like a huge new PB (F01). Detected via the
    "N x DIST" leg form or the word "relay" adjacent to the event descriptor
    (see ``_RELAY_RE``).
    """
    return bool(_RELAY_RE.search(text or ""))


def _event_is_relay(text: str, dist_m: "re.Match", stroke_m: "re.Match") -> bool:
    """Relay check scoped to the event descriptor within a heuristic row/line.

    The heuristic scans a whole row (event + time + course + date + meet), so an
    unscoped relay check lets a meet/venue name like "Freestyle Relay Cup" or
    "City 400m Relay Gala" drop a real individual PB (F01 over-match). Restrict
    the check to the span covering the event's first distance + stroke, widened
    just enough to catch an adjacent "N x" leg count or a trailing "Relay" —
    mirroring the interpreter path, which only ever inspects the event header.
    """
    lo = min(dist_m.start(), stroke_m.start())
    hi = max(dist_m.end(), stroke_m.end())
    # 6 chars back covers an "N x " / "N × " leg count; 8 forward covers " Relay(s)".
    return _is_relay_row(text[max(0, lo - 6) : hi + 8])


def _extract_times(text: str) -> list[str]:
    """Find swim-time tokens in ``text``, excluding calendar dates.

    ``_TIME_RE``'s SS.ss alternation matches the leading ``dd.mm`` of a dotted
    date such as ``12.03.2024``, so a date column ahead of the time column would
    otherwise yield a fake ``12.03`` s baseline that silently suppresses every
    real PB in that event (F20). Masking recognised date tokens first guarantees
    a token treated as a date is never also treated as a time.
    """
    masked = _DATE_RE.sub(" ", text or "")
    return _TIME_RE.findall(masked)


def _heuristic_extract_pbs(page: ProfilePage) -> list[PBRow]:
    """
    Heuristic fallback: extract PB rows from profile page tables and text.

    Looks for rows containing a time value alongside an event name.
    """
    rows: list[PBRow] = []
    # Course is resolved per row (below). The page-level marker is only a
    # fallback for rows that carry no marker of their own, and is None when the
    # page mixes long- and short-course sections so a marker-bearing row keeps
    # its own course instead of being flattened to the page's first marker (F09).
    # Known limitation: a bare "SC"/"LC" club suffix in a row text (e.g.
    # "Anytown SC") is indistinguishable from a course token, so a course-less
    # row on a page that also has a stray opposite marker can resolve to the
    # club's course. Tolerated over risking the per-row win: the failure is a
    # safe false-negative, never a fabricated PB. The interpreter path is immune
    # in practice (it reads event section headers, not swim/meet rows) unless a
    # header itself embeds a club abbreviation — rare in results-file headers.
    page_course = _detect_course(page.text)

    # Running course for the section the current row belongs to. A course-marker
    # heading row (no swim time) updates this; subsequent data rows inherit it
    # when they carry no inline marker of their own, so an LC section and an SC
    # section on the same page keep distinct courses (F09). Precedence per data
    # row: inline marker → section heading → page marker → final "LC" fallback.
    # Persisted across all tables so a heading in one table governs data rows in
    # the next.
    section_course: Optional[str] = None

    # Try extracting from tables first (more structured)
    for table in page.tables:
        for row in table:
            row_text = " ".join(row)
            sec = _section_course(row_text)
            if sec is not None:
                section_course = sec
            time_matches = _extract_times(row_text)
            if not time_matches:
                continue
            # Detect event components
            dist_m = _DISTANCE_RE.search(row_text)
            stroke, stroke_m = _detect_stroke_match(row_text)
            if dist_m and stroke:
                if _event_is_relay(row_text, dist_m, stroke_m):
                    continue  # relay leg — not an individual-event PB (F01)
                event = f"{dist_m.group(1)}m {stroke}"
                date_m = _DATE_RE.search(row_text)
                rows.append(
                    PBRow(
                        event=event,
                        course=_detect_course(row_text) or section_course or page_course or "LC",
                        time_canonical=_normalise_time(time_matches[0]),
                        date=date_m.group(1) if date_m else None,
                        raw={"row": row, "source": "table_heuristic"},
                    )
                )

    # If no table rows found, try free text extraction
    if not rows:
        section_course = None
        lines = page.text.split("\n")
        for line in lines:
            sec = _section_course(line)
            if sec is not None:
                section_course = sec
            time_matches = _extract_times(line)
            if not time_matches:
                continue
            dist_m = _DISTANCE_RE.search(line)
            stroke, stroke_m = _detect_stroke_match(line)
            if dist_m and stroke:
                if _event_is_relay(line, dist_m, stroke_m):
                    continue  # relay leg — not an individual-event PB (F01)
                event = f"{dist_m.group(1)}m {stroke}"
                date_m = _DATE_RE.search(line)
                rows.append(
                    PBRow(
                        event=event,
                        course=_detect_course(line) or section_course or page_course or "LC",
                        time_canonical=_normalise_time(time_matches[0]),
                        date=date_m.group(1) if date_m else None,
                        raw={"line": line.strip(), "source": "text_heuristic"},
                    )
                )

    return rows


def _interpreter_extract_pbs(page: ProfilePage) -> tuple[list[PBRow], float]:
    """
    Use the interpreter package to extract PBs from a profile page.

    ``interpret_document`` returns an ``InterpretedMeet`` dataclass (events →
    swims), not a dict, so we walk that structure and synthesise one ``PBRow``
    per swim. Event name / course / time follow the same conventions as the
    heuristic extractor (``"{distance}m {stroke}"``, course "LC"/"SC", time via
    ``_normalise_time``). Returns ``(pb_rows, confidence)``; raises
    ``ImportError`` if the interpreter package is unavailable so the caller can
    fall back to the heuristic path.
    """
    try:
        from mediahub.interpreter import interpret_document
    except ImportError:
        raise ImportError(
            "interpreter package not yet built — "
            "provide a stub or wait for the interpreter subagent to complete"
        )

    try:
        raw_bytes = page.text.encode("utf-8")
        result = interpret_document(raw_bytes, hint="profile_page")

        # The interpreter doesn't always resolve course from a sparse profile
        # page; fall back to the event's section header, then the page-level
        # marker the heuristic uses. page_course is None when the page mixes LC
        # and SC sections so a course-less event isn't flattened to one course
        # (F09).
        page_course = _detect_course(page.text)

        pb_rows: list[PBRow] = []
        for event in result.events:
            if event.distance_m and event.stroke:
                event_name = f"{event.distance_m}m {event.stroke}"
            else:
                event_name = (event.raw_header or "").strip()
            if not event_name:
                continue
            # Relay legs must never seed an individual-event PB baseline (F01);
            # the interpreter path folds them into "100m Freestyle" etc. too.
            if _is_relay_row(f"{event_name} {event.raw_header or ''}"):
                continue
            course = event.course or _detect_course(event.raw_header or "") or page_course or "LC"
            for swim in event.swims:
                if not swim.time:
                    continue
                if _is_relay_row(swim.raw_row or ""):
                    continue  # defensive: a relay leg mislabelled onto an event
                pb_rows.append(
                    PBRow(
                        event=event_name,
                        course=course,
                        time_canonical=_normalise_time(swim.time),
                        date=None,
                        meet=result.meet_name,
                        rank=swim.place,
                        raw={
                            "swimmer_name": swim.swimmer_name,
                            "raw_row": swim.raw_row,
                            "source": "interpreter",
                        },
                    )
                )
        return pb_rows, float(result.overall_confidence)
    except Exception:
        # Never crash the discovery flow — but a silently-swallowed interpreter
        # failure degrades every page to the low-confidence heuristic and is
        # undiagnosable in production, so log it with the page URL first.
        log.warning(
            "interpreter PB extraction failed for %s — falling back to heuristic",
            page.url,
            exc_info=True,
        )
        return [], 0.0


def parse_pbs_from_page(
    page: ProfilePage,
    use_interpreter: bool = True,
) -> tuple[list[PBRow], float]:
    """
    Parse PB rows from a fetched profile page.

    Tries the interpreter first (if use_interpreter=True and available),
    then falls back to heuristic extraction.

    Args:
        page: ProfilePage object from fetch_profile.fetch_profile_page()
        use_interpreter: If True, attempt to use interpreter package.

    Returns:
        Tuple of (list[PBRow], confidence_float)
    """
    if not page.fetch_success or not page.text:
        return [], 0.0

    if use_interpreter:
        try:
            rows, conf = _interpreter_extract_pbs(page)
            if rows:
                return rows, conf
        except ImportError:
            pass  # interpreter not built yet, fall through to heuristic
        except Exception:
            log.warning(
                "interpreter PB parse failed for %s — using heuristic extraction",
                page.url,
                exc_info=True,
            )

    # Heuristic fallback
    rows = _heuristic_extract_pbs(page)
    # Heuristic confidence is lower; more rows = slightly higher confidence
    conf = min(0.6, 0.2 + len(rows) * 0.05) if rows else 0.0
    return rows, conf
