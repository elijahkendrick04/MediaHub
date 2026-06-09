# Usability Log

Append-only daily log for the autonomous usability/QA run against
`https://mediahub-gzwc.onrender.com`. Newest handoff at the top, followed by run
entries newest-first. The slow-moving truth (core journeys, capability snapshot,
issue log, proposals) lives in [`USABILITY_REGISTER.md`](USABILITY_REGISTER.md).

---

## HANDOFF (latest)

- **Production health: HEALTHY** (v4.0.0, `/health` ok). Transient cold-start
  502s on the free box are normal.
- **Open defects: 0** (P1 0 / P2 0 / P3 0). One non-defect proposal **P-1** is
  still logged. No next-up defect.
- **In flight: none half-merged.** This run was a clean regression + discovery
  pass with no defect — docs-only log update only.

---

## Run entries (newest first)

### 2026-06-09 (run 3) — clean regression + discovery pass — no defect

**Capabilities detected live.**
Core content pipeline + meet-recap results-from-a-link LIVE. **PC.1 accounts**
(signup/login/logout) LIVE, auth optional. **PC.2 billing** code-complete
awaiting `STRIPE_*` keys (`/billing` now redirects to `/login?next=/billing`
when signed out). **PC.3 true multi-tenancy** still PARTIAL/BLOCKING —
cross-workspace isolation NOT live, so tenant-isolation journeys remain
dormant. No newly-live capability this run.

**Regression pass.**
Sandbox pytest route/web/responsive slice 280 passed + auth/billing/
cross-tenant-isolation/activity-count guards 77 passed (Playwright-only cases
skipped, chromium absent, pre-existing, not regressions). Live: all
core-journey routes load 200 (home, activity, status, media-library, research,
privacy, organisation, organisation/setup, upload, make, pricing, login,
signup, spotlight, settings) with `/billing` redirecting to login. UX-001
verified STILL fixed — `/activity` stat cards settle to 22 / 3,198 / 21 / 1
(Failed shows "1" not "01"). Review → pack (content builder) → audit → api
status → spotlight journey works for run `d4bc93ee7fa0` (api status done, 188
achievements; audit shows graceful "NO PB AUDIT ON FILE" empty state). Bad run
id → branded "Run not found" 404. No site console errors.

**Discovery.**
Exercised results-from-a-link URL validation end to end: empty, "not a url",
`ftp://`, and `javascript:` all rejected client-side; a degenerate `http://`
(scheme, no host) passes the client regex but the server returns a graceful
400 and the page surfaces the message and RE-ENABLES the Fetch button (no
stuck state, no 500). SSRF guard + per-session rate-limit confirmed in
`/upload/from-url`. No functional defect found.

**Mobile.**
A true device-width pass still not assertable with current browser tooling
(window resize does not change the tab's reported innerWidth, stays 2560);
responsive intent guarded by passing `test_responsive_meta.py` /
`test_responsive_guardrails.py`. Carried forward, not filed as a bug.

**Defects.**
Discovered: 0. Fixed: 0. Regression test added: 0.

**PR.** Docs-only (this log entry).

**Queued next.**
- Mobile device-emulation pass once tooling allows.
- Watch for PC.3 multi-tenancy going live (then tenant-isolation becomes the
  crown-jewel P1).

---

### 2026-06-09 — UX-001 fix: /activity Failed stat "01" → "1"

**Defect fixed (P3 — UX-001).**
The "Failed" summary stat card on `/activity` rendered `01` instead of `1` when
the failed-run count was a single digit. Root cause: the server-side Python
template used `:02d` formatting (which zero-pads single digits) for the initial
`textContent` of all stat cards except Achievements; the count-up animation JS
also lacked thousands-comma formatting. Both surfaces now use the same `:,`
equivalent: no leading zeros, comma separators for thousands (matching the
"3,198" Achievements card that was already correct).

**Changes.**
- `src/mediahub/web/web.py`: three Python f-string stat-card templates changed
  from `:02d` to `:,`; JS `animateCount` gains a `_fmtN` helper that applies
  thousands commas and replaces all three `toFixed(dp)` calls.
- `tests/test_activity_count_up.py`: new server-side + Playwright regression
  guard (skips when Playwright/Chromium absent, matching `test_browser_cascade`
  pattern).

**Defects.**
Discovered: 1 (UX-001). Fixed: 1. Regression test added: 1.

**PR.** `claude/ux-activity-failed-count`.

---

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
