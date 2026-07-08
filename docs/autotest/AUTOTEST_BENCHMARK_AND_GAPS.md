# MediaHub Autotest: Public-Repo Benchmark & Implementation Report

## TL;DR
- **Your architecture is genuinely ahead of most public projects on adjudication (the adversarial council), provenance de-contamination, and the seeded golden-baseline oracle — but it is failing on the one thing that makes a QA tool trustworthy: signal-to-noise.** The fix is not more AI; it is borrowing the *finding-lifecycle discipline* that production tools (Sentry, Prometheus, Grafana, Datadog) and flaky-test platforms have already solved.
- **The highest-priority work is Tier A: confirm-on-repeat gating + decay/auto-close + config-artifact suppression in `autotest/report.py` and `semantic.py`.** Mature systems never open a subjective finding on a single sighting (Prometheus `for:`, Grafana "Pending period") and auto-resolve issues that stop recurring — Sentry's official onboarding guidance is verbatim "We recommend setting auto-resolve to 2 weeks for optimal issue and regression tracking." Your `merge_findings` does the opposite, which is why you have 62 open bugs that mostly don't reproduce.
- **A "paid human tester" also covers ground you don't: cross-browser/mobile, accessibility (axe-core), performance budgets (Lighthouse CI), API contracts (Schemathesis — Python-native), visual-regression baselines (Playwright `toHaveScreenshot`/Argos/Lost Pixel), and an external synthetic monitor (Checkly/Upptime) separate from your 6-hour CI.** These are all add-ons to your existing Playwright+pytest+Actions stack.

---

## Key Findings
1. **The noise problem is the trust problem.** Your council already filed a meta-finding that the framework flags "passed-empty"/"0 cards" as bugs — i.e., it knows it is over-flagging. Every mature system treats a single AI/subjective sighting as *pending*, not *open*.
2. **Nobody serious auto-merges LLM-judged findings to prod without a deterministic gate.** The strongest open-source SaaS suites (Cal.com, PostHog, Documenso) gate deploys on *deterministic* Playwright/Cypress E2E, not on LLM verdicts. LLM-judge testing is best used as a *triage/triage-assist* layer feeding human or deterministic gates.
3. **LLM judges are measurably unreliable unless calibrated and ensembled.** Schwinn et al. ("A Coin Flip for Safety," arXiv:2603.06594) found from "a comprehensive audit using 6642 human-verified labels [that] the unpredictable interaction of these shifts often causes judge performance to degrade to near random chance." The literature recommends calibration sets (estimate TPR/FPR), odd-panel majority voting, and precision-correction. Your council is a good instinct; it needs metrics and grounding.
4. **Your Chromium-only, no-a11y, no-perf, no-contract coverage is the gap a human tester fills.** All of these have first-class, CI-native, mostly free tooling that bolts onto your stack.
5. **Your 6-hour CI finder is not a synthetic monitor.** Real uptime/behavior monitoring runs every 1–5 min from outside your CI and pages you; that is a different discipline (Checkly, Upptime, Uptime Kuma, Grafana/k6).

---

## Details — Deliverable 1: Exhaustive, Categorized List of Public Repos/Projects

### Category 1 — End-to-end browser suites in real open-source SaaS (deterministic, deploy-gating)
These are the "human tester replacement done deterministically" exemplars. MediaHub-relevant because they show how serious projects structure, gate, and de-flake E2E.

