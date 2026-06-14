# MediaHub Theming Reference

> The canonical reference for the **Adaptive Theming Engine**
> shipped in Phase 1.6 (Stages A–J). Operators, contributors,
> and future maintainers: this is the one document you need
> to understand the whole engine.

## 1. What is the Adaptive Theming Engine?

When a club uploads their brand and clicks *"Looks right —
start creating"*, MediaHub re-skins every page — chrome,
buttons, focus rings, ink, borders, hover tints, status
colours, the MediaHub mark itself — to fit that club's brand.
The cascade animates the change smoothly. The same theme flows
through web pages, Remotion motion videos, outbound email
HTML, and Playwright-rendered static graphics. Zero drift
across surfaces.

The engine works for *any* brand seed — fluorescent yellow,
muddy dark green, pure primary red. When a seed conflicts with
our locked status anchors under colour-vision deficiency, a
constraint-satisfaction repair loop rotates the status hue and
explains the change to the user. Every decision is auditable.

## 2. Architecture at a glance

```
   ┌────────────────────────┐
   │  Club's brand seed     │  (hex, SVG logo, or raster)
   │  e.g. "#A30D2D"        │
   └───────────┬────────────┘
               │
               ▼
   ┌────────────────────────┐
   │  Stage B colour-science│  HCT seed → 9 tonal ramps × 13
   │  pipeline              │  tones → ~30 MD3 role tokens →
   │  (mediahub.theming)    │  APCA + WCAG + ΔE + CVD gates
   └───────────┬────────────┘  → repair loop
               │
               ▼
   ┌────────────────────────────────────┐
   │  ClubProfile.brand_kit.derived_palette │  (in-memory cache)
   └───────────┬────────────────────────┘
               │ Stage G hook
               ▼
   ┌──────────────────────────────────┐
   │  DATA_DIR/themes/<profile_id>.json│  (on-disk source of truth)
   │  — DTCG-format dict —             │
   └─┬───────┬────────┬─────────┬──────┘
     │       │        │         │
     ▼       ▼        ▼         ▼
   web     motion   email     static graphics
  (Stage    (Stage   (Stage    (Stage G4)
   C-F)     G2)      G3)
```

The seven seed variables flow through one engine. Four
consumer surfaces read the same JSON. The four CSS files in
`src/mediahub/web/static/theme/` derive ~55 shades at runtime
from those seven seeds.

## 3. The role-token vocabulary

The engine's public API is a Material 3-style three-tier
hierarchy of CSS custom properties.

### Tier 1 — Primitives (`--mh-prim-*`)

Raw values. Brand, tertiary, neutral, and four status families
each get a 13-tone OKLCH ramp (tones 0, 10, 20, 30, 40, 50, 60,
70, 80, 90, 95, 99, 100). Never used directly by application
CSS — they're the building blocks the semantic tier composes
from.

Examples: `--mh-prim-brand-40`, `--mh-prim-tertiary-80`,
`--mh-prim-error-50`.

### Tier 2 — Semantic role tokens (`--mh-*`)

The 25+ Material 3 role tokens you actually consume:

