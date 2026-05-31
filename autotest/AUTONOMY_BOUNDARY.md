# The autonomy boundary — what is and isn't autonomous in the proof run

> Committed BEFORE the proof run (council proof-target ruling, prereq 2). The
> "autonomous close" claim is only as strong as this boundary is honest. State
> plainly which steps the loop does unassisted and which have human preconditions.

## The narrowed claim (council)

The proof demonstrates, if it passes: **"the fix loop autonomously closes a
seeded-state functional bug, confirmed by a before/after assertion against the
seeded harness."** NOT "autonomously fixes product bugs." The seeded-harness
oracle is **weaker** than an independent cold-client oracle (it uses the tester's
own seeding) — stated, not hidden.

## AUTONOMOUS (the loop does these with no human in the loop)

- **FIND** — the sweep detects defects; judges + council adjudicate; dedup → ledger.
- **RANK** — selection of which open bug to attempt, within the eligible set, by the
  committed sort key. No human picks the bug.
- **PATCH** — headless `claude -p` authors the product-code fix + a regression test.
  The human writes ZERO product code.
- **VERIFY (internal)** — the full pytest gate + `prove_regression` run inside the loop.
- **OPEN PR** — the loop pushes the branch and opens the PR.
- **MERGE decision** — for a PRODUCT change, auto-merge on green CI (operator's standing
  instruction); for a harness/governance change, the loop STOPS for a human merge
  (CHANGE_CLASSIFICATION.md). The classification is applied mechanically by the loop.

## HUMAN PRECONDITIONS (set up once, before the run — NOT part of the per-bug autonomy)

- **Fixture seeding** — the seeded test org/profile (`_seed_ready_profile`) the finder
  uses. This is test infrastructure, identical for every run; not bug-specific.
- **Reproducibility-gate confirmation** — a human confirms the chosen target's symptom
  is deterministically RED from the seeded state before the run. This is a VALIDITY
  filter on whether the proof is *evaluable*, not a selection of the fix.
- **Before-assertion authorship** — the human writes the external symptom-absent assertion
  (committed RED before the run) so it can't be reverse-fitted to the coder's output.
- **The merge click** for harness/governance changes (by policy).

## What the proof does NOT claim

- It does not claim the loop selects bugs with zero human filtering (a human applied the
  reproducibility/functional-class filter to the candidate set first).
- It does not claim the seeded-harness oracle is as strong as an independent client.
- It does not claim reliability — one close is proof-of-concept; two closes for "working".

## Honest reading

The autonomous core is **FIND→RANK(within filtered set)→PATCH→VERIFY→PR→(auto)merge**.
The human contribution is **test-harness setup + a pre-committed evaluation oracle** — the
scaffolding that makes the result *measurable*, not the engineering of the fix. If that
core runs and the pre-committed assertion flips RED→GREEN with the coder writing the
product change, the narrow claim holds. If a human had to write any product code or pick
the specific bug, it does not.
