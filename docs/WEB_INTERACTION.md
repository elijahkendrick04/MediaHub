# Web interaction — browser automation & web search for Claude Code

This repo wires up two complementary families of MCP server:

1. **Browser automation** (four servers) — so Claude can *operate* the web:
   navigate, click, type, fill forms, log in, drive multi-step flows, and verify
   the running app, not just read pages. The Claude Code equivalent of the
   "Claude in Chrome" coworker experience.
2. **Web search** (three servers) — dedicated, LLM-grade *search* engines that
   return clean, ranked, source-grounded results and clean extracted page
   content. These are the right tool for *finding* information on the open web —
   far better than driving a browser to a search-engine results page and
   screen-scraping it. See [Web search](#web-search--dedicated-search-mcp-servers).

Everything here is already wired up. You do not run any setup command: the
servers are declared in [`.mcp.json`](../.mcp.json) and pre-approved in
[`.claude/settings.json`](../.claude/settings.json), so they auto-start and run
without per-call permission prompts in **every** session in this repo. (The
search servers stay inert until their API key is set in `.env` — see below.)

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

## Web search — dedicated search MCP servers

Browser automation *operates* pages; it is the wrong tool for *finding* things on
the open web. Pointing Playwright at Google and scraping the results page is
fragile (bot walls, shifting DOM, no relevance signal) and wasteful. For search,
this repo ships three purpose-built, LLM-grade search servers that return clean,
ranked, source-grounded results and clean extracted content:

| Server | Package | What it's best at | Free path | Key env var |
| --- | --- | --- | --- | --- |
| `exa` | `exa-mcp-server` | **Neural/semantic search** — finds high-quality sources by meaning, the real quality jump over keyword search. Bundled `web_fetch_exa` returns LLM-ready page content. | ~$10 no-card signup credit, then recurring credits once a card is on file. | `EXA_API_KEY` |
| `tavily` | `tavily-mcp` | **Agent-native search + extract** — pre-cleaned, relevance-ranked results with an optional synthesized answer; `tavily-extract` pulls clean page text without a browser. | **1,000 credits/mo, no card** — the safe always-works default. | `TAVILY_API_KEY` |
| `firecrawl` | `firecrawl-mcp` | **Scrape / crawl / map / extract → clean markdown/JSON**, with a search tool on top. The extraction/crawl leg the two searchers don't cover. | 1,000 credits/mo, no card; plus a keyless hosted tier for zero-setup trial. | `FIRECRAWL_API_KEY` |

### Why these three?

They give maximal capability with minimal overlap: **Exa** is the semantic
searcher (relevance ranking that beats MediaHub's internal keyword
DuckDuckGo/SearXNG), **Tavily** is the agent-native search+extract engine and the
one genuinely no-credit-card free tier, and **Firecrawl** covers deep
page-to-markdown crawl/extract that neither searcher does. All three are
verified-official, actively maintained, and have a free path to trial before any
spend. They were selected over a surveyed field of a dozen candidates.

**Runners-up / swap-ins** if your needs differ:
- **Brave Search** (`@brave/brave-search-mcp-server`, `BRAVE_API_KEY`) — clean
  ranked results from Brave's own **independent index** (a genuine edge if you
  want non-Google/Bing sourcing). Now costs $5/mo credit with a card, so it's
  low-cost rather than free; swap it in for Firecrawl if an independent search
  index matters more than deep extraction.
- **Linkup** (`linkup-mcp-server`, `LINKUP_API_KEY`) — the strongest recurring
  free credits (~$20/mo auto-topped) and top factual-QA scores, but overlaps
  Exa/Tavily as an answer-engine searcher; a swap-in for Tavily, not an addition.
- **Perplexity** (`@perplexity-ai/mcp-server`) is a strong Sonar answer engine but
  effectively paid-only; **Serper** (`serper-search-scrape-mcp-server`) is cheapest
  Google-fidelity SERP at scale but returns raw un-reranked JSON from an unofficial
  community server. Avoid `@modelcontextprotocol/server-brave-search` — it is
  deprecated and superseded by `@brave/brave-search-mcp-server`.

### Search keys (optional)

Each search server stays inert until its key is set in `.env` (env-only — never
hardcode a key in source, per the repo's API-key rule):

```bash
EXA_API_KEY=...          # https://dashboard.exa.ai
TAVILY_API_KEY=tvly-...  # https://app.tavily.com  (no card, 1,000/mo)
FIRECRAWL_API_KEY=fc-... # https://www.firecrawl.dev  (no card)
```

You do not need all three — set only the keys you want. `tavily` is the
easiest to start with (no card). These sit on the dev/research side and are **not**
part of MediaHub's Gemini-first customer AI path.

## When Claude uses them

- **Quick read-only lookup →** use the built-in `WebFetch` / `WebSearch`. No
  server needed.
- **Serious web research / finding sources →** use a **search server** (`exa`
  for semantic relevance, `tavily` for agent-native search+extract, `firecrawl`
  for deep page/crawl extraction). Better ranked, cleaner, and more robust than
  scraping a results page with a browser.
- **Operate a page →** use a **browser server**. Any task that needs to click,
  log in, fill a form, walk a multi-step flow, scrape a stateful/JS-rendered
  site, or check the **running** MediaHub app's real UI behaviour.

Claude reaches for these automatically per the guidance in
[`CLAUDE.md`](../CLAUDE.md) ("Web interaction"). Default browser server:
`playwright`. Default search server: `tavily` (keyless-friendly), or `exa` when
semantic relevance matters.

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

# Web search (set the matching key in the environment first)
claude mcp add exa        --env EXA_API_KEY=...       -- npx -y exa-mcp-server
claude mcp add tavily     --env TAVILY_API_KEY=...    -- npx -y tavily-mcp@latest
claude mcp add firecrawl  --env FIRECRAWL_API_KEY=... -- npx -y firecrawl-mcp
```

Then `/mcp` inside Claude Code to confirm they connected.
