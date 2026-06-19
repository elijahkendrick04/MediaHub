# Web interaction — browser automation for Claude Code

This repo ships four browser-driving MCP servers so Claude can *operate* the web
— navigate, click, type, fill forms, log in, drive multi-step flows, and verify
the running app — not just read pages. They are the Claude Code equivalent of the
"Claude in Chrome" coworker experience.

Everything here is already wired up. You do not run any setup command: the
servers are declared in [`.mcp.json`](../.mcp.json) and pre-approved in
[`.claude/settings.json`](../.claude/settings.json), so they auto-start and run
without per-call permission prompts in **every** session in this repo.

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

## When Claude uses them

- **Read-only research →** use the built-in `WebFetch` / `WebSearch`. No browser
  needed.
- **Operate a page →** use a browser server. Any task that needs to click, log
  in, fill a form, walk a multi-step flow, scrape a stateful/JS-rendered site, or
  check the **running** MediaHub app's real UI behaviour.

Claude reaches for these automatically per the guidance in
[`CLAUDE.md`](../CLAUDE.md) ("Web interaction"). Default server: `playwright`.

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
claude mcp add playwright       -- npx -y @playwright/mcp@latest
claude mcp add chrome-devtools  -- npx -y chrome-devtools-mcp@latest
claude mcp add puppeteer        -- npx -y puppeteer-mcp-server@latest
claude mcp add browserbase      -- npx -y @browserbasehq/mcp@latest
```

Then `/mcp` inside Claude Code to confirm they connected.
