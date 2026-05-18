# Responsive Design Guardrails

> **Status:** Active. Owns the responsive baseline for every page MediaHub
> renders. Future pull requests are expected to keep these guardrails passing.

This document explains the responsive-design layer that ships with every
MediaHub page so that any future template change inherits a future-proof
baseline — no matter the device the user is on.

## Why this exists

MediaHub renders its UI as f-string Jinja2 templates inside a 13 000-line
Flask monolith. Without a guardrail layer, every new route or template edit
is a chance to silently regress mobile-friendliness, accessibility, or
cross-device behaviour. The guardrails close that gap.

**The promise:** the moment a route uses the shared page-render path,
it inherits modern responsive behaviour for free, with no per-route work
required.

## What's in the layer

The guardrails live in **`src/mediahub/web/responsive_guardrails.py`** and
are appended to `BASE_CSS` in `src/mediahub/web/web.py`. They are loaded on
every HTML response.

### 1. Modern viewport units (`dvh` / `svh` / `lvh`)
Fixes mobile-Safari and mobile-Chrome address-bar resize jumps. Falls back
to `100vh` on legacy engines via `@supports`.

### 2. Container queries (`@container`)
Lets cards / panels respond to **their own** width instead of the page
viewport. Opt in by adding `class="mh-container"` (or `mh-card-responsive`).

### 3. Fluid typography
Six `clamp()`-based steps (`--mh-fluid-step-0` … `--mh-fluid-step-5`) that
scale smoothly between mobile and desktop without media queries. All steps
use `rem` floors and stay under the 2.5× ratio so the user can zoom to 200%
without breaking text (WCAG 1.4.4).

### 4. Safe-area insets
`env(safe-area-inset-*)` is applied to the `<body>` with a `max(0px, ...)`
guard so the layout shifts inward on notched / Dynamic-Island phones and
foldables, and remains identical everywhere else. Combined with the new
`viewport-fit=cover` viewport hint.

### 5. Touch-target compliance (WCAG 2.5.8)
Interactive elements get `min-height: 24px; min-width: 24px;` **only on
coarse pointers** (`@media (pointer: coarse)`). Desktop mouse layouts are
untouched. 24 CSS px has been mandatory under the European Accessibility
Act since June 2025.

### 6. User-preference media queries
| Preference | What changes |
|---|---|
| `prefers-reduced-motion: reduce` | Disables animations & transitions (pre-existing) |
| `prefers-contrast: more` | Boosts hairline / rule / chrome opacity, lifts muted ink |
| `forced-colors: active` | Keeps focus rings visible in Windows High Contrast Mode |
| `prefers-color-scheme: light/dark` | Advertises the dark-first scheme to browser chrome |

### 7. Form-factor breakpoints
- **`max-width: 320px`** — smartwatch / Wear-OS. Tight padding so content fits.
- **`min-width: 1920px`** — 4K & ultrawide. `main.wrap` stretches to `min(1400px, 88vw)`.
- **`min-width: 2400px`** — TVs & ultra-large displays. 1600px reading column.

### 8. Defensive CSS
- `overflow-wrap: anywhere` on all text elements — long URLs / tokens can't blow out the layout.
- `text-wrap: balance` on headings, `text-wrap: pretty` on body copy (where supported).
- `min-width: 0` on flex/grid children to prevent intrinsic-min-content overflow.
- `max-width: 100%; height: auto` on `img / video / svg / iframe`.

### 9. Print stylesheet
`@media print` strips chrome, drops shadows, prints link URLs inline, and
prevents page breaks inside cards/tables. Users can save any page as a
clean PDF.

### 10. Opt-in utility classes
| Class | Purpose |
|---|---|
| `.mh-fullheight-stable` / `.mh-fullheight-dynamic` / `.mh-fullheight-large` | Use `svh` / `dvh` / `lvh` respectively |
| `.mh-text-fluid-sm` … `.mh-text-fluid-3xl` | Six clamp-based type sizes |
| `.mh-stack-sm` … `.mh-stack-xl` | Vertical-rhythm helpers |
| `.mh-grid-auto` / `-sm` / `-lg` | Intrinsic responsive grids, no breakpoints |
| `.mh-container` / `-card` / `-panel` | Container-query wrappers |
| `.mh-aspect-video` / `-square` / `-portrait` / `-card` / `-wide` | `aspect-ratio` slots |
| `.mh-truncate`, `.mh-clamp-2`, `.mh-clamp-3`, `.mh-clamp-4` | Truncation helpers |
| `.mh-visually-hidden` / `.mh-sr-only` | Screen-reader-only content |
| `.mh-touch-target` | Forces WCAG 2.5.5 AAA 44px hit area |
| `.mh-pad-safe-top` / `-bottom` / `-x` | Notch-aware padding |

