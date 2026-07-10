# Audit — Live meet (Create hub)

**Feature:** "Live meet" mode, reachable from the Create hub.
**Mode:** AUDIT+FIX.
**Branch:** `claude/audit-live-meet-z2yf0z` (the session's designated audit branch).
**Date:** 2026-07-10.
**Verdict:** WORKS-WITH-CAVEATS before this audit was, in truth, **BROKEN** on
the core promise (see F1); **WORKS** after the fixes in this branch.

---

## 1. Scope contract

**Definition.** Live meet lets a signed-in club paste a host club's
live-results web page. MediaHub polls that page politely for the duration of a
gala; each poll does a full-document parse, diffs the new swims against a
cumulative per-swim key set, and — when genuinely new swims appear — re-runs the
recognition pipeline into one fixed run and queues cards for approval. Nothing
is published; the volunteer gets a notification and reviews/queues cards
manually. Watches auto-expire (default 12h, hard cap 48h). "Working" means: a
volunteer can start a watch on an allowed URL, the watch polls on its interval,
new results turn into queued cards they can review, they can stop the watch, and
the whole thing is org-scoped, honest about failure, and never publishes.

**Routes owned.**

| Endpoint | Method | Path |
|---|---|---|
| `live_meet_page` | GET | `/live` |
| `live_meet_action` | POST | `/live/action` |

Plus the "Live meet" tile in the Create hub (`/make`), which links to `/live`.

**Files owned (blast radius edited here).**
- `src/mediahub/results_fetch/live_watch.py` — engine core (Watch model, CRUD,
  `poll_watch`, dedupe keys, scheduler task type, default fetcher/notifier).
- `src/mediahub/web/web.py` — **only** the live-meet regions: `_live_watch_runner`,
  `live_meet_page`, `live_meet_action`, `_ensure_live_watch_schedule`, and the
  Create-hub Live meet tile.
- `tests/test_live_watch.py`, `tests/test_phase_w_web.py` (the `TestLiveMeet`
  additions), `tests/test_create_hub_live_tiles.py`.

**Shared files depended on but NOT rewritten.** `interpreter/` (`interpret_document`),
`pipeline/pipeline_v4.py` (`run_pipeline_v4`), `results_fetch/fetch.py`
(`StaticBackend`, the SSRF-hardened fetcher), `scheduler/`, `workflow/schedule.py`,
`notify/channels.py`, and the shared CSRF guard / org-gate in `web.py`.

**Inputs / outputs / state.** Input: a results-page URL, a label, a poll
interval (3/5/10 min), and a stop-after window (6/12/24h). Output: queued cards
under a fixed run id, reviewable at `/review/<run_id>`; push notification on new
results and at expiry. State: `live_watches` + `live_watch_swims` tables in
`DATA_DIR/data.db`; persisted runs under `RUNS_DIR`; a single global
`live_meet_poll` cron task in the workflow scheduler.

**Intended happy path.** Sign in → open Create → Live meet → paste a host
club's live-results URL → Start watching → the poll task checks the page every
N minutes → each new swim runs recognition and queues a card → volunteer gets a
push, opens Review, approves/edits → watch stops itself after the window.

---

## 2. Environment

- Installed deps with `pip install -e ".[dev]" --ignore-installed PyYAML`
  (system PyYAML lacked a RECORD file). Python 3.11.15, Flask 3.x, pytest 9.1.1.
- No LLM keys set — the app logs the honest "No LLM provider configured" warning
  and AI surfaces honest-error, which is the intended offline posture. No real
  paid API calls were made. `run_pipeline_v4` runs fully offline (deterministic
  parse/detect/rank; captions are generated lazily on the review page, not in the
  pipeline), so the poll runner works without a key.
- Ran the app locally via a small bootstrap (`app.run` on `127.0.0.1:5055`) with
  `DATA_DIR`/`RUNS_DIR`/`UPLOADS_DIR`/`SWIM_CONTENT_PROFILES_DIR` pointed at a
  scratch dir. Drove `/live` and `/live/action` with `curl` (cookie jar for the
  session; JSON body for the CSRF-exempt set-active-org API; the CSRF token
  scraped from the rendered form for the state-changing POSTs).
- Polls were exercised with a stubbed fetcher returning a LENEX fixture
  (`interpret_document` parses LENEX natively and deterministically) — no
  network. Provider calls were never invoked.
- Full server-boot smoke: `/` and `/healthz` return 200; `/make` and `/live`
  correctly 302 to org setup for an unpinned session.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
|---|---|---|---|
| 1 | Functional correctness | **FAIL → fixed** | Core runner was dead (F1); no card ever queued on a real poll. Fixed + regression test. |
| 2 | Every interactive control | **PASS (with fixes)** | Form, interval/hours selects, Start, Stop, Review link, Create tile all drive the right routes. Review link now honest until carded (F7); error banner now honest (F5). |
| 3 | Input validation / edge cases | **PASS (with fixes)** | Prohibited hosts, bad scheme, empty URL rejected with clear messages. Non-numeric interval (F3) and huge interval (F4) hardened. XSS payload in label escaped. |
| 4 | UI state handling | **PASS (with fixes)** | Loading/empty/success present; error state now amber not green (F5); "No cards yet" placeholder added (F7). |
| 5 | Server-side error handling | **PASS (with fixes)** | Narrow `except ValueError` widened; stop path wrapped; raw exception text no longer surfaced (F6, F9). No stack traces leaked (prod). |
| 6 | Data integrity | **PASS** | Cumulative sidecar dedupe prevents re-carding; time-correction and age-band collision concerns investigated and **refuted** (runner re-runs whole doc, card id excludes time; approvals survive). |
| 7 | Security (feature-specific) | **PASS** | Org gate on both routes; org isolation verified live (org B sees/stops nothing of org A); CSRF enforced; label XSS escaped; SSRF blocked at fetch time (create-time acceptance is defense-in-depth only, F8 logged); queue-only, cannot publish. |
| 8 | Performance | **PASS** | Request path is cheap (`list_watches` indexed by `profile_id`). One full parse per poll before the digest short-circuit is redundant on a quiet page (F10, logged — background task, off request path). |
| 9 | Responsive / accessibility | **PASS (with fixes)** | Form labels now associated (F2); action-column headers now named (F11). |
| 10 | Rendered-graphic correctness | **N/A** | This feature queues cards into the existing pipeline/renderer; it does not itself render graphics. |
| 11 | Consistency / copy quality | **PASS** | British English, no placeholder/debug/TODO strings. Em dashes in prose are the pervasive house style (logged, not changed). |

---

## 4. Findings

Severity uses the audit rubric. "Verified" = survived an independent adversarial
verification pass (a fan-out of finder + refuter agents; two candidate findings
were correctly **refuted** and are listed at the end).

| id | sev | title | reproduction | root cause | status | commit |
|---|---|---|---|---|---|---|
| **F1** | **P0** | Live-meet poll runner is dead — no card ever queues | Start a watch; when a poll finds new swims the scheduler calls `_live_watch_runner`, which does `from mediahub.web.pipeline_v4 import run_pipeline_v4` (module does not exist) and calls it positionally against a keyword-only signature. `poll_watch` catches the exception, does not advance the key set, and retries the same failing diff forever. No run is persisted; "Review cards" dead-ends. Verified: `import mediahub.web.pipeline_v4` → ModuleNotFoundError; positional call → TypeError. | Wrong import path + positional call against `run_pipeline_v4(*, file_bytes, filename, ...)`. Existing tests passed only because they inject a fake runner and never exercise `_live_watch_runner`. | **fixed** | 8ac50d9 |
| **F2** | **P2** | Create-form labels not associated with inputs (WCAG 1.3.1/4.1.2) | On `/live`, each `<label>` for URL/Name/Check-every/Stop-after has no `for`, and no input/select has a matching `id`; the two selects announce only their role to a screen reader. | f-string template emitted labels as bare siblings. | **fixed** | 8ac50d9 |
| **F3** | **P3** | Non-numeric `interval_minutes` leaks a raw `ValueError` | POST create with `interval_minutes=abc`: `int(...)` raised inside the `try`, caught by `except ValueError`, and rendered verbatim as "Could not start the watch: invalid literal for int() with base 10: 'abc'". (`hours` was already guarded; `interval_minutes` was not.) | Unguarded `int()` parse. | **fixed** | 8ac50d9 |
| **F4** | **P3** | Huge `interval_minutes` → uncaught OverflowError → 500 | POST create with `interval_minutes=99999999999999999999`: parses fine (Python bigint), survives the floor-only clamp, and overflows the SQLite INTEGER column on insert. `OverflowError` is not a `ValueError`, so it escaped the guard → 500. | No upper clamp; value bound straight into an INTEGER column. | **fixed** | 8ac50d9 |
| **F5** | **P3** | Error messages rendered as green success | A failed create/stop redirects with the error text through the same `?msg=`, which `live_meet_page` always paints `tag good` (green). A validation failure looks like a success. | Single flash param, hardcoded success class. | **fixed** | 8ac50d9 |
| **F6** | **P3** | Non-`ValueError` failures in create/stop → unhandled 500 | Create caught only `ValueError`; a `sqlite3.OperationalError` (locked/read-only DB) or other error escaped as a 500. Stop (`stop_watch`) had no handler at all. | Overly narrow / missing exception handling. | **fixed** | 8ac50d9 |
| **F7** | **P3** | "Review cards" link always active, dead-ends on "Run not found" | A watch's run is created lazily by the first carding poll. Until then the always-rendered Review link routes to the "Run not found" recovery page. | Link rendered unconditionally regardless of whether a run exists. | **fixed** | 8ac50d9 |
| **F8** | **P3** | `create_watch` accepts internal/metadata hosts at create time | `_validate_url` checks only scheme + ADR-0012 prohibited suffixes, so `http://169.254.169.254/...` or an RFC1918 host is accepted and stored. **Not exploitable**: every poll fetch routes through `StaticBackend`, which re-validates and refuses private/loopback/link-local/metadata IPs, so no internal request is ever made — only a silently-dead watch results. | SSRF hardening lives at fetch time only; create-time validation is not aligned. | **logged** | — |
| **F9** | **P3** | Raw exception text stored in `last_error`, shown in "Last issue" | `fetch failed: {e}`, `parse failed; will retry ({parse_detail})`, `runner failed: {e}` embedded raw internal text (e.g. a DATA_DIR path) into the org-scoped `last_error` shown on `/live`. HTML-escaped (no XSS) but internal detail. | Raw `str(e)` interpolated into the displayed field. | **fixed** | 8ac50d9 |
| **F10** | **P3** | Full-document parse on every poll before the digest short-circuit | `poll_watch` always runs `interpret_document` before comparing the parsed-key digest, so a byte-identical page is re-parsed every interval. Deterministic background poller, off the request path; the digest is derived from the parse. | Change detection keyed on the parsed key set, not a raw-bytes hash. A raw pre-hash would need a new schema column + migration. | **logged** | — |
| **F11** | **P3** | Two empty `<th></th>` action-column headers (no accessible name) | The Watches table's Review/Stop columns had empty header cells. | Placeholder empty headers. | **fixed** | 8ac50d9 |
| **F12** | **P3** | Duplicate submissions create independent watches on the same host | Submitting the same URL twice for one org created two active watches, each polling the host on its own interval (doubling load) and fragmenting cards across two runs. | No uniqueness guard on (org, url). | **fixed** (web-layer dedupe) | 8ac50d9 |
| **F13** | **P3** | Scheduling failure shown as success | `_ensure_live_watch_schedule` swallowed all exceptions while the caller still reported "Watching..."; a watch could persist but never be scheduled. | Success reported unconditionally. Low-probability (system-wide broken scheduler). | **fixed** | 8ac50d9 |

**Refuted (investigated, not real):**
- *Time-correction double-card* — the runner re-runs the whole document into a
  fixed run and card ids exclude the swim time, so a corrected time yields one
  card, not two. Dedupe keys only gate whether the runner runs.
- *Age-band key collision drops a card* — dedupe keys never create cards; the
  runner cards every swim in the parsed document, so no card is dropped.

---

## 5. Fixes applied

All fixes are confined to the owned blast radius (`live_watch.py` and the
live-meet regions of `web.py`).

**`web/web.py` — `_live_watch_runner` (F1, P0):** dropped the non-existent
`from mediahub.web.pipeline_v4 import run_pipeline_v4`; use the module-level
symbol already imported at the top of the file and call it with keywords
(`file_bytes=`, `filename=`).

**`web/web.py` — `live_meet_action` (F3, F4, F5, F6, F12, F13):** defensively
parse `interval_minutes` (bad value → default 5); dedupe by reusing an existing
active watch for the same (org, url); wrap `create_watch` with `except ValueError`
(clean message) and a generic `except Exception` (logged, sanitised message);
wrap `stop_watch` likewise; route all failures through `?err=`; make success
conditional on `_ensure_live_watch_schedule()` returning True.

**`web/web.py` — `live_meet_page` (F5, F7, F2, F11):** honest banner (amber
`tag warn` for `?err=`, green `tag good` for `?msg=`); a `_review_cell` helper
that shows "No cards yet" until `new_swims_total > 0`; `for`/`id` on all four
form controls; `mh-sr-only` accessible names on the two action headers (reusing
the existing site-wide screen-reader-only utility — no shared CSS added).

**`web/web.py` — `_ensure_live_watch_schedule` (F13):** now returns `bool`.

**`results_fetch/live_watch.py` (F4, F9):** new `MAX_INTERVAL_MINUTES` ceiling
(= `MAX_EXPIRE_HOURS * 60`) applied in `create_watch` so no out-of-range int
reaches the INSERT; `last_error` now stores short stable phrases
("fetch failed: could not reach the page", "parse failed; will retry",
"runner failed; will retry") with the raw detail sent to `log.warning`.

---

## 6. Tests added / extended

**`tests/test_phase_w_web.py` — new `TestLiveMeet` class:**
- `test_real_runner_cards_a_poll` — **P0 regression**: registers nothing extra,
  relies on the real `_live_watch_runner` that `create_app` wires onto the
  scheduler, feeds a LENEX fixture via a monkeypatched default fetcher, runs the
  poll handler, and asserts the runner did not fail, both swims were carded, and
  a run was persisted at the watch's run id. (Confirmed to FAIL against the old
  broken runner with "runner failed: No module named 'mediahub.web.pipeline_v4'".)
