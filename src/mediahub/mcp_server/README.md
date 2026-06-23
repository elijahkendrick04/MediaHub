# `mcp_server/` — the MCP server MediaHub exposes (roadmap 1.21)

So a club volunteer can drive MediaHub from Claude/ChatGPT/Gemini. It is a thin
Model Context Protocol translator over the public [`/api/v1`](../api_public/README.md)
surface — one capability definition, one set of scopes and gates.

**Direction:** MediaHub *exposes* this; it depends on **no external MCP**
(standing rule). There is no publishing tool — the strongest action is approving
a card, which ends at the approval queue and never posts to a social account.

## Files

| File | Role |
|---|---|
| `server.py` | Dependency-free MCP over stdio (JSON-RPC 2.0). `handle_message` is unit-testable without a socket; `serve_stdio` is the transport |
| `tools.py` | The tool catalogue (schemas) + dispatch; each tool is one `/api/v1` call |
| `client.py` | `ApiClient` — calls the platform API; transport is injectable (requests by default; Flask test client in tests) |
| `__main__.py` | `python -m mediahub.mcp_server` runner |

## Design

- **Wraps the HTTP API, not internals.** Run-trigger and approval go through the
  same gated endpoints the UI uses, so there is no second code path to keep safe.
- **The token is the authority.** A tool the token isn't scoped for returns the
  underlying `403` as a tool error — least privilege, end to end.
- **No new dependency.** The MCP surface we need (`initialize`, `tools/list`,
  `tools/call`, `ping`) is small and implemented directly, matching MediaHub's
  thin/in-house ethos.

## Testing

`server.handle_message(msg)` processes one decoded JSON-RPC message and returns
the response dict, so the protocol and every tool are testable in-process — point
the `ApiClient` at a Flask test client via `flask_test_transport`. See
`tests/test_mcp_server.py`.

Human docs: [`docs/MCP_SERVER.md`](../../../docs/MCP_SERVER.md).
