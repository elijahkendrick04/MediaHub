# V5 Build Specification — Achievement Intelligence Layer

**Goal:** add an intelligent, source-grounded achievement recognition layer to the existing Swim Content app **without breaking the v4 pilot**. Replace the `/review/<id>` page with a new recognition report. Add a "why was this NOT generated?" surface.

**Owner expectations (from user, verbatim summary):**
- Detect: confirmed PBs, likely PBs, biggest improvements, medals, finals, heat→final improvements, records, qualifying times, standout vs field, standout vs swimmer history, age/category context, first-time barriers (sub-60, sub-30, sub-2:00, etc.), return-to-form, fastest-since-date, strong relays, narrative-worthy, nice-but-not-priority, ordinary (no card).
- Rank, don't just detect.
- Each card has: type, priority, confidence, reason, evidence list, safe-to-post, suggested post type, suggested caption angle, uncertainty/missing data.
- Per-swim "why or why not" panel.
- Source-grounded live web research, cached per meet, never hallucinated.
- MeetContext profile per run.
- Quality bands: elite / strong / story / nice / not-worthy.
- Adapter-friendly: future swimmingresults.org / PDF / Lenex / British live can all feed the same canonical pipeline.
- Persistent SECRET_KEY.
- Web-openable, not local.

## Decisions already made by user

1. **Research depth = Deep.** Per-meet research + per-swimmer research for top-N performers (top 8 by ranked priority). Cache aggressively. Fail safe.
2. **UI = Replace `/review/<id>`** with the new recognition view. The route name stays `/review/<id>` for backwards links — but the HTML body becomes the new recognition report. Old card table is folded inside a "Cards" section of the new page. The URL `url_for('review', run_id=...)` still works.
3. **Barriers = Strict.** Only fire "first sub-X" when we have prior PB data showing the swimmer was above the barrier. Otherwise, downgrade to "no prior PB data — can't verify first-time" and don't fire.
4. **Deploy = mediahub.pplx.app** (site_id `e287696a-e61f-4108-bdb1-ee3bdd82d2af`). After build, redeploy via `deploy_website` + `publish_website` with the existing site_id.

## Architecture

New package `swim_content_v5/` lives alongside `swim_content_v4/`. v4 stays untouched except `pipeline_v4.py` (one additive stage) and `web.py` (new routes + recognition page). v3 (`swim_content/`) is **read-only** — do not modify.

### Files to create

```
swim_content_v5/
├── __init__.py              Empty marker, version constant
├── schema.py                New dataclasses: MeetContext, Achievement, AchievementEvidence,
│                              QualityBand enum, PostType enum, RecognitionReport, SwimTrace
├── context_profile.py       build_meet_context(meet) → MeetContext
│                              Extracts venue, course, dates, governing body clues, 
│                              session/finals presence, age groups, host club
├── research.py              ResearchClient with disk cache at .cache/research/<hash>.json
│                              search_meet_context(meet) → dict of source-grounded findings
│                              search_swimmer_context(swimmer, meet) → dict
│                              Uses pplx CLI via subprocess (api_credentials="pplx-sdk")
│                              Falls back gracefully if subprocess unavailable
├── history.py               SwimmerHistory wrapper around existing pb_cache
│                              Provides: best_time_in_event(swimmer, event) → time | None
│                                       times_in_event(swimmer, event) → list[(date, time)]
│                                       last_swam_event(swimmer, event) → date | None
│                                       all_pbs(swimmer) → dict[event, time]
├── achievements/
│   ├── __init__.py          Detector registry. Iterates all detector classes.
│   ├── base.py              class AchievementDetector ABC with .detect(swim, ctx, history) → list[Achievement]
│   │                        class Achievement dataclass
│   ├── pb.py                PBConfirmedDetector, PBLikelyDetector, PBImprovementMagnitudeDetector
│   ├── barrier.py           FirstSubBarrierDetector — STRICT mode per user choice
│   ├── medal_final.py       MedalDetector, FinalAppearanceDetector, HeatToFinalDropDetector
│   ├── qualifier.py         QualifyingTimeDetector — uses existing quals_registry + research
│   ├── standout_field.py    TopOfFieldDetector — top-3/5/10 vs all entrants in event
│   ├── standout_history.py  FastestSinceDetector, BiggestDropDetector, MultiPBWeekendDetector
│   ├── return_to_form.py    ReturnToFormDetector — first event swim after >6 months
│   └── relay.py             RelayMedalDetector, RelayStrongPerformanceDetector
├── ranker.py                rank_achievements(achievements, ctx) → ranked list with priority scores
│                              Multi-factor: magnitude × rarity × meet_level × medal/final × narrative
│                              Each factor returns (value, weight, reason)
├── recommender.py           recommend_post_type(achievements, ctx) → PostType + angle hints
│                              Buckets achievements into QualityBand based on combined evidence
├── explainer.py             build_swim_trace(swim, all_detector_outputs, ranker_decision) → SwimTrace
│                              For every swim, traces every detector that ran, what it returned,
│                              why it fired or didn't, what factors contributed to ranking
├── report.py                build_recognition_report(meet, profile, ctx, swims, achievements,
│                                                       traces, ranker_output) → RecognitionReport
│                              .to_json() for export, .to_dict() for the UI

```

