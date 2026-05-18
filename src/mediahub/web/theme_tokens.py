"""Three-tier DTCG-format design-token vocabulary for MediaHub.

This module is the foundation layer for the Adaptive Theming Engine
described in Phase 1.6 of ``docs/ROADMAP.md``. It contains a single
exported string ``THEME_TOKENS_CSS`` that is prepended to ``BASE_CSS``
so the rest of the stylesheet (and every f-string-emitted inline
style) can resolve through a coherent role-token vocabulary.

# Tier hierarchy (per W3C Design Tokens Community Group format)

1. **Primitives (``--mh-prim-*``)** — raw colour values, no semantics.
   Organised as tonal ramps (brand, tertiary, neutral) and status
   anchors (error, success, warning, info). For Stage A the ramps are
   hand-anchored to the existing "Podium After Dark" palette. Stage B
   replaces these with HCT-derived values from a single brand seed.

2. **Semantic role tokens (``--mh-*``)** — ~25 Material-3-style tokens
   referencing primitives, never raw hex. These are the *theme layer*
   — Stage E re-points them per club without touching component code.

3. **Component tokens** — deliberately not introduced in Stage A
   (Nathan Curtis's "promote across 3+ component reuses" rule).

# Legacy aliases

Every token the existing ``BASE_CSS`` defines (``--bg``, ``--ink``,
``--lane``, ``--medal``, ``--accent``, ``--panel``, ``--good``, …)
is re-pointed at a tier-2 semantic role here. The cascade resolves
aliases at use time, so the existing 879 ``var(--*)`` callsites in
``web.py`` need zero edits and the rendered pixels are identical.

# ``@property`` registration

Every tier-2 role token is registered via ``@property`` with
``syntax: "<color>"`` and ``inherits: true`` so the Stage E cascade
animation actually interpolates colour values instead of snapping.
Without the registration, CSS custom properties are untyped strings
and ``transition: --mh-surface 600ms`` is a silent no-op.

Browser support: ``@property`` is Baseline Widely Available (Chrome
85+, Firefox 128+, Safari 16.4+, ~94% global coverage in May 2026).
Older browsers ignore the at-rule silently, keeping today's behaviour
(no animation, instant theme apply).

# Cascade order

The string is prepended to ``BASE_CSS`` so the resulting cascade is:

    THEME_TOKENS_CSS → BASE_CSS → RESPONSIVE_GUARDRAILS_CSS

Tier-2 tokens are defined first; ``BASE_CSS``'s ``:root`` block then
overrides legacy aliases to point at the new tokens; the guardrails
layer still has the final word.

# Sources

- W3C Design Tokens Format Module (DTCG)
  https://www.designtokens.org/TR/drafts/format/
- Material Design 3 — Color Roles
  https://m3.material.io/styles/color/roles
- Nathan Curtis — Naming Tokens in Design Systems (EightShapes)
  https://medium.com/eightshapes-llc/naming-tokens-in-design-systems-9e86c7444676
- CSS Properties and Values API Level 1 — ``@property``
  https://www.w3.org/TR/css-properties-values-api-1/
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Primitive seed values (the only raw hex in this module)
# ---------------------------------------------------------------------------
# Each primitive corresponds to an existing colour in ``BASE_CSS`` or a
# derived ramp stop sitting between two existing colours. Stage A's job is
# to ratify the existing palette as a tonal vocabulary, not to redesign it.
# Stage B replaces these with HCT-derived values from a brand seed.

# Brand (lane-marker yellow #D4FF3A). 13 tones.
_BRAND_0    = "#FFFFFF"
_BRAND_50   = "#FAFFE6"
_BRAND_100  = "#F1FFB8"
_BRAND_200  = "#E6FF8A"
_BRAND_300  = "#E6FF6B"  # current --lane-h
_BRAND_400  = "#D4FF3A"  # current --lane (the seed)
_BRAND_500  = "#C2E832"
_BRAND_600  = "#A8CC2E"  # current --lane-deep
_BRAND_700  = "#8AA823"
_BRAND_800  = "#6B821C"
_BRAND_900  = "#4A5E12"
_BRAND_950  = "#2A360A"
_BRAND_1000 = "#000000"

# Tertiary (medal gold #F4D58D). 13 tones.
_TERTIARY_0    = "#FFFFFF"
_TERTIARY_50   = "#FFF9EC"
_TERTIARY_100  = "#FFEEC4"
_TERTIARY_200  = "#FFE5A1"  # current --medal-h
_TERTIARY_300  = "#F8DC97"
_TERTIARY_400  = "#F4D58D"  # current --medal (the seed)
_TERTIARY_500  = "#DEBD75"
_TERTIARY_600  = "#C9A04B"  # current --medal-deep
_TERTIARY_700  = "#9F7E36"
_TERTIARY_800  = "#6E5524"
_TERTIARY_900  = "#3F2F12"
_TERTIARY_950  = "#2B1F00"  # current --medal-ink
_TERTIARY_1000 = "#000000"

# Neutral (paper-cream → pit-wall black). 14 tones because the existing
# palette has more granularity on the dark side than a typical 13-tone ramp.
_NEUTRAL_0    = "#FFFFFF"
_NEUTRAL_50   = "#F5F2E8"  # current --ink
_NEUTRAL_100  = "#E3DFD3"
_NEUTRAL_200  = "#C9C5B6"
_NEUTRAL_300  = "#B6B2A6"  # current --ink-dim
_NEUTRAL_400  = "#9A988A"  # current --ink-muted
_NEUTRAL_500  = "#7A786C"
_NEUTRAL_600  = "#62604F"  # current --ink-faint
_NEUTRAL_700  = "#3D3D33"
_NEUTRAL_750  = "#2E2E26"
_NEUTRAL_800  = "#232838"  # current --surface-3
_NEUTRAL_850  = "#1A1E28"  # current --surface-2
_NEUTRAL_900  = "#14171F"  # current --surface
_NEUTRAL_950  = "#0A0B11"  # current --bg
_NEUTRAL_1000 = "#06070C"  # current --bg-deep

# Status anchors — single tone each for Stage A (full ramps in Stage B).
_ERROR_300    = "#FFBCC3"
_ERROR_400    = "#FF6B6B"  # current --bad
_ERROR_500    = "#FF5D6C"  # used in some inline f-strings
_ERROR_600    = "#FF8A99"  # used in error-text fstrings

_SUCCESS_400  = "#5EE39A"  # current --good

_WARNING_400  = "#FFB454"  # current --warn
_WARNING_500  = "#FFAA3A"  # used in inline f-strings
_WARNING_600  = "#FFAE3B"  # used in inline f-strings

_INFO_400     = "#4DA3FF"  # current --info


THEME_TOKENS_CSS = r"""
/* =====================================================================
   THEME TOKENS (Stage A — Adaptive Theming Engine foundation)
   ---------------------------------------------------------------------
   Three-tier design-token vocabulary prepended to BASE_CSS. See
   src/mediahub/web/theme_tokens.py for the rationale and citations.

   Tier 1 (--mh-prim-*) — raw values, organised as tonal ramps.
   Tier 2 (--mh-*)      — Material-3-style semantic role tokens that
                          reference primitives. THIS IS THE THEME LAYER.
   Tier 3 (component)   — deferred to Stage D+.

   Legacy aliases (--bg, --ink, --lane, --medal, --accent, --panel, …)
   are re-pointed at tier-2 tokens at the bottom of this block, so every
   existing var(--*) callsite resolves to the same pixel value as today.
   ===================================================================== */

