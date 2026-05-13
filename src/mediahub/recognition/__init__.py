"""
recognition — Sport-agnostic recognition engine.

Re-exports the core schema, ranker, recommender, explainer, and report
from swim_content_v5 (the authoritative implementation), plus new V7.3
additions: registry, PostAngle, SafeToPost, copy_text, weekend_in_numbers.
"""
from __future__ import annotations

# Re-export core types from v5
from swim_content_v5.schema import (
    QualityBand, PostType,
    AchievementEvidence,
    RankFactor,
    ContentRecommendation,
    MeetContext,
    DetectorTrace,
    RecognitionReport,
)
from swim_content_v5.ranker import rank_achievements
from swim_content_v5.recommender import recommend_post_type
from swim_content_v5.explainer import build_swim_trace
from swim_content_v5.report import build_recognition_report_for_run

# V7.3 additions
from .schema import Achievement, RankedAchievement, SwimTrace, PostAngle, POST_ANGLE_LABELS, SafeToPost
from .registry import register_sport, get_sport, list_sports, SportConfig
from .copy_text import build_caption_text
from .weekend_in_numbers import build_weekend_in_numbers

# V9: "Why this card?" plain-English explainer surface.
from .explainer import explain_achievement

__all__ = [
    # core from v5
    "QualityBand", "PostType",
    "AchievementEvidence",
    "RankFactor",
    "ContentRecommendation",
    "MeetContext",
    "DetectorTrace",
    "RecognitionReport",
    "rank_achievements",
    "recommend_post_type",
    "build_swim_trace",
    "build_recognition_report_for_run",
    # V7.3 additions
    "Achievement", "RankedAchievement", "SwimTrace",
    "PostAngle", "POST_ANGLE_LABELS", "SafeToPost",
    "register_sport", "get_sport", "list_sports", "SportConfig",
    "build_caption_text",
    "build_weekend_in_numbers",
    # V9 additions
    "explain_achievement",
]
