# V6 Build Specification — PB Accuracy & History Intelligence

**Goal:** make PB fetching accurate enough that `fetch_pbs=True` becomes the default. No false PB claims, full audit trail, manual override path for ambiguous swimmers.

## User decisions (locked)

1. **Accuracy over speed.** Use conservative concurrency. Better to take 30s and be right than 5s and wrong.
2. **No fuzzy name matching.** If the SR-returned swimmer name doesn't exactly match the HY3 name (after format canonicalisation only — uppercase, strip punctuation, normalise whitespace), mark `needs_verification` and suppress PB detection for that swimmer.
3. **Per-meet corrections.** When a swimmer is `needs_verification`, user can provide the correct ASA number for that meet only. Do NOT auto-merge to other runs. Optional separate "save this mapping permanently" action for later.

## Architecture: new package `swim_content_pb/`

Top-level package, sibling to `swim_content_v4/` and `swim_content_v5/`. Importable by both. Lives at `/home/user/workspace/swim-content/swim_content_pb/`.

### Files

```
swim_content_pb/
├── __init__.py            Version constant, module-level convenience exports
├── schema.py              All dataclasses (see below)
├── identity.py            Multi-strategy swimmer matcher
├── fetcher.py             Concurrent HTTP fetcher with budget + circuit breaker
├── parser.py              Improved SR HTML parser
├── cache.py               Versioned, source-stamped disk cache
├── history.py             PreviousPB derivation excluding same-meet duplicates
├── matcher.py             Safe swim-vs-PB comparator
├── audit.py               PBAudit dataclass and audit logger
├── corrections.py         Per-meet override store
├── ground_truth.py        PB-specific ground-truth harness
└── tests/
    ├── __init__.py
    ├── fixtures/          HTML files for known SR pages
    │   ├── sr_basic.html
    │   ├── sr_multi_event.html
    │   ├── sr_same_meet.html
    │   └── sr_404.html
    ├── test_identity.py
    ├── test_parser.py
    ├── test_history.py
    ├── test_matcher.py
    └── test_corrections.py
```

### Dataclasses (`schema.py`)

```python
@dataclass
class IdentityMatch:
    """Result of matching a HY3 swimmer to a swimmingresults.org record."""
    asa_id: str | None
    hy3_name: str                       # raw name from HY3
    sr_name: str | None                 # name returned by SR page
    canonical_hy3_name: str             # normalised for compare
    canonical_sr_name: str | None
    method: str                         # "asa_id_verified" | "asa_id_unverified" |
                                        # "needs_verification" | "no_id" | "manual_override"
    confidence: float                   # 0.0-1.0
    safe_to_use: bool                   # if False, suppress PB detection
    notes: list[str]                    # human-readable trail
    alternative_matches: list[dict]     # if SR returned ambiguity (rare)


@dataclass
class PreviousPB:
    """A swimmer's PB for a specific event/course as of a specific date."""
    swimmer_asa_id: str
    swimmer_name: str
    event_distance: int
    event_stroke: str                   # canonical: free|back|breast|fly|im
    course: str                         # "LC" | "SC"
    time_seconds: float
    time_display: str                   # "1:01.42"
    pb_date_iso: str | None
    pb_meet_name: str | None
    source_url: str
    fetched_at: str                     # ISO timestamp
    excluded_swims: list[dict]          # swims excluded as same-meet duplicates
    confidence: str                     # "high" | "medium" | "low"
    notes: list[str]


@dataclass
class PBDecision:
    """Outcome of comparing a current swim to a PreviousPB."""
    status: str                         # "CONFIRMED_PB" | "LIKELY_PB" |
                                        # "NOT_PB" | "PB_UNVERIFIED" |
                                        # "AMBIGUOUS" | "SUPPRESSED_NEEDS_VERIFICATION"
    swim_id: str
    swimmer_asa_id: str | None
    swimmer_name: str
    event: str
    course: str
    current_time_seconds: float
    current_time_display: str
    previous_pb: PreviousPB | None
    delta_seconds: float | None         # negative = improvement
    improvement_percentage: float | None
    same_meet_excluded_count: int
    reason: str
    evidence: list[dict]                # source URL, fetched_at, time, etc.
    safe_to_post: bool
    confidence: str
    uncertainty_notes: list[str]
    audit_trail: list[str]              # step-by-step decision log


@dataclass
class PBAudit:
    """Per-swimmer audit summary for the run."""
    asa_id: str | None
    hy3_name: str
    sr_name: str | None
    identity: IdentityMatch
    events_fetched: list[str]
    pb_decisions: list[PBDecision]
    achievements_generated: list[str]   # achievement type names
    achievements_suppressed: list[str]  # type names + reasons
    fetch_ok: bool
    fetch_error: str | None
    source_urls: list[str]
    fetched_at: str | None


@dataclass
class RunPBAudit:
    """Aggregate audit for the whole run."""
    run_id: str
    swimmers_total: int
    swimmers_matched_verified: int
    swimmers_needs_verification: int
    swimmers_no_id: int
    swimmers_fetch_failed: int
    pb_decisions_count: int
    pb_confirmed_count: int
    pb_likely_count: int
    pb_not_pb_count: int
    pb_unverified_count: int
    pb_suppressed_count: int
    pb_ambiguous_count: int
    fetch_total_seconds: float
    fetch_budget_exceeded: bool
    cache_hits: int
    cache_misses: int
    per_swimmer: list[PBAudit]
    warnings: list[str]
    started_at: str
    finished_at: str
```

