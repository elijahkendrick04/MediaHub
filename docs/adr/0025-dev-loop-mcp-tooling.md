# 25. Adopt committed dev-loop MCP tooling for the repo

- **Status:** Accepted. A project-scoped MCP configuration is committed to the
  repo so every contributor's Claude Code session shares the same dev-loop
  tooling. This decision **supersedes, in part, [ADR-0009](0009-do-not-integrate-agentmemory.md)** —
  specifically its stance that *any* memory MCP server must never be committed
  (see *Relationship to prior ADRs* below).
- **Date:** 2026-06-19
- **Deciders:** MediaHub maintainer (explicit decision)
- **Method:** Maintainer call. The scope question (which of the proposed MCP
  tools to commit, and in what form) was put to the maintainer directly.

## Context

A set of MCP-based developer tools was proposed for the repo. After the
maintainer reviewed scope, four were adopted:

1. **Playwright MCP** (`@playwright/mcp`) — drives a real browser; lets the
   coding agent exercise MediaHub's own product UI and scrape pages that have
   no API.
2. **Context7** (`@upstash/context7-mcp`) — pulls live, version-specific
   library docs into the session to reduce stale-API hallucinations.
3. **Sequential Thinking** (`@modelcontextprotocol/server-sequential-thinking`)
   — a structured step-by-step planning aid.
4. **Knowledge Graph Memory** (`@modelcontextprotocol/server-memory`) — a
   persistent entity/relationship/observation store across sessions.

All four are **developer-loop tooling**: they help the person (and agent)
writing the code. None is a MediaHub product feature, none is shipped to the
Render container or to customers, and none touches the
`ingest → detect → rank → brand → generate → approve → export` pipeline.

A fifth proposal — an OpenAI **Codex plugin** (a second-LLM in-session
reviewer) — was considered and **dropped at the maintainer's request**: it is
not committed, not declared in `.claude/settings.json`, and requires no setup.

## Decision

Commit the configuration so the tooling is shared rather than re-set-up per
contributor:

- **`.mcp.json`** (repo root) declares four stdio MCP servers launched via
  `npx`: `playwright`, `context7`, `sequential-thinking`, and `memory`. On
  first use each contributor is prompted to approve project-scoped servers.
- **`.gitignore`** excludes `.claude/memory.json` — the memory server's store is
  a contributor's local memory and is **never committed** (repo-state-safe form).
- **`docs/DEVELOPMENT.md`** documents the tooling, the prerequisites, and the
  third-party data-egress caveat.

## Why this is allowed where ADR-0009 said "no"

### Relationship to prior ADRs

**ADR-0009 (`agentmemory`)** rejected committing a memory tool. Two of its three
load-bearing objections do **not** apply to the official
`@modelcontextprotocol/server-memory`:

- ADR-0009 objected to *runtime hostility* — `agentmemory` is a long-lived
  TypeScript service requiring Node ≥ 20 **plus the `iii-engine` native binary**,
  with **three listening ports (3111/3112/3113) and a WebSocket (49134)**. The
  official memory server is a plain **stdio `npx` process** that writes a single
  JSON file: no native binary, no ports, no WebSocket, nothing to supervise.
- ADR-0009 objected to *multi-tenant attack surface* on the deployed container.
  This config is **dev-only** — it is not in `requirements.txt`, `render.yaml`,
  the `Dockerfile`, or `docker-compose.yml`, and never reaches the deployment.

The one objection that **does** still apply is the *category-mismatch* point: a
coding agent's memory benefits the developer, not the swim club. ADR-0009
concluded from this that committing it was a category error. The maintainer has
now decided that **standardising the team's dev-loop tooling is itself worth
committing** — the same reason the repo already commits `.claude/skills/`,
vendored skill packs, and a SessionStart hook. That is an explicit maintainer
override of ADR-0009's no-commit stance, narrowed to the lightweight official
memory MCP and with the store gitignored so **nothing about a contributor's
memory persists in the repo** (which honours ADR-0009's actual data concern).
ADR-0009's rejection of the heavyweight `agentmemory` package itself stands.

### The product AI path is unchanged

MediaHub's customer-facing AI path stays exactly as `CLAUDE.md` mandates:
Gemini-first with Anthropic failover, via `ai_core/llm.py` / `media_ai/llm.py`.
**No customer LLM traffic touches Context7 or the memory server.** The
deterministic engine (parsers, detectors, ranker, colour-science) is likewise
untouched.

## Consequences

**Positive**

- One-clone setup: contributors inherit the same browser-automation, live-docs,
  planning, and memory tooling without manual `claude mcp add` steps (which
  would not persist in the ephemeral cloud sessions anyway).
- Playwright MCP gives the agent a real way to exercise MediaHub's own UI —
  genuinely product-relevant for the `upload → … → export` flow.
- The decision is auditable and will not be re-litigated.

**Caveats / things contributors must know**

- **Third-party data egress.** Context7 sends library/query context to Upstash;
  the memory server stores whatever the agent chooses to remember locally. Do
  not point these at secrets or at proprietary client data you would not share
  with those vendors. API keys stay in `.env` only (never in `.mcp.json`).
- **Prerequisite.** The MCP servers need Node available for `npx`.
- **Not a deploy dependency.** This config must never migrate into
  `requirements.txt`, `render.yaml`, the `Dockerfile`, or `docker-compose.yml`.
  If it ever needs to, that is a new decision.
