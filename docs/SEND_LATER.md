# Scheduled & automated re-checks — without a third-party tool

Goal: have a Claude Code session pick work back up later — e.g. re-check a PR's
CI, respond to review comments — using only first-party Anthropic features. No
extra notification service, no recurring cost, no committed "phone-home" server.

## The honest constraint (read this first)

"Notify **me** (a human) later" and "wake the **agent** later" are different
problems, and only one of them can be first-party:

- **Wake the agent later** — re-run Claude to continue or re-check work. This is
  fully first-party (Anthropic re-invokes the session) and free. ✅ This is what
  we use.
- **Push a notification to your phone later** — inherently needs an external
  delivery service: a push has to be *held and delivered by something* after this
  session's throwaway VM is gone. There is no first-party-only way to do that
  from the repo, so we don't. ❌ Rejected — no third-party tools (e.g. ntfy).

So the scheduling lives in Anthropic's platform, not in a committed file. This
page is the runbook for turning it on.

## 1. While a session is alive — the in-session Monitor (free, automatic)

When Claude is actively working a PR it watches CI **itself** with the built-in
`Monitor` tool: it polls the PR's *public* check-runs and wakes itself the
moment CI reaches a terminal state — all-green or any failure — then acts (push
a fix, report the green). Nothing to configure, no third party, no cost; the
agent does this on its own. This closes the gap GitHub webhooks leave, since
webhooks don't deliver CI **success**.

Limit: a Monitor lives only as long as the session's VM. For re-checks after the
session is gone, use Routines.

## 2. Across sessions — Routines (the first-party scheduler)

[Routines](https://code.claude.com/docs/en/routines) (the `/schedule` command)
re-run a Claude Code task in the cloud **on a schedule, via API call, or in
response to GitHub events**, against an environment you choose. Unlike a
notification, a routine genuinely **re-runs the agent**; you watch the result in
the Claude mobile app. First-party, no third-party tool.

Set up an hourly PR babysitter:

1. In the Claude Code CLI (signed in to the same account) run **`/schedule`**.
   If cloud access isn't set up it points you to `/web-setup`.
2. Set the cadence (e.g. hourly) and the prompt, for example: *"Check open PRs
   on `elijahkendrick04/mediahub`. If CI is red, diagnose and push a fix; if a
   reviewer left actionable comments, address them. If everything is green and
   clean, do nothing."*
3. Choose the environment and network access for the run.

Routines are the supported home for recurring, durable, self-driving work. A
routine consumes your existing Claude plan's usage when it runs (it's a real
agent run) — it is **not** a separate charge — so prefer a sensible cadence.

## 3. Make a connector available in every session (only if you use one)

Connectors (MCP servers Anthropic routes for you) are enabled **per session or
per routine** in claude.ai — not via a repo file. To have one in *every*
session, enable it on the **environment** so new sessions inherit it, and on
your routines. MCP connector traffic is routed through Anthropic's servers, so
you don't need to add its hosts to the network allowlist.

## What we deliberately did **not** do

No third-party push service (e.g. ntfy) and no committed MCP server for delayed
delivery. A repo tool that pings you later would require an external channel and
an ongoing dependency; the first-party options above do the real job —
re-running the agent — with no third-party tool and no cost.