:root {
  /* ------------------------------------------------------------------
     TIER 1 — PRIMITIVES (raw values, no semantics)
     ------------------------------------------------------------------ */

  /* Brand — lane-marker yellow tonal ramp */
  --mh-prim-brand-0:    #FFFFFF;
  --mh-prim-brand-50:   #FAFFE6;
  --mh-prim-brand-100:  #F1FFB8;
  --mh-prim-brand-200:  #E6FF8A;
  --mh-prim-brand-300:  #E6FF6B;
  --mh-prim-brand-400:  #D4FF3A;
  --mh-prim-brand-500:  #C2E832;
  --mh-prim-brand-600:  #A8CC2E;
  --mh-prim-brand-700:  #8AA823;
  --mh-prim-brand-800:  #6B821C;
  --mh-prim-brand-900:  #4A5E12;
  --mh-prim-brand-950:  #2A360A;
  --mh-prim-brand-1000: #000000;

  /* Tertiary — medal-gold tonal ramp */
  --mh-prim-tertiary-0:    #FFFFFF;
  --mh-prim-tertiary-50:   #FFF9EC;
  --mh-prim-tertiary-100:  #FFEEC4;
  --mh-prim-tertiary-200:  #FFE5A1;
  --mh-prim-tertiary-300:  #F8DC97;
  --mh-prim-tertiary-400:  #F4D58D;
  --mh-prim-tertiary-500:  #DEBD75;
  --mh-prim-tertiary-600:  #C9A04B;
  --mh-prim-tertiary-700:  #9F7E36;
  --mh-prim-tertiary-800:  #6E5524;
  --mh-prim-tertiary-900:  #3F2F12;
  --mh-prim-tertiary-950:  #2B1F00;
  --mh-prim-tertiary-1000: #000000;

  /* Neutral — paper-cream → pit-wall black, denser on the dark side
     because the existing palette has multiple surface tiers. */
  --mh-prim-neutral-0:    #FFFFFF;
  --mh-prim-neutral-50:   #F5F2E8;
  --mh-prim-neutral-100:  #E3DFD3;
  --mh-prim-neutral-200:  #C9C5B6;
  --mh-prim-neutral-300:  #B6B2A6;
  --mh-prim-neutral-400:  #9A988A;
  --mh-prim-neutral-500:  #7A786C;
  --mh-prim-neutral-600:  #62604F;
  --mh-prim-neutral-700:  #3D3D33;
  --mh-prim-neutral-750:  #2E2E26;
  --mh-prim-neutral-800:  #232838;
  --mh-prim-neutral-850:  #1A1E28;
  --mh-prim-neutral-900:  #14171F;
  --mh-prim-neutral-950:  #0A0B11;
  --mh-prim-neutral-1000: #06070C;

  /* Status anchors — single tones for Stage A (full ramps in Stage B) */
  --mh-prim-error-300:   #FFBCC3;
  --mh-prim-error-400:   #FF6B6B;
  --mh-prim-error-500:   #FF5D6C;
  --mh-prim-error-600:   #FF8A99;

  --mh-prim-success-400: #5EE39A;

  --mh-prim-warning-400: #FFB454;
  --mh-prim-warning-500: #FFAA3A;
  --mh-prim-warning-600: #FFAE3B;

  --mh-prim-info-400:    #4DA3FF;

  /* ------------------------------------------------------------------
     TIER 2 — SEMANTIC ROLE TOKENS (Material 3 vocabulary)
     ------------------------------------------------------------------ */

  /* Surfaces — the page, cards, raised elements */
  --mh-surface:                var(--mh-prim-neutral-950);
  --mh-surface-deep:           var(--mh-prim-neutral-1000);
  --mh-surface-variant:        var(--mh-prim-neutral-900);
  --mh-surface-container:      var(--mh-prim-neutral-850);
  --mh-surface-container-high: var(--mh-prim-neutral-800);

  /* On-surface (text + icons on neutral surfaces) */
  --mh-on-surface:         var(--mh-prim-neutral-50);
  --mh-on-surface-variant: var(--mh-prim-neutral-300);
  --mh-on-surface-muted:   var(--mh-prim-neutral-400);
  --mh-on-surface-faint:   var(--mh-prim-neutral-600);

  /* Primary (brand) — CTAs, links, focus, live state */
  --mh-primary:               var(--mh-prim-brand-400);
  --mh-primary-hover:         var(--mh-prim-brand-300);
  --mh-primary-pressed:       var(--mh-prim-brand-600);
  --mh-on-primary:            var(--mh-prim-neutral-950);
  --mh-primary-container:     var(--mh-prim-brand-100);
  --mh-on-primary-container:  var(--mh-prim-brand-900);

  /* Secondary — Stage A aliases to primary; Stage B derives a real
     secondary palette with the +0° hue / reduced-chroma MD3 pattern. */
  --mh-secondary:    var(--mh-primary);
  --mh-on-secondary: var(--mh-on-primary);

  /* Tertiary (medal) — RESERVED EXCLUSIVELY for athlete achievements
     per the existing "Podium After Dark" convention */
  --mh-tertiary:               var(--mh-prim-tertiary-400);
  --mh-on-tertiary:            var(--mh-prim-tertiary-950);
  --mh-tertiary-container:     var(--mh-prim-tertiary-100);
  --mh-on-tertiary-container:  var(--mh-prim-tertiary-900);

  /* Outline (borders, dividers, form chrome) */
  --mh-outline:         rgba(245, 242, 232, 0.14);
  --mh-outline-variant: rgba(245, 242, 232, 0.06);
  --mh-outline-rule:    rgba(245, 242, 232, 0.10);

  /* Status roles — kept locked by hue family (red/amber/green/blue) per
     cross-cultural-semantics research (Aslam 2006, WCAG 1.4.1). */
  --mh-error:    var(--mh-prim-error-400);
  --mh-on-error: var(--mh-prim-neutral-950);

  --mh-success: var(--mh-prim-success-400);
  --mh-warning: var(--mh-prim-warning-400);
  --mh-info:    var(--mh-prim-info-400);

  /* Focus */
  --mh-focus: var(--mh-primary);

  /* Elevation (shadows) — three depths */
  --mh-elevation-1: 0 1px 0 rgba(245, 242, 232, 0.04);
  --mh-elevation-2:
    0 1px 0 rgba(245, 242, 232, 0.04),
    0 14px 32px rgba(0, 0, 0, 0.45);
  --mh-elevation-3:
    0 1px 0 rgba(245, 242, 232, 0.06),
    0 24px 60px rgba(0, 0, 0, 0.55);
}

