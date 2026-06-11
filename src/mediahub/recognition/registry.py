"""
recognition/registry.py — Sport registry.

register_sport(name, ...) registers a sport config.
get_sport(name) retrieves it.
list_sports() returns sorted list of registered sport names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SportConfig:
    sport: str
    display_name: str
    detectors: list  # list of AchievementDetector instances
    history_provider: Optional[object] = None  # HistoryProvider implementation
    default_voice_templates: dict = field(default_factory=dict)


_SPORTS: dict[str, SportConfig] = {}


def register_sport(
    sport: str,
    display_name: str = "",
    detectors: Optional[list] = None,
    history_provider: Optional[object] = None,
    default_voice_templates: Optional[dict] = None,
) -> None:
    """Register a sport configuration."""
    _SPORTS[sport] = SportConfig(
        sport=sport,
        display_name=display_name or sport.title(),
        detectors=detectors or [],
        history_provider=history_provider,
        default_voice_templates=default_voice_templates or {},
    )


def get_sport(sport: str) -> Optional[SportConfig]:
    """Return the SportConfig for a registered sport, or None."""
    return _SPORTS.get(sport)


def list_sports() -> list[str]:
    """Return sorted list of registered sport names."""
    return sorted(_SPORTS.keys())


__all__ = ["SportConfig", "register_sport", "get_sport", "list_sports"]
