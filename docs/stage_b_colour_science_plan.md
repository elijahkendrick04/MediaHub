# Stage B — Colour-Science Package: Thesis Plan

> Phase 1.6 Stage B of [`ROADMAP.md`](ROADMAP.md). Builds on Stage A's
> token foundation (`src/mediahub/web/theme_tokens.py`,
> `tests/test_theme_tokens.py`). No website behaviour change yet — the
> derived palette is computed and persisted but not consumed by the
> CSS pipeline until Stage D.

## 1. Context and motivation

Stage A ratified MediaHub's existing "Podium After Dark" palette as a
3-tier DTCG-format vocabulary. Every legacy token (`--bg`, `--ink`,
`--lane`, `--medal`, `--accent`, `--panel`, …) now resolves through
~25 Material-3-style semantic role tokens (`--mh-surface`,
`--mh-on-surface`, `--mh-primary`, `--mh-tertiary`, …) which in turn
reference a set of hand-coded tier-1 primitives. The 27 role tokens
are `@property`-registered so they animate. The vocabulary is in
place; the pixels are unchanged.

**Stage B builds the engine that makes those tier-1 primitives
*derivable* from a single brand seed.** Given any hex value (or a
logo from which a seed is extracted), Stage B produces:

- A `DerivedPalette`: five 13-tone tonal palettes (primary, secondary,
  tertiary, neutral, neutral-variant) plus four status anchor
  palettes (error, success, warning, info), each carrying its HCT
  hue/chroma anchor.
- A `RoleScheme` for light and dark themes — ~30 Material 3 role
  tokens (`primary`, `onPrimary`, `primaryContainer`,
  `onPrimaryContainer`, `surface`, `surfaceContainer`, …, `outline`,
  `outlineVariant`) mapped to specific tones of the underlying
  palettes per the MD3 tone tables.
- A `PaletteQualityReport`: APCA `Lc` for every role pair, CIEDE2000
  ΔE between adjacent tones and between brand vs status anchors,
  Machado-simulated CVD ΔE under deuteranopia / protanopia /
  tritanopia, plus pass/fail flags for each gate.
- A repaired palette if any gate fails — via a constraint-satisfaction
  loop that perturbs lightness first, then chroma, and only relaxes
  hue ±8° as a last resort. A hostile-seed curated-neighbour fallback
  fires when geometry cannot solve the constraints.

The output is cached on `ClubProfile.brand_kit.derived_palette` as a
DTCG-format JSON dict. Computation happens once at brand-kit save
time, never per request. Stage D will wire this JSON into the CSS
delivery; Stages G (motion + email + static graphics) will all read
from the same source of truth.

The non-negotiable constraint is again "no behaviour change". Today
nothing reads `derived_palette` — Stage A's hand-coded primitives
still drive the visible cascade. Stage B writes the data; the pipeline
remains dormant until Stage D wakes it up. This is critical because
it lets us ship Stage B safely behind no feature flag.

## 2. Library choices

### `materialyoucolor` (PyPI, Apache-2.0)

The maintained Python port of Google's `material-color-utilities`. It
ships the entire MD3 pipeline natively:

- `Hct.from_int(argb)` — convert sRGB → HCT (Hue, Chroma, Tone)
- `TonalPalette(hue, chroma).tone(t)` — 13-tone ramp from a single hue/chroma
- `SchemeTonalSpot(source_hct, is_dark, contrast_level)` — MD3 standard
  scheme builder. Produces 5 tonal palettes (primary, secondary,
  tertiary, neutral, neutral-variant) plus the error palette anchored
  at hue 25°. Implements the official `+0°` secondary / `+60°`
  tertiary hue offsets and chroma caps (primary chroma ≥ 48,
  secondary 16, tertiary 24, neutral 4, neutral-variant 8).
- `MaterialDynamicColors().primary.get_argb(scheme)` — resolves any of
  the ~50 named MD3 roles against a scheme. Returns ARGB integers.
