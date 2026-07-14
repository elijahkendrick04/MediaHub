# Decomposing the `web.py` monolith into Blueprints (finding #15)

**Status:** in progress — Stage 0 landed; Stages 1–4 planned, not started.
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
