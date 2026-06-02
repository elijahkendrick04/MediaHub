# MediaHub Autopilot — autonomous tester + fixer

Two cooperating halves that test the product, find bugs, and turn them into fix
PRs on their own — **fully autonomous and cloud-based, running in GitHub
Actions** (no desktop, no Cowork). A headless browser does real uploads/downloads
inside the runner, so nothing needs to "escape a sandbox".

**Cloud setup (this is the engine):**
1. Add **one** repo secret: **`CLAUDE_CODE_OAUTH_TOKEN`** — generated once with
   **`claude setup-token`** from a **Claude Pro/Max subscription**. That single
   token powers the WHOLE loop (subagents, council, fixer) via the Claude CLI —
   **no API keys anywhere, flat cost, no metered billing**. No token → the AI
   judges + fix steps skip cleanly, so nothing runs wild until you arm it. On
   repeated failure the loop **opens a GitHub issue and stops** (capped attempts)
   instead of wasting subscription quota.
   *(Prefer the free-tier Gemini coder/judges instead? Set `AUTOTEST_CODER=gemini`
   and the relevant API key — but the default is API-key-free.)*
2. Settings → General → enable **Allow auto-merge**, and allow the actions bot
   to merge to `main` (loosen branch protection / required reviews as needed).
   **Also let the loop open PRs**, or its fixes have nowhere to land: either
   Settings → Actions → General → tick **"Allow GitHub Actions to create and
   approve pull requests"**, **or** add an **`AUTOTEST_GH_PAT`** secret (a
   fine-grained PAT with `pull_request: write` + `contents: write`) — the
   workflow prefers it over `GITHUB_TOKEN`, and a PAT-opened PR also triggers CI
   so `--auto` merge can actually fire. Without one of these, `gh pr create`
   is denied, the loop reports `fix-pushed-no-pr` (branch pushed, **not** merged)
   and notifies you — it no longer silently claims success.
3. That's it. `.github/workflows/autotest.yml` (every 6h) finds + reports bugs,
   commits `BUGS.md` + `ledger.json` back to `main` so the dedup memory persists,
   then runs the fixer to turn new bugs into fix PRs (auto-merged on green CI when
   armed).

The `loop.py` "run forever" driver below is an OPTIONAL always-on worker (e.g. a
cloud VM) if you ever want continuous rather than scheduled — the cloud default
is the scheduled workflow.

```
                ┌──────────────── TESTING loop (autotest.loop / autotest.run) ───────────┐
  boot app → drive real flow + crawl → deterministic detectors ┐                         │
                                                               ├→ semantic subagents ┐   │
                                                               ├→ vision judge       ├→ LLM Council
                                                               ┘  (adjudicates)      ┘   │
  → BUGS.md (deduped, fix-ready) ──────────────────────────────────────────────────────►│
                                                                                          │
                ┌──────────────── FIXER loop (autotest.fix_loop) ────────────────────────▼─┐
  read ledger → pick top open bug → Claude coder fixes it on a branch → guards + test gate →
                regression-proof → commit + PR → (armed) auto-merge to main on green CI ────┘
```

The two share their git/PR/test-gate plumbing through `autotest/gitops.py` (the
neutral change-landing harness: implement-to-green → protected-engine + scope
guards → product-vs-harness classification → open PR → arm CI-gated auto-merge).

## Optional: run it locally (the cloud workflow is the default)

These are the same single-shot entrypoints the workflow calls — handy for a
local smoke test or an always-on worker. The cloud needs none of this.

```bash
# 1) put your key in a gitignored .env (NEVER hard-code it anywhere):
echo 'GEMINI_API_KEY=...' >> .env

# 2) constant testing (find bugs, write BUGS.md, judge with subagents+council):
python -m autotest.loop

# 3) one-off sweep instead of the loop:
python -m autotest.run

# 4) autonomous bug fixing (bugs -> claude -> PR; arm prod merge separately):
python -m autotest.fix_loop
```

The bug report lands in **`autotest/reports/BUGS.md`** — deduped and written so a
Claude Code session can fix an entry just by reading it (repro, expected/actual,
evidence, suspected `file:line`, screenshot). Paste a section into Claude Code,
or let `autotest.fix_loop` do it.

## The key — env/.env only, never hard-coded

