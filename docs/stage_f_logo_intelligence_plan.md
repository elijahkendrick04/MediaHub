# Stage F — Logo Intelligence: Thesis Plan

> Phase 1.6 Stage F of [`ROADMAP.md`](ROADMAP.md). After Stage E
> re-skins the entire chrome to a club's brand seed, the question
> becomes: how do *logos* — both MediaHub's own marks and the
> uploaded club logos — survive the theme transition without
> losing their identity?

## 1. Context

Stages A–E established the cascade: a single brand seed flows
through Stage B's HCT pipeline, lands in Stage C's static CSS
files as the `--mh-brand-seed` variable, Stage E animates it on
the "Looks right" cascade and persists the derived palette.

Stage F closes a gap that becomes visible the moment Stage E
runs: when the chrome re-skins to (say) a club's deep teal brand,
two visual contracts come under strain:

1. **The club's own uploaded logo** may have been designed
   against a specific background (most often white). Sit it
   directly on a teal surface and it might disappear, clash, or
   read upside-down. The Material You guidance — "ship a
   monochrome layer if you want it tintable" — applies: we don't
   auto-recolour third-party logos, but we DO control the surface
   they sit on.
2. **MediaHub's own marks** (the topnav badge, the footer mark)
   currently carry hard-coded hex fills (`#0A0B11`, `#F5F2E8`,
   `#D4FF3A`, `#F4D58D`). These were correct for the dark Podium
   After Dark theme but become wrong once `--mh-brand-seed`
   moves. They should bind to the cascade through
   `fill="currentColor"` + `fill="var(--mh-…)"` so the marks
   re-skin alongside the rest of the chrome.

The three roadmap sub-tasks address exactly these two problems:

- **F1**: Default to a neutral chip behind every uploaded logo.
  Safe-by-default: a white-ish rounded backplate that preserves
  the logo's design intent regardless of the surrounding surface.
- **F2**: Auto-detect "safe to drop chip" via an OKLCH ΔE2000 +
  APCA dual-polarity check. When the logo's dominant colour is
  perceptually distinct enough from the surface AND has enough
  contrast for visibility, render bare; otherwise chip.
- **F3**: Author MediaHub's own marks with `fill="currentColor"`;
  NEVER auto-inject on uploaded SVGs. Our own marks adapt
  cleanly; uploaded marks are served byte-for-byte unchanged
  with the chip wrapper handling theme interaction.

Critically, Stage F is **server-driven, not browser-driven**.
The decision of chip-vs-bare runs at request time on the active
profile's metadata (the `ai_dominant_colours` field that Stage B
already populates, or live extraction via `extract_seed()`).
There's no client-side colour math; the rendered HTML carries
the decision and the appropriate wrapper. This keeps the
behaviour predictable, testable, and FOUC-free.

## 2. Architecture overview

Three concrete changes plus a new theming module:

| Change | Where | What |
|---|---|---|
| New module | `src/mediahub/theming/logo_chip.py` | The decision algorithm: chip vs bare. Pure data, deterministic, no I/O. |
| Render helpers | New functions in `web.py` | `_logo_chip_html()` and `.mh-logo-chip` CSS class — the actual `<img>` wrapper. |
| Render sites | Existing `<img>` tags in `web.py` | Wrap every uploaded-logo render through the helper. |
| MH mark refactor | Topnav + footer SVGs in `_layout()` | Hard-coded fills → `currentColor` + `var(--mh-…)`. |

The cascade order Stage F adds is purely additive:
`THEME_BASE_CSS + THEME_FALLBACK_CSS + THEME_DERIVE_CSS +
THEME_CASCADE_CSS + (new: chip class)`. The new CSS is small (~10
lines) and integrates into `theme-base.css` rather than a new
file — it's a single utility class, not a new architectural tier.

## 3. F1 — Default to a neutral chip

### The chip class

A new utility class `.mh-logo-chip` in `theme-base.css`:

```css
.mh-logo-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  background: var(--mh-prim-neutral-0);
  border-radius: 6px;
  border: 1px solid var(--mh-outline-variant);
  box-shadow: var(--mh-elevation-1);
  /* Logos sit on a known-safe white-ish chip regardless of the
     surrounding surface. The 8/12 padding gives 1× the logo's
     typical clear-space; the radius matches the platform's
     standard card radius. */
}

.mh-logo-chip > img,
.mh-logo-chip > svg {
  display: block;
  max-height: 96px;
  max-width: 100%;
  object-fit: contain;
}
```