| Token | Purpose | Default value (lane yellow seed) |
|---|---|---|
| `--mh-surface` | Page background | derived |
| `--mh-surface-deep` | Deepest dark surface | derived |
| `--mh-surface-variant` | Raised cards | derived |
| `--mh-surface-container` | Highest-elevation card | derived |
| `--mh-surface-container-high` | Active/hover card | derived |
| `--mh-on-surface` | Primary text on surface | derived |
| `--mh-on-surface-variant` | Secondary text (9.27:1 on bg) | derived |
| `--mh-on-surface-muted` | Tertiary text (5.69:1 on bg) | derived |
| `--mh-on-surface-faint` | Decorative-only text (3.14:1) | derived |
| `--mh-primary` | Brand accent (CTAs, links, focus) | `var(--mh-prim-brand-40)` |
| `--mh-primary-hover` | Primary hover-state tint | derived |
| `--mh-primary-pressed` | Primary active/pressed tint | derived |
| `--mh-on-primary` | Text on primary fill | `var(--mh-prim-brand-100)` |
| `--mh-primary-container` | Tinted-primary surface | derived |
| `--mh-on-primary-container` | Text on primary-container | derived |
| `--mh-secondary` | Secondary accent (less weight) | derived |
| `--mh-on-secondary` | Text on secondary | derived |
| `--mh-tertiary` | Medal/achievement accent | `var(--mh-prim-tertiary-40)` |
| `--mh-on-tertiary` | Text on tertiary | derived |
| `--mh-tertiary-container` | Tinted-tertiary surface | derived |
| `--mh-on-tertiary-container` | Text on tertiary-container | derived |
| `--mh-error` | Danger / failure | `var(--mh-prim-error-40)` |
| `--mh-on-error` | Text on error | derived |
| `--mh-success` | Approved / passing | `var(--mh-prim-success-40)` |
| `--mh-warning` | Caution / amber | `var(--mh-prim-warning-40)` |
| `--mh-info` | Informational | `var(--mh-prim-info-40)` |
| `--mh-outline` | Visible borders | `rgba(245,242,232,0.14)` |
| `--mh-outline-variant` | Faint hairlines | `rgba(245,242,232,0.06)` |
| `--mh-outline-rule` | 1-pixel rules | `rgba(245,242,232,0.10)` |
| `--mh-focus` | Focus ring | `var(--mh-primary)` |
| `--mh-elevation-1` | Subtle drop | composite shadow |
| `--mh-elevation-2` | Card drop | composite shadow |
| `--mh-elevation-3` | Modal drop | composite shadow |

### Light & dark mode (Stage D — UI 1.23)

MediaHub is **dark-first** but ships a real **light** palette. Every
surface / text / outline role above is declared
`light-dark(<light>, <dark>)` in `theme-base.css`, so the *same* token
resolves to a warm-paper value in light and the pit-wall value in dark.
The light branch is the inverse of the dark ramp — page = paper-cream
(`neutral-50`), cards = white (`neutral-0`), text = deep ink
(`neutral-900..500`) — and clears WCAG AA on both the page and white
cards (`tests/test_theme_toggle.py` pins the contrast). The dark branch
is byte-identical to Stage C, so **dark mode does not move a pixel**.

Three rules make this work without per-component effort:

1. **`color-scheme` drives everything.** `light-dark()` resolves against
   the element's used `color-scheme`. The default
   (`responsive_guardrails.py`) is `color-scheme: dark light` —
   dark-first, but a visitor whose OS prefers light gets the light
   branch automatically. No selector, no media query, no JS needed for
   the colour swap.
2. **The in-app toggle just sets `color-scheme`.** The masthead control
   (Light · System · Dark) writes the choice to `localStorage['mh-theme']`
   and, for an explicit pick, forces an inline `color-scheme` onto
   `<html>` (which beats the stylesheet). A `<head>` boot script applies
   the saved choice **before first paint** (no flash). "System" clears
   the override and follows the OS.
3. **Lane-yellow is a fill, not text, in light.** Yellow-on-paper is
   illegible, so links (`--mh-link`) and the focus ring (`--mh-focus`)
   darken to the olive end of the brand ramp in the light branch, while
   button *fills* stay lane-yellow (with dark `--mh-on-primary` text)
   in both modes. The medal/tertiary accent steps to a richer gold so
   it holds its weight on white.

When you add chrome that hardcodes a dark colour (a scrim, a tint), wrap
it in `light-dark(<light>, <dark>)` so it flips too — keep the dark
branch byte-identical to avoid drifting dark mode.

### Tier 3 — Component tokens

Deliberately deferred per Nathan Curtis's *"introduce only when
3+ components share the value"* rule. Phase 1.6 ships zero
component tokens. Component-specific overrides live as inline
styles or scoped class declarations until the threshold is met.

## 4. The seven seed variables

