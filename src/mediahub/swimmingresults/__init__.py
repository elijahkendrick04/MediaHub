"""
swimmingresults — authoritative online PB baseline from swimmingresults.org.

British Swimming's rankings site holds a swimmer's COMPLETE licensed-meet
history, so it is the only baseline that can answer "is this a PB?" without the
false positives a partial, MediaHub-only record produces. This package resolves
a meet's swimmers to their member id and reads their official personal bests,
fresh every run.

Public API:
    lookup_official_pbs(meet, our_swimmer_keys, club_name, ...) -> {swimmer_key: BridgedSnapshot}
    resolve_club_code(club_name) -> Optional[str]
"""

from __future__ import annotations

from .clubs import resolve_club_code
from .lookup import SOURCE_DOMAIN, lookup_official_pbs

__all__ = ["lookup_official_pbs", "resolve_club_code", "SOURCE_DOMAIN"]
