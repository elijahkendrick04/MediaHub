# Council Decision Record — Remove the Autobuilder (keep the autotester + autochecker)

**Date:** 2026-06-01
**Trigger:** Operator directive — "remove the autobuilder of the roadmap tool … keep the autotester and autochecker … fully remove it from ever existing."
**Governance:** `CLAUDE.md` → council runs *before* the 15-step breakage check for any route/data-structure removal or architecture change.
**Status:** DECIDED — binding verdict below.

---

## The question (framed)

The operator has **already decided** to remove MediaHub's *autobuilder* — the autonomous
roadmap-**building** subsystem in `autotest/` — fully and permanently, while **keeping** the
*autotester* (bug-finder, `run.py`/`loop.py`) and the *autochecker* (bug-fixer, `fix_loop.py`).
The Council was convened on the **how / boundary**, not whether.

Verified system facts:

- **Autobuilder** = `builder.py` (pick next roadmap item → Claude codes it → test gate → PR →
  auto-merge → write handover), `build_loop.py` (always-on driver), `.github/workflows/autopilot.yml`
  (build→test→merge cron). It pulls in `roadmap.py` (selects the next item; 2-line `directive()`
  helper), `handover.py` (builder writes, tester reads — no other producer), and `accept.py`
  (the tester's acceptance half: reads handovers, judges the built item vs roadmap intent, emits
  `roadmap: <id> done` or **auto-reverts** the merge + `blocked`; called by the kept `run.py:1088`).

- **Fork 1 — shared git/PR/test-gate plumbing.** The kept fixer `fix_loop.py` does
  `from autotest import builder` and reuses *non-roadmap* helpers (`_git`, `BASE_BRANCH`,
  `STOP_FILE`, `implement_until_green`, `prove_regression`, `_open_pr`, `_merge_to_main`,
  `_changed_files`, `_touches_protected`, `classify_change`, `_test_gate`, scope caps). So
  `builder.py` cannot simply be deleted.
  - **(A)** Extract the shared plumbing into a new neutral module; delete `builder.py` + `build_loop.py`.
  - **(B)** Gut `builder.py` in place, keep the filename.
  - **(C)** Inline the shared helpers into `fix_loop.py`.

- **Fork 2 — removal boundary.** With the builder gone, nothing writes handovers, so
  `accept.process()` is a permanent no-op and `handover.py` has no producer; `roadmap.py`
  selection is builder-only.
  - **(X)** Thorough: also delete `accept.py` + `handover.py` + `autotest/handover/` + `roadmap.py`,
    strip the accept call from `run.py`.
  - **(Y)** Minimal: keep `accept.py` + `handover.py` inert.

- **Also at issue:** the roadmap write-side (`roadmap-autoupdate.yml` + `scripts/roadmap_autoupdate.py`,
  which flip `docs/ROADMAP.md` badges from `roadmap: <id> <status>` commit trailers) — keep or remove?
  And `docs/ROADMAP.md` itself. Plus which tests to delete vs repoint, without weakening any test to go green.

Hard constraints (`CLAUDE.md`): full suite stays green (~253 passed / ~34 skipped) with no new
failures and no test cheating; do **not** touch the deterministic engine; no API keys in source;
the fixer's git/PR/auto-merge behaviour preserved **exactly**; leave **no** dead code or placeholder comments.

---

## Advisor responses (de-anonymised)

### The Contrarian
The framing buries the sharpest risk: `accept.py`'s auto-revert is **not** dead infra, it's a loaded
weapon. Under Fork-2-**Y**, if a stale or manually-created handover record sits on disk,
`accept.process()` fires from `run.py:1088` on the next tester run and could **auto-revert a merge the
builder never made**. "Inert" is an operational assumption, not a code guarantee → choose **X**, and
delete the handover dir contents *and* `builder_state.json` **before** the tester runs again (a race
baked into the sequence). On Fork-1: **B** is dishonest and confuses contributors; **C** bloats the
fixer; **A** is correct — but the byte-identical requirement is glossed: any test that mocks
`autotest.builder._git` *by path* will **silently stop firing** after the extract, so tests go green
for the wrong reason. **Fatal flaw to guard: mock-patch targets break silently → false green.**

### The First Principles Thinker
The essential property of the autobuilder is **roadmap autonomy** — picking what to build without human
direction. *That* is what's removed. The git plumbing is **not**; it's a neutral tool used by both loops.
**Fork 1: A** — a module named `builder.py` doing two distinct things (autonomy + git/PR harness) has a
name that *lies*; extract the plumbing to a neutral module, delete `builder.py`. **Fork 2: X** — the
`accept`/auto-revert pathway *is* conceptually part of roadmap autonomy (it only validates/undoes what
the builder built); a pathway that can never fire is dead code, deletion mandatory. **Roadmap write-side:
KEEP** — badges from commit trailers are a CI-documentation concern, not autonomy. Keep `docs/ROADMAP.md`.

