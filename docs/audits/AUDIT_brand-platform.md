# Audit — Brand platform (Settings)

**Feature:** the "Brand platform" surface in Settings (roadmap 1.12).
**Mode:** AUDIT+FIX. **Branch:** `claude/brand-platform-audit-rrgi64`.
**Date:** 2026-07-10. **Verdict:** WORKS-WITH-CAVEATS → **WORKS** after fixes.

---

## 1. Scope contract

**Definition.** The Brand platform is the per-org brand home at `/brand` plus its
management API: a multi-kit model (primary / sponsor / event / section / personal
kits with palettes, font pairing, tone, token locks and group-approver rules),
Adobe `.ase` / Color-JSON palette import, a kit-edit → re-render sweep with diff
preview, and a per-card deterministic Brand Check with optional AI Brand
Assist (advise / auto-fix). "Working" means an org admin can view every kit,
create/edit/delete/set-default/lock kits, import a palette, and preview+apply a
re-render sweep; non-admins get a coherent (read-only) experience; brand-check
scores a design deterministically; AI surfaces honest-error without a provider;
and all state round-trips exactly through `ClubProfile.brand_kits` /
`default_kit_id`.

**Routes owned** (all in `src/mediahub/web/web.py`):

| Method | Path | Endpoint |
|---|---|---|
| GET | `/brand` | `brand_home_page` |
| POST | `/api/brand/kits` | `api_brand_kit_create` |
| POST | `/api/brand/kits/<kit_id>` | `api_brand_kit_update` |
| POST | `/api/brand/kits/<kit_id>/delete` | `api_brand_kit_delete` |
| POST | `/api/brand/kits/<kit_id>/default` | `api_brand_kit_set_default` |
| POST | `/api/brand/kits/<kit_id>/palette/import` | `api_brand_kit_palette_import` |
| GET/POST | `/api/brand/kits/<kit_id>/resweep/preview` | `api_brand_kit_resweep_preview` |
| POST | `/api/brand/kits/<kit_id>/resweep/apply` | `api_brand_kit_resweep_apply` |
| GET | `/api/runs/<run_id>/card/<card_id>/brand-check` | `api_card_brand_check` |
| POST | `.../brand-check/advise` | `api_card_brand_advise` |
| POST | `.../brand-check/autofix` | `api_card_brand_autofix` |

**Files owned (blast radius):** the brand block of `web/web.py`
(`_brand_can_admin`, `_render_brand_home`, `_brand_kit_card_html`,
`_brand_swatch_row`, `_brand_identity_html`, `_form_palette`, `api_brand_kit_*`,
`_brand_check_context`) and constants `_BRAND_FONT_PAIRINGS`/`_BRAND_LOCK_LABELS`;
`brand/kits.py`, `brand/check.py`, `brand/palette_file.py`, `brand/resweep.py`,
`brand/tone.py`; `tests/test_brand_home_web.py`.

**Shared files depended on (not freely rewritten):** the CSRF layer
`_csrf_protect` / `_security_headers`, `_load_run`, tenancy/session helpers,
`workflow/governance.py`, `brand/palette.py`, `web/club_profile.py`.

**Inputs/outputs.** Input: form posts (kit fields, colour pickers, lock/approver
rules), an uploaded `.ase`/JSON palette file, and run/card ids for brand-check.
Output: the rendered `/brand` page, redirects with `?msg`/`?err` banners, JSON
(resweep/brand-check), and persisted `ClubProfile.brand_kits` / `default_kit_id`.

**Happy path.** Admin opens `/brand` → sees each kit (swatches, role, locks) →
creates/edits a kit or imports a palette → optionally previews and applies a
re-render sweep (affected cards re-queued for review, never auto-published) →
per card, brand-check returns palette/contrast/fonts/logo findings.

---

## 2. Environment

- Installed deps with `pip install -e . --ignore-installed PyYAML` + `pytest`;
  Python 3.11.15, Flask 3.1.3, coloraide present.
