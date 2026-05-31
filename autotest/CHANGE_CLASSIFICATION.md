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
(`builder.PROTECTED`): parsers, detectors, the ranker, colour-science. A diff touching
those aborts the cycle regardless of classification.

## Mixed diffs

If a single change touches BOTH product and harness/governance paths, it is classified
**harness/governance** (the stricter policy wins) → human merge.

## How the loop consumes this

`autotest/builder.py` reads this rule (the path lists above) to decide, for a given
fix's changed-file set, whether to arm auto-merge (product) or stop at PR-opened for a
human merge (harness/governance). The loop never overrides it.
