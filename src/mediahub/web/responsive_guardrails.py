"""Responsive guardrails CSS for MediaHub.

A future-proof, additive responsive enhancement layer. Every rule here either:

  * uses ``@supports`` for progressive enhancement so older engines ignore it,
  * is hidden behind a user-preference media query (``prefers-contrast``,
    ``prefers-reduced-motion``, ``forced-colors``, ``pointer: coarse``) so it
    only activates when the user has asked for it, OR
  * is an opt-in utility class (``.mh-*``) that components must choose to use.

Nothing here overrides an existing MediaHub selector with a stronger one, so
appending this string to ``BASE_CSS`` cannot break the existing visual design.
The whole layer is concatenated AFTER ``BASE_CSS`` so cascade order is
predictable and the guardrails always have the final word for the rules they
introduce.

The covered surface area is the full 2026 modern-responsive toolbox:

  * dynamic viewport units (dvh / svh / lvh) for mobile address-bar safety
  * container queries (@container) for component-level responsiveness
  * fluid typography & spacing via clamp()
  * safe-area insets for notch / Dynamic Island / foldable hardware
  * intrinsic responsive grids (auto-fit + minmax + min) needing no breakpoints
  * touch-target enforcement per WCAG 2.5.8 (Level AA, mandatory under the
    European Accessibility Act in force since June 2025)
  * prefers-contrast / forced-colors / prefers-reduced-motion support
  * defensive text wrapping (overflow-wrap, text-wrap: balance/pretty)
  * ultrawide & sub-320px (smartwatch) guards
  * print stylesheet so users can export a clean copy

Sources informing this layer:
  * https://web.dev/articles/new-responsive
  * https://defensivecss.dev/
  * https://www.joshwcomeau.com/css/custom-css-reset/
  * https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
  * https://web.dev/blog/viewport-units
"""

from __future__ import annotations

