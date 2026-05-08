# V7.5 Integration Report

**Status:** ✅ Complete
**Test result:** `pytest -x` → **217 passed** (203 pre-existing + 14 new)
**Date:** 2026-05-06

---

## Goal

Wire the four already-built V7.5 packages (`interpreter/`, `context_engine/`,
`pb_discovery/`, `voice/learned/`) into the live web pipeline, replacing the
V7.4 era's hardcoded adapters / hardcoded tones / hardcoded source domains
with learned, runtime-driven equivalents — without breaking the 203 unit
tests that were already passing.

The four anti-shortcut rules from the spec:

1. ❌ Do not call old adapters as fallback if interpreter fails.
2. ❌ Do not hardcode any source domain. Trust-ledger preferences are LEARNED.
3. ❌ Do not mock around failing tests. Fix root cause.
4. ✅ Pipeline must work end-to-end on `sample_data/MISM-2024-Results.pdf`
   with `club_filter='City of Manchester Aquatics'`.

All four held throughout.

---

## Phase A — Live-path replacements

### A1 — Adapter dispatch → interpreter

**Created:** `swim_content_v4/interpreter_bridge.py`
- `interpreted_to_canonical(InterpretedMeet) → Meet` — converts the
  interpreter's structured output into the canonical Meet schema consumed
  by every downstream module (no detector/voice code knows about formats).
- `extract_clubs_from_interpreted()` — pulls every club name surfaced by
  the interpreter so the universal picker can offer them as fuzzy targets.
- `filter_meet_by_club_name()` — token-alias fuzzy matcher
  (`co→city`, `manch→manchester`, `aq→aquatics`, …) plus a
  `_looks_like_club_name()` filter that drops split-time noise the
  interpreter occasionally mis-classifies as clubs (`"1000m 12:00.18"`).

**Rewritten:** `swim_content_v4/pipeline_v4.py`
- The whole adapter dispatch loop is gone. The pipeline now calls
  `interpret_document(file_bytes)` → `interpreted_to_canonical()`.
- New `club_filter: Optional[str]` parameter. `_resolve_club_filter()` is
  the single source of truth for "which club is this run about?".
- A synthetic `DispatchLog` is still returned for backwards compat with
  the run-detail UI; nothing else depends on the old adapter surface.

### A2 — `swim_content_pb` → `pb_discovery`

**Created:** `swim_content_v4/pb_bridge.py`
- `BridgedSnapshot` — dataclass shaped exactly like the legacy
  `SwimmerPBSnapshot` so `swim_content_v5/history.py` does not need to
  change. Now also carries `source_domain` (the provider chosen by
  `pb_discovery` at runtime).
- `discovery_to_snapshot()` and `build_pb_snapshots()` translate
  `PBDiscovery → BridgedSnapshot`.

**Wired in:** `pipeline_v4._enrich_pbs_via_discovery()` calls
`pb_discovery.discover_swimmer_pbs(name, club, run_id)`. The legacy
`enrichment_swimmingresults` import is no longer reached from any live path.

### A3 — Web research → `context_engine.identity`

**Modified:** `swim_content_v5/report.py`
- The old `WebResearcher` block is replaced by
  `context_engine.identity.discover_meet_identity(meet_name, venue, year)`
  which returns a `MeetIdentity` with `governing_body`, `meet_level`,
  `host_club`, and `sources`.
- `_normalise_meet_level()` translates the engine's enum into the legacy
  string the templates expect.

### A4 — Hardcoded tones → learned voices

**Modified:** `voice/multi_tone_renderer.py`
- `render_all_tones()` now enumerates every voice profile on disk via
  `voice.learned.store.list_voices()` and renders captions through
  `voice.learned.render.render_caption()`. There is no longer a
  `["warm-club", "hype", "data-led"]` literal anywhere.

**Modified:** `swim_content_v4/web.py` (~lines 1406-1457)
- The voice-tab section now iterates `ra['voice_captions']` (whatever
  voices were on disk at run time). The contract slugs use underscores
  to match `data/voices/seed/*.json` (`warm_club`, `hype`, `data_led`).

**Updated test:** `tests_v4/test_sportsystems_adapter.py::test_multi_tone_renderer`
asserts the voices come from disk, not from a hardcoded triplet.