- `test_prohibited_url_shows_error_banner_not_success` (F5),
  `test_non_numeric_interval_defaults_no_leak` (F3),
  `test_huge_interval_no_500` (F4),
  `test_duplicate_url_reuses_watch` (F12),
  `test_review_link_hidden_until_carded` (F7),
  `test_form_labels_are_associated` (F2),
  `test_stop_unknown_watch_is_amber_error` (F5/F6),
  `test_action_requires_org` (authorisation).

**`tests/test_live_watch.py`:**
- `test_interval_clamped_to_max` (F4) — clamps to `MAX_INTERVAL_MINUTES` and
  round-trips through the DB without overflow.
- `test_last_error_omits_raw_exception_text` (F9) — fetch/parse/runner failures
  carry the stable prefix but none of the raw exception detail.

All existing live-meet tests continue to pass unchanged (the sanitised
`last_error` keeps the "fetch failed" / "parse failed; will retry" /
"runner failed" prefixes the existing assertions rely on).

---

## 7. Cross-cutting changes

**None.** No shared file outside the feature's owned regions was modified. The
accessible-header fix reuses the existing site-wide `.mh-sr-only` utility rather
than adding CSS. The web.py edits are confined to lines ~60844–61033 (the
live-meet routes); no base template, shared CSS/JS, config, `requirements.txt`,
or `pyproject.toml` was touched.

