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

3. **[ ] prove_regression RED→GREEN.** `builder.prove_regression()` logged `proven` for the
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

## Disposition

- ALL 8 checked → the narrow claim is PROVEN for this one bug. (Two such closes on two
  different bugs → "is it working?" answered yes for the narrow claim.)
- ANY box fails → NOT a valid close. Record which box failed and the artifact. A failed
  box at the PATCH/VERIFY/PR stage is the council-predicted "downstream break" — a valuable
  finding, recorded as such, not retried-in-place to force a pass.

## Why this resolves the conflict of interest

The criteria are frozen here, in advance, as artifact-checks. The evaluation is mechanical:
anyone can run the 8 checks against the committed logs and reach the same verdict. The
council does not get to re-interpret "did it really work" after seeing the result — the
answer is whatever the 8 boxes say.