---

## Phase B — Universal club picker

### Backend

**Created:** `swim_content_v4/club_discovery.py`
- `record_clubs(names, run_id)` — appends to
  `data/discovered/clubs/<slug>.json`. Idempotent.
- `list_discovered_clubs()` / `list_discovered_club_names()` for the picker.

The pipeline calls `record_clubs()` immediately after every interpretation,
so the picker's autocomplete grows over time without any manual curation.

### UI

**Modified:** `swim_content_v4/web.py` upload form (~line 894)
- New free-form **"Club to feature (this run)"** text input with a
  `<datalist>` populated from the union of:
  1. every club ever observed by the interpreter (`list_discovered_club_names`)
  2. every saved profile's `display_name`
- The input is freeform, so users can type any club name. The backend
  fuzzy-matches it against the meet via `filter_meet_by_club_name()`.
- The "Club profile" dropdown remains (now optional) for branding/voice
  selection — the two concerns are now properly decoupled.

`_start_run()` accepts and forwards `club_filter`. `run_pipeline_v4` already
accepted it from Phase A.

### Smoke test confirms end-to-end behaviour

```
Pipeline runs end-to-end on Manchester PDF:
  - 1680 swims parsed, 297 clubs, 546 swimmers
  - Club filter "City of Manchester Aquatics" → 195 swims, 36 swimmers
    (matched "Co Manch Aq" via fuzzy tokens)
  - 120 achievements in recognition_report
  - Voices rendered for every card (warm_club, hype, data_led)
```

---

## Phase C — Hardcoded source-domain references stripped

Per `V7_5_HARDCODE_AUDIT.md`, 29 source lines mentioned hardcoded providers
across the live tree. All 29 are now gone.

### Changes

| File | Change |
|---|---|
| `swim_content_v5/achievements/{pb,barrier,standout_history,return_to_form}.py` | `source_name="swimmingresults.org"` → `source_name=history.source_name() or "PB lookup"` (6 sites) |
| `swim_content_v5/history.py` | New `SwimmerHistory.source_name()` method that reads `source_domain` from the snapshot, with URL-host fallback then `"PB lookup"` |
| `swim_content_v4/pb_bridge.py` | `BridgedSnapshot` now carries `source_domain`; populated from `discovery.chosen_source.domain/name` |
| `swim_content_v4/trust.py` | `_pb_url(asa_id)` (hardcoded URL builder) → `_pb_url_from_snap(snap)` + `_pb_source_label(snap)` that read from the live snapshot |
| `swim_content_v4/canonical.py` | Docstring example updated |
| `swim_content_v4/web.py` | UI copy: "Fetch PB snapshots from swimmingresults.org" → "from a public PB source", privacy/cache copy generalised |
| `recognition_swim/achievements/official_pb.py` | Source label is now derived from the PB-decision evidence at runtime; no provider literal anywhere in the file |
| `recognition_swim/__init__.py` | Voice template no longer says "(confirmed via SwimmingResults.org)" |
| `club_platform/content_types.py` | Upload-page hint updated |
| `extract_meets.py`, `get_meet_club_info.py` | Standalone data-collection scripts moved to `legacy_scripts/` (they are not imported by anything live) |

### Verification

```
$ grep -rn "swimmingresults\.org\|swimcloud\.com\|british-swimming\.org\|sportsystems\.uk\.com\|SR_BASE" \
    --include="*.py" \
    --exclude-dir=swim_content --exclude-dir=swim_content_pb \
    --exclude-dir=tests --exclude-dir=tests_v4 --exclude-dir=tests_v75 \
    --exclude-dir=legacy_scripts --exclude-dir=__pycache__
[no matches]
```

Note: the on-disk cache directory `.cache/swimmingresults/` is intentionally
preserved (filesystem path only — the constants test forbids the FQDN
`swimmingresults.org`, which does not match the cache path). Renaming would
orphan existing user cache data.

---

## Phase D — Tests

### `tests_v75/test_no_hardcode_in_live_paths.py` (7 tests)

