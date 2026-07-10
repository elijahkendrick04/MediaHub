# Feature audit — System status (Settings → System status, `/status`, `/api/status`)

**Mode:** AUDIT+FIX  **Auditor session branch:** `claude/system-status-audit-9bbtbn`
**Date:** 2026-07-10  **Verdict:** WORKS-WITH-CAVEATS (fixes applied; residuals logged)

---

## 1. Scope contract

**Definition.** "System status" is MediaHub's operational-health surface: a public
trust signal that reports whether the deployment is up, backed by a heartbeat-density
uptime log. "Working" means: the public page and JSON honestly report up / down /
unknown and real uptime numbers derived from heartbeats (never a fake 100%); the
operator view adds uptime windows, incidents and version; every heartbeat that goes
into the store reads back correctly on every surface; and none of the public surfaces
leak internal detail, crash, or mislead.

**Routes/endpoints owned.**

| Endpoint | Method | Handler | Audience |
|---|---|---|---|
| `/status` | GET | `status_page` | Public 3-state card; operator gets full uptime/incident/version detail. Sets `Refresh: 60` + `Cache-Control: no-store`. |
| `/api/status` | GET | `api_status_json` | Public JSON twin (uptime windows + gaps) for external monitors. |
| `/settings/status` | GET | `settings_section("status")` → `_render_settings_status_public_section` | In-app public status card (org-gated members surface). |
| Settings landing "System status" card | — | `_settings_card_specs` | Discovery tile. |
| `/settings/developer` (operator) | GET | `_render_settings_developer_section` = status detail + deployment section | Operator-only detail. |

**Heartbeat feeders (dependencies, audited as the data source):** `/healthz` (`healthz`),
`/health` (`health`, returns 200/503 + records real `ok`), `_health_payload`,
`_record_heartbeat_safe`, the in-process heartbeat queue + drain thread.

**Files owned (blast radius).**
- `src/mediahub/observability/uptime.py` — the SQLite heartbeat store + uptime maths.
- The status-specific functions inside `src/mediahub/web/web.py` (shared monolith —
  edits kept minimal and confined to the status functions; see §7).
- `tests/test_status_and_usage_pages.py`, `tests/test_status_unavailable_state.py`,
  `tests/test_uptime_log.py`.

**Shared files depended on but NOT freely rewritten.** `web.py` app factory / org gate /
`_layout` chrome / footer; `web/auth.py` (`is_dev_operator`). Only the status functions
in `web.py` were touched.

**Inputs/outputs.** Input: HTTP GETs; heartbeats written by `/healthz` + `/health`
(and any external monitor polling them). Output: HTML status pages + a JSON payload.
State persisted: `DATA_DIR/data.db` table `uptime_heartbeats` (id, ts, ok, source,
response_ms, error), pruned to ~90k rows above 100k.

**Intended happy path.** Fresh deploy with no heartbeat → "Status unavailable" (honest,
not green). After an OK `/healthz` heartbeat → "Website operational". A `/health`
failure or a >30-min silence → "Website down". Operator `/status` shows 24h/7d/30d
uptime %, heartbeats, downtime, last incident, and the backend version, auto-refreshing
every 60s.

---

## 2. Environment

- Python 3.11, Flask 3.1, deps from `requirements.txt` installed (`--ignore-installed PyYAML`).
- Local `.env` created with **dummy** values only (`DATA_DIR`, `FLASK_SECRET_KEY`); `.env`
  is gitignored and never staged. No real provider keys; **no real API spend** — the
  status feature makes no LLM/provider calls, so no stubbing was needed. The
  "No LLM provider configured" boot warning is expected and irrelevant to this feature.
- Driven three ways: Flask `test_client` (fresh `DATA_DIR` per test via `importlib.reload`),
  a live `app.run` on `http://localhost:5001`, and Playwright (prebaked Chromium at
  `/opt/pw-browsers/chromium-1194`) for public + operator screenshots at desktop (1280)
  and mobile (375) widths.
- App boots clean: 502 routes.

---

## 3. Test matrix results

