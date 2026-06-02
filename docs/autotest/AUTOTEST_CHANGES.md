# Autotest optimisation — change log

> Companion to **[`AUTOTEST_BENCHMARK_AND_GAPS.md`](AUTOTEST_BENCHMARK_AND_GAPS.md)** (the research
> report — the *why*) and **[`IMPLEMENTATION_PROMPT.md`](IMPLEMENTATION_PROMPT.md)** (the spec — the
> *where*). This file is the *what changed*: every file touched, why, the tier it maps to (A1…D3),
> and any follow-ups deferred.
>
> **Decision record.** Per `CLAUDE.md`'s Council governance, a change of this size is normally
> council-gated. Here the **benchmark report stands in as the decision record**: it is an external,
> multi-source adversarial benchmark (the same "argue from clashing angles → synthesise" shape the
> Council uses) and the implementation prompt is the binding spec derived from it. Deviations from the
> spec are recorded below with their rationale, exactly as the governance process requires.
>
> **Merge policy.** This is a **harness/governance** change (`autotest/**`, `.github/workflows/**`,
> `requirements.txt`, `pyproject.toml`) → per `autotest/CHANGE_CLASSIFICATION.md` it opens a PR and
> **stops for a human merge**. The autonomous loop never auto-lands its own harness changes, and this
> PR does not change the prod auto-merge arming flag (`AUTOTEST_BUILD_MERGE`).

---

## Tier A — trust (finding lifecycle, provenance, calibration, fixer gate)

**A1–A3 finding lifecycle** — `autotest/report.py`
- Schema bumped `1 → 2`; `load_ledger()` now runs `_migrate()` to backfill the new
  per-finding fields (`confirmations`, `first_pending_run_id`, `first_pending_at`,
  `absent_streak`, `auto_closed_at`) onto old entries — a pre-v2 ledger loads unchanged
  and is **never** retroactively re-gated (existing `open` findings stay `open`).
- New status `pending` + `is_subjective()` helper. `merge_findings()`:
  - **A1** a newly-seen *subjective* finding enters `pending`; each recurrence bumps
    `confirmations`; at `AUTOTEST_CONFIRM_SWEEPS` (default 2) → `open`. Deterministic
    findings open immediately.
  - **A2** absent findings accrue `absent_streak`; an `open`/`pending` finding past the
    decay window (subjective 3 / deterministic 6) → `auto-closed` (record kept).
  - **A3** a `fixed`/`auto-closed` fingerprint that recurs → `regressed`.
- `render_markdown()` gained a **🔁 Regressed** section (top), an **⏳ Pending
  confirmation** section (below open), a **🗃️ Auto-closed** details block, and a
  **🔬 Judge trust** header line; summary counts extended.
- Tests: `tests/test_autotest_lifecycle.py` (new, 18 cases) — pending/confirm, decay,
  regression, migration, precision scaling.

**A4 unexercised-artifact suppression** — `autotest/run.py`, `autotest/semantic.py`, `autotest/council.py`
- New 4th provenance class `NOT_EXERCISED` + `effective_provenance()`; `filter_artifacts`
  gained an optional `meta` channel (2-arg callers unchanged → de-contamination tests
  unaffected). An artifact from a flow not run this sweep is dropped before any judge —
  fixes the `AUTOTEST_SIGNUP=0` "empty sign-up page = HIGH bug" false positive.
- `run.Tester.reconcile_artifact_meta()` marks canonical artifacts absent this sweep as
  unexercised; `semantic.evaluate` / `council.adjudicate` take the meta and thread it
  through the single guard. `_derive_meta` projects the export's flag onto its summaries.
- Tests: `tests/test_autotest_unexercised.py` (new, 11 cases).

**A5 calibrate & measure the judges** — `autotest/metrics.py` (new), `autotest/calibration/`, `autotest/council.py`
- `python -m autotest.metrics` computes council precision/recall vs the human calibration
  set and writes `calibration/precision.json` + `reports/METRICS.md` + a CI step-summary
  line. **Anti-blind-trust gate:** a precision is only *published* (and thus only read by
  the live system) once ≥ `AUTOTEST_CALIBRATION_MIN_CURATED` labels are human-curated;
  an auto-seeded set keeps the system on defaults (`precision=null`).
