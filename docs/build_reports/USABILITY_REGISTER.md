# Usability Register

The durable register the daily usability/QA run maintains for
`https://mediahub-gzwc.onrender.com`.

This file holds the slow-moving truth: the **core user journeys** that must
always work end-to-end, the **live-capability snapshot**, the **issue log**, and
**open proposals**. The append-only narrative of each run lives alongside it in
[`USABILITY_LOG.md`](USABILITY_LOG.md).

Ground rules for this register:

- It lists the **core user journeys** that must always work end-to-end on
  production.
- The **verified-working set only ratchets up** — once a journey is confirmed
  working it stays on the list and is re-checked every run; it is never quietly
  dropped.
- **Every future fixed defect gets a regression test** so it can never silently
  return.
- **All edits are made via Claude Code.**
- First established **2026-06-09**.

---

## Live-capability snapshot (2026-06-09)

Scoped by the shipped-vs-inert test — only capabilities that are actually live
and exercisable on the deployment are treated as testable.

**a) Core content pipeline — LIVE.**
Upload / paste-link → configure → process → review → content builder →
pack / export. Single-org, operator-managed.

**b) Self-serve accounts (Phase C, PC.1) — LIVE, newly detected this run.**
`/signup`, `/login`, `/logout`. Auth is **optional** on this deployment, so a
normal visitor lands on the pinned org without signing in, but the account
routes are live and functional.

**c) Billing (PC.2) — code-complete, awaits operator `STRIPE_*` keys.**
`/pricing` and `/billing` render and honest-error gracefully ("billing not
configured … Free tier fully usable"). Paid tiers show "Unavailable"; no payment
is completable here.

**d) True multi-tenancy, org → workspace (PC.3) — DORMANT (foundation only, not
live).**
Cross-workspace tenant-isolation journeys are **not yet testable**. The existing
cross-**org** tenant-isolation invariant (`_can_access_run`, ADR-0003) remains
in force and guarded.

**e) Inert scaffolding — NOT to be tested as live.**
`/sponsor-post`, `/weekend-preview`, `/session-update`.

---

## Core user journeys

A dynamic list that grows as capabilities ship. Each must work end-to-end on
production.

1. **Home loads** — pinned-org hero + nav / CTAs.
2. **Upload / add input** — `/upload` (file + paste-link), `/make`;
   `/upload/configure` is reached only via a real upload and degrades gracefully
   when opened directly.
3. **Review and approve** — `/review/<run>`: recognition summary, per-card
   approve / reject, Open content builder, Download export, Delete run.
4. **Recognition / why-this-card** — `/recognition/<run>` canonicalises to
   `/review`.
5. **Content pack and export** — `/pack/<run>`, `/pack/<run>/grouped`,
   `/pack/<run>/zip`, `/api/runs/<run>/export`.
6. **Spotlight** — `/spotlight`, `/spotlight/<run>/<swimmer>`.
7. **Audit / PB verification** — `/audit/<run>`, `/ground-truth/<run>`.
8. **Utility pages** — `/activity`, `/status`, `/media-library`, `/research`,
   `/privacy`, `/organisation`, `/organisation/setup`, `/settings-redirects`.
9. **Account flows (LIVE)** — signup → app, login → app, logout, session
   persists, bad-password → graceful 401, duplicate signup → graceful 400,
   short-password / invalid-email → graceful 400, no 500 on any error path.
10. **Graceful failure** — unknown / deleted / malformed run ids → branded
    "Run not found" 404 with recovery links, never a raw 5xx.

---

## Existing guard tests

- **Account / auth:** `tests/test_auth.py`, `tests/test_signup_audits.py`,
  `tests/test_login_idle_timeout.py`, `tests/test_dev_login.py`.
- **Billing:** `tests/test_billing.py`.
- **Cross-tenant isolation (crown jewel):**
  `tests/test_cross_tenant_access.py`,
  `tests/test_run_route_isolation_invariant.py`,
  `tests/test_media_library_profile_isolation.py`.
- **Self-hosted fonts:** `tests/test_self_hosted_fonts.py`.

---

## Issue log

| ID | Date | Severity | Status | Summary | Guard test |
|----|------|----------|--------|---------|------------|
| — | 2026-06-09 | — | — | First usability run: full regression + discovery pass found NO functional defect; production healthy; all routes load; account flows + billing honest-errors + edge/404 states all graceful | — |

---

## Open proposals

These are **NOT defects**. They need operator approval before any change is
made.

**P-1 — Home vs. activity run-count scope.**
The home hero shows `COUNT(*) FROM runs` (deployment-wide, 38) while `/activity`
shows the active org's runs (22). In a single-org deployment a user may read
both as "my runs". The home count is a deliberate deployment-wide hero counter
in `web.py` `home()`, so this is intended-but-imperfect, not a clear bug.
Rescoping would change intended behaviour, so it is logged as a proposal and not
actioned this run.
