# MediaHub Autopilot — autonomous tester + builder

Two cooperating loops that test, find/fix bugs, and build the roadmap on their
own — **fully autonomous and cloud-based, running in GitHub Actions** (no
desktop, no Cowork). A headless browser does real uploads/downloads inside the
runner, so nothing needs to "escape a sandbox".

**Cloud setup (this is the engine):**
1. Add **one** repo secret: **`CLAUDE_CODE_OAUTH_TOKEN`** — generated once with
   **`claude setup-token`** from a **Claude Pro/Max subscription**. That single
   token powers the WHOLE loop (subagents, council, coder + fixer) via the
   Claude CLI — **no API keys anywhere, flat cost, no metered billing**. No
   token → the AI judges + build/fix steps skip cleanly, so nothing runs wild
   until you arm it. On repeated failure the loop **opens a GitHub issue and
   stops** (capped attempts) instead of wasting subscription quota.
   *(Prefer the free-tier Gemini coder/judges instead? Set `AUTOTEST_CODER=gemini`
   and the relevant API key — but the default is API-key-free.)*
2. Settings → General → enable **Allow auto-merge**, and allow the actions bot
   to merge to `main` (loosen branch protection / required reviews as needed).
   **Also let the loop open PRs**, or its fixes have nowhere to land: either
   Settings → Actions → General → tick **"Allow GitHub Actions to create and
   approve pull requests"**, **or** add an **`AUTOTEST_GH_PAT`** secret (a
   fine-grained PAT with `pull_request: write` + `contents: write`) — the
   workflows prefer it over `GITHUB_TOKEN`, and a PAT-opened PR also triggers CI
   so `--auto` merge can actually fire. Without one of these, `gh pr create`
   is denied, the loop reports `fix-pushed-no-pr` (branch pushed, **not** merged)
   and notifies you — it no longer silently claims success.
3. That's it. `.github/workflows/autotest.yml` (hourly) finds + fixes bugs and
   commits `BUGS.md` back; `.github/workflows/autopilot.yml` (every 2h) builds
   the next roadmap item, tests it, and merges it to `main` if it didn't
   regress. The roadmap status flips itself via the existing autoupdate.

The `loop.py` / `build_loop.py` "run forever" drivers below are an OPTIONAL
always-on worker (e.g. a cloud VM) if you ever want continuous rather than
scheduled — the cloud default is the two workflows.

```
                ┌───────────────── BUILDER loop (autotest.build_loop) ─────────────────┐
  docs/ROADMAP.md → pick next item → Claude coder builds it → guards + test gate →
                     commit + PR → (arm) merge to main → writes a HANDOVER ───────────┐
                                                                                       │
                ┌───────────────── TESTING loop (autotest.loop) ──────────────────────▼─┐
  boot app → drive real flow + crawl → deterministic detectors ┐                        │
                                                               ├→ semantic subagents ┐  │
   (reads the HANDOVER, judges the new feature vs ROADMAP intent)                    ├→ LLM Council
                                                               ┘  (adjudicates)      ┘  │
  → BUGS.md (deduped, fix-ready)  → accept: mark roadmap DONE  ◄── or AUTO-REVERT ◄──────┘
                                  → fixer (autotest.fix_loop) turns bugs into PRs
```

## Optional: run it locally (the cloud workflows are the default)

These are the same single-shot entrypoints the workflows call — handy for a
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

# 5) autonomous roadmap building (build next item -> PR -> handover):
python -m autotest.build_loop