### The Expansionist
The real win is the **extraction**, not the deletion. `builder.py` is mixed-purpose by historical
accident; extracting the shared infra forces you to articulate what it *is* — a disciplined, repeatable,
test-gated change-application protocol, the mechanical backbone of the package. Payoff: stable, documented
entry points let a *third* automation (regression-bisector, dependency-upgrader) wire in without touching
`fix_loop.py` — a composable platform, not one-off scripts. **Fork 1: A. Fork 2: X** (orphaned
accept/handover are exactly the dead code `CLAUDE.md` forbids; `run.py`'s accept call becomes a lie).
**Roadmap write-side: REMOVE** (overhead with no programmatic reader). Keep `docs/ROADMAP.md`.

### The Outsider
**B** is dishonest naming — a `builder.py` that no longer builds is a trap for newcomers. Go **A**, name
the shared code honestly. **Y** is the most likely source of wasted afternoons: "auto-revert" logic with
no trigger is a ghost someone burns hours tracing → **X**, delete both. The badge-updater is the subtler
trap: with nothing auto-advancing the roadmap, it stamps statuses onto items that never move → it
**becomes a liar** → remove the workflow + script. Keeping `docs/ROADMAP.md` as a static human doc is a
separate call. **Cleanest: A + X + delete the badge-updater.**

### The Executor
**Pick A + X.** **B** leaves a `builder.py` ghost still importing the (deleted) `handover`/`roadmap` →
`ImportError`; **C** inlines 15+ symbols, doubling `fix_loop`. Safe sequence, green at every checkpoint:
1. Create the new module; copy the shared symbols **verbatim**; no `handover`/`roadmap` import.
2. Repoint `fix_loop.py` `builder.`→new. **Critical:** `test_autotest_fix_no_pr_limbo.py` does
   `monkeypatch.setattr(builder, "_git", …)` — after repointing, those patches **must** move to the new
   module or they're no-ops and `fix_one` calls real git.
3. Repoint `change_classification`/`pr_open`/`regression_proof` tests; **delete** `build_rotation`
   (tests the deleted `_select_item`/attempt rotation — removing a test for removed code isn't weakening).
4. Strip the accept call from `run.py`; drop the accept-only `accepted`/`blocked` plumbing.
5. **Delete** `merge_revert` test; `git rm` builder/build_loop/accept/handover/roadmap/autopilot.yml;
   `rm -rf autotest/handover/`.
6. Grep sweep → zero stray imports; smoke `python -c "from autotest import fix_loop, <new>, run, report"`;
   full suite ~253/~34.

---

## Peer review (anonymised A–E → Expansionist=A, Contrarian=B, Executor=C, First Principles=D, Outsider=E)

**Strongest (5/5 reviewers): Response C (the Executor)** — the only one with an actionable, ordered,
green-at-every-checkpoint plan that *resolves* the mock-patch trap rather than merely naming it.

**Biggest blind spots flagged:** Response **D** (First Principles) — "keep the badge-updater, it degrades
gracefully" mistakes *won't crash* for *is honest*; reviewers split on whether that's orphaned telemetry.
Response **B** (Contrarian) — raises the accept race + mock-patch trap but doesn't *resolve* them.
Response **A** (Expansionist) — architecture optimism that skips the mock-patch hazard.

**What the reviewers said the council missed:**
1. **The badge-updater is only decidable by checking who writes the trailers** (Reviewer 1). → *Verified
   post-hoc:* after removal, **nothing in `autotest/` writes `roadmap:` trailers** (only the deleted
   `builder`/`accept` did; the fixer writes none). So the automated driver vanishes, but the script also
   does a last-updated stamp + activity feed (builder-independent) and still honours **human-authored**
   directives.
2. **Naming:** `harness.py` collides with "the harness" (the whole `autotest/` package, per `CLAUDE.md`) →
   use an unambiguous name (`gitops`/`coding_ops`), not `harness`.
3. **Env-var preservation:** `_merge_to_main` reads `AUTOTEST_BUILD_MERGE`, which the **kept** fixer
   workflow sets → do **not** rename it; renaming silently changes fixer behaviour on the runner.
4. **Doc surface:** `autotest/README.md` (build-loop diagram, "what the council said about full
   autonomy"), `CLAUDE.md` ("autonomous tester/builder"), and several `docs/*.md` describe a system that
   will no longer exist → minimum honest doc rewrite is required, not optional.
5. **Process:** run the `CLAUDE.md` 15-step breakage check before deleting; stage as one reviewable
   commit; verify the deterministic engine is untouched; "fully remove from ever existing" settles
   reversibility — git history is the only hedge, no commented-out code.

---

## CHAIRMAN VERDICT (binding)

**Fork 1 → A (extract).** Unanimous. Move the shared git/PR/test-gate/guard plumbing into a new neutral
module and delete `builder.py` + `build_loop.py`. **Name: `autotest/gitops.py`** (not `harness.py`, which
collides with the package-wide "harness" term — Reviewer 2/3 blind-spot). The fixer's behaviour stays
**byte-identical**: same function bodies, **same env-var names** (`AUTOTEST_BUILD_MERGE`,
`AUTOTEST_BUILD_MAX_FILES/INSERTIONS`, `AUTOTEST_BUILD_TEST_TIMEOUT`) preserved verbatim.

**Fork 2 → X (thorough).** Unanimous. Delete `accept.py`, `handover.py`, `autotest/handover/`,
`roadmap.py`, `autotest/reports/builder_state.json`; strip the acceptance handshake (and its accept-only
`roadmap_accepted`/`roadmap_blocked` plumbing) from `run.py`. The Contrarian's "loaded weapon" makes **X**
the *safe* choice, not merely the tidy one — a no-producer auto-revert pathway is a latent foot-gun.

**Roadmap write-side → KEEP** (`roadmap-autoupdate.yml` + `scripts/roadmap_autoupdate.py` +
`tests/test_roadmap_autoupdate.py` + `docs/ROADMAP.md`). This **overrides** the Expansionist/Outsider
"remove it" position, on sharper reasoning than First Principles gave: (a) it is a **separate** subsystem
*outside* the autobuilder boundary; (b) two of its three functions (last-updated stamp, activity feed) are
**builder-independent and useful**; (c) the directive-applying function degrades to **human-driven** (still
correct, not dead); (d) the operator scoped removal to the "autobuilder **of** the roadmap tool" — the
roadmap tool itself stays. To neutralise the "ghost/liar" objection, add **one honest line** to the
script/workflow noting the autonomous emitter was removed and directives are now human-authored.

**Tests:** repoint `change_classification`, `pr_open`, `regression_proof`, and the `fix_no_pr_limbo`
patch targets to `gitops`; **delete** `build_rotation` (tests deleted item-selection) and `merge_revert`
(tests deleted `accept`). Deleting tests for *removed behaviour* is not weakening; weakening is forbidden.

**Docs:** rewrite `autotest/README.md` to a tester+fixer system (drop the builder loop, autopilot,
`build_loop`, roadmap-build, full-autonomy section, `AUTOTEST_BUILD_*` build flags); fix the `CLAUDE.md`
"tester/builder" reference; audit `autotest/CHANGE_CLASSIFICATION.md` / `PROOF_*` (these stay — the fixer
still classifies + regression-proofs) and `docs/ARCHITECTURE.md`/`FEATURE_INVENTORY.md`/`INVENTORY.md` for
builder-as-live-feature language; add a `docs/CHANGELOG.md` removal entry (don't rewrite history).

**Process:** CLAUDE.md 15-step breakage check → safe extract-first sequence (gitops → repoint fixer +
tests → strip run.py → delete files) → 15-step verification → dead-code sweep. One reviewable change.
Deterministic engine (`interpreter/`, `pb_discovery/`, `recognition*`, ranker, colour-science) is **not**
touched — the refactor is confined to `autotest/` + `.github/workflows/` + docs.

### The one thing to do first
Create `autotest/gitops.py` by moving the shared helpers out of `builder.py` **verbatim**, repoint
`fix_loop.py` and the three shared-helper tests + the `fix_no_pr_limbo` monkeypatch targets to it, and run
the full suite green — **before deleting anything**. Extraction-first keeps the tree green at every step
and defuses the false-green mock-patch trap.

---

## Implementation deviations (recorded per CLAUDE.md governance)

- **`docs/CHANGELOG.md` entry — SKIPPED, with reason.** The verdict called for a CHANGELOG removal
  entry. On inspection `docs/CHANGELOG.md` is a *product-release* digest ("the build report from that
  version") — it does not track the `autotest/` harness at all (the builder's original *addition* was
  never logged there either). Shoehorning a harness-internal removal into a product-release digest would
  be inconsistent with the file's stated purpose, so the removal is instead recorded in this decision
  record, the single squashed commit, and the PR body. History is not rewritten (the verdict's hard rule).
- **`last_run.json` / `_write_last_run` — additionally removed** (beyond the literal file list). Its sole
  documented consumer was the deleted `autopilot.yml` merge-gate; with that gone it was write-only
  orphaned telemetry whose docstring referenced the deleted autopilot. Removing it (and its now-unused
  `crit_high`/`hard_crashes` feeder + the fail-closed sentinel in `run.py:main`) is the dead-code-sweep-
  correct outcome and keeps `run.py` honest. The per-run audit dump `runs/<run_id>.json` is retained.
- **Roadmap write-side — KEPT as ruled**, with one honest clarifying line added (`scripts/
  roadmap_autoupdate.py` + workflow) noting the autonomous emitter was removed and directives are now
  human-authored — neutralising the "ghost/liar" objection the Expansionist/Outsider raised.
- **New module named `gitops.py`** (not `harness.py`) per the peer-review blind-spot: "harness" already
  denotes the whole `autotest/` package in CLAUDE.md. Env-var names (`AUTOTEST_BUILD_*`) preserved verbatim.
