# Claude Code task — optimise the MediaHub autotest autopilot ("autobuilder")

You are working **inside the MediaHub repository** (Python 3.12 / Flask SaaS; Playwright + pytest; GitHub Actions; deployed on Render; AI via the Claude CLI on a subscription token, optional Gemini). Your job is to upgrade the autonomous tester+fixer under `autotest/` so it is **trustworthy** (low false-positive noise) and **covers what a paid human tester would cover**, following a research report that has been provided to you.

Read this entire prompt first. Then read the report in full. Then work in small, reviewable commits on a branch. **Do not skip the safety rules in §1.**

---

## 0. Files provided alongside this prompt

Two markdown files have been uploaded into the working tree (likely at the repo root or wherever the operator dropped them):

1. **This prompt** — `CLAUDE_CODE_PROMPT_autotest_optimisation.md`.
2. **The research report** — its title is **"MediaHub Autotest: Public-Repo Benchmark & Implementation Report"** (filename may vary; find it by that H1 title or by `grep -rl "Public-Repo Benchmark" .`).

**First actions:**
- Locate both files (`git status`, `ls`, or `grep -rl`). If they aren't in the tree yet, search `~/Downloads`, `/tmp`, and the repo root.
- **Read the report end to end before writing any code.** It defines the tiers (A1–A6, B1–B6, C1–C2, D1–D3) referenced throughout this prompt. The report is authoritative on *why*; this prompt is authoritative on *where in the code*.
- Create `docs/autotest/` and **move both files there**: `docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md` (the report) and `docs/autotest/IMPLEMENTATION_PROMPT.md` (this prompt). Add a link to the report from `autotest/README.md` (a new "Benchmark & roadmap" line) and from `docs/` index files if one exists (e.g. `docs/INVENTORY.md`).
- **You are explicitly instructed to do everything specified in this prompt AND to interpret the report yourself and implement anything else in it you judge valuable** — even if not itemised below. Where you act on your own reading of the report beyond the explicit steps, record it in §8's `AUTOTEST_CHANGES.md` with a one-line rationale and the tier it maps to.

---

## 1. Operating rules (NON-NEGOTIABLE — these mirror the repo's own governance)

- **Branch + PR, human merge.** Per `autotest/CHANGE_CLASSIFICATION.md`, changes to the harness (`autotest/`, CI, governance) **open a PR and stop for a human merge** — the loop never auto-lands harness changes. Do the same: work on a branch (suggest `autotest/optimise-trust-and-coverage`), push, open a PR for review. **Do not enable or rely on auto-merge for your own changes.**
- **Do not touch the deterministic product engine.** Leave parsers, detectors, the ranker, PB engine, and colour-science untouched (the repo treats these as protected paths). This task is about the *test harness and CI*, not the product pipeline. If a real product bug is implied by the report, file it as a normal autotest finding/issue — do not fix product code here.
- **Never weaken, delete, or skip tests to make CI pass.** The whole suite (~2837 pytest tests) must stay green. Add tests; don't remove or loosen them. If a change breaks a test, fix the root cause.
- **Preserve all existing safety nets:** the `autotest/STOP` kill switch, protected-engine abort, scope caps (`AUTOTEST_BUILD_MAX_FILES`/`AUTOTEST_BUILD_MAX_INSERTIONS`), iterate-to-green, regression-proof, and attempt-cap→GitHub-issue. Your changes must not bypass or disarm them.
- **Honest-skip everywhere.** Any new step that depends on an AI provider, an external service, or an optional dependency must skip cleanly (record a non-bug `info` finding) when the dependency/key is absent — never crash the sweep, never invent findings. This matches `semantic.py`/`vision.py` behaviour today.
- **Respect the provenance/de-contamination contract** in `semantic.py` (RENDERED_PAGE / TESTER_CONTROL / TESTER_SUMMARY). You will *extend* it (§2, A4), never relax it.
- **Config via `AUTOTEST_*` env flags with safe defaults**, read through `os.environ.get`, matching the existing convention and documented in `autotest/README.md`. New behaviour should be toggleable and default to **on but conservative**.
- **Bump the ledger schema and migrate.** `report.py` has a `SCHEMA_VERSION`. When you add ledger fields, bump it and make `load_ledger()` backfill missing fields on old entries so existing `ledger.json` keeps working.
- **Keep the prod auto-merge arming decision with the operator.** The workflow currently sets `AUTOTEST_BUILD_MERGE: "1"`. Do **not** silently flip it. Implement the deterministic-corroboration gate (A6) so that *even when armed*, only corroborated findings can drive a fix; leave the arm/disarm switch and any change to it to the human, and note the report's recommendation (keep prod merges human until trust metrics are met) in the PR description.