These are the *inputs* to the engine. Stage J1's feature flag
controls whether the per-request override fires; when it does,
it sets `--mh-brand-seed` only — the other six stay at their
static defaults declared in `theme-base.css`.

| Variable | Purpose | Static default |
|---|---|---|
| `--mh-brand-seed` | The user-supplied brand colour | `#D4FF3A` (lane yellow) |
| `--mh-tertiary-seed` | Medal/achievement accent | `#F4D58D` (medal gold) |
| `--mh-neutral-seed` | Warm-cream neutral anchor | `#F5F2E8` |
| `--mh-error-seed` | Locked: WCAG 1.4.1 red family | `#FF6B6B` |
| `--mh-success-seed` | Locked: green family | `#5EE39A` |
| `--mh-warning-seed` | Locked: amber family | `#FFB454` |
| `--mh-info-seed` | Locked: blue family | `#4DA3FF` |

The four status seeds are **never** moved by the brand. The
repair loop (Stage B) may rotate them by up to ±30° when a
brand-vs-status collision threatens CVD distinguishability —
but the rotation is logged, surfaced in the Stage H3 warning
callout, and recorded in the audit trail.

## 5. The cascade order

```
1. theme-base.css       — primitives + role tokens + @property
2. theme-fallback.css   — Safari ≤ 16.3 fallback (inside @supports not)
3. theme-derive.css     — modern oklch(from var(--mh-…-seed) …)
                          (inside @supports)
4. theme-cascade.css    — @view-transition + :root transition +
                          prefers-reduced-motion
5. BASE_CSS             — global app styles
6. responsive_guardrails.py — viewport, fluid type, container
                              queries (concat'd at end)
7. <style id="mh-theme-seed"> — per-request override (Stages D-J)
```

The runtime CSS engine resolves the cascade. The `@supports
(color: oklch(from red l c h))` gate makes modern browsers run
the relative-colour derivation; Safari ≤ 16.3 falls through to
the static hex values byte-identical to the pre-Stage-C
palette.

## 6. The four consumer surfaces

The same theme JSON drives all four surfaces. The role-mapping
convention in `mediahub.theming.theme_store`:

| Surface | Scheme | `primary ←` |
|---|---|---|
| Web (cascade) | both via `light-dark()` | `--mh-primary` |
| Motion (Remotion) | dark | `roles.dark.primary` |
| Email | light | `roles.light.primary` |
| Static graphics | light | `roles.light.primary` |

Motion uses the **dark** scheme because video output benefits
from higher saturation. Email + static graphics use **light**
because they render against white backgrounds (white email
bodies, white social-feed chrome on mobile).

Each consumer calls its dedicated helper:

```python
from mediahub.theming.theme_store import (
    palette_for_motion,  # dark scheme
    palette_for_email,   # light scheme
    palette_for_static,  # light scheme
)
```

Each returns `{primary, secondary, accent, scheme, source}` so
downstream code is consumer-agnostic.

## 7. Override patterns

Three operator-facing override patterns, in increasing scope:

### Per-organisation — through brand-kit setup

A club uploads their brand (or types a hex) at
`/organisation/setup`. The Stage E "Looks right" button calls
`POST /api/organisation/finalise` which writes the derived
palette to `DATA_DIR/themes/<profile_id>.json`. Every page
rendered while that profile is the active session loads the
per-profile theme.

This is the *normal* override path — every club uses it.

### Per-deployment — by editing `theme-base.css`

Static defaults live in
`src/mediahub/web/static/theme/theme-base.css`. Edit the
`:root { --mh-brand-seed: …; }` declaration to change the
deployment's *fallback* (when no profile is active).

This is the path for a forked MediaHub instance with a
different visual identity from the upstream. Re-running the
Stage I snapshot regenerator (`python
scripts/update_theme_snapshots.py`) after the edit captures
any algorithmic effects of the new default.

### Per-element — inline `style=""`

Any element can opt out of the cascade with an inline `style`.
This is the escape hatch for genuinely-one-off treatments
(sponsor banners with a sponsor-provided hex, third-party
embeds, etc.).