| # | Dimension | Result | Evidence |
|---|---|---|---|
| 1 | Functional correctness (uptime maths) | **PASS** (core maths verified by hand: grace-window, `failed*60`, clamp, cross-surface consistency) with 1 honesty defect fixed | workflow functional-correctness agent + `test_uptime_log.py` |
| 2 | Every interactive control / links | **PASS** after fix | all operator-dashboard/status links GET 200; 1 misroute fixed (SS-02) |
| 3 | Input validation / edge cases | **PASS** | malformed/naive/empty/future ts → graceful (unknown/has_data=False); weird `window_hours` normalised; existing `test_uptime_log` coverage |
| 4 | UI state (loading/empty/error/success) | **PASS** after fix | empty→"no data", outage→honest downtime (SS-03), error→degraded not 500 (SS-05) |
| 5 | Server-side error handling / no 500s | **PASS** after fix | forced observability raise: operator `/status` now 200 degraded, no traceback leak in prod |
| 6 | Data integrity | **PASS** | heartbeat in == read-back out on all three surfaces; retention sweep correct; idempotent re-requests |
| 7 | Security (authz / disclosure / injection / CSRF) | **PASS** after fix | `/api/status` path-leak fixed (SS-01); `source`/`error` server-set (no XSS vector); `/developer` password-protected (ADR-0019), not passwordless; no secrets in any response |
| 8 | Performance | **PASS (with caveat)** | `/api/status` ≈215 ms on a 43k-row store; 30d window scanned twice — logged SS-08 |
| 9 | Responsive / a11y | **PASS (minor)** | no mobile overflow (public + operator, 375px); status dot colour-only but always paired with text; SS-09 logged |
| 10 | Rendered-graphic correctness | **N/A** | feature renders no card graphics |
| 11 | Consistency / copy (British English, plain hyphens) | **PASS (minor)** | copy is British English; public/operator threshold tension logged SS-06; "longer than 5 min" vs `>=` logged SS-07 |

---

## 4. Findings

| id | sev | title | status | commit |
|---|---|---|---|---|
| SS-01 | P2 | `/api/status` (public, unauth) echoes heartbeat `error` text → leaks internal filesystem paths | **fixed** | see §5 |
| SS-02 | P3 | Settings landing "System status" card misroutes signed-out / no-org visitors to org setup | **fixed** | see §5 |
| SS-03 | P2 | Ongoing total outage rendered as "no data yet / —" on any window with no in-window heartbeats | **fixed** | see §5 |
| SS-04 | P3 | Uptime cell rounds to "100%" beside a non-zero Downtime cell on the same row | **fixed** | see §5 |
| SS-05 | P3 | Operator `/status` had no try/except around the uptime calls → unhandled 500 if the store raised (settings twin already guarded) | **fixed** (operator `/status`) | see §5 |
| SS-06 | P3 | Public "operational" (age ≤ 30 min) vs operator "stale" (age > 5 min) disagree on the same heartbeat | **logged** (intentional) | — |
| SS-07 | P3 | `recent_gaps` lists a gap of exactly 300 s as an incident (`>=`) while `uptime_stats` counts 0 downtime (`>`); page copy says "longer than 5 minutes" | **logged** | — |
| SS-08 | P2 | `/api/status` loads all window rows into Python and scans the 30-day window twice (`uptime_stats` + `recent_gaps`) → ~215 ms per poll on a full store | **logged** (residual) | — |
| SS-09 | P3 | Public status colour dot has no `aria-hidden`/label (decorative); state text is present alongside so screen readers still get it | **logged** | — |

**Reproductions & root causes (fixed items):**

- **SS-01.** Seed `record_heartbeat(ok=False, source="health", error="database: unable to open
  database file /home/user/MediaHub/data/data.db")`, then GET `/api/status`. Before: the raw
  `error` (with the absolute DB path) appears in the public JSON's `latest_heartbeat.error`.
  Root cause: `api_status_json` returned `latest_heartbeat()` verbatim; on a `/health` failure
  the recorded `error` is `_health_payload`'s raw `str(e)`, which can carry an absolute path or
  OS error. The operator HTML views never render `error`, so only the public JSON leaked.
- **SS-02.** No org / signed out, `ENFORCE_ORG_GATE=True`: GET `/settings` (200) → the
  "System status" tile's href was `/settings/status`; following it 302s to `/organisation/setup`,
  while the public `/status` is 200 for the same session. Root cause: the tile targeted the
  org-gated `settings_section`, not the gate-exempt `status_page`.
