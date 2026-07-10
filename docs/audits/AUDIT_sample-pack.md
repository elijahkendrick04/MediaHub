# Feature Audit — Sample Pack ("create")

**Feature:** The U.4 "Generate a sample pack" one-click onboarding path in Create.
**Mode:** AUDIT+FIX
**Branch:** `claude/sample-pack-audit-99itin` (the harness-designated development branch;
the task's suggested `audit/sample-pack` name is mapped onto it — see Handover).
**Date:** 2026-07-10
**Verdict:** **WORKS** (see §9).

---

## 1. Scope contract

**Definition.** "Sample Pack" is the signed-in first-run onboarding path that runs the
**real** content pipeline on a bundled synthetic meet PDF, stamped to the user's own
organisation, so a brand-new club can watch the whole engine work end to end (parse →
detect → rank → brand → cards/captions) without having to source a results file first.
It lands in the normal review queue like any real run, marked as demo/fictional data.
"Working" means: a signed-in, org-ready user clicks "Generate a sample pack", a real run
starts under their org, the demo PDF parses and produces a non-empty, correctly-attributed,
error-free content pack filtered to the hero club, and the review page clearly flags it as
demo data with a route back to uploading real results.

**Routes/endpoints owned:**
- `POST /onboarding/sample` → `onboarding_sample()` (the only state-changing route the
  feature owns). Redirects to `run_status` on success.

**Files owned (blast radius):**
- `src/mediahub/web/web.py`, and only these sample-pack members within it:
  - constants `_SAMPLE_MEET_PDF` / `_SAMPLE_MEET_CLUB` / `_SAMPLE_MEET_FILENAME`
  - `_run_is_sample()` / `_mark_run_sample()` (the sidecar marker)
  - `_sample_pack_cta()` (the reusable CTA, rendered on 3 surfaces)
  - the `onboarding_sample` route body
  - the review-page **sample banner** block
  - the `make_page` **first-run nudge** block that calls `_sample_pack_cta`
  - the CTA call-sites on the upload page and the org-setup preview
- `samples/demo-meet-results.pdf`, `samples/README.md` (the fixture + its doc)
- `tests/test_u4_onboarding_sample.py`
- `docs/audits/AUDIT_sample-pack.md` (this report)

**Shared files depended on but NOT freely rewritten:** the app factory / gating
`before_request`s in `web.py`, the CSRF layer, `_recovery_page`, `_start_run` /
`_execute_run` / `run_pipeline_v4` (the pipeline), `club_profile.py`
(`ClubProfile.is_ready`), and the `context_engine` / recognition research path.

**Inputs / outputs / state.** Input: an authenticated request from an org-ready session
(no user file — the bundled PDF is the input). Output: a normal run whose cards/captions
carry the user's brand; a redirect to `/runs/<id>` that advances to `/review/<id>`. State:
a run row in `data.db`, run artefacts under `RUNS_DIR/<id>/`, and a `sample.json` marker
sidecar that flags the run as demo data.

**Intended happy path (concrete):** org-ready user POSTs `/onboarding/sample` → `302` to
`/runs/<id>` → pipeline runs the demo PDF, filtered to "Riverbend SC" (8 of 30 swims kept)
→ ~13 ranked achievements / 13 cards, `run.error is None` → `/review/<id>` renders the
cards **and** a "Sample meet … the swimmers and clubs are fictional" banner with an
"Upload real results →" link.

---

## 2. Environment

- **Install:** `pip install -e .` (+ `pytest`); Python 3.11.15. Session-start hook also
  reinstalls `requirements.txt` and pins Playwright to the prebaked Chromium.
- **Local run:** driven via the Flask test client (`create_app()`, `TESTING=True`),
  mirroring `tests/test_u4_onboarding_sample.py`. Each check uses a fresh temp
  `DATA_DIR` / `RUNS_DIR` / `SWIM_CONTENT_PROFILES_DIR`. The full app also boots clean
  (502 routes) via `mediahub.web.web:create_app`.
- **Offline / no-spend:** no LLM provider configured, so AI surfaces honest-error
  (expected); `fetch_pbs=False` on this path; the web-research boundary
  (`WebResearcher.search`) is stubbed to `[]` in the new E2E test so no outbound call
  fires. No real Gemini/Anthropic/Photoroom/Replicate calls were made.
- **Security-parity checks** were run with `ENFORCE_ORG_GATE=1` / `ENFORCE_CSRF=1` to
  exercise the production gates that `TESTING` bypasses.
- **Green gate (full suite):** `python -m pytest tests/ -q` on the rebased result →
  **12,485 passed, 1 failed, 10 skipped** in 44m13s. The single failure —
  `tests/test_log_sentinel.py::test_boot_grace_blocks` — is a pre-existing **wall-clock
  flake unrelated to this feature**: it asserts a 600s boot-grace window is still open, but
  the single-process 44-minute run had aged past 600s by the time it ran. It **passes in
  isolation** (`pytest tests/test_log_sentinel.py::test_boot_grace_blocks` → passed in
  0.17s) and my diff does not touch `test_log_sentinel.py` or the sentinel module. CI runs
  the suite **sharded** (`unit-suite.yml`, pytest-split), so each shard reaches this test
  well within its grace window and it passes there. The pinned pre-commit (ruff v0.8.4)
  hooks pass on all changed files; no secrets / no `.env` staged.

---

## 3. Test matrix results

| # | Dimension | Result | Note |
|---|-----------|--------|------|
| 1 | Functional correctness | **PASS** | Real pipeline on the bundled PDF → 13 cards / 13 ranked achievements, `run.error is None`, filtered to Riverbend SC. Now locked by `test_bundled_demo_pdf_produces_a_real_content_pack`. |
| 2 | Every interactive control | **PASS** | CTA renders a real `<button type=submit>`+form on all 3 surfaces; review banner link → `/upload`; redirect → `/runs/<id>`; nudge retires after a `done` run. No dead/misrouted/no-op controls. |
| 3 | Input validation / edge cases | **PASS** | No-org & not-ready → `302 /organisation/setup` (no run); `GET` → `405`; missing PDF → `404` recovery ("Sample meet unavailable", no run); unicode/emoji/very-long org name → run starts and review renders. |
| 4 | UI state handling | **PASS** | Loading (run_status), empty-pack (banner + "no standout swims"), and success states render. One gap on the **error** state — see F2. |
| 5 | Server-side error handling | **PASS** | `_start_run` raising → graceful `500` "engine stalled" page; no traceback / internal path / exception text leaked. Correct codes throughout (302/404/405/409/500). |
| 6 | Data integrity | **PASS** | Marker written & read back; run attributed to the session's own `profile_id`; club filter correct (22 excluded, 8 kept); runs isolated by server uuid. Non-idempotent double-submit addressed — see F1. |
| 7 | Security | **PASS** | Double-gated authz; multi-tenant isolation holds (forged `profile_id` ignored); CSRF enforced (`403` without token); XSS escaped via `_h`; no secret leak; no path traversal/IDOR; audit-log carries nothing user-controlled. No findings. |
| 8 | Performance | **PASS (1 residual)** | Request path does no unbounded work; meet-identity research is globally cached. `runs` has no `(profile_id,status)` index, but that is pre-existing and app-wide — see R2. |
| 9 | Responsive / a11y | **PASS** | CTA + banner flex-wrap, no overflow at 360px; real button/link, keyboard-reachable, no icon-only/missing-alt controls. Heading-level skip is a page-wide convention, not sample-specific — see §Rejected. |
| 10 | Rendered-graphic correctness | **N/A / PASS** | The feature reuses the standard card renderer; cards render in the user's brand. No sample-specific render path. |
| 11 | Consistency & copy | **PASS** | British English; no placeholder/debug/TODO strings; the three CTA headings differ by context intentionally. Em-dash usage is house style, not a defect — see §Rejected. |

Evidence: reproductions were run via the Flask test client and `run_pipeline_v4` directly;
the durable ones are captured as tests in `tests/test_u4_onboarding_sample.py`.

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status |
|----|-----|-------|--------------|------------|--------|
| F1 | P2 | Double-click on the CTA queued two identical 30–90s runs | POST `/onboarding/sample` twice → two `_start_run` calls, two runs (`/runs/run00000001`, `…0002`); rendered form had no submit guard | `_sample_pack_cta` emitted a bare submit form; the route has no server-side dedup | **Fixed** — `4c543cb` |
| F2 | P3 | Sample banner dropped on the run **error** review page | Force a sample run to terminal error → `/review/<id>` renders the shared "Processing failed" page, which returns before the sample-banner block; only the filename hints it was a demo | The error early-return in the review route precedes the `_run_is_sample` banner block (shared review flow) | **Logged** (out of tight scope; low value) |
| F3 | P3 | Route comment falsely claimed "no third-party calls for demo data" | The recognition step logs "Researching meet identity…" and calls `WebResearcher.search` even with `fetch_pbs=False`; by default this falls through to a live DuckDuckGo GET | `discover_meet_identity` always researches uncached meets; `fetch_pbs` only gates PB verification, not meet-identity | **Fixed (comment)** — `4c543cb`; behaviour logged as R1 |
| G1 | P2 (coverage) | No test proved the bundled PDF actually runs the pipeline | Every existing test monkeypatches `_start_run`, so a corrupt/regenerated PDF or a parser/detector/ranker regression that empties the pack would ship green | Test gap | **Fixed** — `4c543cb` |

**Rejected (false positives against repo convention — verified, not defects):**
- *Em dashes in user-facing copy.* Flagged by an auditor, but `web.py` alone contains
  **1,968** em dashes across shipped copy, with **no** lint/test guard — it is the
  established MediaHub house style. Retrofitting only the sample-pack strings would make
  them inconsistent with every neighbouring surface. New copy I authored uses plain
  hyphens; existing house-style copy is left untouched.
- *`h1 → h3` heading-level skip on the CTA card.* The whole page uses `h1` then `h3`
  card headings (`/upload` sequence `1,3,3,3,4,4,4,3`; `/make` similar) — a page-wide
  pattern, not sample-specific. Changing only the CTA's `h3` would break local
  consistency without fixing the page. Out of scope.

---

## 5. Fixes applied

All fixes are inside the feature's blast radius (the `_sample_pack_cta` helper, the
`onboarding_sample` route comment, and the feature's own test module). No shared file was
functionally changed.

1. **F1 — double-submit guard** (`_sample_pack_cta`): both CTA variants now carry a small
   progressive-enhancement `onsubmit` guard that blocks a second synchronous submit
   (`dataset.mhSent`) and disables the button just after the first POST starts
   (`setTimeout(…,0)` so the in-flight POST is not cancelled). With JS off, the form posts
   exactly as before. A sample pack starts a real 30–90s pipeline run, so this stops an
   ordinary double-click during onboarding from queuing two identical demo packs and two
   worker jobs.
2. **F3 — honest route comment** (`onboarding_sample`): the comment no longer claims "no
   third-party calls for demo data". It now states that PB web-verification is off, that
   meet-identity research inside the recognition report still runs, and that it is globally
   cached so only the first uncached sample generation on a deployment can trigger an
   outbound lookup. Behaviour is deliberately unchanged — the sample pack's promise is to
   run the *real* engine, and the global cache bounds the cost to ~one lookup per
   deployment per 30 days (see R1).

---

## 6. Tests added / extended

Both added to `tests/test_u4_onboarding_sample.py` (extending the existing module, not a
parallel harness):

- `test_sample_cta_has_double_submit_guard` — locks F1: both CTA variants render an
  `onsubmit` guard containing `this.dataset.mhSent` and still post to
  `/onboarding/sample` (so the no-JS path is preserved).
- `test_bundled_demo_pdf_produces_a_real_content_pack` — closes G1: runs the **real**
  `run_pipeline_v4` on the bundled PDF (web-research stubbed to `[]` for offline
  determinism) and asserts `run.error is None`, a non-empty card list, non-empty ranked
  achievements, `n_achievements > 0`, and that the pack is about the hero club. This is the
  first test that proves the sample file still parses/detects/ranks — the feature's whole
  promise — rather than mocking the worker away.

Result: `tests/test_u4_onboarding_sample.py` → **13 passed** (was 11).

---

## 7. Cross-cutting changes

**None.** No shared file was functionally modified. The only edits to `web.py` are within
the sample-pack members listed in §1 (the CTA helper and the route comment). The `runs`
schema, gates, CSRF layer, `_recovery_page`, and the pipeline are untouched.

---

## 8. Residual risks / cross-feature items (not attempted here)

- **R1 (P3, behavioural) — meet-identity research runs on synthetic demo data.**
  `build_recognition_report_for_run` → `discover_meet_identity` always researches an
  uncached meet; `fetch_pbs=False` does not suppress it, and the default search backend is
  a live DuckDuckGo GET. Impact is bounded (global 30-day cache keyed on the constant demo
  meet name → ~one lookup per deployment per 30 days, and the demo meet name literally
  contains "SYNTHETIC DEMO DATA"), but the first uncached sample generation can be up to a
  minute slower and makes an outbound call on fictional data. A behavioural fix (skip
  research when the meet is the synthetic demo) belongs in shared `context_engine`
  code and should be coordinated — logged rather than applied to keep this audit's
  footprint tight.
- **R2 (P3, perf) — `runs` has no `(profile_id, status)` index.** The `make_page`
  first-run-nudge query (and ~10 other call sites) scans `runs` filtered by
  `profile_id`/`status`. Negligible at current scale (`LIMIT 1` short-circuits; tens of
  rows per deployment) and pre-existing / app-wide, so a shared schema change is out of
  scope for a single-feature audit.
- **F2 (P3) — error-state review page** drops the demo banner (see §4). A fix touches the
  shared review-route early-return; low value, logged.
- **Observation (not a bug):** a completed *sample* run counts as a `status='done'` run,
  so it retires the `make_page` first-run nudge. This reads as correct onboarding UX (the
  user has now seen the engine work), but if the intent were "retire only after a *real*
  run", the nudge query would need to exclude sample runs. Left as-is; noted for the owner.

---

## 9. Feature verdict

**WORKS.** The happy path is correct and now regression-locked end to end (real pipeline,
13 cards, correct org attribution and club filtering); every gate, error path, and
security property (authz, multi-tenancy, CSRF, XSS, secrets, traversal) is sound; and the
one genuine UX defect (double-submit) is fixed and tested. The remaining items are P3
polish or pre-existing, app-wide characteristics logged for coordination.

---

## 10. Handover & merge status

- **Branch:** `claude/sample-pack-audit-99itin` (the harness-designated branch; the
  session's git rules require developing here and never pushing to another branch without
  explicit permission, so the task's suggested `audit/sample-pack` slug is realised on this
  branch and a **draft PR** is opened rather than a direct push to `main`).
- **Merge status:** rebased onto `origin/main` twice as it advanced (BASE `33602c5`, after a
  parallel meet-recap audit landed), clean each time (no conflicts); green gate re-run on the
  integrated result; pushed and **draft PR opened: elijahkendrick04/MediaHub#1124**. Landing
  is via the PR (branch-protection "up to date + CI on merge result" is the task-sanctioned
  equivalent of the atomic-push gate), not a direct push to `main` — the harness git rules
  forbid pushing to another branch, and `main` auto-deploys to production. CI (sharded unit
  suite + hygiene + security + contract) is the authoritative final gate on the merge result.
- **Orchestration note:** the multi-dimension audit was run as a parallel workflow of
  auditor + adversarial-verifier subagents. Several verify agents and one audit dimension
  hit the account's weekly subagent limit mid-run; those dimensions
  (correctness/controls, data-integrity/perf, and all verification) were completed
  **solo** with direct reproductions. One audit agent also exceeded its read-only remit and
  drafted the F1/F3/G1 changes in the working tree; I reviewed, corrected the framing, and
  verified each before owning them.
- **Review the diff:** `git diff origin/main...claude/sample-pack-audit-99itin`
