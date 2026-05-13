"""
V5 schema — new dataclasses for the achievement layer.

These types live entirely in swim_content_v5 and do NOT modify canonical.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class QualityBand(str, Enum):
    ELITE = "elite"         # national-level medal, national record, huge PB
    STRONG = "strong"       # county medal, big PB, qual hit inside window
    STORY = "story"         # return to form, multi-PB weekend, fastest since
    NICE = "nice"           # bronze at local meet, small PB
    NOT_WORTHY = "not_worthy"  # nothing notable


class PostType(str, Enum):
    MAIN_FEED = "main_feed"         # full athlete spotlight carousel / image post
    STORY = "story"                 # Instagram / Facebook story
    RECAP = "recap"                 # included in a meet recap post
    INTERNAL_NOTE = "internal_note" # not for public posting; internal record


# ---------------------------------------------------------------------------
# Evidence attached to one achievement
# ---------------------------------------------------------------------------

@dataclass
class AchievementEvidence:
    source_type: str              # "results_file" | "pb_cache" | "live_research" | "registry"
    source_name: str
    statement: str                # what this evidence proves
    source_url: Optional[str] = None
    fetched_at: Optional[str] = None   # ISO timestamp
    confidence: str = "medium"         # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "statement": self.statement,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Achievement — one notable thing that happened for one swimmer
# ---------------------------------------------------------------------------

@dataclass
class Achievement:
    type: str                     # e.g. "pb_confirmed", "medal_gold", "first_sub_60"
    swim_id: str                  # swimmer_key + event label composite
    swimmer_id: str               # swimmer_key from canonical schema
    swimmer_name: str
    event: str                    # canonical event label e.g. "100m Freestyle (LC)"
    headline: str                 # short factual statement
    angle_hint: str               # narrative angle suggestion
    confidence: float             # 0.0–1.0
    confidence_label: str         # "high" | "medium" | "low"
    evidence: list[AchievementEvidence] = field(default_factory=list)
    raw_facts: dict = field(default_factory=dict)      # time, prev_pb, drop_seconds, etc.
    uncertainty_notes: list[str] = field(default_factory=list)
    detector_name: str = ""

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "swim_id": self.swim_id,
            "swimmer_id": self.swimmer_id,
            "swimmer_name": self.swimmer_name,
            "event": self.event,
            "headline": self.headline,
            "angle_hint": self.angle_hint,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "evidence": [e.to_dict() for e in self.evidence],
            "raw_facts": self.raw_facts,
            "uncertainty_notes": self.uncertainty_notes,
            "detector_name": self.detector_name,
        }
        # V7.3: include post_angle if set
        pa = getattr(self, "post_angle", None)
        if pa is not None:
            d["post_angle"] = pa
        return d


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

@dataclass
class RankFactor:
    name: str
    value: float
    weight: float
    reason: str
    plain_summary: str = ""    # one-line plain-English explanation of this factor's contribution

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "reason": self.reason,
            "plain_summary": self.plain_summary,
        }


@dataclass
class RankedAchievement:
    achievement: Achievement
    priority: float                 # 0.0–1.0
    factors: list[RankFactor] = field(default_factory=list)
    quality_band: QualityBand = QualityBand.NICE
    suggested_post_type: PostType = PostType.RECAP
    rank: int = 0

    def to_dict(self) -> dict:
        d = {
            "achievement": self.achievement.to_dict(),
            "priority": self.priority,
            "factors": [f.to_dict() for f in self.factors],
            "quality_band": self.quality_band.value,
            "suggested_post_type": self.suggested_post_type.value,
            "rank": self.rank,
        }
        # V7.3: include safe_to_post and post_angle if set
        s2p = getattr(self, "safe_to_post", None)
        if s2p is not None:
            d["safe_to_post"] = s2p.to_dict() if hasattr(s2p, "to_dict") else s2p
        pa = getattr(self, "post_angle", None)
        if pa is not None:
            d["post_angle"] = pa
        return d


# ---------------------------------------------------------------------------
# Content recommendation
# ---------------------------------------------------------------------------

@dataclass
class ContentRecommendation:
    title: str
    swimmer_or_group: str            # name or "meet recap"
    included_achievement_types: list[str]
    suggested_post_type: PostType
    angle_hint: str
    ranked_achievements: list[RankedAchievement] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "swimmer_or_group": self.swimmer_or_group,
            "included_achievement_types": self.included_achievement_types,
            "suggested_post_type": self.suggested_post_type.value,
            "angle_hint": self.angle_hint,
            "ranked_achievements": [r.to_dict() for r in self.ranked_achievements],
        }


# ---------------------------------------------------------------------------
# Meet context
# ---------------------------------------------------------------------------

@dataclass
class MeetContext:
    meet_name: str = ""
    venue: Optional[str] = None
    course: str = "LC"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    governing_body: Optional[str] = None
    meet_level: str = "open"        # "national" | "county" | "university" | "open" | "club"
    has_finals: bool = False
    has_age_groups: bool = False
    age_groups: list[str] = field(default_factory=list)
    host_club_code: Optional[str] = None
    research_sources: list[dict] = field(default_factory=list)   # [{url, name, used_for}]
    research_available: bool = False
    research_error: Optional[str] = None
    # V7: optional reference to the ClubProfile (not serialised to JSON)
    profile: Optional[object] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "meet_name": self.meet_name,
            "venue": self.venue,
            "course": self.course,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "governing_body": self.governing_body,
            "meet_level": self.meet_level,
            "has_finals": self.has_finals,
            "has_age_groups": self.has_age_groups,
            "age_groups": self.age_groups,
            "host_club_code": self.host_club_code,
            "research_sources": self.research_sources,
            "research_available": self.research_available,
            "research_error": self.research_error,
        }


# ---------------------------------------------------------------------------
# Swim trace — "why was this not generated?"
# ---------------------------------------------------------------------------

@dataclass
class DetectorTrace:
    detector_name: str
    ran: bool = True
    fired: bool = False
    reason: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "detector_name": self.detector_name,
            "ran": self.ran,
            "fired": self.fired,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class SwimTrace:
    swim_id: str
    swimmer_name: str
    event: str
    time_str: str
    achievement_count: int = 0
    detector_traces: list[DetectorTrace] = field(default_factory=list)
    summary: str = ""           # human-readable "why nothing notable"
    near_miss_category: Optional[str] = None  # V7.3: "almost_pb" | "possible_pb_uncertain" | etc.

    def to_dict(self) -> dict:
        d = {
            "swim_id": self.swim_id,
            "swimmer_name": self.swimmer_name,
            "event": self.event,
            "time_str": self.time_str,
            "achievement_count": self.achievement_count,
            "detector_traces": [t.to_dict() for t in self.detector_traces],
            "summary": self.summary,
        }
        nmc = getattr(self, "near_miss_category", None)
        if nmc is not None:
            d["near_miss_category"] = nmc
        return d


# ---------------------------------------------------------------------------
# Recognition report — the top-level output of V5
# ---------------------------------------------------------------------------

@dataclass
class RecognitionReport:
    run_id: str
    meet_name: str
    meet_context: MeetContext
    ranked_achievements: list[RankedAchievement] = field(default_factory=list)
    recommendations: list[ContentRecommendation] = field(default_factory=list)
    swim_traces: list[SwimTrace] = field(default_factory=list)
    n_swims_analysed: int = 0
    n_achievements: int = 0
    n_elite: int = 0
    n_strong: int = 0
    n_story: int = 0
    n_nice: int = 0
    all_sources: list[dict] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "meet_name": self.meet_name,
            "meet_context": self.meet_context.to_dict(),
            "ranked_achievements": [r.to_dict() for r in self.ranked_achievements],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "swim_traces": [t.to_dict() for t in self.swim_traces],
            "n_swims_analysed": self.n_swims_analysed,
            "n_achievements": self.n_achievements,
            "n_elite": self.n_elite,
            "n_strong": self.n_strong,
            "n_story": self.n_story,
            "n_nice": self.n_nice,
            "all_sources": self.all_sources,
            "generated_at": self.generated_at,
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2, default=str)
