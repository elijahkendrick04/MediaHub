# Web interaction — browser automation & web search for Claude Code

This repo wires up two complementary families of MCP server:

1. **Browser automation** (four servers) — so Claude can *operate* the web:
   navigate, click, type, fill forms, log in, drive multi-step flows, and verify
   the running app, not just read pages. The Claude Code equivalent of the
   "Claude in Chrome" coworker experience.
2. **Web search** (one server) — a dedicated *search* tool for *finding*
   information on the open web, far better than driving a browser to a
   search-engine results page and screen-scraping it. The wired-in server is
   **keyless** — no API key, no account, no card. See
   [Web search](#web-search--dedicated-search-mcp-server).

Everything here is already wired up. You do not run any setup command: the
servers are declared in [`.mcp.json`](../.mcp.json) and pre-approved in
[`.claude/settings.json`](../.claude/settings.json), so they auto-start and run
without per-call permission prompts in **every** session in this repo. The
web-search server needs no key and works out of the box.

## The four servers

| Server | Package | What it's for | Setup needed |
| --- | --- | --- | --- |
| `playwright` | `@playwright/mcp` | **Primary.** Navigate, accessibility snapshot, click, type, fill forms, select, hover, drag/drop, file upload, run JS, inspect network, multi-tab. | None — Chromium is prebaked. |
| `chrome-devtools` | `chrome-devtools-mcp` | Real-Chrome (CDP) driving for DevTools-grade work: network/perf traces, console, deep DOM/CDP. | Downloads its own Chrome on first use. |
| `puppeteer` | `puppeteer-mcp-server` | Chromium automation alternative; overlaps Playwright, kept for parity/fallback. | Downloads its own Chromium on first use. |
| `browserbase` | `@browserbasehq/mcp` | Cloud, Stagehand-powered headless browsers — scale and anti-bot resilience. | API keys (below). |

### Why all four?

`playwright` covers the great majority of "interact with the web" tasks and
works out of the box. `chrome-devtools` adds genuine DevTools/CDP depth.
`puppeteer` is a redundant-by-design fallback. `browserbase` is the only one that
runs *off-box* (in the cloud), which is what you want for scale or sites with
aggressive bot defences. Pick the lightest tool that does the job — default to
`playwright`.

## Web search — dedicated search MCP server

Browser automation *operates* pages; it is the wrong tool for *finding* things on
the open web. Pointing Playwright at Google and scraping the results page is
fragile (bot walls, shifting DOM, no relevance signal) and wasteful. So the repo
also wires in one dedicated, **keyless** web-search server:

| Server | Package | What it's for | Setup needed |
| --- | --- | --- | --- |
| `ddg-search` | `@oevortex/ddg_search` | DuckDuckGo web search (its `web-search` tool returns ranked title/URL/snippet results). No API key, no account, no card. | **None** — keyless, works out of the box. |

### Why keyless, and why this one

The requirement was web search that needs **no API key**. The strong
LLM-grade searchers (Exa, Tavily, Brave, Firecrawl, Perplexity, Linkup, Serper)
all require an API key and usually an account — so they're out.

Among genuinely keyless search MCP servers, most fail in a *server* environment
(this repo runs on Render, behind an egress proxy). Each candidate below was
launched and actually called from the deployment-style container before choosing:

- **`@oevortex/ddg_search`** — ✅ returned real, relevant results through the
  proxy. Scrapes DuckDuckGo HTML. **Chosen.**
- **`duckduckgo-mcp-server`** (PyPI, nickclyde) — inits, but DuckDuckGo bot-blocks
  it server-side (it wants an optional Chrome-impersonation backend). Unreliable
  here.
- **`jina-mcp-tools`** — its Reader is keyless but the server would not initialise
  over stdio in this environment; its *search* tool needs a key anyway.
- **You.com** (`@youdotcom-oss/mcp`, keyless mode) — inits but returns
  near-empty results.
- **`mcp-server-fetch`** (official) — a keyless page *fetcher*, not a searcher, and
  it honours robots.txt so it's blocked on many result pages. The built-in
  `WebFetch` already covers clean page fetching.

Only `@oevortex/ddg_search` reliably works keyless in the deployment egress, so
that is the single server wired in — rather than padding the count with servers
that don't actually work here.

### If you later accept an API key

If you're willing to add one key (env-only, never hardcoded — per the repo's
API-key rule), the quality ceiling is much higher. The no-credit-card options:
- **Tavily** (`tavily-mcp`, `TAVILY_API_KEY`) — agent-native search + extract;
  genuinely free 1,000/mo, no card. The easiest upgrade.
