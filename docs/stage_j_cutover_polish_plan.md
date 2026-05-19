# Stage J — Cutover + Polish: Plan

> Phase 1.6 Stage J of [`ROADMAP.md`](ROADMAP.md). The final
> stage. Stages A–I built and tested the adaptive theming
> engine. Stage J makes the cutover safely-reversible and
> ensures every render path — including the unconfigured
> first-run experience — flows through the new pipeline.

## 1. Context

By the end of Stage I, the adaptive theming engine has nine
shipped stages with 800+ tests covering structural integrity,
algorithmic correctness, on-disk persistence, the full audit
trail, golden-master regressions for 30 representative seeds,
and a real-browser end-to-end. Every piece works.

But the codebase still carries a soft seam: the inline
`<style id="mh-theme-seed">` override only fires for users with
an *active organisation*. Visitors landing on `/status`,
`/sign-in`, or `/healthz/usage` without a pinned profile see the
*static* defaults from `theme-base.css` — the Stage A
"Podium After Dark" lane yellow. The engine isn't running on
their pages. They're effectively running pre-Stage-D code.

Three closure pieces remain:

1. **A safety lever.** Adaptive theming is the new normal — but
   any production deployment needs a way to roll back without a
   code revert if something breaks. A feature flag controls the
   per-request seed injection; setting `MEDIAHUB_ADAPTIVE_THEME=0`
   reverts the rendered HTML to the Stage A cascade exactly.
2. **The default experience.** When MediaHub is deployed but no
   club has finalised their brand kit yet, the unconfigured
   pages should *also* show the pipeline at work — running the
   `BrandKit.generic_default()` seeds (`#0E2A47` navy +
   `#C9A227` gold) through the same Stage B derivation that
   real clubs use. This proves the pipeline runs end-to-end on
   every page render, not just for the configured-profile case.
3. **The reference doc.** Phase 1.6 produced 9 detailed
   per-stage plans. Stage J distils them into a single
   `docs/THEMING.md` that an operator, a contributor, or a
   future-Claude can read to understand the whole engine —
   role-token table, cascade order, override pattern, feature
   flag, and the academic citations that anchor every algorithm.

After Stage J, the Adaptive Theming Engine is *complete*.

## 2. The user-visible promise

Three observable outcomes:

**Outcome 1: Reversibility.** An operator who suspects the
adaptive theming is causing trouble (a rendering bug, a contrast
regression spotted in the wild, a third-party screen-reader
incompatibility) can disable the per-request seed injection by
setting `MEDIAHUB_ADAPTIVE_THEME=0` in their environment and
restarting the app. The rendered HTML reverts to the Stage A
cascade — every page renders with the static lane-yellow
defaults, no per-org override, no derived palette consumed at
the CSS layer. The reverse — re-enabling — is one env var flip
plus a restart.

**Outcome 2: Universal pipeline coverage.** Every page rendered
by the Flask app, even before any organisation has been
configured, now carries an inline `<style id="mh-theme-seed">`
block — either the active profile's seed (Stage D-G) or the
generic-default-derived theme (Stage J). The Playwright
end-to-end test from Stage I — currently asserting that
`--mh-brand-seed` resolves on the active-profile page — extends
to assert the same on the unconfigured `/status` page.

**Outcome 3: Documented engine.** A developer who lands on
`docs/THEMING.md` sees a single 3,000-word reference: how the
seven seed variables map to the ~25 MD3 role tokens, how the
cascade resolves at runtime, how to override a single role, how
to roll back, and which academic papers ground the algorithm
choices. No more needing to read nine separate `stage_*.md`
plans.

## 3. Architecture overview

Four concrete changes:

| Change | Where | What |
|---|---|---|
| Feature flag | New `_adaptive_theme_enabled()` helper in `web.py` | Returns False when `MEDIAHUB_ADAPTIVE_THEME=0`; True otherwise |
| Default-theme cache | New `_default_theme_json()` helper in `web.py` | Lazy `lru_cache`d derivation of `BrandKit.generic_default()` |
| Seed-style fallthrough | Modify `_theme_seed_style_block()` | If no active profile, fall back to default theme; if flag disabled, return empty |
| Reference doc | New `docs/THEMING.md` | Comprehensive operator + contributor reference |

The data flow becomes a clean three-tier fallback:

```
   Request lands on a page
              │
              ▼
   _theme_seed_style_block()
              │
              ├─ flag disabled?         → return ""  (rollback to Stage A cascade)
              ├─ active profile pinned? → use profile.brand_kit.derived_palette
              └─ neither                → use _default_theme_json() (J2)
              ▼
   <style id="mh-theme-seed">:root { --mh-brand-seed: <hex>; }</style>
```

This is the cleanest possible cutover: every render path goes
through ONE function with explicit tiered fallback.