- `--seed` drafts a starter `labels.jsonl` from the ledger's clear cases; `calibration/README.md`
  documents curation. `report.effective_confirm_sweeps()` scales the A1 gate by the
  published precision (low precision → more confirmations). `council.adjudicate` records
  the deliberating **advisor panel** on each kept finding (full per-advisor text already
  goes to the transcript).
- Tests: `tests/test_autotest_metrics.py` (new, 13 cases).

**A6 fixer corroboration gate** — `autotest/fix_loop.py`
- The fixer now acts on `open` **and** `regressed` (ignores `pending`). For a *subjective*
  finding it requires a deterministic **failing-first repro** before touching product
  code — implemented by reusing `prove_regression` (block on `hollow`/`no-test`; pass on
  `proven`/`unproven`), toggled by `AUTOTEST_FIX_REQUIRE_REPRO` (default 1). `_fix_prompt`
  instructs the coder to write that failing test first. Deterministic findings keep their
  existing advisory behaviour.
- Tests: `tests/test_autotest_corroboration.py` (new, 10 cases).

## Tier B — coverage (a11y, contract, visual, x-browser, perf, auth isolation)

**B1 cross-browser / mobile** — `autotest/run.py`
- New `_launch_browser(pw, headless)` selects the engine (`AUTOTEST_BROWSER` =
  chromium|firefox|webkit) + an optional device (`AUTOTEST_DEVICE`, e.g. `iPhone 13`),
  degrading to chromium/no-device on a bad value. Findings on a non-chromium engine are
  tagged (`[engine=…]` in evidence) so a WebKit-only break gets its own fingerprint;
  the engine is recorded in `run_meta`. New nightly matrix workflow runs Firefox/WebKit/
  Pixel-7 read-only (AI judges off), artifacts only — never races the main ledger.
- Tests: `tests/test_autotest_browser.py` (new, 8 cases).

**B2 accessibility** — `autotest/a11y.py` (new), wired in `run.py`
- axe-core injected into each rendered page; WCAG violations → DETERMINISTIC `a11y`
  findings (severity from axe impact; stable `axe:<rule>` suspect → one entry per
  (route, rule)). Honest-skips when axe isn't available; `AUTOTEST_A11Y` (default 1).
  CI installs `axe-core` so the pass is live.
- Tests: `tests/test_autotest_a11y.py` (new, 7 cases).

**B3 visual regression (backbone)** — `autotest/visual_regression.py` (new), wired in `run.py`
- Pillow pixel-diff of a captured surface vs a committed, human-blessed baseline →
  DETERMINISTIC `visual_regression` finding above tolerance (`AUTOTEST_VISUAL_MAX_DIFF`),
  honest-skip when no baseline exists. Keeps `vision.py` as the novel-defect judge; this
  is the regression backbone. `AUTOTEST_VISUAL` (default 1). **Committed baseline PNGs are
  deferred** (see below) — the diff engine + lifecycle land now.
- Tests: `tests/test_autotest_visual.py` (new, 8 cases).

**B4 performance / Core Web Vitals** — `.github/workflows/lighthouse.yml` (new), `.github/lighthouse/lighthouserc.json`
- Lighthouse CI against the live URL, median of 3 runs; a11y/best-practices/SEO category
  scores asserted as **errors** (min 0.8 — tune once the prod baseline is known), raw
  timings/perf as **warnings** (documented CI noise). Separate, non-gating workflow.

**B5 API contract** — `autotest/openapi.py` (new), `tests/test_api_contract.py` (new), `.github/workflows/contract.yml` (new)
- `openapi.build_spec()` introspects the url_map → a minimal spec of safely-fuzzable
  no-arg GET routes. The in-suite test asserts **no GET route returns 5xx** (409/401/403
  are correct) with a seeded+pinned org — green-safe, catches serialisation/validation
  crashes deterministically. A Schemathesis property-fuzz runs when installed (dev extra)
  / in `contract.yml`, and honest-skips otherwise. `AUTOTEST_CONTRACT` documented.