Background uses `var(--mh-prim-neutral-0)` (pure white) by
default. `--mh-outline-variant` for the chip edge — same colour
that bounds other neutral surfaces in the design. `--mh-elevation-1`
for a subtle lift so the chip reads as foreground rather than
hole.

### The render helper

```python
def _logo_chip_html(
    src_url: str,
    alt: str = "",
    *,
    height: int = 96,
    dominant_hex: Optional[str] = None,
    force_chip: bool = False,
) -> str:
    """Render an uploaded logo with a neutral chip by default.

    Stage F1: every uploaded logo sits on a near-white chip so its
    design intent is preserved regardless of the surface colour.

    Stage F2: if dominant_hex is provided and the decision algorithm
    says it's safe to drop the chip, render bare. Pass force_chip=True
    to bypass the F2 detection and always chip (used for thumbnails,
    grids, etc. where uniformity matters more than visual lightness).
    """
```

### Render sites updated

Three existing `<img>` tags get migrated to call `_logo_chip_html`:

1. **Line 10797** — the "Detected logo" preview on the brand-DNA
   capture card. This is the most-seen logo render in the app
   and the highest-risk one for theme conflict.
2. **Line 11171** — the profile card on `/sign-in`. Logos here
   represent organisations; they sit alongside text and need
   consistent presentation across orgs.
3. **Line 11567** — the logos grid on `/organisation/setup`. The
   chip background was already migrated in Stage A
   (`var(--mh-prim-neutral-0)`); Stage F formalises it as a
   `.mh-logo-chip` class so the styling is one source of truth.

## 4. F2 — Auto-detect "safe to drop chip"

The F2 promise is auto-detection: when the logo's dominant
colour is *already* visually distinct from the surface, the chip
is visual noise. Drop it and let the logo breathe.

### The decision algorithm

```python
@dataclass
class LogoChipDecision:
    mode: Literal["chip", "bare"]
    chip_color: str             # the chip background (only used when chip)
    delta_e_2000: float          # perceptual distance, dominant vs surface
    apca_lc: float               # signed APCA Lc, dominant on surface
    apca_abs: float              # |Lc|
    reasoning: str               # human-readable for audit/explainability

def decide_logo_chip(
    dominant_hex: str,
    surface_hex: str,
    *,
    de_min: float = 15.0,
    apca_min: float = 45.0,
    chip_color: str = "#FFFFFF",
) -> LogoChipDecision:
    """Decide chip vs bare via two gates that BOTH must pass for bare:

      Gate 1 (perceptual distinctness):
        ΔE2000(dominant, surface) >= de_min
        Below 15 the logo's dominant colour is too close to the
        surface to read cleanly — chip.

      Gate 2 (APCA dual-polarity contrast):
        |APCA Lc(dominant, surface)| >= apca_min
        Below 45 the logo's edges blur into the surface even if
        the hue differs — chip. The 45 floor is APCA's "UI element"
        threshold (large-text Bronze) and matches Stage B's
        contrast.py default.

    Either gate failing → chip. The chip_color (default white) is
    fixed; Stage J may later choose chip colour based on logo
    polarity (light vs dark logo).
    """
```

### The "dual-polarity" interpretation

APCA Lc is a signed value: positive for dark text on light
background, negative for light text on dark background. The
roadmap's phrase "APCA dual-polarity check" means we test the
absolute magnitude `|Lc|` against the threshold — regardless of
whether the logo is darker or lighter than the surface. A
positive Lc of 60 (dark logo on light surface) and a negative
Lc of -60 (light logo on dark surface) both clear the bar.

This handles both common logo polarities — dark logos designed
for white papers AND light logos designed for dark themes —
with one check.

### Sourcing `dominant_hex`

Three options, in preference order:

1. **`ai_dominant_colours[0]`** from the logo's metadata
   (`brand/logos.py`). Stage B already populates this via the
   AI vision pass at upload time. Cheap, cached, accurate.
2. **`extract_seed(logo_bytes)`** at render time. Re-runs
   Stage B's `seed_extract.extract_seed()` over the logo's raw
   bytes. Accurate but slow (~50–200 ms per call); used as
   fallback only.
3. **`safe_primary()` from BrandKit** if neither of the above
   yields a hex. Conservative default: assume the logo's
   dominant colour matches the brand primary.