### Identity matcher (`identity.py`)

```python
def canonicalise_name(name: str) -> str:
    """Normalise a name for comparison: uppercase, strip punctuation,
    collapse whitespace, sort given/family components.

    Handles formats:
      - "BRADLEY, MATHEW J" (HY3)
      - "Mathew Bradley" (SR)
      - "MATHEW J BRADLEY"
    
    Returns a canonical form like "BRADLEY MATHEW" (surnames first, alphabetical
    given names, no middle initials).
    
    NO FUZZY MATCHING. This only normalises format differences.
    """

def match_swimmer(
    *,
    hy3_swimmer: ParsedSwimmer,
    sr_snapshot: SwimmerPBSnapshot | None,
    corrections: CorrectionsStore,
    run_id: str,
) -> IdentityMatch:
    """Apply the matching strategy in priority order:
      1. corrections.has_override(run_id, hy3_swimmer.asa_id) → manual_override
      2. asa_id present + sr_snapshot.fetch_ok + canonical names match
         → asa_id_verified, safe_to_use=True, confidence=1.0
      3. asa_id present + sr_snapshot.fetch_ok + names DON'T match
         → needs_verification, safe_to_use=False, confidence=0.0
      4. asa_id present + sr_snapshot.fetch_failed
         → asa_id_unverified, safe_to_use=False, confidence=0.0
      5. No asa_id at all
         → no_id, safe_to_use=False, confidence=0.0
    """
```

### Parser (`parser.py`)

Improvements over `swim_content/enrichment_swimmingresults.py`:

- **Canonical event labels.** Map every distance/stroke variant to a single key (e.g. `(50, "freestyle", "LC")`, `(200, "individual_medley", "SC")`). Handle "Free", "Freestyle", "FR", "F", "IM", "Medley", "Individual Medley", "Back", "Backstroke", "BK", etc.
- **Multiple entries per event.** SR pages list every recent swim per event; current parser only takes the best. New parser keeps the full list and the "best" flag.
- **Robust date parsing.** Handle `dd/mm/yyyy`, `dd-mmm-yyyy`, `dd MMM yyyy`. Output ISO.
- **Same-meet duplicate identification.** Each parsed entry retains `meet_name` and `venue` if present in the row, so `history.py` can exclude them.
- **Course explicitness.** Never default course; if not derivable from the table heading, mark course as `UNKNOWN` and skip.

### Cache (`cache.py`)

```python
class PBCache:
    cache_dir: Path
    schema_version: str = "v6.0"
    
    def get(self, asa_id: str, max_age_days: int = 7) -> CachedSnapshot | None:
        """Returns cached snapshot if exists, fresh, and schema_version matches.
        Returns None otherwise — caller must re-fetch."""
    
    def put(self, asa_id: str, snapshot: ParsedSnapshot) -> None:
        """Store with schema_version, fetched_at, source_url, raw_html_hash."""
    
    def invalidate(self, asa_id: str) -> None:
        """Manual refresh path."""
```

Old v3-cache files (without schema_version) are treated as cache misses — never deserialised, never trusted. This forces a clean re-fetch on first V6 upload.

### Fetcher (`fetcher.py`)

```python
class PBFetcher:
    max_workers: int = 3
    request_delay_sec: float = 0.5
    per_request_timeout_sec: float = 12.0
    total_budget_sec: float = 90.0
    max_retries: int = 2
    circuit_breaker_threshold: int = 5  # consecutive failures before stopping
    
    def fetch_many(
        self,
        asa_ids: list[str],
        cache: PBCache,
        progress_cb: Callable | None = None,
    ) -> dict[str, FetchResult]:
        """Fetch every asa_id with concurrency, respecting budget and circuit breaker.
        Returns dict keyed by asa_id, including failures.
        Cache is consulted FIRST; only misses go to the network."""
```

