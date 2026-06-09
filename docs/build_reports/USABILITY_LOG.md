# Usability Log

Append-only daily log for the autonomous usability/QA run against
`https://mediahub-gzwc.onrender.com`. Newest handoff at the top, followed by run
entries newest-first. The slow-moving truth (core journeys, capability snapshot,
issue log, proposals) lives in [`USABILITY_REGISTER.md`](USABILITY_REGISTER.md).

---

## HANDOFF (latest)

- **Production health: HEALTHY** (v4.0.0, `/health` ok). Brief cold-start 502s
  are normal on the single-CPU free box and recover in seconds.
- **Open defects: 0** (P1 0 / P2 0 / P3 0). One non-defect proposal **P-1** is
  logged. No next-up defect.
- **In flight: none half-merged.** This run shipped a docs-only PR establishing
  the register + log (no code change).

---

## Run entries (newest first)

### 2026-06-09 — first usability run

**Capabilities detected live.**
Core pipeline; **PC.1 accounts** newly live (auth optional); **PC.2 billing**
code-complete awaiting `STRIPE_*` keys (honest-errors); **PC.3 multi-tenancy**
DORMANT (cross-workspace isolation not testable); existing cross-org invariant
intact.

**Regression pass.**
All documented routes load; no 5xx except transient cold-start 502.
`/api/runs/<run>/status` and `/cards` return JSON. `/recognition` and `/runs`
canonicalise to `/review`.

**Discovery.**
Account error paths all graceful (400 / 401, no 500). `/pricing` and `/billing`
honest-error when unconfigured. Bad / malformed / deleted run ids and
configure-without-run return branded recovery pages. Mobile viewport
inconclusive via current tooling — not asserted.

**Defects.**
Discovered: none. Fixed: none. Regression test added: none (the newly-live
account flows are already guarded — see the register's guard-test list).

**Test-account note.**
Two throwaway accounts were created via the product's own public signup with
fake `@mediahub.invalid` emails under the test-account carve-out, then logged
out. No real PII, payment, or credentials were used.

**PR.** Docs-only.

**Queued next.**
- A true mobile-viewport pass with device emulation.
- Drive one full content-pack journey end-to-end with sample data and lock it
  with a Playwright guard.
- Re-check PC.3 capability detection for multi-tenancy going live.
