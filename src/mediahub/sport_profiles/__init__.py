"""
``mediahub.sport_profiles`` — typed sport-profile config + autonomy levels.

A *sport profile* says what a given sport should post: per post type, whether it
is enabled, what data feeds it, which template set renders it, and how autonomous
it may be by default. See ``docs/SPORT_PROFILES.md`` and ``docs/POST_TYPE_TAXONOMY.md``.

Consumed by the running product: ``content_engine/planner.py`` (plan builds),
``club_platform/post_types.py`` and ``club_platform/format_catalog.py`` (per-sport
post types / formats), and the web routes (sport selection, goals, calendar).
Importing it has no runtime side effects.
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
