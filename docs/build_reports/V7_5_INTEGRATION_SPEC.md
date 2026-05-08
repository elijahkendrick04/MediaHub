# V7.5 — Integration Spec

## Goal
Wire V7.5 modules (interpreter/, context_engine/, pb_discovery/, voice/learned/) into the live pipeline that the web UI uses. Strip hardcoded `swimmingresults.org` references. Add universal club picker. Make sure existing meets (Manchester, Swansea) still work.

## Reference files
- Audit: `/home/user/workspace/swim-content/V7_5_HARDCODE_AUDIT.md` — section 1 lists every hardcoded SR reference to fix
- Build reports: INTERPRETER_BUILD_REPORT.md, CONTEXT_ENGINE_BUILD_REPORT.md, VOICES_BUILD_REPORT.md

## Phase A — Pipeline integration

### 1. Replace adapter dispatch
File: `swim_content_v4/pipeline_v4.py`

Today it reads bytes via `swim_content_v4/adapters/dispatcher.py` which dispatches between `hy3.py` and `engine_v4/adapters/sportsystems_pdf.py`.

Replace with:
```python
from interpreter import interpret_document
interpreted = interpret_document(file_bytes, hint=None)
```

Then convert `InterpretedMeet` → the existing canonical `SwimMeet` shape that the rest of the pipeline (recognition, ranker, content pack) expects. Create a new module `swim_content_v4/interpreter_bridge.py` that does this conversion, including:
- Mapping InterpretedSwim → canonical Result
- Mapping InterpretedEvent → event metadata on each Result
- Producing a SwimMeet with name/venue/dates from InterpretedMeet
- Preserving `host_club_code` as None unless the interpreter found it

Keep the old adapters/ directory in place for now but unused — clean removal happens in Phase D. The pipeline must import only the interpreter going forward.

### 2. Replace `swim_content_pb` with pb_discovery
File: `swim_content_v4/pipeline_v4.py` — find the PB-fetch block (search for `swim_content_pb` or `IdentityMatcher` or `pb_fetch`).

Replace the SR-specific fetch with:
```python
from pb_discovery import discover_swimmer_pbs
for swimmer in our_roster:
    pb = discover_swimmer_pbs(name=swimmer.name, club=club_name, run_id=run_id)
    # pb.pbs is list[PBRow]
```

PB results need to be shaped into the existing `pb_snapshots` format that `swim_content_v5/report.py` consumes. Create `swim_content_v4/pb_bridge.py`:
- `pb_discovery.PBRow` → existing PB snapshot shape
- Carry through source URLs and trust scores

### 3. Replace `context_profile.build_meet_context` research call
File: `swim_content_v5/report.py`

V7.4 already wired DDG search via `web_research.search.WebResearcher`. Replace that block to use `context_engine.identity.discover_meet_identity()` instead, which gives richer output (governing body, level, host club).

Pass discovered facts into `build_meet_context(meet, research_data=...)`.

### 4. Voices integration
File: `swim_content_v4/web.py` — find the V7.4 multi-tone renderer. The existing renderer hardcoded three tones; replace with:
```python
from voice.learned.store import list_voices, load_voice_from_path
from voice.learned.render import render_caption
voices = list_voices()  # reads data/voices/ + data/voices/seed/
```

For each achievement card, render one caption per loaded voice. Tone tabs come from `voices`, not constants.

Update the caption renderer that the pipeline pre-computes. Find `voice/multi_tone_renderer.py` (V7.4) and either:
- Replace its internals to call `voice.learned.render.render_caption`, OR
- Delete it and call render_caption directly from web.py

Whichever is cleaner. Keep behaviour: each card has all voices pre-rendered; clicking a tab swaps panels.

## Phase B — Universal club picker

### 5. Upload page changes
File: `swim_content_v4/web.py` — the upload form currently has a profile dropdown with `coma` and `swansea-uni` plus "Auto-detect". Add a new field after upload:

After parsing the file, the recognition page has `our_swim_count` based on a single profile's club codes. Change this so:
- After interpretation, the engine extracts ALL club names appearing in the file (from the interpreted swims)
- Plus reads any clubs from `data/discovered/clubs/*.json` (any club ever seen by the engine)
- Plus a freeform "type a club name" search box
- The user picks ONE club from the union; recognition is filtered to that club's swimmers

