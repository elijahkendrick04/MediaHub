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

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .fetch_profile import ProfilePage


@dataclass
class PBRow:
    """A single personal best entry."""
    event: str                    # Canonical event name, e.g. "100m Freestyle"
    course: str                   # "LC" (long course) or "SC" (short course)
    time_canonical: str           # e.g. "1:02.34"
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
    r'\b(?:\d{1,2}:)?\d{1,2}:\d{2}\.\d{1,2}\b'   # MM:SS.ss or HH:MM:SS.ss
    r'|\b\d{2,3}\.\d{2}\b'                          # SS.ss (e.g. 59.87)
)

# Event distance patterns
_DISTANCE_RE = re.compile(
    r'\b(50|100|200|400|800|1500|1650)\s*m?\b', re.IGNORECASE
)

# Stroke name patterns (canonical form detection)
_STROKE_PATTERNS = [
    (re.compile(r'\b(free(?:style)?)\b', re.IGNORECASE), 'Freestyle'),
    (re.compile(r'\b(back(?:stroke)?)\b', re.IGNORECASE), 'Backstroke'),
    (re.compile(r'\b(breast(?:stroke)?)\b', re.IGNORECASE), 'Breaststroke'),
    (re.compile(r'\b(butt?erfly|fly)\b', re.IGNORECASE), 'Butterfly'),
    (re.compile(r'\b(i\.?m\.?|individual\s+medley|medley)\b', re.IGNORECASE), 'Individual Medley'),
]

# Course detection
_LC_RE = re.compile(r'\b(?:LC|LCM|long\s+course|50\s*m\s+pool)\b', re.IGNORECASE)
_SC_RE = re.compile(r'\b(?:SC|SCM|short\s+course|25\s*m\s+pool)\b', re.IGNORECASE)

# Date pattern
_DATE_RE = re.compile(
    r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})\b'
)


def _detect_course(text: str) -> str:
    """Detect pool course from surrounding text."""
    if _LC_RE.search(text):
        return "LC"
    if _SC_RE.search(text):
        return "SC"
    return "LC"  # default assumption


def _detect_stroke(text: str) -> Optional[str]:
    """Detect stroke name from text."""
    for pattern, canonical in _STROKE_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def _normalise_time(t: str) -> str:
    """Normalise a time string to MM:SS.ss or SS.ss format."""
    t = t.strip()
    # Already in good format
    return t


def _heuristic_extract_pbs(page: ProfilePage) -> list[PBRow]:
    """
    Heuristic fallback: extract PB rows from profile page tables and text.

    Looks for rows containing a time value alongside an event name.
    """
    rows: list[PBRow] = []
    course = _detect_course(page.text)

    # Try extracting from tables first (more structured)
    for table in page.tables:
        for row in table:
            row_text = " ".join(row)
            time_matches = _TIME_RE.findall(row_text)
            if not time_matches:
                continue
            # Detect event components
            dist_m = _DISTANCE_RE.search(row_text)
            stroke = _detect_stroke(row_text)
            if dist_m and stroke:
                event = f"{dist_m.group(1)}m {stroke}"
                date_m = _DATE_RE.search(row_text)
                rows.append(PBRow(
                    event=event,
                    course=course,
                    time_canonical=_normalise_time(time_matches[0]),
                    date=date_m.group(1) if date_m else None,
                    raw={"row": row, "source": "table_heuristic"},
                ))

    # If no table rows found, try free text extraction
    if not rows:
        lines = page.text.split('\n')
        for line in lines:
            time_matches = _TIME_RE.findall(line)
            if not time_matches:
                continue
            dist_m = _DISTANCE_RE.search(line)
            stroke = _detect_stroke(line)
            if dist_m and stroke:
                event = f"{dist_m.group(1)}m {stroke}"
                date_m = _DATE_RE.search(line)
                rows.append(PBRow(
                    event=event,
                    course=course,
                    time_canonical=_normalise_time(time_matches[0]),
                    date=date_m.group(1) if date_m else None,
                    raw={"line": line.strip(), "source": "text_heuristic"},
                ))

    return rows


def _interpreter_extract_pbs(page: ProfilePage) -> tuple[list[PBRow], float]:
    """
    Use the interpreter package to extract PBs from a profile page.

    Returns (pb_rows, confidence). Falls back gracefully if interpreter
    is not available.
    """
    try:
        import mediahub.interpreter  # lazy import — may not exist yet
        raw_bytes = page.text.encode("utf-8")
        result = interpreter.interpret_document(raw_bytes, hint='profile_page')

        pbs_raw = result.get("pbs") or result.get("rows") or []
        confidence = result.get("confidence", 0.5)

        pb_rows = []
        for r in pbs_raw:
            if isinstance(r, dict):
                pb_rows.append(PBRow(
                    event=r.get("event", r.get("event_canonical", "")),
                    course=r.get("course", "LC"),
                    time_canonical=r.get("time_canonical", r.get("time", "")),
                    date=r.get("date"),
                    meet=r.get("meet"),
                    rank=r.get("rank"),
                    raw=r,
                ))
        return pb_rows, float(confidence)
    except ImportError:
        raise ImportError(
            "interpreter package not yet built — "
            "provide a stub or wait for the interpreter subagent to complete"
        )
    except Exception:
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
            pass

    # Heuristic fallback
    rows = _heuristic_extract_pbs(page)
    # Heuristic confidence is lower; more rows = slightly higher confidence
    conf = min(0.6, 0.2 + len(rows) * 0.05) if rows else 0.0
    return rows, conf
