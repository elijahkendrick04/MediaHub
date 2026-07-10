# Audit — Developer feature in Settings

- **Feature:** Settings -> Developer (operator-only deployment console) + its sign-in gate.
- **Mode:** AUDIT+FIX
- **Branch:** `claude/developer-settings-audit-oh85xm` (the designated development branch for this task; used in place of the generic `audit/<slug>` name per the repo's Git Development Branch Requirements).
- **Date:** 2026-07-10
- **Verdict:** WORKS-WITH-CAVEATS -> now WORKS for the fixed states (see section 9).

---

## 1. Scope contract

**Definition.** The "Developer" feature in Settings is the operator-only deployment
console reached at `/settings/developer`. For a signed-in operator it renders live
operational health (uptime pills, 24h/7d/30d uptime table, last incident), deployment
status (backend version + dependency health-check table), a list of links to the deeper
operator dashboards, and a site-wide "Clear all caches" action. It is gated by the
operator developer sign-in at `/developer` (username + password, ADR-0019), which grants
an unrestricted Owner-plan session. "Working" means: (a) an operator can sign in; (b) the
developer section renders its health/deployment/cache content; (c) every control on the
page does what its label says; (d) non-operators can never see or trigger any of it.

**Routes owned (method + path -> endpoint):**
- `GET /settings/developer` -> `settings_section` (section="developer") — the console.
- `GET /developer` -> `developer_login` — operator sign-in page.
- `POST /developer` -> `developer_login_post` — operator sign-in submit.
- `POST /operator/cache/purge` -> `operator_cache_purge` — the "Clear all caches" action on the page.

**Adjacent (linked from the page, owned by other features — verified reachable, not deep-audited):**
`/status`, `/healthz/usage`, `/healthz/governance`, `/api/status`, `/health`,
`/healthz/deps`, `/healthz/memory`, `/tools/mobile-parity`, `/developer/api`.

**Files owned (blast radius):**
- `src/mediahub/web/web.py` — `_render_settings_developer_section`, `_render_settings_status_section`,
  `_render_settings_deployment_section`, `_render_settings_cache_purge_card`, `_cache_tally`,
  `_developer_login_page`, `developer_login`, `developer_login_post`, `operator_cache_purge`,
  and the `settings_section` dispatch + its `is_dev_operator()` gate.
- `tests/test_developer_settings_org_gate.py` (new), `tests/test_dev_login.py`,
  `tests/test_cache_purge.py`, `tests/test_developer_login_label_a11y.py`.

**Shared files depended on but NOT freely rewritten:**
- `src/mediahub/web/auth.py` — `verify_dev_credentials`, `is_dev_operator`, `login_dev_operator` (read only; unchanged).
- `src/mediahub/web/web.py` `_gate_until_org_ready` before_request + `_SETUP_EXEMPT_ENDPOINTS` — the first-run
  organisation gate (a shared app-factory surface). **This is where the fixes land** — three additive entries only, no logic rewrite. Called out under "Cross-cutting changes" (section 7).
- `mediahub/privacy/cache_purge.py` — the purge implementation (read only; unchanged).

**Inputs / outputs / state.** Input: the operator's username + password at `/developer`
(verified against an argon2id hash via env override or baked-in default). Output: an
HTML console; the cache-purge action deletes re-derivable caches under `DATA_DIR` and
returns a flash toast. State: the operator identity is a boolean `dev_operator` flag in
the Flask signed session cookie; no per-operator data is persisted.

**Intended happy path.** Operator visits `/developer` -> enters credentials -> unrestricted
session -> opens Settings -> clicks "Developer" -> sees health + deployment + dashboards +
cache card -> optionally clicks a dashboard link (renders) or "Clear all caches" (purges,
returns with a success toast). Non-operators are redirected away and never see any of it.

---

## 2. Environment

- Installed deps: `pip install -r requirements.txt` (+ `pytest`, `pytest-xdist`, `ruff==0.8.4` to match the CI-pinned rev).
- Ran the Flask app locally: `python -m mediahub.web` on `PORT=5055`, `DATA_DIR` pointed at a scratch dir.
- **No real spend / offline:** `ANTHROPIC_API_KEY=""`, `GEMINI_API_KEY=""` — every AI surface honest-errors; the developer feature makes no provider calls, so nothing needed stubbing.
- **Throwaway operator credential** via the documented env override: `MEDIAHUB_DEV_USER=audit-op`, `MEDIAHUB_DEV_PASSWORD_HASH=<argon2id hash of a throwaway password>`. The real operator password/hash was never used.
- Drove routes with `curl` (cookie jar + CSRF token) and validated behaviour in-process with the Flask test client (`ENFORCE_ORG_GATE=1` to exercise the first-run gate the same way `test_org_setup_gate.py` does).
- App booted clean (only the expected "no LLM provider" + "DATA_DIR not set for prod" warnings). No 500s logged across the whole audit.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
|---|-----------|--------|-----------------|
| 1 | Functional correctness | PASS | `/settings/developer` renders status + deployment + cache card for an operator; version/health/uptime values come from `_health_payload()`/uptime observability. |
| 2 | Every interactive control | PASS (after fix) | All 10 linked dashboards return 200 for a no-org operator; the "Clear all caches" POST purges and 302s back with a success toast. Before the fix, 3 controls were dead for a no-org operator (F-1/F-2/F-3). |
| 3 | Input validation / edge cases | PASS | Dev login: missing fields, empty user+pass, 5000-char password -> 401 (no crash); non-ASCII username -> 401 (not 500). |
| 4 | UI state handling | PASS | Wrong login shows an error banner (`[ ERROR ] Invalid username or password.`); cache purge shows success/failure toast; degraded/healthy pills render from live health. |
| 5 | Server-side error handling | PASS | No unhandled 500s across all probes; cache-purge failure is caught and reported as a flash, not a stack trace. |
| 6 | Data integrity | PASS | Cache purge only removes re-derivable caches (`cache_roots()`); runs/uploads/DB/media/ledgers untouched. Idempotent (second purge -> "0 files deleted"). |
| 7 | Security | PASS | See section below. Sensitive dashboards gate non-operators; cache-purge POST is CSRF-protected + operator-gated; no secrets in responses; password never echoed; login rate-limited (429 after 6 attempts). |
| 8 | Performance sanity | PASS | `_cache_tally()` snapshots the on-disk walk for `_CACHE_TALLY_TTL` (~60s) so the page render doesn't stat tens of thousands of cache files each time. Deployment health uses a 60s snapshot. |
| 9 | Responsive / a11y basics | PASS | Login form has `<label for=...>` on both fields, autofocus, autocomplete hints; locked by `tests/test_developer_login_label_a11y.py`. Console uses semantic tables. |
| 10 | Rendered-graphic correctness | N/A | The developer feature renders no card/PNG graphics. |
| 11 | Consistency / copy quality | PASS | British English ("organisation", "Auto-refresh disabled"); no placeholder/TODO/debug text shown to users. |

**Security detail (dimension 7):**
- **Authorisation.** `/settings/developer` and `/operator/cache/purge` both require `is_dev_operator()`; a non-operator is redirected away and never receives operator HTML (verified: no "Deployment status" in the redirect body). `/healthz/usage` and `/healthz/governance` redirect non-operators to `/settings`; `/tools/mobile-parity` 404s for non-operators (doesn't even confirm existence). The `/developer` passwordless concern flagged in the brief is **stale** — closed by ADR-0019; `/developer` is username + password (argon2id, constant-time, rate-limited).
- **Secrets.** No `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`/token/hash appears in any response, page source, or error. The baked-in operator credential is an argon2id hash, never plaintext (locked by `tests/test_dev_login.py`).
- **CSRF.** State-changing POSTs (`/developer`, `/operator/cache/purge`) are covered by the global `_csrf_protect` before_request; an unauth POST with no token -> 403. Tokens auto-injected into rendered forms.
- **Injection / XSS.** The developer section interpolates only server-controlled values (version constant, health-check names/details, uptime numbers), all through `_h()`. No user-controlled text reaches the page. The login error is a fixed string; the submitted password is never rendered back.

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
|----|-----|-------|--------------|------------|--------|--------|
| F-1 | P1 | Developer settings section unreachable for a no-org operator | Sign in at `/developer`, then (with no organisation created) open Settings -> click "Developer". You land on `/organisation/setup`, not the developer console. | `settings_section` is not in `_SETUP_EXEMPT_ENDPOINTS`, so the first-run org gate (`_gate_until_org_ready`) intercepts the developer section before its handler runs — even though the section is operator-only and org-independent (like the exempted `operator_commercial` / `mobile_parity_tool`). | Fixed | see section 8 |
| F-2 | P2 | "AI governance — usage" dashboard link dead for a no-org operator | On the developer page, click "AI governance — usage" (`/healthz/governance`) with no org set up -> 302 to `/organisation/setup`. Its sibling "LLM usage dashboard" (`/healthz/usage`) works. | `healthz_governance` missing from `_SETUP_EXEMPT_ENDPOINTS` while its twin `healthz_usage` is present. The handler's own docstring assumed the exemption existed. | Fixed | see section 8 |
| F-3 | P2 | "Clear all caches" action silently no-ops for a no-org operator | On the developer page (once reachable), click "Clear all caches" with no org -> 302 to `/organisation/setup`; the purge never runs. | `operator_cache_purge` (POST) missing from `_SETUP_EXEMPT_ENDPOINTS`. The org gate swallows the POST before the handler's `_require_operator()` runs. Uncovered only after F-1's fix made the page reachable, exposing its primary action as dead. | Fixed | see section 8 |
| F-4 | P3 | `/healthz/deps` publicly discloses binary paths | `curl /healthz/deps` (no auth) returns `/opt/node22/bin/node`, the Chromium executable path, and `/home/.../remotion`. | The deps probe is public (deliberate deployment health signal) and reports absolute binary locations. Minor info disclosure. | Logged (out of blast radius) | — |

**Notes on F-1..F-3.** All three share one root cause: operator-only, org-independent
surfaces reachable from the developer page were not exempt from the first-run organisation
gate, so a fresh-deployment operator (who legitimately has no organisation yet) was bounced
to org setup. This is exactly the "control that doesn't do what it claims" class. F-1 was
found first; fixing it surfaced F-3 (the page's main action was still dead), which is why
all three are fixed together.

**F-4** is on a shared health route owned by the observability/health feature, not the
developer-settings feature, and the disclosure (container binary paths) is low-severity and
plausibly intentional operator-debug output. Left for the owning feature/session; not fixed
here to keep the footprint tight.

---

## 5. Fixes applied

All fixes are in `src/mediahub/web/web.py`, confined to the first-run org-gate machinery
(`_gate_until_org_ready` + `_SETUP_EXEMPT_ENDPOINTS`). No handler logic, template, or auth
code changed. Each fix is additive and mirrors an existing, established exemption pattern
(the sibling operator surfaces `operator_commercial`, `mobile_parity_tool`, `healthz_usage`
are already exempt for the same reason).

1. **F-2:** added `"healthz_governance"` to `_SETUP_EXEMPT_ENDPOINTS` (next to its twin `healthz_usage`).
2. **F-3:** added `"operator_cache_purge"` to `_SETUP_EXEMPT_ENDPOINTS` (next to `mobile_parity_tool`). Safe because the handler re-checks `_require_operator()` — the exemption only lets the POST past the org-setup wall, it is not an auth grant.
3. **F-1:** a surgical carve-out in `_gate_until_org_ready`: when `endpoint == "settings_section"`, the requested section is `developer`, and `is_dev_operator()` is true, the gate returns early. Scoped to the developer section only (the `settings_section` endpoint also serves org-scoped sections, so it cannot be a flat exemption). Not an auth grant — the handler still re-checks `is_dev_operator()`.

**Why not exempt all of `settings_section`?** The other settings sections are org-scoped and
some assume an active profile; a blanket exemption could expose a section that misbehaves
with no profile. The carve-out is the minimal change that fixes the operator dashboard
without altering any other section's behaviour.

---

## 6. Tests added / extended

`tests/test_developer_settings_org_gate.py` (new; 8 tests). Runs the app with the first-run
org gate ACTIVE (`ENFORCE_ORG_GATE`) and no organisation on disk — the exact fresh-deployment
operator state — and locks:

- `test_operator_reaches_developer_settings_without_org` — `/settings/developer` -> 200 with "Deployment status" + "Clear all caches" (F-1).
- `test_operator_reaches_governance_dashboard_without_org` — `/healthz/governance` -> 200 with "AI governance" (F-2).
- `test_governance_matches_its_usage_sibling` — governance and usage dashboards behave identically for a no-org operator.
- `test_operator_cache_purge_runs_without_org` — the purge POST -> 302 back to `/settings/developer`, not `/organisation/setup` (F-3).
- `test_non_operator_still_cannot_see_developer_settings` — a non-operator is redirected away and never receives operator content (exemption is not an auth grant).
- `test_non_operator_governance_redirected` — non-operator governance is redirected.
- `test_non_operator_cache_purge_blocked` — a non-operator's purge POST never lands on the developer section.
- `test_content_route_still_gated_for_operator` — a normal content route (`/upload`) still gates the operator to setup (proves the exemption is scoped, not a hole in the gate).

**Bug-locking proof:** with the `web.py` fix stashed, the three positive tests fail
(operator/governance/cache-purge all bounce to setup); with it applied, all 8 pass. So the
tests genuinely pin the fix and are not tautologies.

---

## 7. Cross-cutting changes

**One shared surface touched:** `src/mediahub/web/web.py` `_gate_until_org_ready` /
`_SETUP_EXEMPT_ENDPOINTS` (the app-factory first-run organisation gate). The change is three
additive entries + one narrowly-scoped early-return, all mirroring existing exemptions in the
same list. It does **not** rewrite the gate's logic and does not change behaviour for any
non-developer endpoint or for non-operators. Reconcilers: if another session also edits
`_SETUP_EXEMPT_ENDPOINTS`, the two edits are independent additions to the same frozenset and
should merge cleanly; if they collide textually, keeping both sets of entries is the correct
resolution.

No changes to `requirements.txt`, `pyproject.toml`, base templates, shared CSS/JS, or config.

---

## 8. Residual risks / cross-feature items

- **F-4 (`/healthz/deps` path disclosure)** — a shared health route; owner should decide whether to operator-gate it or redact absolute paths. Low severity.
- **Operator-with-an-org path was already correct** — the three fixes only affect the no-org state; an operator with a ready organisation always reached the console. No regression risk there.
- **Whole-file formatting drift in `web.py`** — the newest `ruff` reports quote-style deviations across pre-existing, untouched parts of `web.py`, but under the CI-pinned `ruff==0.8.4` the file is already clean and my edits pass. I deliberately did **not** run a whole-file reformat (it would churn dozens of unrelated lines and collide with parallel sessions).
- **Pre-existing sandbox-flaky/environmental test failures (not caused by this change)** — the full-suite green-gate run (12,491 passed, 10 skipped) surfaced 5 failures, all outside this feature and all passing in isolation:
  - `tests/test_ui_2_1_cutout_compare.py::TestEnsureCutoutResolver` (3 tests) — **environmental**: the rembg cutout model download is network-blocked in this sandbox (`403 Forbidden ... releases/download/.../u2net.onnx`), so the resolver honestly reports `failed` instead of `generated`/`cached`/`unavailable`. Unrelated to routing.
  - `tests/test_club_profile_token_scrub.py::test_legacy_secrets_json_is_scrubbed` and `tests/test_status_unavailable_state.py::test_no_heartbeat_shows_unavailable_not_green` — cross-test global-state pollution under parallel xdist (a one-time secrets scrub / a shared heartbeat singleton); both pass when run alone.
  A clean `origin/main` worktree was re-run under identical parallel conditions (same command, same sandbox) as the baseline. It **also failed** — 8 failures, and a **different** overlapping set (`test_spotlight_build_brand_grounding` x4, `test_ui_2_1_cutout_compare::TestCutoutFileRoute` x3, plus the same `test_status_unavailable_state` heartbeat test). The failing set varying run-to-run is the defining signature of flaky/environmental failures, not deterministic regressions. My branch has **fewer** failures (5) than clean main (8) and none in the developer-settings area. The org-gate change (two frozenset entries + a section carve-out) has no causal path to token scrubbing, image cutout, or heartbeat state, and all 5 pass in isolation. **Conclusion: no new failures attributable to this diff; green gate satisfied.**

---

## 9. Feature verdict

**WORKS** (after fix). The developer console, its sign-in gate, and every control on the
page now function for both operator states (with and without an organisation), with correct
authorisation, CSRF, error handling, and no secret leakage. Before the fix the honest verdict
was **WORKS-WITH-CAVEATS**: an operator on a fresh deployment (no organisation yet) could not
reach the console at all, and two of its controls were dead — precisely the first thing a new
operator would try.

---

## 10. Handover and merge status

- **Branch:** `claude/developer-settings-audit-oh85xm`
- **Merge status:** _to be completed by Phase 5_ — integrate latest `origin/main`, run the full green gate on the integrated result, then land via non-force push. Recorded here after the attempt.
- **Review the diff:** `git diff origin/main...claude/developer-settings-audit-oh85xm`
