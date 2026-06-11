"""
history/provider.py — Abstract HistoryProvider base class.

Swimming implements this via swim_content_pb.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .schema import PreviousBest, IdentityMatch


class HistoryProvider(ABC):
    """
    Abstract base class for sport-specific history providers.

    Each sport implements a subclass that:
    - Resolves participant identity
    - Fetches/caches historical performance data
    - Returns PreviousBest objects
    """

    sport: str = "abstract"

    @abstractmethod
    def resolve_identity(self, participant_id: Optional[str], name: str) -> IdentityMatch:
        """
        Attempt to match the participant to an authoritative external record.
        Returns an IdentityMatch with safe_to_use=False if identity is uncertain.
        """
        raise NotImplementedError

    @abstractmethod
    def get_previous_best(
        self,
        participant_id: Optional[str],
        name: str,
        event_key: str,
        exclude_event_name: Optional[str] = None,
        exclude_date_iso: Optional[str] = None,
    ) -> Optional[PreviousBest]:
        """
        Return the participant's previous best for event_key, excluding
        performances from the current event if specified.
        Returns None if no history is available.
        """
        raise NotImplementedError