For Stage F's first cut, we use option 1 with option 3 as the
fallback. Option 2 is implemented but unused; Stage H's "Why
does my theme look like this?" panel may surface it as an
opt-in re-extract button.

### Sourcing `surface_hex`

The active surface colour is the resolved value of the
tier-2 `--mh-surface` token for the active theme. For Stage F's
dark-only default theme, that's `#0A0B11`. For a club whose
derived theme produces a different surface (still dark, but
slightly tinted in their brand hue), the value comes from
their `ClubProfile.brand_kit.derived_palette['roles']['dark']['surface']`.

The helper does the lookup once per render with a tiny `try/except`
that defaults to `#0A0B11` so a malformed profile never breaks
the page.

## 5. F3 — MediaHub's own marks via `currentColor`

### The current state

The topnav SVG at `web.py:3424–3434`:

```xml
<svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
  <rect x="0.5" y="0.5" width="31" height="31" rx="2"
        fill="#0A0B11" stroke="#262B33" stroke-width="1"/>
  <rect x="6"  y="20" width="5" height="7"  fill="#F5F2E8" opacity="0.55"/>
  <rect x="13.5" y="9"  width="5" height="18" fill="#D4FF3A"/>
  <rect x="21" y="14" width="5" height="13" fill="#F4D58D"/>
  <line x1="4" y1="27.5" x2="28" y2="27.5"
        stroke="#D4FF3A" stroke-width="1"/>
</svg>
```

Five hard-coded fills, all matching the Stage A palette but
none of which adapt to a re-skinned chrome. When a club's seed
shifts the chrome from lane yellow to teal, this mark stays
yellow — wrong.

### The refactor

```xml
<svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
  <!-- Backplate: the chrome surface, with an outline that follows
       the cascade -->
  <rect x="0.5" y="0.5" width="31" height="31" rx="2"
        fill="var(--mh-surface)" stroke="var(--mh-outline-rule)" stroke-width="1"/>
  <!-- Paper-cream bar: ink-on-surface, follows the cascade via currentColor -->
  <rect x="6"  y="20" width="5" height="7"  fill="currentColor" opacity="0.55"/>
  <!-- Brand bar: always the primary -->
  <rect x="13.5" y="9"  width="5" height="18" fill="var(--mh-primary)"/>
  <!-- Tertiary bar: always the medal tertiary -->
  <rect x="21" y="14" width="5" height="13" fill="var(--mh-tertiary)"/>
  <!-- Baseline: brand primary stroke -->
  <line x1="4" y1="27.5" x2="28" y2="27.5"
        stroke="var(--mh-primary)" stroke-width="1"/>
</svg>
```

Five fills:

- **Backplate**: `var(--mh-surface)` so it follows the chrome.
  Stroke uses `var(--mh-outline-rule)` — same as Stage C.
- **Paper-cream bar**: `currentColor`. The enclosing
  `header.topnav .brand` link has `color: var(--ink)`, so this
  bar inherits the ink colour and adapts whenever ink changes.
- **Brand bar**: `var(--mh-primary)`. Always the brand primary
  — the most visible bar in the mark, semantically "this is
  the brand colour".
- **Tertiary bar**: `var(--mh-tertiary)`. The medal-gold
  tertiary slot — semantically "this is the achievement
  colour".
- **Baseline stroke**: `var(--mh-primary)`. Reinforces the
  brand colour as the foundation of the mark.

When `--mh-brand-seed` changes (Stage E's cascade), the brand
and tertiary bars interpolate via Stage C's `oklch(from
var(--mh-brand-seed) …)` chain. When `--ink` changes (Stage D),
the paper-cream bar follows via `currentColor`. When the
surface theme changes, the backplate follows. The mark is now
a first-class theme-aware element.

### The footer SVG

The footer mark at `web.py:3460–3465` already uses
`fill="currentColor"`:

```xml
<rect x="6"  y="20" width="5" height="7"  rx="1.2"
      fill="currentColor" opacity="0.45"/>
<rect x="13.5" y="14" width="5" height="13" rx="1.2"
      fill="currentColor" opacity="0.70"/>
<rect x="21" y="8"  width="5" height="19" rx="1.2"
      fill="currentColor"/>