- `QuantizeCelebi.quantize(pixels, max_colors)` — Wu + WSMeans
  quantizer used by Android 12 Monet for wallpaper colour extraction.
- `Score.score(quantized, desired=…)` — picks the best seed from a
  set of quantized candidates using the hue-bucketing + chroma-weighting
  algorithm Material You uses.

This single library covers seed extraction, palette derivation, role
mapping, and the algorithm decisions Material 3 has spent years tuning
against arbitrary user wallpapers. The whole MediaHub-flavoured
question is "how do we wrap this for our brand-kit pipeline and add
the QA gates the dissertation requires".

### `coloraide` (PyPI, MIT)

The pure-Python reference implementation of the W3C CSS Color
Module Level 4 / 5 spec. Used for:

- OKLCH conversions (`Color('#hex').convert('oklch')`) for our own
  perceptual-uniformity checks
- Gamut mapping (`Color(...).fit('srgb', method='oklch-chroma')`) —
  the CSS Color 4 binary-search chroma-reduction algorithm
- CIEDE2000 deltas (`color1.delta_e(color2, method='2000')`)
- Round-trip sRGB ↔ XYZ for the Machado CVD matrix multiplication

These two libraries cover everything except APCA (Andrew Somers'
contrast model), which we implement from spec — it's ~50 lines.

### What's NOT being added

- `colour-science` — too heavy (numpy + scipy + matplotlib stack);
  only the APCA piece is needed.
- `colorthief` / `extcolors` — superseded by `materialyoucolor`'s
  QuantizeCelebi which is the algorithm Android actually ships.
- `colormath` — abandoned upstream.
- `apca-py` — exists on PyPI but is a thin wrapper; embedding the
  spec directly avoids one more transient dependency.

Both libraries are pure-Python with optional C accelerations.
`materialyoucolor` has Pillow as its only non-stdlib dependency, and
Pillow is already a MediaHub hard dep. `coloraide` has zero non-stdlib
dependencies.

## 3. Module-by-module design

The package is `src/mediahub/theming/` with seven modules. Each is
independently importable and unit-testable. Together they form the
data-only side of the Adaptive Theming Engine.

### `__init__.py`

Re-exports the public entry points:
- `derive_theme(seed_hex_or_logo, *, force_repair=False) → DerivedTheme`
- `extract_seed(logo_bytes_or_svg) → str` (returns hex)

Nothing else is in the public surface — every other module is an
implementation detail.

### `seed_extract.py`

Given a logo (SVG string or raster bytes) or a hex string, return the
seed hex.

```python
def extract_seed(source: str | bytes, *, fallback: str = "#0E2A47") -> SeedResult:
    """Returns (hex, source_kind, candidates) — the chosen seed,
    whether it came from SVG fast-path / raster fallback / direct
    hex / fallback default, plus the top-N candidates with their
    HCT and score for the audit trail."""
```

Three branches:

1. **Direct hex** — if `source` matches `#RRGGBB`, return it.
2. **SVG fast-path** — if `source` looks like SVG markup, parse with
   `lxml.etree`, harvest every `fill=`, `stop-color=`, presentation
   attribute, and `<style>`-block colour, weight each by its element's
   approximate area (bounding-box × opacity), reject near-grey/near-
   black/near-white via HCT chroma < 5 and tone bounds, then feed the
   survivors into `Score.score()`.
3. **Raster fallback** — if `source` is bytes (PNG/JPEG) or the SVG
   contained gradients/embedded images/filters, rasterise to 256×256
   via Pillow, drop alpha < 16 pixels, run
   `QuantizeCelebi.quantize(pixels, 128)` → `Score.score(...)`.

The fallback `#0E2A47` matches the existing `BrandKit.generic_default()`
so an unconfigured profile still threads through the pipeline.

Returns: `SeedResult(hex, source_kind, candidates)` where `candidates`
is a list of `(hex, hct, score)` tuples — the explainability artefact
Phase 1.6 cares about.

### `palette.py`

Given a seed hex, produce a `DerivedPalette`:

```python
@dataclass
class TonalRamp:
    name: str           # "primary" / "secondary" / "tertiary" / "neutral" / "neutral_variant" / "error" / "success" / "warning" / "info"
    hue: float          # HCT hue in degrees
    chroma: float       # HCT chroma
    tones: dict[int, str]  # tone (0..100) → hex

@dataclass
class DerivedPalette:
    seed_hex: str
    seed_hct: tuple[float, float, float]  # (H, C, T)
    primary: TonalRamp
    secondary: TonalRamp
    tertiary: TonalRamp
    neutral: TonalRamp
    neutral_variant: TonalRamp
    error: TonalRamp
    success: TonalRamp
    warning: TonalRamp
    info: TonalRamp
    generated_at: str   # ISO-8601 UTC
    decision_trace: list[str]
```

Implementation: instantiate `SchemeTonalSpot(Hct.from_int(seed_argb),
is_dark=False, contrast_level=0.0)` — but rather than consuming the
scheme directly, we extract its underlying tonal palettes (which
SchemeTonalSpot exposes as `.primary_palette`, `.secondary_palette`,
etc.) and materialise the 13 standard MD3 tones {0, 10, 20, 30, 40,
50, 60, 70, 80, 90, 95, 99, 100} for each.

Status palettes (error, success, warning, info) are anchored at
**fixed hues** — error at 25° (per MD3), success at 142°, warning at
80°, info at 240° — to keep them culturally legible (Aslam 2006,
WCAG 1.4.1). They're not derived from the brand seed because doing so
would silently substitute the brand's red for our danger red, which
defeats their semantic purpose. The chroma values are also fixed,
chosen to give clean tonal ramps across the same 13-tone grid.

### `roles.py`

Given a `DerivedPalette`, return a `ThemeRoles` containing light and
dark `RoleScheme` instances:

```python
@dataclass
class RoleScheme:
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str
    secondary: str
    on_secondary: str
    secondary_container: str
    on_secondary_container: str
    tertiary: str
    on_tertiary: str
    tertiary_container: str
    on_tertiary_container: str
    error: str
    on_error: str
    error_container: str
    on_error_container: str
    background: str
    on_background: str
    surface: str
    on_surface: str
    surface_variant: str
    on_surface_variant: str
    surface_container: str
    surface_container_high: str
    surface_container_highest: str
    surface_container_low: str
    surface_container_lowest: str
    outline: str
    outline_variant: str
    inverse_primary: str
    inverse_surface: str
    inverse_on_surface: str
    focus: str             # MediaHub addition: aliases to primary

@dataclass
class ThemeRoles:
    light: RoleScheme
    dark: RoleScheme
```

Implementation: reuse `materialyoucolor.dynamiccolor.material_dynamic_colors.MaterialDynamicColors`,
build a `SchemeTonalSpot(seed_hct, is_dark=False, 0.0)` for light and
`SchemeTonalSpot(seed_hct, is_dark=True, 0.0)` for dark, then iterate
the role names and call `dc.get_argb(scheme)` to resolve each. The
contrast guarantees come baked-in via the MD3 tone tables — no runtime
check needed.

This module is intentionally thin. The reason it's its own module
rather than a method on `DerivedPalette` is testability and the
"single responsibility per file" rule.

### `contrast.py`

Two responsibilities:

1. **APCA `Lc` for any (fg, bg) pair.** Implements SAPC-APCA v0.1.9
   per Somers' Github reference (`Myndex/SAPC-APCA`). The numeric
   constants (`SAPC_FACTOR`, `BLK_THRS`, exponents for forward and
   reverse polarity) are embedded as module-level constants with
   citations. Returns a signed `Lc` value (positive = dark text on
   light bg; negative = light text on dark bg).

2. **Ink-on-surface picker.** Given any surface hex, computes APCA Lc
   for `#000` and `#FFFF`, returns the higher-|Lc| ink and the
   polarity flag. Used by `quality.py` to fill in `on_primary`,
   `on_surface`, etc. when MD3's defaults don't quite hit the body-
   text threshold (`|Lc| ≥ 75` for Silver Bronze body-text level).