- **Cal.com** — `github.com/calcom/cal.com`. Large Next.js SaaS; Playwright E2E lives in `apps/web/playwright/*.e2e.ts`, run in CI. Instructive: they tag and temporarily disable known-flaky specs (e.g., `workflow.e2e.ts`, issue #10640) rather than letting them block — a real-world flake-quarantine pattern. Very active, tens of thousands of stars.
- **PostHog** — `github.com/PostHog/posthog`. Playwright E2E (`hogli test:e2e`, `/playwright` dir) **plus** Storybook visual-regression via `@storybook/test-runner` + Playwright snapshots that auto-commit updated snapshots to the PR. Uses GitHub Actions to run Cypress, Jest, Django, and Storybook tests. Excellent model for combining functional + visual in CI.
- **Documenso** — `github.com/documenso/documenso`. Open-source DocuSign alternative with Playwright E2E. Honest exemplar of the *flaky-tests* failure mode (issue #2227: "Playwright tests are flaky") — useful to study how a small team struggles with the exact problem you have.
- **NocoDB** — `github.com/nocodb/nocodb`. Migrated Cypress→Playwright; tests in `tests/playwright`. Published a two-part engineering blog on Page Object Model, mandatory stress-testing of new tests before merge, and lint-enforced `await` — directly relevant to your `run.py` flow design.
- **Gitea** (`github.com/go-gitea/gitea`), **Medusa** (`github.com/medusajs/medusa`), **Chatwoot** (`github.com/chatwoot/chatwoot`), **Twenty** (`github.com/twentyhq/twenty`), **Ghost** (`github.com/TryGhost/Ghost`), **Supabase** (`github.com/supabase/supabase`), **Plane** (`github.com/makeplane/plane`), **Formbricks** (`github.com/formbricks/formbricks`), **Rocket.Chat**, **Mastodon**, **n8n** (`github.com/n8n-io/n8n`), **Sentry** (`github.com/getsentry/sentry`), **Grafana** (`github.com/grafana/grafana`) — all maintain serious E2E/integration suites wired into CI. Mixed languages; treat as strong general exemplars (Ghost and n8n use Playwright/Cypress respectively; Rocket.Chat and Chatwoot have long-standing E2E suites).
- **Playwright canonical CI patterns** — `playwright.dev/docs/ci-intro` and the generated `.github/workflows/playwright.yml`. The reference for `projects` (cross-browser), `retries: process.env.CI ? 2 : 0`, `trace: 'on-first-retry'`, and `forbidOnly`.

### Category 2 — Production/synthetic monitoring & "is my live site up and behaving" (distinct from CI)
- **Checkly / checkly-cli** — `github.com/checkly`. "Monitoring as code": write **standard Playwright `*.spec.ts`** that run on a schedule from 20+ global locations, collecting console logs, network, Web Vitals, and traces. Free Hobby tier (10,000 API + 1,500 browser check runs/month); native Playwright (no proprietary DSL). The single best model for "reuse your E2E as a production monitor." Distinct from your CI because it runs continuously and alerts (Slack/PagerDuty).
- **Upptime** — `github.com/upptime/upptime` (16,000+ stars). Pure **GitHub-Actions-native** uptime monitor + status page: cron every 5 min, opens a GitHub Issue when a URL is down, auto-closes when back up, commits response-time history to git. Zero server. Closest thing to "your stack, but for uptime." Used by Canonical and WakaTime among 3,000+ teams.
- **Uptime Kuma** — `github.com/louislam/uptime-kuma`. Self-hosted, fancy UI, HTTP/TCP/DNS/keyword checks, Prometheus metrics endpoint, 50+ notifiers. The default self-hosted choice.
- **Gatus** — `github.com/TwiN/gatus`. Declarative YAML health checks with conditions on status/body/latency; great for "behaving," not just "up."
- **Statping-ng** — `github.com/statping-ng/statping-ng`. Status page + uptime; polished public status pages.
- **Grafana k6** (`github.com/grafana/k6`) + **Grafana Synthetic Monitoring**, and **Prometheus Blackbox Exporter** (`github.com/prometheus/blackbox_exporter`) — probe HTTP/TCP/DNS/ICMP and expose metrics; pair with Grafana alerting.

### Category 3 — AI/LLM-driven & self-healing autonomous testing agents (your peer group)
- **Skyvern** — `github.com/Skyvern-AI/skyvern` (Python, ~13k+ stars). Vision+LLM swarm over Playwright; resilient to layout changes because it maps *visual* elements to actions (no fixed selectors). Reports best-in-class results on WRITE/RPA flows (form-filling); weaker on deterministic regression. Borrow: vision-grounded element actions for your flow steps.
- **Stagehand** — `github.com/browserbase/stagehand` (~21k stars). `act()/extract()/observe()/agent()` over Playwright; **auto-caching + self-healing** so repeated flows run with zero LLM inference until the page changes. Borrow: cache deterministic actions, only invoke AI on change — directly attacks your cost/nondeterminism.
- **browser-use** — `github.com/browser-use/browser-use` (Python). Largest community; high-level LLM→browser task interface. Borrow: task-planning ergonomics.
- **TestZeus Hercules** — `github.com/test-zeus-ai/testzeus-hercules` (Python, AGPL, ~900+ stars). "World's first open-source testing agent": UI/API/**accessibility**/security/visual from plain-English Gherkin; Docker-native, CI-ready; emits JUnit XML + HTML report + **video/screenshot/network proofs**; auto-healing. The closest *philosophical* peer to your autopilot — and it already does a11y/API/visual you lack. Borrow: proof-bundle per finding (video+network+screenshot) for trustable bug reports.
- **Midscene.js** — `github.com/web-infra-dev/midscene` (vision-driven, `aiAssert()`/`aiQuery()`/`aiWaitFor()`; multi-platform). Borrow: `aiAssert`-style semantic assertions with screenshot grounding.
- **Shortest** (`github.com/antiwork/shortest`, ~5.5k stars) — natural-language E2E on Playwright via Claude's computer-use; note the community's key critique (Discussion #340): it's great for *sanity checks* but "not that useful to use for E2E tests on CI/CD, due to the lack of determinism" — exactly the trap your fixer must avoid. Borrow the *lesson*, not the auto-merge.
- **LaVague** (`github.com/lavague-ai/LaVague`) incl. **LaVague-QA** (Gherkin→tests), **Auto-Playwright** (`github.com/lucgagan/auto-playwright`), **ZeroStep** — NL-driven action layers.
- **Self-healing locators:** **Healenium** (`github.com/healenium/healenium`, Java/Selenium; ML tree-comparison locator healing; has Playwright examples) and the Python port **autoheal-locator** (`github.com/SanjayPG/autoheal-locator-python`, Selenium+Playwright, pytest fixture, caches AI fixes so AI is called once per broken selector). Borrow: cache-the-heal pattern + only-call-AI-on-failure.

### Category 4 — Visual-regression frameworks (for your VLM `vision.py` job)
- **Playwright built-in `toHaveScreenshot()`** — `playwright.dev/docs/test-snapshots`. Zero-extra-dependency pixel diffing (pixelmatch), `maxDiffPixelRatio`, `animations:'disabled'`, `stylePath` masking, per-browser/platform baselines. **Start here** — it's already in your stack.
- **Argos** — `github.com/argos-ci/argos`. Open-source visual platform; plugs into Playwright; compares screenshots **and ARIA snapshots**, PR status checks, built-in stabilization to cut flaky noise, plus flaky-management. Pixel-diff (cost-predictable).
- **Lost Pixel** — `github.com/lost-pixel/lost-pixel`. Open-source Percy/Chromatic/Applitools alternative; GitHub Action; per-screenshot thresholds, `excludeSelectors` masking, multi-browser.
- **BackstopJS** (`github.com/garris/BackstopJS`) — mature, MIT, scrubber HTML report across breakpoints. **reg-suit/reg-cli** (`github.com/reg-viz/reg-suit`) — best pure comparison + S3/GCS baselines + PR comments. **Loki** for Storybook.

### Category 5 — Accessibility, performance, and API-contract testing in CI
- **axe-core** — `github.com/dequelabs/axe-core` (the engine inside Lighthouse a11y). **@axe-core/playwright** drops directly into your sweep. **pa11y / pa11y-ci** (`github.com/pa11y/pa11y-ci`) — CLI a11y with WCAG2AA, sitemap crawl, fails PRs.
- **Lighthouse CI** — `github.com/GoogleChrome/lighthouse-ci` + Action `treosh/lighthouse-ci-action`. `lhci autorun`, assertions/budgets (`budget.json`), `numberOfRuns: 3` (median) to fight perf-noise, fails build on regressions. Note the documented caveat that perf metrics are noisy on shared CI runners — assert *scores/budgets/a11y*, warn (not error) on raw timings.
- **Schemathesis** — `github.com/schemathesis/schemathesis` (**Python, pytest-native**). Property-based API testing from OpenAPI/GraphQL; `schema.parametrize()`, stateful workflows, `from_asgi`/`from_wsgi` for Flask, GitHub Action `schemathesis/action@v2`. Used by Spotify/Red Hat/WordPress/JetBrains. Its peer-reviewed pedigree is strong: Hatfield-Dodds & Dygalo, ICSE 2022 ("Deriving Semantics-Aware Fuzzers from Web API Schemas," arXiv:2112.10328) reported it "identified a total of 755 bugs in 16 services, finding between 1.4× to 4.5× more defects than the second-best tool," and it was "the only tool to handle more than two-thirds of our target services without a fatal internal error." **This is the most directly droppable contract tool for your `/api` routes.**
- **Dredd** (`github.com/apiaryio/dredd`), **Pact** (`github.com/pact-foundation`), **Postman/newman**, **Schemathesis+Pact bi-directional** (PactFlow examples) — alternatives/complements for consumer-provider contracts.

### Category 6 — Flaky-test management & test-quality tooling (for "noise never ages out")
- **Playwright native**: `retries`, `trace:'on-first-retry'`, `--fail-on-flaky-tests` (CLI since v1.45; config `failOnFlakyTests:true` since v1.52), `@flaky` tag + `--grep-invert @flaky` to run quarantined tests in a separate non-blocking job.
- **Datadog Test Optimization** — Early Flake Detection retries new tests "up to ten times," and per Datadog's docs "A study shows that up to 75% of flaky tests can be identified with this approach" (their blog adds "over 70% of flaky tests exhibit flaky behavior when they're first introduced"). Auto Test Retries default: "retry any failing test case up to 5 times" (`DD_CIVISIBILITY_FLAKY_RETRY_COUNT` default 5). Flaky Tests Management adds quarantine/disable, a verbatim "14-day grace period [that] applies to every flaky test with a successful fix after using the remediation flow," auto-policies that can disable a test "if it remains unfixed after 30 days," and a remediation flow that retries a "fixed" test 20× and only marks Fixed on merge. The richest model for your ledger states.
- **Datadog Synthetic Monitoring** — fast-retries + "minimum duration" before alerting; only the *final* retry counts in evaluation; "self-healing" locators recompute on success. The canonical "distinguish flake from regression" reference.
- **pytest plugins (your stack):** **pytest-rerunfailures** (`--reruns`), **pytest-randomly** (order randomization to surface state leakage), **flaky**. Also **BuildPulse**, **Trunk Flaky Tests**, **Mergify CI Insights** (auto-quarantine when a confidence score drops, auto-lift when main recovers).

---

## Details — Deliverable 2: Gap Analysis + Prioritized Implementation Report

### TIER A — Remove the false-positive/noise problem (HIGHEST PRIORITY: this is what makes the tool trustworthy)

**A1. Confirm-on-repeat gating before a subjective finding becomes "open."**
*Gap:* `merge_findings` opens AI/subjective findings on a single sighting, so cold-run artifacts ("0 cards") become HIGH bugs.
*Who does it well:* **Prometheus** `for:` clause — an alert stays *pending* and only *fires* after the condition persists across evaluations: "Prometheus will check that the alert continues to be active during each evaluation for [the configured duration] before firing… Elements that are active, but not firing yet, are in the pending state" (default `for: 0s`). **Grafana** "Pending period" keeps an instance Pending "until the condition has been continuously true for the entire Pending period… [which] ensures the condition breach is stable before the alert transitions to the Alerting state." **Datadog Synthetics** requires failures to persist for a "minimum duration" before alerting.
*Concrete change:* In `report.py`, add a `pending` status. A finding from `semantic.py`/`vision.py`/`council.py` enters `pending` and only transitions to `open` after it recurs in **N≥2–3 consecutive sweeps** (deterministic oracle failures may go straight to `open`). Add `confirmations` and `first_pending_sweep` fields to the ledger fingerprint record.

**A2. Decay / auto-close after N consecutive absences.**
*Gap:* You deliberately never auto-close a non-reproducing finding, so noise accumulates (62 open / 18 high, many "not reproduced in latest run").
*Who does it well:* **Sentry** auto-resolve via the `resolveAge` project field ("Automatically resolve an issue if it hasn't been seen for this many hours. Set to 0 to disable auto-resolve"), with the official onboarding recommendation, verbatim: "We recommend setting auto-resolve to 2 weeks for optimal issue and regression tracking." **Grafana** "Keep firing for" introduces a *Recovering* state to avoid flapping before resolving.
*Concrete change:* In `merge_findings`, if a finding is not reproduced for **K consecutive sweeps** (e.g., K=3 for subjective; longer for deterministic), transition `open → auto-closed (decayed)`. Keep the record (don't delete) so a recurrence reopens it.

**A3. Regression-aware reopening (don't lose real bugs to decay).**
*Who does it well:* **Sentry** regression detection — "A regression happens when the state of an issue changes from Resolved back to Unresolved"; a recurring resolved issue lands in the "For Review"/"Regressed" (`is:regressed`) tab; comparison uses release version (semver) or release date.
*Concrete change:* When a fingerprint that is `fixed`/`verified-fixed`/`auto-closed` recurs, set status `regressed` and surface it at the top of `BUGS.md` with the prior fix's commit/PR — this directly strengthens your existing `needs-disproof` state.

**A4. Stop feeding intentionally-unexercised artifacts to judges.**
*Gap:* With `AUTOTEST_SIGNUP=0`, `signup_text` is empty *by configuration*, yet `user_brain` flags the empty page HIGH.
*Concrete change:* In `run.py`/`semantic.py`, attach an explicit `exercised: bool` (or `skipped_reason`) to every captured artifact. The judge dispatch must **skip any artifact where `exercised=False`** and must never construct a "you are the user looking at this page" prompt from an unexercised flow. This is an extension of your existing provenance scheme (RENDERED_PAGE vs TESTER_CONTROL) — add a `NOT_EXERCISED` provenance class that is judge-ineligible.

**A5. Calibrate and ensemble the judges; measure precision/recall.**
*Gap:* The council adjudicates but you have no ground-truth measurement of its error rate, so you can't tell improvement from noise.
*Who does it well / evidence:* The "Noisy but Valid" framework (Feng et al., arXiv:2601.20913, ICLR 2026) uses "a small human-labelled calibration set to estimate the judge's True Positive and False Positive Rates (TPR/FPR)" and derives "a variance-corrected critical threshold," explicitly treating "judge outputs as noisy labels" rather than ground truth (it warns the alternative is "a form of 'blind trust' rather than statistical rigor"). **ChainPoll / panel voting** (Friel & Sanyal, arXiv:2310.18344; Galileo's recommendation to "Run three judges. Require two out of three to agree") filters single-sample variance — ChainPoll reported an aggregate AUROC of 0.781, "beating the next best theoretical algorithm by 11%." Conversely, the "Coin Flip for Safety" audit (arXiv:2603.06594) shows judges can degrade "to near random chance" under distribution shift, and a separate paper (arXiv:2602.09341) warns majority voting can fail when agent errors aren't independent ("confabulation consensus").
*Concrete change:* (1) Maintain a committed, human-labeled calibration set of ~50–100 past findings labeled real/noise; compute the council's precision/recall each release and **gate council changes on precision not regressing** (mirrors your golden-baseline discipline). (2) Keep the 5-advisor council but record per-advisor votes and require an explicit majority + chairman rationale; (3) report a "trust score" (precision) in `BUGS.md` so a human knows how much to trust open findings. Per the "Coin Flip" method, you can also **scale a finding's confidence by the judge's measured precision** before opening it.

**A6. Gate the auto-fixer on deterministic evidence, not LLM verdicts alone.**
*Gap:* Auto-merge-on-green is risky if the triggering "bug" is an LLM false positive.
*Who does it well:* Cal.com/PostHog/Documenso gate deploys on deterministic E2E; Shortest's own community notes LLM tests are "not that useful to use for E2E tests on CI/CD, due to the lack of determinism."
*Concrete change:* Require the fixer to only act on findings that are either (a) deterministic-oracle failures, or (b) subjective findings that passed A1 (confirmed N sweeps) **and** are corroborated by a deterministic reproduction the fixer first writes as a failing pytest/Playwright test. Keep auto-merge **off** for anything touching protected-engine/governance paths (you already do this) and consider human-merge-only as the default for prod.

### TIER B — Coverage gaps a human tester would catch

**B1. Cross-browser + mobile viewports.** *Gap:* Chromium-only. *Borrow:* Playwright `projects` (Firefox, WebKit, `devices['iPhone 13']`, `Pixel 7`). *Change:* add `firefox`, `webkit`, and 1–2 mobile projects to your Playwright config; run the smoke/primary flow across all on the schedule, full matrix nightly. **[The nightly CI matrix built from this was removed 2026-07-08 — see docs/adr/0021; the local `AUTOTEST_BROWSER`/`AUTOTEST_DEVICE` browser-select capability is retained.]**

**B2. Accessibility.** *Gap:* none today. *Borrow:* **@axe-core/playwright** (and/or pa11y-ci WCAG2AA). *Change:* in `run.py`, after each rendered page, run axe and emit violations as a *new deterministic finding class* (`a11y`) with severity from axe impact — these are deterministic, so they bypass A1 gating.

**B3. Visual regression baselines.** *Gap:* your VLM is great for novel defects but has no stable baseline, contributing to nondeterminism. *Borrow:* **Playwright `toHaveScreenshot()`** for committed baselines of home/review pages (with `animations:'disabled'`, masking dynamic captions/timestamps), optionally **Argos** or **Lost Pixel** for a review UI + ARIA snapshots. *Change:* keep the VLM as the "novel defect" judge **but** add deterministic snapshot assertions as the regression backbone; this gives you a human-blessed visual golden baseline analogous to your `baseline.py`.

**B4. Performance / Core Web Vitals budgets.** *Borrow:* **Lighthouse CI** + `treosh/lighthouse-ci-action`, `budget.json`, `numberOfRuns:3`. *Change:* assert a11y/best-practices/SEO scores and resource budgets as errors; treat raw timing metrics as *warnings* (documented CI noise). Run against the live Render URL. **[The Lighthouse CI job built from this was removed 2026-07-08 — see docs/adr/0021.]**

**B5. API contract/schema testing for `/api`.** *Borrow:* **Schemathesis** (Python/pytest-native, `from_wsgi` for Flask). *Change:* generate an OpenAPI spec for your Flask API (if not present), add `schema.parametrize()` tests to the pytest suite; these find 5xx/serialization/validation bugs deterministically and feed straight into the oracle, not the judges.

**B6. Auth/role/multi-tenant isolation.** *Gap:* org-pin flow is exercised but cross-tenant leakage isn't asserted. *Borrow:* Playwright `storageState` per role + explicit negative tests. *Change:* add tests that authenticate as Org A and assert Org B's resources return 403/404 (deterministic findings).

### TIER C — Monitoring & reliability of the live site (distinct from the 6-hour CI)

**C1. External synthetic monitor at 1–5 min cadence.** *Gap:* your finder runs every 6h inside CI; that's not uptime/behavior monitoring. *Borrow:* **Checkly** (reuse your Playwright specs as monitors, alerts to Slack/PagerDuty, Web Vitals, traces) or, to stay GitHub-native and free, **Upptime** (5-min cron, opens/closes GitHub Issues, status page) or self-hosted **Uptime Kuma**. *Change:* deploy a Checkly monitor of the primary login + a lightweight health endpoint; keep it separate from the bug-finding/fixing pipeline so monitoring noise never reaches the fixer. **[The Upptime monitor built from this was removed 2026-07-08 — see docs/adr/0021.]**

**C2. Status/incident hygiene.** Use the monitor's native issue/alert flow (Upptime auto-opens/closes issues; Checkly→PagerDuty) rather than your `notify.py` for *uptime* events, reserving `notify.py` for confirmed functional bugs.

### TIER D — Test-suite health, evals, and metrics

**D1. Flake quarantine + retry in the pytest/Playwright suite.** *Borrow:* Playwright `retries:2` in CI + `trace:'on-first-retry'`, `@flaky` tag with a separate non-blocking job; **pytest-rerunfailures** + **pytest-randomly** for your ~2837 pytest tests. *Change:* a test that fails-then-passes is tagged flaky, runs in a non-blocking job, and opens a ticket with an owner — never silently retried into green.

**D2. Early flake detection + remediation flow.** *Borrow:* **Datadog Test Optimization** model (or replicate cheaply): run new/changed tests multiple times to detect flakiness *before* merge (Datadog finds up to 75% of flakes this way; over 70% flake on first introduction); mark a "fixed" flaky test as truly fixed only after it passes many reruns and the fix reaches main.

**D3. Trust metrics dashboard.** Track and publish in `BUGS.md`/CI summary: council precision/recall vs the calibration set, open-finding count by status, mean sweeps-to-confirm, mean sweeps-to-decay, flaky rate (target <2%), and pass rate (target 95–98%). These convert "is the tool working?" from vibes to numbers.

---

## What MediaHub already does as well as or better than most public projects
- **Adversarial "LLM council" adjudication** (5 advisors → anonymized peer review → chairman, anti-sycophancy) is *more* sophisticated than the single-judge or simple-majority designs in most open-source AI testers (Shortest, Auto-Playwright). It aligns with the literature's "panel + consensus" recommendation (ChainPoll, "2-of-3 judges") — you just need calibration/metrics around it.
- **Artifact-provenance / de-contamination** (RENDERED_PAGE vs TESTER_CONTROL vs TESTER_SUMMARY so a control token can't reach a "you are the user" judge) is a genuinely advanced safeguard most projects lack entirely; extending it with a `NOT_EXERCISED` class closes the config-artifact hole.
- **Seeded deterministic regression oracle + committed, human-blessed golden baseline that is never auto-advanced** is exactly the discipline that LLM-heavy testers (Skyvern, Hercules, Midscene) lack, and it mirrors best practice (Sentry/Datadog never trust a single signal; their whole design is built around persistence and calibration).
- **Guarded auto-fix loop** (kill switch, protected-engine aborts, scope caps, iterate-to-green, attempt-cap→issue) is more safety-conscious than typical auto-fix bots, and more disciplined than the "fire-and-forget" agents.

## Opposing views where experts disagree
- **Autonomous auto-merge-to-prod:** Proponents (the autopilot/self-healing camp — Skyvern, Hercules, Stagehand) argue agents should close the loop and self-heal. Skeptics — including the Shortest community's own conclusion that LLM tests lack the determinism for CI gating — argue auto-merge should require deterministic corroboration and that prod merges stay human. **My recommendation sides with the skeptics for prod:** auto-fix on a branch + deterministic green gate, human merge for anything user-facing.
- **Is LLM-judge testing reliable enough to gate releases?** Optimists point to ChainPoll-style consensus (AUROC 0.781, +11% over the next best) and calibration making judges usable. Pessimists show judges near "random chance" under distribution shift (arXiv:2603.06594) and that majority voting can fail when errors correlate (arXiv:2602.09341). **Net:** use judges to *find and triage*, use deterministic oracles/contract/visual tests to *gate*.

---

## Recommendations (staged, with thresholds that change them)
1. **Sprint 1 (trust): Tier A1–A4.** Add `pending`/confirm-on-repeat (N=2–3), decay/auto-close (K=3), regression reopening, and `NOT_EXERCISED` provenance. *Threshold to proceed:* open-finding count drops and "not reproduced" findings stop accumulating.
2. **Sprint 2 (measure): A5–A6.** Build the human-labeled calibration set; publish council precision/recall; gate the fixer on deterministic corroboration. *Thresholds:* council precision ≥0.8 before you trust auto-triage; if <0.6 (coin-flip territory), demote judges to advisory-only.
3. **Sprint 3 (coverage): B1–B6**, starting with axe-core (B2) and Schemathesis (B5) since they're deterministic and pytest-native, then Playwright visual baselines (B3), cross-browser/mobile (B1), Lighthouse (B4), auth isolation (B6).
4. **Sprint 4 (monitor + health): C1–C2, D1–D3.** Stand up a Checkly/Upptime external monitor; add flake quarantine + trust dashboard.
5. **Re-evaluate auto-merge-to-prod** only after the trust dashboard shows sustained council precision ≥0.85 and flaky rate <2% for several weeks; otherwise keep prod merges human.

## Caveats
- Several "best tool" comparisons and star/maintenance notes come from vendor blogs (Checkly, Datadog, Galileo, Argos, Lost Pixel) and tool-roundup sites; treat capability claims from a tool's own marketing with appropriate skepticism. Official docs were used for mechanism specifics (Playwright, Prometheus, Grafana, Sentry, Datadog, Schemathesis).
- Some LLM-judge reliability papers are recent preprints; "A Coin Flip for Safety" has a minor internal label-count discrepancy (6642 vs 6442 in different sections) and is focused on adversarial-robustness eval, which is a harder setting than functional QA — its "coin flip" figure is a cautionary upper bound on judge unreliability, not a measurement of your council.
- Star counts and "active/maintained" status drift; verify current numbers on each repo before committing.
- The auto-merge-to-prod recommendation is a judgment call; teams with strong deterministic gates and low blast-radius deploys reasonably choose more automation.