The Gemini/Anthropic key is read from the environment (loaded from the gitignored
`.env` by `autotest/_env.py`). It is **never** written into source, tests,
commits, or logs. Rotate it by editing `.env` alone. With no key, the AI layers
(semantic subagents + council + vision judge) skip cleanly and the deterministic
finder still runs.

## The intelligence layer

- **Deterministic finder** — 5xx, server tracebacks, JS/console errors, broken
  links, failed sub-requests, flow failures. Treats expected behaviour
  (AI-unconfigured, the 409 no-org guard, soft-404 recovery pages, gracefully
  rejected uploads) as **not** bugs.
- **Semantic subagents** (`semantic.py`) — three AI personas judge *meaning*:
  *is it doing what it should* (functional), *is the output correct* (captions
  grounded, confidence sane), and *does it work how a user would want*
  (user-brain). Dispatched in parallel.
- **Vision judge** (`vision.py`) — looks at the *rendered* review/home
  screenshots for **visual defects** the deterministic finder and the text-only
  semantic judges are blind to: a logo/photo that 404'd into a broken-image box,
  a caption clipped out of its card, an error banner painted over the page, an
  empty review screen, illegible contrast. It runs on MediaHub's existing
  `media_ai.llm` vision capability (Gemini→Anthropic) — **no GPU, no new
  runtime**, honest-skip with no key. The VLM *looks and reports*; it never
  drives the UI and never decides a swim time / PB (that stays in the
  deterministic engine). Toggle with `AUTOTEST_VISION` (default `1`).
- **LLM Council** (`council.py`, embedding the vendored `skills/llm-council`) —
  5 adversarial advisors → anonymised peer review → chairman verdict. It
  **adjudicates** the subagents' findings: confirms real bugs, demotes noise,
  surfaces blind spots. Anti-sycophancy, so the ledger stays clean. Full
  transcript + HTML report under `autotest/reports/council/`.

## Safety nets & flags

