# 9. Do not integrate `agentmemory` into the MediaHub repo

- **Status:** Accepted — rejected for integration. `rohitg00/agentmemory`
  will **not** be added to the MediaHub repo in any deployed or committed form
  (no entry in `requirements.txt`, `render.yaml`, the `Dockerfile`,
  `docker-compose.yml`, `src/mediahub/`, or `docs/DEVELOPMENT.md` as a project
  dependency). If a contributor wants agent memory while coding, it is a
  personal, local dev-environment choice that lives outside this repo and off
  the deploy path — like their editor.
  **Superseded in part by [ADR-0025](0025-dev-loop-mcp-tooling.md)
  (2026-06-19):** the maintainer has since decided to commit the *lightweight
  official* `@modelcontextprotocol/server-memory` MCP server as shared dev-loop
  tooling (stdio, single JSON file, no native binary, no ports, store
  gitignored). The rejection of the *heavyweight* `agentmemory` package itself —
  with its `iii-engine` native binary and three ports + WebSocket — stands.
- **Date:** 2026-05-31
- **Deciders:** MediaHub maintainer
- **Method:** Decision adjudicated by the LLM Council
  (`autotest/skills/llm-council/`) — 5 advisors → anonymised peer review →
  chairman synthesis. Verdict was unanimous.
- **Context source:** [`../research/agentmemory-council-2026-05-31.md`](../research/agentmemory-council-2026-05-31.md)
  (full transcript: advisor responses, peer reviews, chairman synthesis). A
  self-contained visual briefing of the same session is at
  [`../research/agentmemory-council-report-2026-05-31.html`](../research/agentmemory-council-report-2026-05-31.html).

## Context

The question put to the council: *"Should MediaHub integrate
`rohitg00/agentmemory`, and if so, as what?"*

What the candidate actually is (verified against the live repository, not taken
on faith):

- **Purpose:** "Persistent memory for AI **coding** agents" — it helps coding
  assistants (Claude Code, Cursor, Copilot CLI, Gemini CLI, and ~20 others)
  remember *codebase* context across development sessions. It is
  developer/agent tooling, **not** an end-user product feature.
- **Shape:** a standalone **TypeScript** service. Requires Node ≥ 20 and the
  `iii-engine` v0.11.2 native binary (or Docker). Runs long-lived background
  processes on ports **3111** (REST + MCP HTTP), **3112** (streams worker),
  **3113** (real-time viewer) and a WebSocket on **49134**. Apache-2.0.
- **No native Python library.** The only integration paths are the REST API on
  3111 and an `iii-sdk` over WebSocket.

MediaHub, by contrast, is a Python/Flask monolith delivered as a **hosted SaaS**
to swim clubs and societies on a single-container Render deployment, with **no
customer self-host path**. Its value is the deterministic intelligence layer
(ingest → detect → rank → brand → generate → approve → export) and the accuracy
of "is this a PB?" / "which card outranks which?".

## Decision

**Do not integrate `agentmemory`.** The reasons converged independently from
every advisor:

1. **Category mismatch.** agentmemory gives memory to a *coding agent*. It
   benefits the developer, never the swim club. It produces nothing in the
   `ingest → detect → rank → brand → generate → approve → export` pipeline — no
   route, card, caption, detection, or ranking gets better. The diagnostic
   test the council applied: nobody can finish the sentence *"…and then the
   swim club gets ____."* A dependency that only benefits the person writing
   the code does not belong in the product.

2. **Runtime hostility to the deployment model.** Integrating means MediaHub
   ships and supervises a second runtime — a Node ≥ 20 process plus the
   `iii-engine` native binary (or a nested Docker sidecar) and three listening
   ports plus a WebSocket — inside a Render container that exists to parse swim
   results and render cards. With no Python client, MediaHub would also have to
   hand-maintain a REST shim. That is image bloat and operational surface for a
   thing customers never invoke.

3. **Security / multi-tenant isolation.** Three open ports and a WebSocket on a
   deployed multi-tenant SaaS container is unrequested attack surface and a
   data-isolation question nobody asked for — directly against the
   multi-tenant-isolation and "no new exposure" focus areas in `CLAUDE.md`.

The correct artifact for this question is **nothing in this repo.** A
coding-agent's memory is part of a contributor's local toolchain, not a
committed, shipped dependency.

## Alternatives considered

The council surfaced and weighed three softer integration shapes; all were
rejected for the repo:

1. **Run it as a deployed sidecar / product dependency.** *Rejected* — reasons
   1–3 above. This is the primary rejected path.

2. **Vendor it as contributor dev-tooling in the repo (e.g. under
   `docs/DEVELOPMENT.md` or a compose profile).** *Rejected.* Even as dev
   tooling it is a category error to commit: a memory aid for *your* coding
   assistant is a personal dev-environment choice, like your editor. It still
   drags in a Node + native-binary runtime and, run anywhere, would index
   **proprietary client code** — a confidentiality consideration. If a
   contributor wants it, they run it locally, outside the repo, never
   committed, with its data dirs ignored.

3. **"Don't ship it — mine the idea."** The Expansionist advisor argued for
   building a Python-native, season-aware **club memory layer** (athlete
   history, recurring sponsors, tone preferences, "already posted this moment"
   dedup) that feeds captioning and ranking. Peer review flagged this as a
   **category slip**: agentmemory is a coding-agent vector/context store and
   shares almost nothing architecturally with the *relational athlete history*
   such a feature would need — so there is no blueprint to "borrow" from this
   tool. The *underlying product insight* (cross-season narrative memory as an
   intelligence-layer moat) is genuinely valuable, but it is a **separate
   product bet** to be decided by the maintainer on its own merits — explicitly
   **not** this tool, and **not** built as part of this decision. See
   *Consequences → Forward note* below.

## Consequences

**Positive**

- The question is settled and auditable: this ADR plus the council transcript
  prevent the integration from being re-litigated or quietly re-proposed.
- The single-container Render deployment stays a single Python runtime — no
  second runtime, no extra ports, no new attack surface, no REST shim to
  maintain.
- The "no fake fallback / honest engine" and multi-tenant-isolation principles
  are upheld: nothing customers never invoke is bundled into their container.

**Neutral**

- No code changes. This decision touches no routes, data structures, parsers,
  detectors, the ranker, AI surfaces, or `DATA_DIR` state, so `CLAUDE.md`'s
  gated removal/replacement checklists do not apply. `requirements.txt`,
  `render.yaml`, the `Dockerfile`, and `docker-compose.yml` are unchanged.
- A contributor may still run agentmemory (or any memory MCP server) **locally**
  on their own machine, pointed at the repo from outside. That is invisible to
  MediaHub and must stay that way — it is not an integration and nothing about
  it is committed.

**Forward note (not a commitment)**

- "Season-aware club memory layer" is recorded here as a *roadmap candidate to
  evaluate separately* — a Python-native, store-backed layer that gives the
  intelligence layer cross-run/cross-season context. It would be designed from
  MediaHub's own data model (organisations → athletes → meets → results →
  detections), not derived from agentmemory. Pursuing it is the maintainer's
  call; this ADR neither approves nor schedules it.