---

## 2. TIER A — Make the tool trustworthy (HIGHEST PRIORITY; do this tier first and land it before Tier B)

The core defect today: subjective AI findings open on a single sighting and **never age out**, so the ledger fills with non-reproducing "bugs". Fix the **finding lifecycle**.

**Crucial distinction you must implement and respect throughout Tier A:**
- **Deterministic findings** — categories produced by code, not judgement: everything from `run.py`'s deterministic finder (`http_5xx`, `server_traceback`, `page_exception`, `network_error`, `broken_link`, `flow_failure`, `navigation_error`, `js_console_error`), `ground_truth.py`, `baseline.py`, and the new `a11y` / `contract` / `visual_regression` findings from Tier B. These go **straight to `open`** (no confirm gate) and decay only slowly.
- **Subjective findings** — judgement calls: `semantic:*`, `vision:*`, and `council:*`. These are the ones that get the **pending → confirm-on-repeat** gate and faster decay.

### A1. Confirm-on-repeat gating (`autotest/report.py`)
- Add a new status **`pending`** (insert into the status vocabulary alongside `open`/`fixing`/`fixed`/`verified-fixed`/`needs_disproof`).
- New ledger fields per finding: `confirmations` (int), `first_pending_run_id`, `first_pending_at`.
- In `merge_findings`: a **subjective** finding that is newly seen enters `pending` (not `open`). Each subsequent sweep in which the same fingerprint recurs increments `confirmations`. When `confirmations >= AUTOTEST_CONFIRM_SWEEPS` (default **2**, i.e. seen in 3 sweeps total — tune via env), transition `pending → open`. A **deterministic** finding still inserts directly as `open`.
- `BUGS.md` (via `report.py` render): show `pending` findings in a separate, clearly-labelled **"⏳ Pending confirmation"** section *below* open bugs, with their confirmation count. The fixer must ignore `pending` (see A6).
- *Borrow the pattern from:* Prometheus `for:` (alert stays *pending* until the condition persists) and Grafana "Pending period" — cited in the report (A1).