- **SS-03.** Non-empty store whose last heartbeat is 48 h old: `uptime_stats(24h)` returned
  `has_data=False, samples=0` (renders "—") while `uptime_stats(7d)` returned real downtime.
  Root cause: `if not rows: return default` conflated "empty store" with "no rows in this window"
  — the latter is a live 100%-downtime outage.
- **SS-04.** 30 days of 5-min heartbeats with one failure → `uptime_pct≈0.99998, downtime=60s`;
  the 30-day row rendered `100% … 1 min`. Root cause: `_format_uptime_pct` returned "100%" for
  `pct>=99.995` regardless of counted downtime.
- **SS-05.** Monkeypatch `uptime.uptime_stats`/`latest_heartbeat`/`recent_gaps` to raise, GET
  operator `/status`: before, an unhandled 500 (traceback in `TESTING`, generic 500 in prod);
  the settings-section twin already degraded gracefully. Root cause: the operator branch called
  the five uptime functions without the try/except `_render_settings_status_section` already had.

---

## 5. Fixes applied

All fixes are minimal and confined to the status functions / the uptime module.

1. **SS-01** — `web.py::api_status_json`: drop `error` from the public `latest_heartbeat`
   before serialising (`latest.pop("error", None)`). The `ok` flag still signals failure
   honestly; no internal text is exposed. (`src/mediahub/web/web.py`)
2. **SS-02** — `web.py::_settings_card_specs`: point the "System status" tile at
   `url_for("status_page")` (public, gate-exempt) instead of `settings_section(section="status")`.
   Operators still reach full detail via the Developer card. (`src/mediahub/web/web.py`)
3. **SS-03** — `uptime.py::uptime_stats`: only early-return the "no data" default when the
   store is truly empty (`first_row is None`); when the store is non-empty but the window is
   empty, fall through so the tail-gap maths scores the ongoing outage as ~0 % uptime with
   real downtime and a populated `tracking_since`. (`src/mediahub/observability/uptime.py`)
4. **SS-04** — `web.py::_format_uptime_pct`: return "99.99%" instead of "100%" when the window
   has counted downtime (`downtime_seconds > 0`); "100%" is reserved for a gap-free window.
   (`src/mediahub/web/web.py`)
5. **SS-05** — `web.py::status_page` operator branch: wrap the five uptime calls in try/except;
   on any unexpected error, degrade to the honest public status section (same fallback shape the
   settings twin uses) rather than 500. (`src/mediahub/web/web.py`)

**Files touched:** `src/mediahub/observability/uptime.py`, `src/mediahub/web/web.py` (status
functions only), plus the three test modules below.

---

## 6. Tests added / extended

Extended existing modules (no parallel harness):

- `tests/test_status_and_usage_pages.py`
  - `TestApiStatusJsonShape::test_public_json_does_not_leak_heartbeat_error_text` — locks SS-01.
  - `TestOperatorStatusHonestyAndResilience::test_window_with_downtime_never_renders_bare_100pct`
    — locks SS-04.
  - `TestOperatorStatusHonestyAndResilience::test_operator_status_degrades_not_500_when_observability_raises`
    — locks SS-05.
  - `TestSettingsSystemStatusCardReachable::test_landing_card_points_at_public_status_and_resolves_without_org`
    — locks SS-02.
- `tests/test_uptime_log.py`
  - `TestUptimeStatsYoungStore::test_ongoing_outage_not_hidden_as_no_data_in_short_window` — locks SS-03.
- `tests/test_status_unavailable_state.py`
  - Fixture now reloads the `uptime` module (not just `web`) so the "no heartbeat" premise is
    hermetic — a pre-existing order-dependency (module-level `DB_PATH`) that surfaced once new
    heartbeat-seeding tests changed test ordering. This hardens isolation; it does not weaken
    any assertion.

---

## 7. Cross-cutting changes

- **`src/mediahub/web/web.py` (shared monolith).** Edited **only** the status functions
  (`api_status_json`, `_settings_card_specs` status tile, `_format_uptime_pct`, `status_page`
  operator branch). No app-factory, gate, base-template, shared-CSS/JS, config, or dependency
  changes. Net +44 lines, all inside status functions — small, localised, low conflict surface.
  Flagged here for reconciliation against other parallel sessions editing `web.py`.
