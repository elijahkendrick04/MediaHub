# Feature Audit — Settings ▸ Activity

**Feature slug:** `activity` · **Mode:** AUDIT+FIX · **Date:** 2026-07-10
**Branch:** `claude/activity-feature-audit-djfuym`
**Reviewer:** autonomous QA + fix session

---

## 1. Scope contract

**Definition.** The Settings ▸ "Activity" card (`/settings/activity`) is the
per-organisation run log. Its tile promises: *"Every run for this organisation
— status, matches, and one-click delete."* It is rendered by
`_render_settings_activity_section(prof)` in `src/mediahub/web/web.py`, and is a
**distinct surface** from the standalone `/activity` page (`activity_page`) and
the `/activity/feed` stream — those are out of scope except where behaviour must
stay consistent. "Working" means: for the pinned org (and only that org), it
lists recent runs with an honest status, the real engine output per run, and a
per-row delete that actually deletes and stays on the page; it degrades cleanly
with no org, no runs, or a store failure; and no user-controlled text can break
out into the page.

**Routes/endpoints owned or exercised.**
| Method | Path | Role |
|---|---|---|
| GET | `/settings/activity` | The feature page (via `settings_section("activity")` → `_render_settings_activity_section`) |
| POST | `/privacy/run/<run_id>/delete` | Per-row delete (shared with Privacy / standalone Activity; **not owned**) |

**Files owned (blast radius).**
- `src/mediahub/web/web.py` — `_render_settings_activity_section` (the section
  renderer) and the "Activity" tile spec in `_settings_card_specs`.

**Shared files depended on but NOT freely rewritten.**
- `web.py`: `privacy_delete_run`, `_delete_run`, `_run_owner_profile_id`,
  `_warm_run_achievements`, `_RUN_DELETE_JS`, the CSRF `before_request`, the
  org-setup gate, the `runs` table schema, `settings_section` dispatch.

**Inputs / outputs / state.** Input: the session's pinned `active_profile_id`
(no caller-supplied id → no read-side IDOR). Output: an HTML table of the org's
runs. State: read from the `runs` table in `DATA_DIR/data.db`, scoped by
`profile_id`; delete cascades run JSON + sidecars + DB row + caches via
`_delete_run`.

**Intended happy path (concrete).** Pin an org → open Settings ▸ Activity → see
each recent run as a row: Input (meet/file name, links to `/review/<id>`),
Status badge (done/queued/running/error), Matched (`our_swims`), **Achievements**
(the real V5 recognition count), Started (relative time). Errored runs show a
"Why did this run fail?" expander and a top "N runs failed" callout. Each row
has a Delete button that removes the run in place (optimistic + 8s undo) and
stays on the page.

---

## 2. Environment

- **Run locally:** `pip install -r requirements.txt` (+ `--ignore-installed
  PyYAML` for the debian-managed copy), `pip install -e . --no-deps`, `pip
  install pytest ruff`. Booted with `PORT=5001 python -m mediahub.web`.
- **Port:** `http://localhost:5001`. Startup clean apart from the expected
  `env_check: No LLM provider configured` warning (AI honest-errors offline).
- **Offline / no-spend:** `.env` created from `.env.example` with a random
  `SECRET_KEY`, `DATA_DIR` under the session scratchpad, and **no provider
  keys** (Gemini/Anthropic unset). The Activity feature makes no AI/paid calls,
  so no provider stubbing was required; `.env` is gitignored and never staged.
- **Browser:** Python Playwright against the prebaked Chromium at
  `/opt/pw-browsers` (the Playwright MCP defaulted to a missing `chrome`
  channel, so the direct driver was used). Desktop 1280px + mobile 390px.
- **Fixtures / stubs:** two seeded orgs (`club-a`, `club-b`) and runs covering
  done / error / queued, a modern **V5 run** (`our_swims=30`, `n_achievements=7`,
  legacy `n_cards`/`n_queue=0`), an XSS meet name, and unicode/emoji. Matching
  run JSON files written so `_prune_orphaned_runs()` (import-time cleanup of
  done rows whose JSON is gone) doesn't eat the seed.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