- Ran the app locally via the Flask **test client** (mirrors
  `tests/test_brand_home_web.py`): `DATA_DIR`/`RUNS_DIR`/`SWIM_CONTENT_PROFILES_DIR`
  → per-test tmp dirs; **all LLM keys unset** so AI surfaces honest-error (no real
  spend). `app.config["TESTING"]=True`; production CSRF simulated with
  `app.config["ENFORCE_CSRF"]=True`.
- No real paid API calls, no external publishing, no live-Render testing.
- App boots clean; smoke check: `/`, `/healthz`, `/sign-in`, `/pricing` all load
  (200), `/brand` redirects when signed out (302).

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
|---|---|---|---|
| 1 | Functional correctness | PASS | Kit CRUD round-trips to `brand_kits`; palette import maps ordered colours→slots (ASE binary + Color JSON + hex list); resweep preview detects affected cards; brand-check returns the 4 findings with correct pass/fail. |
| 2 | Every interactive control | FAIL→FIXED | Resweep Preview/Apply were CSRF-dead in prod (F1); non-admins saw admin controls that 404 (F3); resweep JS masked errors as success (F5). |
| 3 | Input validation / edge cases | MOSTLY PASS | Palette parser robust (empty/oversized/garbage/CMYK/LAB/nested-JSON/1000-colours all clean); kit name unicode/emoji/10k accepted+escaped; approver rule clamped; kit_id traversal safe. Gaps: over-long run_id 500 (F4); role coercion mints duplicate primary (F6). |
| 4 | UI state handling | PASS (after F5) | Empty state → synthesised primary; `?msg`/`?err` banners escaped; resweep 0-affected and error paths now handled. |
| 5 | Server-side error handling | FAIL→FIXED | Over-long run_id raised an uncaught `OSError` → 500 + internal path in logs (F4); now anti-IDOR 404. |
| 6 | Data integrity | FAIL→FIXED | No-op save fabricated accent/fourth palette colours (F2). Import isolation and idempotency verified clean. |
| 7 | Security | PASS | Every POST route gates on `_brand_can_admin`; cross-tenant run → 404 not 403; kit/name/tone/font/banner sinks HTML-escaped (`_h`); palette upload size/type-bounded, filename never used as a path; advise/autofix honest-error leaks no key. CSRF: forms auto-inject the token; resweep gap fixed (F1). |
| 8 | Performance | PASS-with-note | Resweep `apply` recomputes `preview_kit_change` per chunk (O(chunks×briefs) brief resolutions); bounded and dominated by the Playwright render, documented in code — see Residual risks. |
| 9 | A11y basics | PASS (improved) | Colour pickers and the palette-file input now carry aria-labels; buttons are real `<button>`; swatch hex is in `title`/text, not colour-only. |
| 10 | Rendered-graphic correctness | N/A here | `/brand` renders no card graphics; the render sweep re-runs the existing graphic pipeline (out of this feature's scope). |
| 11 | Consistency / copy | PASS | British English ("colour"), no placeholder/TODO/debug text. (Existing em dashes are the repo-wide house style and were left untouched; no new ones added.) |

---

## 4. Findings

| id | sev | title | reproduction | root cause | status | commit |
|---|---|---|---|---|---|---|
| F1 | **P1** | Resweep Preview/Apply dead in production (CSRF) | With `ENFORCE_CSRF`, the browser-style `fetch(preview,{method:'POST'})` (no token, no JSON ctype) → **403** `{"error":"csrf"}`. | `_render_brand_home` inline JS sent neither `X-CSRF-Token` nor `application/json`; `_csrf_protect` requires one. | **fixed** | 0874e5a |
| F2 | **P2** | No-op "Save kit" fabricates accent/fourth palette colours | Render `/brand`, submit the primary-kit edit form unchanged → palette gains `accent`/`fourth` = primary. | `_kit_colour_slot` fills unset pickers with `_pal_default`; `<input type=color>` always submits, so `_form_palette()` persists the fallback. | **fixed** | 0874e5a |
| F3 | **P2** | Non-owner member sees admin controls that 404 | Bound org + Viewer session → `/brand` shows Create/Edit/Import/Resweep, but every POST → 404. | `brand_home_page` never called `_brand_can_admin`; render gate diverged from the POST gate. | **fixed** | 0874e5a |
| F4 | **P2** | Over-long `run_id` 500s brand-check (path leak) | `GET /api/runs/<3000×'a'>/card/c1/brand-check` → **500**, logs `OSError ENAMETOOLONG` + internal `RUNS_DIR` path. | `_load_run` calls `p.exists()` outside its try/except; `_brand_check_context` didn't catch it. | **fixed** (in-scope guard) | 0874e5a |
| F5 | P3 | Resweep JS treats error JSON as benign | `POST .../resweep/preview` for a missing kit → 404 JSON, but JS shows "No cards would change"; apply shows false "0 re-queued". | Neither `fetch().then()` checked `r.ok`. | **fixed** | 0874e5a |
| F6 | P3 | Invalid/`primary` role mints a 2nd, undeletable primary | `POST /api/brand/kits` `role=primary` (or `wizard`) → `normalise_kit` coerces unknown→primary → 2 primaries, none deletable. | `api_brand_kit_create` passed `role` unconstrained. | **fixed** | 0874e5a |

All six were confirmed by running a repro before fixing and re-running after.
XSS injection into kit name (and quote-breaking payloads) was tested and is
correctly escaped — no finding.

---

## 5. Fixes applied

All in `src/mediahub/web/web.py` (brand block); tests in
`tests/test_brand_home_web.py`. Single commit `0874e5a`.

- **F1/F5** — `_render_brand_home`: the resweep driver is now built as
  `resweep_js`, emitted only for admins, sends `X-CSRF-Token` on both fetches,
  and uses a `jok(r)` helper that throws on `!r.ok` so the existing `.catch`
  surfaces "Preview failed." / "Apply failed." on any error status.
- **F2** — `_kit_colour_slot`: unset slots render a `disabled` colour picker
  behind a "set" checkbox (`onchange` toggles `disabled`); disabled inputs aren't
  submitted, so a no-op save round-trips the palette and no colour is fabricated.
  Setting a slot still works (tick → enabled → submitted). `_form_palette` and the
  update route are unchanged.
- **F3** — `brand_home_page` passes `can_admin=_brand_can_admin(pid)` into
  `_render_brand_home` → `_brand_kit_card_html`; the create form, per-kit actions,
  edit form, import and resweep controls are gated, leaving a read-only card
  (name, swatches, locks, identity) for non-admins.
- **F4** — `_brand_check_context` wraps `_load_run(run_id)` in `try/except OSError`
  → anti-IDOR 404 (covers brand-check/advise/autofix). Root cause in shared
  `_load_run` left untouched and logged below.
- **F6** — `api_brand_kit_create` constrains `role` to
  `{sponsor,event,section,personal}`, defaulting to `sponsor`.
- **a11y** — aria-labels on the four colour pickers and the palette-import file
  input.

---

## 6. Tests added

Added to `tests/test_brand_home_web.py` (9 tests, all passing):

- `test_resweep_js_carries_csrf_token_and_ok_guard` — rendered JS has
  `X-CSRF-Token` + `if(!r.ok)` (F1/F5).
- `test_resweep_csrf_enforced_needs_token` — with `ENFORCE_CSRF`, a tokenless
  resweep POST 403s and the header path returns 200 (F1).
- `test_edit_form_unset_slots_disabled_and_noop_save_preserves_palette` — unset
  pickers disabled; no-op save leaves palette unchanged (F2).
- `test_edit_form_can_still_set_a_new_colour` — guard: explicit set still works.
- `test_brand_home_read_only_for_non_owner_member` /
  `test_brand_home_shows_controls_for_owner` — viewer read-only vs owner full (F3).
- `test_brand_check_overlong_run_id_is_404_not_500` (F4).
- `test_create_kit_cannot_mint_second_primary` (F6).

Full module: **22 passed**. Broad brand subset (`test_brand_*`, F10 form,
governance, brand a11y, v8 upload): **105 passed**. CSRF/settings/security-headers/
self-hosted-fonts/org-setup subset: **60 passed**.

---

## 7. Cross-cutting changes

- **No shared *code* files changed.** F4's root cause is in the shared
  `_load_run` (it stats `p.exists()` outside its try/except); I fixed it only for
  this feature's routes (in `_brand_check_context`) to keep the blast radius tight
  and avoid conflicting with other in-flight audits. See Residual risks for the
  shared item to coordinate.
- **One shared-build hygiene fix (not code):** `docs/audits/AUDIT_meet-recap.md`
  (another session's report, already on `main`) ended with a trailing blank line,
  which `end-of-file-fixer` flags. The pre-commit "Hygiene hooks" check runs
  `--all-files`, so this pre-existing violation red-ed CI on every open PR,
  including this one. Trimmed it to a single trailing newline (no content change)
  to unblock the shared gate. Flagged here for reconciliation with the meet-recap
  session.

---

## 8. Residual risks / cross-feature work (not attempted here)

- **Shared `_load_run` ENAMETOOLONG (coordination item).** Every route that
  passes a user-controlled `run_id` into `_load_run` has the same 500 + path-leak.
  The one-line systemic fix is to move `p.exists()` inside `_load_run`'s existing
  `try/except (OSError, …)`. Left for a shared-file owner to avoid a merge clash;
  this feature is guarded regardless.
- **Resweep apply is O(chunks × briefs).** Each apply chunk recomputes the full
  `preview_kit_change` and re-skips earlier cards via the offset cursor. Bounded
  and dominated by the per-card Playwright render (seconds each), and documented
  in code, so not fixed here; a cheap win would be to compute the affected list
  once and cache it across chunks.
- **Resweep chunk ordering relies on `glob` stability.** `iter_profile_briefs`
  yields briefs in unsorted `glob` order; the offset cursor assumes it's stable
  across chunk requests. It is in practice (the briefs dir isn't mutated during a
  sweep), but sorting the `cb_*.json` glob would make it robust — a small,
  low-risk follow-up in `brand/resweep.py`.
- **Create form still captures its default pickers.** A new kit created without
  changing the (enabled) create-form pickers pins the three generic defaults
  rather than inheriting the club base. Lower impact than F2 (the values are
  visible during an explicit "create"), so left as-is; the F2 checkbox pattern
  could be extended to the create form if inherit-by-default is preferred.

---

## 9. Feature verdict

**WORKS** (was WORKS-WITH-CAVEATS). The core flow — view/manage kits, lock
tokens, import palettes, preview+apply the re-render sweep, deterministic
brand-check with honest-error AI assist — is correct and access-controlled. The
one production-breaking control (the CSRF-dead resweep, P1) and the silent
palette-data mutation (P2) are fixed and locked with tests; the remaining
findings were smaller robustness/UX gaps, all fixed.

---

## 10. Handover & merge status

- **Branch:** `claude/brand-platform-audit-rrgi64` (the harness-designated audit
  branch; used in place of `audit/brand-platform` per the environment's
  branch policy).
- **Merge status:** see the PR opened for this branch. Per the managed-environment
  rules, changes land via a draft PR rather than a direct push to `main`; the
  green gate (relevant test subsets, ruff lint+format on the pinned v0.8.4, boot
  smoke) was run on the integrated result.
- **Review the diff:** `git diff origin/main...claude/brand-platform-audit-rrgi64`

_Assumptions recorded: (1) the audit ran on the harness-designated branch, not
`audit/brand-platform`, because the environment forbids pushing to a different
branch; (2) landing is via a draft PR, not a direct `main` push, per the managed
GitHub integration; (3) the parallel audit workflow was rate-limited partway, so
the security / errors-performance / a11y dimensions were completed by hand._
