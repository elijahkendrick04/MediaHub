"""
pb_discovery/discover.py — Search the web for a swimmer's personal best times.

Algorithm:
1. Per-run cache check (same swimmer is fetched only once per recognition run).
2. Warm swimmer cache check (7-day TTL across runs).
3. Build search queries and call WebResearcher.
4. Rank candidate URLs by trust ledger.
5. Fetch top 3 candidates, parse PBs from each.
6. Pick highest-confidence source, update trust ledger.
7. Cache results per-run and in warm swimmer cache.

No source domains are hardcoded. The engine discovers sources via web search
and ranks them by empirical success (trust ledger).
"""
from __future__ import annotations

import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ensure repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mediahub.context_engine.research import ResearchClient
from mediahub.context_engine.trust import score_domain, rank_candidates, record_attempt

from .cache import RunCache, WarmCache, make_swimmer_key
from .fetch_profile import fetch_profile_page
from .parse_pbs import PBRow, parse_pbs_from_page


@dataclass
class PBSource:
    """A candidate source tried during PB discovery."""
    url: str
    domain: str
    fetched_at: str
    parse_confidence: float
    pbs: list[PBRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "domain": self.domain,
            "fetched_at": self.fetched_at,
            "parse_confidence": self.parse_confidence,
            "pbs": [pb.to_dict() for pb in self.pbs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PBSource":
        return cls(
            url=d["url"],
            domain=d["domain"],
            fetched_at=d["fetched_at"],
            parse_confidence=d["parse_confidence"],
            pbs=[PBRow.from_dict(r) for r in d.get("pbs", [])],
        )


@dataclass
class PBDiscovery:
    """Result of discovering a swimmer's personal bests."""
    swimmer_query: str
    sources_tried: list[PBSource] = field(default_factory=list)
    chosen_source: Optional[PBSource] = None
    pbs: list[PBRow] = field(default_factory=list)
    confidence: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> dict:
        return {
            "swimmer_query": self.swimmer_query,
            "sources_tried": [s.to_dict() for s in self.sources_tried],
            "chosen_source": self.chosen_source.to_dict() if self.chosen_source else None,
            "pbs": [pb.to_dict() for pb in self.pbs],
            "confidence": self.confidence,
            "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PBDiscovery":
        chosen = None
        if d.get("chosen_source"):
            chosen = PBSource.from_dict(d["chosen_source"])
        return cls(
            swimmer_query=d["swimmer_query"],
            sources_tried=[PBSource.from_dict(s) for s in d.get("sources_tried", [])],
            chosen_source=chosen,
            pbs=[PBRow.from_dict(r) for r in d.get("pbs", [])],
            confidence=d.get("confidence", 0.0),
            cache_hit=d.get("cache_hit", False),
        )


def _build_queries(name: str, club: str, dob_year: Optional[int]) -> list[str]:
    """Build web search queries for a swimmer's PBs."""
    queries = [
        f'"{name}" {club} swimming personal best times',
        f'"{name}" {club} swimmer profile',
    ]
    if dob_year:
        queries.append(f'"{name}" {club} swimmer {dob_year}')
    return queries


def _domain_from_url(url: str) -> str:
    import re
    try:
        s = re.sub(r'^https?://', '', url)
        return s.split('/')[0].split('?')[0].split(':')[0].lower()
    except Exception:
        return ""


def discover_swimmer_pbs(
    name: str,
    club: str,
    dob_year: Optional[int] = None,
    run_id: Optional[str] = None,
    force_refresh: bool = False,
    use_interpreter: bool = True,
    max_sources: int = 3,
) -> PBDiscovery:
    """
    Discover a swimmer's personal best times via live web research.

    Per-run cache ensures each swimmer is only researched once per run.
    Warm cache persists results across runs (7-day TTL).

    Args:
        name: Swimmer's full name.
        club: Swimmer's club name.
        dob_year: Optional year of birth for disambiguation.
        run_id: Recognition run identifier. If None, a UUID is generated.
        force_refresh: If True, bypass all caches.
        use_interpreter: Whether to try the interpreter package for parsing.
        max_sources: Maximum number of candidate URLs to try.

    Returns:
        PBDiscovery with discovered PBs, sources tried, and confidence.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    swimmer_key = make_swimmer_key(name, club)
    swimmer_query = f"{name} ({club})"

    run_cache = RunCache(run_id)
    warm_cache = WarmCache()

    # 1. Per-run cache check
    if not force_refresh and run_cache.has(swimmer_key):
        cached = run_cache.get(swimmer_key)
        if cached is not None:
            result = PBDiscovery.from_dict(cached)
            result.cache_hit = True
            return result

    # 2. Warm swimmer cache check
    if not force_refresh:
        cached = warm_cache.get(swimmer_key)
        if cached is not None:
            result = PBDiscovery.from_dict(cached)
            result.cache_hit = True
            # Populate run cache too
            run_cache.set(swimmer_key, result.to_dict())
            return result

    # 3. Build queries and search
    client = ResearchClient(num_results=5)
    queries = _build_queries(name, club, dob_year)

    candidate_urls: list[str] = []
    seen_urls: set[str] = set()

    for query in queries:
        hits = client.search(query, num=5)
        for hit in hits:
            if hit.url not in seen_urls:
                candidate_urls.append(hit.url)
                seen_urls.add(hit.url)

    # 4. Rank by trust ledger (highest trust first)
    ranked_urls = rank_candidates(candidate_urls)

    # 5. Fetch top N candidates and parse PBs
    sources_tried: list[PBSource] = []
    best_source: Optional[PBSource] = None
    best_confidence = 0.0

    for url in ranked_urls[:max_sources]:
        domain = _domain_from_url(url)
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        page = fetch_profile_page(url)

        if not page.fetch_success:
            sources_tried.append(PBSource(
                url=url,
                domain=domain,
                fetched_at=fetched_at,
                parse_confidence=0.0,
                pbs=[],
            ))
            record_attempt(domain, success=False, purpose="swimmer_pbs")
            continue

        pb_rows, confidence = parse_pbs_from_page(page, use_interpreter=use_interpreter)
        success = len(pb_rows) > 0

        source = PBSource(
            url=url,
            domain=domain,
            fetched_at=fetched_at,
            parse_confidence=confidence,
            pbs=pb_rows,
        )
        sources_tried.append(source)

        # 6. Update trust ledger
        record_attempt(domain, success=success, purpose="swimmer_pbs")

        # Track best source
        if confidence > best_confidence:
            best_confidence = confidence
            best_source = source

    # 7. Build result
    result = PBDiscovery(
        swimmer_query=swimmer_query,
        sources_tried=sources_tried,
        chosen_source=best_source,
        pbs=best_source.pbs if best_source else [],
        confidence=best_confidence,
        cache_hit=False,
    )

    # 8. Cache to run + warm swimmer cache
    result_dict = result.to_dict()
    run_cache.set(swimmer_key, result_dict)
    warm_cache.set(swimmer_key, result_dict)

    return result