```

This is already Stage F3 compliant — the bars take the
enclosing `.mh-footer-brand` color, which is `var(--ink)`. No
change needed; Stage F just verifies it remains so via a test.

### The non-rule for uploaded SVGs

For uploaded SVGs (the `brand/logos.py` files), MediaHub
**never** modifies the markup. The serving route at
`organisation_setup_logo_serve` returns the file's raw bytes
via `send_from_directory`. There's no `currentColor` injection,
no fill rewriting, no transform. If a club wants their logo to
adapt, they ship an SVG authored with `currentColor` themselves
(per the Material You guidance: "ship a monochrome layer if
you want it tintable"). MediaHub's job is to render the chip
wrapper and trust the upload.

A new test asserts this invariant: a fixture SVG with
`fill="#FF0000"` round-trips through the upload + serve cycle
with bytes unchanged.

## 6. Code organisation

### `src/mediahub/theming/logo_chip.py` — the decision logic

Pure-data module. Imports `coloraide` for ΔE2000 and the local
`contrast.py` for APCA. Exports `LogoChipDecision` and
`decide_logo_chip()`. ~80 lines.

### `src/mediahub/web/web.py` — the render helpers

Two additions:
1. `_logo_chip_html()` — wraps an `<img>` in a `.mh-logo-chip`
   if the decision says chip, returns the bare `<img>` if bare.
2. Modifications to the three existing `<img>` render sites to
   call the helper.

Plus the SVG mark refactor in `_layout()`.

### `src/mediahub/web/static/theme/theme-base.css` — the chip CSS

Add the `.mh-logo-chip` utility class. ~12 lines.

## 7. Backwards compatibility

Stage F is purely additive:
- The new `.mh-logo-chip` class is opt-in via the helper; existing
  inline-style logo renders keep working.
- The SVG mark refactor changes hex values to `var()` references
  but resolves to the same pixels under the default seed (lane
  yellow → `var(--mh-primary)` = `#D4FF3A`, identical).
- The new module under `theming/` has zero impact on Stage B's
  existing `derive_theme` pipeline.

For users with `prefers-reduced-motion` set, the chip transition
(if any) inherits the global `transition: none !important`
override from the responsive-guardrails layer. Stage F adds no
new motion.

## 8. Test strategy

Three new test files:

### `tests/theming/test_logo_chip.py`

Pure-logic tests for `decide_logo_chip()`:

- Dominant black on white surface → bare (huge ΔE + APCA)
- Dominant white on white surface → chip (low ΔE)
- Dominant near-surface colour → chip (low ΔE even with
  arbitrary APCA)
- Dominant high contrast but small ΔE → chip (one gate fails)
- Dominant high ΔE but low APCA → chip (other gate fails)
- Boundary: ΔE exactly at threshold → chip (strict >=)
- Boundary: APCA exactly at threshold → chip
- Reasoning string is non-empty and mentions both gates

### `tests/test_logo_render_sites.py`

Integration tests for the three `<img>` render sites:

- After uploading a logo to a profile, the `/organisation/setup`
  page renders it inside `.mh-logo-chip`
- The "Detected logo" preview on the brand-DNA capture card
  renders inside `.mh-logo-chip`
- The sign-in profile card renders the logo inside
  `.mh-logo-chip`
- For a profile with NO logo, no `.mh-logo-chip` element
  appears (clean fallback)
- The chip's `background` resolves via the cascade to a
  light-neutral colour

### `tests/test_mediahub_mark_theming.py`

Contract tests for F3:

- The topnav SVG no longer contains the hard-coded `#0A0B11`,
  `#F5F2E8`, `#D4FF3A`, `#F4D58D` fills
- The topnav SVG contains `fill="currentColor"` for the
  paper-cream bar
- The topnav SVG contains `fill="var(--mh-primary)"` for the
  brand bar
- The topnav SVG contains `fill="var(--mh-tertiary)"` for the
  tertiary bar
- The topnav SVG contains `fill="var(--mh-surface)"` for the
  backplate
- The footer SVG remains `currentColor`-driven (Stage F3 audit
  pin)
- The uploaded-logo serve route preserves bytes
  exactly — a fixture SVG with `fill="#FF0000"` round-trips
  unchanged

