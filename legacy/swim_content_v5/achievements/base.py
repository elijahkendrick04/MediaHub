"""
Base class for all V5 achievement detectors.

Every detector:
  1. Has a stable `name` string identifier.
  2. Implements `detect(swim, ctx, history, all_results)` returning list[Achievement].
  3. Gets a default `trace()` implementation that runs detect() and summarises.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from swim_content_v5.schema import Achievement, DetectorTrace

if TYPE_CHECKING:
    from swim_content_v5.schema import MeetContext
    from swim_content_v5.history import SwimmerHistory


class AchievementDetector(ABC):
    """Abstract base class for all achievement detectors."""

    name: str = "abstract"

    @abstractmethod
    def detect(
        self,
        swim,                   # canonical RaceResult
        ctx: "MeetContext",
        history: "SwimmerHistory",
        all_results: Optional[list] = None,   # all results in the meet (for field comparisons)
        extra: Optional[dict] = None,         # extra per-swim data (swimmer object, etc.)
    ) -> list[Achievement]:
        """Detect achievements for a single swim. Return empty list if nothing notable."""
        ...

    def trace(
        self,
        swim,
        ctx: "MeetContext",
        history: "SwimmerHistory",
        all_results: Optional[list] = None,
        extra: Optional[dict] = None,
    ) -> DetectorTrace:
        """
        Run detect() and return a trace dict explaining what happened.
        Detectors can override this for richer explanations.
        """
        try:
            achievements = self.detect(swim, ctx, history, all_results, extra)
            fired = len(achievements) > 0
            if fired:
                reason = "; ".join(a.headline for a in achievements[:2])
            else:
                reason = self._no_fire_reason(swim, ctx, history, all_results, extra)
            return DetectorTrace(
                detector_name=self.name,
                ran=True,
                fired=fired,
                reason=reason,
                evidence=[a.evidence[0].statement if a.evidence else "" for a in achievements],
            )
        except Exception as exc:
            return DetectorTrace(
                detector_name=self.name,
                ran=False,
                fired=False,
                reason=f"detector error: {exc}",
            )

    def _no_fire_reason(
        self,
        swim,
        ctx: "MeetContext",
        history: "SwimmerHistory",
        all_results: Optional[list] = None,
        extra: Optional[dict] = None,
    ) -> str:
        """Override in subclasses to explain why the detector didn't fire."""
        return "no notable achievement detected"