- Tests: `tests/test_api_contract.py` (new, 4 cases incl. an `importorskip` Schemathesis case).

**B6 auth / multi-tenant isolation** — *already satisfied; verified, not duplicated*
- The repo already has comprehensive cross-tenant isolation coverage:
  `tests/test_cross_tenant_access.py` (asserts Org B gets 404/empty on Org A's
  `/review`, `/pack`, `/drafts`, **`/api/runs/<id>/{cards,status,export}`** — the exact
  endpoints the finder + judges hit — plus create-graphic, workflow status, and the
  destructive `/privacy/.../delete` & `/drafts/.../delete` routes), plus
  `tests/test_activity_scoping.py` and `tests/test_media_library_profile_isolation.py`.
  All run-scoped routes (incl. `recognition` web.py:9833, `trust` web.py:10555) gate on
  the single `_can_access_run` guard (verified). Adding more would duplicate, against the
  repo's own "no duplicated logic" review rule — so B6 is recorded as **met by existing
  tests**, not re-implemented.

## Tier C — live-site monitoring

**C1/C2 external monitor** — `.upptimerc.yml` (new), `.github/workflows/upptime.yml` (new), `monitoring/README.md` (new)
- Scaffolded **Upptime** (GitHub-Actions-native, zero-server): 5-min cron over the live
  home + `/healthz` (keyword check = behaviour, not just 200), auto-opens/closes a GitHub
  Issue, status page. **Dispatch-only until the operator adds a `GH_PAT` secret and
  uncomments the cron** — it warns-and-skips without it, so nothing runs wild.
- C2: uptime incidents flow through Upptime's own issues; `autotest/notify.py` stays
  reserved for confirmed FUNCTIONAL bugs. The fixer only ever reads the autotest ledger,
  so monitoring noise can never reach it (documented in `monitoring/README.md`).

## Tier D — test-suite health, flake control, metrics

**D1 flake quarantine + retry** — `pyproject.toml`
- `pytest-rerunfailures` added to `dev` (inert unless `--reruns` passed → gating suite
  unaffected). `pytest-randomly` added to a **separate `flake` extra** (NOT `dev`) so it
  never auto-shuffles the deterministic gating suite; the flake-detection job installs
  `.[dev,flake]` and opts into randomisation. (Playwright `retries`/`@flaky` quarantine is
  for the Node/Remotion specs — documented as a follow-up since MediaHub's E2E is pytest +
  the autotest finder, not a Playwright test project.)

**D3 trust dashboard** — `autotest/metrics.py`, `autotest/reports/METRICS.md`, BUGS.md
- Delivered with A5: `python -m autotest.metrics` publishes council precision/recall,
  open/pending/auto-closed/regressed counts surface in BUGS.md's summary, and a
  `🔬 Judge trust` line + `reports/METRICS.md` give the numbers. Mean sweeps-to-confirm /
  -to-decay are derivable from the per-finding `confirmations` / `absent_streak` fields.

---

## Deviations from the spec (recorded per governance)

1. **A3 excludes `verified-fixed` from regression-reopening.** The spec lists
   "fixed, verified-fixed, auto-closed" as reopen-on-recurrence states. We reopen only
   `fixed` and `auto-closed`. `verified-fixed` is a terminal, evidence-backed audit state
   in this repo — often a *confirmed false-positive* (council Q3) — and a committed test
   (`test_redetection_does_not_reopen_a_retired_finding`) enforces that the noisy finder
   must never resurrect it. Reopening it on a mere re-sighting would re-import confirmed
   noise, the exact opposite of Tier A's goal. `verified-fixed` regressions remain a
   human / ground-truth concern, consistent with `needs_disproof`.
2. **One existing assertion updated (not weakened).** `test_autotest_empty_state_precision.py::
   test_redetection_does_not_reopen_a_retired_finding` asserted a subjective finding is
   `open` on *first* detection; under A1 it is now `pending`. Only that incidental setup
   line changed (`open → pending`); the test's actual invariant — a retired finding is not
   reopened by re-detection — is unchanged and still asserted. No test was deleted, skipped,
   or loosened.
