# SearXNG search (in your MediaHub server)

MediaHub can search the web in two ways:

1. **DuckDuckGo** — free, always on, no setup. This is the default and the
   safety net.
2. **SearXNG** — a free "super-searcher" that asks many search engines at once
   (Google, Bing, Wikipedia, …) and combines the results. Sturdier and broader.

On this deployment, SearXNG runs **inside your existing MediaHub server** — no
second service, no extra bill. It's a separate little program living in the same
box, and MediaHub talks to it privately (only MediaHub can reach it; it's not on
the public internet).

## Is it on?

It's controlled by one setting in your Render dashboard:

- `MEDIAHUB_RUN_SEARXNG = 1` → SearXNG **on** (this is the default here).
- `MEDIAHUB_RUN_SEARXNG = 0` → SearXNG **off**; MediaHub uses DuckDuckGo.

When it's on, MediaHub points itself at the in-container SearXNG via
`MEDIAHUB_SEARCH_ENDPOINT = http://127.0.0.1:8888` (already set for you).

## How do I know it's actually working?

If SearXNG is running, web-research results come back tagged `searxng`. If it
isn't (for any reason), **MediaHub automatically falls back to DuckDuckGo** —
research keeps working either way, you just don't get the multi-engine upgrade.
So there is never a broken state: worst case is "quietly using DuckDuckGo."

## When should I turn it off?

Your server has a fixed amount of memory. Making videos already uses a lot of
it. SearXNG adds roughly 150–250 MB. If you ever notice the app restarting a lot
or memory warnings (check `/healthz/memory`), set `MEDIAHUB_RUN_SEARXNG = 0` in
Render and redeploy — that turns SearXNG off and frees the memory immediately,
with no other effect (MediaHub goes back to DuckDuckGo).

## Troubleshooting: "SearXNG unavailable" in the logs

Quick check: open `/healthz/search`. It tells you which engine is really in
use, whether SearXNG answered a live probe, and whether the circuit breaker is
open.

How the pieces fail safe (hardened after the June 2026 incident, where the
image silently shipped without SearXNG and every research query warned about
it):

- **Install** — SearXNG's `setup.py` imports its own package, so the Dockerfile
  installs SearXNG's pinned `requirements.txt` first and then installs with
  `--no-build-isolation`, pinned to a verified commit (`SEARXNG_REF`). The
  build log prints `searxng OK` on success and a WARN line on failure (the
  image still builds — MediaHub just uses DuckDuckGo).
- **Boot** — the entrypoint waits (up to 20s) for SearXNG to actually answer on
  127.0.0.1:8888. If it doesn't, it prints the tail of `/tmp/searxng.log` into
  the deploy log and **unsets `MEDIAHUB_SEARCH_ENDPOINT`** so the app is
  honestly on DuckDuckGo instead of probing a dead port on every query.
- **Runtime** — if SearXNG dies later, the first failed query logs ONE warning
  and opens a circuit breaker (`MEDIAHUB_SEARCH_BREAKER_COOLDOWN`, default 5
  minutes of silent DuckDuckGo); a `/healthz/search` probe that succeeds closes
  it immediately. No more one-warning-per-query spam.

## Licensing note

SearXNG is AGPL-3.0 and is run **stock and unmodified** — MediaHub only sends it
search queries over localhost; it never changes SearXNG's code. See
`THIRD_PARTY_LICENSES.md`.
