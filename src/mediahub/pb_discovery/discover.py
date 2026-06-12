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

import os
import sys
import threading
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
from mediahub.context_engine.trust import rank_candidates, record_attempt

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
    # False when the HTTP fetch itself failed (vs. fetched but ineligible).
    # Lets the snapshot bridge distinguish "couldn't reach any page" from
    # "reached pages, found no verifiable history".
    fetch_success: bool = True

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "domain": self.domain,
            "fetched_at": self.fetched_at,
            "parse_confidence": self.parse_confidence,
            "pbs": [pb.to_dict() for pb in self.pbs],
            "fetch_success": self.fetch_success,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PBSource":
        return cls(
            url=d["url"],
            domain=d["domain"],
            fetched_at=d["fetched_at"],
            parse_confidence=d["parse_confidence"],
            pbs=[PBRow.from_dict(r) for r in d.get("pbs", [])],
            fetch_success=bool(d.get("fetch_success", True)),
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


# Default sport vocabulary. "swimming" / "swimmer" keeps PB discovery working
# exactly as before; passing a different sport (e.g. "athletics" / "athlete")
# makes the same engine work for a new sport with no code change — the engine
# is sport-agnostic, the vocabulary is just a parameter.
_DEFAULT_SPORT = "swimming"

_ATHLETE_NOUNS = {
    "swimming": "swimmer",
    "athletics": "athlete",
    "cycling": "cyclist",
    "running": "runner",
    "rowing": "rower",
}


def _athlete_word(sport: str) -> str:
    """A reasonable athlete noun for a sport ("swimming" -> "swimmer")."""
    s = (sport or _DEFAULT_SPORT).strip().lower()
    if s in _ATHLETE_NOUNS:
        return _ATHLETE_NOUNS[s]
    if s.endswith("ing"):
        return s[:-3] + "er"
    return f"{s} athlete"


def _build_queries(
    name: str, club: str, dob_year: Optional[int], sport: str = _DEFAULT_SPORT
) -> list[str]:
    """Build web search queries for an athlete's PBs (sport-agnostic)."""
    sport = (sport or _DEFAULT_SPORT).strip().lower()
    who = _athlete_word(sport)
    queries = [
        f'"{name}" {club} {sport} personal best times',
        f'"{name}" {club} {who} profile',
    ]
    if dob_year:
        queries.append(f'"{name}" {club} {who} {dob_year}')
    return queries


def _domain_from_url(url: str) -> str:
    import re

    try:
        s = re.sub(r"^https?://", "", url)
        return s.split("/")[0].split("?")[0].split(":")[0].lower()
    except Exception:
        return ""


# --- Identity, authority, and budget-gated research gates ------------------
#
# The deterministic gates the engine review demanded before any discovered page
# can supply a baseline: the page must actually be ABOUT the target athlete
# (name match), and an authoritative source is preferred. The parsed TIME is
# always the deterministic parser's — research, when enabled, only ever
# PROPOSES candidate URLs, never a number.

_NAME_PARTICLES = {"de", "van", "von", "der", "la", "le", "da", "di", "del", "the", "of"}


def _name_tokens(text: str) -> set[str]:
    """Significant lowercased, accent-folded word tokens of a name/text."""
    import re
    import unicodedata

    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return {t for t in re.findall(r"[a-z0-9]+", folded.lower()) if len(t) >= 2}


def _page_is_about_swimmer(page_text: str, name: str) -> bool:
    """True if the page plausibly concerns the target athlete: every significant
    token of their name appears in the page text. Conservative on purpose — a
    wrong personal best is worse than a missing one, so a page that doesn't even
    name the athlete must never supply their baseline (the same-name guard)."""
    want = {t for t in _name_tokens(name) if t not in _NAME_PARTICLES}
    if not want:
        return False
    have = _name_tokens(page_text)
    return want.issubset(have)


def _is_authority(url: str) -> bool:
    """True if the URL's domain is operator-declared authoritative or has earned
    high trust (via web_research.verify). Never raises; no domain hardcoded."""
    try:
        from mediahub.web_research import verify

        return verify.is_authority_source(url)
    except Exception:
        return False


_research_budget_lock = threading.Lock()
_research_budget: dict[str, int] = {}


def _research_limit() -> int:
    """Per-run ceiling on budget-gated deep-research calls. 0 (the default)
    keeps PB discovery 100% deterministic and £0 — research never runs."""
    raw = os.environ.get("MEDIAHUB_PB_RESEARCH_LIMIT", "").strip()
    try:
        return max(0, min(20, int(raw))) if raw else 0
    except ValueError:
        return 0


def _take_research_budget(run_id: str) -> bool:
    """Atomically consume one unit of this run's research budget. False when the
    budget is disabled (the £0 default) or already exhausted — so a big meet
    can't trigger a runaway number of LLM loops."""
    limit = _research_limit()
    if limit <= 0:
        return False
    with _research_budget_lock:
        remaining = _research_budget.get(run_id, limit)
        if remaining <= 0:
            _research_budget[run_id] = 0
            return False
        _research_budget[run_id] = remaining - 1
        return True


def _research_candidate_urls(
    name: str, club: str, sport: str, dob_year: Optional[int]
) -> list[str]:
    """Use the bounded deep-research loop to PROPOSE candidate profile URLs for a
    hard-to-find athlete. Returns URLs only — never the model's prose or any
    time. Authoritative sources first. Never raises."""
    try:
        from mediahub.web_research.deep_research import deep_research

        who = _athlete_word(sport)
        question = (
            f"Find the official {sport} results or profile page that lists the "
            f"personal best times for {who} {name} of {club}"
            + (f", born {dob_year}." if dob_year else ".")
        )
        res = deep_research(question)
        authority = list(res.authority_sources or [])
        rest = [u for u in (res.sources or []) if u not in (res.authority_sources or [])]
        return authority + rest
    except Exception:
        return []


def _evaluate_url(
    url: str, name: str, use_interpreter: bool, sources_tried: "list[PBSource]"
) -> "tuple[Optional[PBSource], bool]":
    """Fetch + deterministically parse one candidate URL, apply the identity
    gate, append the attempt to sources_tried, and record the trust-ledger
    outcome. Returns (source, eligible); eligible means it parsed >=1 PB AND the
    page is about the target athlete."""
    domain = _domain_from_url(url)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    page = fetch_profile_page(url)
    if not page.fetch_success:
        sources_tried.append(
            PBSource(
                url=url,
                domain=domain,
                fetched_at=fetched_at,
                parse_confidence=0.0,
                pbs=[],
                fetch_success=False,
            )
        )
        record_attempt(domain, success=False, purpose="swimmer_pbs")
        return None, False

    pb_rows, confidence = parse_pbs_from_page(page, use_interpreter=use_interpreter)
    identity_ok = _page_is_about_swimmer(page.text, name)
    eligible = bool(pb_rows) and identity_ok

    # A page that parses but isn't about this athlete must never supply a
    # baseline: record it (auditable) with zeroed confidence/PBs so it can't be
    # chosen, and count it as a failed attempt for the trust ledger.
    source = PBSource(
        url=url,
        domain=domain,
        fetched_at=fetched_at,
        parse_confidence=confidence if identity_ok else 0.0,
        pbs=pb_rows if identity_ok else [],
    )
    sources_tried.append(source)
    record_attempt(domain, success=eligible, purpose="swimmer_pbs")
    return source, eligible


def discover_swimmer_pbs(
    name: str,
    club: str,
    dob_year: Optional[int] = None,
    run_id: Optional[str] = None,
    force_refresh: bool = False,
    use_interpreter: bool = True,
    max_sources: int = 3,
    sport: str = _DEFAULT_SPORT,
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
        sport: Sport vocabulary for query building (default "swimming"); makes
            the same engine work for other sports with no code change.

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

    # 3. Build queries and search (sport-agnostic; defaults to swimming)
    client = ResearchClient(num_results=5)
    queries = _build_queries(name, club, dob_year, sport)

    candidate_urls: list[str] = []
    seen_urls: set[str] = set()

    def _add_candidates(urls: list[str]) -> list[str]:
        fresh: list[str] = []
        for u in urls:
            if u and u not in seen_urls:
                seen_urls.add(u)
                candidate_urls.append(u)
                fresh.append(u)
        return fresh

    for query in queries:
        _add_candidates([hit.url for hit in client.search(query, num=5)])

    # 4-6. Rank by trust, fetch top N, deterministically parse, identity-gate,
    # and select. Selection prefers an authoritative source, then parse
    # confidence — but the TIME is always the deterministic parser's; selection
    # only decides WHICH verified page to trust.
    sources_tried: list[PBSource] = []
    best_source: Optional[PBSource] = None
    best_key: Optional[tuple[int, float]] = None

    def _consider(urls: list[str]) -> None:
        nonlocal best_source, best_key
        for url in rank_candidates(urls)[:max_sources]:
            source, eligible = _evaluate_url(url, name, use_interpreter, sources_tried)
            if not eligible or source is None:
                continue
            key = (1 if _is_authority(url) else 0, source.parse_confidence)
            if best_key is None or key > best_key:
                best_key, best_source = key, source

    _consider(list(candidate_urls))

    # 6b. Budget-gated research — £0 and OFF by default (see
    # MEDIAHUB_PB_RESEARCH_LIMIT). Only when the deterministic pass found no page
    # that is both parseable AND about this athlete do we spend one unit of the
    # run's research budget to PROPOSE more candidate URLs. deep_research never
    # supplies a time — the same deterministic parse + identity gate decide.
    if best_source is None and _take_research_budget(run_id):
        researched = _add_candidates(_research_candidate_urls(name, club, sport, dob_year))
        if researched:
            _consider(researched)

    # 7. Build result
    result = PBDiscovery(
        swimmer_query=swimmer_query,
        sources_tried=sources_tried,
        chosen_source=best_source,
        pbs=best_source.pbs if best_source else [],
        confidence=best_source.parse_confidence if best_source else 0.0,
        cache_hit=False,
    )

    # 8. Cache to run + warm swimmer cache
    result_dict = result.to_dict()
    run_cache.set(swimmer_key, result_dict)
    warm_cache.set(swimmer_key, result_dict)

    return result
