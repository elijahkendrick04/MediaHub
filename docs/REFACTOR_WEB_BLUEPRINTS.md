# Decomposing the `web.py` monolith into Blueprints (finding #15)

**Status: COMPLETE — stages 0–5 (2026-07-18).** Every route handler is out of
the closure: all **464 routes live in eleven importable `routes_*.py` surface
modules**, all helpers/constants and the tenant spine are module-level, and
`create_app` is **~440 lines of genuine wiring** — config, request hooks, the
three errorhandlers, scheduler/sentinel start-up, and the eleven
`register(app)` calls. See §"Outcome" below and ADR-0031 for the
endpoint-name decision. Remaining follow-up: bulk test migration onto the canonical `app`/`client`/
`web_module` fixtures (which landed on `main` in parallel via finding-#130 work
— this refactor's own `mh_*` fixture draft was superseded by them and dropped;
`tests/_helpers.py` here contributes `web_surface_src()` for source-scan tests).
**Scope:** `src/mediahub/web/web.py`. Deterministic engine (`interpreter/`,
`pb_discovery/`, `recognition*/`, the ranker, colour-science) is **out of scope
and untouched**.
**Source finding:** #15 of the 2026-07 deep code review — *"`create_app` is a
48k-line closure nesting all ~465 route handlers plus ~250 helpers as inner
`def`s that close over `create_app`-scoped locals. No surface can be split off,
unit-tested, or reasoned about in isolation."*

This document is the **staged, reversible** plan for that decomposition. It is
deliberately incremental: each stage is a small, independently-mergeable,
behaviour-preserving PR, and the highest-risk stages are explicitly gated on
maintainer sign-off.

---

## 1. The problem, measured

Numbers from the current tree (`ast`/`symtable` over `web/web.py`):

| Metric | Value |
| --- | --- |
| `web/web.py` total lines | ~69,200 |
| `create_app` span | lines 20,742 → 69,199 (**~48,460 lines, 70% of the file**) |
| Route handlers nested in `create_app` | **464** |
| Helper `def`s nested directly in `create_app` | **~240** (was ~249; Stage 0 hoisted 9) |
| Nested funcs that close over ≥1 `create_app` local | **587** |
| Module-level helpers already proving the pattern | `_load_run`, `_can_access_run`, `_load_run_input`, `_layout`, + ~190 others |

Because everything is an inner `def`, **nothing** below `create_app` can be
imported, unit-tested, mocked, or reasoned about without building the whole
Flask app. A single 48k-line function is also unreviewable and a merge-conflict
magnet.

## 2. The seam — what actually couples the closure

The 587 coupled nested functions do **not** each close over 240 different
things. They close over a small **tenant-resolution spine**. The most-depended-on
`create_app`-scoped names:

| Dependents | Name | Role |
| ---: | --- | --- |
| 245 | `_active_profile_id` | session → active tenant (org) id |
| 70 | `_active_profile` | loads the active `ClubProfile` |
| 37 | `app` | `.config` / `.logger` / `.response_class` / `.secret_key` |
| 37 | `_session_can_access_profile` | tenant-gate |
| 21 | `_user_store` | user/session backing store |
| 17 | `_video_project_store` | video-surface store |
| 15 | `_session_can_use_profile` | tenant-gate |
| 15 | `_resolve_run_brand_kit` | brand resolution for a run |
| 12 | `_safe_next` | safe-redirect (Stage 0: **hoisted**) |
| 11 | `_active_role` | session role (owner/admin/member) |
| … | `_require_operator`, `_memberships_snapshot`, `_op_flash`, `_csrf_token`, … | gates / CSRF |

**Consequence for sequencing:** a session-authenticated surface cannot leave the
closure until this spine is importable. That is why the finding orders it
*helpers first, Blueprints second*. `api_public/blueprint.py` (the existing first
Blueprint) sidesteps the spine entirely — it authenticates by **bearer token**
(`g.api_*`), not session — which is exactly why it could be extracted already.

The closed-over `app` is only used for `.config`, `.logger`, `.response_class`,
and `.secret_key` inside helpers — every one of which is reachable from
`flask.current_app` in request context. The `@app.route` / `@app.before_request`
/ `@app.errorhandler` **registrations** stay in `create_app` (or become
`bp.*` on a Blueprint); they are not part of the seam.

## 3. The blocker — test coupling (findings #129 & #130)

This refactor is **substantially blocked by the test suite**, and honesty about
that ordering is the whole point of this doc:

- **#130 — fixture sprawl.** `tests/conftest.py` has **no** shared
  `app`/`client`/`DATA_DIR` fixtures. **305 test files** call `importlib.reload`
  on the monolith and re-`create_app()` by hand. Moving code between modules
  changes what `importlib.reload(web)` rebuilds, so template/route relocations
  ripple into hundreds of files.
  - **Status: done.** The canonical `app`/`client`/`web_module` fixtures +
    autouse `_isolate_data_dir` (Stage 3) are on `main`, and every test file
    that reloaded the `web.py` monolith has been migrated onto them across
    batched follow-up PRs — including the final "judgment batch" of files whose
    reload also picked up an env var (each such flag was verified read *live*
    inside a function, not at `web.py` import, so `monkeypatch.setenv` before
    `create_app()` reproduces the behaviour without the reload; provider-key
    `delenv`s and other honest-error setups were kept verbatim). Assertion
    counts were held identical per file. **One** web.py reload is deliberately
    retained: a single test in `tests/test_public_wall.py` asserts the
    import-time `RUNS_DIR` constant re-derives from a `RUNS_DIR` env var pointing
    *outside* `DATA_DIR/runs_v4` — a state the canonical fixtures structurally
    cannot represent, so it stays a genuine load-bearing reload. The ~30 test
    files that still call `importlib.reload` reload *non-web* modules
    (`club_profile`, `imagine_usage`, `secrets_store`, `uptime`, `presenter`,
    the interpreter, …) for their own module-state isolation and are out of
    scope for #130.
- **#129 — implementation-detail asserts.** **207 test files** assert on literal
  `mh-*` CSS class strings, raw HTML tags, and hardcoded URL paths pulled from
  `web.py`'s f-string templates (0 use a stable `data-testid` today). A pure
  template move breaks huge swaths of the suite even when behaviour is identical.

**Therefore:** helper hoisting (Stages 0–2) is safe to do *now* because it does
not move templates or change URLs. Blueprint extraction that relocates templates
(Stage 4) must be preceded by the test-decoupling work (Stage 3), or it will be
drowned in incidental test churn.

## 4. Staged plan

Each stage is one-or-more small PRs off `main`. Every PR: full suite green
(`~13,260` collected), `test_autotest_ground_truth.py` (the oracle) green,
`url_for()`/`DATA_DIR` discipline held, and the CLAUDE.md 15-step
route/data-structure checks for anything moved. **No route URL and no
tenant-gate semantics change** in any stage without explicit maintainer sign-off.

### Stage 0 — Hoist pure leaf helpers ✅ (this PR)

Move **closure-free** (`symtable.get_frees() == ∅`) leaf helpers to module level.
Zero behaviour change: each references only module-level names, is defined once,
and has no test currently pinning it by name. Landed in this PR:

`_format_uptime_pct`, `_humanize_duration`, `_humanize_when`, `_pounds_to_pence`,
`_pence_str`, `_safe_filename`, `_nl_range`, `_parse_month_param`,
`_org_calendar_sport`.

Payoff proven by `tests/test_web_hoisted_helpers.py` — 24 assertions that import
these helpers **directly** and run in 0.2s with **no `create_app()` and no
`importlib.reload`**. That is the finding's "unit-tested in isolation" promise,
demonstrated on a first slice.

### Stage 1 — Hoist the remaining closure-free helpers (batched)

~128 more helpers have zero closure captures (verified by `symtable`) and are
mechanically hoistable the same way. Do them in **themed batches** (one PR each,
~10–20 helpers), so review stays legible and any regression is bisectable:

- **1a — formatting/render fragments:** `_settings_card_specs`,
  `_render_settings_*_section` (the closure-free ones), `_coming_soon_card`,
  `_brand_swatch_row`, `_plan_subnav`, `_render_activity_feed`, …
- **1b — money/id/path utilities:** `_client_ip`, `_pence_str` siblings,
  `_v9_*_history_path`, `_intro_seen_path`, `_export_quick_dir`, …
- **1c — payload/error builders:** `_motion_error_payload`,
  `_reformat_error_payload`, `_imagine_error_response`, `_billing_error_body`, …
- **1d — video/footage read helpers:** `_video_render_dir`, `_video_safe_look`,
  `_video_norm_source`, `_project_source_states`, `_video_footage_summary`, …

