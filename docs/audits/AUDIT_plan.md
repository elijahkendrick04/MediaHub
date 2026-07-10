# Audit — the "Plan" feature (Create → Plan, the Cross-Source Planner)

Mode: AUDIT+FIX · Auditor session · Branch: `claude/audit-plan-feature-t0a7hi`

> Branch-name note: Hard Rule 1 asks for `audit/<slug>`; this session was
> assigned the fixed development branch `claude/audit-plan-feature-t0a7hi` by
> the harness and told never to push elsewhere without permission, so all work
> lands there. The invariant that matters — branch first, never commit to
> `main`, merge only through the Phase 5 green gate — is honoured.

## 1. Scope contract

**What the feature is.** The Plan feature is MediaHub's *strategy brain* (roadmap
P1.3 + 1.14): the `/plan` page, reached from the **Create** tab, answers "what
should we post next?" It fuses three deterministic, read-only signal sources —
**own** (processed runs, card workflow state, draft-pack recency, measured post
performance), **external** (discovered meet context, calendar anniversaries,
curated key dates), and **direct** (operator-entered upcoming events, blackout
dates, structured goals) — into a **ranked, explainable content plan** where every
line traces to a signal. Around the ranked plan sit five companion surfaces: a
month **calendar** (drag-to-schedule planned drafts), an Instagram-style **grid**
preview, per-channel **previews**, a committee **board** (Kanban idea cards →
promote to draft), a first-party **performance** loop (log posts → deterministic
attribution feeds the ranker + optional AI digest), and **sponsor ad-variant**
export sets. An AI free-text box (`/api/plan/interpret`) turns a plain-language
note into structured direct inputs for review. **"Working" means:** the ranked
plan is correct + deterministic + source-grounded; every control does what it
says; inputs validate cleanly; state persists and reads back per-org with no
leakage; nothing publishes; and the AI surfaces honest-error without a provider.

**Routes owned (method · path):**

| Method | Path | Handler |
|---|---|---|
| GET | `/plan` | `plan_page` — ranked plan + direct-inputs form + NL box |
| GET | `/api/plan/latest` | `api_plan_latest` |
| POST | `/api/plan/generate` | `api_plan_generate` |
| GET/POST | `/api/plan/inputs` | `api_plan_inputs` |
| POST | `/api/plan/interpret` | `api_plan_interpret` (AI, honest-error) |
| GET | `/plan/calendar` | `plan_calendar_page` |
| GET | `/api/plan/calendar` | `api_plan_calendar` |
| POST | `/api/plan/calendar/schedule` | `api_plan_calendar_schedule` |
| GET | `/plan/grid` | `plan_grid_page` |
| GET | `/plan/preview/<pack_id>` | `plan_preview_page` |
| POST | `/api/channel-preview` | `api_channel_preview` |
| GET | `/plan/board` | `plan_board_page` |
| GET | `/api/plan/board` | `api_plan_board` |
| POST | `/api/plan/board/add\|move\|delete\|promote` | board APIs |
| GET | `/plan/analytics` | `plan_analytics_page` |
| POST | `/api/plan/analytics/record\|delete\|digest` | analytics APIs |
| GET | `/plan/ad-variants/<pack_id>` | `plan_ad_variants_page` |
| GET | `/api/plan/ad-variants/<pack_id>/export` | `api_plan_ad_variants_export` |

**Files owned (blast radius):**
- `src/mediahub/content_engine/{planner,signals,inputs,nl_inputs,calendar,key_dates,board}.py`
- `src/mediahub/analytics/{store,attribution,digest}.py`
- The plan route handlers + inline templates/JS inside `src/mediahub/web/web.py`
  (lines ~31047-32778) and their local helpers.

**Shared files depended on but NOT freely rewritten:** `web/web.py` app factory
and `_layout`/`_h`/`_active_profile_id` (edit only the plan routes, minimally);
`club_platform/{post_types,stub_pack_store,content_types}.py`; `sport_profiles`;
`channel_preview`; `ad_export`; `workflow/store`; base CSS/JS.

**Inputs/outputs/state.** In: sport (from org type), operator events/goals/
blackouts, free-text note, logged post metrics, board idea cards, draft schedule
dates. Out: ranked `ContentPlan` (per-org JSON under `DATA_DIR/content_plans/`),
calendar model, attribution table, ad manifests. State persists per-org under
`DATA_DIR/{content_plans,planner_inputs,plan_board,analytics,stub_packs}/`.