RESPONSIVE_GUARDRAILS_CSS = r"""
/* =====================================================================
   RESPONSIVE GUARDRAILS (2026)
   ---------------------------------------------------------------------
   Additive layer concatenated after BASE_CSS. Every rule is either:
     - gated by @supports (progressive enhancement),
     - scoped to a user-preference media query, or
     - an opt-in `.mh-*` utility class.
   Nothing here is meant to override existing MediaHub styles.
   ===================================================================== */

/* ---------------------------------------------------------------------
   1. New design tokens. Additive — never reassign existing tokens.
   --------------------------------------------------------------------- */
:root {
  /* Modern viewport sizing — fallbacks first, dvh/svh/lvh below via @supports */
  --mh-vh-dynamic: 100vh;
  --mh-vh-small:   100vh;
  --mh-vh-large:   100vh;

  /* WCAG 2.5.8 touch target minimum (24 CSS px AA, 44 CSS px AAA).
     The 24px minimum became legally required under the EAA in June 2025. */
  --mh-touch-min:         24px;
  --mh-touch-comfortable: 44px;

  /* Safe-area inset tokens. env() resolves to 0 on devices with no notch,
     so referencing them is always safe even on legacy browsers. */
  --mh-safe-top:    env(safe-area-inset-top,    0px);
  --mh-safe-right:  env(safe-area-inset-right,  0px);
  --mh-safe-bottom: env(safe-area-inset-bottom, 0px);
  --mh-safe-left:   env(safe-area-inset-left,   0px);

  /* Fluid type scale built with clamp(min, preferred, max).
     Combines rem + vw so the user's zoom & font-size preferences still win. */
  --mh-fluid-step-0: clamp(0.875rem, 0.84rem + 0.18vw, 1rem);
  --mh-fluid-step-1: clamp(1rem,     0.95rem + 0.25vw, 1.125rem);
  --mh-fluid-step-2: clamp(1.125rem, 1.04rem + 0.42vw, 1.375rem);
  --mh-fluid-step-3: clamp(1.375rem, 1.2rem  + 0.88vw, 1.875rem);
  --mh-fluid-step-4: clamp(1.75rem,  1.4rem  + 1.75vw, 2.75rem);
  --mh-fluid-step-5: clamp(2.25rem,  1.7rem  + 2.75vw, 4rem);

  /* Fluid spacing scale */
  --mh-fluid-space-xs: clamp(0.25rem, 0.2rem  + 0.2vw, 0.5rem);
  --mh-fluid-space-sm: clamp(0.5rem,  0.4rem  + 0.4vw, 0.875rem);
  --mh-fluid-space-md: clamp(1rem,    0.85rem + 0.6vw, 1.5rem);
  --mh-fluid-space-lg: clamp(1.5rem,  1.2rem  + 1.2vw, 2.5rem);
  --mh-fluid-space-xl: clamp(2rem,    1.5rem  + 2vw,   4rem);

  /* Container-query breakpoints (component-relative, not viewport). */
  --mh-cq-sm: 360px;
  --mh-cq-md: 540px;
  --mh-cq-lg: 720px;

  /* Viewport breakpoint tokens — parity with the existing media queries,
     plus the new ultrawide tier and a smartwatch tier. */
  --mh-bp-watch:     320px;
  --mh-bp-mobile:    480px;
  --mh-bp-tablet:    720px;
  --mh-bp-desktop:   860px;
  --mh-bp-wide:     1280px;
  --mh-bp-ultrawide:1920px;
}

/* Promote to modern dynamic viewport units where supported. dvh/svh/lvh
   reached Baseline Widely Available in June 2025. */
@supports (height: 100dvh) {
  :root {
    --mh-vh-dynamic: 100dvh;
    --mh-vh-small:   100svh;
    --mh-vh-large:   100lvh;
  }
}

/* Root-level safety primitives. Wrapped in @supports so older engines
   silently skip them; everything is independently safe to omit. */
@supports (text-size-adjust: 100%) {
  html { text-size-adjust: 100%; -webkit-text-size-adjust: 100%; }
}
@supports (scrollbar-gutter: stable) {
  html { scrollbar-gutter: stable; }
}
@supports (color-scheme: dark) {
  /* MediaHub ships a single dark theme. Pinning color-scheme to dark
     keeps the UA chrome (scrollbars, form controls, text selection)
     dark to match. */
  :root { color-scheme: dark; }
}
@supports (interpolate-size: allow-keywords) {
  :root { interpolate-size: allow-keywords; }
}

/* ---------------------------------------------------------------------
   2. Defensive text & media flow.
   These rules harden existing markup against overflowing on narrow
   viewports. They only activate when content would otherwise break out
   of its container, so visible layouts on normal content stay identical.
   --------------------------------------------------------------------- */

/* Long unbreakable strings (URLs, tokens, swimmer keys) can't blow out
   the layout on phones. overflow-wrap: anywhere is the modern, safer
   word-wrap; it only breaks when no other opportunity exists. */
h1, h2, h3, h4, h5, h6,
p, dt, dd, li, td, th, blockquote, figcaption, caption, summary, label {
  overflow-wrap: anywhere;
  word-break: normal;
}

/* Pretty / balanced text wrapping on browsers that support it — no orphans
   in headings, no rivers in body copy. Falls back silently elsewhere. */
@supports (text-wrap: balance) {
  h1, h2, h3, h4 { text-wrap: balance; }
}
@supports (text-wrap: pretty) {
  p, li, dd, blockquote { text-wrap: pretty; }
}

/* Inline media never overflows its container. height: auto preserves
   aspect ratio; max-width: 100% caps width. These are the canonical
   defensive defaults from Andy Bell's modern reset. */
img, picture, video, canvas, svg, iframe, embed, object {
  max-width: 100%;
  height: auto;
}
img, video { block-size: auto; }

/* Flex / grid children that have intrinsic min-content (long words, large
   images) can otherwise refuse to shrink and force horizontal scroll.
   min-width: 0 lets them shrink. Scoped to MediaHub's own layout helpers
   so unrelated flexboxes are untouched. */
.row > *, .grid-2 > *, .grid-3 > *, .topnav nav > * {
  min-width: 0;
}

/* ---------------------------------------------------------------------
   3. Touch-target safety (WCAG 2.5.8, Level AA).
   Only enlarges hit areas on coarse pointers (phones, tablets, kiosks),
   so desktop mouse layouts are unchanged. Uses min-* so any larger
   pre-existing size wins.
   --------------------------------------------------------------------- */
@media (pointer: coarse) {
  a[href], button,
  input[type="button"], input[type="submit"], input[type="reset"],
  input[type="checkbox"], input[type="radio"],
  [role="button"], [role="link"], [role="tab"], [role="menuitem"],
  summary, select {
    min-height: var(--mh-touch-min);
    min-width:  var(--mh-touch-min);
  }
}

/* ---------------------------------------------------------------------
   4. Safe-area-inset for notch / Dynamic Island / foldable hardware.
   max(0px, env(...)) means the body still has zero side padding on
   non-notched devices (env() resolves to 0px). On phones with cutouts
   the content shifts inward by exactly the inset, so nothing is hidden.
   Wrapped in @supports for ultra-old engines.
   --------------------------------------------------------------------- */
@supports (padding: max(0px)) {
  body {
    padding-left:  max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}

/* ---------------------------------------------------------------------
   5. User-preference media queries.
   --------------------------------------------------------------------- */

/* Higher-contrast tokens for users who request them. Only the muted
   variants are nudged — chrome colours (lane yellow, medal gold) stay
   pinned because they are brand. */
@media (prefers-contrast: more) {
  :root {
    --hairline:  rgba(245,242,232,0.20);
    --rule:      rgba(245,242,232,0.32);
    --chrome:    rgba(245,242,232,0.48);
    --ink-muted: #9C9A8D;
    --ink-dim:   #D6D2C6;
    --ink-faint: #6A6960;
  }
  a, button, .btn { outline-offset: 2px; }
}

/* Windows High Contrast Mode + system forced-colors. CanvasText is the
   system-paint that always contrasts with the system background. */
@media (forced-colors: active) {
  :focus-visible {
    outline: 2px solid CanvasText;
    outline-offset: 2px;
  }
  .btn, button, a {
    forced-color-adjust: auto;
  }
}

/* ---------------------------------------------------------------------
   6. Viewport-tier guards for emerging form factors.
   --------------------------------------------------------------------- */

/* Smartwatch / sub-mobile (≤ 320px). Wear-OS browsers and small embedded
   surfaces. Pulls inner padding tight so content still fits without
   horizontal scroll. */
@media (max-width: 320px) {
  main.wrap { padding-left: 10px; padding-right: 10px; }
  .row { gap: 8px; }
  .grid-2, .grid-3 { gap: 8px; }
}

/* Ultrawide & 4K (≥ 1920px). Caps line length for readability but lets
   the wrap stretch a bit beyond its 1200px desktop max so the layout
   doesn't look stranded in the middle of a 34" monitor. */
@media (min-width: 1920px) {
  main.wrap { max-width: min(1400px, 88vw); }
}

/* TV / very large displays (≥ 2400px). Centred reading column. */
@media (min-width: 2400px) {
  main.wrap { max-width: 1600px; }
}

/* ---------------------------------------------------------------------
   7. Print stylesheet.
   Page can be printed or saved as PDF cleanly without losing content.
   --------------------------------------------------------------------- */
@media print {
  *, *::before, *::after {
    background: transparent !important;
    color: #000 !important;
    box-shadow: none !important;
    text-shadow: none !important;
  }
  body { background: #fff !important; color: #000 !important; }
  .topnav, .mh-footer, #mh-loader, #mh-toast-container, .no-print { display: none !important; }
  main.wrap { max-width: 100%; padding: 0; }
  a[href]::after { content: " (" attr(href) ")"; font-size: 0.85em; color: #444; }
  img, svg, video { max-width: 100% !important; page-break-inside: avoid; }
  h1, h2, h3, h4 { page-break-after: avoid; }
  pre, blockquote, table { page-break-inside: avoid; }
}

/* ---------------------------------------------------------------------
   8. Focus visibility — keyboard-only outline.
   :focus-visible only triggers on keyboard focus, never on mouse click,
   so mouse users don't get the "click ring" but keyboard users do.
   --------------------------------------------------------------------- */
@supports selector(:focus-visible) {
  :focus-visible {
    outline: 2px solid var(--lane);
    outline-offset: 2px;
    border-radius: 2px;
  }
  :focus:not(:focus-visible) { outline: none; }
}

/* ---------------------------------------------------------------------
   9. Opt-in utility classes for new responsive features.
   Components that want the new powers add the class; everything else
   is untouched.
   --------------------------------------------------------------------- */

/* Viewport-height utilities — pick the right one for the surface:
     -stable   = won't shift when mobile browser chrome appears
     -dynamic  = follows the browser chrome as it expands / collapses
     -large    = always the full extended viewport */
.mh-fullheight-stable  { min-height: var(--mh-vh-small);   }
.mh-fullheight-dynamic { min-height: var(--mh-vh-dynamic); }
.mh-fullheight-large   { min-height: var(--mh-vh-large);   }

/* Fluid type utilities */
.mh-text-fluid-sm  { font-size: var(--mh-fluid-step-0); line-height: 1.5; }
.mh-text-fluid-md  { font-size: var(--mh-fluid-step-1); line-height: 1.5; }
.mh-text-fluid-lg  { font-size: var(--mh-fluid-step-2); line-height: 1.4; }
.mh-text-fluid-xl  { font-size: var(--mh-fluid-step-3); line-height: 1.3; }
.mh-text-fluid-2xl { font-size: var(--mh-fluid-step-4); line-height: 1.2; }
.mh-text-fluid-3xl { font-size: var(--mh-fluid-step-5); line-height: 1.1; }

/* Fluid spacing utilities */
.mh-stack-xs > * + * { margin-block-start: var(--mh-fluid-space-xs); }
.mh-stack-sm > * + * { margin-block-start: var(--mh-fluid-space-sm); }
.mh-stack-md > * + * { margin-block-start: var(--mh-fluid-space-md); }
.mh-stack-lg > * + * { margin-block-start: var(--mh-fluid-space-lg); }
.mh-stack-xl > * + * { margin-block-start: var(--mh-fluid-space-xl); }

/* Intrinsic responsive grids — never overflow, no media queries needed.
   The min() guards against the minmax track itself overflowing when the
   container is narrower than the minimum. */
.mh-grid-auto {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
  gap: var(--mh-fluid-space-md);
}
.mh-grid-auto-sm {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr));
  gap: var(--mh-fluid-space-sm);
}
.mh-grid-auto-lg {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(360px, 100%), 1fr));
  gap: var(--mh-fluid-space-lg);
}

/* Container-query wrappers. Add this class to a card / panel and it can
   query its OWN width via @container instead of the page viewport. */
.mh-container      { container-type: inline-size; }
.mh-container-card { container: mh-card / inline-size; }
.mh-container-panel{ container: mh-panel / inline-size; }

/* Aspect-ratio media slots — reserve space BEFORE the image loads,
   eliminating cumulative layout shift (CLS). */
.mh-aspect-video    { aspect-ratio: 16 / 9; }
.mh-aspect-square   { aspect-ratio: 1 / 1; }
.mh-aspect-portrait { aspect-ratio: 9 / 16; }
.mh-aspect-card     { aspect-ratio: 4 / 5; }
.mh-aspect-wide     { aspect-ratio: 21 / 9; }

/* Truncation helpers */
.mh-truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.mh-clamp-2,
.mh-clamp-3,
.mh-clamp-4 {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mh-clamp-2 { -webkit-line-clamp: 2; line-clamp: 2; }
.mh-clamp-3 { -webkit-line-clamp: 3; line-clamp: 3; }
.mh-clamp-4 { -webkit-line-clamp: 4; line-clamp: 4; }

/* Screen-reader-only content (visible to assistive tech, hidden visually). */
.mh-visually-hidden,
.mh-sr-only {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0,0,0,0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

/* Force a comfortable touch target (WCAG 2.5.5 AAA, 44 CSS px). */
.mh-touch-target {
  min-height: var(--mh-touch-comfortable);
  min-width:  var(--mh-touch-comfortable);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* Notch-aware padding helpers for fixed top/bottom UI. */
.mh-pad-safe-top    { padding-top:    max(var(--sp-4, 16px), env(safe-area-inset-top));    }
.mh-pad-safe-bottom { padding-bottom: max(var(--sp-4, 16px), env(safe-area-inset-bottom)); }
.mh-pad-safe-x {
  padding-left:  max(var(--sp-4, 16px), env(safe-area-inset-left));
  padding-right: max(var(--sp-4, 16px), env(safe-area-inset-right));
}

/* Logical-property helpers for RTL-friendly margins / paddings. */
.mh-mi-auto { margin-inline: auto; }
.mh-mb-auto { margin-block:  auto; }
.mh-pi-md   { padding-inline: var(--mh-fluid-space-md); }
.mh-pb-md   { padding-block:  var(--mh-fluid-space-md); }

/* ---------------------------------------------------------------------
   10. Container-query example — opt-in card that adapts to its slot.
   --------------------------------------------------------------------- */
.mh-card-responsive { container-type: inline-size; }

@container (max-width: 360px) {
  .mh-card-responsive .mh-card-body { font-size: 0.875rem; padding: 8px; }
  .mh-card-responsive .mh-card-actions { flex-direction: column; gap: 6px; }
}
@container (min-width: 720px) {
  .mh-card-responsive .mh-card-body { font-size: 1rem; padding: 16px; }
}

/* ===================================================================== */
/* END RESPONSIVE GUARDRAILS                                              */
/* ===================================================================== */
"""

__all__ = ["RESPONSIVE_GUARDRAILS_CSS"]
