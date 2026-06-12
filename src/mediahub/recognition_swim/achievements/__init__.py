"""
recognition_swim/achievements — Re-exports all swim achievement detectors.
"""

from swim_content_v5.achievements import (
    AchievementDetector,
    Achievement,
    DETECTORS,
    get_all_detectors,
)
from swim_content_v5.achievements.pb import (
    PBConfirmedDetector,
    PBLikelyDetector,
    PBImprovementMagnitudeDetector,
)
from swim_content_v5.achievements.barrier import FirstSubBarrierDetector
from swim_content_v5.achievements.medal_final import (
    MedalDetector,
    FinalAppearanceDetector,
    HeatToFinalDropDetector,
)
from swim_content_v5.achievements.qualifier import QualifyingTimeDetector
from swim_content_v5.achievements.standout_field import TopOfFieldDetector
from swim_content_v5.achievements.standout_history import (
    FastestSinceDetector,
    BiggestDropDetector,
    MultiPBWeekendDetector,
)
from swim_content_v5.achievements.return_to_form import ReturnToFormDetector
from swim_content_v5.achievements.relay import RelayMedalDetector, RelayStrongPerformanceDetector

# OfficialPBDetector is new in V7.3
from .official_pb import OfficialPBDetector

# Phase W registry-fed detectors
from .club_record import ClubRecordDetector
from .milestones import MilestoneDetector

__all__ = [
    "AchievementDetector",
    "Achievement",
    "DETECTORS",
    "get_all_detectors",
    "PBConfirmedDetector",
    "PBLikelyDetector",
    "PBImprovementMagnitudeDetector",
    "FirstSubBarrierDetector",
    "MedalDetector",
    "FinalAppearanceDetector",
    "HeatToFinalDropDetector",
    "QualifyingTimeDetector",
    "TopOfFieldDetector",
    "FastestSinceDetector",
    "BiggestDropDetector",
    "MultiPBWeekendDetector",
    "ReturnToFormDetector",
    "RelayMedalDetector",
    "RelayStrongPerformanceDetector",
    "OfficialPBDetector",
    "ClubRecordDetector",
    "MilestoneDetector",
]
