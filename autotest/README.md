# MediaHub Autopilot — autonomous tester + builder

Two cooperating loops that test, find/fix bugs, and build the roadmap on their
own — **fully autonomous and cloud-based, running in GitHub Actions** (no
desktop, no Cowork). A headless browser does real uploads/downloads inside the
runner, so nothing needs to "escape a sandbox".

**Cloud setup (this is the engine):**
1. Add repo secrets: **`GEMINI_API_KEY`** (tester subagents + council) and
   **`ANTHROPIC_API_KEY`** (the builder/fixer's Claude Code — without it the
   build/fix steps skip, so nothing runs wild until you arm it).
2. Settings → General → enable **Allow auto-merge**, and allow the actions bot
   to merge to `main` (loosen branch protection / required reviews as needed).
3. That's it. `.github/workflows/autotest.yml` (hourly) finds + fixes bugs and
   commits `BUGS.md` back; `.github/workflows/autopilot.yml` (every 2h) builds
   the next roadmap item, tests it, and merges it to `main` if it didn't
   regress. The roadmap status flips itself via the existing autoupdate.

The `loop.py` / `build_loop.py` "run forever" drivers below are an OPTIONAL
always-on worker (e.g. a cloud VM) if you ever want continuous rather than
scheduled — the cloud default is the two workflows.

```
                ┌───────────────── BUILDER loop (autotest.build_loop) ─────────────────┐
  docs/ROADMAP.md → pick next item → claude -p builds it → guards + test gate →
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
| Auto-revert | the testing loop reverts a merged item on `main` if it regresses, and marks the roadmap `blocked` |

| Flag | Default | Effect |
|---|---|---|
| `AUTOTEST_BUILD_APPLY` | `1` | build the item (claude + commit + push + PR). `0` = dry-run plan |
| `AUTOTEST_BUILD_MERGE` | `0` | **arm** CI-gated auto-merge to `main` (full auto to prod). One flag from hands-off |
| `AUTOTEST_ACCEPT_APPLY` | `0` | let the tester push roadmap `done`/`blocked` directives + reverts |
| `AUTOTEST_FIX_APPLY` | `1` | run the bug-fixer (`0` = list only) |
| `AUTOTEST_SEMANTIC` / `AUTOTEST_COUNCIL` | `1` | enable the AI judges / the council |
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
