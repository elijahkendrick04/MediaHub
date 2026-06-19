"""
pb_history/identity.py — stable keys for the cross-upload PB history.

Matching a swimmer across separately-uploaded meets has no shared ID to lean on
(interpreter swimmers carry no ASA number), so we derive a deterministic key
from the fields a results file always has: name + club + year of birth. The key
is deliberately CONSERVATIVE — if two uploads disagree on any of those, the
swimmer is treated as new, which can MISS a PB but never invents a wrong one (a
wrong PB is worse than a missing one). No swim vocabulary or sources hardcoded.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Generic club words that carry no identity (so "Brighton Dolphins SC" and
# "Brighton Dolphins Swimming Club" fold to the same club core).
_CLUB_STOPWORDS = {
    "sc",
    "asc",
    "sclub",
    "club",
    "swimming",
    "swim",
    "swimmers",
    "aquatics",
    "aquatic",
    "amateur",
    "the",
    "of",
    "and",
    "team",
}

_NONALNUM = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NONALNUM.sub(" ", s.lower())
    return _WS.sub(" ", s).strip()


def _name_core(first: str, last: str) -> str:
    """Order-independent, accent-folded name core ("last|first")."""
    return f"{_fold(last)}|{_fold(first)}"


def _club_core(club: str) -> str:
    """Distinctive club tokens, sorted, with generic swim words removed."""
    toks = [t for t in _fold(club).split() if t and t not in _CLUB_STOPWORDS]
    return " ".join(sorted(toks))


def swimmer_identity(
    first_name: str,
    last_name: str,
    club: Optional[str] = None,
    yob: Optional[int] = None,
) -> str:
    """A stable, conservative cross-upload identity key for one swimmer.

    Built from name + club core + year of birth. Returns ``""`` when there is no
    usable name (the caller then skips the swimmer rather than store a blank
    identity that would merge unrelated people).
    """
    name = _name_core(first_name or "", last_name or "")
    if not name.strip("|"):
        return ""
    return f"{name}|{_club_core(club or '')}|{yob or ''}"


def name_key(first_name: str, last_name: str) -> str:
    """Order-independent folded name tokens (e.g. "effy johnson"), used so a
    data-subject erasure can find a swimmer's rows whether the source wrote
    "First Last" or "Last, First". Returns "" when there is no usable name."""
    toks = sorted(t for t in _fold(f"{first_name or ''} {last_name or ''}").split() if t)
    return " ".join(toks)


def event_key(distance: int, stroke: str, course: str) -> str:
    """Canonical event key ``"100FRLC"`` — distance + stroke code + course.

    Matches ``swim_content_v5.history`` so a snapshot built from the store feeds
    the existing PB detectors unchanged.
    """
    return f"{distance}{(stroke or '').upper()}{(course or '').upper()}"


_MEET_NONALNUM = re.compile(r"[^A-Z0-9 ]")


def canon_meet_key(name: Optional[str], start_date: Optional[str], venue: Optional[str]) -> str:
    """A stable key identifying ONE meet, for same-meet exclusion and idempotent
    re-runs. Canonicalises the name (uppercase, alnum-only, collapsed) and pairs
    it with the start date and a folded venue. Re-uploading the same meet yields
    the same key, so its rows replace rather than duplicate."""
    nm = _MEET_NONALNUM.sub(" ", (name or "").upper())
    nm = _WS.sub(" ", nm).strip()
    ven = _fold(venue or "")
    return f"{nm}|{(start_date or '').strip()}|{ven}"
