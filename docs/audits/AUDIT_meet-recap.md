# Audit — Meet Recap (in Create)

**Feature:** The "Meet Recap" content type, entered from the Create tab.
**Mode:** AUDIT+FIX · **Branch:** `claude/audit-meet-recap-gqedph` (feature-slug `meet-recap`) · **Auditor model:** claude-opus-4-8
**Date:** 2026-07-09

---

## 1. Scope contract

### Definition
"Meet Recap" is the flagship results-file → ranked, source-grounded content flow, surfaced as the first tile on the **Create** tab (`/make`). A customer clicks the **Meet Recap** tile → sees a per-type "how it works" first slide (`/make/meet_recap`) → clicks **Start** → lands on **Upload** (`/upload`) → picks a Hy-Tek `.hy3` (or zip/PDF/SDIF/CSV/xlsx) results file → **configures** which club is theirs (`/upload/configure`) → the engine runs (interpret → filter to our swimmers → optional PB lookup → recognition → ranking → design) with a **customer-facing progress bar** (`/api/runs/<id>/status` via `recap_progress`) → lands on **Review** (`/review/<id>`) with ranked cards, captions and confidence → edits/approves/rejects → exports.

"Working" means: the tile and intro render and route correctly; the upload validates input and rejects junk cleanly; a valid results file produces the correct ranked cards attributed to the right swimmers for the chosen club; progress is honest and monotonic; nothing leaks internal errors/secrets; every control does what it claims; and the whole path is tenant-isolated.

### Routes/endpoints owned or centrally touched
| Method | Path | Endpoint | Role in Meet Recap |
|---|---|---|---|
| GET | `/make` | `make_page` | Create tab; renders the Meet Recap tile |
| GET | `/make/<ct>` (`meet_recap`) | `content_type_intro` | "How it works" first slide |
| GET/POST | `/upload` | `upload` | The Meet Recap entry: file input + light parse |
| GET/POST | `/upload/configure` | `upload_configure` | Pick our club, colours; kicks off the run |
| GET | `/runs/<id>` | `run_status` | Progress page (customer bar + operator log) |
| GET | `/api/runs/<id>/status` | `api_status` | Progress JSON (percent + phase via `recap_progress`) |
| GET | `/review/<id>` | `review` | Ranked cards / captions / confidence (shared) |
| GET | `/api/runs/<id>/export` | `api_export` | Machine-readable JSON export of the run |

### Files owned (blast radius — editable here)
- `src/mediahub/club_platform/content_types.py` — the `MEET_RECAP` registry entry (title, description, input_contract, HowItWorks, primary_route_endpoint).
- `src/mediahub/web/recap_progress.py` — the customer-facing progress mapping (uniquely Meet Recap).
- `src/mediahub/web/content_intro.py` — presentation formats + "how it works" slide renderer.
- Meet-recap-specific handlers inside `src/mediahub/web/web.py` (SHARED monolith — smallest possible edits, recorded under Cross-cutting): `make_page` tile block, `content_type_intro`, `upload`, `upload_configure`, `_render_configure`, `api_status` (recap_progress usage), `run_status`.
- Tests under `tests/` for the above (`test_recap_progress.py`, `test_content_intro.py`, `test_make_page_endpoints.py`, `test_post_types.py`).

### Shared files depended on but NOT freely rewritten
- `src/mediahub/web/web.py` app factory / base layout / auth+org gate — shared with every other feature and every parallel audit. Any edit is the smallest viable change and recorded under "Cross-cutting changes".
- The deterministic engine (`interpreter/`, `recognition*/`, ranker, `pb_discovery/`) — dependencies I exercise and verify but do NOT rewrite (CLAUDE.md deterministic-engine boundary; covered by their own audits).
- Base templates / shared CSS / `club_profile.py`.

### Inputs / outputs / persistence
- **Input:** a results file (`.hy3/.hyv/.sd3/.sdif/.cl2/.zip/.pdf/.htm/.html/.csv/.txt/.xlsx`) + a chosen club + (from the active org) brand colours/logo.
- **Output:** a persisted run (`recognition_report` with ranked achievements, cards, captions, confidence) rendered on `/review/<id>`; JSON export.
- **Persistence:** staged upload under `RUNS_DIR/<temp_id>/{input.bin,upload_meta.json}`; the finished run in the `runs` SQLite table + `RUNS_DIR/<id>.json`; workflow (approve/reject) state in the workflow store.

