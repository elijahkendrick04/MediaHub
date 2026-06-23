# `api_public/` — the public platform API (roadmap 1.21)

This package is MediaHub's **front door for other software**. It lets a club,
a federation, or an AI assistant drive the same engine the web app drives:
submit results, list and approve cards, export packs, read the data hub — over
plain HTTP and JSON at `/api/v1`.

## The big idea

Everything the platform can do is defined **once**, in `service.py`. Two
adapters sit on top of it:

- the **REST blueprint** (`blueprint.py`) — the `/api/v1` HTTP surface, and
- the **MCP server** (`mediahub.mcp_server`, a sibling package) — the same
  capabilities exposed as tools for Claude/ChatGPT/Gemini.

So there is never a second definition of "approve a card" that can drift.

## How access works

- **Bearer tokens.** Every request carries `Authorization: Bearer mhk_…`. A
  token belongs to exactly one organisation and is created in the app under
  *Organisation → API tokens*.
- **Scopes.** Each token lists the fine-grained permissions it holds
  (`runs:read`, `cards:approve`, `content:export`, …). Each endpoint needs one
  scope. A read-only integration can never approve or export.
- **Only the hash is kept.** The secret is shown once at creation; we store
  `sha256(secret)`. A database leak yields no usable token.
- **Same gates as the app.** Approving a card over the API runs the *identical*
  consent / brand-lock / group-approval checks as the UI, and counts as the
  human-publish signal. Nothing here posts to an external social account.
- **Tenant isolation.** A token only ever sees its own org's data; an unknown
  or other-org id returns `404` (never a "forbidden" that confirms it exists).

## Files

| File | Role |
|---|---|
| `scopes.py` | The least-privilege scope catalogue (one source of truth) |
| `tokens.py` | Org-scoped bearer tokens — mint, verify, list, revoke (sha256-hashed) |
| `service.py` | Capabilities over the engine internals; reads decoupled, writes via callbacks `web.py` registers |
| `blueprint.py` | The Flask `/api/v1` adapter — auth, scope checks, rate limit, JSON errors |
| `openapi.py` | The OpenAPI 3.1 contract, generated from a registry (drift-tested) |
| `ratelimit.py` | Per-token fixed-window limiter (no new infra) |
| `errors.py` | The JSON error-envelope helpers |
| `_db.py` | Shared SQLite helper (the `api_tokens` table in `DATA_DIR/data.db`) |

## Where the rest lives

- Outbound **signed webhooks** are a sibling package (`mediahub.webhooks`).
- The **MCP server** is `mediahub.mcp_server`.
- Human docs: [`docs/PUBLIC_API.md`](../../../docs/PUBLIC_API.md). Live contract:
  `/api/v1/openapi.json`.
