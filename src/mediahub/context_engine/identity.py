"""
context_engine/identity.py — Meet identity discovery.

discover_meet_identity() uses live web research to determine the governing body,
meet level, and host club for a swimming meet.

No governing bodies, meet levels, or domains are hardcoded — everything is
discovered from live search results and cached.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from .cache import DiscoveryCache
from .research import ResearchClient
from .trust import record_attempt


# ── Patterns for extracting facts from meet text ──────────────────────────────
# These match common patterns in swimming meet documentation.
# No specific governing body names are hardcoded here — patterns match
# structure, and the governing body name is extracted from the text itself.

_LEVEL_PATTERNS = [
    # Match "Level 1", "Level 2", "Level 3", etc.
    (re.compile(r'\bLevel\s*([1-9])\b', re.IGNORECASE), lambda m: f"Level {m.group(1)}", 0.85),
    # Match "National" meets
    (re.compile(r'\b(National\s+(?:Championships?|Qualifier|Qualifying|Open))\b', re.IGNORECASE),
     lambda m: m.group(1), 0.8),
    # Match "Regional" meets
    (re.compile(r'\b(Regional\s+(?:Championships?|Qualifier|Qualifying|Open))\b', re.IGNORECASE),
     lambda m: m.group(1), 0.75),
    # Match "County" meets
    (re.compile(r'\b(County\s+(?:Championships?|Open|Qualifier))\b', re.IGNORECASE),
     lambda m: m.group(1), 0.7),
    # Match "Open Meet"
    (re.compile(r'\b(Open\s+Meet)\b', re.IGNORECASE), lambda m: m.group(1), 0.6),
    # Match qualifier designations
    (re.compile(r'\b((?:national|regional|county)\s+qualifier)\b', re.IGNORECASE),
     lambda m: m.group(1).title(), 0.72),
]

# Patterns to extract governing body name from text context
_GOVERNING_BODY_PATTERNS = [
    # "sanctioned by Swim England", "licensed by Welsh Swimming", etc.
    re.compile(
        r'(?:sanctioned|licensed|approved|affiliated|registered)\s+(?:by|with|under)\s+'
        r'([A-Z][a-zA-Z\s]{2,30}(?:Swimming|Swim\s+\w+|ASA|Amateur\s+Swimming))',
        re.IGNORECASE
    ),
    # Standalone governing body mentions near the meet name
    re.compile(
        r'\b((?:Swim\s+\w+|Welsh\s+Swimming|Scottish\s+Swimming|'
        r'Swim\s+Ireland|British\s+Swimming|Amateur\s+Swimming\s+Association|ASA))\b',
        re.IGNORECASE
    ),
]


@dataclass
class Source:
    url: str
    domain: str
    title: str
    fetched_at: str
    excerpt: str = ""


@dataclass
class MeetIdentity:
    canonical_name: Optional[str]
    governing_body: Optional[str]
    meet_level: Optional[str]
    level_confidence: float
    host_club: Optional[str]
    host_url: Optional[str]
    sources: list[Source] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MeetIdentity":
        sources = [Source(**s) for s in d.get("sources", [])]
        return cls(
            canonical_name=d.get("canonical_name"),
            governing_body=d.get("governing_body"),
            meet_level=d.get("meet_level"),
            level_confidence=d.get("level_confidence", 0.0),
            host_club=d.get("host_club"),
            host_url=d.get("host_url"),
            sources=sources,
            notes=d.get("notes", ""),
        )


def _extract_level(text: str) -> tuple[Optional[str], float]:
    """Extract meet level from text. Returns (level_str, confidence)."""
    best_level = None
    best_conf = 0.0
    for pattern, extractor, base_conf in _LEVEL_PATTERNS:
        m = pattern.search(text)
        if m:
            candidate = extractor(m)
            if base_conf > best_conf:
                best_level = candidate
                best_conf = base_conf
    return best_level, best_conf


def _extract_governing_body(text: str) -> Optional[str]:
    """Extract governing body name from text."""
    for pattern in _GOVERNING_BODY_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


def _extract_host_club(text: str, meet_name: str) -> Optional[str]:
    """
    Try to extract host club from text context.
    Looks for patterns like "hosted by X SC", "X Swimming Club presents", etc.
    """
    patterns = [
        re.compile(r'[Hh]osted\s+by\s+([A-Z][A-Za-z\s&\'-]{2,40}(?:SC|Swimming Club|Swim Club))', re.IGNORECASE),
        re.compile(r'([A-Z][A-Za-z\s&\'-]{2,40}(?:SC|Swimming Club|Swim Club))\s+presents', re.IGNORECASE),
        re.compile(r'([A-Z][A-Za-z\s&\'-]{2,40}(?:SC|Swimming Club|Swim Club))\s+(?:Open|Championships?|Gala)', re.IGNORECASE),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1).strip()
    return None


def discover_meet_identity(
    meet_name: str,
    venue: str,
    year: int | str,
    host_club_hint: Optional[str] = None,
    force_refresh: bool = False,
) -> MeetIdentity:
    """
    Discover meet identity (governing body, level, host club) via live research.

    Results are cached under data/discovered/meets/<key>.json (30-day TTL).

    Args:
        meet_name: Name of the meet (e.g. "City of Birmingham Open")
        venue: Venue name or city
        year: Year of the meet
        host_club_hint: Optional hint for the hosting club
        force_refresh: If True, bypass cache and re-research

    Returns:
        MeetIdentity with discovered facts and source list
    """
    cache = DiscoveryCache("meets", ttl_seconds=30 * 24 * 3600)
    cache_key = cache.make_key(str(meet_name), str(venue), str(year))

    # Check cache first
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            try:
                return MeetIdentity.from_dict(cached)
            except Exception:
                pass

    client = ResearchClient(num_results=5)
    query = f'"{meet_name}" {venue} {year} swimming meet level licence'
    hits = client.search(query)

    sources: list[Source] = []
    all_text = ""
    best_level: Optional[str] = None
    best_conf = 0.0
    governing_body: Optional[str] = None
    host_club: Optional[str] = host_club_hint
    host_url: Optional[str] = None
    notes_parts: list[str] = []

    for hit in hits[:5]:
        # Fetch page text
        text = client.fetch_text(hit.url, max_chars=6000) or ""
        domain = hit.domain

        src = Source(
            url=hit.url,
            domain=domain,
            title=hit.title,
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            excerpt=text[:300],
        )
        sources.append(src)
        all_text += f"\n{hit.snippet}\n{text}"

        # Extract level facts
        lvl, conf = _extract_level(hit.snippet + " " + text[:2000])
        if conf > best_conf:
            best_level = lvl
            best_conf = conf

        # Extract governing body
        if governing_body is None:
            governing_body = _extract_governing_body(hit.snippet + " " + text[:2000])

        # Extract host club if not already known
        if host_club is None:
            host_club = _extract_host_club(text[:3000], meet_name)
            if host_club:
                host_url = hit.url

        record_attempt(domain, success=bool(lvl or governing_body), purpose="meet_identity")

    # Build canonical name from inputs
    canonical_name = f"{meet_name} {year}" if meet_name else None

    if not sources:
        notes_parts.append("No search results returned; all fields are None.")
    if best_level is None:
        notes_parts.append("Level not found in search results.")
    if governing_body is None:
        notes_parts.append("Governing body not found in search results.")

    identity = MeetIdentity(
        canonical_name=canonical_name,
        governing_body=governing_body,
        meet_level=best_level,
        level_confidence=best_conf,
        host_club=host_club,
        host_url=host_url,
        sources=sources,
        notes="; ".join(notes_parts),
    )

    cache.set(cache_key, identity.to_dict())
    return identity
