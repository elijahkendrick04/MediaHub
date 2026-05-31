# 2. Do not integrate jcode into MediaHub

- **Status:** Accepted — declined. The proposal to integrate
  [`jcode`](https://github.com/1jehuang/jcode) into the MediaHub repository as a
  "skill" is rejected. No code, dependency, vendored tree, or build step is added
  as a result of this decision.
- **Date:** 2026-05-31
- **Deciders:** MediaHub maintainer, via the `llm-council` skill (5 advisors +
  anonymised peer review + chairman synthesis)
- **Context source:** Full deliberation in
  [`0002-no-jcode-integration-council-transcript.md`](./0002-no-jcode-integration-council-transcript.md)

## Context

The maintainer asked the council whether `jcode` should be integrated into
MediaHub as a skill.

**What jcode is.** A terminal-based, multi-session AI **coding-agent harness** —
a Claude Code competitor — that is roughly 95% Rust (MIT licensed). Its feature
set is developer-facing: multi-agent "swarm" workflows, embedding-based agent
memory, support for 20+ LLM providers, browser automation, and agent
self-modification. It ships **no `SKILL.md`**; it was not built to be a Claude
Code skill.

**What MediaHub is.** A hosted Python/Flask content-automation SaaS whose
defensible moat is a swimming-results-to-content intelligence layer
(ingest → detect → rank → brand → generate → approve → export). The critical
engine — parsers, detectors, the ranker, colour science — is deliberately
deterministic; AI surfaces are Gemini-first with Claude failover and must
surface honest errors rather than heuristic fallbacks.

A "skill" in this repo is a Markdown `SKILL.md` capability the agent/pipeline can
invoke — not a vendored binary. So "integrate jcode as a skill" is already
mis-shaped at the tooling layer: there is nothing to file.

## Decision

**Do not integrate jcode** — not as a product skill, not vendored into the repo,
not as a dependency, and not as a build step.

Four of the five council advisors reached "no" independently; the chairman
concurred. The reasoning:

1. **Category error / zero pipeline value.** jcode is a tool for *building
   software*, not for turning swim results into content. It touches no stage of
   ingest → detect → rank → brand → generate → approve → export. A swim club pays
   for content, not for an embedded Rust agent swarm — it fails every MediaHub
   product-principle gate ("Would someone pay for this as a standalone feature?").

2. **Security liability in a multi-tenant SaaS.** Agent self-modification +
   swarm + browser automation embedded in a hosted product that handles
   per-club data is a remote-code-execution and tenant-isolation surface that
   would have to be actively suppressed. This is antithetical to the security
   focus areas (IDOR, multi-tenant isolation, secrets hygiene).

3. **Direct contract collisions.** "20+ LLM providers" contradicts the
   Gemini-first / Claude-failover provider contract (`ai_core/llm.py`); a
   self-modifying, multi-provider agent collides with the env-only-keys rule and
   the no-fake-fallback honest-error rule.

4. **Stack and supply-chain drag.** A ~95% Rust project would pull a Cargo
   toolchain into the Python/Flask Docker image, CI, and the Render deploy —
   build-time, image-size, and second-ecosystem cost for no product gain.
   Vendoring a single-author MIT repo means inheriting its CVE/supply-chain
   surface with no SLA, forever.

## Rejected alternative — "mine the patterns"

One advisor (the Expansionist) argued a softer path: don't vendor the binary,
but study jcode's swarm orchestration, embedding memory, and provider-routing
*patterns* as an MIT "pattern library" to inform MediaHub's own orchestration as
it scales sport-agnostic.

This is **noted but not adopted as work.** Peer review flagged it as the
deliberation's biggest blind spot: it quietly assumes MediaHub should grow its
own LLM orchestration/memory layers, which collides with the settled
deterministic-engine boundary (parsers/detectors/ranker stay non-AI) and the
Gemini-first contract. Reading another project's architecture for inspiration is
always allowed and needs no repo change; it ranks well below parser accuracy and
the review/approve UX, and must never breach the deterministic-engine boundary
or introduce a parallel, ungoverned provider router.

## Consequences

- The repository is unchanged except for this decision record and its transcript.
  No Rust toolchain, no `vendor/jcode`, no new dependency, no new route or data
  structure.
- If a contributor wants jcode as a personal coding assistant, that is a
  workstation/dev-environment choice on their own machine — it has no place in
  the MediaHub product repo, its Docker image, its CI, or its attack surface
  (which holds `ANTHROPIC_API_KEY`).
- The constructive carve-out (pattern-inspiration only) is recorded here so a
  future agent does not re-litigate the same ground or mistake "interesting
  architecture" for "belongs in the product."