|---|---|---|---|
| 1 | Functional correctness | **FAIL → fixed** | Modern V5 runs showed "Queue / Total: 0 / 0", hiding the real `n_achievements`. Now an "Achievements" column (F-1). |
| 2 | Every interactive control | **PASS** | Delete (JSON `{ok:true}`), Input→`/review/<id>` (200 own / 404 cross-tenant), "Why did this run fail?" expander all correct. No dead/misrouted controls. |
| 3 | Input validation & edge cases | **PASS (w/ fixes)** | Empty org, no-runs, unicode/emoji, XSS name, error-without-text, >100 runs all handled; see F-2/F-4. |
| 4 | UI state handling | **PASS (w/ fix)** | loading (optimistic delete + undo), empty, error, success all render. Store-failure state fixed (F-5). |
| 5 | Server-side error handling | **PASS** | No 500s; bad run-id → 400, missing → 404, cross-tenant → 404, no CSRF → 403. No stack traces/paths leaked. |
| 6 | Data integrity | **PASS** | Counts read back correctly; tenant isolation holds on read and delete; delete cascades; re-render after delete is consistent. |
| 7 | Security | **PASS** | No read IDOR (active-profile only); delete guarded by `_run_owner_profile_id` cross-tenant check + run-id shape allowlist; CSRF enforced; meet name HTML-escaped via `_h()`; no secrets in output. Does not touch the passwordless `/developer` route. |
| 8 | Performance | **PASS** | Single `LIMIT 100` query + a bounded, self-healing achievements warm-up (JSON read once per row missing the column, then backfilled). No N+1 in steady state. |
| 9 | Responsive / a11y | **PASS (w/ fix)** | `mh-table-stack` collapses cleanly at 390px. Delete buttons given descriptive `aria-label`s (F-3). Residual: no `<table caption>` (low). |
| 10 | Rendered-graphic correctness | **N/A** | This feature renders no cards/PNGs. |
| 11 | Consistency & copy | **PASS (w/ fix)** | British English; no placeholder/debug/TODO. New copy uses plain hyphens. colspan mismatch fixed (F-6). |

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
|---|---|---|---|---|---|---|
| F-1 | **P1** | Activity shows legacy "Queue / Total" (0/0 for modern runs), hiding the real engine output | Seed a V5 run (`our_swims=30`, `n_achievements=7`, `n_cards=n_queue=0`); open `/settings/activity` → row reads **Queue / Total: 0 / 0**. | The renderer printed `n_queue / n_cards`, which the V5 recognition-first pipeline leaves at 0. The standalone `/activity` page was fixed (a "Council STEP 3" pass) to surface `n_achievements`; the Settings mirror was never updated. A successful run reads as "produced nothing". | **Fixed** | `08a65c0` |
| F-2 | P2 | "Every run" tile vs silent 100-run truncation | Seed 105 runs; only 100 shown, no notice. | `LIMIT 100` with no disclosure; tile copy promises "every run". | **Fixed** — honest "Showing the 100 most recent of N" note when older runs exist. | `08a65c0` |
| F-3 | P2 | Delete buttons indistinguishable to screen readers | Playwright a11y snapshot: 5 buttons, all accessible-named just "Delete". | No per-row `aria-label`. | **Fixed** — `aria-label="Delete <meet name>"`. | `08a65c0` |
| F-4 | P3 | Failure callout undercounts vs the red "error" badge | Seed two error runs, one with empty `error` text → callout said "1 run failed" while two rows show an error badge. | `n_errored` was incremented only inside `if status=="error" and error`. | **Fixed** — count on status alone; expander stays gated on captured text (never invent a reason). | `08a65c0` |
| F-5 | P3 | Store-read failure masquerades as an empty org | Monkeypatch `_db` to raise → page shows "No results yet for this organisation". | `except Exception: rows = []` conflated a DB failure with a genuinely empty org. | **Fixed** — distinct honest "couldn't reach the runs store" card. | `08a65c0` |
| F-6 | P3 | Error-detail row `colspan="7"` in a 6-column table | Inspect the error row markup. | Copy inherited a 7-column colspan; the table has 6 columns. | **Fixed** — `colspan="6"`. | `08a65c0` |
| F-7 | P3 | Input cell (meet/file name) has no length clamp | A very long unbroken meet name could stretch the row (error text is clamped to 600 chars; the Input cell is not). | Same pattern as the standalone `/activity` page; CSS `mh-table-stack` word-wraps in practice. | **Logged** (not fixed) — see §8; deliberately not diverged from the standalone page. | — |

No P0 found. The feature does not touch the known passwordless `/developer`
concern.

---

## 5. Fixes applied

All fixes are confined to `_render_settings_activity_section` in
`src/mediahub/web/web.py` (one function; **no shared file rewritten**):