### Files to modify

**`swim_content_v4/pipeline_v4.py`** — add ONE new stage at the end, after `build_trust_report`. Wrap in try/except so v5 failure doesn't break v4 cards. Store result on `PipelineRunV4`:
```python
# After existing v4 work...
try:
    from swim_content_v5.report import build_recognition_report_for_run
    run.recognition_report = build_recognition_report_for_run(run)
except Exception as exc:
    run.recognition_report = None
    run.recognition_error = f"{type(exc).__name__}: {exc}"
    step(f"v5 recognition failed: {exc}")
```

Add `recognition_report: dict | None = None` and `recognition_error: str | None = None` fields to `PipelineRunV4`. Persist them in the run JSON.

**`swim_content_v4/web.py`** — add:
- `/api/runs/<id>/recognition` — JSON endpoint returning the full report
- `/api/runs/<id>/swim/<swim_id>/trace` — JSON for one swim's trace
- `/recognition/<id>` — full HTML page (the new recognition UI)
- **Replace the `review()` view's body** with the new recognition page UI. Keep the route name `review` and same path. Existing `url_for('review', run_id=...)` calls still resolve. Fold the old card table inside the new page as one section.
- Add filters: by achievement type, confidence, swimmer, event, priority, post type
- Add a "Not generated" panel listing swims that did not produce achievements with the trace summary
- Add a "Sources used" panel showing every research source touched
- Add a "Download recognition JSON" button hitting the new API

Keep all existing routes, all existing url_for endpoints, and all existing copy buttons working.

**`swim_content_v4/web.py` SECRET_KEY** — change line ~43 to:
```python
secret = os.environ.get("SECRET_KEY", "")
if not secret:
    # Persistent fallback derived from data dir + machine; better than ephemeral
    persistent_path = Path(os.environ.get("DATA_DIR", ".")) / ".secret_key"
    if persistent_path.exists():
        secret = persistent_path.read_text().strip()
    else:
        secret = os.urandom(32).hex()
        try:
            persistent_path.write_text(secret)
        except OSError:
            pass
app.config["SECRET_KEY"] = secret
```

**`swim_content_v4/canonical.py`** — no changes needed for v5 if all new types live in `swim_content_v5/schema.py`. The canonical.py `Meet`/`RaceResult` types are reused as-is.

## Detector specifications

Every detector implements:
```python
class AchievementDetector(ABC):
    name: str   # stable identifier, e.g. "pb_confirmed"
    @abstractmethod
    def detect(self, swim: RaceResult, ctx: MeetContext, history: SwimmerHistory) -> list[Achievement]:
        ...
    def trace(self, swim, ctx, history) -> dict:
        # returns {"ran": True, "fired": bool, "reason": str, "evidence": [...]}
        # default impl runs detect() and summarises
```

Each `Achievement` carries:
```python
@dataclass
class Achievement:
    type: str                     # e.g. "first_sub_60", "biggest_drop_of_meet"
    swim_id: str
    swimmer_id: str
    swimmer_name: str
    event: str                    # canonical event label
    headline: str                 # short factual statement
    angle_hint: str               # narrative angle suggestion
    confidence: float             # 0.0-1.0
    confidence_label: str         # "high" | "medium" | "low"
    evidence: list[AchievementEvidence]
    raw_facts: dict               # numerical facts: time, prev_pb, drop_seconds, etc.
    uncertainty_notes: list[str]  # explicit gaps (e.g. "no prior PB data")
    detector_name: str
```

`AchievementEvidence`:
```python
@dataclass
class AchievementEvidence:
    source_type: str              # "results_file" | "pb_cache" | "live_research" | "registry"
    source_url: str | None
    source_name: str
    statement: str                # what this evidence proves
    fetched_at: str | None        # ISO timestamp
    confidence: str               # "high" | "medium" | "low"
```

### Detector implementation notes

