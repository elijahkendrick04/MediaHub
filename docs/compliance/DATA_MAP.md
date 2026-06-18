# Data Map — where personal data lives and flows

> Engineering evidence document (Phase 1 of the compliance programme).
> Grounded in the code as of 2026-06-12 — every claim names the module/route.
> Feeds [`ROPA.md`](ROPA.md), [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) and the
> erasure/retention capabilities. Update this file whenever a store, payload,
> or third-party call changes.

**Personal data categories handled:** athlete full name, year of birth /
age / age group, sex category (from event), club, race times/placements,
ASA (Swim England) IDs, photos of athletes (largely under-18), PB history,
generated captions naming athletes, club-user account emails.

## 1. Entry points

| # | Entry | Route / module | Data |
|---|---|---|---|
| E1 | Results upload (HY3/SDIF/PDF/HTML/ZIP) | `POST /upload` → `web.py` (`upload_post`, ~line 9023); parsing in `interpreter/` | Names, age (AaD), sex category, club, events, times, splits, placements — for **every athlete in the file, including other clubs' athletes** |
| E2 | Results from a link | `results_fetch/` 3-tier crawl → same pipeline | Same as E1 |
| E3 | Media upload | media library routes → `media_library/store.py` | Photos of athletes (children), `linked_athlete_names`, uploader identity |
| E4 | PB enrichment (collection from a third party, **not** the data subject) | `pb_discovery.fetch_profile` → swimmingresults.org | Athlete name + club sent as search query; PB history (event, course, time, date) received |
| E5 | Club profile setup | `/organisation*` routes → `web/club_profile.py` | Roster ASA IDs, "important swimmers" list, club branding |
| E6 | Account signup/login | `/signup`, `/login` → `web/auth.py` | Club-user email + password (bcrypt-hashed) |

## 2. Stores (everything under `DATA_DIR`; resolution at `web/web.py:808-810`)

| # | Store | Path | Writer | Personal data | Tenant scoping | Erasable today? |
|---|---|---|---|---|---|---|
| S1 | Raw uploads | `uploads_v4/<run_id>/<filename>` | `upload_post` | Full results file (all athletes) | per-run `profile_id` | With run delete |
| S2 | Run state (single source of truth) | `runs_v4/<run_id>.json` + `data.db` `runs` table | `_persist_run` (`web.py:1529`) | Parsed athletes, achievements, captions (names embedded), ages | `profile_id` column/field | `POST /privacy/run/<id>/delete` → `_delete_run` (`web.py:1831`) cascades to S1–S5 |
| S3 | Rendered outputs | `runs_v4/<run_id>/visuals/`, `runs_v4/<run_id>/motion_cache/`, `turn_into_packs/<run_id>/` | renderers | Card PNGs/MP4s with **names and photos of minors**; explainability manifests | via run | With run delete |
| S4 | Workflow / approval state | `runs_v4/<run_id>__workflow.json` | `workflow/store.py` | Card approval decisions (QUEUE → APPROVED → POSTED) | via run | With run delete |
| S5 | In-memory run cache | process memory | `web.py` | Run state | — | Evicted on delete |
| S6 | PB cache (per-run) | `data/discovered/pbs/<run_id>/<swimmer_key>.json` | `pb_discovery/cache.py:41` | PB history keyed by md5(name\|club) (`make_swimmer_key`, `cache.py:35`) | per-run | `POST /privacy/cache/clear` (`web.py:12579`) clears lookup caches; per-run files **not** covered by run delete — **gap** |
| S7 | PB warm cache | `data/discovered/swimmers/<swimmer_key>.json` (7-day TTL) | same | Same | **NOT tenant-scoped** — shared across tenants; undermines the processor framing (LEGAL_FRAMEWORK §5) — **gap** | `/privacy/cache/clear` |
| S8 | Search/trust cache | `data/discovered/search_cache/<hash>.json` | `context_engine.trust` | **Raw HTML of fetched profile pages** (names, full PB history) | not scoped — **gap** | `/privacy/cache/clear` |
| S9 | Media library | `data.db` `media_assets` table + file blobs | `media_library/store.py:37-72` | Photos, `linked_athlete_names`, `permission_status` (`unknown\|user_owned\|needs_parental_consent\|approved_by_club\|approved_public\|do_not_use`), `safe_for_minors`, `uploaded_by` | `profile_id` | `POST /api/media-library/<id>/delete` |
| S10 | Club profiles | `club_profiles/<org_id>.json` | `club_profile.py:430` (`save_profile`) | Roster ASA IDs, important-swimmer IDs, voice examples (may quote captions naming athletes), per-club tokens | per-org file | Admin edit; no full-profile delete route |
| S11 | Users ledger | `users.jsonl` (chmod 0600, append-only) | `web/auth.py:191` | Email, bcrypt hash, plan, Stripe customer ID | global | **No delete route** — append-only; account erasure unimplemented — **gap** |
| S12 | Semantic caption memory | `memory.db` (sqlite-vec) | `memory/store.py:127` (`upsert`) | **Captions with athlete names** + embeddings, `card_id`, `run_id` | `tenant_id` column | **Not deleted on run delete** — **gap** |
| S13 | Autonomy audit ledger | `autonomy_audit/<org_id>.jsonl` (immutable, append-only) | `workflow/autonomy.py:93` | Tool args capped at 2000 chars — may embed athlete names from card payloads | per-org | Never (by design — accountability record); contents should be pseudonymised — **gap** |
| S14 | Scheduler state | `data.db` task tables | `workflow/schedule.py` | Task params (JSON) — must not carry athlete data | per-org | No purge |
| S15 | Session secret | `DATA_DIR/.secret_key` (0600) | `web.py:7877` | — (key material) | — | n/a |
| S16 | Observability | `data.db` uptime/LLM-usage tables | `observability/` | Aggregate counts only | — | n/a |

