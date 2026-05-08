"""
build_meet_context(meet) -> MeetContext

Extracts structured context from the canonical Meet object, inferring
meet level, whether finals are present, age groups, etc.
"""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from .schema import MeetContext

if TYPE_CHECKING:
    from swim_content_v4.canonical import Meet


# ---------------------------------------------------------------------------
# Meet-level detection heuristics
# ---------------------------------------------------------------------------

_NATIONAL_KEYWORDS = [
    "national", "nationals", "championship", "championships",
    "british", "gb open", "great britain", "world", "european",
    "international", "olympic", "commonwealth",
]

_UNIVERSITY_KEYWORDS = [
    "bucs", "university", "uniswim", "varsity", "student",
]

_COUNTY_KEYWORDS = [
    "county", "regional", "region", "asa county", "welsh",
    "scottish", "northern ireland",
]

_OPEN_KEYWORDS = [
    "open", "invite", "invitational", "club champs", "gala",
    "long course", "short course", "lc", "sc", "aquatics",
]


def _infer_meet_level(name: str, governing_body: Optional[str]) -> str:
    """Infer meet level from the name and governing body string."""
    n = (name or "").lower()
    g = (governing_body or "").lower()

    if any(k in n for k in _NATIONAL_KEYWORDS) or any(k in g for k in _NATIONAL_KEYWORDS):
        return "national"
    if any(k in n for k in _UNIVERSITY_KEYWORDS) or any(k in g for k in _UNIVERSITY_KEYWORDS):
        return "university"
    if any(k in n for k in _COUNTY_KEYWORDS):
        return "county"
    if any(k in n for k in _OPEN_KEYWORDS):
        return "open"
    return "open"


def _has_finals(meet) -> bool:
    """Check if meet has distinct finals rounds (not just timed finals)."""
    for r in getattr(meet, "results", []):
        rnd = (getattr(r, "round", "") or "").lower()
        if rnd == "final":
            return True
    return False


def _extract_age_groups(meet) -> list[str]:
    """Extract distinct age band labels from results."""
    bands = set()
    for r in getattr(meet, "results", []):
        band = (getattr(r, "age_band", "") or "").strip()
        if band and band not in ("", "0-99", "OPEN", "open"):
            bands.add(band)
    return sorted(bands)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_meet_context(meet, research_data: Optional[dict] = None) -> MeetContext:
    """
    Build a MeetContext from a canonical Meet object, optionally enriched
    with research data from ResearchClient.search_meet_context().
    """
    name = getattr(meet, "name", "") or "(unknown)"
    venue = getattr(meet, "venue", None)
    course = getattr(meet, "course", "LC") or "LC"
    start_date = getattr(meet, "start_date", None)
    end_date = getattr(meet, "end_date", None)
    governing_body = getattr(meet, "governing_body", None)
    host_club_code = getattr(meet, "host_club_code", None)

    # Base inferences
    meet_level = _infer_meet_level(name, governing_body)
    has_fin = _has_finals(meet)
    age_groups = _extract_age_groups(meet)
    has_age = len(age_groups) > 0

    ctx = MeetContext(
        meet_name=name,
        venue=venue,
        course=course,
        start_date=start_date,
        end_date=end_date,
        governing_body=governing_body,
        meet_level=meet_level,
        has_finals=has_fin,
        has_age_groups=has_age,
        age_groups=age_groups,
        host_club_code=host_club_code,
        research_available=False,
    )

    # Enrich from research if available
    if research_data and not research_data.get("error") and research_data.get("ok", True) is not False:
        ctx.research_available = True

        # Override meet_level if research found it
        if research_data.get("meet_level"):
            ctx.meet_level = research_data["meet_level"]
        if research_data.get("has_finals") is not None:
            ctx.has_finals = ctx.has_finals or research_data["has_finals"]
        if research_data.get("governing_body") and not ctx.governing_body:
            ctx.governing_body = research_data["governing_body"]

        # Collect research sources
        for src in research_data.get("sources", []):
            ctx.research_sources.append(src)
    elif research_data and research_data.get("error"):
        ctx.research_error = research_data["error"]

    return ctx