- **Exa** (`exa-mcp-server`, `EXA_API_KEY`) — neural/semantic search; best
  relevance. Small no-card signup credit, then recurring credits with a card.
- **Firecrawl** (`firecrawl-mcp`, `FIRECRAWL_API_KEY`) — scrape/crawl/extract to
  clean markdown; free 1,000/mo, no card.

To add one: put its key in `.env`, then add the server to `.mcp.json` and
`.claude/settings.json` the same way `ddg-search` is wired (see the recipes at
the bottom of this file). These sit on the dev/research side and are **not**
part of MediaHub's Gemini-first customer AI path.

## When Claude uses them

- **Quick read-only lookup →** use the built-in `WebFetch` / `WebSearch`. No
  server needed.
- **Finding sources on the open web →** use the **`ddg-search`** server. Keyless,
  and more robust than scraping a results page with a browser.
- **Operate a page →** use a **browser server**. Any task that needs to click,
  log in, fill a form, walk a multi-step flow, scrape a stateful/JS-rendered
  site, or check the **running** MediaHub app's real UI behaviour.

Claude reaches for these automatically per the guidance in
[`CLAUDE.md`](../CLAUDE.md) ("Web interaction"). Default browser server:
`playwright`. Default search server: `ddg-search`.

## Remote container (Claude Code on the web)

The web container prebakes a Playwright Chromium at `/opt/pw-browsers`, and the
[`SessionStart` hook](../.claude/hooks/session-start.sh) exports
`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, so `playwright` is ready instantly
with no ~300 MB download. `chrome-devtools` and `puppeteer` manage their own
browser binary and may download one on first use; `browserbase` runs in the
cloud and needs no local browser at all.

## Browserbase keys (optional)

`browserbase` stays inert until you set both keys in `.env` (env-only — never
hardcode a key in source, per the repo's API-key rule):

```bash
BROWSERBASE_API_KEY=bb_live_...
BROWSERBASE_PROJECT_ID=...
```

Get them at <https://www.browserbase.com>. Its Stagehand layer reuses the
project's `GEMINI_API_KEY` for natural-language `act`/`extract`/`observe` steps
(passed through in `.mcp.json`); override the model with `--modelName` in the
server args if you prefer another provider.

## Logged-in-session parity (drive a real, authenticated browser)

The default browsers start clean (no cookies/logins). To get the Chrome-extension
"my own logged-in tabs" behaviour, use one of:

1. **Persistent profile** — keep cookies/logins between runs by pointing
   Playwright at a user-data dir:

   ```jsonc
   // .mcp.json → mcpServers.playwright.args
   ["-y", "@playwright/mcp@latest", "--user-data-dir", "./.claude/pw-profile"]
   ```

   (Add `./.claude/pw-profile/` to `.gitignore` — it holds session cookies.)

2. **Attach to your real Chrome over CDP** — launch Chrome yourself with remote
   debugging, then have the server attach to that exact (already-logged-in)
   browser:

   ```bash
   # macOS example
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --remote-debugging-port=9222
   ```

   ```jsonc
   // chrome-devtools: attach instead of launching a fresh Chrome
   ["-y", "chrome-devtools-mcp@latest", "--browserUrl", "http://127.0.0.1:9222"]
   ```

   This is the closest parity to the "Claude in Chrome" extension — Claude drives
   the same browser, and session, you are already signed into.

## Guardrails

Browser automation does **not** change MediaHub's publishing rule: nothing is
placed on an external or social account without explicit human approval (see
"External integrations" in `CLAUDE.md`). Use these servers to test, research, and
drive flows — not to auto-publish. Never point a destructive/automated flow at
the production Render deployment or a customer environment without written
permission.

## Add your own Claude Code (outside this repo)

```bash
# Browser automation
claude mcp add playwright       -- npx -y @playwright/mcp@latest
claude mcp add chrome-devtools  -- npx -y chrome-devtools-mcp@latest
claude mcp add puppeteer        -- npx -y puppeteer-mcp-server@latest
claude mcp add browserbase      -- npx -y @browserbasehq/mcp@latest

# Web search (keyless — nothing to configure)
claude mcp add ddg-search -- npx -y @oevortex/ddg_search@latest

# Optional keyed upgrades (set the matching key in the environment first)
# claude mcp add tavily    --env TAVILY_API_KEY=...    -- npx -y tavily-mcp@latest
# claude mcp add exa       --env EXA_API_KEY=...       -- npx -y exa-mcp-server
# claude mcp add firecrawl --env FIRECRAWL_API_KEY=... -- npx -y firecrawl-mcp
```

Then `/mcp` inside Claude Code to confirm they connected.
