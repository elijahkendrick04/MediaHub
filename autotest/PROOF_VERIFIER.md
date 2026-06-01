# Independent verifier checklist for the autonomous-close proof

> Committed BEFORE the run (council proof-target ruling, prereq 5). Resolves the
> structural conflict of interest (the council designs the criteria AND would
> otherwise evaluate the result). This is a FROZEN, mechanical pass/fail checklist
> applied to the run's ARTIFACTS — not a judgement. A reviewer (human, or any
> process not involved in designing these criteria) runs down this list against the
> committed artifacts. Every box must be checkable from a file or a command output,
> not from anyone's opinion.

## The run is a VALID PROOF of the narrow claim iff ALL are true:

1. **[ ] Pre-committed RED.** The before-assertion (external symptom check) was committed
   to git BEFORE the loop ran, and its committed run-log shows it FAILED (RED) on the
   pre-fix tree. → check: the assertion file's commit timestamp precedes the fix commit;
   the committed `proof_before.log` shows a failure.

2. **[ ] Coder authored the product fix.** The fix diff to `src/mediahub/**` was produced
   by `claude -p` in the loop, not hand-written. → check: the fix commit author is the
   autotest bot; no human commit touches product code in the fix branch.

3. **[ ] prove_regression RED→GREEN.** `gitops.prove_regression()` logged `proven` for the
   fix (the new test fails on pre-fix source, passes after). → check: committed
   `prove_regression.log` shows the status `proven`.

4. **[ ] Full suite green.** The complete pytest suite passes on the fix branch. → check:
   committed suite log shows `N passed`, rc=0.

5. **[ ] CI green on the PR.** The loop-opened PR's GitHub checks are all `success`. → check:
   the PR's check-run conclusions.

6. **[ ] External assertion now GREEN.** The same before-assertion, re-run after the fix,
   PASSES (symptom absent in the real-client/seeded-harness response). → check: committed
   `proof_after.log` shows it passing, against the SAME assertion file (unchanged hash).

7. **[ ] Autonomy boundary honoured.** No human wrote product code; no human picked the
   specific bug (RANK selected within the pre-filtered set). → check against
   AUTONOMY_BOUNDARY.md.

8. **[ ] Caveats stated.** The writeup states the seeded-harness oracle is weaker than a
   cold client, and that this is one close (proof-of-concept, not reliability).

## What this proof actually claims (council — do not overclaim)

If it passes, the proof shows: **the autonomous loop can execute ONE complete close cycle
(FIND→RANK→PATCH→VERIFY→PR→merge) on a real seeded bug, with a documented result.** It does
NOT claim pipeline reliability in general (n=1 is an anecdote, not a distribution). "Is it
working?" for the narrow claim needs TWO closes on two different bugs.

## The break-point case (council prereq — the most likely outcome on the architectural bug)

The target is the hardest real bug (zero-cards root). The coder may not produce a valid
patch. That is a **valid, interpretable result**, classified as:

- **BREAK@PATCH** — the coder produced no valid patch (stalled / max-turns / gate stayed
  red / would only pass by editing the fixture). → check: the loop's result is
  `failed`/`coder-failed`, the bug is still `open`, NO PR opened, NO product code
  hand-written. This is a **valid PROOF OUTCOME**, not a proof failure: it locates the
  break exactly where the council predicted (downstream of FIND, at the coder). Record the
  exact stall reason + the coder's last output.
- **BREAK@VERIFY** — a patch landed but `prove_regression` is hollow/no-test or the suite
  is red. → recorded; not a close.
- **BREAK@PR/CI** — PR didn't open or CI is red. → recorded; not a close.
- **CLOSE** — all 8 boxes above pass.

A BREAK is a **successful, certifiable run with a negative result** — the proof ran and we
learned exactly where the chain breaks. The only *uninterpretable* outcome (which this box
exists to prevent) is a stall with no recorded classification.

## Cascade close (council prereq)

A root-cause fix to zero-cards may close MULTIPLE queue items at once (the 13 functional
facets are downstream of it). That is still ONE close cycle for proof purposes (one fix,
one PR). The before/after assertion targets the ROOT symptom (the seeded sample meet
produces ≥1 content card after the fix where it produced 0 before). Secondary items
closing as a side effect are noted, not separately counted.

## Independence caveat (stated, not hidden)

This checklist was authored by the same effort that designed the proof. The evaluation is
mechanical (artifact-checks anyone can re-run), which bounds but does not eliminate the
conflict. **External audit pending** — a reviewer outside this effort can re-run the 8
boxes against the committed logs and should.

## Disposition

- ALL 8 boxes checked → the narrow claim is PROVEN for this one bug (n=1).
- A classified BREAK (@PATCH/@VERIFY/@PR) → a VALID run with a negative result: the proof
  ran, the break point is located and recorded. Not retried-in-place to force a pass.
- An UNCLASSIFIED stall (no box assignable) → the run is inconclusive; fix the gap and re-run.

## Why this resolves the conflict of interest

The criteria are frozen here, in advance, as artifact-checks. The evaluation is mechanical:
anyone can run the 8 checks against the committed logs and reach the same verdict. The
council does not get to re-interpret "did it really work" after seeing the result — the
answer is whatever the 8 boxes say.
