# Stage E — "Looks right" Cascade: Thesis Plan

> Phase 1.6 Stage E of [`ROADMAP.md`](ROADMAP.md). The user-visible
> moment of the Adaptive Theming Engine: when a club's owner clicks
> *"Looks right — start creating"* on `/organisation/setup`, the
> derived brand palette gets persisted, the page navigates to
> `/make`, and the cascade animates smoothly to the new theme.

## 1. Context

Stage A introduced the three-tier DTCG token vocabulary
(`THEME_TOKENS_CSS`). Stage B built the colour-science package
(`mediahub.theming`) that derives a full HCT-based palette from a
seed and caches it on `ClubProfile.brand_kit.derived_palette`.
Stage C extracted the static CSS into three on-disk files
(`theme-base.css`, `theme-fallback.css`, `theme-derive.css`) and
introduced the runtime derivation path where ~33 shades are
computed from seven seed variables via `oklch(from var(--mh-…-seed)
…)` and `color-mix(in oklch, …)` expressions.

Stage E is the user-visible payoff. The infrastructure of Stages
A–C produces a complete adaptive theme; Stage E animates the
transition from one theme to the next so the user experiences the
new identity rather than just sees it appear. The roadmap
sub-tasks:

- **E1**: Wire the "Looks right" button to derive + persist the
  palette, then trigger a View-Transition-driven navigation.
- **E2**: `@view-transition { navigation: auto; }` so cross-document
  navigations crossfade by default.
- **E3**: `:root { transition: --mh-brand-seed 600ms … }` so the
  whole derived palette interpolates in lockstep when the seed
  changes.
- **E4**: `prefers-reduced-motion: reduce` → instant swap, no
  animation, full accessibility compliance.

Stage D (`before_request` middleware loading `g.theme` into the
template context, full `<link rel="stylesheet">` switch) is
explicitly *not* the focus of this work, but Stage E requires the
**minimum viable Stage D piece**: the rendered HTML must carry an
inline `<style id="mh-theme-seed">` block reflecting the active
profile's seed, so when the user navigates to a new page the seed
override is present. Without this, every page would show the
static default seed and there'd be no animation target. Stage E
ships this minimum wiring as the foundation for the proper Stage D
middleware refactor later.

## 2. The user-visible promise

The brief from Phase 1.6's preamble is "the whole website's
colour scheme switches beautifully every time, without fail". For
Stage E this becomes a specific gesture:

1. User completes brand-DNA capture on `/organisation/setup`.
2. Engine has computed `derived_palette` (Stage B); the page now
   shows the user "What MediaHub learned about <club name>" with
   the captured palette swatch and reasoning.
3. User scans the captured context and clicks **"Looks right —
   start creating"**.
4. The click triggers:
   - Server-side: `BrandKit.ensure_derived_palette()` runs
     (idempotent — usually no-op since palette was computed
     earlier); profile saved; new seed hex returned to the client.
   - Client-side: the `@view-transition { navigation: auto; }`
     rule in the static CSS tells the browser to crossfade the
     navigation. The user sees the page morph: panels, buttons,
     focus rings, hover tints all shift in lockstep to the new
     brand colour.
   - On `/make`, the inline `<style id="mh-theme-seed">` block
     declares the new seed; everything Stage C derives picks up
     the change automatically.
5. For users with `prefers-reduced-motion: reduce`, the
   crossfade is bypassed — the new page renders instantly with
   the new theme, no animation.

This is the moment that distinguishes MediaHub from a generic
SaaS chrome. The intelligence layer captures the brand; the
theming engine renders it; the cascade animation MAKES THE USER
FEEL IT.

## 3. Architecture overview

Five concrete changes:

| Change | Where | What |
|---|---|---|
| Cascade-animation CSS | New file `src/mediahub/web/static/theme/theme-cascade.css` | `@view-transition` rule, `:root` seed transition, reduced-motion override |
| Loader update | `src/mediahub/web/theme_tokens.py` | Concat the new file into `THEME_TOKENS_CSS` |
| Per-org seed style block | New helper in `web.py` | Returns `<style id="mh-theme-seed">` reflecting the active profile's derived palette |
| Layout injection | `_layout()` in `web.py` | Insert the seed style block after the assembled CSS |
| Finalise endpoint + button JS | `web.py` | `POST /api/organisation/finalise` persists the palette; button click hits it then navigates |

