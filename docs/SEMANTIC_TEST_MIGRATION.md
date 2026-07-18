# Semantic test-assertion migration (deep-review #129)

**In plain words.** Hundreds of tests check the web UI by looking for exact CSS
class names and chunks of HTML inside the page (`assert 'class="mh-action-dock"'
in html`). That pins the *styling*, not the *behaviour* — so the moment we tidy
up or move markup around (which the big `web.py` split, #15, needs to do), those
tests go red even though every button still works. This plan swaps those brittle
checks for stable ones: each control gets a `data-testid` hook and a shared
helper asserts *"a control that does X exists"* instead of *"this CSS class
string is somewhere in the blob"*. Same guarantee, no false breakage.

Status: **helper + convention + first proof-of-concept slice landed** (the mobile
action dock). The rest is scoped into route-sized slices below.

---

## 1. The problem, measured

A subsystem survey of the suite (read-only) bucketed every "brittle" assert — one
referencing an `mh-` class, a `data-*` string, a literal HTML tag, or a hardcoded
URL — by **where the string it tests came from**. That origin is what decides
whether the assert is brittle template-scraping or a legitimate contract:

| Bucket | What it asserts against | ~asserts | ~files | Migrate? |
|---|---|---:|---:|---|
| **1. Rendered-HTML template scrape** | HTML from a Flask route (`client.get(...).get_data()`) or a `_layout`/page render | **~1,040** | **~185** | **Yes — the target** |
| 2. CSS-file contract | text of a `.css` read from disk (`theme-components.css`, `BASE_CSS`) | ~97 | ~31 | No — it's the stylesheet's own contract |
| 3. JS-source contract | text of a `.js` read from disk (`ui-kit.js`) | ~26 | ~14 | No — it's the script's own contract |
| 4a. Pure-function unit | return value of a pure helper (the syntax highlighter's `mh-tok-*`, SVG/chart fragment builders) | ~79 | ~16 | No — a function-output contract |
| 4b. `_render_*` fragment scrape | return value of an *internal template-fragment* renderer (`_render_factor_breakdown`, `_render_reactions`, `apply_render_hooks`) | ~100 | ~10 | **Opportunistically** — see §6 |
| 5. web.py source-text scrape | `web.py` read as source text, asserting an f-string literal is present | ~18 | ~12 | **Convert or drop** — see §6 |

**Only bucket 1 (and, adjacent, 4b) breaks on a template refactor.** Buckets 2,
3, and 4a assert on files/functions that a *template* refactor does not touch, so
they stay exactly as they are. Conflating them is why the headline number looked
like "~1,300 assertions" — the real migration surface is **~1,040 route-scrape
asserts across ~185 files**, plus a ~100-assert bucket-4b tail to mop up.

The dominant bucket-1 targets cluster on a handful of routes: **`/` (landing)**,
**`/about`**, **`/review/<run>`**, **`/media-library`**, **`/make/<type>`**,
**`/help`**, **`/pricing`**, **`/pack/<id>`**, **`/season`**, **`/developer/api`**.
Adding testids to those ~10 templates retires the bulk of the surface.

---

## 2. The solution: a stable hook + a shared helper

### 2.1 `data-testid` — the stable hook

Every control or region a test needs to find gets a `data-testid` attribute:

```html
<nav class="mh-action-dock" data-testid="action-dock" aria-label="Quick review actions">
  <a href="{{ url_for('make_page') }}" data-testid="dock-create">Create</a>
  <button data-testid="dock-approve" data-mh-dock-approve>Approve</button>
</nav>
```

Why a new attribute rather than reusing the `mh-*` class or the existing
`data-mh-*` behaviour hooks?

- **`mh-*` classes are styling.** They're renamed/merged/split freely during a
  refactor — that's the whole point of the refactor. A test must not depend on
  them.
- **`data-mh-*` hooks are JS wiring.** They're more stable than classes (JS
  breaks if they move), but they exist only where the frontend happens to need
  them, and their naming follows JS needs, not test needs. Good to *also* assert
  when present; not a complete or intentional test surface.
- **`data-testid` is an explicit, test-only contract.** Its one job is "a test
  depends on this control." It signals intent to the next person editing the
  template ("keep this hook"), and it's the widely-understood convention. Adding
  it is additive and never changes rendered appearance.

**Naming:** `data-testid="<surface>-<control>"`, kebab-case. The surface prefix
keeps ids unique across the shared chrome (`dock-approve`, `review-bulk-approve`,
`nav-signin`). Page-level *state* (not a control) uses a `data-<flag>` attribute
on `<body>` (e.g. `data-has-dock`), mirroring the existing `data-page` hook.

### 2.2 `tests/_semantic.py` — the helper

A small, dependency-light module (BeautifulSoup over the stdlib `html.parser`
backend — bs4 is already a declared core dep) that parses real elements, not
substrings:

```python
from tests._semantic import assert_has_control, assert_no_control, scope, assert_body_flag

assert_has_control(html, "dock-create", tag="a", href=url_for("make_page"))
assert_has_control(html, "dock-approve", role="button")       # native <button> role
assert_has_control(html, "dock-count", text="4", attrs={"aria-hidden": "true"})
assert_no_control(html, "action-dock")                        # control must be absent
assert_body_flag(html, "has-dock", present=True)              # page-level state

dock = scope(html, "action-dock")                             # parse-accurate slice
assert_has_control(dock, "dock-approve", role="button")       # …then scope into it
```

Full API (all accept a raw HTML string *or* an already-parsed tree, so scoping
composes): `assert_has_control` (with optional `tag` / `role` / `name` /
`name_contains` / `href` / `text` / `text_contains` / `enabled` / `count` /
`attrs`), `assert_no_control`, `assert_control_count`, `get_control`, `scope`,
`assert_body_flag`, `get_body`, plus `accessible_name` / `control_role`. The
helper is itself unit-tested in `tests/test_semantic_helper.py`.

### 2.3 The non-negotiable rule: do not weaken

The migration **swaps the hook, never lowers the bar**. `assert 'class="x"' in
html` becomes an assertion that the *control* exists **with its identity** — its
tag, role, label, link target — which is strictly *more* precise than a class
substring. Concretely:

- "the Create link exists" → `assert_has_control(dock, "dock-create", tag="a",
  href=url_for("make_page"))` — verifies it's a link *and* points where the URL
  contract says. Stronger than `'href="/make"' in dock`.
- "the count chip shows 4" → `assert_has_control(body, "dock-count", text="4")` —
  parse-accurate, replacing a brittle `re.search(r'data-mh-dock-count[^>]*>(\d+)')`.

An assert may only be **dropped** (not migrated) when it verifies *no behaviour or
content* — a purely decorative class with no user-facing consequence and no
separate coverage lost (e.g. asserting a cosmetic `mh-tabs__ind` indicator span
exists, when a sibling test already proves the tabs switch). Every drop is called
out in its PR with why nothing is lost. When in doubt, migrate, don't drop.

---

## 3. What a slice looks like

Slices are **one route (template) at a time**, because testids are added per
template and the breakage surface is naturally the tests hitting that route:

1. **Add testids** to the route's template in `web.py` — additive only; keep
   existing classes and `data-mh-*` hooks (CSS/JS still need them).
2. **Migrate that route's test files** onto the helper (bucket-1 asserts only);
   leave bucket-2/3/4a asserts in those files untouched.
3. **Drop** the incidental decorative asserts, each noted in the PR.
4. **Dead-code sweep** the touched test files (orphaned string-slice helpers like
   the dock's old `_real_body_tag`, now-unused `re`/`import`s).
5. **Verify**: the migrated files pass, and the full suite stays green (the
   template edit is additive, so nothing else should move).

### Definition of done, per slice

- [ ] Every bucket-1 assert in the slice's files goes through `tests/_semantic.py`
      or is explicitly dropped-with-reason.
- [ ] No test is weakened — property checks (`tag`/`role`/`href`/`text`) preserve
      or tighten what was verified.
- [ ] Template edits are additive (no class/attribute removals); appearance
      unchanged; page still renders.
- [ ] `python -m pytest tests/ -q` shows no *new* failures.
- [ ] Touched files are swept of dead helpers/imports; PR notes each drop.

---

## 4. Slice ordering (the work-list)

Ordered to (a) prove the pattern on self-contained pages first, then (b) harden
the surfaces the `web.py` decomposition (#15) extracts *first* — so those tests
are refactor-robust before the blueprints move — then (c) mop up the marketing
pages that carry the largest raw counts.

| # | Slice (route) | Representative test files | ~B1 | Notes |
|---|---|---|---:|---|
| **0** | **`/review` mobile dock** ✅ | `test_mobile_action_dock.py` | 23 | **This PR — the POC.** |
| 1 | `/help`, `/pricing` | `test_help_page.py`, `test_pricing_ui120.py` | ~34 | Small, self-contained; second pattern proof. |
| 2 | `/review/<run>` core | `test_ui_2_4_clientside_tabs.py`, `test_review_body_content.py`, `test_usability_b4_slim_review_rows.py`, `test_ui19_bulk_actions.py`, `test_ui2_athlete_tooltips.py`, `test_usability_j3_review_pagination.py`, `test_u7_focus_facts.py` | ~120 | **#15 blueprint target (`api/runs`).** High leverage. |
| 3 | `/media-library`, `/make` | `test_ui_1_27_drag_gallery.py`, `test_hover_preview.py`, `test_content_intro.py`, `test_ui_2_5_cta_motion.py` | ~50 | **#15 blueprint targets (`media-library`, create).** |
| 4 | `/about` | `test_ui_1_29_chapter_nav.py`, `test_u5_scroll_reveal.py`, `test_u8_pipeline_diagram.py` | ~85 | Chapter-nav + scroll-reveal cluster. |
| 5 | `/` (landing) | `test_u10_hero_demo.py`, `test_ui_1_6_charts.py`, `test_ui_1_22_faq_accordion.py`, `test_ui_1_28_shortcuts_overlay.py`, `test_u9_hero_word_cycle.py`, `test_ui_2_7_caption_type_on.py`, `test_u12_odometer_stats.py`, `test_signed_in_logo_backdrop.py` | ~200 | Largest raw count; many files, one template. Sub-slice by test file. |
| 6 | `/pack`, `/season`, `/developer/api`, chrome/logo | `test_usability_b2_export_collapse.py`, `test_season_timeline.py`, `test_api_docs_page.py`*, `test_logo_chip_chrome.py` | ~55 | Tail. *api-docs = route-side asserts only; its highlighter unit asserts (4a) stay. |
| 7 | Bucket-4b + source-scrape cleanup | `test_u3_explainability.py`, `test_card_reactions.py`, `test_sprint_hook_mono_mode.py`, `test_photo_tint_hook.py`, + §6 source-scrape files | ~120 | See §6. |

Each row is one PR (slice 5 is several — sub-slice by file). Keep PRs ≲1k lines
per the review's #1 velocity guidance.

---

## 5. Coordination with #130 (shared fixtures) — ordering

**#129 and #130 are orthogonal in mechanism but overlap in file set.**

- **#130** changes *how a test gets its client* — it hoists the copy-pasted
  `setenv(DATA_DIR) + importlib.reload(web) + create_app()` boilerplate (305
  files reload the monolith today) into canonical `app`/`client` fixtures +
  an autouse `_isolate_data_dir` in `conftest.py`.
- **#129** changes *what a test asserts on* — the right-hand side of the assert
  and the template attributes. It does **not** touch how the client is built.

They edit **different lines** of the same files, so they don't logically
conflict — but two large sweeps touching ~185 overlapping files *will* collide in
git if run blind. Recommended sequencing:

1. **#129 infrastructure first (this PR).** The helper + testid convention + the
   POC have **zero** dependency on fixtures — the helper operates on an HTML
   string however it was obtained. Landing it now unblocks nothing else and
   proves the pattern. ✅
2. **#130 next.** Hoist the canonical `client`/`app` fixtures into `conftest.py`.
   This is smaller, purely mechanical, and *foundational*: every future test
   (including #129-migrated ones) should build its client the canonical way.
   Landing it before the #129 bulk means the per-route slices adopt the shared
   fixture in the *same* edit — one touch per file, not two.
3. **#129 bulk slices after #130.** Migrate route-by-route (§4) on top of the
   stabilised fixtures, avoiding a rebase of 185 files against a moving
   `conftest.py`.

**Rule while both are in flight:** whoever touches a file first wins; the other
rebases. When a slice opens a file for either reason, do **both** migrations in
that one touch (adopt the shared fixture *and* migrate the asserts) so no file is
churned twice. The POC deliberately leaves this file's per-test `env` fixture
as-is — that's #130's job — to keep the two concerns cleanly separable and show
they compose.

**Bottom line: land #129-infra (this PR) → #130 → #129 bulk.**

---

## 6. Open decisions (buckets 4b and 5)

- **Bucket 4b (~100 asserts)** — tests calling an internal `_render_*` fragment
  builder directly and scraping its `mh-*` output. These *do* break on a template
  refactor, but they're reached by a function call, not a route, so a per-route
  testid pass won't auto-cover them. **Recommendation: migrate opportunistically**
  — when a slice touches the same surface, add testids to the fragment builder and
  migrate. Slice 7 mops up the rest. (These fragments are template markup, so the
  same "don't weaken" rule applies.)
- **Bucket 5 (~18 asserts)** — tests that read `web.py` as *source text* and
  assert an f-string literal appears in it. These are the most brittle of all (a
  literal string match against source). **Recommendation: convert each to a
  route-render assert** (fetch the page, assert the control) where a route exists,
  or **drop** where the check is redundant with a rendered-output test. Never add
  new source-text scrapes.

---

## 7. Governance

This is ordinary test-infrastructure work — **not** a Council-level decision (it's
reversible, touches no deterministic-engine boundary, and ships no external
surface). No ADR is required. The one durable output worth recording is the
**`data-testid` convention itself** (§2.1) and the **do-not-weaken rule** (§2.3),
captured here and pointed to from `tests/README.md`. A future optional guardrail —
a lint that flags *new* `assert 'class="mh-..."' in html` and forbids removing a
`data-testid` still referenced by a test — would keep the brittleness from
creeping back; it is out of scope for the first slices.

---

## 8. This PR (the proof-of-concept)

- **Helper:** `tests/_semantic.py` (+ `tests/test_semantic_helper.py`, 23 tests).
- **Template:** `data-testid` on the mobile action dock's controls
  (`action-dock`, `dock-create`, `dock-library`, `dock-approve`, `dock-label`,
  `dock-count`) and a `data-has-dock` state flag on `<body>` — all additive, no
  class or behaviour removed.
- **Tests migrated:** `tests/test_mobile_action_dock.py` — every bucket-1
  template-scrape assert now goes through the helper; the browser probe's
  dock selectors use the testids too; the orphaned `_real_body_tag` string-slicer
  is removed. The `TestDockCss` block (bucket-2 stylesheet contract) is
  **unchanged** — proving the discipline of migrating only what's brittle.
- **Result:** 27/27 dock tests pass; full suite green.
