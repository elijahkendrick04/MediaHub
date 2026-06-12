# ADR 0020 — The autotest loop no longer auto-merges; human approval for all fixes

- **Status:** accepted (2026-06-12) — supersedes the auto-merge decision in
  [ADR-0005](0005-autotest-governed-auto-merge.md). The 3-way change
  classification in ADR-0005 / `autotest/CHANGE_CLASSIFICATION.md` still stands
  for scope/labelling; only the **auto-merge consequence** is removed.
- **Context:** operator directive after the 2026-06-12 incident. The autonomous
  autotest fix loop auto-merged **PR #424** — a `src/mediahub/web/web.py` change
  that added a custom `/static/theme/fonts.css` route to satisfy an axe-core
  accessibility check. The route's endpoint name was not on the org-gate
  exemption list, so in production `/static/theme/fonts.css` 302-redirected to
  `/sign-in`, the browser received HTML instead of CSS, and **every page on the
  live site fell back to system fonts.** CI was green because the org gate is
  bypassed under `TESTING`, so the loop's local suite never saw the redirect and
  the change auto-merged + deployed with no human in the loop. The operator:
  *"fix whatever that autobot did wrong to be able to change something as serious
  as the fonts so easily without permission."*

## Decision

**The autotest loop never auto-merges to `main`.** It still runs autonomously —
finds bugs, writes fixes, runs the local gate, and opens a PR — but a **human
reviews and merges every fix PR**. There is no longer an auto-merge-eligible
class of change.

- The operative switch is `AUTOTEST_BUILD_MERGE` in
  `.github/workflows/autotest.yml`, now `"0"`. `gitops._merge_to_main` only arms
  `gh pr merge --auto` when that flag is `"1"`, so with it off the loop opens the
  PR and stops.
- `tests/test_autonomy_tripwire.py` (self-governance — human-merge only) asserts
  the workflow does **not** set `AUTOTEST_BUILD_MERGE: "1"`. Re-arming auto-merge
  therefore requires a deliberate human change to **both** the workflow and that
  test — it cannot be flipped back silently or by the loop itself.

## Why (root cause, two layers)

1. **No human gate on user-facing production changes.** ADR-0005 let any
   `src/mediahub` "product" fix auto-merge. A website/UI change is exactly the
   kind of thing whose breakage is visible to customers and whose correctness
   the test suite did not fully cover. "Approval for everything" is the operator's
   chosen posture.
2. **Test/prod gap.** The org gate is disabled under `TESTING`, so a gate-related
   break passes the loop's local suite. Fixed separately in the same change:
   `tests/test_static_assets_bypass_gate.py` runs with the gate **enforced** and
   asserts `/static/` assets are never redirected — so this specific class of
   break now fails CI regardless of the merge policy.

## Consequences

- The loop's value (autonomous detection + drafted fixes) is preserved; only the
  unattended landing to production is removed. Throughput on fixes is now bounded
  by human review, which is the intended trade.
- ADR-0005's classifier (`product` / `harness` / `self_governance`) and the
  protected-engine / kill-switch tripwires remain wired and meaningful for scope
  control; they simply no longer feed an auto-merge.

## Out of scope (not changed here)

- **Dependabot** auto-merge (`.github/workflows/dependabot-automerge.yml`) is a
  separate mechanism for dependency bumps and is left as-is. Revisit separately
  if the operator wants dependency PRs gated too.
- **Roadmap auto-update** commits (`[skip render]` docs) do not deploy and are
  unaffected.
