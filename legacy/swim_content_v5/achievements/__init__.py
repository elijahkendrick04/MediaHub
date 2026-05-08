"""
Achievement detector registry.

Import every detector here. The registry is used by the report builder
to run all detectors in one pass and by the explainer for swim traces.

To add a new detector:
  1. Create swim_content_v5/achievements/mydetector.py
  2. Import and add it to DETECTORS below.
  Zero changes needed anywhere else.
"""
from __future__ import annotations

from .base import AchievementDetector, Achievement

# Import all detectors
from .pb import PBConfirmedDetector, PBLikelyDetector, PBImprovementMagnitudeDetector
from .barrier import FirstSubBarrierDetector
from .medal_final import MedalDetector, FinalAppearanceDetector, HeatToFinalDropDetector
from .qualifier import QualifyingTimeDetector
from .standout_field import TopOfFieldDetector
from .standout_history import FastestSinceDetector, BiggestDropDetector, MultiPBWeekendDetector
from .return_to_form import ReturnToFormDetector
from .relay import RelayMedalDetector, RelayStrongPerformanceDetector

# Ordered registry — priority given to higher-confidence detectors first
DETECTORS: list[AchievementDetector] = [
    PBConfirmedDetector(),
    PBLikelyDetector(),
    PBImprovementMagnitudeDetector(),
    FirstSubBarrierDetector(),
    MedalDetector(),
    FinalAppearanceDetector(),
    HeatToFinalDropDetector(),
    QualifyingTimeDetector(),
    TopOfFieldDetector(),
    FastestSinceDetector(),
    BiggestDropDetector(),
    MultiPBWeekendDetector(),
    ReturnToFormDetector(),
    RelayMedalDetector(),
    RelayStrongPerformanceDetector(),
]


def get_all_detectors() -> list[AchievementDetector]:
    """Return all registered detectors."""
    return list(DETECTORS)


__all__ = [
    "AchievementDetector",
    "Achievement",
    "DETECTORS",
    "get_all_detectors",
]
