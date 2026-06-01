# Change classification rule: product vs. harness/governance

> **Human-authored governance artifact** (council "is it working" ruling, Q2 bootstrap).
> The autonomous loop must NOT classify its own changes — that would be a governance
> decision made by the system about the system (the recursion the council flagged).
> Instead, the loop applies THIS fixed, human-authored rule. Authored once, in advance,
> and merged via a human merge. After that the loop applies it mechanically.

## Why this exists

The merge policy depends on what KIND of change a fix is:

- **product change** → may auto-merge on green CI (the operator's standing instruction).
- **harness / governance change** → requires a **human merge** (council Q4: a human
  clicks merge for trust-boundary code).

If the loop decided that classification itself, it would be self-governing its own trust
boundary. So the boundary is defined HERE, by a human, not inferred by the loop.

## The rule (path-based — deterministic, not a judgement)

A change is **HARNESS / GOVERNANCE** (human merge required) if its diff touches ANY of:

- `autotest/**` — the testing/build/fix harness, the judges, the council, the ledger,
  and these governance artifacts themselves.
- `.github/workflows/**` — CI / automation policy.
- `CLAUDE.md`, `**/CLAUDE.md` — the project operating rules.
- `autotest/PROOF_CRITERION.md`, `autotest/CHANGE_CLASSIFICATION.md` — these artifacts.
- `render.yaml`, `Dockerfile`, `pyproject.toml`, `requirements*.txt` — deploy/dependency
  surface (supply-chain / runtime trust boundary).

A change is a **PRODUCT** change (auto-merge eligible) if and only if its diff touches
NONE of the above — i.e. it is confined to product code/assets (`src/mediahub/**` minus
the protected deterministic engine, templates, static assets) and/or `tests/**` for
that product code.

## Protected engine (unchanged, still hard-blocked)

Independent of merge policy, the deterministic engine remains un-editable by the loop
(`gitops.PROTECTED`): parsers, detectors, the ranker, colour-science. A diff touching
those aborts the attempt regardless of classification.

## Mixed diffs

If a single change touches BOTH product and harness/governance paths, it is classified
**harness/governance** (the stricter policy wins) → human merge.

## How the loop consumes this

`autotest/gitops.py` reads this rule (the path lists above) to decide, for a given
fix's changed-file set, whether to arm auto-merge (product) or stop at PR-opened for a
human merge (harness/governance). The loop never overrides it.

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