Implement this as:
1. Two-step upload: upload → light parse + show club picker → pick → run full recognition for that club. OR
2. One-step: upload + select club → if "auto" or unlisted, parse and show picker before recognition runs.

Pick whichever flows better; the second is cleaner for users who already know which club they want.

Backend:
- `_start_run` takes a `club_filter` parameter (a club name string, not a profile_id slug)
- The pipeline filters results to that club
- "Profiles" (slugs) become a convenience: a saved bundle of (club_filter + voice + brand_kit). User can save the current setup as a profile after a run.

The `coma` and `swansea-uni` profiles continue to work but are now profiles in the new sense — bundles, not the source of truth for what counts as "us".

### 6. Club discovery storage
Every club name observed during interpretation gets recorded to `data/discovered/clubs/<slug>.json` with: `{name, slugs_seen, meets_seen_in: [run_ids], first_seen, last_seen}`. The picker dropdown populates from this file plus the current upload's clubs.

## Phase C — Strip hardcoded SR references

For each file in V7_5_HARDCODE_AUDIT.md section 1, replace:
- `"swimmingresults.org"` → use the actual `chosen_source.domain` from `pb_discovery.PBDiscovery`
- `SR_BASE = "https://www.swimmingresults.org"` → delete
- UI copy mentioning swimmingresults.org → reword to describe capability ("personal-best lookup") without naming source

Specific fixes:
- `swim_content_v4/web.py:883, 886, 894, 1934, 2572, 2610, 2613` — UI copy
- `swim_content_v5/achievements/{pb,barrier,standout_history,return_to_form}.py` — `source_name="swimmingresults.org"` → use the actual source from the PB discovery
- `swim_content_v4/canonical.py:41`, `trust.py:53,82` — comments + example URLs
- `recognition_swim/achievements/official_pb.py` — multiple instances; use the source from PB discovery
- `club_platform/content_types.py:89` — UI string

The `swim_content/` and `swim_content_pb/` legacy packages — leave in place but mark them dead. The pipeline must not import from them after this integration.

## Phase D — Verification

### 7. Add no-hardcode test that covers the WHOLE codebase (excluding legacy)
`tests_v75/test_no_hardcode_in_live_paths.py`:
- Grep these directories: `interpreter/`, `context_engine/`, `pb_discovery/`, `voice/learned/`, `swim_content_v4/`, `swim_content_v5/`, `recognition/`, `recognition_swim/`, `engine_v4/`, `voice/`, `web_research/`, `content_pack/`, `brand/`, `workflow/`, `club_platform/`, `canonical/`, `history/`
- Forbidden literals: `swimmingresults.org`, `swimcloud.com`, `british-swimming.org`, `sportsystems.uk.com`, `SR_BASE`
- Excluded files: anything under `swim_content/` (legacy), `swim_content_pb/` (legacy), tests (`tests/`, `tests_v4/`, `tests_v75/`), build reports (*.md), documentation (*.md), example URLs in docstrings
- Assert zero matches.

### 8. Smoke test the integrated pipeline
`tests_v75/test_pipeline_integration.py`:
- Use `sample_data/MISM-2024-Results.pdf` (Manchester)
- Run pipeline_v4 with `club_filter="City of Manchester Aquatics"`
- Assert: recognition_report has >0 achievements, meet_context.governing_body is set, voices rendered for at least 3 cards

Run pytest -x and ensure it passes.

## Deliverable
- All Phase A/B/C changes applied
- `tests_v75/test_no_hardcode_in_live_paths.py` and `tests_v75/test_pipeline_integration.py` passing
- A short `V7_5_INTEGRATION_REPORT.md` describing what changed and any items deferred

## Anti-shortcut rules
- Do NOT bypass the interpreter by calling old adapters as a fallback. If the interpreter struggles on a real file, that's a signal to improve the interpreter, not to fall back.
- Do NOT hardcode any source domain in the new code paths. Trust ledger preferences are LEARNED.
- Do NOT mock around failing tests. If integration tests fail, fix root cause.