## 9. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| Chip background looks wrong against a teal-brand surface | Low | Always-white chip is the design-system default (Adobe Spectrum, IBM Carbon, BBC). Light chip on any dark surface produces a recognisable card; on a light surface the elevation shadow keeps the chip visible. |
| Decision algorithm fails for monochrome logos | Medium | Algorithm explicitly checks |APCA Lc|, which is sign-agnostic. Tested against both polarities. |
| MediaHub SVG mark pixel-drift after refactor | None | `var(--mh-primary)` defaults to `#D4FF3A` = today's lane yellow. Test asserts pixel parity. |
| Stage E cascade animation breaks the SVG | Low | SVG `fill="var()"` re-evaluates per frame just like CSS — the bars interpolate alongside everything else. |
| Logo metadata missing for older profiles | Medium | Helper has 3-tier fallback (metadata → re-extract → safe_primary). Test exercises every branch. |
| Re-extract slowness on render | Low | Skipped at request time — only metadata used unless explicitly invoked. |
| Auto-injection on uploaded SVGs (the thing F3 forbids) | None | The serve route uses `send_from_directory` which is a pure file passthrough. Test asserts byte equality. |
| Chip wraps a non-logo image incorrectly | Low | Helper is opt-in; callers only invoke it for logo render sites. |

## 10. Audit plan (10 subtasks)

After implementation:

1. `theming/logo_chip.py` module exists and imports cleanly.
2. `decide_logo_chip()` produces a `LogoChipDecision` for canonical
   inputs (black on white, white on white).
3. The `.mh-logo-chip` CSS class is in `theme-base.css`.
4. `_logo_chip_html()` helper renders a chip-wrapped `<img>` for
   the default case.
5. The "Detected logo" render site (web.py ~10797) uses the
   helper, not the raw `<img>` form.
6. The MediaHub topnav SVG contains the four `var(--mh-…)`
   refs and the `currentColor` ref.
7. The topnav SVG no longer contains `#D4FF3A` as a literal
   `fill=` attribute (it lives only in token-definition lines).
8. Uploaded SVG bytes round-trip through the serve route
   unchanged (byte-for-byte).
9. Stage A's 161 tests still pass.
10. Stage E's 30 tests still pass.

## 11. Verify plan (10 subtasks)

After audit:

1. App boots; `/status` returns HTTP 200.
2. Rendered HTML of `/status` carries the refactored topnav SVG
   (the `var(--mh-primary)` and `currentColor` markers).
3. With an active profile that has an uploaded logo, the
   `/organisation/setup` page renders the logo grid with chip
   styling.
4. With an active profile that has a `brand_logo_url`,
   `/organisation/setup` renders the "Detected logo" preview
   wrapped in `.mh-logo-chip`.
5. The chip's resolved CSS `background` is the expected
   light-neutral colour (`#FFFFFF` via `--mh-prim-neutral-0`).
6. The cascade-animation rules from Stage E (`@view-transition`,
   `:root` transition) still apply.
7. POST `/api/organisation/finalise` still works end-to-end
   (Stage E integration unbroken).
8. The full pytest suite still passes (Stage A + B + C + E + new
   F tests), zero new structural failures.
9. The `.mh-logo-chip` styles obey reduced-motion (no animation
   added by Stage F).
10. The MH mark's brand-yellow bar interpolates correctly when
    `--mh-brand-seed` changes (manual computational check via
    coloraide).

## 12. Out of scope (deferred)

- Auto-recolouring uploaded logos (e.g. injecting `currentColor`
  into multi-fill SVGs). The Material You "ship a monochrome
  asset" guidance prevails — MediaHub never modifies uploaded
  marks.
- Per-club chip colour overrides (Stage H "Why does my theme
  look like this?" UI may add an opt-in).
- Choosing chip polarity (dark chip for light logos, light chip
  for dark logos). Stage F always chips with light neutral;
  Stage J may revisit.
- Generating new logos from a brand seed. Out of scope for the
  Adaptive Theming Engine entirely — that's the achievement
  engine's job (motion graphics + Remotion).
- Logo-colour quantisation for tier-3 component tokens. Stage F
  reads the existing `ai_dominant_colours` metadata; it does
  not re-extract or re-cluster.
- A dedicated logo-rendering Remotion composition. Stage G's
  motion/email/static graphic share-JSON work covers this when
  it lands.

Stage F closes the visible chrome loop. After it, the entire
chrome — chrome surfaces, button accents, hover tints, focus
rings, the MediaHub mark itself, AND the uploaded club logo — all
move coherently when a club's brand seed changes. The result is
the "feels like our own" experience the Phase 1.6 brief opened
with: clubs see their identity in every pixel, not just the
generated content.