## 4. J1 — MEDIAHUB_ADAPTIVE_THEME feature flag

### What the flag controls

Setting `MEDIAHUB_ADAPTIVE_THEME=0` (or `false`/`off`/`no`) at
deploy time causes `_theme_seed_style_block()` to return the
empty string for *every* request, regardless of whether an
active profile is pinned. The rendered HTML then carries no
override, and the static `theme-base.css` defaults win.

The default (flag unset or set to anything other than the off
values) is `enabled = True`. The cutover is the new normal; the
flag exists for rollback.

### Pre-cutover behaviour

When `MEDIAHUB_ADAPTIVE_THEME=0`:
- No inline `<style id="mh-theme-seed">` block in any rendered page
- Rendered cascade matches Stage A's pre-Stage-D state exactly
- The static CSS still loads (Stages B-I derived shades still
  resolve in modern browsers) but the seed cannot be overridden
  per request
- The Stage H audit panel and Stage H3 callout STILL render —
  they're independent of the cascade override and surface what
  the engine *would* do if the flag were on

### Post-cutover behaviour

When the flag is enabled (the default):
- Active-profile requests inject `--mh-brand-seed: <profile_seed>` (Stages D-G)
- No-profile requests inject `--mh-brand-seed: #0E2A47` (J2 — the
  generic-default-derived theme)
- Stages H1-H3 continue to work — audit panel + callout reflect
  the live derivation

### Rollback semantics

Critical: setting the flag never *loses data*. The on-disk
theme JSON at `DATA_DIR/themes/<pid>.json` (Stage G) stays
populated — `ensure_derived_palette()` writes there regardless
of the flag. Stage H's audit panel reads from the same JSON.

What the flag controls is purely the *visible* cascade —
whether the inline `<style>` block injects an override. Toggling
the flag is reversible mid-deployment; nothing needs to be
recomputed.

## 5. J2 — Generic-default pre-derivation

### Where the default theme lives

A module-level `lru_cache`d helper:

```python
@functools.lru_cache(maxsize=1)
def _default_theme_json() -> Optional[dict]:
    """Return the DTCG theme JSON derived from BrandKit.
    generic_default()'s seeds.

    Lazy-derived on first call (~50ms), cached for the life of the
    process. Returns None if the derivation itself errors (in which
    case the cascade falls back to the static Stage A defaults).
    """
    try:
        from mediahub.brand.kit import BrandKit
        kit = BrandKit.generic_default()
        return kit.ensure_derived_palette()
    except Exception:
        return None
```

The `lru_cache` decorator ensures the derivation runs exactly
once per process. On a typical web worker that's a 50ms cost on
first request, then free for every subsequent request.

### Why the disk side-effect is fine here

