"""
recognition/schema.py — Sport-agnostic recognition engine schema.

Extends and re-exports from swim_content_v5.schema with new V7.3 additions:
  - PostAngle enum + POST_ANGLE_LABELS
  - post_angle field on Achievement
  - SafeToPost dataclass
  - safe_to_post field on RankedAchievement
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Re-export everything from v5 schema for backward compat
from swim_content_v5.schema import (
    QualityBand, PostType,
    AchievementEvidence,
    Achievement as _Achievement,
    RankFactor,
    RankedAchievement as _RankedAchievement,
    ContentRecommendation,
    MeetContext,
    DetectorTrace,
    SwimTrace as _SwimTrace,
    RecognitionReport,
)


# ---------------------------------------------------------------------------
# PostAngle taxonomy (Phase D)
# ---------------------------------------------------------------------------

class PostAngle(str, Enum):
    # PB family
    CONFIRMED_OFFICIAL_PB = "confirmed_official_pb"
    PB_IMPROVEMENT = "pb_improvement"
    LIKELY_PB = "likely_pb"
    FIRST_SUB_BARRIER = "first_sub_barrier"

    # Meet performance
    MEDAL_GOLD = "medal_gold"
    MEDAL_SILVER = "medal_silver"
    MEDAL_BRONZE = "medal_bronze"
    MEDAL_AND_PB_COMBO = "medal_and_pb_combo"   # recommender override
    FINALIST = "finalist"
    HEAT_TO_FINAL_DROP = "heat_to_final_drop"

    # Field context
    TOP_OF_FIELD = "top_of_field"
    QUALIFYING_TIME = "qualifying_time"

    # Historical
    BIGGEST_DROP = "biggest_drop"
    FASTEST_SINCE = "fastest_since"
    MULTI_PB_WEEKEND = "multi_pb_weekend"
    RETURN_TO_FORM = "return_to_form"

    # Team / aggregate
    TEAM_DEPTH = "team_depth"
    RELAY_HIGHLIGHT = "relay_highlight"
    WEEKEND_IN_NUMBERS = "weekend_in_numbers"
    ATHLETE_SPOTLIGHT = "athlete_spotlight"
    RECAP_MENTION = "recap_mention"


POST_ANGLE_LABELS: dict[PostAngle, str] = {
    PostAngle.CONFIRMED_OFFICIAL_PB: "Official PB confirmed",
    PostAngle.PB_IMPROVEMENT: "PB improvement",
    PostAngle.LIKELY_PB: "Likely PB",
    PostAngle.FIRST_SUB_BARRIER: "First sub-barrier",
    PostAngle.MEDAL_GOLD: "Gold medal",
    PostAngle.MEDAL_SILVER: "Silver medal",
    PostAngle.MEDAL_BRONZE: "Bronze medal",
    PostAngle.MEDAL_AND_PB_COMBO: "Medal + PB combo",
    PostAngle.FINALIST: "Finalist",
    PostAngle.HEAT_TO_FINAL_DROP: "Heat-to-final drop",
    PostAngle.TOP_OF_FIELD: "Top of field",
    PostAngle.QUALIFYING_TIME: "Qualifying time",
    PostAngle.BIGGEST_DROP: "Biggest drop",
    PostAngle.FASTEST_SINCE: "Fastest since",
    PostAngle.MULTI_PB_WEEKEND: "Multi-PB weekend",
    PostAngle.RETURN_TO_FORM: "Return to form",
    PostAngle.TEAM_DEPTH: "Team depth",
    PostAngle.RELAY_HIGHLIGHT: "Relay highlight",
    PostAngle.WEEKEND_IN_NUMBERS: "Weekend in numbers",
    PostAngle.ATHLETE_SPOTLIGHT: "Athlete spotlight",
    PostAngle.RECAP_MENTION: "Recap mention",
}


# ---------------------------------------------------------------------------
# SafeToPost (Phase F)
# ---------------------------------------------------------------------------

@dataclass
class SafeToPost:
    level: str      # "safe" | "needs_review" | "do_not_post"
    reason: str     # short user-facing explanation

    def to_dict(self) -> dict:
        return {"level": self.level, "reason": self.reason}


# ---------------------------------------------------------------------------
# Extended Achievement with post_angle (Phase D)
# ---------------------------------------------------------------------------

@dataclass
class Achievement(_Achievement):
    """Extended Achievement with post_angle field."""
    post_angle: Optional[str] = None    # PostAngle value as string

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["post_angle"] = self.post_angle
        return d


# ---------------------------------------------------------------------------
# Extended SwimTrace with near_miss_category (Phase J)
# ---------------------------------------------------------------------------

@dataclass
class SwimTrace(_SwimTrace):
    """Extended SwimTrace with near_miss_category for grouped display."""
    near_miss_category: Optional[str] = None   # "almost_pb" | "possible_pb_uncertain" | etc.

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["near_miss_category"] = self.near_miss_category
        return d


# ---------------------------------------------------------------------------
# Extended RankedAchievement with safe_to_post (Phase F)
# ---------------------------------------------------------------------------

@dataclass
class RankedAchievement(_RankedAchievement):
    """Extended RankedAchievement with safe_to_post and post_angle."""
    safe_to_post: Optional[SafeToPost] = None
    post_angle: Optional[str] = None   # PostAngle value as string

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["safe_to_post"] = self.safe_to_post.to_dict() if self.safe_to_post else None
        d["post_angle"] = self.post_angle
        return d


__all__ = [
    "QualityBand", "PostType",
    "AchievementEvidence",
    "Achievement",
    "RankFactor",
    "RankedAchievement",
    "ContentRecommendation",
    "MeetContext",
    "DetectorTrace",
    "SwimTrace",
    "RecognitionReport",
    "PostAngle",
    "POST_ANGLE_LABELS",
    "SafeToPost",
]