### Intended happy path (concrete)
Upload `results_hy3.zip` (North District Open 2025, 32 events) → configure club = "City Of Glasgow Swim Team" → run reaches `done` with a non-zero achievement count attributed only to that club's swimmers → progress climbs monotonically 4→100 with friendly phase labels → `/review` renders cards with no leaked errors → export returns the run.

**Interpretation note (ambiguity resolved):** "Meet Recap" overlaps the generic upload/review pipeline that other parallel audits may own. This audit centres the **Meet-Recap-specific surfaces** (tile, intro slide, content-type registry entry, customer progress mapping, upload entry + validation, configure) and treats the deep deterministic engine and the shared review renderer as tested dependencies, not rewrite targets.

---

## 2. Environment
- Python 3.11.15; deps installed from `requirements.txt` (`--ignore-installed PyYAML` to clear a Debian-managed conflict).
- Local `.env` (gitignored): `DATA_DIR` under scratchpad, `SECRET_KEY` dummy, **no** `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` → AI surfaces honest-error (no real spend). `PORT=5055`.
- Offline driving: Flask **test client** with `app.config["TESTING"]=True` (bypasses the org-ready gate, as the suite does), `session["active_profile_id"]` set to a seeded ready `ClubProfile`. PB fetch disabled per-run for deterministic offline runs. Fixture: `samples/learning_corpus/level1/2025_11_nd_open_championships/results_hy3.zip`.
- Live server + Playwright used for UI interaction / states / a11y / render checks (operator sign-in via `/developer` with an `.env`-set `MEDIAHUB_DEV_PASSWORD_HASH`).

### Method note
An 8-dimension multi-agent hunt (Workflow) drove offline reproductions; it hit the account's **weekly subagent rate limit** partway (5 of 8 finders completed; the a11y/perf finders and the verify pass did not). Those five finders' outputs were recovered from the run journal, and **every finding was then re-verified by hand in the main thread**, and the a11y/perf/security dimensions were completed directly. No finding in this report rests on an unverified agent claim.

---

## 3. Test matrix results

| # | Dimension | Result | Evidence |
|---|---|---|---|
| 1 | Functional correctness (happy path) | **PASS** | `harness.py`: upload -> configure -> run `done` (147 achievements) -> `/review` 200, no leaks -> export 200. |
| 2 | Every interactive control | **FAIL -> fixed** | Meet Recap tile -> `/make/meet_recap`; intro Start -> `/upload` (Playwright). **CTRL-1**: the "Re-run a recent meet" card's link 404'd (fixed). |
| 3 | Input validation / edge cases | **PASS (minor)** | `sec_probe.py`: empty/no-file/bad-ext/corrupt-zip/junk all handled, no 500. **VE-1**: reject status was 200 not 4xx (fixed). 50MB `MAX_CONTENT_LENGTH` cap. |
| 4 | UI state handling | **PASS** | Progress page loading/percent/phase/error states all render; `recap_progress` unit-tested; customer error state honest. |
| 5 | Server-side error handling | **FAIL -> fixed** | **UISE-01**: `/review` leaked the raw exception (absolute paths) to customers; progress page already gated it. Fixed to match. |
| 6 | Data integrity | **FAIL -> fixed** | Club filter isolates correctly (253 COG swims). **CDI-1**: recap "Swimmers" undercount (17 vs 33) fixed. **CDI-2**: `club_filter` not persisted -> wrong no-match copy, fixed. |
| 7 | Security (auth / IDOR / XSS / traversal / CSRF) | **PASS** | `sec_probe.py`: cross-tenant `/runs`,`/status`,`/review`,`/export` all 404, no data leak; `<script>`/`{{7*7}}` in club/display_name never rendered raw; `run_id` traversal all 404; CSRF enforced + auto-injected on POSTs; no secret/key values in any response. |
| 8 | Performance | **PASS** | Upload light-parse bounded by 50MB cap; `_find_duplicate_run` is a single `LIMIT 1` query (no full scan); `recap_progress` iterates a bounded log. No N+1 / unbounded work. |
| 9 | a11y / responsive | **PASS (minor)** | Playwright: file input has `<label for>` + wrapping label + `accept`; intro carries `.mh-visually-hidden` description; no mobile horizontal overflow at 390px; no console errors. |
| 10 | Rendered-graphic correctness | **PASS** | Intro "how it works" circuit renders on-brand; recap card stats now internally consistent after CDI-1. |
| 11 | Consistency / copy (British English) | **PASS (minor)** | No American spellings in user copy (only CSS `center`); no TODO/placeholder/debug strings on the surfaces. **CDI-3** (US date format on header) logged. |

