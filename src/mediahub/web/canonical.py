"""
V4 canonical schema.

Every meet input adapter must return objects from this module. Downstream
modules (PB enrichment, qualification check, ranker, captions, output)
must depend ONLY on this schema — never on the original file format or
on V3's internal `swim_content.parsers_hy3.ParsedMeet`.

Design principles:
  - One canonical Meet object regardless of input format.
  - Every claim or derived fact is anchored on one of these objects;
    nothing should be passed around as bare strings or tuples.
  - Adapters MUST surface ParseWarnings for anything ambiguous,
    inferred, or partially parsed. We never silently fail.
  - Schema is intentionally lossy in only one direction: inputs richer
    than the schema (e.g. exotic Hytek extensions) get downcast to a
    sensible canonical form, with the original kept in `extra` if useful.

Field naming matches the user-facing UI vocabulary so we don't have a
naming-translation layer between adapter -> rest-of-engine -> templates.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------
# Stroke / round / course constants — adapters MUST normalise to these
# ---------------------------------------------------------------------

STROKE_CODES = {"FR", "BK", "BR", "FL", "IM", "MEDLEY"}   # MEDLEY = relay medley
COURSE_CODES = {"LC", "SC", "Y"}                          # Y = yards (US)
ROUND_CODES = {"final", "timed_final", "heat", "semi"}


@dataclass
class SourceEvidence:
    """Where a fact came from. Attached to anything we claim."""
    source: str               # e.g. "PB lookup", "Aquatics GB", "Meet results file"
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None  # ISO timestamp
    confidence: str = "medium"          # high | medium | low
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParseWarning:
    """Something the adapter could not fully resolve."""
    code: str                 # short machine code, e.g. "missing_dob", "ambiguous_course"
    message: str              # human-readable
    severity: str = "info"    # info | warn | error
    field: Optional[str] = None
    record: Optional[str] = None  # e.g. "swimmer:1382076" or "swim:50FR_F:Smith,J"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Club:
    """One participating club/team."""
    code: str                 # canonical short code (4-letter Hytek, or USA Swimming team code, or stable hash if absent)
    name: str
    short_name: str = ""
    aliases: list[str] = field(default_factory=list)  # other codes/names seen for this club
    is_host: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class Swimmer:
    """One identifiable swimmer."""
    swimmer_key: str          # primary internal key (asa_id when known, else "club:lname,fname:dob" or stable hash)
    first_name: str
    last_name: str
    gender: str               # 'M' | 'F' | 'X' | ''
    dob: Optional[str] = None
    age_at_meet: Optional[int] = None
    asa_id: Optional[str] = None       # Swim England member id, when known
    usa_id: Optional[str] = None       # USA Swimming SWIMS id, when known
    fina_id: Optional[str] = None
    club_code: Optional[str] = None
    club_name: Optional[str] = None        # V7.4: canonical club name (set by PDF adapter)
    aliases: list[str] = field(default_factory=list)
    identity_confidence: str = "high"  # high (id-matched) | medium (name+club+dob) | low (name only)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class Split:
    """One split within a race result."""
    distance_marker: int      # 50, 100, 150, ...
    cumulative_cs: int        # centiseconds from start
    differential_cs: Optional[int] = None  # split for this segment


@dataclass
class RaceResult:
    """One individual swim by one swimmer in one event."""
    swimmer_key: str
    club_code: Optional[str]
    distance: int             # metres or yards
    stroke: str               # FR/BK/BR/FL/IM
    course: str               # LC/SC/Y
    gender: str               # 'M' | 'F' | 'X' (event gender, not necessarily swimmer)
    age_band: str = ""        # raw band, e.g. "13-14", "OPEN", "0-99"
    finals_time_cs: Optional[int] = None  # None ⇒ DQ/NS/scratch (see dq + status)
    seed_time_cs: Optional[int] = None
    place: Optional[int] = None
    round: str = "timed_final"
    dq: bool = False
    status: str = "completed"  # completed | dq | dns | dnf | scratch | exhibition
    swim_date: Optional[str] = None     # ISO yyyy-mm-dd
    splits: list[Split] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class RelayLeg:
    swimmer_key: Optional[str] = None
    leg_index: int = 0
    leg_time_cs: Optional[int] = None
    leg_stroke: Optional[str] = None  # for medley relays


@dataclass
class RelayResult:
    club_code: Optional[str]
    distance: int
    stroke: str               # 'FR' for free relay, 'MEDLEY' for medley
    course: str
    gender: str
    age_band: str = ""
    finals_time_cs: Optional[int] = None
    seed_time_cs: Optional[int] = None
    place: Optional[int] = None
    round: str = "timed_final"
    dq: bool = False
    status: str = "completed"
    swim_date: Optional[str] = None
    legs: list[RelayLeg] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class Meet:
    """The whole canonical meet."""
    name: str = "(unknown)"
    venue: Optional[str] = None
    course: str = "LC"            # majority course; per-swim courses live on the result
    start_date: Optional[str] = None  # ISO
    end_date: Optional[str] = None
    host_club_code: Optional[str] = None
    country: Optional[str] = None
    governing_body: Optional[str] = None  # e.g. "Swim England", "USA Swimming"
    clubs: dict[str, Club] = field(default_factory=dict)        # keyed by code
    swimmers: dict[str, Swimmer] = field(default_factory=dict)  # keyed by swimmer_key
    results: list[RaceResult] = field(default_factory=list)
    relays: list[RelayResult] = field(default_factory=list)
    source_format: str = "unknown"   # 'hy3' | 'cl2' | 'pdf' | 'csv' | ...
    source_filename: Optional[str] = None
    source_evidence: list[SourceEvidence] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    inferred_fields: list[str] = field(default_factory=list)  # which fields were inferred not parsed

    # ------------- conveniences -------------

    def add_warning(self, code: str, message: str, *,
                    severity: str = "warn",
                    field_name: Optional[str] = None,
                    record: Optional[str] = None) -> None:
        self.warnings.append(ParseWarning(
            code=code, message=message, severity=severity,
            field=field_name, record=record,
        ))

    def has_blocking_errors(self) -> bool:
        return any(w.severity == "error" for w in self.warnings)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "venue": self.venue,
            "course": self.course,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "host_club_code": self.host_club_code,
            "country": self.country,
            "governing_body": self.governing_body,
            "clubs": {k: asdict(v) for k, v in self.clubs.items()},
            "swimmers": {k: asdict(v) for k, v in self.swimmers.items()},
            "results": [asdict(r) for r in self.results],
            "relays": [asdict(r) for r in self.relays],
            "source_format": self.source_format,
            "source_filename": self.source_filename,
            "source_evidence": [e.to_dict() for e in self.source_evidence],
            "warnings": [w.to_dict() for w in self.warnings],
            "inferred_fields": self.inferred_fields,
        }


# ---------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------

class MeetAdapter:
    """
    Base class for meet input adapters. Each adapter:
      - declares the formats it can parse via `format_id`
      - reports a confidence score for a given input via `can_parse()`
      - parses the input into a canonical Meet via `parse()`

    Adapters MUST NOT raise on partial input — they must return a Meet
    with ParseWarnings instead. Only catastrophic, unrecoverable errors
    (e.g. file unreadable) may raise.
    """
    format_id: str = "abstract"
    display_name: str = "Abstract adapter"

    def can_parse(self, file_bytes: bytes, filename: str) -> float:
        """
        Return a confidence score 0.0–1.0 that this adapter can parse the input.
        0.0 means "definitely not", 1.0 means "I am sure".
        Used by the dispatcher to pick the best adapter for an input.
        """
        return 0.0

    def parse(self, file_bytes: bytes, filename: str) -> Meet:
        raise NotImplementedError
