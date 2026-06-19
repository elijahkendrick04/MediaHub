# Development

Contributor-only setup notes. MediaHub itself is a cloud-hosted SaaS — customers
use it via the deployment URL. This document is for engineers working on the
codebase, not for end users.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install           # pip install -r requirements.txt && pip install -e .
make media-deps        # Playwright Chromium + Remotion node_modules
cp .env.example .env   # add cloud API keys (Gemini and/or Anthropic, Replicate, Photoroom)
make run               # boots the Flask app for development
```

`make media-deps` downloads ~500 MB the first time (Chromium + Remotion). The
HTML→PNG and MP4 pipelines need both; `/healthz/deps` reports which renderers
are available at runtime.

The Flask development server is for engineering iteration only. The customer-
facing product runs on the operator's managed deployment (see
[`DEPLOYMENT.md`](DEPLOYMENT.md)).

## Tests

```bash
make test            # full suite, 287 tests
make test-collect    # collection only
python -m pytest tests/ -q
```

## Motion-graphic / video output (Remotion)

MediaHub generates branded MP4 outputs via Remotion 4.x:
- **Story cards** — 1080×1920, 6 seconds, one card per swimmer/achievement
- **Meet reels** — 1080×1920, 15 seconds, top-3 cards stitched with crossfades

The Node + Remotion stack lives at `src/mediahub/remotion/`. It is invoked
from Python via `src/mediahub/visual/motion.py`, which shells out to
`render.js` and caches outputs under `DATA_DIR/motion_cache/<hash>.mp4`.

### One-time setup

```bash
# Node 18+ (Remotion 4 requirement)
node --version    # must be >= 18

cd src/mediahub/remotion
npm install

# Smoke-test the integration tests (optional)
cd ../../..
MEDIAHUB_RUN_MOTION_TESTS=1 pytest tests/test_motion.py -v
```

If Node is missing, the motion routes return HTTP 500 with a clear
"Node is not installed" error; static graphic generation is unaffected.

### Routes

- `POST /api/runs/<run_id>/card/<card_id>/motion` — render a single story card MP4
- `POST /api/runs/<run_id>/reel` — render the meet reel from the top-N cards
  (default 3, capped at 5; pass `?n=4` to override)

Both endpoints serve the rendered MP4 directly with `Content-Type: video/mp4`.
Cache hits return the existing file (< 30s wall-clock); cold renders take
30–90s depending on the host's CPU.

## API keys for dev

The codebase no longer ships heuristic fallbacks for AI-driven features. To
work on captioning, brand interpretation, creative direction, or any other
AI-mediated surface, configure at least one LLM provider:

- `GEMINI_API_KEY` — default LLM provider (free tier covers most dev work)
- `ANTHROPIC_API_KEY` — optional higher-quality alternative

Without a configured provider, AI-dependent routes surface
`ClaudeUnavailableError` so it's immediately obvious that the provider is
unset rather than silently producing low-quality heuristic output.

## Claude Code dev-loop tooling (MCP servers + Codex plugin)

The repo ships a shared Claude Code tooling config so contributors don't have to
re-add it by hand (and so it survives the ephemeral cloud sessions, where
`claude mcp add` would not). This is **developer tooling only** — none of it is a
product feature, none of it ships to Render, and none of it touches MediaHub's
customer AI path (which stays Gemini → Anthropic via `ai_core/llm.py` /
`media_ai/llm.py`). Rationale and scope: [`adr/0025-dev-loop-mcp-tooling.md`](adr/0025-dev-loop-mcp-tooling.md).

**MCP servers** (declared in `.mcp.json` at the repo root; approve them on first
session, check with `/mcp`):

| Server | Package | What it's for |
| --- | --- | --- |
| `playwright` | `@playwright/mcp` | Drive a real browser — exercise MediaHub's own UI, scrape API-less pages |
| `context7` | `@upstash/context7-mcp` | Pull live, version-specific library docs into the session |
| `sequential-thinking` | `@modelcontextprotocol/server-sequential-thinking` | Structured step-by-step planning |
| `memory` | `@modelcontextprotocol/server-memory` | Persistent cross-session memory; store at `./.claude/memory.json` (gitignored, never committed) |

**Codex plugin** (OpenAI Codex as an in-session second-opinion reviewer). The
marketplace + enable flag are committed in `.claude/settings.json`; finish setup
per-contributor:

```bash
npm install -g @openai/codex     # the Codex CLI (Node 18.18+)
# in Claude Code:
/codex:setup                     # verify install + OpenAI/ChatGPT auth
```

Then `/codex:review`, `/codex:adversarial-review`, and `/codex:rescue` are
available. (The marketplace name is `openai-codex`, so the manual install — if
ever needed — is `/plugin install codex@openai-codex`.)

**Data-egress caveat.** Context7 sends query/library context to Upstash and the
Codex plugin sends code/diffs to OpenAI under *your* credentials. Don't point
them at secrets or proprietary client data. Provider keys live in `.env` only —
never in `.mcp.json` or committed settings.

## Deployment

Production runs on Render via `render.yaml`; see [`DEPLOYMENT.md`](DEPLOYMENT.md)
for the operator-facing deployment instructions. Branch model: feature branches
from `dev`; never merge to `main` without approval.
