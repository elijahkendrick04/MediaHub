# V7.5 — Context Engine + PB Discovery Spec

## Goal
Replace every hardcoded fact about meets/sources/governing bodies with **live research** the engine performs per input, persisting what it learns to disk. The current `web_research.search.WebResearcher` (DuckDuckGo HTML fallback + 30-day cache) is the available web tool — use it.

## Package layout

```
context_engine/
  __init__.py           — public API
  research.py           — query/cache wrapper around web_research.search
  identity.py           — meet identity discovery (name+venue+year → governing body, level, host club)
  trust.py              — per-domain trust ledger (data/discovered_sources.jsonl)
  ontology.py           — load + extend data/ontology/*.json from research
  cache.py              — persistent cache layer (data/discovered/)

pb_discovery/
  __init__.py           — public API: discover_swimmer_pbs(name, club, dob_year=None) -> PBDiscovery
  discover.py           — search the web for candidate sources for this swimmer's PBs
  fetch_profile.py      — generic profile-page fetcher: given any URL, returns text + tables
  parse_pbs.py          — parse PB rows from any layout via the V7.5 interpreter
  cache.py              — per-swimmer-per-run cache layer
```

## Critical rule
**Zero hardcoded references to `swimmingresults.org`, `swimcloud.com`, `british-swimming.org`, etc.** in Python source. The engine searches the web, evaluates results, and persists what it learns.

A test in `tests_v75/test_no_hardcoded_sources.py` must `grep -r 'swimmingresults\.org'` over `context_engine/`, `pb_discovery/`, `interpreter/` and assert ZERO matches.

## Context engine: identity discovery

`context_engine.identity.discover_meet_identity(meet_name, venue, year, host_club_hint=None) -> MeetIdentity`

Returns:
```python
@dataclass
class MeetIdentity:
    canonical_name: Optional[str]
    governing_body: Optional[str]   # e.g. "Swim England" — but DISCOVERED, not assumed
    meet_level: Optional[str]       # learned from text, e.g. "Level 2", "national qualifier"
    level_confidence: float
    host_club: Optional[str]
    host_url: Optional[str]
    sources: list[Source]           # what the engine read to decide
    notes: str
```

Algorithm:
1. Cache check: `data/discovered/meets/<key>.json` — if present, return.
2. Build a search query: `f'"{meet_name}" {venue} {year} swimming meet level licence'`.
3. WebResearcher.search → top N hits.
4. For top hits: fetch the page (use existing `pplx content fetch` via subprocess; if not available, use urllib + light HTML cleaning).
5. From fetched text, extract candidate facts using regex families (level codes, governing-body name patterns). Confidence-score each.
6. Synthesise: pick highest-confidence answer, persist sources used.
7. Cache and return.

## Context engine: ontology growth

`context_engine.ontology.note_new_term(category, term, source)` appends to the JSON file. E.g., when interpreter sees `"Mileage"` as a stroke and confidence is high (because regex+context matched), the context engine records it as an alias under category=strokes, parent stroke decided by research.

## Trust ledger

`data/discovered_sources.jsonl` — append-only:
```jsonl
{"domain": "swimmingresults.org", "first_seen": "...", "last_used": "...", "parse_attempts": 14, "parse_successes": 13, "domains_observed_for": ["meet_id", "swimmer_pbs"]}
{"domain": "swimcloud.com", ...}
```

`context_engine.trust.score_domain(domain) -> float` returns `(parse_successes + 1) / (parse_attempts + 2)` Laplace-smoothed.
`context_engine.trust.rank_candidates(urls) -> list[str]` orders URLs by domain trust + freshness.

The ledger starts empty in code; the engine populates it as it works.

## PB discovery

`pb_discovery.discover.discover_swimmer_pbs(name, club, dob_year=None, run_id=None) -> PBDiscovery`

Returns:
```python
@dataclass
class PBSource:
    url: str
    domain: str
    fetched_at: str
    parse_confidence: float
    pbs: list[PBRow]                # discovered PBs from this source

@dataclass
class PBDiscovery:
    swimmer_query: str
    sources_tried: list[PBSource]
    chosen_source: Optional[PBSource]
    pbs: list[PBRow]                # the chosen source's PBs (or merged if multiple agree)
    confidence: float
    cache_hit: bool

@dataclass
class PBRow:
    event: str                       # canonical
    course: str
    time_canonical: str
    date: Optional[str]
    meet: Optional[str]
    rank: Optional[int]
    raw: dict                        # whatever was parsed; for audit
```

Algorithm:
1. Per-run cache check at `data/discovered/pbs/<run_id>/<swimmer_key>.json`. If present, return.
2. (No run-level cache hit) per-swimmer "warm" cache at `data/discovered/swimmers/<swimmer_key>.json`. If present and the user's run hasn't requested a refresh, use it; otherwise refresh.
3. Build queries:
   - `f'"{name}" {club} swimming personal best times'`
   - `f'"{name}" {club} swimmer profile'`
4. WebResearcher.search → candidate URLs.
5. Rank by trust ledger (domains we've parsed successfully before float to top).
6. For top 3 candidates:
   - Fetch page (urllib + simple cleaner OR `pplx content fetch` if available).
   - Pass content to interpreter (`interpreter.interpret_document(bytes, hint='profile_page')`).
   - Score parse confidence.
7. Pick highest-confidence source, persist its PBs.
8. Update trust ledger.
9. Cache to per-run + per-swimmer locations.

**Per-run-per-swimmer scope** confirmed: within the same recognition run, each swimmer is researched once; subsequent recognition runs may refresh.

## Cache layout

```
data/discovered/
  meets/<key>.json
  swimmers/<key>.json        — long-lived swimmer warm cache
  pbs/<run_id>/<swimmer>.json — per-run cache so all achievements in this run see same data
  search_cache/              — query → results, 30-day TTL (already covered by web_research)
```

## UI surfaces this enables

The recognition page already shows discovered sources (live verified in V7.4 with Manchester International). After V7.5:
- **Source list per achievement** (e.g., the PB chip on a card lists the 1+ source URLs that confirm it; clicking a source opens it).
- **Trust indicator** per source (green/yellow/red based on trust ledger).
- **"How we found this"** expansion showing the search query and the candidates considered.

The web.py changes will be tackled after the engine modules pass tests.

## Tests

`tests_v75/test_pb_discovery.py`:
- Mock the web search to return a small fake corpus of pages.
- Verify the engine ranks/picks correctly.
- Verify the trust ledger updates after a successful parse.
- Verify per-run cache prevents duplicate fetches.

`tests_v75/test_no_hardcoded_sources.py`:
- Grep `context_engine/`, `pb_discovery/`, `interpreter/` for forbidden literals: `swimmingresults`, `swimcloud`, `british-swimming`, `sportsystems` (the literal substring).
- Assert all three return zero matches.

## Anti-shortcut rule
Do NOT import the existing `swim_content_pb` package. Build from scratch using `web_research.search.WebResearcher` and the new `interpreter` package. The old package is dead-end legacy.

## Deliverable
- Files under `context_engine/`, `pb_discovery/` created
- Tests passing
- `CONTEXT_ENGINE_BUILD_REPORT.md` summarising