`ensure_derived_palette()` writes to `DATA_DIR/themes/default.
json` (Stage G's hook). That's intentional — it makes the
default theme available to the motion / email / static
renderers exactly the same way real profile themes are. The
"default" profile_id is a stable slug (`a-z0-9-_`) so the path-
validation regex in `theme_store.py` accepts it.

The cached file means:
- Repeat process startups don't re-derive (cached on disk)
- Motion renders triggered without an active profile pick up
  the default theme via `read_theme("default")` ← already
  works through Stage G's `palette_for_motion()` etc.

### Why this is "the unconfigured first-run benefits"

Before Stage J, a fresh MediaHub deployment with no clubs set
up rendered every page using the Stage A static defaults. The
motion renderer fell back to `#0A2540` (Stage G's
`_FALLBACK_PRIMARY`). The newsletter renderer fell back to
`#0A2540`. There was no theme JSON on disk for any consumer to
read, because no profile had been finalised.

After Stage J, the moment Flask boots and the first request
lands, `_default_theme_json()` fires. The generic-default theme
gets derived AND persisted to `DATA_DIR/themes/default.json`.
Every consumer (web cascade, motion, newsletter, static) now
has a theme to read. The pipeline is *active*, not dormant.

A real club that subsequently finalises their kit gets their
own theme file. The default keeps working for unconfigured
visitors and unattached batch renders.

## 6. J3 — `docs/THEMING.md`

The reference doc, structured for three reader types:

1. **Operators** who deploy MediaHub and need to know what the
   theming system does, how to roll back, and what env vars
   exist.
2. **Contributors** who want to add a new role token, change a
   threshold, or understand the cascade.
3. **Future-Claude** who needs to recover full context about
   the engine in a single read.

### Document structure

```
# MediaHub Theming Reference

## 1. What is the Adaptive Theming Engine?
[Two-paragraph user-visible summary.]

## 2. Architecture at a glance
[ASCII diagram of the data flow, from seed input to four
content surfaces (web/motion/email/static).]

## 3. The role-token vocabulary
[Table: each tier-2 role token, its purpose, the CSS variable
name, and which static file declares it.]

## 4. The seven seed variables
[Table: --mh-brand-seed, --mh-tertiary-seed, --mh-neutral-seed,
and the four status seeds — their purpose and default values.]

## 5. The cascade order
[Documented sequence: theme-base → theme-fallback → theme-derive
→ theme-cascade → <style id="mh-theme-seed"> override.]

## 6. The four consumer surfaces
[Documented mapping: web/motion/email/static and the
palette_for_* helpers from theme_store.]

## 7. Override patterns
[Three patterns: per-org via brand-kit, per-deployment via
theme-base.css edit, per-element via inline style.]

## 8. Feature flags
[MEDIAHUB_ADAPTIVE_THEME, MEDIAHUB_SKIP_BROWSER_TESTS.]

## 9. The audit + repair pipeline
[High-level summary of Stages B (derive), H (audit), and the
repair loop.]

## 10. Adding a new role token
[Walkthrough.]

## 11. Adding a new seed
[Walkthrough for tests/theming/seeds_catalogue.py.]

## 12. Academic citations
[Cohen-Or, Sharma, Somers, Machado, Ottosson, Material 3, etc.]
```

### Citations inline

Each algorithmic claim links to its primary source. Examples:

> "The repair loop perturbs the L and C of the OKLCH point
> first; hue is the last channel to move
> [(Lalitha A R, arXiv 2512.05067)](https://arxiv.org/abs/2512.05067).
> This matches human tolerance for luminance shifts being
> substantially higher than tolerance for hue shifts."

The citation style is footnote-free Markdown links so the doc
reads cleanly on GitHub without a separate citations section.

## 7. Backwards compatibility

Stage J is purely additive:

- Adding a feature flag with default-enabled behaviour means a
  deployment with no env var set sees the same behaviour as a
  deployment with `MEDIAHUB_ADAPTIVE_THEME=1`.
- The default-theme helper is wholly new — no existing code
  calls it. The seed-style helper changes only the fallback
  branch (when no active profile), so active-profile
  rendering is byte-identical to Stage E-H.
- The new docs file doesn't touch any code.

The one thing that *visibly* changes: an unconfigured fresh
deployment now sees navy chrome on `/status` instead of lane
yellow. This is the documented J2 behaviour.

## 8. Test strategy

Three new test files:

### `tests/test_adaptive_theme_flag.py`

The J1 feature flag:
- Flag unset → adaptive enabled
- `MEDIAHUB_ADAPTIVE_THEME=0` → adaptive disabled → seed block empty
- `MEDIAHUB_ADAPTIVE_THEME=1` → adaptive enabled
- `MEDIAHUB_ADAPTIVE_THEME=false`, `off`, `no` → disabled
- Stage H audit panel still renders even when flag is disabled
  (audit lives outside the cascade)
- Stage G theme-store still writes on `ensure_derived_palette()`
  regardless of flag

### `tests/test_default_theme.py`

The J2 generic-default cache:
- `_default_theme_json()` returns a populated dict for
  `BrandKit.generic_default()`'s seeds
- The seed_hex matches `#0E2A47` (navy)
- Subsequent calls return the cached value (no re-derivation)
- A fresh process can read `DATA_DIR/themes/default.json` after
  the first call
- The motion/email/static helpers pick up the default theme
  when given a profile_id of "default"
- An unconfigured request to `/status` carries the inline
  `<style id="mh-theme-seed">` with the generic-default seed

### `tests/test_theming_md.py`

The J3 documentation file:
- `docs/THEMING.md` exists
- File contains the documented section headers
- The role-token table covers every tier-2 role from `theme-base.css`
- The seven seed variables are all named
- The four content surfaces (web/motion/email/static) are all
  documented with their scheme mappings
- The `MEDIAHUB_ADAPTIVE_THEME` flag is documented
- At least 6 academic citations appear (Cohen-Or, Sharma, Somers,
  Machado, Ottosson, Material 3)
- Word count ≥ 1,500 (substantial reference doc)

## 9. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| Flag-disabled rendering breaks something Stage E expected | Low | Disable just returns "" from one helper; cascade falls through to static defaults — already tested |
| Default theme derivation fails on cold start | Low | Helper returns None on exception; falls back to static defaults |
| Default theme file pollutes existing `DATA_DIR/themes/` | Low | Uses profile_id "default" — a stable slug; idempotent writes |
| `lru_cache` retains stale data across config changes | Low | Cache key has size 1; full process restart invalidates |
| New default visual identity breaks user expectations | Medium | Documented in roadmap; flag rollback gives instant revert |
| The doc gets out of sync with the code | Medium | Test asserts each documented role token actually exists in the CSS; drift between code + doc fails CI |
| Documentation length too short to be useful | Low | Word-count test asserts ≥ 1,500 |
| Old Playwright test breaks because default-theme seed override changed surface | Medium | Update Playwright test to assert override IS present on unconfigured page (the new expectation) |

## 10. Audit plan (10 subtasks)

1. `_adaptive_theme_enabled()` returns True when env var unset.
2. `_adaptive_theme_enabled()` returns False when env var is "0".
3. `_default_theme_json()` returns a dict for `BrandKit.generic_default()`.
4. The default theme's `seed_hex` is `#0E2A47`.
5. `_theme_seed_style_block()` returns "" when flag is disabled.
6. `_theme_seed_style_block()` returns the default-theme override
   when no active profile is pinned.
7. `docs/THEMING.md` exists with the documented section headers.
8. Every tier-2 role token from theme-base.css is documented.
9. The Stage I 67 snapshot tests still pass.
10. The Stage F 40 logo / mark theming tests still pass.

## 11. Verify plan (10 subtasks)

1. App boots; `/status` returns 200.
2. Setting `MEDIAHUB_ADAPTIVE_THEME=0` and rendering `/status`
   produces HTML with NO `<style id="mh-theme-seed">` block.
3. Unsetting the flag and re-rendering `/status` produces HTML
   WITH the override block.
4. The override block on unconfigured `/status` declares
   `--mh-brand-seed: #0E2A47` (the generic-default).
5. The override block on a profile-pinned page declares
   the profile's seed (Stage E behaviour preserved).
6. After app boot, `DATA_DIR/themes/default.json` exists and
   contains the generic-default theme.
7. The new docs file exists and includes at least 6 academic citations.
8. `tests/test_browser_cascade.py` still passes (the rendered
   cascade still resolves cleanly in chromium-1194).
9. Stage I snapshot tests still pass (no algorithm drift).
10. Full pytest suite passes (Stage A-J + new J tests), zero
    new structural failures.

## 12. Out of scope (deferred entirely)

These items lived in earlier stage plans as "future" and are
deliberately NOT in scope for Stage J:

- Multi-tenant subdomain routing for per-tenant theme files
  (Phase 3 work — the operator-managed single-org model still
  applies)
- Switching from inline `<style>` to `<link rel="stylesheet">`
  for the seed override (would require browser-cache-aware
  rotation; out of proportion for Stage J)
- Pre-warming the theme store at deploy time for *every*
  existing profile (an admin migration script — not needed
  unless an operator asks for it)
- Operator UI for managing the flag (env vars are the
  operator interface; no UI proposed)
- Per-role overrides via an operator-edited
  `theme-override.css` (mentioned in Stage A planning;
  belongs to a future polish phase post-launch)

## 13. Phase 1.6 completion summary

After Stage J merges, the Adaptive Theming Engine spans:

- 10 shipped stages
- ~1,800 tests across structural, snapshot, browser, and
  integration layers
- 5 colour-science modules (`palette`, `roles`, `contrast`,
  `cvd`, `quality` + `harmony`, `repair`, `theme_store`)
- 4 static CSS files (`theme-base`, `theme-fallback`,
  `theme-derive`, `theme-cascade`)
- 30 golden-master snapshots covering a deliberate
  cross-section of the colour space
- 1 explainability panel + 1 repair callout per page render
- 1 reference doc (`docs/THEMING.md`)
- 1 reversible feature flag for production safety

The headline Phase 1.6 promise — "every club's colours feel
like their own, across every surface, without engineering
intervention" — is now production-ready. Stage J was the final
polish that makes the system *safe to deploy*. The next phase
of MediaHub work can begin without any open theming threads.

## 14. The shape of a Phase 1.6 retrospective

Worth keeping in mind for the eventual retrospective doc
(post-launch): which stages should be cited as engineering
patterns to repeat, and which were the right scope but the
wrong sequence.

Likely retrospective findings (predictions, not commitments):
- Stage A's "three-tier tokens with legacy aliases preserved"
  pattern enabled every subsequent stage to land additively.
  This pattern is reusable for any future design-system
  refactor.
- Stage B's "constraint-satisfaction repair loop with curated
  fallback" is over-engineered for swimming clubs whose seeds
  rarely conflict. But it's exactly right for the wider sport-
  agnostic future Phase 1.6 was building toward.
- Stage I's 30-seed catalogue is the workhorse — every later
  algorithm change pays for itself by either passing the
  snapshots or surfacing a deliberate diff.
- Stage J's feature flag is the kind of safety lever every
  large refactor should ship with; the discipline of "don't
  ship a cutover without a rollback path" generalises beyond
  theming.

That's the final entry in Phase 1.6's planning record. The next
chapter is the pilot deployment.
