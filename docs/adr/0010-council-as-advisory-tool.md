# 10. The Council is an advisory tool, not a gate on all work

- **Status:** Accepted. Supersedes [`0002-council-as-decision-authority.md`](0002-council-as-decision-authority.md).
- **Date:** 2026-06-03
- **Deciders:** MediaHub maintainer (directive: *"do a major audit on the council skill …
  make sure it actually serves its purpose and doesn't block legitimate progress of this
  SAAS"*).
- **Context source:** audit of the council footprint across the repo — the skill
  ([`../../autotest/skills/llm-council/SKILL.md`](../../autotest/skills/llm-council/SKILL.md)),
  the in-process tester adjudicator ([`../../autotest/council.py`](../../autotest/council.py)),
  the governance policy ([`../COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md)), and the
  `CLAUDE.md` governance section.

## Context

ADR-0002 promoted the Council from "a tool that's there" to **the repo's decision
authority for all non-trivial decisions**. In practice the council-gated list it
defined was so broad — *any* new module, *any* schema change, *any* new persisted
shape, changing *any* public route's contract, removing/replacing *any* route or data
structure, "what to build next", and *any* ≥2-way choice costing "more than an
afternoon" — that it caught nearly every substantive PR. Each gated change was further
required to emit an ADR **plus** a transcript **plus** an HTML report **plus** a PR-body
link.

For a solo-founder, fast-moving SaaS that is a tax on almost all real work, and the
ceremony was not paying for itself:

- ADR-0003 records the council deliberating on a **false premise** (it prioritised
  fixing a cross-tenant IDOR that turned out to be already fixed) — process ran, verdict
  was moot.
- The `docs/adr/` folder accumulated **six** colliding `0002-*` files, so the
  "explainable & auditable" process undermined its own audit trail.

The audit distinguished two mechanisms sharing one name:

1. **The in-process tester adjudicator** (`autotest/council.py`) — runs automatically on
   each autonomous-tester sweep to demote false-positive findings and surface blind
   spots. It is rate-limit aware, self-skips without a provider, uses no API key, and
   **never blocks a human** — it only filters machine-generated noise. This is healthy.
2. **The governance overlay** (the `CLAUDE.md` mandate + `COUNCIL_GOVERNANCE.md`) — the
   broad gating + per-change ceremony. This is the part that blocked legitimate progress.

## Decision

Keep mechanism (1) entirely unchanged. Reform mechanism (2):

- **Default to *just build*.** Features, bug fixes, refactors, new modules, reversible
  schema/route/data-structure changes, and roadmap sequencing are normal engineering and
  ship on the builder's judgement — no council, no ceremony. (The `CLAUDE.md` 15-step
  breakage/safe-removal checks still apply to route/data **removals**; that is a
  correctness gate, not a council gate.)
- **Reserve the Council for high-stakes, hard-to-reverse calls only:** outward-facing /
  expensive-to-unwind changes (deployment-shape, external integrations, pricing/commercial
  surfaces); major architecture forks where a wrong pick means *days* of rework; and the
  deterministic-engine boundary (where it may frame but still **cannot approve**
  Gemini-ifying parsers/detectors/ranker/colour-science — that needs explicit user
  sign-off).
- **Record lightly.** A council-gated call leaves a short ADR linked from the PR. The
  mandatory per-change transcript + HTML artifact requirement is dropped — the tester
  writes those automatically when *it* deliberates; a human convening interactively owes
  only the ADR.
- **Enforcement is convention, not a gate** — unchanged in spirit from ADR-0002 (still no
  CI merge-gate), but the binding language in `CLAUDE.md` is softened from "the verdict is
  what you build" to "pressure-test the few big calls, then decide."

Housekeeping done alongside this decision: the six colliding `0002-*` ADRs were renumbered
to unique IDs (`0006`/`0006`-transcript/`0007`/`0008`/`0009`) with all references updated.

## Consequences

- **Positive:** ordinary work is no longer taxed; the Council is preserved for the rare
  decision where adversarial peer review genuinely earns its cost; the audit trail is
  smaller but real; the ADR folder numbers uniquely again.
- **Cost:** fewer decisions get an automatic second opinion. Mitigated by the in-process
  tester adjudicator (unchanged) and by the standing "when in doubt on a big, irreversible
  call, run it" guidance.
- **Unchanged:** `autotest/council.py` and its integration (`run.py`, `report.py`,
  `metrics.py`, `fix_loop.py`), the `AUTOTEST_COUNCIL*` env vars, the `/llm-council` skill,
  and the deterministic-engine sign-off boundary.
