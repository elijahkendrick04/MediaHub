# Why a human merged #204/#205 (the council's prereq-6 question)

> The council flagged: "two real fix-branches existed and a HUMAN merged them — why
> did a human step in when autonomous branches existed? Until answered, the proof of
> autonomous close is contested." Here is the documented answer.

## What #204 and #205 actually were

- **#205** merged branch `autotest/fix-b07572c63c13` whose tip commit `2dccbb7` was
  authored by `mediahub-autotest[bot]` on **2026-05-30 20:01** — i.e. it is the OLD
  orphan branch from BEFORE the PR-creation bug was fixed (#177) and before the FIND
  de-contamination (#197). It carried the original stranded coder fix (the
  "N moments found — ready to review" status-string change + a 138-line test).
- **#204** merged `autotest/fix-8ee1cbc395d9`, the analogous old orphan for the
  "/review body never verified" finding, also bot-authored 2026-05-30.

## Why a human merged them (not the loop)

1. **They predate the working auto-merge path.** These branches were pushed back when
   `gh pr create` was silently failing (the bug #177 fixed) — so they were stranded with
   NO PR. They could not auto-merge because no PR ever existed for them.
2. **They are governed by the human-merge rule anyway.** Both touched harness/governance
   surface in their diffs (the stale base meant the diff spanned `pyproject.toml` /
   workflow / governance files), which CHANGE_CLASSIFICATION.md routes to a HUMAN merge.
   So even on the current loop, these specific branches would NOT auto-merge.
3. **The operator chose to rescue the stranded work.** Rather than discard two real,
   suite-passing fixes, the operator opened/merged them manually. That is a human
   recovering pre-existing work — explicitly NOT an autonomous close.

## What this means for the proof

- #204/#205 are **NOT** evidence of an autonomous close. They are old stranded work a human
  rescued. The autonomous-close proof has NOT yet happened and must still be run on the
  de-contaminated queue, per the proof criterion.
- The governance gate behaved correctly throughout: the loop opens PRs; product-bug PRs the
  loop opens auto-merge on green CI; harness/governance PRs (and these stale-based ones)
  stop for a human. A human merging is the designed path for harness/governance, not a
  failure of autonomy.

## The honest scoreboard right now

- FIND input: de-contaminated and proven clean (a real sweep regenerated ZERO flow_result
  false-positives).
- PATCH→VERIFY→PR plumbing: demonstrated to OPEN correct PRs; product fixes are real.
- Fully-autonomous CLOSE on the clean queue against the pre-committed criterion: **not yet
  done.** That is the remaining proof.
