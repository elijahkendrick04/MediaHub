# Change classification rule: product vs. harness/governance

> **Human-authored governance artifact** (council "is it working" ruling, Q2 bootstrap).
> The autonomous loop must NOT classify its own changes — that would be a governance
> decision made by the system about the system (the recursion the council flagged).
> Instead, the loop applies THIS fixed, human-authored rule. Authored once, in advance,
> and merged via a human merge. After that the loop applies it mechanically.

## Why this exists

The merge policy depends on what KIND of change a fix is. The operator directed
(2026-06-02) that the **autotest feature is fully autonomous** — the loop auto-merges its
own ordinary harness code, not just product fixes — and that **autotest is the only place
auto-merge is expanded to**. The LLM Council pressure-tested *how* to do that safely
(verdict: `docs/adr/0005-autotest-governed-auto-merge.md`). The result is a **3-way**
classification:

- **product change** → may auto-merge on green CI (operator's standing instruction).
- **harness change** (ordinary autotest machinery) → may auto-merge on green CI (the new
  autonomy).
- **self-governance change** → requires a **HUMAN merge**. The loop must never auto-merge a
  change to the files that GOVERN it — including this classifier itself, or it would simply
  reclassify its own diff as ordinary code.

If the loop decided that classification itself, it would be self-governing its own trust
boundary. So the boundary is defined HERE, by a human, not inferred by the loop — and it is
enforced in **two layers** (see *Enforcement* below), because an in-repo guard is run by the
same identity that writes the code.

## The rule (path-based — deterministic, not a judgement)

A change is **SELF-GOVERNANCE** (human merge required) if its diff touches ANY of
(`gitops.SELF_GOVERNANCE`):

- `autotest/gitops.py` — the merge gate, the protected-engine guard, the scope caps, and
  THIS classifier.
- `autotest/fix_loop.py` — the fixer's decision logic (attempt cap, the A6 corroboration gate).
- `autotest/STOP` — the kill switch.
- `autotest/CHANGE_CLASSIFICATION.md`, `autotest/AUTONOMY_BOUNDARY.md`,
  `autotest/PROOF_CRITERION.md`, `autotest/PROOF_VERIFIER.md` — the governance/autonomy docs.
- `tests/test_autonomy_tripwire.py`, `tests/test_autotest_change_classification.py` — the
  deterministic safety tripwire and the classifier's own tests.
- `.github/workflows/**`, `.github/CODEOWNERS` — CI / automation policy + the platform boundary.
- `CLAUDE.md`, `**/CLAUDE.md` — the project operating rules.
- `render.yaml`, `Dockerfile`, `pyproject.toml`, `requirements*.txt` — deploy/dependency
  supply-chain.

A change is a **HARNESS** change (auto-merge eligible) if it touches `autotest/**` but NONE
of the self-governance set — ordinary machinery: finders, judges, the council, the report
lifecycle, metrics, the coverage finders (a11y/visual/contract), the ledger/reports.

A change is a **PRODUCT** change (auto-merge eligible) if its diff touches none of the
above — confined to product code/assets (`src/mediahub/**` minus the protected engine) and
`tests/**`.

## Protected engine (unchanged, still hard-blocked)

Independent of merge policy, the deterministic engine remains un-editable by the loop
(`gitops.PROTECTED`): parsers, detectors, the ranker, colour-science. A diff touching those
aborts the attempt regardless of classification.

## Mixed diffs

Stricter wins: if a single change touches ANY self-governance path, the whole diff is
**self-governance** → human merge. An **empty / unknown** change set also fails safe to
self-governance (never auto-merge an unknown change).

## How the loop consumes this

`autotest/gitops.py` (`classify_change` + `_merge_to_main`) reads this rule to decide, for a
fix's changed-file set, whether to arm auto-merge (product / harness) or stop at PR-opened
for a human merge (self-governance). The loop never overrides it.

## Enforcement — two layers (the in-repo guard alone is not enough)

The council's decisive blind-spot catch: a self-checked guard is run by the same identity
that writes the code, so "green CI" is exactly what an optimiser produces — a PR that disarms
a safety net *and* deletes the test checking it, all green. So the boundary is enforced twice:

1. **In-repo (deterministic):** the 3-way `classify_change` above + `tests/test_autonomy_tripwire.py`,
   which fails CI if any safety net (kill switch, protected list, scope caps, A6 gate, the
   self-governance set, CODEOWNERS) is removed, or if the test suite is silently shrunk.
2. **Platform (the real stop):** GitHub branch protection on `main` + `.github/CODEOWNERS`
   require a human code-owner review on every self-governance path, and the autotest bot
   identity holds **no bypass**. So even a green PR touching the constitution set cannot be
   merged by the loop — only by a human. **The operator must enable this** (see CODEOWNERS
   header + the ADR); without it, layer 1 is advisory.

The **bootstrap** — the PR that first grants this auto-merge authority — is itself a
self-governance change and is **human-merged** (a grant of authority can't ratify itself),
exactly as this artifact was authored once and human-merged, then applied mechanically.

## Versioned AI-judgement-surface changes

> Council requirement: an AI judge's rubric is a trust surface. When it changes, log the
> diff here with before/after behaviour and a `non-suppressive` tag, and version it (do
> not silently mutate) so a future reader can see what the charter said before.

### functional charter rubric — v1 → v2 (AI judgement surface, **non-suppressive**)

- **Why:** the v1 rubric told the judge to flag *any* zero-card meet ("a real meet file
  that yielded ZERO cards"). But "0 cards" is the CORRECT result of a club-name mismatch
  (file parsed, no swims matched the selected club → nothing to rank — the honest "No
  swims matched your club" state, fixed product-side in #196). The judge could not tell
  that legitimate empty state from a real failure because its only content signal,
  `content_summary`, omitted the swim-match counts. Result: a false-positive on every
  mismatch run, which a re-sweep **re-created** rather than cleared.
- **v1 behaviour:** every zero-card run → HIGH "real meet produced zero cards" (LEGIT,
  REAL-bug, and empty-meet cases all flagged identically).
- **v2 change:** (1) enrich `_content_summary` with `parsed_swim_count`, `our_swim_count`,
  `club_filter`, `parse_warnings` (already on the export; absent counts render `unknown`,
  never coerced to 0); (2) two verbatim rules applied first — **rule 1:** unknown/absent
  counts or a filter/parse error → escalate (medium), do not exonerate; **rule 2:**
  `our_swim_count > 0 AND cards = 0` → HIGH, no exceptions.
- **v2 behaviour (live-judge gate, stable across repeats):** LEGIT-empty (parsed>0,
  matched=0, no warnings) → **clean**; REAL-bug (matched>0, cards=0) → **HIGH** (invariant
  preserved); broken-filter / null-counts → **medium escalate**; empty-meet (parsed=0) →
  informational.
- **Non-suppressive:** this is additive precision — it gives the judge the exact inputs to
  reason, and the `matched>0 → HIGH` invariant is stated verbatim so real failures are
  never suppressed. No deterministic-engine change. (Council rejected a hardcoded
  pre-filter as "a suppression rule wearing different clothes".)

### `verified-fixed` retirement (council Q3)

A terminal, fix-owned ledger status for a finding confirmed already-resolved by external
evidence (a prior commit and/or a finder-precision fix that removes a false-positive),
retired with a `{commit, tests, note, verified_by, at}` audit record via
`report.retire_verified_fixed()`. Never-skip still holds for *open* findings — this only
retires ones with evidence in hand. The harness PR carrying the retirement is human-merged,
so the merging human is the signing gate.

- **Deviation from the council's premise (recorded per governance):** the council assumed
  all ~10 stale findings were the empty-state condition. On individual review, one
  (`8e7c25cd0c3b`, "'032 TOTAL RUNS' leading-zero counter") is an **unrelated** open UX bug
  and was **kept open**; one (`4f1d8d41781e`, "confidence threshold filtering all cards")
  was speculative and retired with **falsification** evidence (cards are demonstrably
  produced), not a same-condition claim. 10 retired, 1 kept open.