**Happy path (concrete expected results).** Ready swimming org → open `/plan` →
"Generate plan" → deterministic ranked list of post types, each with a score and
signal-traced reasons, result-led types honest about "no results yet"; add an
event/goal/blackout → Save → regenerate → the ranking shifts and cites the new
signal; drag a draft on the calendar → `planned_date` set, blackout warns softly;
log posts → attribution table + planner nudge; nothing publishes anywhere.

## 2. Environment

- Python 3.11.15; installed `-r requirements.txt` + `.[dev]` (`--ignore-installed PyYAML`).
- `.env` (gitignored) with dummy `SECRET_KEY`, empty provider keys (offline — AI
  surfaces honest-error), `DATA_DIR` under the session scratchpad.
- App booted via `python -m mediahub.web` on **port 5055**; 502 routes, 22 `/plan*`
  routes registered; clean startup (one expected warning: "No LLM provider configured").
- A **ready** unbound swimming-club org `audit-club` seeded on disk; a valid signed
  Flask session cookie minted (same SECRET_KEY) to drive the authenticated pages.
- Reproductions use the in-process Flask test client with a tmp `DATA_DIR`
  (matches the existing `tests/` pattern). Provider calls are never made (no keys).
- Playwright drives the live pages via the prebaked Chromium
  (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `executable_path`).

## 3. Test matrix results

Method: 8-dimension adversarial hunt (parallel subagents, code-grounded + live/in-process
reproductions), then I re-reproduced every candidate myself with the in-process Flask test
client and the live server before fixing. All defects were reproduced before fix and
re-checked after.

| # | Dimension | Result | Note (evidence) |
|---|---|---|---|
| 1 | Functional correctness | PASS* | Ranking deterministic + source-grounded (test_cross_source_planner); one real correctness bug in the anniversary signal (QA-P1) fixed and now matches the calendar. |
| 2 | Every interactive control | PASS* | All buttons/links/forms wired; `Create →` links resolve; NL + digest buttons honest-error without a provider. One a11y control gap on the calendar (drag-only planned chip, QA-P3) fixed. |
| 3 | Input validation & edge cases | PASS* | Store cleaners bound + validate (dates, caps, unicode, negatives). Three unguarded 500s on malformed JSON bodies (QA-P4/P5/P8) fixed → clean 400s. |
| 4 | UI state handling | PASS* | Empty / success / error states render on all 8 pages; corrupt persisted files degrade to empty after QA-P6/P7. |
| 5 | Server-side error handling | PASS* | Correct 403/404/400/503/502; unhandled 500s (QA-P4/5/6/7) eliminated. `internal_error` body carries no stack trace or path. |
| 6 | Data integrity & idempotency | PASS* | Tenant isolation verified (cross-org pack/card/metric/plan rejected 404/false); `promote` idempotent; readback correct. Phantom zero-metric row (QA-P8) fixed. |
| 7 | Security (authz/IDOR/XSS/traversal/secrets) | PASS | All 24 routes org-gate (403/302); XSS in event/venue/goal/board/analytics fields HTML-escaped via `_h()` (verified: 0 raw `<script>`); sport slug + pack_id + org id sanitised (no traversal); no secret/`DATA_DIR` leak. CSRF: same-origin JSON, no tokens — consistent with the whole app (see Residual). |
| 8 | Performance | PASS-WITH-CAVEAT | Bounded per org for a realistic corpus; a cross-tenant full-disk scan (QA-P10) degrades only at thousands of *foreign* records — logged, not a Plan-local fix. |
| 9 | Responsive & a11y basics | PASS* | Clean consoles on all pages; drag now has non-drag/keyboard parity (QA-P3); form inputs given labels/aria-labels (QA-P9); analytics inputs already use wrapping labels. |
| 10 | Rendered-graphic correctness | N/A | The Plan feature renders no HTML→PNG cards; its "previews" are HTML/geometry only, which render correctly and stably. |
| 11 | Copy quality (British English) | PASS* | Singular counts now pluralise (QA-P2). One em dash in an error string (QA-P8-copy) left as-is — consistent with the codebase's established house typography (see Residual). |

\* passes after the fixes in §5.

## 4. Findings

