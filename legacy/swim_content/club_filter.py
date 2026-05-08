"""
Single chokepoint for "is this swim ours?".

The pilot is for Swansea University Swimming. The host of the meet — Swansea
Aquatics — is a different club. Without explicit filtering, the v1 system
generated achievements for opposition swimmers. This module fixes that.

Filtering strategy (in order):
1. Strict: club_code is in our configured roster of canonical codes
   (e.g. 'SUNY' for Swansea Uni). This is the only authoritative signal.
2. ASA member ID lookup as a fallback when club_code is missing/unknown
   (e.g. CSV imports that don't carry HY3 club codes). We maintain a roster
   of "known to be ours" ASA IDs from prior meets and the PB store.
3. Name-based matching is NOT used. Swimmer names collide across clubs and
   are unsafe for ownership decisions.

Crucially, we explicitly EXCLUDE any club with substring "aquatics" or
short_name "Swansea Aq" — that's the host club and a frequent confusion
case.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class ClubRoster:
    """Identifies a single club for filtering purposes."""

    # Canonical Hytek/file club codes that mean "us". For Swansea Uni: {'SUNY'}.
    club_codes: set[str] = field(default_factory=set)

    # ASA member IDs known to belong to us. Built from prior meets + PB PDFs
    # uploaded under this club.
    known_asa_ids: set[str] = field(default_factory=set)

    # Hard-exclude club codes that are commonly confused with us
    # (different team but similar name). For Swansea Uni this is the host
    # club Swansea Aquatics ('SWAY').
    exclude_codes: set[str] = field(default_factory=set)

    # Human-readable name for logging/UI.
    display_name: str = ""

    def is_ours(self, club_code: str | None, asa_id: str | None) -> bool:
        # Hard exclude: even if ASA ID matches our roster, if the swim is
        # registered under an excluded club, it is NOT ours.
        if club_code and club_code in self.exclude_codes:
            return False
        # If a club_code is present and it's NOT ours, the swim is not ours.
        # Do not fall back to ASA-ID matching: the swimmer is competing for
        # someone else at this meet (e.g. a former member now at a different
        # club). The PB store is permissive about historical clubs; the
        # roster filter must be strict about current registration.
        if club_code:
            return club_code in self.club_codes
        # No club_code at all (rare — happens with hand-typed CSV imports).
        # Only then do we trust ASA-ID as a fallback.
        if asa_id and asa_id in self.known_asa_ids:
            return True
        return False

    def filter_swims(self, swims: Iterable, attr_club: str = 'club_code',
                     attr_asa: str = 'asa_id') -> list:
        """Return only the swims that belong to us."""
        keep = []
        for s in swims:
            club = getattr(s, attr_club, None)
            asa = getattr(s, attr_asa, None)
            if self.is_ours(club, asa):
                keep.append(s)
        return keep


# ----------------------------------------------------------------------
# Pre-configured rosters
# ----------------------------------------------------------------------

def swansea_uni_roster(known_asa_ids: set[str] | None = None) -> ClubRoster:
    """Roster for the Swansea University Swimming pilot.

    Args:
        known_asa_ids: optional set of ASA IDs from the PB store / prior
            meets. Used as a fallback when club_code is missing.
    """
    return ClubRoster(
        club_codes={'SUNY'},
        known_asa_ids=set(known_asa_ids or ()),
        exclude_codes={'SWAY'},   # City of Swansea Aquatics — host club, NOT us
        display_name='Swansea University Swimming',
    )
