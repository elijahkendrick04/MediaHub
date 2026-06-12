"""
swim_content_pb/schema.py
All dataclasses for the V6 PB accuracy and history intelligence subsystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IdentityMatch:
    """Result of matching a HY3 swimmer to a swimmingresults.org record."""
    asa_id: Optional[str]
    hy3_name: str                        # raw name from HY3
    sr_name: Optional[str]               # name returned by SR page
    canonical_hy3_name: str              # normalised for compare
    canonical_sr_name: Optional[str]
    method: str                          # "asa_id_verified" | "asa_id_unverified" |
                                         # "needs_verification" | "no_id" | "manual_override"
    confidence: float                    # 0.0-1.0
    safe_to_use: bool                    # if False, suppress PB detection
    notes: list = field(default_factory=list)               # human-readable trail
    alternative_matches: list = field(default_factory=list) # if SR returned ambiguity (rare)


@dataclass
class ParsedSwimEntry:
    """One swim row parsed from a SR personal-best page."""
    distance: int
    stroke: str                          # canonical: free|back|breast|fly|im (long form)
    course: str                          # "LC" | "SC" | "UNKNOWN"
    time_str: str                        # "1:01.42"
    time_seconds: float
    date_iso: Optional[str]              # ISO YYYY-MM-DD
    meet_name: Optional[str]
    venue: Optional[str]
    licence: Optional[str]
    level: Optional[str]
    is_best: bool = True                 # True = best for this event on the page


@dataclass
class ParsedSnapshot:
    """Full parsed result for one swimmer's SR page."""
    asa_id: str
    swimmer_name: Optional[str]          # name as shown on the SR page
    entries: list = field(default_factory=list)  # list[ParsedSwimEntry]
    source_url: str = ""
    fetched_at: str = ""                 # ISO timestamp
    fetch_ok: bool = True
    error: Optional[str] = None
    raw_html_hash: Optional[str] = None


@dataclass
class FetchResult:
    """Result of one HTTP fetch attempt (or cache hit)."""
    asa_id: str
    snapshot: Optional[ParsedSnapshot]
    from_cache: bool
    fetch_ok: bool
    error: Optional[str] = None
    status_code: Optional[int] = None
    source: str = "network"              # "network" | "cache" | "skipped_budget" |
                                         # "skipped_circuit_open" | "invalid_id"


@dataclass
class PreviousPB:
    """A swimmer's PB for a specific event/course as of a specific date."""
    swimmer_asa_id: str
    swimmer_name: str
    event_distance: int
    event_stroke: str                    # canonical: free|back|breast|fly|im
    course: str                          # "LC" | "SC"
    time_seconds: float
    time_display: str                    # "1:01.42"
    pb_date_iso: Optional[str]
    pb_meet_name: Optional[str]
    source_url: str
    fetched_at: str                      # ISO timestamp
    excluded_swims: list = field(default_factory=list)   # swims excluded as same-meet duplicates
    confidence: str = "high"            # "high" | "medium" | "low"
    notes: list = field(default_factory=list)


@dataclass
class PBDecision:
    """Outcome of comparing a current swim to a PreviousPB."""
    status: str                          # "CONFIRMED_PB" | "LIKELY_PB" |
                                         # "NOT_PB" | "PB_UNVERIFIED" |
                                         # "AMBIGUOUS" | "SUPPRESSED_NEEDS_VERIFICATION"
    swim_id: str
    swimmer_asa_id: Optional[str]
    swimmer_name: str
    event: str
    course: str
    current_time_seconds: float
    current_time_display: str
    previous_pb: Optional[PreviousPB]
    delta_seconds: Optional[float]       # negative = improvement
    improvement_percentage: Optional[float]
    same_meet_excluded_count: int
    reason: str
    evidence: list = field(default_factory=list)   # source URL, fetched_at, time, etc.
    safe_to_post: bool = False
    confidence: str = "low"
    uncertainty_notes: list = field(default_factory=list)
    audit_trail: list = field(default_factory=list)  # step-by-step decision log


@dataclass
class PBAudit:
    """Per-swimmer audit summary for the run."""
    asa_id: Optional[str]
    hy3_name: str
    sr_name: Optional[str]
    identity: Optional[IdentityMatch]
    events_fetched: list = field(default_factory=list)        # list[str]
    pb_decisions: list = field(default_factory=list)          # list[PBDecision]
    achievements_generated: list = field(default_factory=list)   # achievement type names
    achievements_suppressed: list = field(default_factory=list)  # type names + reasons
    fetch_ok: bool = False
    fetch_error: Optional[str] = None
    # True when the lookup completed but found no verifiable online history
    # for this swimmer — a legitimate result, distinct from a failed fetch.
    no_history: bool = False
    source_urls: list = field(default_factory=list)
    fetched_at: Optional[str] = None


@dataclass
class RunPBAudit:
    """Aggregate audit for the whole run."""
    run_id: str
    swimmers_total: int = 0
    swimmers_matched_verified: int = 0
    swimmers_needs_verification: int = 0
    swimmers_no_id: int = 0
    swimmers_fetch_failed: int = 0
    swimmers_no_history: int = 0          # lookup completed, no online history found
    pb_decisions_count: int = 0
    pb_confirmed_count: int = 0          # V7.3: includes CONFIRMED_OFFICIAL_PB + CONFIRMED_PB_IMPROVEMENT + legacy CONFIRMED_PB
    pb_confirmed_official_count: int = 0  # V7.3: NEW — only CONFIRMED_OFFICIAL_PB (time + date match)
    pb_matched_count: int = 0             # V7.3: NEW — MATCHED_PB (time matches but date doesn't prove new)
    pb_likely_count: int = 0
    pb_not_pb_count: int = 0
    pb_unverified_count: int = 0
    pb_suppressed_count: int = 0
    pb_ambiguous_count: int = 0
    fetch_total_seconds: float = 0.0
    fetch_budget_exceeded: bool = False
    cache_hits: int = 0
    cache_misses: int = 0
    per_swimmer: list = field(default_factory=list)   # list[PBAudit]
    warnings: list = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    # Extra fields for legacy compatibility
    snapshots_by_asa_id: dict = field(default_factory=dict)  # asa_id -> ParsedSnapshot
    decisions_by_swim_id: dict = field(default_factory=dict) # swim_id -> PBDecision

    def find_decision(self, swim_id: str) -> Optional[PBDecision]:
        """Look up a PBDecision by swim_id (used by V5 detectors)."""
        return self.decisions_by_swim_id.get(swim_id)