### A2. Decay / auto-close after consecutive absences (`autotest/report.py`)
- New ledger fields: `absent_streak` (int), `auto_closed_at`, plus reuse `present_last_run`.
- In `merge_findings`, after marking everything not seen this run: increment `absent_streak` for absent findings (reset to 0 when seen). When `absent_streak >= AUTOTEST_DECAY_SWEEPS_SUBJECTIVE` (default **3**) for subjective findings, or `>= AUTOTEST_DECAY_SWEEPS_DETERMINISTIC` (default **6**) for deterministic ones, transition `open`/`pending → auto-closed` with `archived_reason="decayed: not reproduced for N sweeps"`. **Never delete** the record — keep it so a recurrence can reopen it (A3).
- Terminal states (`verified-fixed`) are exempt from decay.
- *Borrow from:* Sentry auto-resolve (`resolveAge`; the report quotes Sentry's "auto-resolve to 2 weeks" recommendation) — cited (A2).

### A3. Regression-aware reopening (`autotest/report.py`)
- When a fingerprint currently in a closed/terminal/auto-closed state (`fixed`, `verified-fixed`, `auto-closed`) **recurs**, set status **`regressed`**, reset `absent_streak=0`, and surface it at the **top** of `BUGS.md` in a **"🔁 Regressed"** section, including the prior `fix_pr`/`fix_branch`/commit if recorded. This strengthens the existing `needs_disproof` path.
- *Borrow from:* Sentry regression detection (`is:regressed`) — cited (A3).

### A4. Stop feeding intentionally-unexercised artifacts to judges (`autotest/run.py` + `autotest/semantic.py`)
- **Root cause today:** with `AUTOTEST_SIGNUP=0` on the schedule, `signup_text` is empty *by configuration*, yet the `user_brain` judge flags the empty page as HIGH.
- In `run.py`, when capturing artifacts (`home_text`, `signup_text`, `review_text`, `export_json`, screenshots, etc.), attach metadata recording whether the flow that produces each artifact was **actually exercised** this sweep. Concretely: store artifacts with an `exercised: bool` (and optional `skipped_reason`) — e.g. a small parallel dict `tester.artifact_meta[key] = {"exercised": bool, "skipped_reason": str}`, or wrap values. When a flow is skipped (signup disabled, no content on a live org, lifecycle not run), mark its artifact `exercised=False`.
- In `semantic.py`, add a fourth provenance class **`NOT_EXERCISED`** to the provenance model and make `filter_artifacts` (the single guard used by both the judge dispatch and the council framing) **drop any artifact whose `exercised` is False** before it reaches a judge — regardless of its RENDERED_PAGE/TESTER_* class. An unexercised artifact is **judge-ineligible**. (Keep the existing fail-closed/fail-open asymmetry for unknown keys.)
- Net effect: an empty page that exists only because we didn't run that flow can never become a finding. A genuinely empty page from an *exercised* flow still can.
- *This is an extension of the council-mandated de-contamination scheme — preserve its single-implementation property.*

### A5. Calibrate, ensemble, and MEASURE the judges (`autotest/council.py`, new `autotest/calibration/`, new `autotest/metrics.py`)
- **Per-advisor votes:** in `council.py`, record each of the 5 advisors' individual verdicts (not just the chairman's) into the finding's `rationale`/a structured field, and require an explicit majority **plus** the chairman rationale to confirm. Keep anti-sycophancy.
- **Calibration set:** create `autotest/calibration/labels.jsonl` — a human-labelled set of past findings (fingerprint, the finding's key fields, and `label ∈ {real, noise}`). Seed it from the current `ledger.json` + the council transcript under `autotest/reports/council/` (pre-label the council's own "blind_spot/over-flagged" rulings as `noise`, confirmed defects as `real`); leave a short `autotest/calibration/README.md` explaining how a human curates it. Target ~50–100 labelled items; it's fine to start smaller and grow.
- **Metrics harness:** add `autotest/metrics.py` with a function that, given the calibration set and the council's verdicts, computes **precision and recall** of the council (treat judge outputs as noisy labels vs the human set). Wire a CLI (`python -m autotest.metrics`) and print a one-line summary into `GITHUB_STEP_SUMMARY` and `BUGS.md` (a "🔬 Judge trust" line: precision/recall, n labelled).
- **Confidence scaling (optional but recommended):** scale a subjective finding's effective severity/priority by the council's measured precision before it becomes `open`; if precision is unknown, fall back to current behaviour.
- *Borrow from / cite:* the report's A5 sources — "Noisy but Valid" (calibration set → TPR/FPR; arXiv:2601.20913), ChainPoll / "2-of-3 judges" panel voting (arXiv:2310.18344), and the cautionary "A Coin Flip for Safety" (arXiv:2603.06594) and "confabulation consensus" (arXiv:2602.09341). Add these as references in `docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md` if not already linked.

### A6. Gate the fixer on deterministic corroboration (`autotest/fix_loop.py`, `autotest/gitops.py`)
- The fixer must **only act on**: (a) **deterministic** findings (oracle/baseline/a11y/contract/visual/finder), or (b) **subjective** findings that have **passed A1** (status `open`, i.e. confirmed ≥ `AUTOTEST_CONFIRM_SWEEPS`) **and** for which the fixer can first write a **failing deterministic reproduction** (a pytest or Playwright test that fails on current `main`). If no deterministic repro can be produced for a subjective finding, the fixer **does not change product code** — it leaves the finding `open` and (after the existing attempt cap) opens a GitHub issue for a human.
- This sits *in addition to* the existing protected-engine/harness/scope/green-test/regression-proof gates — do not remove any of them.
- Add `AUTOTEST_FIX_REQUIRE_REPRO` (default **1**) to toggle the "must write a failing test first for subjective findings" rule.
- *Borrow the lesson from:* the Shortest community's own conclusion that LLM tests lack determinism for CI gating (report A6 / Category 3).

