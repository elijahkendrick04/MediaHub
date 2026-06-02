"""
``mediahub.sport_profiles`` — typed sport-profile config + autonomy levels.

A *sport profile* says what a given sport should post: per post type, whether it
is enabled, what data feeds it, which template set renders it, and how autonomous
it may be by default. See ``docs/SPORT_PROFILES.md`` and ``docs/POST_TYPE_TAXONOMY.md``.

This package is **non-breaking scaffolding** introduced by the roadmap rebuild
(Phase 1 groundwork). It is intentionally NOT wired into the running pipeline
yet — later roadmap phases consume it. Importing it has no runtime side effects.
"""

from __future__ import annotations

from .autonomy import AutonomyLevel
from .loader import list_sport_profiles, load_sport_profile
from .schema import PostTypeConfig, SportProfile

__all__ = [
    "AutonomyLevel",
    "PostTypeConfig",
    "SportProfile",
    "load_sport_profile",
    "list_sport_profiles",
]