1. **Achievements column (F-1).** Added `n_achievements` to the `SELECT` and
   call the existing `_warm_run_achievements(conn, rows)` helper (the same one
   the standalone page uses) before closing the connection; the "Queue / Total"
   column and header became "Achievements" fed by `ach_by_id`.
2. **Honest 100-run cap (F-2).** Added a bounded `SELECT COUNT(*)` and, when it
   exceeds the shown rows, a small "Showing the 100 most recent runs of N total"
   note under the table.
3. **Accessible delete (F-3).** Added `aria-label="Delete <label>"` to each
   per-row Delete button (label = meet/file name/id).
4. **Failure count (F-4).** `n_errored` now counts every `status=="error"` row;
   the "Why did this run fail?" expander stays gated on captured error text.
5. **Honest store-failure state (F-5).** A `db_failed` flag returns a distinct
   error card instead of the empty-state copy.
6. **colspan (F-6).** Error-detail row `colspan` corrected from 7 to 6.

---

## 6. Tests added

`tests/test_settings_activity_section.py` (new, 12 tests, all pass), following
the `tests/test_activity_scoping.py` fixture pattern:

- `TestAchievementsColumn` — locks the Achievements column shows `n_achievements`
  (not 0/0) and "Queue / Total" is gone; Matched still shows `our_swims`.
- `TestTenantIsolation` — pinned org sees only its own runs; empty-state for a
  no-runs org.
- `TestXssEscaping` — `<script>` in a meet name is HTML-escaped.
- `TestDeleteAffordance` — descriptive `aria-label`; delete form targets the
  privacy delete route with `next=/settings/activity`.
- `TestFailureCallout` — an error run with no error text is still counted;
  singular/plural wording.
- `TestTruncationNotice` — no note under 100 runs; honest note at 105.
- `TestDbFailure` — a runs-store read failure shows the honest error, not the
  empty state.

---

## 7. Cross-cutting changes

**None.** No shared file was rewritten. The fix reuses the existing shared
`_warm_run_achievements` helper (unchanged) and the shared `privacy_delete_run`
route (unchanged), editing only the single feature-owned function in `web.py`.

*Note (parallel-session traffic):* during the merge window the shared
`end-of-file-fixer` hygiene check was transiently red for all open PRs because a
sibling session's already-merged report had a stray trailing newline. It was
fixed upstream by that session before this branch merged, so this branch carries
no hygiene change of its own (a redundant fix committed here was dropped on
rebase as "already upstream").

---

## 8. Residual risks / cross-feature notes

- **F-7 (logged):** the Input cell isn't length-clamped. Left as-is to stay
  identical to the standalone `/activity` page; a fix should be applied to both
  surfaces together, not just here.
- **No `<table caption>`** for the runs table (the section intro supplies visual
  context but isn't programmatically associated). Low-priority a11y polish,
  shared with the standalone page.
- **Import-time `_prune_orphaned_runs()`** deletes `done` rows whose run JSON is
  missing. Correct sandbox behaviour, but it means seeded DB rows without JSON
  vanish on restart — a testing gotcha, not a feature bug. Out of scope.
- **Auth model:** any session that can pin an org sees that org's Activity. This
  is the app-wide profile/anti-enumeration model (ADR-0014), not specific to
  this feature — no change made.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS → WORKS (after fix).** The one material defect (F-1: every
modern run reading as "0 / 0 produced nothing") is fixed and test-locked, along
with five smaller correctness/honesty/a11y issues. One cosmetic residual (F-7)
is logged for a cross-surface fix. Security, tenant isolation, and error
handling were already sound.

---

## 10. Handover & merge status

- **Branch:** `claude/activity-feature-audit-djfuym` (the session's designated
  development branch, per the environment's Git requirements; all work and the
  final push go here).
- **PR:** #1112 against `main`. Merged on green at the operator's instruction,
  via a **merge commit** (the repo's only enabled method).
- **Green gate (integrated result):** the branch was rebased onto the live
  `origin/main` before merge; app boots clean; the new module (12) + a broad
  regression subset (activity / privacy / run / settings / web / security —
  1589 tests) pass, plus the full CI matrix on the integrated head (unit-suite
  shards, ground-truth oracle, bandit / semgrep / gitleaks / pip-audit,
  pre-commit hygiene, bloat guard, stylelint, responsive, schemathesis).
  `ruff` + full `pre-commit --all-files` clean; no secrets/`.env` staged.
- **Review the diff:** `git diff origin/main...claude/activity-feature-audit-djfuym`