**Tier A acceptance criteria (verify before opening the PR):**
- Re-running the finder twice in a row against a stable target does **not** grow the open-bug count from one-shot subjective findings (they sit in `pending`).
- An artifact from a skipped flow (e.g. signup with `AUTOTEST_SIGNUP=0`) produces **no** semantic/vision/council finding.
- The existing `ledger.json` loads without error after the schema bump (old entries backfilled).
- `python -m autotest.metrics` runs and prints precision/recall (or an honest "insufficient labels" message).
- Full pytest suite green; existing autotest entrypoints (`python -m autotest.run`) still run.

---

## 3. TIER B — Coverage a human tester would catch (after Tier A is committed)

Add these as **deterministic** finding sources (they bypass the A1 confirm gate). Keep each behind an `AUTOTEST_*` flag, default on, honest-skip if a dep is missing.

### B1. Cross-browser + mobile (`autotest/run.py` Playwright launch; CI matrix)
- Today the launcher is Chromium-only (`pw.chromium.launch`). Introduce a browser/device selection driven by `AUTOTEST_BROWSER` (`chromium`|`firefox`|`webkit`) and `AUTOTEST_DEVICE` (a Playwright device name like `iPhone 13`/`Pixel 7`, optional). Run the **primary flow + a smoke pass** across the configured target; in CI, run Chromium on the 6-hour schedule and a **fuller matrix nightly** (add a scheduled matrix job in `autotest.yml` or a sibling workflow). Tag any browser-specific finding with the engine/device in its route/evidence so fingerprints don't collapse across engines. **[The nightly CI matrix was removed 2026-07-08 — see docs/adr/0021; the local `AUTOTEST_BROWSER`/`AUTOTEST_DEVICE` browser-select capability in `run.py` is retained.]**

### B2. Accessibility (`@axe-core/playwright`; new `a11y` finding class in `run.py`)
- After each rendered page in `probe`/`_capture_surface`, run **axe-core** against the DOM and emit violations as a new **deterministic** finding category `a11y`, severity mapped from axe impact (critical/serious→high, moderate→medium, minor→low). Install `@axe-core/playwright` (Node) — or inject `axe.min.js` and call it via `page.evaluate` to avoid a new npm dep if you prefer. Toggle `AUTOTEST_A11Y` (default 1); honest-skip if axe isn't available. Consider `pa11y-ci` as a separate CI job if you want sitemap-wide coverage.

### B3. Visual-regression baselines (Playwright snapshots; optionally Argos/Lost Pixel)
- Add **deterministic** visual baselines for the key surfaces the VLM already screenshots (home, review). Use Playwright's built-in `expect(page).toHaveScreenshot()` with `animations:'disabled'`, masking dynamic regions (captions, timestamps, run ids) via `mask:`/`stylePath`, and per-browser/platform baselines committed under `autotest/` (a human-blessed baseline, analogous to `baseline.py`'s golden baseline — never auto-updated by the loop). Emit diffs as category `visual_regression`. Keep `vision.py` as the **novel-defect** judge; the snapshots are the **regression backbone**. `AUTOTEST_VISUAL` (default 1).

### B4. Performance / Core Web Vitals budgets (Lighthouse CI; new CI job) **[Removed 2026-07-08 — see docs/adr/0021.]**
- Add a **Lighthouse CI** job (`treosh/lighthouse-ci-action` or `@lhci/cli autorun`) against the live Render URL with a `budget.json`. Assert **accessibility / best-practices / SEO scores and resource budgets as errors**, and treat raw timing metrics (LCP/TBT ms) as **warnings** (documented CI noise); use `numberOfRuns: 3` (median). This can live in its own workflow file (`.github/workflows/lighthouse.yml`) rather than inside the autotest sweep.

### B5. API contract/schema testing for `/api` (Schemathesis — Python/pytest-native)
- Generate or hand-write an **OpenAPI** spec for the Flask API if one doesn't exist (introspect the `url_map` from `discover_get_routes`'s `create_app()` to enumerate routes as a starting point). Add **Schemathesis** tests to the pytest suite (`schema.parametrize()`, `from_wsgi=app` for Flask) and a CI step (`schemathesis/action`), surfacing failures as deterministic `contract` findings. This catches 5xx/serialisation/validation bugs without the judges. `AUTOTEST_CONTRACT` (default 1).