# Full autopilot = run the builder loop AND the testing loop together,
# with the tester allowed to mark the roadmap done / revert:
AUTOTEST_ACCEPT_APPLY=1 python -m autotest.loop      # terminal 1
python -m autotest.build_loop                        # terminal 2
```

The bug report lands in **`autotest/reports/BUGS.md`** — deduped and written so a
Claude Code session can fix an entry just by reading it (repro, expected/actual,
evidence, suspected `file:line`, screenshot). Paste a section into Claude Code,
or let `autotest.fix_loop` do it.

## The key — env/.env only, never hard-coded

The Gemini/Anthropic key is read from the environment (loaded from the gitignored
`.env` by `autotest/_env.py`). It is **never** written into source, tests,
commits, or logs. Rotate it by editing `.env` alone. With no key, the AI layers
(semantic subagents + council + acceptance judge) skip cleanly and the
deterministic finder still runs.

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
  deterministic engine). This is the one idea taken from ByteDance's
  UI-TARS-desktop — *let an AI see the screen* — applied to QA, not control
  (verdict: `reports/council/ui-tars-desktop-*`). Toggle with `AUTOTEST_VISION`
  (default `1`).
- **LLM Council** (`council.py`, embedding the vendored `skills/llm-council`) —
  5 adversarial advisors → anonymised peer review → chairman verdict. It
  **adjudicates** the subagents' findings: confirms real bugs, demotes noise,
  surfaces blind spots. Anti-sycophancy, so the ledger stays clean. Full
  transcript + HTML report under `autotest/reports/council/`.

## Safety nets & flags

The operator chose **full auto-merge to `main`** (overriding the council's
advice for a human gate). These are therefore the only things between a bad AI
change and production, and they are strict:

| Net | Behaviour |
|---|---|
| Kill switch | `touch autotest/STOP` halts both loops immediately |
| Circuit breaker | `AUTOTEST_BUILD_BREAKER` (3) consecutive failed builds → halt for a human |
| Protected paths | a build/fix touching the deterministic engine (parsers, detectors, ranker, colour-science) aborts before merge |
| Scope cap | `AUTOTEST_BUILD_MAX_FILES` (25) / `AUTOTEST_BUILD_MAX_INSERTIONS` (2000) |
| Test gate | the full suite must stay green or nothing merges |
| Iterate-to-green | a gate failure is fed back to the coder to fix the ROOT CAUSE (repo skills), up to `AUTOTEST_GATE_MAX_ITERS`, then it carries on merging — it does not just abandon the change (and may not delete/weaken tests to pass) |
| Auto-revert | the testing loop reverts a merged item on `main` if it regresses, and marks the roadmap `blocked` |

| Flag | Default | Effect |
|---|---|---|
| `AUTOTEST_BUILD_APPLY` | `1` | build the item (claude + commit + push + PR). `0` = dry-run plan |
| `AUTOTEST_BUILD_MERGE` | `0` | **arm** CI-gated auto-merge to `main` (full auto to prod). One flag from hands-off |
| `AUTOTEST_ACCEPT_APPLY` | `0` | let the tester push roadmap `done`/`blocked` directives + reverts |
| `AUTOTEST_FIX_APPLY` | `1` | run the bug-fixer (`0` = list only) |
| `AUTOTEST_CODER` | `claude` | coding agent: `claude` (best quality, no fallback) or `gemini` |
| `AUTOTEST_FIX_MAX_ATTEMPTS` | `2` | give up + open a GitHub issue after N failed fix tries (credit guard) |
| `AUTOTEST_GATE_MAX_ITERS` | `3` | when a change fails the test gate, feed the failure back to the coder to fix the root cause, up to N iterations, then give up (bounded) |
| `AUTOTEST_SEMANTIC` / `AUTOTEST_COUNCIL` | `1` | enable the AI judges / the council |
| `AUTOTEST_VISION` | `1` | enable the screenshot vision judge (`vision.py`) — skips cleanly with no provider key |
| `AUTOTEST_DISCOVER` | unset | let `claude` find more test files on the web |
| `AUTOTEST_BUILD_ITEM` | — | force a specific roadmap id (e.g. `PAR-2`) |

## Roadmap integration

The builder reads `docs/ROADMAP.md` (IDs `SEQ-N`, `PAR-N`, `Step N`, phase
`1.6`) and picks the next uncompleted item. Status is flipped via the existing
`scripts/roadmap_autoupdate.py` machinery — the loops just emit a
`roadmap: <id> <status>` commit trailer (`wip` on build, `done` on acceptance,
`blocked` on regression).

## GitHub Actions backstop

`.github/workflows/autotest.yml` runs the finder on a schedule (no machine
needed) and uploads `BUGS.md` + screenshots as an artifact. Add `GEMINI_API_KEY`
as a repo secret to run the subagents + council there too.

## What the council said about full autonomy

Consulted on this exact design, the council called fully-autonomous
build→merge→deploy with no human "catastrophic risk" — chiefly the
builder/tester validating each other's mistakes (a "hallucination cascade") and
uncontrolled prod deploys. Its #1 recommendation was a human feature-level check
before prod. The operator reviewed this and chose full auto to `main` anyway;
the safety nets above are the agreed mitigation. Flip to a human gate any time
by requiring approval on the build PRs and leaving `AUTOTEST_BUILD_MERGE=0`.
```