---

## 8. Residual risks / follow-ups (not done here)

- **F8 (SSRF create-time acceptance, P3, logged):** aligning `_validate_url`
  with the fetch-time guard would turn a silently-dead internal-URL watch into
  an immediate honest error. Left for coordination because the authoritative
  SSRF block already lives in `StaticBackend` (no exploit) and a create-time
  literal-IP-only check would be partial; a full check adds DNS at create time.
- **F10 (redundant full parse per poll, P3, logged):** a raw-bytes pre-hash
  short-circuit would need a new `live_watches` column + migration for existing
  `data.db` files. Marginal benefit on a 5-minute background task; deferred to
  avoid a schema change in an audit.
- **Em dashes in user-facing prose** are the pervasive house style across the
  whole monolith; de-dashing only this feature would be inconsistent and is
  out-of-scope copy churn. Noted, not changed.
- The poll runner re-runs the full pipeline into a fixed run id on every carding
  poll; approvals survive (separate workflow sidecar) and card ids are stable,
  but caption regeneration cost per poll is a broader pipeline concern outside
  this feature.

---

## 9. Feature verdict

**WORKS** (after this branch). Before the audit the feature was effectively
**BROKEN**: its single core promise — turn new live results into queued cards —
never happened on any real poll because the production runner died on a bad
import and a keyword-only call (F1). That is now fixed and locked by a regression
test that fails against the old code, and the surrounding create/stop/list flow
is hardened, honest about failure, org-isolated, and accessible.

---

## 10. Handover and merge status

- **Branch:** `claude/audit-live-meet-z2yf0z` (the session's designated branch).
- **Merge status:** **MERGED to `main`.** Rebased cleanly onto `origin/main`
  twice (BASE `95c83d0`, then `62116ce` after `main` moved during the full-suite
  run); no conflicts either time (the incoming changes — an app-factory refresh
  and an interface-language-switcher audit — sit in disjoint `web.py` regions).
  Green gate: app boots; full `tests/` suite passed on the first rebased base
  (12,499 passed, 10 legitimate skips, 0 failures); after the second rebase, a
  targeted regression passed (131: the 60 feature tests + the incoming language
  delta's test + a broad web-surface subset — security hardening, org-setup gate,
  review, upload, layout, settings); ruff 0.8.4 lint + format clean; no secrets
  or `.env` staged. Freshness-checked `origin/main` immediately before pushing
  (still `62116ce`), then landed with a non-force fast-forward push.
  - Commits on `main`: `01477c4` (P0 runner + hardening), `13a6b5e` (regression
    tests), `0c13738` (this report). Final `main` after merge: **`0c13738`**.
- **Review the diff:** `git diff 62116ce..0c13738` (or, before the report
  commit, `git diff 62116ce..13a6b5e`).