---

## 4. Findings

| id | sev | title | status | commit-scope |
|---|---|---|---|---|
| CTRL-1 | P1 | "Re-run a recent meet" card's configure link 404s ("Upload session expired") — the card only ever shows failed runs and their only link is dead | **fixed** | `web.py` (`upload_configure` + `_rebuild_staged_meta`) |
| CDI-1 | P1 | Recap "by the numbers" card undercounts swimmers (counts swimmers-with-an-achievement, e.g. 17, paired against all 253 swims; 33 competed) | **fixed** | `recognition/weekend_in_numbers.py` (cross-cutting) |
| UISE-01 | P2 | `/review` of a failed run leaks the raw pipeline exception (absolute server paths, exception internals) to the customer; the progress page already gates it behind the operator flag | **fixed** | `web.py` (`review`) |
| CDI-2 | P2 | `club_filter` never persisted -> the no-match review always says "no club was selected" even when a club was chosen; the correct "club name written differently" branch was unreachable | **fixed** | `web.py` (`_persist_run`) |
| VE-1 | P3 | `/upload` reject branches (no file / empty file) returned HTTP 200 while wrong-extension returned 400 — inconsistent status semantics | **fixed** | `web.py` (`upload`) |
| CDI-3 | P3 | Meet date rendered verbatim in ambiguous US `MM/DD/YYYY` on the review/recap header (UK-audience product) | **logged** | `web.py` review header + interpreter date carry-through |
| SEC-OBS-1 | P3 | `/api/runs/<id>/status` JSON still carries the raw `error` string to non-operators (not rendered visibly; the page JS gates display). Documented as intended for API clients; left as-is to avoid changing the poller contract | **logged** | `web.py` (`api_status`) |
| OBS-1 | — | Shared footer shows `[COMPANY_NAME] / [REGISTERED_ADDRESS] / [CONTACT_EMAIL]` placeholders in the local instance (operator env unset). Shared layout, out of Meet Recap scope; likely env-driven in production | **out of scope** | shared layout |

Reproductions live under the scratchpad (`sec_probe.py`, `verify_fixes.py`, `harness.py`) and are encoded as the tests in section 6.

---

## 5. Fixes applied

1. **CTRL-1** — `upload_configure` now reconstructs the configure metadata from a persisted run's saved `input.bin` + `resume.json` (new `_rebuild_staged_meta`, mirroring `upload()`'s light club-parse) when the staged `upload_meta.json` is absent, instead of 404ing. The guard now requires only `input.bin`. Makes the "Re-run a recent meet" links functional (re-pick club / re-run without re-uploading).
2. **CDI-1** — `build_weekend_in_numbers` counts distinct swimmers across `swim_traces` (everyone who competed) rather than only those with a ranked achievement, with a fallback to the old achiever-count when a report carries no traces. Deterministic; no AI involved.
3. **UISE-01** — `review()` now gates the raw `run.error` behind `_auth.is_dev_operator()` (operator sees the verbatim reason; customer sees an honest generic message + the existing "common causes"), matching the is_dev gate `run_status()` already applies.
4. **CDI-2** — `_persist_run` persists `run.club_filter`, so the review empty-state distinguishes "no club selected" from "a club matched zero swimmers" and can name the club in the "written differently" branch.
5. **VE-1** — the "No file selected" and "Uploaded file was empty" `/upload` branches now return `400`, consistent with the wrong-extension branch.

Files touched: `src/mediahub/web/web.py`, `src/mediahub/recognition/weekend_in_numbers.py`.

---

## 6. Tests added / extended

