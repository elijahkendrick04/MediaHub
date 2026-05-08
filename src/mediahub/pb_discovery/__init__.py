"""
pb_discovery — V7.5 Personal Best Discovery public API.

Provides discover_swimmer_pbs() to find a swimmer's personal best times
via live web research. Results are cached per-run-per-swimmer to avoid
redundant fetches within a single recognition run.

No sources are hardcoded — the engine searches the web and evaluates
candidates based on the trust ledger.
"""

from .discover import discover_swimmer_pbs, PBDiscovery, PBSource, PBRow

__all__ = [
    "discover_swimmer_pbs",
    "PBDiscovery",
    "PBSource",
    "PBRow",
]
