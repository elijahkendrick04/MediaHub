# V7.5 Context Engine + PB Discovery — Build Report

## Status: COMPLETE ✓

All 27 tests pass:
- `tests_v75/test_pb_discovery.py` — 11 passed
- `tests_v75/test_no_hardcoded_sources.py` — 16 passed

---

## Packages Built

### `context_engine/`

| File | Purpose |
|------|---------|
| `__init__.py` | Public API exports |
| `research.py` | `ResearchClient` — wraps `WebResearcher` (DDG HTML fallback), adds `SearchHit` dataclass and `fetch_text()` / `fetch_bytes()` via urllib + BeautifulSoup |
| `identity.py` | `discover_meet_identity()` — live research for governing body, meet level, host club. Regex pattern families match level codes and governing-body name structures from fetched text. 30-day cache. |
| `trust.py` | Domain trust ledger at `data/discovered_sources.jsonl` (append-only JSONL). `score_domain()` uses Laplace smoothing: `(successes+1)/(attempts+2)`. `rank_candidates()` sorts URLs by trust (stable sort). `record_attempt()` updates ledger after each parse attempt. |
| `ontology.py` | Loads `data/ontology/*.json`. `note_new_term()` appends new aliases discovered at runtime. `lookup_canonical()` maps raw terms to canonical form. Thread-safe. |
| `cache.py` | `DiscoveryCache` — namespace-scoped persistent JSON cache under `data/discovered/`. `SubpathCache` for per-run/sub-directory storage. Key hashing via MD5. |

### `pb_discovery/`

| File | Purpose |
|------|---------|
| `__init__.py` | Public API: `discover_swimmer_pbs()`, `PBDiscovery`, `PBSource`, `PBRow` |
| `discover.py` | Main entry point. Builds search queries, calls `WebResearcher`, ranks by trust ledger, fetches top 3 candidates, picks highest-confidence source, updates trust ledger, writes per-run + warm caches. |
| `fetch_profile.py` | Generic profile-page fetcher: urllib + BeautifulSoup (stdlib fallback). Extracts both text and HTML tables. Returns `ProfilePage` dataclass. |
| `parse_pbs.py` | Two-stage parser: (1) lazy import of `interpreter.interpret_document()` — raises clear `ImportError` message if not yet built; (2) heuristic regex fallback (time patterns, stroke names, distance patterns, course detection). Returns `list[PBRow]` + confidence float. |
| `cache.py` | `RunCache` — per-run-per-swimmer (no TTL, scoped by `run_id`). `WarmCache` — cross-run 7-day TTL under `data/discovered/swimmers/`. `make_swimmer_key()` is case-insensitive, deterministic MD5-based. |

---

## Cache Layout

```
data/discovered/
  meets/<key>.json              — meet identity (30-day TTL)
  swimmers/<key>.json           — warm swimmer PB cache (7-day TTL)
  pbs/<run_id>/<swimmer>.json   — per-run cache (no TTL, scoped to run)
data/discovered_sources.jsonl   — trust ledger (append-only JSONL)
data/ontology/*.json            — growing ontology (strokes, etc.)
```

---

## Critical Constraints Satisfied

### 1. Zero hardcoded source references
Verified by `test_no_hardcoded_sources.py` (16 tests, parametrised over all forbidden literals × all packages). Zero matches for:
- `swimmingresults`
- `swimcloud`
- `british-swimming`
- `sportsystems`

### 2. Uses existing `WebResearcher`
`context_engine/research.py` imports and wraps `web_research.search.WebResearcher`. All searches go through it (DuckDuckGo HTML fallback + 30-day cache).

### 3. Page fetching via urllib + BeautifulSoup
`fetch_profile.py` and `research.py` use `urllib.request` for HTTP. BeautifulSoup for HTML cleaning (stdlib regex fallback if not available). No pplx subprocess dependency.

### 4. No `swim_content_pb` import
Built from scratch. No reference to legacy package.

### 5. Lazy interpreter import
`parse_pbs.py` imports `interpreter` inside the `_interpreter_extract_pbs()` function with `try/except ImportError`. If interpreter is not built, falls back to heuristic extraction without crashing. Tests use a monkeypatched stub via the `inject_interpreter_stub` autouse fixture.

### 6. Per-run-per-swimmer cache
`RunCache(run_id)` stores each swimmer under `data/discovered/pbs/<run_id>/<swimmer_key>.json`. The second call for the same swimmer in the same run returns `cache_hit=True` without re-fetching.

---

## Test Coverage

### `test_pb_discovery.py` (11 tests)

| Class | Tests |
|-------|-------|
| `TestPBDiscoveryRanking` | Picks highest-confidence source; high-trust domains rank first |
| `TestTrustLedger` | Ledger updated after success; Laplace scoring; unknown domain prior=0.5 |
| `TestPerRunCache` | Second call is cache hit; different run_ids fetch independently |
| `TestInterpreterStub` | Stub returns valid PBs; `parse_pbs_from_page` uses interpreter |
| `TestWarmCache` | Set/get round-trip; `make_swimmer_key` is stable and case-insensitive |

### `test_no_hardcoded_sources.py` (16 tests)

- 12 parametrised tests: 4 forbidden literals × 3 packages
- 4 aggregate tests: per-package checks + meta-test confirming both required packages exist

---

## Design Decisions

- **Trust ledger is ephemeral-friendly**: starts empty, earns trust from empirical use. No bootstrap assumptions about any domain.
- **Heuristic fallback in `parse_pbs`**: even without the interpreter package, the engine can extract PBs from structured HTML tables and free text using time/stroke/distance regex patterns.
- **Warm + run caches decouple refresh granularity**: warm cache is 7-day TTL; run cache is per-session with no TTL. Both layers are checked before doing any network I/O.
- **`rank_candidates` uses stable sort**: Python's `sorted()` is always stable, so equal-trust domains preserve their original search-result order (earlier hits = higher recency signal from DDG).
- **BeautifulSoup used with lxml parser**: cleaner HTML extraction than the stdlib regex fallback, and BeautifulSoup is already in `requirements.txt`.

---

## Files Created

```
context_engine/
  __init__.py
  cache.py
  identity.py
  ontology.py
  research.py
  trust.py

pb_discovery/
  __init__.py
  cache.py
  discover.py
  fetch_profile.py
  parse_pbs.py

tests_v75/
  __init__.py
  test_pb_discovery.py
  test_no_hardcoded_sources.py

data/discovered/
  meets/        (directory)
  swimmers/     (directory)
  pbs/          (directory)
  search_cache/ (directory)

CONTEXT_ENGINE_BUILD_REPORT.md  (this file)
```