The cascade still flows through the existing
`THEME_TOKENS_CSS → BASE_CSS → RESPONSIVE_GUARDRAILS_CSS` order.
Stage E adds a new last layer: the per-request
`<style id="mh-theme-seed">` override that the seed picks up at
the `:root` cascade tier.

## 4. E1 — Button + finalise endpoint

### The button

Current state at `src/mediahub/web/web.py:11434`:

```python
'<a class="btn" href="{url_for("make_page")}">Looks right &mdash; start creating &rarr;</a>'
```

After Stage E:

```python
'<a class="btn" href="{url_for("make_page")}" data-mh-cascade="finalise">'
'Looks right &mdash; start creating &rarr;</a>'
```

The `data-mh-cascade` attribute is the JS-hook selector. The link
remains a real `<a href>` so:
- Graceful degradation: no JS → click navigates directly, no animation
- Right-click / open-in-new-tab still works
- Screen readers read it as a normal link
- Search engines never reach this page (auth-gated) so SEO is moot

### The finalise endpoint

New route:

```python
@app.route("/api/organisation/finalise", methods=["POST"])
def organisation_finalise():
    """Idempotent endpoint: ensure the active profile has a derived
    palette and persist any updates. Called by the 'Looks right'
    button click handler before triggering the View Transition.

    Returns 200 + JSON {seed_hex, was_repaired, polarity_changed}
    so the client can include a tiny pre-flight inline style if it
    wants to nudge the View Transition starting frame.
    """
    prof = _active_profile()
    if not prof:
        return jsonify({"error": "no active organisation"}), 400
    kit = prof.get_brand_kit()
    palette = kit.ensure_derived_palette()
    # Persist the cached palette back to the profile so subsequent
    # requests see it. ensure_derived_palette mutated kit in-place;
    # we need to write that mutation back to the profile dict and
    # save the profile.
    prof.brand_kit = kit.to_dict()
    save_profile(prof)
    return jsonify({
        "seed_hex": palette["seed_hex"],
        "was_repaired": palette.get("was_repaired", False),
    })
```

The endpoint is idempotent: calling it twice produces the same
result because `ensure_derived_palette()` is itself idempotent
(returns the cached dict unless `force=True`). This matters
because the JS might retry on transient network errors.

### The click handler

A small JS block added once to `_layout()`:

```javascript
(function(){
  function onClick(e){
    var link = e.target.closest('a[data-mh-cascade]');
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href) return;
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    var base = window._API_BASE || '';
    fetch(base + '/api/organisation/finalise', {
      method: 'POST',
      credentials: 'same-origin',
    }).catch(function(){
      // Network error — still navigate; the next page will lazily
      // ensure the palette via the BrandKit cache pattern.
    }).finally(function(){
      // Browsers with cross-doc View Transitions support pick up
      // the animation automatically from @view-transition. Others
      // navigate without animation. Either way, just navigate.
      window.location.assign(href);
    });
  }
  document.addEventListener('click', onClick);
})();
```

Crucially this handler:
1. Respects modifier keys (let the user open in a new tab).
2. Only handles primary mouse button (`e.button === 0`).
3. Posts to the finalise endpoint BEFORE navigating, so the new
   page has the derived palette persisted and ready.
4. Falls through to navigation if the POST fails — graceful
   degradation; the next-page render will lazily ensure the
   palette.
5. Doesn't try to handle the animation itself — that's the CSS's
   job via `@view-transition`.

The roadmap mentioned `document.startViewTransition(…)` for E1.
That's the *same-document* View Transitions API and doesn't help
across a navigation. The right primitive for cross-document
navigation is the `@view-transition` CSS rule, which the browser
applies automatically when navigation happens. The JS wraps the
finalise + navigate flow; the animation is declarative CSS.