### B6. Auth / role / multi-tenant isolation (`tests/` + optional autotest pass)
- Add deterministic tests that authenticate as **Org A** and assert **Org B**'s resources return 403/404 (no cross-tenant leakage) — exercising the org-pin/session model that `run.py` already drives. Use Playwright `storageState` per role where helpful. Emit leaks as **critical** deterministic findings.

---

## 4. TIER C — Live-site monitoring distinct from the 6-hour CI

### C1. External synthetic monitor (separate from the bug-finding/fixing pipeline)
- Stand up an **external monitor** of the primary login + a lightweight health check, running every 1–5 min, **completely separate** from the autotest finder/fixer so monitoring noise can never reach the fixer. Two acceptable implementations — pick one and scaffold it:
  - **Checkly "monitoring as code"** (`checkly` CLI): reuse a trimmed Playwright `*.check.ts`/`*.spec` of the login + health flow; config + a `checkly.config` committed under `monitoring/`. Alerts to Slack/PagerDuty (leave the destination as a documented TODO/secret).
  - **Upptime** (GitHub-Actions-native, zero-server): add an `.upptimerc.yml` and the Upptime workflow targeting the Render URL + `/healthz`; it opens/closes GitHub Issues on down/up and publishes a status page. (Self-hosted **Uptime Kuma** is the alternative if the operator prefers a server.) **[The Upptime monitor built from this was removed 2026-07-08 — see docs/adr/0021.]**
- Document the choice and setup in `monitoring/README.md`.

### C2. Incident hygiene
- Route **uptime** events through the monitor's native issue/alert flow (Upptime auto-issues, or Checkly→PagerDuty), and reserve `autotest/notify.py` for **confirmed functional bugs** only. Note this split in `monitoring/README.md`.

---

## 5. TIER D — Test-suite health, flake control, and metrics

### D1. Flake quarantine + retry
- Configure Playwright `retries: process.env.CI ? 2 : 0`, `trace: 'on-first-retry'`; add a `@flaky` tag convention and run quarantined specs in a **separate non-blocking** CI job (`--grep @flaky`) while the main job excludes them (`--grep-invert @flaky`). For the pytest suite add **pytest-rerunfailures** (`--reruns`) and **pytest-randomly** (surface state leakage). A test that fails-then-passes is tagged flaky and gets an issue/owner — **never silently retried into green** as a permanent state.