Preferred landing site: a new **`src/mediahub/web/helpers.py`** imported back
into `web.py` (`from .helpers import *`-free, explicit names), so the helpers
become genuinely isolated and the monolith shrinks. Same-module hoisting (as in
Stage 0) is the fallback when a helper references many `web.py` module globals.
Skip any helper a test pins by literal name until Stage 3 gives it a stable
handle.

### Stage 2 — Extract the request-context spine ⚠️ **GATED**

Create **`src/mediahub/web/context.py`** holding the tenant-resolution spine as
module-level functions that read `flask.g` / `flask.session` / `flask.request`
and `flask.current_app` instead of closing over `app`:

`_active_profile_id`, `_active_profile`, `_active_role`, `_session_can_access_profile`,
`_session_can_use_profile`, `_memberships_snapshot`, `_user_store`,
`_require_operator`, `_pin_active_profile`.

Keep per-request memoisation on `flask.g` (as `_memberships_snapshot` already
does). `create_app` imports these and keeps its `app.active_profile_id = …`
attribute exposure for back-compat. This is the linchpin that unblocks every
session Blueprint.

> **STOP / sign-off required.** This stage relocates the **tenant-gate**
> machinery. Even though the intended change is behaviour-preserving, per the
> session's standing instruction *"STOP and ask before any change that alters a
> route's URL or a tenant-gate."* Stage 2 does not begin without explicit
> maintainer approval, a dedicated PR, and the full 15-step check on each moved
> gate. Multi-tenant isolation tests (`test_*tenant*`, `test_*org*access*`,
> `_can_access_run` suites) are the acceptance oracle.

### Stage 3 — Decouple the tests (unblocks Stage 4)

Prerequisite for any template-moving Blueprint work. Two workstreams, each
mergeable independently and valuable on its own:

- **3a (#130):** add canonical `app` / `client` / autouse `_isolate_data_dir`
  fixtures to `tests/conftest.py`; migrate files off hand-rolled
  `setenv(DATA_DIR) + importlib.reload(web) + create_app()`. Cuts the 305-file
  reload sprawl and the reload-induced `isinstance` heisenbugs.
- **3b (#129):** add a shared `assert_has_control(html, testid=…)` helper and
  seed stable `data-testid` anchors on the controls that tests care about;
  migrate the incidental `mh-*` class asserts onto semantics. Do this per-surface
  **just before** that surface's Blueprint move, so churn is co-located.

### Stage 4 — Carve Blueprints, largest-first

Mirror `api_public/blueprint.py`: a `build_<surface>_blueprint()` factory
returning a `Blueprint(url_prefix=…)`, registered in `create_app` via
`app.register_blueprint(...)`. Handlers import the Stage 2 context spine and
Stage 1 helpers. **URL paths are preserved exactly** (`url_prefix` + same rule
suffixes ⇒ identical `url_map`); any deviation is a STOP.

Order (authoritative counts from finding #15; extracting these four moves
**~14,000 lines / 153 routes** out of the closure):

1. **`api/runs`** — 72 routes / ~5,856 L. Mostly JSON, lighter template
   coupling ⇒ best first carve.
2. **`organisation`** — 26 routes / ~4,664 L.
3. **`media-library`** — 36 routes / ~2,357 L.
4. **`video`** — 19 routes / ~1,260 L (reel/motion; pairs with `visual/motion.py`).

Each Blueprint is its own PR with the **15-step before + 15-step after** checks
(§B below) and a route-parity assertion: snapshot `sorted(url_map)` before and
after and diff to zero.

## 5. Per-move checklist (CLAUDE.md §A/§B)

For every helper/route/data-structure moved:

- **Before:** whole-repo grep for the name; find `url_for()` targets, template
  references, JS/`fetch` callers, `DATA_DIR` persistence, feature-flag gating
  (`_club_platform_ok`/`_v73_ok`/`_v8_ok`), AI-surface producers/consumers,
  dynamic (`getattr`/`**kwargs`) refs, and every test that pins it. Write the
  breakage list.
- **After:** re-grep for zero stray refs; confirm no dangling `url_for()`;
  imports resolve; **full suite green with no new failures and no test
  weakened**; affected routes exercised end-to-end; templates render; old
  persisted runs still load; flags still gate; **engine output byte-identical**;
  no new debug/admin/IDOR exposure; no key leak; clean diff.
- **Dead-code sweep** at the end of every stage: drop orphaned imports,
  now-dead branches, stale comments — no `_unused` shims or "removed" placeholders.

## 6. Risk register & stop conditions

| Risk | Mitigation |
| --- | --- |
| Silent tenant-gate weakening | Stage 2 is gated on sign-off; tenant-isolation tests are the oracle; no gate logic edited, only relocated. |
| Route URL drift | `url_prefix` + suffix parity; before/after `url_map` snapshot diff must be empty; STOP on any change. |
| Template-move test avalanche | Stage 3 precedes Stage 4; `data-testid` anchors added before the move. |
| Reload heisenbugs during migration | Stage 3a shared fixtures replace `importlib.reload`; run suite with and without `-n auto` to catch order-dependence. |
| Deterministic engine drift | Engine modules are out of scope; §B step 12 asserts identical parser/detector/ranker output. |

**Hard stops (ask first):** any change to a route's URL; any change to
tenant-gate *semantics* (not just location); Gemini-ifying anything on the
deterministic-engine boundary (never in scope here).

## 7. Outcome (stages 0–4, shipped 2026-07-14)

Maintainer-authorized completion of every stage, including the previously
gated Stage 2. All moves verified by: symtable safety gates + per-function
AST-equivalence proofs (verbatim moves), `url_map` snapshot diff (rule
strings, endpoint names, methods — byte-identical at every stage), hook-order
capture, and the full suite.

| Stage | What shipped |
| --- | --- |
| 0 | 9 pure formatter/parser helpers hoisted + isolation tests (PR #1258). |
| 1 | 147 closure-free helpers hoisted by the fixpoint engine (3 rounds). |
| 2 | Tenant spine extracted: `_active_profile_id` & friends module-level; `app.config` → `current_app.config`; the six request hooks converted to explicit `app.before_request(...)`/`after_request`/`teardown_request` registration at identical positions; gate semantics unchanged. |
| 1b | Last non-route captures cleared: constants module-level; per-app mutable state (`_auth_attempts`, complaint throttle, icon cache) on `app.extensions` via `_app_state()` (per-app isolation preserved); `_login_idle_seconds()` / `_preview_render_timeout()` read env per call. |
| 3 | Landed on `main` in parallel (canonical `app`/`client`/`web_module` fixtures + `tests/_semantic.py`, findings #129/#130) — this PR contributes `tests/_helpers.py::web_surface_src()` and repairs the source-scan tests the carve exposed. Bulk migration of the reload-preamble files was completed as batched follow-up PRs: all files that reloaded the `web.py` monolith are on the canonical fixtures, leaving exactly one deliberate load-bearing reload (`test_public_wall.py`, `RUNS_DIR` outside `DATA_DIR/runs_v4`). See §3. |
| 4 | `routes_api_runs.py` (74), `routes_organisation.py` (29), `routes_media_library.py` (32), `routes_video.py` (19) — handlers carved out with `W.<name>` call-time references (the `@require_run` tenant guard moves with its handlers as `@W.require_run`); registered via `register(app)` with ORIGINAL endpoint names (ADR-0031). |
| 5 | **The remaining 311 routes (~23.3k lines), carved 2026-07-18** — the last 14 `create_app`-local constants hoisted verbatim, then seven surface modules generated by a deterministic carve toolkit: `routes_auth.py` (17), `routes_site.py` (43), `routes_review.py` (22), `routes_planner.py` (61), `routes_creative.py` (65), `routes_api_misc.py` (74), `routes_operator.py` (29). Same mechanics as stage 4 (`W.<name>` call-time refs, `current_app` for the captured `app`, original endpoint names). Verified per surface by per-handler AST-equivalence proofs (which also prove every template string byte-identical), a zero-diff `url_map` snapshot (491 rules), static zero-unresolved-globals checks, a runtime `W.<attr>` resolution probe, and an independent multi-lens adversarial audit. Orphaned in-`create_app` design comments were relocated next to their carved handlers (sw.js/offline-queue spec, healthz/usage, SEC-27 auth brakes, C-11 stub retirement, PC.1/PC.2, PC.7 demo, media-ingest security notes); source-scan tests migrated onto `web_surface_src()`. |

`web.py`: 69.6k → **~32.2k lines**. `create_app`: 48.5k lines / 464 routes +
~250 nested helpers → **~440 lines of registrations & wiring** (config,
hooks, errorhandlers, scheduler/sentinel start-up, eleven `register(app)`
calls). Every helper and **all eleven surfaces** are importable and
unit-testable without building the app — finding #15 is closed.
