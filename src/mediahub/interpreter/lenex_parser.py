"""
lenex_parser.py — Parse LENEX 3.0 (`.lef` / `.lxf`) files into InterpretedMeet.

LENEX 3.0 is the openly licensed XML interchange format for swim results
and entries ("free of charge and without restriction") used by
SportSystems and most European meet software. Two file shapes exist:

* ``.lef`` — plain LENEX XML
* ``.lxf`` — a ZIP archive containing one ``.lef``

Structure (elements of interest):

    LENEX > MEETS > MEET (name, city, course)
      > SESSIONS > SESSION (date)
        > EVENTS > EVENT (eventid, gender)
          > SWIMSTYLE (distance, stroke, relaycount)
          > AGEGROUPS > AGEGROUP > RANKINGS > RANKING (place, resultid)
      > CLUBS > CLUB (name, code)
        > ATHLETES > ATHLETE (firstname, lastname, birthdate, gender)
          > RESULTS > RESULT (resultid, eventid, swimtime, status, reactiontime)
          > ENTRIES > ENTRY (eventid, entrytime)

Times use the LENEX swimtime format ``HH:MM:SS.hh`` (or ``NT`` for no
time); they are canonicalised to the same ``m:ss.cc`` / ``ss.cc`` strings
the HY3/SDIF parsers emit so downstream output parity holds (W.5 exit
criterion).

Deterministic throughout — stdlib ``xml.etree`` only, no LLM involvement.
Stroke and course vocabulary comes from ``data/ontology`` (strokes.json,
courses.json, hytek_codes.json); this module adds no swim-vocabulary
literals. Malformed or hostile input never crashes the worker: bad XML
returns an honest ``needs_review`` entry and `.lxf` archives go through
:mod:`interpreter._zip_safety` (compression bombs raise ``UnsafeZipError``).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from ._zip_safety import (
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    UnsafeZipError,
    safe_infolist,
    safe_read_member,
)
from .ontology_loader import OntologyLoader
from .schema_dataclasses import (
    InterpretedEvent,
    InterpretedMeet,
    InterpretedSwim,
)

log = logging.getLogger(__name__)

# Canonical vocabulary comes from data/ontology so this module contains
# no swim-vocabulary literals (same convention as hytek_parser/sdif_parser).
_ONTOLOGY = OntologyLoader()
_STROKE_MAP: dict[str, str] = _ONTOLOGY.canonical_map("strokes")
_COURSE_MAP: dict[str, str] = _ONTOLOGY.canonical_map("courses")
_HY3_STROKE_CODES: dict[str, str] = (_ONTOLOGY["hytek_codes"] or {}).get(
    "hy3_stroke_codes", {}
)
# Relay stroke names ride on the existing hytek ontology entries
# (A=individual free → F=free relay, E=individual medley → G=medley relay)
# so relays canonicalise without new vocabulary literals here.
_RELAY_STROKE: dict[str, str] = {}
if _HY3_STROKE_CODES.get("A") and _HY3_STROKE_CODES.get("F"):
    _RELAY_STROKE[_HY3_STROKE_CODES["A"]] = _HY3_STROKE_CODES["F"]
if _HY3_STROKE_CODES.get("E") and _HY3_STROKE_CODES.get("G"):
    _RELAY_STROKE[_HY3_STROKE_CODES["E"]] = _HY3_STROKE_CODES["G"]

_ZIP_MAGIC = b"PK\x03\x04"
_MAX_LENEX_BYTES = MAX_MEMBER_UNCOMPRESSED_BYTES

# LENEX RESULT status codes that mean "no countable swim happened".
# These are format status codes (like HY3 record-type codes), not swim
# vocabulary. The swim is excluded from events and flagged in
# needs_review so "why no card for this swimmer?" stays explainable.
_NON_FINISH_STATUS = frozenset({"DSQ", "DNS", "DNF", "WDR", "SICK"})

# ``<LENEX`` root tag followed by whitespace, ``>`` or ``/`` (so e.g. a
# hypothetical <LENEXTRAS> tag does not match).
_LENEX_TAG_RE = re.compile(rb"<\s*lenex[\s>/]", re.IGNORECASE)
_SWIMTIME_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})\.(\d{2})$")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_lenex(data: bytes) -> bool:
    """True if *data* looks like a LENEX ``.lef`` XML document.

    Pure-XML check only: ``.lxf`` ZIP wrappers are routed via the filename
    hint or the ZIP-member recursion in ``interpreter.__init__``, both of
    which call :func:`parse_lenex` (which unwraps the ZIP itself).
    """
    if not data:
        return False
    head = data[:2048]
    if head[:3] == b"\xef\xbb\xbf":  # UTF-8 BOM
        head = head[3:]
    if not head.lstrip()[:1] == b"<":
        return False
    return bool(_LENEX_TAG_RE.search(head))


# ---------------------------------------------------------------------------
# Small deterministic field helpers
# ---------------------------------------------------------------------------


def _attr(el: Optional[ET.Element], name: str) -> Optional[str]:
    """Case-insensitive attribute lookup; empty strings become None."""
    if el is None:
        return None
    lname = name.lower()
    for key, value in el.attrib.items():
        if key.lower() == lname:
            value = value.strip()
            return value or None
    return None


def _children(el: ET.Element, tag: str) -> list[ET.Element]:
    """Direct children matching *tag*, case-insensitively."""
    upper = tag.upper()
    return [c for c in el if isinstance(c.tag, str) and c.tag.upper() == upper]


def _collect(el: ET.Element, *path: str) -> list[ET.Element]:
    """Walk a case-insensitive tag path, e.g. ``_collect(meet, "CLUBS", "CLUB")``."""
    current = [el]
    for tag in path:
        nxt: list[ET.Element] = []
        for e in current:
            nxt.extend(_children(e, tag))
        current = nxt
    return current


def _first(el: ET.Element, *path: str) -> Optional[ET.Element]:
    found = _collect(el, *path)
    return found[0] if found else None


def _to_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    s = raw.strip()
    if not s.lstrip("-").isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_swimtime(raw: Optional[str]) -> Optional[str]:
    """LENEX swimtime ``HH:MM:SS.hh`` → canonical ``m:ss.cc`` / ``ss.cc``.

    ``NT`` (no time), blank, zero, and malformed values return None.
    A couple of non-spec shapes some exporters emit (``m:ss.cc`` and
    plain ``ss.cc``) are tolerated, matching the forgiving stance of the
    HY3/SDIF parsers.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s or s.upper() == "NT":
        return None
    m = _SWIMTIME_RE.match(s)
    if m:
        hours, minutes = int(m.group(1)), int(m.group(2))
        seconds, hundredths = int(m.group(3)), m.group(4)
        total_minutes = hours * 60 + minutes
        if total_minutes == 0 and seconds == 0 and hundredths == "00":
            return None  # zero time = no swim
        if total_minutes:
            return f"{total_minutes}:{seconds:02d}.{hundredths}"
        return f"{seconds}.{hundredths}"
    # Tolerated non-spec shapes
    m = re.match(r"^(\d{1,3}):(\d{2}\.\d{2})$", s)
    if m:
        return f"{int(m.group(1))}:{m.group(2)}"
    m = re.match(r"^(\d{1,3}\.\d{2})$", s)
    if m:
        secs = float(m.group(1))
        if secs == 0.0:
            return None
        if secs >= 60.0:
            mm = int(secs // 60)
            return f"{mm}:{secs - mm * 60:05.2f}"
        return m.group(1)
    return None


def _canon_stroke(raw: Optional[str], relaycount: Optional[int]) -> Optional[str]:
    """LENEX stroke name (FREE/BACK/BREAST/FLY/MEDLEY) → canonical name."""
    if not raw:
        return None
    base = _STROKE_MAP.get(raw.strip().lower())
    if base is None:
        return None
    if relaycount and relaycount > 1:
        return _RELAY_STROKE.get(base, base)
    return base


def _canon_course(raw: Optional[str]) -> Optional[str]:
    """LENEX course (LCM/SCM/SCY/SCM16/…) → canonical "LC"/"SC".

    Exact alias match first; LENEX pool-length variants (SCY, SCM16, …)
    resolve by longest-known-alias prefix — structural, no new vocabulary.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _COURSE_MAP:
        return _COURSE_MAP[key]
    for n in range(len(key) - 1, 1, -1):
        prefix = key[:n]
        if prefix in _COURSE_MAP:
            return _COURSE_MAP[prefix]
    return None


def _gender(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    g = raw.strip().upper()
    return g if g in ("M", "F", "X") else None  # LENEX "A" (all) → None


def _athlete_name(ath: ET.Element) -> str:
    first = _attr(ath, "firstname") or ""
    last = _attr(ath, "lastname") or ""
    if first and last:
        return f"{first} {last}"
    return last or first


def _athlete_yob(ath: ET.Element) -> Optional[int]:
    """Year from a LENEX birthdate (``YYYY-MM-DD``)."""
    raw = _attr(ath, "birthdate") or ""
    m = re.match(r"^(\d{4})-\d{2}-\d{2}$", raw)
    if not m:
        return None
    year = int(m.group(1))
    return year if 1900 <= year <= 2030 else None


def _reaction(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = raw.strip().lstrip("+").strip()
    return s or None


# ---------------------------------------------------------------------------
# .lxf (ZIP) unwrapping — bomb-safe via _zip_safety
# ---------------------------------------------------------------------------


def _unwrap_lxf(data: bytes) -> Optional[bytes]:
    """Return the ``.lef`` XML bytes inside an ``.lxf`` ZIP wrapper.

    Raises :class:`UnsafeZipError` for hostile archives (member-count or
    compression-bomb limits). Returns None when no LENEX member exists.
    Only one level of wrapping is supported, per the LENEX spec.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:  # noqa: BLE001 — not a readable ZIP
        return None
    try:
        all_files = [i for i in zf.infolist() if not i.is_dir()]
        safe = safe_infolist(zf)  # raises UnsafeZipError for hostile archives
        safe_by_name = {i.filename: i for i in safe}
        lef_named = [i.filename for i in all_files if i.filename.lower().endswith(".lef")]
        if lef_named and not any(n in safe_by_name for n in lef_named):
            raise UnsafeZipError(
                "all .lef members were rejected by ZIP safety limits"
            )
        # Prefer .lef-named members, then any other safe member that
        # sniffs as LENEX XML (some exporters use odd extensions).
        ordered = [safe_by_name[n] for n in lef_named if n in safe_by_name]
        lef_set = set(lef_named)
        ordered += [i for i in safe if i.filename not in lef_set]
        for info in ordered:
            blob = safe_read_member(zf, info)  # UnsafeZipError propagates
            if detect_lenex(blob):
                return blob
        return None
    finally:
        zf.close()


# ---------------------------------------------------------------------------
# Document indexing
# ---------------------------------------------------------------------------


def _index_events(meet_el: ET.Element) -> tuple[dict[str, dict], list[str]]:
    """Map eventid → event info from SESSIONS/SESSION/EVENTS/EVENT.

    Returns ``(index, session_dates)``; index preserves document order.
    """
    index: dict[str, dict] = {}
    dates: list[str] = []
    for session in _collect(meet_el, "SESSIONS", "SESSION"):
        s_date = _attr(session, "date")
        if s_date:
            dates.append(s_date)
        for ev in _collect(session, "EVENTS", "EVENT"):
            event_id = _attr(ev, "eventid")
            if not event_id or event_id in index:
                continue
            style = _first(ev, "SWIMSTYLE")
            relaycount = _to_int(_attr(style, "relaycount"))
            index[event_id] = {
                "event_id": event_id,
                "number": _attr(ev, "number"),
                "gender": _gender(_attr(ev, "gender")),
                "distance": _to_int(_attr(style, "distance")),
                "stroke": _canon_stroke(_attr(style, "stroke"), relaycount),
                "course": _canon_course(_attr(ev, "course")),
                "session_date": s_date,
            }
    return index, dates


def _index_rankings(meet_el: ET.Element) -> dict[str, int]:
    """Map resultid → place from every RANKING element under the meet."""
    places: dict[str, int] = {}
    for el in meet_el.iter():
        if isinstance(el.tag, str) and el.tag.upper() == "RANKING":
            result_id = _attr(el, "resultid")
            place = _to_int(_attr(el, "place"))
            if result_id and place and result_id not in places and 1 <= place <= 500:
                places[result_id] = place
    return places


def _count_elements(meet_el: ET.Element, tag: str) -> int:
    upper = tag.upper()
    return sum(
        1 for el in meet_el.iter() if isinstance(el.tag, str) and el.tag.upper() == upper
    )


def _empty_meet(needs_review: list[dict]) -> InterpretedMeet:
    return InterpretedMeet(
        meet_name=None,
        venue=None,
        dates=None,
        course_default=None,
        governing_body_hint=None,
        events=[],
        overall_confidence=0.0,
        needs_review=needs_review,
        sources_used=["format:lenex"],
        patterns_used=[],
        new_patterns_proposed=[],
    )


def _load_meet_element(
    data: bytes,
) -> tuple[Optional[ET.Element], list[dict]]:
    """Unwrap (.lxf), bound, and parse the XML; return (MEET element, flags).

    Never raises for malformed input — only :class:`UnsafeZipError` for
    hostile ``.lxf`` archives escapes, by design.
    """
    if data[:4] == _ZIP_MAGIC:
        inner = _unwrap_lxf(data)  # UnsafeZipError propagates
        if inner is None:
            return None, [
                {
                    "reason": "lenex-lxf-no-member",
                    "detail": "ZIP archive contains no parseable LENEX (.lef) member",
                }
            ]
        data = inner
    if len(data) > _MAX_LENEX_BYTES:
        return None, [
            {
                "reason": "lenex-too-large",
                "detail": f"{len(data)} bytes exceeds the {_MAX_LENEX_BYTES}-byte limit",
            }
        ]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return None, [{"reason": "lenex-xml-malformed", "detail": str(exc)}]
    meets = _collect(root, "MEETS", "MEET")
    if not meets:
        return None, [
            {"reason": "lenex-no-meet", "detail": "no MEETS/MEET element in document"}
        ]
    flags: list[dict] = []
    if len(meets) > 1:
        flags.append(
            {
                "reason": "lenex-multiple-meets",
                "detail": f"{len(meets)} MEET elements present; only the first was parsed",
            }
        )
    return meets[0], flags


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def parse_lenex(data: bytes) -> InterpretedMeet:
    """Parse a ``.lef`` / ``.lxf`` byte buffer and return an InterpretedMeet."""
    meet_el, needs_review = _load_meet_element(data)
    if meet_el is None:
        return _empty_meet(needs_review)

    meet_name = _attr(meet_el, "name")
    venue = _attr(meet_el, "city")
    course_default = _canon_course(_attr(meet_el, "course"))

    event_index, session_dates = _index_events(meet_el)
    place_by_result = _index_rankings(meet_el)

    dates: Optional[tuple[str, str]] = None
    if session_dates:
        ordered_dates = sorted(session_dates)
        dates = (ordered_dates[0], ordered_dates[-1])

    swims_by_event: dict[str, list[InterpretedSwim]] = {}

    for club_el in _collect(meet_el, "CLUBS", "CLUB"):
        club = _attr(club_el, "name") or _attr(club_el, "code")
        for ath in _collect(club_el, "ATHLETES", "ATHLETE"):
            swimmer_name = _athlete_name(ath)
            yob = _athlete_yob(ath)
            for res in _collect(ath, "RESULTS", "RESULT"):
                event_id = _attr(res, "eventid")
                status = (_attr(res, "status") or "").upper()
                raw_time = _attr(res, "swimtime")
                result_id = _attr(res, "resultid")
                raw_row = (
                    f"RESULT resultid={result_id or '?'} eventid={event_id or '?'} "
                    f"swimtime={raw_time or '?'} status={status or 'OK'}"
                )[:120]

                info = event_index.get(event_id or "")
                if info is None:
                    needs_review.append(
                        {
                            "reason": "lenex-unknown-event-reference",
                            "event_id": event_id,
                            "swimmer": swimmer_name,
                            "detail": "RESULT references an eventid not declared under SESSIONS",
                        }
                    )
                    continue
                if status in _NON_FINISH_STATUS:
                    # Not a countable swim — exclude, but keep it explainable.
                    needs_review.append(
                        {
                            "reason": "lenex-result-status-excluded",
                            "status": status,
                            "event_id": event_id,
                            "swimmer": swimmer_name,
                        }
                    )
                    continue

                time_value = _parse_swimtime(raw_time)
                if time_value is None:
                    needs_review.append(
                        {
                            "reason": "lenex-missing-swim-time",
                            "event_id": event_id,
                            "swimmer": swimmer_name,
                            "raw": raw_time or "",
                        }
                    )
                place = place_by_result.get(result_id) if result_id else None

                field_conf = {
                    "swimmer_name": 0.95 if swimmer_name else 0.2,
                    "time": 0.95 if time_value else 0.0,
                    "place": 0.85 if place else 0.3,
                    "club": 0.9 if club else 0.0,
                    "stroke": 0.95 if info["stroke"] else 0.0,
                    "distance": 0.95 if info["distance"] else 0.0,
                }
                swim = InterpretedSwim(
                    swimmer_name=swimmer_name or "Unknown",
                    yob=yob,
                    club=club,
                    place=place,
                    time=time_value,
                    reaction=_reaction(_attr(res, "reactiontime")),
                    confidence=round(sum(field_conf.values()) / len(field_conf), 3),
                    raw_row=raw_row,
                    field_confidence=field_conf,
                )
                swims_by_event.setdefault(info["event_id"], []).append(swim)

    events: list[InterpretedEvent] = []
    for event_id, info in event_index.items():
        swims = swims_by_event.get(event_id)
        if not swims:
            continue
        if info["distance"] and info["stroke"] and info["gender"]:
            ev_conf = 0.95  # fully specified structured event
        elif info["distance"] and info["stroke"]:
            ev_conf = 0.85
        else:
            ev_conf = 0.5
        events.append(
            InterpretedEvent(
                gender=info["gender"],
                distance_m=info["distance"],
                stroke=info["stroke"],
                course=info["course"] or course_default,
                age_band=None,
                swims=swims,
                confidence=ev_conf,
                raw_header=f"EVENT {info['number'] or event_id}",
            )
        )

    if not events and _count_elements(meet_el, "ENTRY"):
        # An entries-only file (psych sheet) — honest signal for the
        # results pipeline; W.6 consumes these via parse_lenex_entries.
        needs_review.append(
            {
                "reason": "lenex-entries-only",
                "detail": "document carries ENTRY elements but no countable RESULT swims",
            }
        )

    # Overall confidence: same convention as parse_hy3/parse_sdif — mean
    # of event confidences weighted by swim share, clamped to [0.5, 0.99].
    if events:
        total_swims = sum(len(e.swims) for e in events) or 1
        overall = sum(e.confidence * (len(e.swims) / total_swims) for e in events if e.swims)
        overall = round(min(0.99, max(0.5, overall)), 3)
    else:
        overall = 0.0

    return InterpretedMeet(
        meet_name=meet_name,
        venue=venue,
        dates=dates,
        course_default=course_default,
        governing_body_hint=None,
        events=events,
        overall_confidence=overall,
        needs_review=needs_review,
        sources_used=["format:lenex"],
        patterns_used=[],
        new_patterns_proposed=[],
    )


def parse_lenex_entries(data: bytes) -> list[dict]:
    """Extract entry rows (ATHLETE > ENTRIES > ENTRY) from a ``.lef``/``.lxf``.

    Feeds the W.6 meet-preview work stream. Deterministic, no LLM. Each
    row carries::

        {"swimmer_name", "yob", "gender", "club", "distance_m", "stroke",
         "course", "entry_time", "event_id", "session_date"}

    Rows preserve document order. Malformed XML yields an empty list;
    hostile ``.lxf`` archives raise :class:`UnsafeZipError`.
    """
    meet_el, _flags = _load_meet_element(data)
    if meet_el is None:
        return []

    event_index, _dates = _index_events(meet_el)
    meet_course = _canon_course(_attr(meet_el, "course"))

    rows: list[dict] = []
    for club_el in _collect(meet_el, "CLUBS", "CLUB"):
        club = _attr(club_el, "name") or _attr(club_el, "code")
        for ath in _collect(club_el, "ATHLETES", "ATHLETE"):
            swimmer_name = _athlete_name(ath)
            yob = _athlete_yob(ath)
            gender = _gender(_attr(ath, "gender"))
            for entry in _collect(ath, "ENTRIES", "ENTRY"):
                event_id = _attr(entry, "eventid")
                info = event_index.get(event_id or "", {})
                rows.append(
                    {
                        "swimmer_name": swimmer_name,
                        "yob": yob,
                        "gender": gender,
                        "club": club,
                        "distance_m": info.get("distance"),
                        "stroke": info.get("stroke"),
                        "course": info.get("course") or meet_course,
                        "entry_time": _parse_swimtime(_attr(entry, "entrytime")),
                        "event_id": event_id,
                        "session_date": info.get("session_date"),
                    }
                )
    return rows