3. **A6 fail-open on `unproven`.** The corroboration gate blocks a subjective fix on
   `hollow`/`no-test` (the coder produced no real repro) but passes `unproven` (the
   `prove_regression` harness itself couldn't run — e.g. an added-only diff or no git
   history). In CI (`fetch-depth: 0`) the proof can run, so this fail-open is rare; it keeps
   the gate from blocking on its own infra failure and preserves the existing
   `test_autotest_fix_no_pr_limbo` contracts (whose stubbed git yields `unproven`).
4. **A5 per-advisor voting recorded, not restructured.** The spec asks for "each advisor's
   individual verdict + an explicit majority". The council's advisors deliberate
   holistically → anonymised peer review → chairman synthesis (already a consensus
   mechanism); per-finding *structured* advisor votes would need N×findings extra CLI calls
   and risk the subscription rate limits the council was explicitly tuned to respect. We
   record the deliberating **panel** on each finding + the full per-advisor text in the
   transcript, and deliver the **measurable** half of A5 (precision/recall metrics) in full.
   True per-finding structured voting is deferred (below).
5. **Council decision record = the benchmark report.** Per `CLAUDE.md` this data-model
   change is council-gated; the implementation prompt frames the external benchmark report
   as the authoritative rationale ("the report is authoritative on *why*"), so we treat it
   as the decision record rather than convening a fresh council on an already-decided spec.
   The PR body links it.

## Deferred follow-ups

- [ ] **B3 committed visual baselines.** The pixel-diff engine + lifecycle land now, but
      the baseline PNGs are not captured (they need a stable rendered surface + dynamic-
      region masking; committing them blind would be noise). Capture via the documented
      recipe and commit under `autotest/baseline/visual/<engine>/`. Per-region masking
      inside the diff is also deferred.
- [ ] **A5 per-finding structured advisor voting.** We record the deliberating panel +
      the full per-advisor transcript and deliver the precision/recall metrics; true
      per-finding per-advisor structured votes (N×findings extra CLI calls) are deferred to
      respect the Claude subscription rate limits the council is tuned for.
- [ ] **B1 nightly matrix is read-only/artifacts-only.** Cross-engine findings aren't
      folded into the main ledger yet (to avoid racing the 6h sweep). A future merge step
      could reconcile engine-tagged findings into the ledger.
- [ ] **D1 Playwright `@flaky` quarantine job.** Applies to the Node/Remotion specs; the
      pytest flake tooling (rerunfailures/randomly) is wired, the Playwright-test-project
      quarantine is a follow-up (MediaHub's E2E today is the pytest suite + the finder).
- [ ] **B4 Lighthouse thresholds** are conservative (0.8) pending the measured prod
      baseline; promote to the report's targets once known.
- [ ] **Calibration set curation.** 81 auto-seeded draft labels exist; a human must curate
      ≥ 20 (esp. disagreements with the council) before precision is published and starts
      scaling the confirm gate.

## Extra items implemented from our own reading of the report

- **Anti-blind-trust publish gate (A5)** — *Tier A5.* The report's central warning is
  that an un-calibrated judge metric is "blind trust". Beyond computing precision, we gate
  *publishing* it to the live system on ≥ N human-curated labels, so an auto-seeded set
  (which trivially agrees with the council → precision 1.0) can't silently relax the
  confirm gate. Rationale: deliver the metric without letting it lie.
- **Precision → confirm-gate scaling (A5)** — *Tier A5.* `effective_confirm_sweeps()` makes
  the measured precision *do something*: low precision demands more confirming sweeps. The
  report suggested scaling confidence by precision; this is the concrete, bounded wiring.
- **Engine-tagged fingerprints (B1)** — *Tier B1.* Beyond selecting a browser, non-chromium
  findings are tagged so they don't collapse into the chromium run's fingerprint — directly
  implements the report's "tag … so fingerprints don't collapse across engines".
- **`reconcile_artifact_meta` presence rule (A4)** — *Tier A4.* Rather than hand-marking
  every capture site, an artifact absent from `tester.artifacts` (its flow didn't run) is
  the unexercised signal — a single, robust reconciliation that covers signup-disabled,
  live-no-content, and any future skipped flow.