## 5. E2 — `@view-transition { navigation: auto; }`

This single CSS rule tells supporting browsers (Chrome 126+,
Safari 18.2+, Firefox in progress) to crossfade between
same-origin navigations automatically. No JS required.

```css
@view-transition {
  navigation: auto;
}
```

Placed at the top of `theme-cascade.css`. Browsers that don't
understand it ignore the at-rule silently — fallback to instant
navigation, no animation, no error.

The crossfade snapshot captures the *entire viewport* by default,
which is what we want: the user clicks the button, the whole page
fades to the new theme. If we wanted a fancier choreography
(circle-wipe from the click origin, separate panel + button
crossfades) we'd add `view-transition-name` properties to
specific elements — that's a Stage F polish.

## 6. E3 — `:root { transition: --mh-brand-seed 600ms … }`

This is the "lockstep cascade" magic. Recall that Stage C made
every primitive a `oklch(from var(--mh-brand-seed) …)` expression.
The expressions re-evaluate every animation frame when the
underlying var changes.

If we put a `transition` on the seed:

```css
:root {
  transition:
    --mh-brand-seed 600ms cubic-bezier(0.2, 0.7, 0.2, 1),
    --mh-tertiary-seed 600ms cubic-bezier(0.2, 0.7, 0.2, 1);
}
```

then changing `--mh-brand-seed` from one value to another causes
the browser to interpolate between them over 600 ms. Because the
seed is `@property`-registered as `<color>` (Stage A invariant),
the interpolation uses OKLCH colour-space math by default — clean
perceptual crossfade, no muddy mid-tones.

Each interpolated frame of `--mh-brand-seed` triggers
re-evaluation of every `oklch(from var(--mh-brand-seed) …)`
expression. So 30+ derived primitives, the 25 tier-2 role tokens
that reference them, and every CSS rule that ends up resolving
to one of those tokens — all interpolate in lockstep. The user
sees the entire palette morph as one coherent motion.

The 600 ms duration matches:
- View Transitions API's default crossfade duration (so the
  in-page transition aligns with the cross-document one).
- The `cubic-bezier(0.2, 0.7, 0.2, 1)` curve — a snappy
  ease-out, hits 80% of the target by 350 ms, settles smoothly.
- Reduces motion-sickness risk vs longer transitions.

This rule sits in `theme-cascade.css` at the `:root` level so it
applies to every page. Same-document seed changes (e.g. a future
"switch organisation" dropdown that swaps the seed via JS) get
the same lockstep animation for free.

## 7. E4 — `prefers-reduced-motion: reduce`

WCAG 2.3.3 (and the EAA in force since June 2025) require
respecting the user's motion preference. The Stage A
`responsive_guardrails.py` already includes a generic
`@media (prefers-reduced-motion: reduce) { *, *::before, *::after
{ transition-duration: 0.01ms !important; … } }` block that would
catch our `:root` transition automatically.

But the View Transitions API has *its own* animation pseudo-
elements (`::view-transition-old(root)`, `::view-transition-new(root)`,
`::view-transition-group(*)`) that the global rule doesn't reach.
Stage E adds explicit overrides:

```css
@media (prefers-reduced-motion: reduce) {
  :root {
    transition: none !important;
  }
  ::view-transition-group(*),
  ::view-transition-old(root),
  ::view-transition-new(root) {
    animation: none !important;
  }
}
```

Belt + braces: the `:root` transition override doubles up the
existing guardrails rule (intentional — explicit at the
declaration site makes the rule reviewable in isolation), and the
View Transitions pseudo-element rules cover the cross-document
case the global rule misses.

## 8. Stage D minimum — per-org seed style block

For the cascade to animate, the *target* page must declare the
new seed value somewhere the cascade picks up. Static
`theme-base.css` ships the lane-yellow default; the per-org
override goes in an inline `<style id="mh-theme-seed">` block
emitted by the server on every rendered page.

Implementation:

```python
def _theme_seed_style() -> str:
    """Return the inline <style> block carrying the active profile's
    seed override, or an empty string if no active profile.

    Sits last in the cascade (after the static theme CSS) so it
    wins. The id="mh-theme-seed" anchor makes it easy for
    devtools / future JS to find and rewrite.
    """
    try:
        prof = _active_profile()
    except Exception:
        return ""
    if not prof:
        return ""
    try:
        kit = prof.get_brand_kit()
        palette = kit.ensure_derived_palette()
    except Exception:
        return ""
    seed_hex = palette.get("seed_hex")
    if not seed_hex:
        return ""
    # Only override seeds that actually move per-org. Status
    # anchors stay locked (per Stage B's cross-cultural-semantics
    # rule); tertiary may or may not be derived — for Stage E we
    # ship just --mh-brand-seed and let tertiary follow Stage C's
    # static default.
    return (
        f'<style id="mh-theme-seed">'
        f':root {{ --mh-brand-seed: {seed_hex}; }}'
        f'</style>'
    )
```

Injected in `_layout()` right after the assembled CSS `<style>`
block, so the cascade order is:

```
<style>theme-base + theme-fallback + theme-derive + theme-cascade + BASE_CSS + guardrails</style>
<style id="mh-theme-seed">:root { --mh-brand-seed: <org's seed>; }</style>
```

The override is per-request, ~80 bytes of HTML, and is
recomputed each render — fine for the small-org-per-deployment
model. Full Stage D will introduce `before_request` caching once
multi-tenant subdomain routing arrives.

## 9. Pixel-parity strategy

For users *without* an active org, Stage E is invisible — the
seed override block is empty, the cascade animation rule
matches "seed didn't change" (no-op), pixels are identical to
Stage C.

For users *with* an active org whose `derived_palette` was
already computed (the common case after Stage B has run on
their profile), the rendered HTML now includes the seed
override. If the override resolves to the same hex as the
static default (`#D4FF3A`), pixels are identical to Stage C.
If it differs (e.g. a club whose brand-DNA capture produced
a navy primary), the rendered pixels reflect the override —
which is the *new feature* of Stage E, the user-visible
adaptive theming.

The View Transitions animation only triggers on actual
navigation between same-origin pages, and only in browsers
that support it. For everyone else, navigation is instant
and the new page just appears with its theme. No regression
either way.

## 10. Test strategy

Three new test files:

### `tests/test_theme_cascade.py`

The CSS contract:
- `theme-cascade.css` exists on disk.
- The file is concatenated into `THEME_TOKENS_CSS` by the
  loader.
- Contains `@view-transition { navigation: auto; }`.
- Contains `:root { transition: --mh-brand-seed …; }`.
- The transition duration parses to `600ms`.
- Contains the cubic-bezier curve.
- Contains a `@media (prefers-reduced-motion: reduce)` block.
- The reduced-motion block overrides both `:root` transition
  *and* the View Transitions pseudo-elements.

### `tests/test_organisation_finalise.py`

The endpoint contract:
- `POST /api/organisation/finalise` exists.
- Without an active org: returns 400.
- With an active org: returns 200 + JSON
  `{seed_hex, was_repaired}`.
- The active profile's `derived_palette` is populated after the
  call (persistence works).