- **PBConfirmedDetector**: prior PB exists (via pb_cache) and current time is faster. Confidence high.
- **PBLikelyDetector**: no prior PB data, but entry time > final time and final time looks plausible (in event range). Confidence medium. Add uncertainty note.
- **PBImprovementMagnitudeDetector**: separate from "is it a PB?" — measures magnitude vs prior PB. Buckets: tiny (<0.5%), notable (0.5-2%), big (2-5%), huge (>5%). Different priority weights.
- **FirstSubBarrierDetector** (STRICT): for each event, computes the natural barrier (e.g. for 100 Free LC: 60s, 55s, 50s, 48s, 47s; for 50 Free SC: 30s, 28s, 25s, etc.). For each crossed barrier, **only fire if history shows a prior swim above the barrier**. If no history, skip and add an uncertainty trace.
- **MedalDetector**: place 1/2/3 in event. Read from canonical RaceResult.place. Includes para/junior splits if present.
- **FinalAppearanceDetector**: detects swims labelled as finals (heat name contains "final", "A final", session text). Falls back to "made the final" inferred from multi-round events when adapter provides round info.
- **HeatToFinalDropDetector**: same swimmer + event has a heat time and a final time on the same day. Fires if final < heat by >0.3s.
- **QualifyingTimeDetector**: uses existing `swim_content/quals_registry.py` PLUS any standards harvested by research. Reports level (e.g. "BUCS LC 2026-27 A").
- **TopOfFieldDetector**: top 3/5/10 finishers in their event across the whole meet (not just the club). Useful at large meets.
- **FastestSinceDetector**: from pb_cache history, current time is fastest in event since date X. "Fastest since 2024" framing.
- **BiggestDropDetector**: meet-level — the single swim with the largest improvement over prior PB across all club swimmers. Only one fires per meet.
- **MultiPBWeekendDetector**: per swimmer, count confirmed PBs across the meet. Fires if >=3.
- **ReturnToFormDetector**: per swimmer + event, the last recorded swim was >6 months ago and current time is within 2% of historic best.
- **RelayDetector(s)**: medal placements + sub-event-level strong legs (if relay split data is available).

## Ranker specification

```python
def rank_achievements(achievements, ctx, history) -> list[RankedAchievement]:
    # For each achievement, compute priority = sum of weighted factors:
    # - magnitude_factor (improvement size, time barrier, vs field)
    # - rarity_factor (medal at high-level meet > medal at club gala)
    # - meet_level_factor (from MeetContext)
    # - narrative_factor (multiple PBs, return to form, biggest drop)
    # - barrier_factor (sub-X barriers add bonus)
    # - certainty_factor (low confidence reduces priority)
    # Each factor returns (value, weight, reason)
    # Final priority = weighted sum / max possible
```

`RankedAchievement` carries:
```python
@dataclass
class RankedAchievement:
    achievement: Achievement
    priority: float                # 0.0-1.0
    factors: list[RankFactor]      # each with name, value, weight, reason
    quality_band: QualityBand      # ELITE | STRONG | STORY | NICE | NOT_WORTHY
    suggested_post_type: PostType  # MAIN_FEED | STORY | RECAP | INTERNAL_NOTE
    rank: int                      # 1, 2, 3... within the run
```

## Recommendation specification

The recommender groups achievements per swimmer and decides:
- A swimmer with one elite + several strong → main-feed athlete spotlight
- A swimmer with one strong → story or recap mention
- A swimmer with only nice-band → recap roll-up only
- Meet-level standouts (biggest drop, top-of-field) → headline meet recap
- Quality bands map to post types but recommender can override (e.g. multiple strongs > one elite for narrative).

Output: list of `ContentRecommendation` objects with title, swimmer/group, included achievements, suggested post type, angle hint.

## Research client specification

`ResearchClient` lives in `swim_content_v5/research.py`. Uses `pplx` CLI via subprocess (the `pplx-sdk` credential preset is available in the deployed sandbox; if not, every method must fail-safe and return empty results).

```python
class ResearchClient:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _cached_or_fetch(self, key: str, fetch_fn) -> dict:
        cache_path = self.cache_dir / f"{key}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        try:
            result = fetch_fn()
            cache_path.write_text(json.dumps(result))
            return result
        except Exception as e:
            return {"error": str(e), "ok": False}
    
    def search_meet_context(self, meet: Meet) -> dict:
        # Query: meet name + venue + year
        # Returns: {meet_level, has_finals, has_age_groups, governing_body,
        #           qualifying_standards_url, sources: [...]}
    
    def search_swimmer_context(self, swimmer_name, club, asa_id) -> dict:
        # Returns: {recent_meets, ranking_context, sources: [...]}
        # Only called for top-N swimmers AFTER initial ranking
```