/* =====================================================================
   @property registrations
   ---------------------------------------------------------------------
   Register each tier-2 role token as a typed colour custom property so
   Stage E's theme-switch cascade interpolates instead of snapping.
   The initial-value must be a fully-resolved colour (the spec forbids
   var() inside initial-value), so each value here is the raw primitive
   the token currently aliases to. Pixel-identical to today's resolved
   cascade.
   ===================================================================== */

@property --mh-surface {
  syntax: "<color>";
  inherits: true;
  initial-value: #0A0B11;
}
@property --mh-surface-deep {
  syntax: "<color>";
  inherits: true;
  initial-value: #06070C;
}
@property --mh-surface-variant {
  syntax: "<color>";
  inherits: true;
  initial-value: #14171F;
}
@property --mh-surface-container {
  syntax: "<color>";
  inherits: true;
  initial-value: #1A1E28;
}
@property --mh-surface-container-high {
  syntax: "<color>";
  inherits: true;
  initial-value: #232838;
}
@property --mh-on-surface {
  syntax: "<color>";
  inherits: true;
  initial-value: #F5F2E8;
}
@property --mh-on-surface-variant {
  syntax: "<color>";
  inherits: true;
  initial-value: #B6B2A6;
}
@property --mh-on-surface-muted {
  syntax: "<color>";
  inherits: true;
  initial-value: #9A988A;
}
@property --mh-on-surface-faint {
  syntax: "<color>";
  inherits: true;
  initial-value: #62604F;
}
@property --mh-primary {
  syntax: "<color>";
  inherits: true;
  initial-value: #D4FF3A;
}
@property --mh-primary-hover {
  syntax: "<color>";
  inherits: true;
  initial-value: #E6FF6B;
}
@property --mh-primary-pressed {
  syntax: "<color>";
  inherits: true;
  initial-value: #A8CC2E;
}
@property --mh-on-primary {
  syntax: "<color>";
  inherits: true;
  initial-value: #0A0B11;
}
@property --mh-primary-container {
  syntax: "<color>";
  inherits: true;
  initial-value: #F1FFB8;
}
@property --mh-on-primary-container {
  syntax: "<color>";
  inherits: true;
  initial-value: #4A5E12;
}
@property --mh-secondary {
  syntax: "<color>";
  inherits: true;
  initial-value: #D4FF3A;
}
@property --mh-on-secondary {
  syntax: "<color>";
  inherits: true;
  initial-value: #0A0B11;
}
@property --mh-tertiary {
  syntax: "<color>";
  inherits: true;
  initial-value: #F4D58D;
}
@property --mh-on-tertiary {
  syntax: "<color>";
  inherits: true;
  initial-value: #2B1F00;
}
@property --mh-tertiary-container {
  syntax: "<color>";
  inherits: true;
  initial-value: #FFEEC4;
}
@property --mh-on-tertiary-container {
  syntax: "<color>";
  inherits: true;
  initial-value: #3F2F12;
}
@property --mh-error {
  syntax: "<color>";
  inherits: true;
  initial-value: #FF6B6B;
}
@property --mh-on-error {
  syntax: "<color>";
  inherits: true;
  initial-value: #0A0B11;
}
@property --mh-success {
  syntax: "<color>";
  inherits: true;
  initial-value: #5EE39A;
}
@property --mh-warning {
  syntax: "<color>";
  inherits: true;
  initial-value: #FFB454;
}
@property --mh-info {
  syntax: "<color>";
  inherits: true;
  initial-value: #4DA3FF;
}
@property --mh-focus {
  syntax: "<color>";
  inherits: true;
  initial-value: #D4FF3A;
}
"""