Concurrency via `concurrent.futures.ThreadPoolExecutor`. Each worker uses its own `urllib.request` session. Polite headers including `User-Agent` identifying the app.

Circuit breaker: if 5 consecutive HTTP errors, abort remaining fetches and mark all unfetched as `fetch_skipped_circuit_open`.

Budget: `total_budget_sec` is wall-clock from start of `fetch_many`; once exceeded, in-flight requests are allowed to finish but no new ones are submitted.

### History builder (`history.py`)

```python
def build_previous_pb(
    *,
    snapshot: ParsedSnapshot,
    swimmer_asa_id: str,
    swimmer_name: str,
    event_distance: int,
    event_stroke: str,
    course: str,
    meet_name: str | None,
    meet_date_iso: str | None,
    venue: str | None,
) -> PreviousPB | None:
    """Build a PreviousPB by:
      1. Filter snapshot entries matching (event_distance, event_stroke, course)
      2. Exclude entries that match the current meet (same_meet_dedup):
         - meet_name match (after canonicalisation)
         - OR meet_date_iso match
         - OR (date within 2 days AND venue match)
      3. Of remaining entries, pick the FASTEST (lowest time_seconds)
         — this is the previous PB
      4. If no entries remain, return None
      5. Tag entries that were excluded with reasons in PreviousPB.excluded_swims
    """
```

### Matcher (`matcher.py`)

```python
def decide_pb(
    *,
    swim_id: str,
    swimmer_asa_id: str | None,
    swimmer_name: str,
    event_distance: int,
    event_stroke: str,
    course: str,
    current_time_seconds: float,
    current_time_display: str,
    identity: IdentityMatch,
    snapshot: ParsedSnapshot | None,
    meet_name: str | None,
    meet_date_iso: str | None,
    venue: str | None,
) -> PBDecision:
    """The single comparator. Returns PBDecision with full audit trail."""
```

Decision tree:
- `identity.safe_to_use is False` → `SUPPRESSED_NEEDS_VERIFICATION`
- `snapshot is None or not fetch_ok` → `PB_UNVERIFIED`
- `previous_pb is None` (no historical data for event) → `PB_UNVERIFIED`
- `current_time < previous_pb.time_seconds` → `CONFIRMED_PB` with delta
- `current_time == previous_pb.time_seconds` (within 0.005s) → `CONFIRMED_PB` (matched PB)
- `current_time > previous_pb.time_seconds` → `NOT_PB` with delta
- Edge case: snapshot's listed PB is from this meet but we excluded it → `LIKELY_PB` with note

Each decision records its full audit trail: every step considered, every entry excluded, every threshold tested.

### Corrections (`corrections.py`)

Per-meet store, simple JSON file at `runs_v4/<run_id>__corrections.json`:

```python
class CorrectionsStore:
    def get_override(self, run_id: str, hy3_swimmer_key: str) -> dict | None:
        """Look up override for a HY3 swimmer in this run.
        hy3_swimmer_key = original_asa_id or 'name:LASTNAME, FIRSTNAME'."""
    
    def set_override_asa_id(self, run_id: str, hy3_swimmer_key: str, new_asa_id: str, note: str) -> None:
        """User says: this swimmer's correct ASA number for this meet is X."""
    
    def set_ignore_pb(self, run_id: str, hy3_swimmer_key: str, reason: str) -> None:
        """User says: don't run PB detection for this swimmer in this meet."""
    
    def all_for_run(self, run_id: str) -> list[dict]:
        """For UI display."""
```

NO automatic merging across runs. A separate `save_to_persistent_mappings()` will exist as a stub for future work but the UI won't expose it yet.

### Ground-truth harness (`ground_truth.py`)

```python
@dataclass
class GroundTruthEntry:
    swimmer_name: str
    event_label: str           # "100 Freestyle LC"
    result_time: str
    expected_pb: bool          # "yes" | "no" | "unknown"
    expected_prev_pb: str | None
    expected_barrier_crossed: bool | None
    notes: str | None


def run_ground_truth(
    *,
    run_id: str,
    truth_csv_path: Path,
) -> GroundTruthReport:
    """Load CSV, find each entry in the run's PB decisions, compare,
    output:
      - true_positives, false_positives, false_negatives
      - precision, recall
      - per-detector breakdown
      - ambiguous cases
      - skipped (no match in run)"""
```

### Pipeline integration

In `pipeline_v4.py`, replace lines ~190-220 (the PB enrichment block) with:

```python
from swim_content_pb import run_pb_subsystem

if fetch_pbs:
    pb_audit = run_pb_subsystem(
        run_id=run_id,
        meet=meet,
        our_swimmers=our_v3_swims,
        use_cache=use_pb_cache,
        progress_cb=step,
    )
    run.pb_audit = pb_audit
    run.pb_snapshots = pb_audit.snapshots_by_asa_id  # for v3 trust shim compatibility
else:
    run.pb_audit = None
    run.pb_snapshots = {}
```

`run_pb_subsystem` handles: identity matching, fetching, parsing, history building, decision making, audit logging. Returns `RunPBAudit` for the UI plus a snapshots dict for the legacy v3 trust path (so existing code still works).

### V5 detector wiring

In `swim_content_v5/achievements/pb.py` (and `barrier.py`, `standout_history.py`, `return_to_form.py`), accept a new optional `pb_audit: RunPBAudit | None` parameter. When present, use `pb_audit.find_decision(swim_id)` to get the rich `PBDecision` instead of the v3 trust object. This unlocks:

- `PBConfirmedDetector` fires when `decision.status == "CONFIRMED_PB"` AND `decision.safe_to_post`
- `PBLikelyDetector` fires when `status == "LIKELY_PB"`
- `FirstSubBarrierDetector` (strict) uses `decision.previous_pb` to check if the swimmer was previously above the barrier
- `FastestSinceDetector` uses `previous_pb.pb_date_iso`
- `BiggestDropDetector` uses `decision.improvement_percentage`
- `MultiPBWeekendDetector` counts `CONFIRMED_PB` decisions per swimmer
- `ReturnToFormDetector` uses `previous_pb.pb_date_iso` for the gap calculation

Existing detectors keep their fallback paths so the system still works without `pb_audit` (i.e., when `fetch_pbs=False`).

### UI additions to `web.py`

**1. PB Audit panel in `/review/<run_id>`** (after Meet Context, before Top Achievements):

```
┌──────────────────────────────────────────────────┐
│ PB Audit                                          │
├──────────────────────────────────────────────────┤
│ 36 swimmers · 31 verified · 4 needs verification  │
│ 1 fetch failed · 145 PB decisions                │
│ 12 confirmed · 6 likely · 95 not PB              │
│ 28 unverified · 4 suppressed                     │
│ Fetch took 24.3s · Cache hits: 22 · Misses: 14   │
├──────────────────────────────────────────────────┤
│ ⚠ 4 swimmers need verification:                  │
│   [Verify] BRADLEY, MATHEW J  (id 1382076)       │
│             SR returned: "Matthew Bradley"        │
│             ↳ canonical mismatch                  │
│   [Verify] ...                                   │
├──────────────────────────────────────────────────┤
│ [Show all per-swimmer audits ▼]                  │
└──────────────────────────────────────────────────┘
```

**2. New routes:**

- `GET /audit/<run_id>` → full PB audit page (drill-down on every swimmer)
- `GET /audit/<run_id>/verify/<swimmer_key>` → form to enter correct ASA number
- `POST /audit/<run_id>/verify/<swimmer_key>` → save correction, re-run PB stage for this swimmer only
- `POST /audit/<run_id>/ignore/<swimmer_key>` → mark "ignore PBs for this swimmer in this meet"
- `GET /audit/<run_id>/ground-truth` → upload a CSV of expected outcomes
- `POST /audit/<run_id>/ground-truth` → run the harness, show precision/recall

**3. Per-swimmer audit page** shows: identity match details (HY3 name, SR name, canonical comparison), every event fetched with previous PB and decision, all evidence URLs.

**4. Per-decision drill-down** on the recognition page: clicking a PB-related achievement shows the full `PBDecision.audit_trail`.

### Default flag changes

In `web.py` upload form (around line 743), keep `fetch_pbs` checkbox checked by default. Add a new info note:

```
ℹ With PB fetching enabled, your meet results are checked against
  swimmingresults.org for accurate PB and history claims. Adds 30-60s
  for an uncached meet. Cached on subsequent runs.
```

### What must NOT break

1. The Swansea zip with `fetch_pbs=False` must still produce `1665 / 88 / 36 / 45 cards / 261 achievements`.
2. The Swansea zip with `fetch_pbs=True` must:
   - Produce all the V4 cards (now possibly with more `pb_confirmed` claims)
   - Produce a `RunPBAudit` with at least 30 verified swimmers
   - Show the PB Audit panel on `/review/<id>`
   - Not crash if any single swimmer's fetch fails