| ID | Sev | Title | Reproduction (summary) | Root cause | Status |
|---|---|---|---|---|---|
| QA-P1 | P2 | Anniversary signal misses cross-year-boundary anniversaries (plan ≠ calendar for ~2 weeks each New Year) | Meet finished 2020-12-30; `gather_external_signals(now=2026-01-02)` → 0 anniversary signals though it's 3d after the anniversary and the calendar shows it | `signals.py` only tested `finished.replace(year=today.year)`; near a boundary the true nearest anniversary is in `today.year ± 1` | **fixed** dd2967d |
| QA-P2 | P3 | Counts of 1 read "1 achievements" / "1 cards" | `gather_own_signals` with `n_achievements=1` → "1 achievements detected"; planner reasons "1 cards awaiting review" | Hardcoded plural nouns in `signals.py:174` + `planner.py:249,257` | **fixed** dd2967d |
| QA-P3 | P2 | Calendar planned chip is drag-only — no touch/keyboard reschedule/unschedule | Schedule a draft, load `/plan/calendar`; the planned chip has no date field/`tabindex` — touch/keyboard users can't move or clear it | I-1 non-drag field was added to `_rail_card` only, not `_entry_chip`'s planned branch | **fixed** dd2967d |
| QA-P4 | P2 | `POST /api/channel-preview` 500s on non-list `hashtags` | `{"hashtags":5}` → 500 TypeError | `body.get("hashtags") or []` lets a truthy non-list reach `len([h for h in hashtags])` | **fixed** dd2967d |
| QA-P5 | P2 | `POST /api/plan/analytics/record` 500s on non-dict `metrics` | `{"metrics":5,...}` → 500 AttributeError | `(body.get("metrics") or {}).get(...)` — `or {}` only guards falsy, not wrong type | **fixed** dd2967d |
| QA-P6 | P2 | Non-UTF-8 analytics file 500s all of `/plan/analytics` + APIs | Write a non-UTF-8 `analytics/<org>.json` → `/plan/analytics` 500, unrecoverable (delete also 500s) | `store.load_metrics` caught only `(OSError, json.JSONDecodeError)`, not `UnicodeDecodeError` | **fixed** dd2967d |
| QA-P7 | P2 | Non-UTF-8 board file 500s `/plan/board` + all board CRUD | Write a non-UTF-8 `plan_board/<org>.json` → `/plan/board` 500 | `board.load_board` same narrow guard | **fixed** dd2967d |
| QA-P8 | P2 | Phantom all-zero metric stored; error message lies; corrupts planner signal | All-zero `metrics` → 200 + stored empty row that reaches `MIN_SAMPLES` and emits a fake "100% below average" −6 nudge | Route never enforced the "at least one metric" its own 400 message promised | **fixed** dd2967d (route-level; store contract preserved) |
| QA-P9 | P3 | Unlabelled form inputs (a11y) | `/plan` event/goal add-row inputs + `/plan/board` "New idea" input had no `<label>`/`aria-label` | Missing accessible names | **fixed** dd2967d |
| QA-P10 | P2 | Plan requests do a full cross-tenant disk scan of `runs_v4` + `stub_packs` | Seed a foreign org with 2000 runs → a 3-run org's `/plan/calendar` ≈ 149 ms (scales with the whole deployment) | Gatherers glob every `*.json` and filter by `profile_id` *after* reading — no per-tenant namespacing/index | **logged** (see §7 — shared-storage change, out of blast radius) |
| QA-P11 | P3 | `runs_v4` parsed twice per request | `build_calendar` scans runs twice (posted + anniversary); `gather_all_signals` scans twice (own + external) | Independent `_iter_org_runs` calls | **logged** (§7 — touches tested signatures; low value) |
| QA-P8-copy | P3 | Em dash in digest error message | `digest.py:48` error string uses "—" | Literal em dash | **logged** — consistent with the codebase's pervasive house typography; sweeping one instance would be inconsistent noise (see §7) |

No secret leak, no injection, no IDOR, no unprotected route, and no XSS was found — those checks passed.

## 5. Fixes applied (commit dd2967d)

- **`analytics/store.py`** — `load_metrics` corrupt-file guard widened to `(OSError, ValueError)` (QA-P6).
- **`content_engine/board.py`** — `load_board` corrupt-file guard widened to `(OSError, ValueError)` (QA-P7).
- **`content_engine/signals.py`** — anniversary evaluated across `today.year ± 1`, closest chosen (QA-P1, new `_anniversary_on` helper mirroring the calendar); run-results summary pluralised (QA-P2).
- **`content_engine/planner.py`** — plan reason lines pluralised (QA-P2).
- **`web/web.py`** (plan routes only) — `/api/plan/analytics/record` guards non-dict metrics + rejects data-free submissions with the honest 400 (QA-P5, QA-P8); `/api/channel-preview` coerces `hashtags` to a list (QA-P4); calendar `_entry_chip` planned branch gains the non-drag reschedule field + `unschedule` control + `mhCalUnplan` JS (QA-P3); aria-labels on `/plan` event/goal inputs and `/plan/board` new-idea input (QA-P9).

