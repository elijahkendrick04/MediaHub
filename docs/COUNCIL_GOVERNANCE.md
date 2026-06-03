# Council Governance — how the big decisions get a second opinion

> **In plain words.** The default in this repo is *just build* — trust your
> judgement and ship. For the rare decision where being wrong is expensive **and**
> hard to undo, reach for **the Council**: five advisors argue from clashing angles,
> peer-review each other anonymously, and a chairman writes a verdict you can weigh
> against your instinct. This file says *which* decisions are worth that, *how* to run
> one, and *how lightly* to record it. The Council is a tool, not a toll booth.

The council is the methodology in [`autotest/skills/llm-council/SKILL.md`](../autotest/skills/llm-council/SKILL.md)
(Karpathy's LLM Council), also embedded in the autonomous tester as
[`autotest/council.py`](../autotest/council.py) where it adjudicates the semantic
sub-agents' findings automatically. This document covers the *interactive* use — when
a human or agent should convene it before a big call.

---

## 1. When to convene the council (and when not to)

The council earns its keep on decisions that are **both expensive to get wrong and
hard to reverse**. That is a small set. Run it *before* the change when one applies;
otherwise build and move on.

**Worth a council — pressure-test before acting:**

- **Outward-facing or hard-to-reverse** — publishing/deployment-shape changes, external
  integrations, pricing or other commercial surfaces, anything customers see that you
  can't quietly roll back.
- **Major architecture forks** — a structural choice where the wrong pick means *days* of
  rework, not an afternoon; a genuine ≥2-way decision with real switching cost.
- **The deterministic-engine boundary** — introducing a new AI judgement surface, or any
  proposal touching parsers, detectors, the ranker, or colour-science. The council cannot
  *approve* Gemini-ifying the deterministic engine — that still needs explicit user
  sign-off — but it's the right place to pressure-test the framing.

**Not worth a council — just build it well:**

- Ordinary features, bug fixes, and refactors.
- New packages/modules, schema changes, and new persisted shapes that are reversible.
- Reversible route or data-structure changes — normal engineering. (The 15-step breakage
  and safe-removal checks in `CLAUDE.md` still apply to removals; that's a correctness
  gate, not a council gate.)
- "What do we build next" sequencing — that's a founder call, make it.
- Typo/comment/format fixes, mechanical refactors, dependency bumps, test-only changes.

> Rule of thumb from the skill: *"Don't council trivial questions. If the question has
> one right answer, just answer it."* Over-using the council taxes the work and dulls the
> mechanism for the decisions that actually matter.

---

## 2. How to convene the council

1. **Frame the question** neutrally, enriched with repo context (`CLAUDE.md`,
   `docs/ROADMAP.md`, `docs/KNOWN_ISSUES.md`, the files in scope). State the real
   options and what's at stake. Don't pre-bias toward your preferred answer.
2. **Five advisors, in parallel** — Contrarian, First-Principles, Expansionist,
   Outsider, Executor (see the SKILL). Each leans fully into its angle.
3. **Anonymise A–E and peer-review** — each advisor critiques all five blind, naming
   the strongest response, the biggest blind spot, and what everyone missed.
4. **Chairman synthesis** — agreements, clashes, blind spots, a *clear* recommendation
   (not "it depends"), and the one concrete first step.
5. **Weigh it, then build.** The verdict is advice from five angles, not a court order —
   but if you override it, know why. Record the call per §3.

You can drive this interactively via the `llm-council` skill, or in-process via
`autotest/council.py` during a tester sweep. Both honour the no-API-key rule
(subscription/CLI token only) and self-skip cleanly when no provider is available.

---

## 3. Recording the decision (kept light)

When you convene the council on a genuinely significant call, leave a **short ADR** under
[`docs/adr/`](adr/) — the canonical, version-controlled statement of *what was decided
and why*, following the existing ADR convention (Status / Date / Deciders / Context /
Decision / Consequences). **The PR links that ADR.** One paragraph of reasoning is plenty;
this is a decision record, not an essay.

- **No mandatory transcript/HTML per change.** The in-process tester writes full
  transcripts and HTML briefings under `autotest/reports/council/` automatically when
  *it* deliberates (gitignored runtime output). A human convening the council interactively
  does **not** owe a transcript — the ADR is the record. Keep a transcript only if it's
  genuinely useful to re-council the same ground later.
- If hands-on work invalidates a premise the verdict assumed (as happened on 2026-05-31,
  when a prioritised IDOR turned out already fixed), note the deviation in the ADR rather
  than pretending the verdict still holds.

---

## 4. Enforcement — convention, not a gate

The council is enforced by **convention and good judgement**, not by CI or a hard merge
gate. It is registered as a first-class Claude Code skill at
[`.claude/skills/llm-council`](../.claude/skills/llm-council) — a symlink to the single
source of truth in [`autotest/skills/llm-council`](../autotest/skills/llm-council),
mirroring how `emil-design-eng` is wired — so every session auto-discovers it. Any agent
or contributor convenes it with `/llm-council` or a trigger phrase ("council this",
"pressure-test this", "debate this", …).

A hard CI merge-gate was considered and **deliberately not adopted**: running an LLM on
every qualifying PR costs money and blocks the auto-deploying trunk. The autonomous tester
additionally runs the in-process council (`autotest/council.py`) on its own findings — that
automated use is unchanged by this policy and stays on.

---

## 5. Why keep it at all

- **Anti-sycophancy, where it counts.** On a genuinely hard, costly call, a single voice
  (model or engineer) rationalises whatever it already leans toward. Five clashing advisors
  plus anonymous peer review surface the blind spot before it ships. That value is real —
  but only on decisions big enough to be worth the friction, which is why §1 is short.
- **Explainable & auditable.** The few council-gated decisions leave an ADR in the repo,
  matching MediaHub's standing rule that *every step should be explainable and auditable* —
  without burying ordinary work in process.
