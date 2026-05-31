# Machine-verifiable success criterion for "the autonomous loop closed a real product bug"

> Committed BEFORE the proof run (council ruling, "is it working" deliberation #11+).
> Council opinion on any criterion below is **inadmissible** — each is an artifact, a
> fact independent of any LLM judgement. The criterion is valid only because it was
> committed before `autotest.fix_loop` executed against the target bug.

## Definition of "autonomous close" (council Q2, option b + bootstrap)

An **autonomous close** is: an unassisted `FIND → PATCH → VERIFY → PR` on a **product
bug** (not harness/governance code), auto-merged via the operator's standing
instruction, where the harness-vs-product **classification rule was human-authored and
merged in advance** (see `autotest/CHANGE_CLASSIFICATION.md`). The human does not write
the fix, pick the bug, or shepherd the patch. The human's only prior act is authoring
the classification rule once.

## The four criteria — ALL must be satisfied; each is an ARTIFACT, not a judgement

1. **prove_regression RED (pre-fix):** `builder.prove_regression()` (or an equivalent
   run) on the target bug's PRE-fix tree logs a status of `proven` — i.e. the new
   regression test FAILS/ERRORS on the source before the patch. Captured to a file.

2. **prove_regression GREEN (post-fix):** the same new test PASSES after the patch, and
   the full suite is green. Captured to a file.

3. **CI green on the opened PR:** the loop-opened PR's GitHub checks are all `success`.
   Captured as the check-run result.

4. **External symptom-absent assertion (OUTSIDE the loop):** the SPECIFIC product
   symptom of the target bug is absent in a **real client response**, captured by a
   call made OUTSIDE `autotest/*` (a direct Flask-test-client or HTTP call written for
   this verification, asserting on the rendered/returned output — not on an internal
   field, not via any judge). This is the external layer that covers the
   "prove_regression lives inside the system" gap: it can distinguish a correct fix
   from a narrowly-passing-but-wrong one only if the assertion targets the exact
   user-observable symptom.

   The symptom assertion MUST be written against the target bug's concrete symptom and
   committed in this file's companion `autotest/PROOF_RUN.md` once the target is known,
   BEFORE the patch is applied — so it cannot be reverse-fitted to whatever the coder
   produced.

## Experimental design (council Q1) — stated honestly, not hidden

- The candidate pool for THIS first proof run **excludes architectural-class bugs**
  (the "zero content cards / empty content" cluster — `_is_hard_cluster` in
  `fix_loop.py`). Rationale: step 3 tests **pipeline mechanics** (does FIND→PATCH→
  VERIFY→PR work on a real bug), NOT the coder's architectural ceiling (which we
  already know it can't one-shot). This is mild, declared experimental scoping — not
  evidence-filtering. Within the remaining pool, RANK picks with **zero** steering.
- The queue must be de-contaminated FIRST (the 47 residual `council:blind_spot`
  entries resolved — see Fix C broadening) so RANK cannot pick speculative
  contamination as the target.

## Two-close standard

One satisfied close is a proof of concept, NOT proof of reliability. "Is it working?"
is answered only after **two** autonomous closes on **two different** real product bugs,
each meeting all four criteria above.

## Failure branch (council blind-spot: name the break)

If any criterion fails, the run is a **structured failure report**, not a retry-in-place:
record the exact failing stage (coder / gate / prove_regression / PR-open / CI /
external-assertion) and the precise output. Per the council's prediction, the likely
break is downstream of FIND. A documented break is a valid, valuable deliverable — it
names where the PATCH→VERIFY chain is actually broken. No human-written fix is
substituted to rescue a failed close.