**CRITICAL: published sandbox restrictions.** The `api_credentials=["pplx-sdk"]` mechanism IS available at build/test time but `call_external_tool` is NOT available in published sites. Therefore the research client must call `pplx` via subprocess, where the sandbox's environment variables provide the credential. If `subprocess.run(["pplx", "search", "web", ...])` fails (CalledProcessError, FileNotFoundError, timeout), the client returns `{"ok": False, "error": ..., "sources": []}` and the pipeline continues without research data.

**Execution budget:** total research time per upload ≤ 60 seconds. If research is taking too long, the pipeline kills it and proceeds with what it has.

## UI specification

Replace `/review/<id>` body. Sections, in order:

1. **Header** — Meet name, dates, course, venue, profile, link to JSON export, link to old `/runs/<id>` progress page.
2. **Recognition summary band** — 6 stat blocks: Elite, Strong, Story, Total achievements, Swims analysed, Cards generated.
3. **Meet context card** — Shows MeetContext fields: meet level, governing body, has_finals, age_groups, with confidence indicators on each. Sources panel listing all research URLs.
4. **Top achievements panel** — top 10 ranked by priority. Each row: swimmer, event, achievement type, headline, priority bar, confidence pill, quality band tag, expandable factors+evidence.
5. **All cards (legacy)** — the existing v4 card table, kept for compatibility. Collapsible.
6. **Not generated panel** — swims that ran through detectors but emitted no achievements. Each row: swimmer, event, time, summary of why (e.g. "no PB data, no medal, ordinary time").
7. **Filters bar** — sticky. Filter by: achievement type, confidence, swimmer, event, post type, quality band.
8. **Sources used** — global list of all research URLs touched, with timestamps and what they were used for.

Add JS to filter the achievement list client-side. No SPA framework — vanilla JS with `dataset` attributes and querySelectorAll.

For each achievement row, clicking expands to show:
- All factors with name, value, weight, reason
- Evidence list with source links
- "View full trace" link → `/api/runs/<id>/swim/<swim_id>/trace` (opens JSON)

## Test plan

After build, run these in order:

1. **Syntax check:** `python3 -c "import ast; [ast.parse(open(f).read()) for f in __import__('glob').glob('swim_content_v5/**/*.py', recursive=True)]"`
2. **Import check:** `python3 -c "from swim_content_v5 import schema, context_profile, research, history, ranker, recommender, explainer, report"`
3. **Detector dry run:** programmatically load the existing run JSON (`runs_v4/c4c10260645c.json` or `ff1dd5cf095c.json`), feed swims through each detector, print achievement counts per detector. Should be non-zero for at least PBLikely, Medal, Qualifier, TopOfField.
4. **Pipeline regression:** run `pipeline_v4` on the Swansea zip end-to-end via `app.test_client()`. Assert: still 1665 total swims, 88 our_swims, 36 swimmers, ≥40 cards, recognition_report present and non-empty, recognition_error is None.
5. **Web smoke:** `c.get('/review/<id>')` returns 200 with the new recognition UI, contains "Recognition" header, contains achievement listings.
6. **Browser walkthrough:** Playwright opens the live site, navigates to /review of the existing run, screenshots above-the-fold and a scrolled view, expands one achievement row, clicks "Not generated" panel.

## Don't break

- Existing `/api/runs/<id>/cards`, `/api/runs/<id>/trust`, `/api/runs/<id>/export` payload formats — leave alone.
- Existing `url_for` endpoint names: `home`, `upload`, `run_status`, `review`, `api_status`, `api_cards`, `api_trust`, `api_export`, `ground_truth`, `profiles_page`, `research_page`, `privacy_page`, `privacy_delete_run`, `privacy_clear_cache`, `health`, `healthz`. Add new ones without renaming any.
- The `/port/5000` URL prefix middleware. Every new HTML href / fetch / location.replace / form action MUST use `url_for(...)`.
- The `_h()` escaping discipline — wrap every user/file-derived string in HTML output.
- The S3 redirect `dist/public/index.html` — leave alone.

## Definition of done

1. All test plan steps pass.
2. The site at https://mediahub.pplx.app/review/<existing_run_id> shows the new recognition view, with no console errors and no 4xx/5xx.
3. The Swansea zip uploaded fresh through the UI still produces the canonical 1665/88/36 numbers.
4. Recognition report contains achievements from at least 5 distinct detectors.
5. Persistent SECRET_KEY is in place.
6. v5 code is structured so adding a new adapter (PDF, Lenex, swimmingresults.org) requires zero changes inside `swim_content_v5/` — only a new module under `swim_content_v4/adapters/`.
7. v5 code is structured so adding a new detector requires only one new file in `swim_content_v5/achievements/` registered in `__init__.py`.
8. The "why was this not generated?" panel shows real, useful explanations.
9. Sources panel shows live research URLs (or a clear "research unavailable" notice if `pplx` subprocess fails in the sandbox).

Build it.