The operator chose **full auto-merge to `main`** for product fixes (overriding
the council's advice for a human gate). These are therefore the only things
between a bad AI change and production, and they are strict:

| Net | Behaviour |
|---|---|
| Kill switch | `touch autotest/STOP` halts the loop immediately |
| Protected paths | a fix touching the deterministic engine (parsers, detectors, ranker, colour-science) aborts before merge |
| Self-governance gate | a fix is classified 3 ways (`CHANGE_CLASSIFICATION.md`, council 2026-06-02): **product** + ordinary **harness** code auto-merge on green CI; a **self-governance** change (the files that govern the loop — `gitops.py`/`fix_loop.py` merge+guard logic, the `STOP` kill switch, the classifier, CI/deploy/deps, governance docs, the tripwire) stops for a HUMAN merge. Enforced in-repo (`classify_change` + `tests/test_autonomy_tripwire.py`) AND platform-side (branch protection + `.github/CODEOWNERS`, bot token without bypass — the real stop) |
| Scope cap | `AUTOTEST_BUILD_MAX_FILES` (25) / `AUTOTEST_BUILD_MAX_INSERTIONS` (2000) |
| Test gate | the full suite must stay green or nothing merges |
| Iterate-to-green | a gate failure is fed back to the coder to fix the ROOT CAUSE (repo skills), up to `AUTOTEST_GATE_MAX_ITERS`, then it stops — it may not delete/weaken tests to pass |
| Regression-proof | the fix's new test must fail on pre-fix source and pass after (`gitops.prove_regression`); advisory by default, hard-blocking under `AUTOTEST_REQUIRE_REGRESSION_PROOF=1` |
| Attempt cap | after `AUTOTEST_FIX_MAX_ATTEMPTS` failed tries on one bug the loop opens a GitHub issue and de-prioritises it (never silently drops it) |

| Flag | Default | Effect |
|---|---|---|
| `AUTOTEST_FIX_APPLY` | `1` | run the bug-fixer (`0` = list only) |
| `AUTOTEST_BUILD_MERGE` | `0` | **arm** CI-gated auto-merge of fix PRs to `main` (full auto to prod). One flag from hands-off |
| `AUTOTEST_CODER` | `claude` | coding agent: `claude` (best quality, no fallback) or `gemini` |
| `AUTOTEST_FIX_MAX_ATTEMPTS` | `2` | give up + open a GitHub issue after N failed fix tries (credit guard) |
| `AUTOTEST_GATE_MAX_ITERS` | `3` | when a change fails the test gate, feed the failure back to the coder to fix the root cause, up to N iterations, then give up (bounded) |
| `AUTOTEST_SEMANTIC` / `AUTOTEST_COUNCIL` | `1` | enable the AI judges / the council |
| `AUTOTEST_VISION` | `1` | enable the screenshot vision judge (`vision.py`) — skips cleanly with no provider key |
| `AUTOTEST_DISCOVER` | unset | let `claude` find more test files on the web |

### Trust & coverage flags (Tier A–D — see `docs/autotest/`)

| Flag | Default | Effect |
|---|---|---|
| `AUTOTEST_CONFIRM_SWEEPS` | `2` | A1: extra sweeps a *subjective* finding must recur before `pending → open` (0 disables the gate) |
| `AUTOTEST_DECAY_SWEEPS_SUBJECTIVE` | `3` | A2: absent sweeps before a subjective finding auto-closes |
| `AUTOTEST_DECAY_SWEEPS_DETERMINISTIC` | `6` | A2: absent sweeps before a deterministic finding auto-closes |
| `AUTOTEST_FIX_REQUIRE_REPRO` | `1` | A6: fixer must write a failing-first deterministic test before touching product code for a *subjective* finding |
| `AUTOTEST_CALIBRATION_MIN_CURATED` | `20` | A5: human-curated labels needed before the measured council precision is published |
| `AUTOTEST_A11Y` | `1` | B2: axe-core accessibility pass on each rendered page (deterministic) |
| `AUTOTEST_VISUAL` | `1` | B3: Playwright visual-snapshot regression on key surfaces (deterministic) |
| `AUTOTEST_CONTRACT` | `1` | B5: Schemathesis API contract tests for `/api` (deterministic, pytest-native) |
| `AUTOTEST_BROWSER` | `chromium` | B1: `chromium` \| `firefox` \| `webkit` |
| `AUTOTEST_DEVICE` | _(unset)_ | B1: optional Playwright device name for a mobile pass (e.g. `iPhone 13`, `Pixel 7`) |

### Finding lifecycle (Tier A — trust)

Findings now have a lifecycle instead of opening on a single sighting and never
ageing out (the noise problem the benchmark report flagged):

```
            (subjective)                          (deterministic)
new finding ───► pending ──confirm×N──► open ◄──────── new finding
                    │                     │
              (absent×K) decay      fix loop picks it up
                    │                     ▼
                    ▼                  fixing ──► fixed ──recurs──► regressed (top of BUGS.md)
              auto-closed ──recurs──► regressed        verified-fixed (terminal, never reopened)
```

- **Subjective** findings (`semantic:*`, `vision:*`, `council:*`) enter **`pending`**
  and only become **`open`** after recurring `AUTOTEST_CONFIRM_SWEEPS` times — a single
  AI sighting is not a bug. **Deterministic** findings (crashes, 5xx, broken links,
  ground-truth, a11y/contract/visual) open immediately.
- A finding not reproduced for the decay window **`auto-closed`** (record kept, never
  deleted); if it recurs it reopens as **`regressed`** at the top of the report.
- The fixer only acts on `open`/`regressed`, ignores `pending`, and (A6) needs a
  deterministic failing-first repro before changing product code for a subjective one.
- `python -m autotest.metrics` measures the council's precision/recall vs the
  human-curated calibration set (`autotest/calibration/`) and prints a 🔬 Judge-trust
  line; low precision tightens the confirm gate.

## Benchmark & roadmap

The trust + coverage work in this harness follows a public-repo benchmark and gap
analysis: **[`docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md`](../docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md)**
(the *why*), with the implementation spec in
[`docs/autotest/IMPLEMENTATION_PROMPT.md`](../docs/autotest/IMPLEMENTATION_PROMPT.md) and
the change log in [`docs/autotest/AUTOTEST_CHANGES.md`](../docs/autotest/AUTOTEST_CHANGES.md).

> `AUTOTEST_BUILD_MERGE` keeps its historical name (the deployed workflow sets it)
> so re-homing the auto-merge code from the old builder into `gitops.py` didn't
> change the operator's configured behaviour. It arms the **fixer's** auto-merge.

## GitHub Actions backstop

`.github/workflows/autotest.yml` runs the finder on a schedule (no machine
needed) and uploads `BUGS.md` + screenshots as an artifact, then runs the fixer.
Add `GEMINI_API_KEY` as a repo secret to run the subagents + council there too
(or use the subscription `CLAUDE_CODE_OAUTH_TOKEN`).
