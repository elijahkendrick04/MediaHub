# Live-site monitoring (Tier C) — separate from the autotest pipeline

The autotest finder/fixer (`autotest/`, `.github/workflows/autotest.yml`) runs **every
6 hours inside CI** to find and fix functional bugs. That is **not** uptime/behaviour
monitoring. Real monitoring runs **every 1–5 minutes from outside CI** and pages you.
This folder documents that distinct discipline.

## C1 — external synthetic monitor (Upptime)

We scaffold **[Upptime](https://github.com/upptime/upptime)** (GitHub-Actions-native,
zero-server): a 5-minute cron checks the live URLs, opens a GitHub Issue when one is
down and auto-closes it when it recovers, records response-time history, and can publish
a status page. The two checks are the **primary landing page** and a **`/healthz`
keyword check** (so it verifies *behaviour*, not just a 200).

- Config: [`../.upptimerc.yml`](../.upptimerc.yml) (repo root — Upptime's convention).
- Workflow: [`../.github/workflows/upptime.yml`](../.github/workflows/upptime.yml).

### Enabling it (operator, ~2 minutes)

1. Create a fine-grained **`GH_PAT`** secret with `contents: write` + `issues: write`.
2. Uncomment the `schedule:` block in `.github/workflows/upptime.yml` (every 5 min).
3. (Optional) enable GitHub Pages for the generated status site.

Until step 1, the workflow is **dispatch-only and no-ops** (it warns and skips without
the PAT), so nothing runs wild. Pin `upptime/uptime-monitor-action` to the current exact
version when you enable it.

> Alternative considered: **Checkly** "monitoring-as-code" (reuse a trimmed Playwright
> `*.spec` as a scheduled monitor with Slack/PagerDuty alerts and Web Vitals). We chose
> Upptime to stay GitHub-native and free; switch to Checkly if you want richer browser
> checks + paging. Self-hosted **Uptime Kuma** is the option if you prefer a server.

## C2 — incident hygiene (which channel owns what)

| Event | Channel |
|---|---|
| **Uptime / behaviour** (site down, `/healthz` failing, slow) | Upptime's auto-opened/closed **GitHub Issues** (and a status page) |
| **Confirmed functional bug** (a real defect the finder + council confirmed) | `autotest/notify.py` (the existing operator alert) |

Keeping these separate is the point: **monitoring noise must never reach the autotest
fixer.** The fixer only ever reads the autotest ledger (`autotest/reports/ledger.json`);
it has no path to Upptime's issues, so a flaky uptime blip can't trigger a code change.
