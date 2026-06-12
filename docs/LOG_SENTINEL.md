# Log sentinel — production log watchdog with bounded auto-fix

## In plain words

MediaHub now has a night guard. Every minute it reads the server's own logs on
Render — the same lines you see on the dashboard's Logs page — and checks them
against a list of known problems. When it spots one, it sends you a push
message that says what happened, how bad it is, and what to do. If you have
explicitly allowed it, it can also apply one safe fix by itself (restart the
server), never more than a few times a day, and it writes down everything it
sees and does so you can always check its homework.

## What it watches for

| Issue id | Severity | What it means | Can auto-fix? |
|---|---|---|---|
| `searxng_unavailable` | warning | Search backend down, research running on the DuckDuckGo fallback | notify only |
| `searxng_boot_failed` | info | The entrypoint reported SearXNG missing/not answering at boot | notify only |
| `worker_timeout` | critical | A request wedged a gunicorn worker past 300s | **restart** (opt-in) |
| `worker_sigterm_churn` | warning | Workers repeatedly SIGTERMed — the historical memory-pressure signature | notify only |
| `out_of_memory` | critical | MemoryError / OOM signals | **restart** (opt-in) |
| `disk_full` | critical | DATA_DIR's persistent disk is full (a restart will NOT fix this) | notify only |
| `http_5xx` | warning | ≥5 server-error responses in one poll window | notify only |
| `llm_provider_down` | warning | AI surfaces raising honest "unavailable" errors | notify only |
| `unhandled_traceback` | warning | A Python traceback escaped to the logs | notify only |

Detection is deterministic (regex + thresholds — the same philosophy as the
recognition engine: facts are matched mechanically). The optional AI layer only
*summarises* a traceback cluster inside the notification, via the normal
`ai_core.llm` provider chain; with no provider configured it honestly skips.
Routine gunicorn recycling ("Autorestarting worker after current request") is
deliberately **not** an alert.

## Setup (5 minutes)

1. Create a Render API key: dashboard → Account Settings → API Keys.
2. In the service's Environment tab set:
   - `RENDER_API_KEY` — the key (secret)
   - `RENDER_SERVICE_ID` — the `srv-…` id from the service's URL
   - a notify channel: `MEDIAHUB_NTFY_TOPIC` (phone push via ntfy) and/or
     `MEDIAHUB_NOTIFY_WEBHOOK` (Slack/Discord/any JSON endpoint)
3. Redeploy. The sentinel thread starts inside the app (one worker is elected
   leader via a heartbeat lockfile; gunicorn recycling just moves the lease).
4. Verify: open `/healthz/sentinel` — it shows the last poll, what was found,
   and the recent audit trail. Or run `python -m mediahub.log_sentinel check`
   in a Render shell for an end-to-end config validation.

Without step 2 the sentinel idles and `/healthz/sentinel` says so — it never
pretends to be watching.

## Turning on auto-fix (deliberately a double opt-in)

Out of the box the sentinel **only notifies**. To let it restart the service
for a specific issue:

```
MEDIAHUB_SENTINEL_AUTOFIX=1                  # global switch
MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT=1   # plus one per trusted issue
MEDIAHUB_SENTINEL_AUTOFIX_OUT_OF_MEMORY=1
```

Every action must still pass ALL of these gates (same philosophy as the
publishing gate in `publishing/publish_gate.py`):

- **Kill switch** — `MEDIAHUB_SENTINEL_KILL=1` stops all actions instantly;
  notifications keep flowing (observability never turns off).
- **Daily cap** — max `MEDIAHUB_SENTINEL_MAX_ACTIONS_PER_DAY` (default 4)
  actions per UTC day.
- **Per-issue cooldown** — same issue not acted on again within
  `MEDIAHUB_SENTINEL_ACTION_COOLDOWN` (default 6h).
- **Boot grace** — no action within `MEDIAHUB_SENTINEL_RESTART_GRACE` (default
  10 min) of process start, so a restart loop can never feed itself.
- The action is claimed in persisted state **before** it runs, so the sentinel
  that boots after its own restart still sees the caps.

Why restart is the only v1 action: it is generic, reversible, and exactly what
an operator does by hand for a wedged/OOM service. Fixes that need code or
config changes are notified with a precise diagnosis instead — those belong in
a human's hands (or a Claude Code session), not a log-watching daemon. The
decision record is [`adr/0017-log-sentinel-bounded-autoremediation.md`](adr/0017-log-sentinel-bounded-autoremediation.md).

## Where its memory lives

Everything is under `DATA_DIR/log_sentinel/` on the persistent disk:

- `audit.jsonl` — append-only ledger: every finding, notification, gate
  decision and action outcome ("why did/didn't the bot act?" is always
  answerable).
- `state.json` — the log cursor, per-issue cooldown timestamps, daily action
  counter.
- `status.json` — last-poll snapshot served by `/healthz/sentinel`.
- `leader.json` — the polling-leader heartbeat.

## Running it outside the app

The same loop runs anywhere with the env vars set:

```
python -m mediahub.log_sentinel check    # validate config end-to-end
python -m mediahub.log_sentinel once     # one poll cycle, print summary
python -m mediahub.log_sentinel run      # foreground loop
python -m mediahub.log_sentinel status   # last snapshot + audit tail
```

One honest limitation to know: the in-app sentinel can't report a *total*
outage (if the whole service is down, the watchdog inside it is down too —
that case is covered by Render's own health checks on `/healthz`). It exists
to catch the quieter failures: the app that is up but degraded.
