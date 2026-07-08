# ADR 0021 — Cull the GitHub bots that never delivered; sharpen the ones that do

- **Status:** accepted (2026-07-08) — operator directive: *"critically evaluate
  the bots on my github repo, improve the ones that can work properly, but fully
  delete the ones that will never work to the level I want."*
- **Context:** the repo had accumulated a dozen GitHub Actions. Several were
  "green but hollow" — they ran without error yet produced nothing anyone acted
  on. Each bot was evaluated on three axes: *does it run green*, *does it deliver
  real value*, and *can its stated goal ever be reached in this hosted CI setup*
  (a green badge is not evidence of value — `autotest.yml` is deliberately built
  to stay green even when its fix pass crashes). Evidence: workflow run history,
  the PRs/issues each bot actually opened and merged, and the live
  `autotest/state` ledger.

## Decision

**Delete three bots that never reached, and cannot reach, a useful level; keep
and sharpen the rest.**

### Removed

1. **Autotest cross-browser matrix** (`autotest-crossbrowser.yml`). A nightly
   Firefox/WebKit/mobile sweep whose findings were artifact-only. In 30+ nights
   it produced **no acted-upon output**: no consumer, no triage path, no issues
   filed. It is a ~278-line-per-engine-per-night firehose whose cross-engine
   tagging also defeats the read-only dedup baseline, so a real WebKit-only
   regression is indistinguishable from recurring noise; and with
   `AUTOTEST_SIGNUP=0` it only inspects the unauthenticated surface, so its
   incremental coverage over the 6-hourly chromium finder is near-zero on the
   flows that matter. Turning it into signal is a rebuild, not a tweak.
   *Note:* `run.py` keeps its `AUTOTEST_BROWSER` / `AUTOTEST_DEVICE` multi-engine
   support (a real, working capability for optional local runs) — only the
   scheduled bot is removed.
2. **Lighthouse CI** (`lighthouse.yml`, `.github/lighthouse/`). Green 36/36 but
   35+ nights of zero actionable output: not a required gate, no token to post a
   status check or open an issue, reporting to an ephemeral URL nobody reads. Its
   a11y/best-practices/SEO coverage duplicates the 6-hourly autotest finder's
   axe-core pass; its perf/Core-Web-Vitals half is inherently unreliable against
   a Render free-tier URL that cold-starts. Redundant with a monitor we keep.
3. **Upptime uptime monitor** (`upptime.yml`, `.upptimerc.yml`, `monitoring/`). A
   correctly-built but permanently-inert scaffold: schedule commented out, every
   step gated on a `GH_PAT` secret that was never set. Zero monitoring for 30+
   days. Enabling it needs an operator-only secret; the 6-hourly autotest finder
   already exercises the live site, so a hard-down would not go fully unnoticed.

### Kept and sharpened

- **Autonomous tester — FINDER half: keep.** It drives Playwright + axe-core + AI
  judges + the LLM council against the live site every 6h, maintains a real
  ledger with a confirm→decay lifecycle, and surfaces genuine functional defects.
  It is also load-bearing beyond testing: `autotest/skills/llm-council` backs the
  repo's `/llm-council` governance skill.
- **Autonomous tester — FIXER half: keep, reframed.** ~18 real merged fixes is a
  legitimate track record, but per [ADR-0020](0020-no-autotest-automerge.md) it
  is permanently human-reviews-every-PR: it is a **human-approved PR drafter**,
  not an autonomous fixer, and that is the correct posture — not a bug to fix.
  Two changes stop its recent value-leak (all four July PRs were throwaway
  "document 502" notes about Render cold-starts):
  - `autotest/fix_loop.py:_is_transient_5xx` — a gateway 5xx (502/503/504) is the
    hosting layer, not product code the coder can fix, so it is excluded from the
    fix queue (a genuine 500 stays eligible; the finding still appears in the
    ledger for human visibility). Guarded by `tests/test_autotest_transient_5xx.py`.
  - `autotest.yml` gains a warm-up step that pings `/healthz` until the instance
    answers before the sweep, so a cold-start 5xx is not filed as a finding in the
    first place.
- **Roadmap auto-update: keep as-is.** The healthiest bot in the repo — 365 PRs
  opened and merged, 0 stuck, 0 failures. Mechanical, idempotent docs edits.
- **Dependabot auto-merge (Actions bumps): keep.** Merges only `github_actions`
  version bumps on all-green checks (blast radius is CI itself). Sharpened to pass
  `[skip render]` on the merge-commit subject so an Actions-only bump no longer
  triggers a pointless Render redeploy.
- **CI test gates** (`unit-suite`, `security`, `repo-hygiene`, `contract`,
  `responsive-design`, `motion-visual-regression`): keep — sound, maintainable
  gates. Fixed a dead doc link in the responsive summary.

## Consequences

- CI Actions-minutes drop (three scheduled/nightly jobs removed), advancing part
  of ROADMAP RP.2's pre-private-flip CI trim.
- The repo loses Firefox/WebKit/mobile CI coverage and Lighthouse perf/SEO
  budgets. Both currently produced only unread output; revisit with a real triage
  path (issue-opener + per-engine baseline) if cross-engine testing becomes a
  priority. External uptime monitoring can be reintroduced by re-enabling Upptime
  (operator adds a pinned-action `GH_PAT`) if wanted.
- No product runtime code changed; the deterministic engine is untouched.

## Known follow-up (not done here)

- `contract.yml`'s Schemathesis property-fuzz (`test_schemathesis_finds_no_server_errors`)
  silently skips on every run since the pin moved to Schemathesis 4.x (the test
  targets the 3.x API). The deterministic no-5xx smoke still runs and delivers.
  Either port the test to the 4.x loader or drop the fuzz and rename the workflow;
  left as-is here because it needs a Schemathesis-4.x environment to verify.
