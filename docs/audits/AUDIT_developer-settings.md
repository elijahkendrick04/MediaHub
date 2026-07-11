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
- **Information disclosure.** `/healthz/deps` (a public probe linked from the developer page) previously returned absolute server paths to anonymous callers (F-4); now redacted to operator-only, monitoring booleans preserved (locked by `tests/test_healthz_deps_path_disclosure.py`). The other linked probes disclose no paths.
- **CSRF.** State-changing POSTs (`/developer`, `/operator/cache/purge`) are covered by the global `_csrf_protect` before_request; an unauth POST with no token -> 403. Tokens auto-injected into rendered forms.
- **Injection / XSS.** The developer section interpolates only server-controlled values (version constant, health-check names/details, uptime numbers), all through `_h()`. No user-controlled text reaches the page. The login error is a fixed string; the submitted password is never rendered back.

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
|----|-----|-------|--------------|------------|--------|--------|
| F-1 | P1 | Developer settings section unreachable for a no-org operator | Sign in at `/developer`, then (with no organisation created) open Settings -> click "Developer". You land on `/organisation/setup`, not the developer console. | `settings_section` is not in `_SETUP_EXEMPT_ENDPOINTS`, so the first-run org gate (`_gate_until_org_ready`) intercepts the developer section before its handler runs — even though the section is operator-only and org-independent (like the exempted `operator_commercial` / `mobile_parity_tool`). | Fixed | see section 8 |
| F-2 | P2 | "AI governance — usage" dashboard link dead for a no-org operator | On the developer page, click "AI governance — usage" (`/healthz/governance`) with no org set up -> 302 to `/organisation/setup`. Its sibling "LLM usage dashboard" (`/healthz/usage`) works. | `healthz_governance` missing from `_SETUP_EXEMPT_ENDPOINTS` while its twin `healthz_usage` is present. The handler's own docstring assumed the exemption existed. | Fixed | see section 8 |
| F-3 | P2 | "Clear all caches" action silently no-ops for a no-org operator | On the developer page (once reachable), click "Clear all caches" with no org -> 302 to `/organisation/setup`; the purge never runs. | `operator_cache_purge` (POST) missing from `_SETUP_EXEMPT_ENDPOINTS`. The org gate swallows the POST before the handler's `_require_operator()` runs. Uncovered only after F-1's fix made the page reachable, exposing its primary action as dead. | Fixed | see section 8 |
| F-4 | P2 | `/healthz/deps` publicly discloses absolute server paths | `curl /healthz/deps` (no auth) returns `/opt/node22/bin/node`, the Chromium executable path, and `/home/.../remotion`. | The deps probe is public (deliberate deployment health signal) and reported absolute binary/install locations to anonymous callers, disclosing the deployment's internal layout. | Fixed | see section 8 |
| F-5 | P3 | "Clear all caches" under-delivers — `export_cache` + `charts_cache` survive the purge | On a mature deployment, click "Clear all caches" to reclaim disk; up to ~2 GB of `DATA_DIR/export_cache` and the unbounded `DATA_DIR/charts_cache` are left on disk, and the success toast's "MB reclaimed" excludes them. | `cache_roots()` (`privacy/cache_purge.py`) omitted two genuine, content-addressed, re-derivable `DATA_DIR` caches, so `purge_all_caches()` skipped them and `_cache_tally()` under-counted — despite the card promising "every re-derivable cache". Same bug class the file already fixed once for `render_cache`. Found by the adversarial re-audit workflow; under-deletion only (never touches source data). | Fixed | see section 8 |
| F-6 | P3 | `/developer/api` docs state the reel outro default as 1.0s; the real default is 2.5s | Read `GET /developer/api`; the `POST /api/runs/{id}/reel` "cover / outro" row said "Default 2.0 / 1.0". Real outro default is `REEL_OUTRO_SEC = 2.5`. | Stale copy in `_render_api_docs_body`: the outro default was extended 1.0s -> 2.5s in the engine but the public docs weren't updated, so a developer setting `?outro=1.0` to "match the default" silently shortens the outro. Found by the adversarial re-audit workflow. | Fixed | see section 8 |

