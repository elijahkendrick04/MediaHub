# 2. The Council is the repo's decision authority

- **Status:** Superseded by [`0010-council-as-advisory-tool.md`](0010-council-as-advisory-tool.md)
  (2026-06-03). The Council is retained, but its *authority* is narrowed: it is now a tool
  reached for on a small set of high-stakes, hard-to-reverse decisions rather than a gate on
  all non-trivial work. The history below is preserved as the original rationale.
- **Date:** 2026-05-31
- **Deciders:** MediaHub maintainer (directive: *"the council shouldn't just be there,
  it should dictate all decisions across my whole repo"*).
- **Context source:** the LLM Council skill
  [`../../autotest/skills/llm-council/SKILL.md`](../../autotest/skills/llm-council/SKILL.md)
  and its in-process embedding [`../../autotest/council.py`](../../autotest/council.py);
  governance policy [`../COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md).

## Context

The Council (Karpathy's LLM Council — five advisors with clashing thinking styles →
anonymous peer review → chairman synthesis) already existed in the repo, but only as
(a) an installable skill and (b) an adjudicator of the autonomous tester's findings.
It was *available* but not *authoritative*: nothing said which decisions had to go
through it, so the default decision-maker was a single voice (a maintainer's instinct
or a single model's first answer). Single voices rationalise whatever they already
lean toward — the exact failure mode the Council was built to counter.

## Decision

Promote the Council from "a tool that's there" to **the repo's decision authority for
non-trivial decisions.** Concretely:

- **`CLAUDE.md` gains a "Decision governance — the Council decides" section** that
  binds every agent/contributor: convene the Council *before* acting on council-gated
  work, build the verdict, and record it.
- **`docs/COUNCIL_GOVERNANCE.md`** defines the full policy: what is council-gated
  (architecture/data-model, route/data-structure removal, roadmap priority, ≥2-credible-
  approach forks, new AI surfaces / deterministic-boundary framing, outward-facing or
  hard-to-reverse changes), what is explicitly *not* (trivia, single-obvious-fix bugs,
  implementing an already-decided step), how to convene, and the decision-record format.
- **Decision records are ADRs** in `docs/adr/` (committed, linkable from the PR); the
  full transcript + HTML briefing are kept as ephemeral artifacts under the gitignored
  `autotest/reports/council/`.

### Enforcement: wired into Claude Code

The Council is enforced **through Claude Code, not CI.** It is registered as a
first-class Claude Code skill at `.claude/skills/llm-council` — a symlink to the single
source of truth in `autotest/skills/llm-council`, mirroring how `emil-design-eng` is
wired — so every session in this repo auto-discovers it and can convene it via
`/llm-council` or a trigger phrase ("council this", "pressure-test this", …). The
`CLAUDE.md` "Decision governance" rule binds agents to run it before council-gated work
and link the ADR in the PR; the autonomous tester runs the in-process Council
(`autotest/council.py`) for its own findings.

A hard CI merge-gate was considered and **deliberately rejected** — see Consequences.

## Consequences

- **Positive:** decisions are adversarially pressure-tested before they ship; every
  council-gated decision leaves an auditable trail (matches the standing rule *every
  step should be explainable and auditable*); new contributors and autonomous agents
  inherit the same discipline from one file.
- **Cost:** a real overhead per non-trivial decision. Mitigated by the explicit
  "don't council trivia" carve-out and by the Council's own warning against trivial use.
- **Deliberately rejected:** a hard CI merge-gate. It needs a provider token in CI and
  a per-PR spend, and it can block the auto-deploying trunk. Enforcement is wired into
  Claude Code instead — the registered `.claude/skills/llm-council` skill — so governance
  lives where decisions are made, not in a post-hoc check.
- **Boundary preserved:** the Council may frame, but **cannot approve**, Gemini-ifying
  the deterministic engine (parsers, detectors, ranker, colour-science) — that still
  requires explicit user sign-off.

The first decision made under this authority is recorded in
[`0003-pilot-safety-invariant-lock.md`](0003-pilot-safety-invariant-lock.md).
