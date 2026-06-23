# MediaHub Platform API (`/api/v1`)

MediaHub exposes a versioned, first-party HTTP API so clubs, federations, and
AI assistants can drive the engine they already use — **submit results, list and
approve cards, export packs, query the data hub** — without screen-scraping the
app. This is roadmap item **1.21** (the platform surface). It sits beside two
siblings: outbound **signed webhooks** (see [`WEBHOOKS.md`](WEBHOOKS.md)) and a
first-party **MCP server** (see [`MCP_SERVER.md`](MCP_SERVER.md)).

> **MediaHub never posts to a social account.** Approving a card over the API is
> the human-publish signal and runs the same consent and brand checks as the UI;
> the approved content is then exported/downloaded for a person to post. There is
> no machine path to an external social channel.

## Authentication

Every request (except the public meta endpoints) carries an **organisation API
token** as a bearer credential:

```
Authorization: Bearer mhk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Mint and revoke tokens in the app under **Organisation → API tokens**
(`/organisation/api`, owner/operator only). The secret is shown **once** at
creation — copy it then; only its sha256 hash is stored, so it can never be
shown again. A token belongs to exactly one organisation and only ever sees that
organisation's data.

### Scopes (least privilege)

Each token carries an explicit set of scopes, and each endpoint needs exactly
one. Grant only what an integration needs.

| Scope | Allows |
|---|---|
| `runs:read` | List and read pipeline runs |
| `runs:write` | Submit results and start runs |
| `cards:read` | Read generated cards and captions |
| `cards:write` | Edit card captions |
| `cards:approve` | Approve / reject cards (the human-publish signal) |
| `content:export` | Export approved content packs |
| `data:read` / `data:write` | Read / write the org data hub |
| `brand:read` | Read brand kits |
| `media:read` / `media:write` | Read / upload media |
| `webhooks:read` / `webhooks:manage` | List / manage webhook endpoints |

A request missing the required scope returns `403 insufficient_scope` with the
scope it needed.

## Conventions

- **Base path:** `/api/v1`. The machine-readable contract is at
  `/api/v1/openapi.json` (OpenAPI 3.1).
- **Responses:** JSON, except `/export`, which streams a ZIP.
- **Errors:** a stable envelope — `{"error": "<code>", "message": "<sentence>"}`
  — with a matching status (`401` no/!valid token, `403` scope/forbidden,
  `404` unknown *or* not-yours, `429` rate limited).
- **Rate limit:** a fixed window (default 120 req/min per token), surfaced in
  `X-RateLimit-Limit` / `-Remaining` / `-Reset`. Tunable with
  `MEDIAHUB_API_RATELIMIT_PER_MIN` (0 disables).
- **Tenant isolation:** an id that isn't yours returns `404`, never a `403` that
  would confirm it exists.

## Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/` | — | Service index |
| GET | `/health` | — | Liveness |
| GET | `/openapi.json` | — | This contract |
| GET | `/me` | (any token) | The calling token's org + scopes |
| GET | `/runs` | `runs:read` | List runs (`?limit`, `?offset`) |
| POST | `/runs` | `runs:write` | Submit a results file → start a run |
| GET | `/runs/{id}` | `runs:read` | One run |
| GET | `/runs/{id}/cards` | `cards:read` | A run's cards (`?status`) |
| GET | `/runs/{id}/cards/{cid}` | `cards:read` | One card |
| POST | `/runs/{id}/cards/{cid}/approve` | `cards:approve` | Approve (gated) |
| POST | `/runs/{id}/cards/{cid}/reject` | `cards:approve` | Reject |
| PATCH | `/runs/{id}/cards/{cid}` | `cards:write` | Edit captions (`{"edits": {…}}`) |
| GET | `/runs/{id}/export` | `content:export` | Download the pack ZIP |
| GET | `/brand-kits` | `brand:read` | List brand kits |
| GET | `/data/tables` | `data:read` | List data-hub tables |

## Quickstart

```bash
BASE="https://your-mediahub.example/api/v1"
TOKEN="mhk_…"

# Who am I?
curl -s "$BASE/me" -H "Authorization: Bearer $TOKEN"

# Submit a results file and start a run.
curl -s -X POST "$BASE/runs?file_name=gala.hy3" \
  -H "Authorization: Bearer $TOKEN" \
  --data-binary @gala.hy3

# List runs, then a run's cards.
curl -s "$BASE/runs" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/runs/$RUN_ID/cards" -H "Authorization: Bearer $TOKEN"

# Approve a card (runs the same consent/brand checks as the app).
curl -s -X POST "$BASE/runs/$RUN_ID/cards/$CARD_ID/approve" \
  -H "Authorization: Bearer $TOKEN"

# Export the approved pack.
curl -s "$BASE/runs/$RUN_ID/export" -H "Authorization: Bearer $TOKEN" -o pack.zip
```

```python
import requests

base = "https://your-mediahub.example/api/v1"
s = requests.Session()
s.headers["Authorization"] = "Bearer mhk_…"

run = s.post(f"{base}/runs", params={"file_name": "gala.hy3"},
             data=open("gala.hy3", "rb").read()).json()
cards = s.get(f"{base}/runs/{run['id']}/cards").json()["cards"]
for c in cards:
    s.post(f"{base}/runs/{run['id']}/cards/{c['id']}/approve")
```

## What's deliberately *not* here (yet)

- **No CORS** — the API is for server-to-server and agent use. Browser-embedded,
  read-only views of approved content are the embed surface (roadmap 1.21 build 4),
  not this token API.
- **No GWS connectors** — Gmail/Drive/Calendar stay excluded (standing rule).
  Cloud-file import is generic remote-fetch + upload; calendars are ICS export.
- **No third-party app marketplace** — demand-gated long-term; "apps" today are
  MediaHub's own modules.