```python
def apca(fg_hex: str, bg_hex: str) -> float: ...
def wcag2_ratio(fg_hex: str, bg_hex: str) -> float: ...
def pick_ink(surface_hex: str) -> tuple[str, str]:  # (ink_hex, polarity)
    ...
```

`wcag2_ratio` is the simple `(L1+0.05)/(L2+0.05)` formula via coloraide
— we ship both because some downstream consumers (the explainability
panel) want both numbers side by side.

### `cvd.py`

Machado 2009 colour vision deficiency simulation.

The Machado matrices for deuteranopia, protanopia, and tritanopia at
severity 1.0 (full dichromacy) are public — they're 3×3 floats. We
embed them directly as module-level numpy arrays with citations.

```python
DEUTAN_MATRIX = np.array([[0.367,  0.861, -0.228], …])
PROTAN_MATRIX = np.array([…])
TRITAN_MATRIX = np.array([…])

def simulate(hex_color: str, cvd: str) -> str:
    """Return the hex that a `cvd`-affected viewer perceives."""

def collision(hex_a: str, hex_b: str, cvd: str) -> CVDPair:
    """Return ΔE2000 between the simulated pair, plus a
    distinguishable flag (ΔE2000 ≥ 10 per ColorBrewer)."""
```

The simulation pipeline: hex → linear-light sRGB → multiply by matrix
→ re-encode → hex. CIEDE2000 ΔE comes from `coloraide`.

### `quality.py`

The QA gate. Given a `DerivedPalette` + `ThemeRoles`, run every
check the dissertation requires:

```python
@dataclass
class ContrastCheck:
    role_pair: str    # e.g. "light.primary/light.on_primary"
    foreground: str
    background: str
    apca_lc: float
    wcag2_ratio: float
    passes_apca_body: bool   # |Lc| >= 75
    passes_apca_ui: bool     # |Lc| >= 45
    passes_wcag2_aa: bool    # ratio >= 4.5 normal text
    passes_wcag2_aa_large: bool  # ratio >= 3.0

@dataclass
class AdjacencyCheck:
    palette: str
    tone_a: int
    tone_b: int
    delta_e_2000: float
    distinguishable: bool   # >= 5

@dataclass
class CVDCheck:
    cvd: str           # "deutan" / "protan" / "tritan"
    role_a: str
    role_b: str
    simulated_delta_e: float
    distinguishable: bool   # >= 10

@dataclass
class PaletteQualityReport:
    palette: DerivedPalette
    roles: ThemeRoles
    contrast: list[ContrastCheck]
    adjacency: list[AdjacencyCheck]
    cvd: list[CVDCheck]
    warnings: list[str]
    errors: list[str]
    passed: bool

def audit(palette: DerivedPalette, roles: ThemeRoles) -> PaletteQualityReport:
    ...
```

The audit checks:

1. Every text-on-surface role pair (primary/on_primary, surface/on_surface,
   error/on_error, …) has `|APCA Lc| ≥ 75` in both light and dark.
2. UI elements (`outline`, `outline_variant`) have `|Lc| ≥ 45`
   against the surface they sit on.
3. Adjacent tones in each tonal palette have `ΔE2000 ≥ 5` per Radix's
   working "clearly perceptible step" threshold.
4. Brand seed vs status anchors have `ΔE2000 ≥ 15` (hard fail) /
   `≥ 25` (soft warn).
5. Brand vs status under Machado-deutan/protan/tritan simulation
   have `ΔE2000 ≥ 10` (the ColorBrewer floor for categorical
   distinguishability).

Returns a report. `passed = (len(errors) == 0)`.

### `repair.py`

The constraint-satisfaction loop. If `quality.audit()` returns
`passed = False`, repair attempts to fix the palette without
abandoning the brand identity:

```python
def repair(palette: DerivedPalette, report: PaletteQualityReport,
           *, max_iters: int = 8) -> tuple[DerivedPalette, list[str]]:
    """Return (repaired_palette, decision_trace).

    Strategy (per Lalitha A R, arXiv 2512.05067):
      1. Clamp chroma to the OKLCH-gamut ceiling at each tone.
      2. Sweep tone L within ±10 to satisfy APCA + adjacent-ΔE.
      3. Only if still failing, relax hue ±8° (silent), ±18° (warn),
         or fall back to a curated-neighbour table by hue sextant.
    The brand seed itself never moves; only the *derived* palette
    stops move, and only the *status* colours rotate to stay distinct
    from the brand seed under CVD.
    """
```

The curated-neighbour table is short — six entries by hue sextant,
each a "safest analogous hue" with a citation to Material You's
fallback behavior (the only place in the codebase where we hard-code
colour-name → fallback-hex pairings, per the Phase 1.6 acceptance
criterion #3).

## 4. Persistence (B3)

Extend `BrandKit` with a single optional field:

```python
@dataclass
class BrandKit:
    profile_id: str
    display_name: str
    primary_colour: str = "#A30D2D"
    secondary_colour: str = "#000000"
    accent_colour: Optional[str] = None
    logo_svg: Optional[str] = None
    governing_body: Optional[str] = None
    short_name: Optional[str] = None

    # Phase 1.6 Stage B
    derived_palette: Optional[dict] = None  # DTCG-format theme JSON
```

The shape of `derived_palette` is documented in `theming/__init__.py`
as a `TypedDict` so consumers can introspect it without importing
the dataclasses. It's serialised as a plain `dict` rather than a
nested dataclass so `asdict(kit)` and `json.dumps(kit.to_dict())`
keep working with no extra encoder.

`BrandKit.from_dict()` already ignores unknown keys, so old profiles
without `derived_palette` load unchanged. New profiles get
`derived_palette = None` until something writes to it.

A new helper on `BrandKit`:

```python
def ensure_derived_palette(self, *, force: bool = False) -> dict:
    """Compute (or re-compute) the derived palette from this kit's
    primary_colour or logo_svg and cache it on the instance.
    Returns the palette dict. Safe to call repeatedly; idempotent
    unless force=True."""
```

Called at brand-kit save time (next branch's wiring in Stage D) and
nowhere else. The "compute once, never per request" rule.

## 5. Test strategy

New `tests/theming/` directory:

- `test_seed_extract.py` — direct hex passthrough, SVG fast-path with
  fixtures, raster fallback with a synthetic 16×16 PNG, near-grey
  filtering, fallback default firing.
- `test_palette.py` — golden-master snapshots for ~12 representative
  seeds (lane yellow, navy, brand red, fluorescent yellow, muddy
  dark green, near-white, near-black, sky blue, hot pink, deep
  purple, generic-default navy, brand-from-existing-default).
  Asserts every palette has all 13 tones, hue/chroma anchors match
  HCT, ramps are monotonic in L*.
- `test_roles.py` — verify role mapping for light + dark on a known
  seed, assert all ~30 roles are populated and valid hex.
- `test_contrast.py` — APCA Lc against the published reference test
  vectors (Somers ships ~20 known-good pairs); WCAG2 ratio against
  the W3C examples; ink-on-surface picker chooses correctly for
  pure white, pure black, mid-grey, vivid yellow surfaces.
- `test_cvd.py` — Machado simulator against a known fixture vector
  (deuteranopia simulation of pure red, green, blue); ΔE2000
  distinguishability gate fires correctly.
- `test_quality.py` — synthetic palettes that deliberately fail one
  gate at a time produce a report with exactly that error; a known-
  good palette produces `passed=True`.
- `test_repair.py` — hostile fluorescent-yellow seed gets repaired
  to a passing palette; the decision trace records every step.
- `test_brand_kit_derived.py` — `BrandKit.ensure_derived_palette()`
  is idempotent, persists across `to_dict`/`from_dict` round-trips,
  doesn't fire if the field is already populated unless `force=True`.

Plus a top-level `tests/theming/__init__.py` for package discovery.

All existing 1,175 tests must still pass — Stage B is purely
additive at the source level.

## 6. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| `materialyoucolor` API drifts between versions | Low | Pin minimum version `>=3.0`; CI runs against the latest. |
| Numpy version skew on Render | Low | Pillow already requires it; same numpy version. |
| APCA implementation diverges from `apca-w3` (npm) | Medium | Validate against ≥10 published reference vectors in `test_contrast.py`. |
| Machado matrices typo'd | Medium | Validate against the published deutan/protan/tritan vectors at the boundaries (red, green, blue, white, black). |
| Quality gates too strict, every palette fails | Medium | Calibrate thresholds against MediaHub's existing palette first — if the *current* palette doesn't pass, the gates are mis-tuned. |
| Repair loop infinite-loops on hostile seeds | Low | `max_iters=8` with the curated-neighbour fallback as the terminal branch. |
| `BrandKit.derived_palette` serialisation explodes existing profiles | Low | Optional + None default + `from_dict` ignores unknown keys (already the contract). |

## 7. Audit plan (10 subtasks)

1. `pip install materialyoucolor coloraide` succeeds in a clean env;
   `requirements.txt` updated.
2. Every new module imports without error.
3. `derive_theme("#D4FF3A")` (the existing lane yellow) produces a
   palette where the seed appears verbatim in the primary ramp at the
   closest tone.
4. APCA implementation matches at least 10 published reference
   vectors within ±0.5 Lc.
5. Machado simulator matches the published deutan/protan/tritan
   reference vectors for primary colours.
6. Quality audit on a known-good palette returns `passed=True` with
   zero errors.
7. Quality audit on a known-bad synthetic palette returns the exact
   error categories you'd expect.
8. Repair loop converges (max_iters not exceeded) for hostile seeds
   (fluorescent yellow, near-white, near-black).
9. `BrandKit.from_dict({...})` round-trips `derived_palette` unchanged.
10. Full pytest suite green (existing 1,175 + new theming tests).

## 8. Verification plan (10 subtasks)

1. Boot Flask app — no import errors.
2. Hit `/status` and `/healthz/usage` — HTTP 200, no regression.
3. Render the BASE_CSS via `mediahub.web.web.BASE_CSS` — bytewise
   identical to pre-Stage-B (Stage B writes no CSS).
4. Programmatically derive a palette for the existing default
   profile's primary_colour, inspect the JSON shape matches the
   documented TypedDict.
5. Round-trip the derived palette: `derive_theme(seed) → save →
   BrandKit.from_dict → ensure_derived_palette → identical output`.
6. Verify all 9 tonal palettes (primary, secondary, tertiary, neutral,
   neutral_variant, error, success, warning, info) contain all 13
   tones.
7. Light and dark `RoleScheme` differ in expected directions (light
   `primary` darker than dark `primary`, etc.).
8. The audit trail captures every decision the engine made (seed
   extraction source, repair iterations, fallback firing).
9. A second computation with the same seed produces a bytewise-
   identical palette (deterministic).
10. Running `audit + repair` on MediaHub's *current* lane-yellow
    palette returns `passed=True` without modification — proving the
    gates are calibrated to today's status quo, not to an arbitrary
    standard we'd never meet.

Pass all 20 → Stage B shipped, Stage C unblocked.

## 9. Out of scope (deferred to later stages)

- Wiring `derived_palette` into actual CSS delivery (Stage D).
- The smooth cascade animation on "Looks right – start creating"
  (Stage E).
- Logo recolouring intelligence (Stage F).
- Single-source-of-truth JSON for Remotion + newsletter + static
  graphic (Stage G).
- The "Why does my theme look like this?" UI panel (Stage H).
- Cutover to remove Stage A's hand-coded primitives (Stage J).

Stage B is *only* the engine. It computes and persists; nothing yet
reads from `derived_palette`. This is by design.