Every fix reuses an existing pattern (the QA-016 guard widening, the `_rail_card` date field, the `'s' if n != 1` idiom) and is scoped to the Plan feature. `record_metric`'s store contract (it still stores a clamped row, per `test_record_clean_and_delete`) was deliberately preserved — the "at least one metric" gate lives in the route that makes the promise.

## 6. Tests added (8, all passing)

- `test_cross_source_planner.py::test_anniversary_signal_spans_year_boundary` — QA-P1: the boundary anniversary fires, has the right `years`/`delta`, reaches a ranked item, and matches the calendar.
- `test_cross_source_planner.py::test_signal_and_reason_copy_pluralise_singular_counts` — QA-P2.
- `test_performance_analytics.py::test_record_route_never_500s_on_malformed_metrics` — QA-P5 (metrics = int/str/list/bool → 400).
- `test_performance_analytics.py::test_record_route_rejects_data_free_submissions` — QA-P8 (all-zero + negative-only → 400, nothing stored; impressions-only still records).
- `test_performance_analytics.py::test_analytics_surface_survives_non_utf8_metrics_file` — QA-P6.
- `test_planner_board.py::test_board_survives_non_utf8_file` — QA-P7.
- `test_channel_preview.py::test_channel_preview_route_tolerates_non_list_hashtags` — QA-P4.
- `test_planner_calendar.py::test_planned_chip_has_nondrag_reschedule_and_unschedule` — QA-P3.

## 7. Cross-cutting changes & coordination items

- **Cross-cutting (small, made):** the fixes to `web/web.py` touch only the Plan route
  handlers/templates, but `web.py` is the shared monolith — flagged here for
  reconciliation. `/api/channel-preview` (QA-P4) is defined in the Plan section and used
  by the plan preview surface; it may also serve a latent editor live-preview. The
  coercion is strictly more robust and changes nothing for valid input.
- **QA-P10 (logged, NOT fixed — needs coordination):** eliminating the cross-tenant
  full-disk scan requires namespacing `runs_v4` / `stub_packs` by tenant or a per-org
  index — a change to shared storage layout used across the whole pipeline, well outside
  the Plan blast radius and high merge-conflict risk. It is a pre-existing characteristic
  of the app (the runs list scans the same way), not a Plan regression, and is harmless
  for a realistic club corpus (tens of runs). Recommend a separate, coordinated change.
- **QA-P11 (logged):** de-duplicating the twice-per-request run parse would change the
  signatures of `gather_own_signals`/`gather_external_signals`/`_posted_entries`/
  `_anniversary_entries` (all directly unit-tested). P3 value, non-trivial risk — left for
  a focused change.
- **QA-P8-copy (logged):** the em dash in the digest error string matches the codebase's
  established typography (raw em dashes / `&mdash;` are used pervasively across the Plan
  templates and Python copy). "Fixing" one instance would be inconsistent; a house-wide
  hyphen sweep is out of scope for a single-feature audit.

## 8. Residual risks

- **Cross-tenant scan latency (QA-P10)** at very large multi-tenant scale — see §7.
- **CSRF:** the Plan state-changing POSTs are same-origin `fetch` JSON with no CSRF token
  — the same convention as the rest of the app. Not a Plan-specific regression; if the app
  adopts CSRF tokens it should be app-wide, not Plan-only.
- **Run-id guessing** within an org (documented in `KNOWN_ISSUES.md`) — unchanged; cross-org
  access is enforced.
- **Anniversary `±1 year` window** assumes at most one relevant anniversary within the ±7d
  window per meet (true for a 7-day window); deliberately picks the closest.

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The Plan feature is functionally correct, deterministic,
source-grounded, tenant-isolated, XSS-safe, and honest without an AI provider — and it now
survives malformed input and corrupt persisted files without 500s after this audit fixed 8
findings (1×correctness, 3×unhandled-500, 1×data-integrity, 1×a11y-control, 2×copy/a11y).
The one caveat is the cross-tenant disk-scan latency (QA-P10), which only bites at
many-thousand-record multi-tenant scale and needs a coordinated shared-storage change.

## 10. Handover & merge status

- Branch: `claude/audit-plan-feature-t0a7hi` (the harness-assigned development branch; see
  the branch-name note at the top).
- Review the diff: `git diff origin/main...claude/audit-plan-feature-t0a7hi`
- Merge status: _completed in Phase 5 — see the final section appended below._