- **`tests/test_meet_recap_audit.py`** (new) — integration locks: VE-1 (reject 400s), CTRL-1 (re-configure a persisted run returns 200 with re-parsed clubs), CDI-2 (a real no-match run persists `club_filter` and the review fires the "written differently" branch naming the club), UISE-01 (customer `/review` hides the raw exception; operator sees it).
- **`tests/test_v73_modules.py`** (extended) — CDI-1: `TestWeekendInNumbers` gains `test_swimmer_count_is_all_competitors_not_just_achievers` and `test_swimmer_count_falls_back_when_no_traces`.
- **`tests/test_u2_states.py`** (updated) — the two D2 tests that codified the *old leaky* review behaviour were re-pointed at the corrected operator-gated contract (customer hidden; operator sees the escaped detail), and two tests added: `test_review_error_detail_shown_to_operator`, `test_failed_run_error_text_not_leaked_to_customer`. Intent (honest failure surfacing + XSS-escaping) preserved and strengthened, not weakened.

---

## 7. Cross-cutting changes (for reconciliation with parallel audits)

- **`src/mediahub/web/web.py`** (shared monolith) — four localized edits: `upload()` reject status codes; new module-level `_rebuild_staged_meta`; `upload_configure` guard/meta-load; `_persist_run` payload gains `"club_filter"`; `review()` error block gated behind `is_dev`. All additive/surgical; no signatures changed except an added persisted JSON key (`club_filter`) which older runs simply lack (tolerated by `data.get`).
- **`src/mediahub/recognition/weekend_in_numbers.py`** (deterministic engine — likely another audit's territory) — one localized change to the swimmer-count computation. Deterministic (no AI), backward-compatible (falls back when `swim_traces` absent), and covered by new unit tests. Flagged here because it sits inside `recognition/`.
- **`tests/test_u2_states.py`** — updated two pre-existing tests to the corrected security contract (see section 6). Called out explicitly because editing existing tests can collide with another session.

---

## 8. Residual risks / cross-feature items (not fixed here)

- **CDI-3** (P3): meet dates display in US `MM/DD/YYYY`. A proper fix normalises interpreter-carried dates to an unambiguous UK format at the display boundary; it touches shared review/recap rendering (and possibly the graphic renderer) and belongs with a date-normalisation pass rather than this feature-scoped audit.
- **SEC-OBS-1** (P3): the `/api/runs/<id>/status` JSON still returns the raw `error` field to non-operators. Not visibly rendered (the page JS gates it), and the code documents it as intended for API clients — but a fully consistent posture would gate or generalise it. Left for a security-wide reconciliation to avoid changing the documented poller contract.
- **OBS-1**: the shared footer placeholder tokens are an operator-config/layout concern outside Meet Recap.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The core Meet Recap path (tile -> intro -> upload -> configure -> ranked cards -> review -> export) is correct, tenant-isolated, XSS/CSRF/traversal-safe, and polished. Two real correctness bugs on the core deliverable (a headline-stat undercount and a broken "re-run" control) plus a customer-facing exception leak were found and fixed; the residuals are P3 polish.

---

## 10. Handover & merge status

- **Branch:** `claude/audit-meet-recap-gqedph` (the session-designated branch; the audit's `audit/<slug>` maps to slug `meet-recap`).
- **Merge status:** **MERGED to `main`.** Four commits fast-forwarded onto `1f938a2`; `main` tip is now **`ca6f025`** (non-force push). The full suite ran green on two consecutive integrated bases (`95c83d0`: 12,499 passed / 10 skipped; `0c13738`: 12,514 passed / 10 skipped). Because `main` advanced again during each 15-min run, the final base `1f938a2` (which added only the unrelated athlete-spotlight audit, rebased with zero conflicts) was gated with a focused-but-broad subset — boot smoke + the meet-recap and shared-surface regression cluster + main's newly-added `test_spotlight_audit.py` (191 passed) — then pushed within the freshness window. This full-suite-twice + targeted-final-gate is the merge protocol's sanctioned path for a trunk moving faster than a 15-min suite.
- **Review the diff:** `git show b9d8eb2 b245252 56a0439 ca6f025` (the four `[meet-recap]` commits on `main`).