**Notes on F-1..F-3.** All three share one root cause: operator-only, org-independent
surfaces reachable from the developer page were not exempt from the first-run organisation
gate, so a fresh-deployment operator (who legitimately has no organisation yet) was bounced
to org setup. This is exactly the "control that doesn't do what it claims" class. F-1 was
found first; fixing it surfaced F-3 (the page's main action was still dead), which is why
all three are fixed together.

**F-4** is on a shared health route (`/healthz/deps`) that the developer-settings deployment
section links to. It was first logged as out-of-blast-radius, then fixed on a follow-up pass
(the operator explicitly asked for the remaining caveats to be closed): the absolute paths
are now operator-only, while the endpoint stays public and keeps every availability boolean
and version, so uptime monitoring is unaffected. This mirrors the established
`/healthz/sentinel` pattern, where the raw audit tail is operator-only.

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

**Second pass (F-5, F-6)** — found by re-running the adversarial verification workflow:

4. **F-5:** added `export_cache` and `charts_cache` to `cache_roots()` in `src/mediahub/privacy/cache_purge.py` (resolved through each module's own resolver, `export_engine.cache.cache_dir` / `charts.export._cache_dir`, with a `DATA_DIR` fallback — exactly the pattern the sibling roots use). Both are content-addressed, re-derivable caches; adding them makes the site-wide purge honour its "every re-derivable cache" promise. Under-deletion only, so no data-integrity risk. **This is a shared file — see Cross-cutting changes.**
5. **F-6:** corrected the reel `outro` default in `_render_api_docs_body` (`/developer/api`) from `1.0` to `2.5` to match the engine constant `REEL_OUTRO_SEC`. One-line copy fix, wholly inside the developer feature surface.

**Third pass (F-4)** — closing the last caveat at the operator's request:

6. **F-4:** in `healthz_deps` (`src/mediahub/web/web.py`), the three absolute-path fields (`playwright.executable`, `node.path`, `remotion.dir`) are now stripped from the payload for any caller that is not `is_dev_operator()`. The endpoint stays public and every availability boolean, version and the top-level `ok` flag are unchanged, so uptime monitors are unaffected; only the on-disk locations are gated. Mirrors `/healthz/sentinel` (operator-only audit tail). Verified against the other linked probes (`/health`, `/healthz/memory`, `/api/status`, `/healthz`, `/healthz/breaker`, `/healthz/sentinel`, `/healthz/search`) — none of them disclose paths to anonymous callers, so `/healthz/deps` was the whole surface. **Shared file — see Cross-cutting changes.**

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

**Second pass:**
- `tests/test_cache_purge.py::test_purge_covers_newer_cache_roots` — extended to require `export_cache` and `charts_cache` in `cache_roots()` and to assert both are actually deleted by `purge_all_caches()` (F-5).
- `tests/test_api_docs_page.py::test_api_docs_reel_defaults_match_the_engine` (new) — asserts the documented reel cover/outro defaults equal the live `REEL_COVER_SEC`/`REEL_OUTRO_SEC` constants and that the stale "2.0 / 1.0" string is gone, so the docs can't drift from the engine again (F-6).

Both fail with the source fixes stashed and pass with them applied.

**Third pass:**
- `tests/test_healthz_deps_path_disclosure.py` (new; 3 tests) — an anonymous `/healthz/deps` payload contains no absolute path (`test_anonymous_deps_leaks_no_absolute_paths`, a recursive walk of the whole JSON), still reports `ok` + the availability booleans so monitoring is intact (`test_anonymous_deps_still_reports_health`), and a signed-in operator still sees the diagnostic paths (`test_operator_deps_keeps_paths`) (F-4). Fails with the redaction removed, passes with it applied.

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

**Second shared surface (F-5):** `src/mediahub/privacy/cache_purge.py` `cache_roots()` — two
additive `(label, path)` entries (`export_cache`, `charts_cache`), each resolved through the
owning module's resolver with a `DATA_DIR` fallback, following the exact pattern of the roots
already in the list. It only *adds* re-derivable caches to a purge that already existed (never
removes or narrows), so it cannot over-delete or touch source data. Reconcilers: independent
additions to the `roots` list; if another session edits `cache_roots()`, keeping both sets of
entries is the correct resolution.

**Third shared surface (F-4):** `src/mediahub/web/web.py` `healthz_deps` — a single additive
guard that pops three absolute-path fields for non-operators before the payload is returned.
It only *removes* data from the anonymous response (never adds or changes the availability
booleans), so it cannot break a monitor and has no interaction with any other route.
Reconcilers: the change is localised to the tail of the `healthz_deps` handler.

**Fourth shared surface (unblock the pre-existing `test_theme_tokens` red):** three inline
`color:var(--warn,#FFB454)` occurrences in `web.py` (the shared AI-unavailable banner, twice,
and `_chip_html_for`) had their **dead** `#FFB454` fallback dropped (`→ var(--warn)`). `--warn`
is globally defined in the base `:root` theme, so the fallback was never reached — the change
is provably zero-visual-change on every theme and touches no behaviour; it only lowers the
inline-hex-hardcode count (21 → 18) so the CI-gating `test_inline_hex_count_within_budget`
passes. This was done at the operator's explicit direction to fix the blocker and merge on
green. Reconcilers: three one-token deletions of a dead fallback; if a parallel session edits
the same lines, keeping `var(--warn)` (no hex fallback) is the correct resolution.

No changes to `requirements.txt`, `pyproject.toml`, base templates, shared CSS/JS, or config.

---

## 8. Residual risks / cross-feature items

- **F-4 (`/healthz/deps` path disclosure) — now fixed** (third pass): absolute paths are operator-only; the endpoint stays public for monitors. The other health probes the developer page links to were checked and disclose no paths, so the surface is closed.
- **`test_theme_tokens.py::test_inline_hex_count_within_budget` — pre-existing `main` breakage, now FIXED (operator-authorised, fourth pass).** The third-pass full-suite run (12,546 passed, 10 skipped, 5 failed) surfaced this deterministic theming-hygiene failure: `web.py` carried **21** inline hex hardcodes against a budget of 20. My F-4 diff adds **zero** hex (confirmed), and a clean `origin/main` worktree failed it identically (21 vs 20) — a parallel-merge accumulation artifact where independent sessions each added an inline hex that individually passed but together crossed 20. It blocked a clean merge (`main` was red on the CI-gating suite), so — the operator explicitly directed *"find out why it's not green, fix the issue then merge on green"* — I brought the count back under budget with the **safest possible** change: the three inline `color:var(--warn,#FFB454)` uses (the AI-unavailable banner and a chip helper) carried a **dead hex fallback** — `--warn` is defined globally in the base `:root` theme (web.py, `--warn: var(--mh-warning)`), so the `#FFB454` fallback is never reached. Dropping it (`→ var(--warn)`) is **provably zero-visual-change on every theme** (default and brand) and removes 3 offenders → **count 18** (2 under budget). This is a cross-cutting change touching shared components — see Cross-cutting changes. Lifting the budget in the test was **not** done (never weaken a test to pass a gate); the real hex count was reduced instead.
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

- **Branch:** `claude/developer-settings-audit-oh85xm` (pushed to origin).
- **Merge status: MERGED to `main`.** Integrated the moving `main` twice (BASE `95c83d0` -> `fe2605d` -> `33602c5`; other audit sessions and the roadmap bot were merging in parallel), re-ran the green gate on each integrated result, passed the freshness re-check (`origin/main` == BASE `33602c5` at push time), and landed via a non-force fast-forward push (`git push origin HEAD:main`). The four `[developer-settings]` commits (`494f6dd` fix, then the report commits) are the four commits on `main` above roadmap `33602c5`; `main` tip after the push: **`1a1b232`**.
- **Green gate:** app boots clean; full suite on the prior integration = 12,491 passed / 10 skipped / 5 pre-existing flaky-or-environmental failures also present (differently) on a clean `origin/main` baseline; a 175-test gate+feature+auth+language-switcher regression subset passed on the final integration; ruff (pinned v0.8.4) lint + format clean; no secrets or `.env` staged.
- **Review the diff:** `git diff 33602c5..1a1b232` (or `git show 494f6dd` for the code fix alone).
- **Second pass (F-5, F-6) — MERGED to `main`.** After re-running the adversarial verification workflow, the two P3 fixes landed in a follow-up: code+tests `ec66e8b`, report `22fefbb`, integrated onto `origin/main` BASE `9b7d0a7` (rebased cleanly past parallel `[season-wraps]`/`[plan]` web.py edits), green gate re-run (126-test cache-purge + api-docs + developer + gate + operator subset passed; ruff v0.8.4 clean; app boots), freshness re-checked, landed via non-force push. Review: `git show ec66e8b`.
- **Third pass (F-4) — the operator asked for the remaining caveats to be closed.** The one actionable caveat (F-4, `/healthz/deps` path disclosure) is now fixed: absolute paths are operator-only, monitoring booleans preserved. Code+test commit (the redaction) + report commit; new test `tests/test_healthz_deps_path_disclosure.py`. Branch restarted from the latest `origin/main` (the earlier developer-settings branch was already merged, so this pass is a fresh change on top of current `main`), rebased onto BASE `2349a41`.
  - **Green gate:** app boots clean (483 routes); the feature+affected subset (189 tests: healthz-deps-disclosure, developer-org-gate, dev-login, cache-purge, health-title, org-setup-gate, operator-commercial, api-docs, authn-hardening, …) all pass; full `tests/` suite = **12,546 passed / 10 skipped / 5 failed**, where all 5 are pre-existing and unrelated: 4× `test_spotlight_build_brand_grounding` (flaky under parallel xdist — pass in isolation) and 1× `test_theme_tokens::test_inline_hex_count_within_budget` (deterministic, but fails identically on a clean `origin/main` `2349a41` worktree; my diff adds zero hex). ruff (pinned v0.8.4) lint + format clean on both changed files; no secrets or `.env` staged.
  - **Merge line appended below once pushed.**
