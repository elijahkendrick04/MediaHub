# MediaHub MCP Server

MediaHub **exposes** a Model Context Protocol (MCP) server so an external
agent — Claude, ChatGPT, Gemini-class — can drive your MediaHub: list runs,
read and approve cards, export packs, query your data hub. It is MediaHub's own
version of "Canva in Claude", pointed at our engine. Part of roadmap **1.21**.

> **Direction matters.** MediaHub *exposes* this server; MediaHub itself depends
> on **no external MCP** (a standing rule — see `CLAUDE.md`). And there is no
> publishing tool: the strongest action an agent can take is *approve a card*,
> which ends at the approval queue and is the human-publish signal — nothing here
> posts to a social account.

## What it is

A thin Model Context Protocol translator over the public
[`/api/v1`](PUBLIC_API.md) surface. Every tool is one API call, authenticated
with an **organisation API token** — so the agent can do exactly what the
token's scopes allow, and no more. One capability definition, one set of gates.

It is dependency-free (the small JSON-RPC surface is implemented directly) and
speaks newline-delimited JSON-RPC 2.0 over stdio, the standard MCP transport.

## Running it

```bash
MEDIAHUB_API_BASE_URL="https://your-mediahub.example/api/v1" \
MEDIAHUB_API_TOKEN="mhk_…" \
python -m mediahub.mcp_server
```

Mint the token in the app under **Organisation → API & webhooks**, granting only
the scopes you want the agent to have (e.g. `runs:read`, `cards:read`,
`cards:approve`).

### Wiring it into a client

Point your MCP-capable client at that command. For a Claude-desktop-style
`mcpServers` config:

```json
{
  "mcpServers": {
    "mediahub": {
      "command": "python",
      "args": ["-m", "mediahub.mcp_server"],
      "env": {
        "MEDIAHUB_API_BASE_URL": "https://your-mediahub.example/api/v1",
        "MEDIAHUB_API_TOKEN": "mhk_…"
      }
    }
  }
}
```

## Tools

| Tool | Does | Scope needed |
|---|---|---|
| `whoami` | The token's org + scopes | any |
| `list_runs` | List pipeline runs | `runs:read` |
| `get_run` | One run | `runs:read` |
| `list_cards` / `get_card` | A run's cards | `cards:read` |
| `approve_card` | Approve (human-publish signal; gated) | `cards:approve` |
| `reject_card` | Reject a card | `cards:approve` |
| `edit_card_caption` | Edit caption overrides | `cards:write` |
| `export_pack` | Build the pack; returns a download pointer | `content:export` |
| `submit_results` | Start a run from a base64 file | `runs:write` |
| `list_brand_kits` | List brand kits | `brand:read` |
| `list_data_tables` | List data-hub tables | `data:read` |
| `list_webhooks` | List webhook endpoints | `webhooks:read` |

A call the token isn't scoped for comes back as a tool error (the underlying
`403 insufficient_scope`), so least privilege is enforced end-to-end.

## Notes

- `export_pack` returns a **download pointer**, not the binary — fetch the ZIP
  from the returned URL with your token.
- Results are returned as JSON text in the tool result content.
- The server never crashes the session on a bad message; protocol/transport
  errors come back as JSON-RPC errors, tool failures as `isError` results.