### D2. Early flake detection
- Add a CI step that runs **new/changed** tests several times before merge to catch flakiness early (replicate Datadog's "early flake detection" cheaply with a loop, or document enabling Datadog Test Optimization). A "fixed" flaky test is only un-quarantined after passing many reruns and the fix reaching `main`.

### D3. Trust dashboard
- Extend the `BUGS.md`/`GITHUB_STEP_SUMMARY` output (and optionally a small `autotest/reports/METRICS.md`) to publish: council precision/recall (from A5), open vs pending vs auto-closed counts, mean sweeps-to-confirm, mean sweeps-to-decay, flaky rate (target <2%), and suite pass rate (target 95–98%). This turns "is it working?" into numbers.

---

## 6. New / changed CI workflows (`.github/workflows/`)

- **`autotest.yml`** — wire in the new deterministic finders (a11y/visual/contract toggles), keep the read-only live sweep + fixer, and ensure the new `pending`/decay logic is reflected in the committed `BUGS.md`/`ledger.json`. Do **not** change the prod auto-merge arming yourself (§1).
- **`lighthouse.yml`** (new) — B4. **[Removed 2026-07-08 — see docs/adr/0021.]**
- **`contract.yml`** (new) or a step in the existing test workflow — B5 (Schemathesis).
- **Nightly cross-browser matrix** (new job or workflow) — B1. **[Removed 2026-07-08 — see docs/adr/0021.]**
- **Monitoring** — Upptime workflow **or** Checkly deploy step (C1), clearly separate from autotest. **[The Upptime workflow was removed 2026-07-08 — see docs/adr/0021.]**
- Keep every new workflow self-contained and using only official actions where possible (matches the repo's `responsive-design.yml` philosophy). Pin action versions.

---

## 7. Config flags to add (document all in `autotest/README.md`)

| Flag | Default | Effect |
|---|---|---|
| `AUTOTEST_CONFIRM_SWEEPS` | `2` | extra sweeps a *subjective* finding must recur before `pending → open` |
| `AUTOTEST_DECAY_SWEEPS_SUBJECTIVE` | `3` | absent sweeps before a subjective finding auto-closes |
| `AUTOTEST_DECAY_SWEEPS_DETERMINISTIC` | `6` | absent sweeps before a deterministic finding auto-closes |
| `AUTOTEST_FIX_REQUIRE_REPRO` | `1` | fixer must write a failing deterministic test before touching product code for a subjective finding |
| `AUTOTEST_A11Y` | `1` | axe-core accessibility pass |
| `AUTOTEST_VISUAL` | `1` | Playwright visual-snapshot regression |
| `AUTOTEST_CONTRACT` | `1` | Schemathesis API contract tests |
| `AUTOTEST_BROWSER` | `chromium` | `chromium`\|`firefox`\|`webkit` |
| `AUTOTEST_DEVICE` | _(unset)_ | optional Playwright device name for a mobile pass |

(Keep names consistent with the existing `AUTOTEST_*` family; honest-skip when a dependency is missing.)

---

## 8. Deliverables & PR checklist

- A branch + PR titled e.g. **"autotest: trust (pending/decay/judge-calibration) + coverage (a11y/visual/contract/x-browser) + external monitor"**, with a description that:
  - summarises the change per tier,
  - states the report's recommendation on **keeping prod auto-merge human until trust metrics are met**, and explicitly says you did **not** change the arming flag,
  - lists any **extra** items you implemented from your own reading of the report (per §0), each tagged with its tier and a one-line rationale.
- A new **`docs/autotest/AUTOTEST_CHANGES.md`** changelog: every file touched, why, which tier (A1…D3), and any follow-ups deferred.
- The report and this prompt moved into `docs/autotest/` and linked from `autotest/README.md`.
- Updated `autotest/README.md` (new flags table rows; "Benchmark & roadmap" link; brief note on the new finding lifecycle: `pending → open → fixing → fixed/verified-fixed`, plus `auto-closed`/`regressed`).
- Updated `requirements.txt`/`pyproject.toml` extras for any new Python deps (`schemathesis`, `pytest-rerunfailures`, `pytest-randomly`); Node devDeps for `@axe-core/playwright` if used.
- **All tests green.** `python -m autotest.run` still runs. `python -m autotest.metrics` runs. New CI workflows validate (`actionlint` if available).

### Do NOT
- Do not modify the product engine (parsers/detectors/ranker/PB/colour-science).
- Do not weaken/delete/skip tests, or disable existing safety nets.
- Do not enable auto-merge for your PR, or flip `AUTOTEST_BUILD_MERGE`.
- Do not let any new AI/monitoring step crash the sweep when a key/service is missing (honest-skip).
- Do not reduce or bypass the provenance/de-contamination guard — only extend it (A4).

---

## 9. Suggested execution order (commit-by-commit)

1. Move + link the two docs; create `docs/autotest/AUTOTEST_CHANGES.md` scaffold.
2. **Tier A1–A3** (lifecycle: `pending`/decay/regression in `report.py`) + schema bump + ledger migration; update `BUGS.md` renderer; verify "two runs don't grow open count".
3. **Tier A4** (unexercised-artifact suppression in `run.py` + `semantic.py`); verify signup-disabled produces no finding.
4. **Tier A6** (fixer corroboration gate in `fix_loop.py`/`gitops.py`).
5. **Tier A5** (per-advisor votes, calibration set, `metrics.py`, trust line).
6. **Tier B2 + B5** (a11y, contract — deterministic, pytest/CI-native) → **B3** (visual) → **B1** (x-browser/mobile) → **B4** (Lighthouse) → **B6** (auth isolation).
7. **Tier D1–D3** (flake control + dashboard).
8. **Tier C1–C2** (external monitor, separate pipeline).
9. Final: README/flags/docs, changelog, PR.

Land Tier A before B/C/D — trust first, then coverage. If you run low on time, a partial PR is fine **provided Tier A is complete and the suite is green**; defer the rest in `AUTOTEST_CHANGES.md` as a checklist.