### 11. Meta tags (in `web.py`)
The shared page template now emits:
```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="dark light" />
<meta name="theme-color" content="#0A0B11" />
<meta name="format-detection" content="telephone=no" />
```

## How to extend it

**Don't edit `BASE_CSS` in `web.py`** for responsive concerns. Add to
`responsive_guardrails.py` instead. The guardrails file is documented
section-by-section so each addition has a clear home.

When adding a new utility class:
1. Add the rule to the right section of `responsive_guardrails.py`.
2. Prefix the class with `mh-` so it's clearly part of the layer.
3. Add an `@supports` gate if it depends on a modern feature.
4. Add a test in `tests/test_responsive_guardrails.py` so the class can't
   be silently dropped later.

## What the tests pin

Two pytest files lock the contract:

- **`tests/test_responsive_guardrails.py`** — unit checks on the CSS
  content: each modern feature, each fluid-type step, each WCAG primitive,
  each `@supports` gate. Also verifies the existing brand tokens
  (`--bg`, `--lane`, `--medal`, …) survive any future edit.
- **`tests/test_responsive_meta.py`** — integration checks that boot the
  Flask app and verify every public HTML route ships the viewport meta
  tag, `viewport-fit=cover`, `color-scheme`, `theme-color`, and the
  guardrails CSS payload.

Run them locally with:
```bash
python -m pytest tests/test_responsive_guardrails.py tests/test_responsive_meta.py -v
```

## CI

`.github/workflows/responsive-design.yml` runs both suites on every PR and
on every push to `main` / `dev`. A green check is required for the
responsive baseline to be considered intact.

A separate (non-blocking) job runs **stylelint** against the standalone
`.css` files in `src/mediahub/graphic_renderer/layouts/` so future PRs to
those static assets get linted too. Stylelint runs with
`stylelint-config-standard` plus a small set of MediaHub-specific
overrides in `.stylelintrc.json`.

## Browser-support floor

The guardrails are designed against **Baseline Widely Available 2024+**:
- Chrome / Edge ≥ 117
- Firefox ≥ 121
- Safari ≥ 16.4
- iOS Safari ≥ 16.4

Anything older falls back gracefully because every modern primitive is
behind an `@supports` gate. The page will still render — it just won't get
the dvh smoothing, container queries, balanced text, or safe-area insets.

## How to test on real devices

Until we wire in Playwright visual regression (see "Future work" below),
the manual QA pass is:

1. **Phone (iOS Safari, notched):** open `/status`; the body should shift
   inward on the notch side. Rotate landscape; both edges should respect
   the notch.
2. **Phone (Android Chrome):** scroll the page — the address bar collapse
   shouldn't cause anything below the fold to jump.
3. **Tablet (iPad):** zoom Pinch-to-200%; all text should remain readable
   and no content should clip.
4. **Desktop (1280–1440):** Resize the window between 480 and 1920 px in
   DevTools. Layout should change smoothly with no horizontal scroll.
5. **Ultrawide (≥ 1920):** `main.wrap` should be wider than 1200 px but
   still capped — it shouldn't stretch all the way across.
6. **Accessibility:** Enable "Reduce motion" in OS settings — all
   animations should freeze. Enable "Increase contrast" in OS settings —
   muted ink and rules should darken.

## Future work

- **Playwright visual-regression matrix** (iPhone SE, Pixel 7, iPad,
  desktop 1440, ultrawide 2560, reflow 320×256). Will live in
  `tests/visual/` and be invoked from a separate workflow.
- **Lighthouse CI** with budgets for LCP ≤ 2.5s, CLS ≤ 0.1, INP ≤ 200ms,
  accessibility ≥ 0.95.
- **axe-core** assertions on key flows.
- **Container query coverage** rolled out to more existing cards as
  they're refactored (`.mh-container` is opt-in today).

## Source material

The guardrails follow the 2026 modern-responsive playbook documented at:
- [web.dev: The new responsive](https://web.dev/articles/new-responsive)
- [defensivecss.dev](https://defensivecss.dev/)
- [Josh Comeau: A Modern CSS Reset](https://www.joshwcomeau.com/css/custom-css-reset/)
- [Andy Bell: A (more) Modern CSS Reset](https://piccalil.li/blog/a-more-modern-css-reset/)
- [W3C WCAG 2.2 SC 2.5.8 Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- [web.dev: Viewport units (dvh/svh/lvh)](https://web.dev/blog/viewport-units)
- [MDN: CSS environment variables (`env()`)](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_environment_variables/Using_environment_variables)