## 3. Logs

- App logging goes to **stdout/stderr only**; no log files under `DATA_DIR`.
- Verified practice: log lines carry `run_id` tokens, not athlete names or
  meet names (e.g. `web.py:922,984-999,1611`). No Flask access log.
- Residual: hosting provider (Render) captures stdout and request logs
  (IPs, paths) on its side — covered in SUBPROCESSORS (hosting) and the
  retention capability must document the host-side log window.
- Phase 3 adds a structured security-event log with **pseudonymised**
  identifiers (`security/logging-monitoring`).

## 4. Outbound flows (third-party calls)

| # | Flow | Module | Payload today | Minimisation target (Phase 2) |
|---|---|---|---|---|
| F1 | Caption generation → Gemini/Anthropic | `web/ai_caption.py:362-538` (`generate_caption_for_tone`) builds system+user prompt; user prose from `narrate_achievement(...)` | **Athlete full name, age/age group, club, event, time, placement, ASA ID where present**; club brand context; few-shot past captions (more names) | Strip ASA IDs and DOB-adjacent fields; honour per-tenant child-policy (initialise surname / suppress age) **before** payload leaves; never send raw upload text |
| F2 | Creative brief / media tagging / operating profile → LLM | `creative_brief/generator.py`, `brand/derived.py`, media description path | Brief prose; image descriptions; brand docs | Same boundary rules |
| F3 | Photo cutout → Photoroom | `media_ai/providers/photoroom_provider.py:64` | **Full photo bytes** (children) to `sdk.photoroom.com/v1/segment` | Only when tenant enables cloud cutout; consent-checked assets only |
| F4 | Photo cutout → Replicate | `media_ai/providers/replicate_provider.py:63` | Full photo bytes to model `851-labs/background-remover` | Same; default remains in-process rembg (`rembg_local.py`) |
| F5 | PB lookup → swimmingresults.org | `pb_discovery/fetch_profile.py` | HTTP GET with **athlete name + club** as search params | Per-tenant opt-in; rate-limited; cache-first (exists) |
| F6 | Notifications → ntfy/webhook | `notify/channels.py` | Operational messages | Must carry **no athlete personal data** (enforce + test) |
| F7 | Web research → SearXNG/DuckDuckGo | `web_research/` | Search queries | No minor names in queries (enforce + test) |

## 5. The approval / export path and its gates (as implemented)

1. Human flow: upload → pipeline → `/review/<run_id>` → per-card approval
   (S4) → export / download. Approval is the default for everything, and it
   is the only path: MediaHub does not publish to social channels — the club
   posts the exported content manually.
2. **The consent gate**: a card featuring an opted-out or no-consent athlete
   is blocked from approval and from pack rendering, so a refused athlete
   never reaches an exportable pack.

## 6. Real personal data inside the repository itself

Found during this audit (flagged in GAP_ANALYSIS as a dedicated item):

- `samples/MISM-2024-Results.pdf` (29 pages) — **real, named children**
  (ages 13–16, full names, clubs, times) from the ARENA Manchester
  International Meet 2024; symlinked from `sample_data/` and used by ~10
  test files (`test_pipeline_integration.py`, `test_v8_smoke_manchester.py`,
  `test_sportsystems_adapter.py`, …).
- `samples/learning_corpus/level1/*` — real published meet results (City of
  Bristol L1 2025, ND Open 2025, Berkshire County Champs 2026, Sheffield
  Winter L1 2026) as PDF/HTM/ZIP, again naming real children.
- These are publicly published competition documents, but they are still
  real children's personal data held in version control. Source documents
  are public; the *repo copy* needs a documented justification (testing
  necessity), access control (private repo), and ideally progressive
  replacement with synthetic fixtures. **Decision logged for the operator —
  not silently deleted because the parser test suite depends on them.**
- Git history secret scan (gitleaks v8.21.2, full history, 152 commits):
  **no real secrets**; 9 findings are one false positive
  (`swimmer_key="jane-smith-001"` in `tests/test_official_pb_detector.py`).

## 7. Known erasure blind spots (drives `compliance/data-subject-rights`)

An "erase athlete X" operation must touch: S1 (raw uploads contain X among
others — redact-or-delete policy needed), S2 (parsed records + captions),
S3 (rendered cards), S4 (approval state for X's cards), S6/S7/S8 (PB caches
keyed by md5(name|club) and raw HTML), S9 (`linked_athlete_names` + photos),
S10 (roster/important-swimmer IDs, voice examples), S12 (caption memory),
S13 (pseudonymise rather than delete — accountability record).
Today only S2→S5 cascade exists (run-level, not athlete-level), plus a
global cache clear and per-asset media delete. Content the club has already
exported and posted to social manually is **outside the platform's reach**
and the tooling must say so honestly.