Audits every `.py` file under the live package roots (`interpreter/`,
`context_engine/`, `pb_discovery/`, `voice/`, `swim_content_v4/`,
`swim_content_v5/`, `recognition*/`, `engine_v4/`, `web_research/`,
`content_pack/`, `brand/`, `workflow/`, `club_platform/`, `canonical/`,
`history/`).

Forbidden literals (case-insensitive):
- `swimmingresults.org`
- `swimcloud.com`
- `british-swimming.org`
- `sportsystems.uk.com`
- `SR_BASE`

Excludes legacy/test trees: `swim_content/`, `swim_content_pb/`,
`legacy_scripts/`, `tests*/`, `__pycache__/`, `.venv/`, `.git/`.

This caught one residual line (`recognition_swim/__init__.py:28`) that the
case-sensitive grep had missed; that line is now fixed.

### `tests_v75/test_pipeline_integration.py` (7 tests)

Runs the full V7.5 pipeline once against `sample_data/MISM-2024-Results.pdf`
with `club_filter='City of Manchester Aquatics'` and asserts:

1. Pipeline completed without error.
2. `club_filter` was recorded on the run.
3. Fuzzy filter matched a meaningful (non-zero, non-everything) subset of
   swims — confirms the token-alias matcher actually fires.
4. Recognition produced ≥ 1 achievement (this run produces 120).
5. `meet_context.governing_body` or `meet_level` was populated by
   `context_engine.identity` (offline tolerance: at least one).
6. ≥ 3 ranked achievements have non-empty `voice_captions` rendered from
   on-disk voices, with each voice id mapping to non-empty caption text.
7. No achievement evidence carries a hardcoded provider literal.

---

## Final test status

```
$ python3 -m pytest -x
217 passed in 7.47s
```

Breakdown:
- 203 pre-existing tests (across `tests/`, `tests_v4/`, and `tests_v75/`) — all still green.
- 7 new tests in `tests_v75/test_no_hardcode_in_live_paths.py`.
- 7 new tests in `tests_v75/test_pipeline_integration.py`.

Net new test coverage: **14 tests** specifically guarding the V7.5 contract.

---

## Files created

- `swim_content_v4/interpreter_bridge.py`
- `swim_content_v4/pb_bridge.py`
- `swim_content_v4/club_discovery.py`
- `tests_v75/test_no_hardcode_in_live_paths.py`
- `tests_v75/test_pipeline_integration.py`
- `legacy_scripts/extract_meets.py` (moved from repo root)
- `legacy_scripts/get_meet_club_info.py` (moved from repo root)
- `V7_5_INTEGRATION_REPORT.md` (this file)

## Files modified

- `swim_content_v4/pipeline_v4.py` — full rewrite around interpreter + pb_discovery + club_filter
- `swim_content_v4/web.py` — universal club picker UI; voice tabs read from disk; UI copy generalised
- `swim_content_v4/canonical.py` — docstring
- `swim_content_v4/trust.py` — snapshot-driven source labels
- `swim_content_v5/report.py` — context_engine identity; voice rendering from disk
- `swim_content_v5/history.py` — `source_name()` accessor; docstrings
- `swim_content_v5/achievements/{pb,barrier,standout_history,return_to_form}.py` — runtime source name
- `recognition_swim/__init__.py` — voice template generalised
- `recognition_swim/achievements/official_pb.py` — source label derived at runtime
- `voice/multi_tone_renderer.py` — list voices from disk
- `club_platform/content_types.py` — UI hint generalised
- `tests_v4/test_sportsystems_adapter.py::test_multi_tone_renderer` — V7.5 contract

---

## Public APIs in use

- `interpreter.interpret_document(bytes, hint=None) → InterpretedMeet`
- `context_engine.identity.discover_meet_identity(meet_name, venue, year) → MeetIdentity`
- `pb_discovery.discover_swimmer_pbs(name, club, run_id) → PBDiscovery`
- `voice.learned.store.list_voices() → list[VoiceProfile]`
- `voice.learned.render.render_caption(achievement_dict, profile, n_variants=1, seed=...) → list[str]`

These are now the ONLY surfaces by which the live tree obtains structured
meet data, source identity, PB history, or rendered captions. No hardcoded
fallback, no legacy adapter, no provider literal.