- Calling twice is idempotent — same response.
- Network safety: GET against the endpoint returns 405 or
  similar (don't accept GET, this is a state change).

### `tests/test_looks_right_button.py`

The button contract:
- Rendering `/organisation/setup` after a profile is loaded
  emits the button.
- The button carries `data-mh-cascade="finalise"`.
- The button still has its original `href` for graceful
  degradation.
- The page also embeds the JS handler.
- The `data-mh-cascade` selector is unique enough not to
  match unrelated `<a>` elements.

Plus extension of `tests/test_responsive_meta.py` so the
`@view-transition` rule is included in the rendered-HTML check
list.

## 11. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| Finalise endpoint fails to persist | Medium | Wrap save in try; return 500; client-side falls back to instant navigation. Tests verify both success + failure paths. |
| Older browsers without `@view-transition` see weird artefacts | Low | The at-rule is silently ignored; navigation is instant. Tested via the no-JS path. |
| `:root` transition triggers on every page load (not just navigation) | Low | A transition only fires when the property's value *changes*. First render has no prior value; no animation. Subsequent same-origin navigation in modern browsers triggers via `@view-transition`. |
| Reduced-motion users still see flicker | Low | E4 explicit overrides on both `:root` and view-transition pseudos. |
| `<style id="mh-theme-seed">` emits invalid HTML for malformed profiles | Low | The helper short-circuits on every exception path. Tests cover the unloaded / missing-derived-palette cases. |
| Stage C's pixel-parity break | None | Stage E is purely additive; Stage C tests must still pass. |
| Cross-doc View Transitions on Firefox break | Low | Firefox doesn't support cross-doc VT yet — they get instant navigation. Tested. |
| Click handler conflicts with other `<a>` elements | Low | The selector `[data-mh-cascade]` is unique; no other elements have it. |
| FOUC during the seed swap | Medium | The `<style id="mh-theme-seed">` is inlined in `<head>` after the main CSS — synchronous, no FOUC. Verified via response inspection. |
| Profile save races with concurrent requests | Low | Existing `save_profile()` is already concurrent-safe; the finalise endpoint just calls it. |

## 12. Audit plan (10 subtasks)

1. `theme-cascade.css` exists on disk and is non-empty.
2. `theme_tokens.py` loader includes it in `THEME_TOKENS_CSS`.
3. Static CSS contains `@view-transition { navigation: auto; }`.
4. Static CSS contains `:root { transition: --mh-brand-seed 600ms …; }`.
5. Static CSS contains `prefers-reduced-motion: reduce` overrides
   for both `:root` and view-transition pseudo-elements.
6. `_layout()` injects the `<style id="mh-theme-seed">` block
   when an active profile is loaded.
7. `POST /api/organisation/finalise` route is registered.
8. The button at line 11434 has `data-mh-cascade="finalise"`
   and the click handler is included.
9. Stage A's 161 tests still pass.
10. Stage C's 87 tests still pass.

## 13. Verify plan (10 subtasks)

1. App boots; `/status` returns HTTP 200.
2. Rendered HTML of `/status` contains `@view-transition`,
   `:root { transition: --mh-brand-seed`, and
   `prefers-reduced-motion: reduce`.
3. Rendered HTML of `/healthz/usage` likewise carries all three
   markers.
4. `POST /api/organisation/finalise` without active org returns
   400 with `error` key.
5. `POST /api/organisation/finalise` with an active org returns
   200 with `seed_hex` key.
6. After a successful POST, the profile's `brand_kit.derived_palette`
   is populated on disk (persistence works end-to-end).
7. The `<style id="mh-theme-seed">` block appears in rendered HTML
   when an active org has a derived palette.
8. The `<style id="mh-theme-seed">` block does NOT appear when
   no profile is active.
9. The "Looks right" button on `/organisation/setup` has the
   `data-mh-cascade` attribute and the JS handler is wired.
10. Full pytest suite passes (Stage A + B + C + new Stage E
    additions), zero new structural failures.

## 14. Out of scope (deferred)

- Full `before_request` middleware Stage D refactor — the
  per-request seed style block is the minimum-viable wiring;
  proper middleware comes later.
- Switching from inline `<style>` to `<link rel="stylesheet">`
  static delivery for `theme-*.css` — Stage D.
- Animated logo swap on theme change — Stage F.
- Theme JSON shared with motion / email / static graphic
  renderers — Stage G.
- "Why does my theme look like this?" UI panel — Stage H.
- Light-mode visual design (the `light-dark()` wrappers in Stage
  C ship identical arguments for both modes) — Stage D/J.

Stage E unlocks the rest of Phase 1.6 by establishing the
end-to-end "click → derive → persist → animate" loop. After
Stage E, every subsequent stage polishes a specific facet of the
loop. The hard architectural work is done.