The Stage A audit captured how many existing inline-style hex
literals remained; the cutover (Stage J) eliminated all but
~14 deliberate ones (raw black for video backgrounds, etc.).

## 8. Feature flags

| Flag | Default | Purpose |
|---|---|---|
| `MEDIAHUB_ADAPTIVE_THEME` | `1` (enabled) | Stage J1 cutover safety lever. Set to `0` / `false` / `off` / `no` to disable the per-request seed injection — every page renders with the static cascade as if Stages D-J had never shipped. The Stage H audit panel and Stage G theme-store keep working. |
| `MEDIAHUB_SKIP_BROWSER_TESTS` | unset (run) | Skip the Playwright end-to-end test in environments without chromium-1194. Auto-detected via the Playwright executable path. |
| `MEDIAHUB_SKIP_MOTION_TESTS` | unset (run) | Skip the Remotion integration tests in environments without Node. |

## 9. The audit + repair pipeline

Every palette derivation flows through `mediahub.theming.
quality.audit_palette()`, which runs five gates:

1. **APCA Lc** — Perceptual contrast (Andrew Somers' SAPC-APCA
   v0.1.9). `|Lc| ≥ 60` for body-text role pairs;
   `|Lc| ≥ 30` for UI elements.
2. **WCAG 2.x ratio** — Legal contrast threshold. Body text
   ≥ 4.5:1; UI ≥ 3:1.
3. **CIEDE2000 adjacent-tone ΔE** — Radix Colors' working
   "clearly perceptible step" floor of 5.
4. **CIEDE2000 brand-vs-status ΔE** — Hard floor 15, soft
   floor 25. Keeps the brand from collapsing into the locked
   status anchors.
5. **Machado-simulated CVD ΔE** — Hard floor 3 (just above
   the JND limit), soft floor 10 (ColorBrewer's categorical-
   palette floor). Verifies the brand stays distinct from the
   status anchors under deuteranopia / protanopia /
   tritanopia.

Plus a non-gate harmonic check:

6. **Cohen-Or 2006 harmonic template fit** — Reports which of
   the seven hue-band templates fits best, with rotation +
   energy. Lower energy = more harmonic. Aesthetic, not
   accessibility — never produces an error.

If any *hard* gate fails (categories 1, 4, 5), the repair loop
in `mediahub.theming.repair` rotates the affected status anchor
hue ±8° / ±18° / ±30° until the gate passes. The brand seed
itself never moves; only status anchors. Every step is logged
into `decision_trace`. If repair fires, the Stage H3 callout
explains the change in plain English.

## 10. Adding a new role token

If a new role appears in 3+ components and needs to be themed:

1. Add the token declaration to `theme-base.css`:
   ```css
   --mh-new-role: light-dark(var(--mh-prim-X-Y),
                              var(--mh-prim-X-Z));
   ```
2. Add the matching `@property` registration:
   ```css
   @property --mh-new-role {
     syntax: "<color>";
     inherits: true;
     initial-value: #default;
   }
   ```
3. Add the role to `tests/test_theme_tokens.py::_TIER2_ROLE_TOKENS`.
4. Run the Stage I snapshot regenerator to capture the new
   role's resolved values across all 30 seeds.
5. Document the new token in section 3 of this file.

## 11. Adding a new seed to the snapshot catalogue

```python
# tests/theming/seeds_catalogue.py
SEEDS_CATALOGUE = [
    ...,
    ("#NEWHEX", "human-readable label", "common"),
]
```

Then:

```bash
$ python scripts/update_theme_snapshots.py
$ git add tests/theming/snapshots/newhex.json
$ git commit
```

The new seed automatically gains:
- A golden-master snapshot regression test (Stage I)
- Coverage in the regenerator-determinism test
- An entry in the per-category coverage assertions

No further code changes needed.

## 12. Academic citations

The engine is grounded in published colour-science. Each
citation matches a specific algorithm choice in the code:

