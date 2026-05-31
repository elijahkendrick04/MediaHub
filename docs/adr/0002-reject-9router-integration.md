# 2. Reject integrating 9router into MediaHub (as a skill or otherwise)

- **Status:** Accepted — rejected. 9router will not be added to the repo as a
  skill, a vendored dependency, a documented dev workflow, or a product
  component. The exclusion is recorded in
  [`../../CLAUDE.md`](../../CLAUDE.md) under *Explicitly Excluded* so the
  proposal does not resurface.
- **Date:** 2026-05-31
- **Deciders:** MediaHub maintainer
- **Decision method:** Run through the `llm-council` skill
  (`autotest/skills/llm-council/`) — five advisors, anonymized peer review,
  chairman synthesis. Full transcript and visual report archived under
  [`../../autotest/reports/council/`](../../autotest/reports/council/)
  (`council-transcript-20260531T021122Z.md`,
  `council-report-20260531T021122Z.html`).

## Context

A proposal was raised to evaluate
[9router](https://github.com/decolua/9router) for integration into MediaHub "as
a skill."

**What 9router actually is.** 9router is a free, open-source, MIT-licensed,
self-hosted **local proxy application** (Node.js 20+, Next.js 16, React 19,
SQLite). It routes requests *from AI coding tools* (Claude Code, Codex, Cursor,
Cline, Copilot, Antigravity) to 40+ language-model providers. Its headline value
proposition, quoted from its README, is "Unlimited FREE AI coding … via 40+
providers," achieved by combining subscription accounts with **free provider
tiers** (e.g. Kiro AI, OpenCode Free, Vertex AI). It runs a dashboard at
`http://localhost:20128`; you point a coding tool's API base at it. Features
include a 3-tier fallback, an "RTK token saver" that compresses tool outputs
(claimed 20–40% input-token reduction), per-provider quota tracking, multi-
account load balancing, and OpenAI/Claude/Gemini format translation.

Two facts frame the decision:

1. **It is not a skill.** A Claude Code skill is a repo-resident set of agent
   instructions that ships with the product. 9router is a standalone daemon that
   runs on a developer's machine. There is no artifact that belongs in the
   MediaHub tree — no module, route, test, or genuine skill. Committing a README
   that says "go install this other thing" is clutter the `repo-tidy` skill
   would flag on sight.
2. **Its differentiator is gray-market access.** The value is concentrated in
   tapping *unofficial / free* provider tiers. For a **commercial, paid SaaS**
   that is a materially different proposition than it is for a hobbyist.

## Decision

**Reject 9router for MediaHub** — as a skill, as a vendored dependency, as a
committed/ documented dev workflow, and as any product runtime component.
MediaHub's production AI path (`ai_core/llm.py` / `media_ai/llm.py`,
Gemini → Anthropic failover, keys from env/`.env` only, honest errors when no
provider is configured) stays exactly as-is and is **never** routed through a
third-party proxy.

If a developer personally wants cheaper local iteration, that is a private,
off-repo, on-their-own-machine choice that must never touch customer LLM traffic
and must never be referenced in this repo. The sanctioned answer to genuine dev
cost/quota pain is prepaid **official** Gemini/Anthropic developer keys with a
spend cap — not a gray-market router.

## Rationale (from the council)

The council was unanimous (5/5 reject). The load-bearing arguments:

- **Legal / ToS exposure tied to revenue.** A revenue-generating SaaS routing
  any LLM traffic through ToS-violating gray-market access creates willful-
  infringement exposure attached to the product's revenue. A customer's counsel
  reading provider terms does not care that the access happened "during
  development." This is the single highest-severity, hardest-to-reverse risk.
- **It contradicts MediaHub's own founding rules.** The product's identity is
  "AI required, honest errors, no heuristic fallbacks, keys env-only." 9router's
  free-tier routing is the banned spirit moved one room over to the dev machine.
- **"Dev-only" is a real leak path, not a safe carve-out.** In a monorepo the
  base-URL pattern leaks: a `localhost:20128` API base copied into a Render env
  var during an incident would send customer swim-club data *and*
  `ANTHROPIC_API_KEY` through an unaudited proxy that **rewrites traffic** (token
  compression) — an MITM installed on purpose, breaking the secrets-hygiene and
  multi-tenant-isolation rules.
- **Data confidentiality, independent of ToS.** Dev traffic includes real club
  result files and proprietary prompts. Routing those through an unaudited third
  party is a customer-data exposure even in development, and likely conflicts
  with MediaHub's own provider enterprise terms and customer DPA.
- **The upside is redundant.** MediaHub already has multi-provider failover
  in-product. Any token saving is personal dev spend — by the product's own
  "would someone pay for this standalone?" test, it fails.

## Alternatives considered

- **Add it as a skill.** Rejected: category error (it is a daemon, not agent
  instructions) and it would commit gray-market guidance into a commercial repo.
- **Add it as a documented optional dev workflow.** Rejected: writes ToS
  exposure into the repo and creates the leak path above; `repo-tidy` would flag
  a "go install this" doc as clutter.
- **Vendor / fork the proxy.** Rejected: same legal and confidentiality
  problems, plus an ongoing maintenance burden for a non-product component.
- **"Mine the patterns" and build them natively** (the Expansionist's pitch:
  token compression as margin, cost telemetry, N-provider failover). *Partially*
  noted, but **out of scope for this decision and not approved here.** Peer
  review flagged that a token compressor in front of `media_ai/llm.py` silently
  mutates prompts inside the AI boundary, colliding with the no-heuristic /
  determinism rules and risking caption fidelity. The only safely adoptable idea
  is **per-content-pack cost/quota telemetry** (an audit-trail surface, env-keyed,
  official APIs only) — if pursued, it must be its own proposal with its own ADR,
  never derived from 9router code.

## Consequences

- **No code changes.** The product, its routes, its AI surfaces, and the
  deterministic engine are untouched. This ADR and the `CLAUDE.md` exclusion are
  the only artifacts.
- **The proposal is durably closed.** Listing 9router alongside the Google
  Workspace exclusion in `CLAUDE.md` means a future agent will not re-raise it
  without an explicit maintainer override.
- **Dev cost/quota pain remains a real, separate problem** — to be solved with
  official prepaid keys and spend caps, tracked outside this decision.
- **A future, honest cost-telemetry feature is left open** as a distinct,
  separately-decided piece of work.
