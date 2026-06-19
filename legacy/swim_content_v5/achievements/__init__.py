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

# Import all detectors.
# NB: a PB inferred from the swimmer's own entry/seed time is deliberately NOT
# registered. Entry/seed times are unreliable (soft / converted / "NT" entries),
# so inferring a PB from them risks false PBs — and a wrong PB is worse than a
# missing one. PBs come only from a real prior-best baseline: the verified web
# PB lookup (pb_confirmed / official_pb_confirmed).
from .pb import PBConfirmedDetector, PBImprovementMagnitudeDetector
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