- **OKLCH colour space** — Björn Ottosson (2020),
  [*"A perceptual color space for image processing"*](https://bottosson.github.io/posts/oklab/).
  The basis for our hue-preserving tone derivations. Stage C
  uses `oklch(from var(--mh-brand-seed) …)` precisely because
  OKLCH varies lightness without shifting hue.

- **CIEDE2000 colour-difference formula** — Sharma, Wu & Dalal
  (2005),
  [*"The CIEDE2000 Color-Difference Formula"*](https://www2.ece.rochester.edu/~gsharma/ciede2000/).
  Used by the brand-vs-status distance gate (Stage B) and the
  adjacent-tone gate.

- **APCA / SAPC contrast** — Andrew Somers,
  [SAPC-APCA v0.1.9](https://github.com/Myndex/SAPC-APCA).
  The perceptual contrast model that replaces WCAG 2.x's
  broken luminance-ratio formula. Stage B's `contrast.py`
  implements the spec from scratch (~50 lines); Stage H's
  audit panel surfaces both Lc and ratio side-by-side because
  WCAG 2.x remains the legal threshold even though APCA is
  the better model.

- **Material 3 dynamic colour / HCT** — Google Material
  Foundation,
  [*Material 3 Dynamic Color*](https://m3.material.io/styles/color/dynamic/overview).
  Stage B uses the
  [`materialyoucolor` PyPI package](https://pypi.org/project/materialyoucolor/)
  — the maintained Python port of `material-color-utilities`
  — for HCT seed → tonal palette derivation.

- **Machado CVD simulation** — Machado, Oliveira & Fernandes
  (2009), IEEE TVCG,
  [*"A Physiologically-based Model for Simulation of Color
  Vision Deficiency"*](https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html).
  The 3×3 matrices Chromium ships natively for the DevTools
  vision-deficiency simulator. Stage B embeds the matrices and
  computes simulated ΔE2000 for brand-vs-status pairs.

- **Cohen-Or harmonic templates** — Cohen-Or, Sorkine, Gal,
  Leyvand & Xu (SIGGRAPH 2006),
  [*"Color Harmonization"*](https://igl.ethz.ch/projects/color-harmonization/).
  Stage H1 implements the seven hue templates (i / V / L / I /
  T / Y / X) and finds the best fit via 7 × 72 rotation search.

- **Constrained palette repair in OKLCH** — Lalitha A R (2025),
  [*"Perceptually-Minimal Color Optimization for Web
  Accessibility"*](https://arxiv.org/abs/2512.05067) (arXiv
  2512.05067). The repair loop's "perturb L and C first, hue
  last" strategy follows this paper's three-phase
  constraint-satisfaction approach.

- **Status colour semantics across cultures** — Aslam (2006);
  Elliot & Maier (2007); Palmer & Schloss (2010); WCAG 1.4.1.
  Why the four status anchors are *locked* by hue family —
  red for danger, green for success, amber for warning, blue
  for info — even when the brand seed conflicts.

- **Web design tokens** — W3C Design Tokens Community Group,
  [DTCG Format](https://www.designtokens.org/TR/drafts/format/).
  The schema for the per-profile `derived_palette` JSON.

- **CSS spec primitives** — W3C CSS Color Module Level 4
  (gamut mapping), Level 5 (`color-mix`, relative-colour
  syntax), CSS Properties & Values API Level 1 (`@property`),
  View Transitions API. The browser-side primitives Stage C-E
  rely on.

- **Characterisation testing** — Michael Feathers (2004),
  *"Working Effectively with Legacy Code"*. The pattern Stage
  I's 30-seed golden-master regression catalogue follows.

## 13. Phase 1.6 stage index

The detailed per-stage thesis plans (A–J) that documented this work
have been consolidated — **this file is now the single canonical record
of the theming architecture and its stages**. The stage breakdown and
acceptance criteria live in [`docs/ROADMAP_BUILT.md`](ROADMAP_BUILT.md) §1.6
(Appendix C — the theming engine is shipped, so its record moved to the built file).
