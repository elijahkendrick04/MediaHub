# 5. Governed auto-merge for the autotest feature

- **Status:** Auto-merge SUPERSEDED by
  [ADR-0020](0020-no-autotest-automerge.md) (2026-06-12) — after an auto-merged
  web change broke production fonts, the operator chose human approval for every
  fix, so the loop no longer auto-merges anything. The 3-way classification
  below still stands for **scope/labelling**; it just no longer feeds an
  auto-merge.
- **Original status:** Accepted. The autonomous autotest loop may auto-merge its own ordinary
  harness code (and product fixes) on green CI; it may **never** auto-merge a change to the
  files that govern it. Recorded in [`../../autotest/CHANGE_CLASSIFICATION.md`](../../autotest/CHANGE_CLASSIFICATION.md)
  and enforced by [`gitops.classify_change`](../../autotest/gitops.py),
  [`tests/test_autonomy_tripwire.py`](../../tests/test_autonomy_tripwire.py), and
  [`.github/CODEOWNERS`](../../.github/CODEOWNERS).
- **Date:** 2026-06-02
- **Deciders:** MediaHub maintainer (operator directive) + the LLM Council.
- **Decision method:** Run through the `llm-council` skill — five advisors (Contrarian,
  First-Principles, Expansionist, Outsider, Executor), anonymized peer review, chairman
  synthesis. Full transcript + visual report archived under
  [`../../autotest/reports/council/`](../../autotest/reports/council/)
  (`council-transcript-20260602T020000Z.md`, `council-report-20260602T020000Z.html`,
  gitignored runtime output).

## Context

The operator directed: *"This whole autotest feature should be fully autonomous. Adopt ways
to work with the governance and then to automerge. This is the only place we should be
automerging."*

Before this, [`CHANGE_CLASSIFICATION.md`](../../autotest/CHANGE_CLASSIFICATION.md) classified
every loop change touching `autotest/**`, `.github/workflows/**`, `CLAUDE.md`, or the
deploy/dependency surface as "harness/governance" → **human merge required**. Only `src/mediahub`
product changes auto-merged. The human gate existed to stop the loop **self-governing its own
trust boundary**: a loop that can auto-merge edits to `autotest/` could weaken its own safety
nets (the `autotest/STOP` kill switch, scope caps, the protected-engine guard, the classifier
and the merge logic in `gitops.py`).

`main` auto-deploys to Render production, so auto-merge is outward-facing and hard to reverse —
a council-gated decision per [`COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md). The operator
set the *what* (autotest is the autonomous, sole auto-merge zone); the Council pressure-tested
the *how*.

## Decision

A **3-way** classification, and a **two-layer** enforcement of the boundary.

1. **Three classes** (`gitops.classify_change`):
   - **product** (`src/mediahub/**` minus the protected engine, `tests/**`) → auto-merge.
   - **harness** (ordinary autotest machinery: finders, judges, council, report lifecycle,
     metrics, the a11y/visual/contract finders, reports/ledger) → **auto-merge** (the new autonomy).
   - **self-governance** (`gitops.SELF_GOVERNANCE`: `gitops.py`, `fix_loop.py`, `autotest/STOP`,
     the governance/autonomy docs, `tests/test_autonomy_tripwire.py` + the classifier's own
     tests, `.github/workflows/**`, `.github/CODEOWNERS`, `CLAUDE.md`, `render.yaml`,
     `Dockerfile`, `pyproject.toml`, `requirements*.txt`) → **HUMAN merge**.
   - Stricter wins; an empty/unknown set fails safe to self-governance. **The classifier itself
     is in the self-governance set** — otherwise the loop could reclassify its own diff as code.

2. **Two-layer enforcement** (the council's decisive blind-spot catch — an in-repo guard is run
   by the same identity that writes the code, so green CI is exactly what an optimiser produces):
   - **In-repo, deterministic:** `classify_change` + `tests/test_autonomy_tripwire.py`, which
     fails CI if any safety net is removed (kill switch, protected list, scope caps, the A6
     corroboration gate, the self-governance set, CODEOWNERS) or if the test suite is silently
     shrunk below committed floors.
   - **Platform, the real stop:** GitHub branch protection on `main` + `.github/CODEOWNERS`
     require a human code-owner review on every self-governance path, with the bot identity
     holding **no bypass**. The loop literally cannot merge those paths.

3. **Keep product auto-merge** (operator confirmed; council 4/5). Product fixes are revertible
   and non-self-referential; they cannot weaken the safety nets and are already gated by the
   full suite + `prove_regression` + scope caps + the A6 gate.

4. **The bootstrap PR is human-merged.** The PR that grants this authority is itself a
   self-governance change; a grant of authority can't ratify itself.

### Council verdict (summary)

- **Unanimous:** not all-or-nothing — split harness *code* (auto-merge) from the
  *constitution set* (human merge); the loop must never auto-merge a change to the files that
  govern it, including the classifier; the bootstrap is human-merged; keep product auto-merge.
- **Peer-review blind spot (all five advisors missed it):** in-repo guards are necessary but
  insufficient — enforcement must move outside the loop (branch protection + CODEOWNERS), and
  the bot's merge credential must hold no bypass, or every gate is advisory.
- **Clash:** the Outsider wanted staging/rollback/delay before prod for product fixes; the
  majority kept product auto-merge. Resolution: keep product auto-merge as-is; a staged-deploy
  with auto-rollback is a separate, valid follow-up (not in scope here).

## Consequences

- The loop can now autonomously improve and ship the bulk of its own harness (judges, lifecycle,
  coverage finders, metrics) without a human in the loop, while the small governance core stays
  human-held — a compounding, self-maintaining QA harness with its leash held outside itself.
- **Required operator action (one-time):** enable branch protection on `main` with "Require
  review from Code Owners" + required status checks, and ensure the autotest bot identity is not
  an admin / has no branch-protection bypass. Until then, layer 1 is advisory. Documented in the
  CODEOWNERS header.
- Changing the boundary later (the self-governance set, the tripwire floors, the classifier) is
  itself a self-governance change → human-merged, by construction.
- **Follow-up (deferred):** a staged prod deploy with automatic rollback for product auto-merges
  (the Outsider's concern); audit/alerting when the tripwire fires or `STOP` is touched.