- No changes to `requirements.txt` / `pyproject.toml` / shared templates / shared CSS.

---

## 8. Residual risks & logged (not fixed) items

- **SS-06 (logged, intentional).** The public page tolerates a 30-min heartbeat gap before
  declaring "down"; the operator page flags "stale" after 5 min. Tightening the public
  threshold would cause false "Website down" alarms during normal brief ping gaps, which is
  worse on a public trust page. Left as a deliberate design tension — recommend a product
  decision, not a code fix, if the "Everything is running normally" copy is felt too strong.
- **SS-07 (logged).** Exactly-300-second gaps are an incident but 0 downtime, and the incidents
  copy says "longer than 5 minutes" while `recent_gaps` uses `>=`. Astronomically rare with real
  timestamps; a one-line boundary/copy alignment would fix it but was left out to avoid churn in
  the shared `recent_gaps` default.
- **SS-08 (logged, residual — P2 perf).** `/api/status` is public and monitor-polled; it loads
  every in-window row into Python for three windows and scans the 30-day window twice
  (`uptime_stats(30d)` + `recent_gaps(30d)`), ≈215 ms on a 43k-row store (bounded by the ~90–100k
  retention cap, so worst case ≈0.4–0.5 s). Not pathological, but a candidate for a short-TTL
  response cache or a single SQL aggregate. Deferred as a moderate change to the uptime maths,
  outside a tight fix scope.
- **`/health` error branch (logged, adjacent).** `/health` is public and, on a dependency
  failure, its `checks[...].error` uses raw `str(e)` (can include an absolute path), whereas the
  OK branch already relativises paths to `DATA_DIR`. Same class as SS-01 but on the shared deep
  probe payload; not changed here to avoid altering a widely-relied-upon probe. Recommend
  relativising/scrubbing the error branch too, coordinated separately.
- **Out-of-scope observations (not this feature):** stale comment at `web.py:18956`
  ("passwordless: one click on /developer") is doc-rot — `/developer` is password-protected
  (ADR-0019); footer `[COMPANY_NAME]`/`[CONTACT_EMAIL]` placeholders and the em-dash page title
  come from the shared `_layout`. Left untouched.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The feature is fundamentally sound — honest three-state public
signalling, correct heartbeat-density uptime maths, well-isolated tenant-free operational data,
and a clean operator detail view. Five defects were found and fixed (one public info-disclosure,
one outage-honesty bug, one misroute, one rounding-honesty display, one missing error guard), all
locked with tests. Four low-severity/perf items are logged with clear recommendations.

---

## 10. Handover & merge status

- **Branch:** `claude/system-status-audit-9bbtbn` (the harness-designated audit branch; the
  session was initialised on it, and the "Git Development Branch Requirements" forbid pushing to a
  different branch, so it serves as `audit/system-status`).
- **Landing path — draft PR, not a direct `main` push.** The session-level branch policy
  requires pushing to the designated branch and opening a **draft PR** (never pushing to a
  different branch), so this lands via **PR #1116** (https://github.com/elijahkendrick04/MediaHub/pull/1116),
  gated by CI + "require branches up to date before merging" — the PR-path equivalent of Phase 5's
  atomic-push guard. Not self-merged into `main`.
- **Green gate (on the integrated result).** Rebased cleanly onto `origin/main` (no conflicts;
  `main` moved repeatedly during testing — final rebase base `71a627d`). App boots clean (509
  routes); the three feature test modules pass (42); a broad regression subset of the 31 test
  files exercising the changed modules passes (505 passed, 1 skipped — schemathesis unavailable);
  ruff 0.8.4 (pinned pre-commit version) lint + format clean; no secrets / no `.env` staged. The
  full ~12k-test suite is **deferred to CI**: its ~25-min runtime is outrun by `main`'s merge
  cadence here, so CI on the PR is the authoritative full-suite gate (Phase 5 prohibitive-runtime
  clause). Exactly what ran locally vs CI is stated above.
- **Review the diff:** `git diff origin/main...claude/system-status-audit-9bbtbn`