3. All existing `url_for` endpoint names must continue to resolve.
4. `/health` must return 200 quickly (don't block on PB module imports).
5. Existing `runs_v4/*.json` files must still load on the recognition page (no schema break).

### Test plan (run before reporting done)

```bash
cd /home/user/workspace/swim-content

# 1. Syntax + imports
python3 -c "
import ast, glob
for f in sorted(glob.glob('swim_content_pb/**/*.py', recursive=True)):
    ast.parse(open(f).read())
print('syntax OK')
from swim_content_pb import schema, identity, parser, cache, fetcher, history, matcher, corrections, audit, ground_truth
print('imports OK')
"

# 2. Unit tests
cd /home/user/workspace/swim-content && python3 -m unittest discover -s swim_content_pb/tests -v 2>&1 | tail -30

# 3. Identity test cases
python3 -c "
from swim_content_pb.identity import canonicalise_name
assert canonicalise_name('BRADLEY, MATHEW J') == canonicalise_name('Mathew Bradley'), 'name canonicalisation'
assert canonicalise_name('SMITH, J') != canonicalise_name('John Smith'), 'no fuzzy matching'
print('identity OK')
"

# 4. Pipeline regression with fetch_pbs=False (no network)
python3 -c "
from pathlib import Path
from swim_content_v4.pipeline_v4 import run_pipeline_v4
zip_path = Path('/home/user/workspace/Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip')
run = run_pipeline_v4(file_bytes=zip_path.read_bytes(), filename=zip_path.name, profile_id='swansea-uni', fetch_pbs=False, use_pb_cache=True, run_id='v6_no_pb')
print('cards:', len(run.cards))
print('recognition_error:', getattr(run, 'recognition_error', 'n/a'))
assert len(run.cards) >= 40
assert getattr(run, 'recognition_report', None) is not None
print('regression OK')
"

# 5. Pipeline with fetch_pbs=True (uses real network — should still complete or fail safe)
python3 -c "
import time
from pathlib import Path
from swim_content_v4.pipeline_v4 import run_pipeline_v4
zip_path = Path('/home/user/workspace/Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip')
t0 = time.time()
run = run_pipeline_v4(file_bytes=zip_path.read_bytes(), filename=zip_path.name, profile_id='swansea-uni', fetch_pbs=True, use_pb_cache=True, run_id='v6_with_pb')
elapsed = time.time() - t0
print('elapsed:', round(elapsed, 1), 's')
print('cards:', len(run.cards))
print('pb_audit present:', getattr(run, 'pb_audit', None) is not None)
audit = getattr(run, 'pb_audit', None)
if audit:
    print('verified:', audit.swimmers_matched_verified)
    print('needs_verification:', audit.swimmers_needs_verification)
    print('confirmed PBs:', audit.pb_confirmed_count)
    print('total decisions:', audit.pb_decisions_count)
print('regression with PB OK')
"

# 6. URL hygiene check
grep -nE 'href=\"/[a-z]|action=\"/[a-z]' swim_content_v4/web.py | grep -v '^\s*#' | head
grep -nE 'fetch\(\"/|fetch\x27/' swim_content_v4/web.py | grep -v '^\s*#' | head
```

All steps must pass. If step 5 hits a network error, that's acceptable as long as the pipeline reports `fetch_failed` cleanly and other achievements are still produced.

### Definition of done

1. All test plan steps complete; unit tests pass.
2. With `fetch_pbs=True` on the Swansea zip, PB-related detectors fire (≥1 confirmed PB if any swimmer has a real PB; if Swansea swimmers are mid-season and have no current PBs, the audit shows that explicitly).
3. PB Audit panel renders on `/review/<id>`.
4. Verification UI works: clicking "Verify" on a needs-verification swimmer leads to a form, saving an override re-runs that swimmer's PB stage.
5. No false-positive PB claims (subagent must spot-check 5 swimmers manually against live SR pages).
6. Existing v4 numbers preserved on `fetch_pbs=False` runs.
7. Code is structured so a future PDF/swimmingresults.org HTML adapter can use the same identity matcher.

### Important constraints

- DO NOT modify `swim_content/enrichment_swimmingresults.py` — leave the legacy module alone. The new system imports nothing from it.
- DO NOT change the schema of `runs_v4/*.json` for old runs. Add `pb_audit` as a new optional top-level key. Loaders must default to None.
- DO NOT add new dependencies. Use stdlib only (`urllib`, `concurrent.futures`, `dataclasses`, `json`, `re`, `html.parser`).
- Every HTML href / form action / fetch URL / location.replace MUST use `url_for(...)`. Run the grep at the end.
- Wrap every user-/file-derived string in `_h()` before HTML interpolation.

Build it.
