# Stage H — Explainability + QA: Plan

> Phase 1.6 Stage H of [`ROADMAP.md`](ROADMAP.md). Stages A–G built
> the engine; Stage H makes it auditable. A club committee member
> who clicks the "Looks right" button now sees exactly *why* the
> engine produced the colours it did, with every QA check it ran,
> every adjustment it made, and a non-blocking callout when the
> repair loop changed anything.

## 1. Context

Stages A–G shipped a complete adaptive theming engine:

- Stage A established the three-tier token vocabulary.
- Stage B built the colour-science pipeline (`mediahub.theming`)
  producing a `DerivedTheme` with a `PaletteQualityReport`
  carrying contrast, adjacency, status-distance, and CVD checks.
- Stage C wired runtime derivation via OKLCH `oklch(from …)`.
- Stage D + E persisted the derived palette and animated the
  cascade.
- Stage F added logo intelligence.
- Stage G centralised the palette as on-disk DTCG JSON consumed
  by web, motion, email, and static-graphic renderers.

The engine works. Stage H asks the next question: when a club
opens `/organisation/setup` and sees the captured brand context,
**can they understand and trust what the engine has done?**

The MediaHub product principle is "every step should be
explainable and auditable" (CLAUDE.md). Today the audit trail is
locked inside `decision_trace` — present in the cached JSON but
not surfaced anywhere a non-engineer would find. Stage H surfaces
it as a first-class UI element, plus a Cohen-Or harmonic-template
fit (the only QA gate Stage B's plan named but didn't ship), plus
a non-blocking warning callout when the repair loop ran.

## 2. The user-visible promise

When a club's owner lands on `/organisation/setup` after the
brand-DNA capture has completed, three new things appear:

1. **A "Why does my theme look like this?" expandable panel** sits
   next to the "Looks right — start creating" button. Collapsed
   by default (so it doesn't add visual weight to first-time
   users). Expanded, it shows:
   - **Captured seed** — the brand hex the engine started from,
     plus its source (direct hex / SVG / raster / fallback).
   - **Derived palette** — swatches for primary, secondary,
     tertiary, plus the four status anchors.
   - **Contrast pairs** — every role/on-role text pair with APCA
     Lc and WCAG 2.x ratio, colour-coded pass/fail.
   - **Brand-vs-status ΔE matrix** — ΔE2000 between the brand
     seed and each status anchor.
   - **CVD simulation** — ΔE for the same pairs under
     deuteranopia / protanopia / tritanopia.
   - **Harmonic fit** — Cohen-Or template + energy score.
   - **Decision trace** — the engine's blow-by-blow log.

2. **A non-blocking warning callout** appears ABOVE the panel
   when the repair loop fired. The callout reads in plain
   English: *"Your brand red (#A30D2D) was very close to our
   success-green under deuteranopia (ΔE2000 = 8.7, below our
   floor of 10). We adjusted the success anchor by 18° to keep
   them distinguishable for colour-blind viewers."*

3. **Behind the scenes**, every derivation is fully audited on
   disk: the theme JSON at `DATA_DIR/themes/<profile_id>.json`
   now carries the FULL `PaletteQualityReport` (not just the
   counts). The previous summary keys are preserved for
   backward compatibility; the new `quality_detail` key adds
   the per-check rows.

Trust is the design goal. Sport-club committees are often
volunteers who'd rather see one warning callout than tunnel into
a hex value to find out why it changed.

## 3. Architecture overview

Five concrete changes:

| Change | Where | What |
|---|---|---|
| Harmonic fit | New `src/mediahub/theming/harmony.py` | Cohen-Or 2006's 7 hue templates + energy search |
| Detailed audit dict | `theming/quality.py` | New `to_detail()` method dumps every per-check row |
| Theme JSON shape | `theming/__init__.py` | `ThemeJSON.quality_detail` adds the per-check dict |
| H2 panel | `web.py` — new helper + insertion at `/organisation/setup` | Expandable `<details>` block rendered server-side |
| H3 callout | `web.py` — new helper + insertion above the panel | Plain-English text when `was_repaired = True` |

Data flow:

```
   BrandKit.ensure_derived_palette()
              │
              ▼
   DerivedTheme.to_json()  ◄── now includes quality_detail + harmonic_fit
              │
              ▼
   DATA_DIR/themes/<pid>.json  (Stage G — bigger file now, ~25KB)
              │
              ▼
   _theme_audit_panel_html(palette_json)  ◄── new helper
              │
              ▼
   organisation_setup() body
              │
              ▼
   <div class="card">                       ← brand preview card
     <h3>What MediaHub learned about …</h3>
     ...
     [H3 callout if was_repaired]           ← new
     [H2 details panel]                     ← new
     <a class="btn" data-mh-cascade>…</a>   ← existing "Looks right" button
   </div>
```

Everything is server-rendered. No JS dependency. Expand/collapse
uses the native `<details>` element so it works in every browser
and in print.

## 4. H1 — full audit-trail logging

### Cohen-Or harmonic-template fit

`src/mediahub/theming/harmony.py` implements the seven templates
from Cohen-Or et al. (SIGGRAPH 2006), §3:

```python
HARMONIC_TEMPLATES = {
    "i": [(0, 18)],                          # 1 narrow band
    "V": [(0, 94)],                          # 1 wide band
    "L": [(0, 18), (90, 78)],                # narrow + wide, 90° apart
    "I": [(0, 18), (180, 18)],               # two narrow, 180° apart
    "T": [(0, 180)],                         # half-wheel
    "Y": [(0, 18), (180, 94)],               # narrow + wide, 180°
    "X": [(0, 94), (180, 94)],               # two wide, 180°
}
```

Each tuple is `(centre_offset_deg, width_deg)`. The full template
is rotatable: for each rotation `θ ∈ [0°, 360°)` we sum the
out-of-band hue distances for the palette's hues. The lowest
energy across all rotations and all templates wins.

```python
@dataclass
class HarmonicFit:
    template: str           # one of "i" / "V" / "L" / "I" / "T" / "Y" / "X"
    rotation: float          # best rotation in degrees
    energy: float            # total out-of-band distance (lower = better)
    hue_count: int           # how many palette hues were scored
    template_bands: list[tuple[float, float]]  # the (centre, width) tuples

def fit_harmonic_template(
    hues: list[float],
    *,
    rotation_step: float = 5.0,
) -> HarmonicFit:
    """Search all 7 templates × 72 rotations; return the best fit.

    Cost: 7 × 72 × len(hues) hue-distance computations ≈ 5 ms for
    8 hues. Runs once per palette derivation; no perf concern.
    """
```

The score for a single hue against a band is
`max(0, min(|h-band_edge_left|, |h-band_edge_right|))`. Hues
inside the band score 0. Energy is the sum.

For the brand palette we pass the hues of `primary`, `secondary`,
`tertiary`, and the four status anchors (7 hues total). The
result lands inside the `PaletteQualityReport`.

### Detailed audit dict

`PaletteQualityReport.to_detail()` (new) returns the full
per-check structure:

```python
def to_detail(self) -> dict:
    return {
        "passed": self.passed,
        "harmonic_fit": asdict(self.harmonic_fit) if self.harmonic_fit else None,
        "contrast": [
            {
                "scheme": c.scheme,
                "role_pair": c.role_pair,
                "foreground": c.foreground,
                "background": c.background,
                "apca_lc": c.apca_lc,
                "wcag2_ratio": c.wcag2_ratio,
                "passes_apca": c.passes_apca,
                "passes_wcag2": c.passes_wcag2,
            }
            for c in self.contrast
        ],
        "adjacency": [...],         # one row per adjacent tone pair
        "status_distance": [...],   # brand vs each status anchor
        "cvd": [...],               # 3 CVD types × 4 status pairs
        "warnings": self.warnings,
        "errors": self.errors,
    }
```

`to_summary()` stays (Stage G consumers still call it for the
counts-only shape). `to_detail()` is the new path.

### Theme JSON shape

`DerivedTheme.to_json()` adds:

```python
{
    "schema_version": "1",
    "seed_hex": "...",
    "palettes": {...},
    "roles": {...},
    "quality": {...},          # existing summary (Stage G)
    "quality_detail": {...},   # NEW (Stage H)
    "harmonic_fit": {...},     # NEW (Stage H)
    "decision_trace": [...],
    "was_repaired": ...,
    "generated_at": "...",
}
```

`schema_version` stays `"1"` because the additions are additive
(new keys, no removed or renamed). Stage J's cutover may bump to
`"2"` if needed; until then every Stage A–G consumer continues
to work.

## 5. H2 — "Why does my theme look like this?" panel

### Where it sits

The "What MediaHub learned" card on `/organisation/setup` at
`web.py:11636` already renders the brand context. The H2 panel
sits INSIDE that card, after the captured-context body and BEFORE
the "Looks right — start creating" button:

```html
<div class="card">
  <h3>What MediaHub learned about …</h3>
  <p>{voice summary}</p>
  …keyword chips, palette swatches, sources…

  {H3 callout — only if was_repaired}

  {H2 panel — collapsible <details>}

  <a class="btn" data-mh-cascade="finalise">Looks right — start creating →</a>
</div>
```

### Panel structure

```html
<details class="mh-theme-audit" style="margin:18px 0;
    border:1px solid var(--mh-outline-variant);
    border-radius:8px;background:var(--mh-surface-variant)">
  <summary style="cursor:pointer;padding:14px 18px;
      font-size:13px;font-weight:600;color:var(--mh-on-surface)">
    Why does my theme look like this?
    <span class="muted" style="font-weight:400;font-size:12px">
      Engine decisions, contrast checks, accessibility audit
    </span>
  </summary>
  <div style="padding:0 18px 18px 18px">
    <h4>Captured seed</h4>
    <p>Seed: <code>#…</code> from <code>{source}</code>; HCT
       H={…}° C={…} T={…}</p>

    <h4>Derived palette</h4>
    {swatch row: 7 colours with labels}

    <h4>Contrast checks (APCA Lc / WCAG 2.x)</h4>
    {table: role_pair | fg | bg | Lc | ratio | pass/fail}

    <h4>Brand vs status anchors (CIEDE2000)</h4>
    {table: anchor | hex | ΔE2000 | pass}

    <h4>Colour-vision-deficiency simulation (CIEDE2000)</h4>
    {table: cvd | pair | ΔE2000 | pass}

    <h4>Harmonic fit (Cohen-Or 2006)</h4>
    <p>Best template: <b>{template}</b> @ {rotation}°,
       energy = {energy:.1f}</p>

    <h4>Decision trace</h4>
    <pre>{joined trace lines}</pre>

    <p class="muted">Stage H — see
       <a href="https://github.com/.../stage_h_explainability_plan.md">docs</a>
       for the underlying algorithms.</p>
  </div>
</details>
```

All values come from the cached `derived_palette` dict — no
recomputation at render time.

### Render helper

`_theme_audit_panel_html(theme_json: dict) -> str` in `web.py`:

- Returns the `<details>` block string.
- Returns empty string if `theme_json` is None / missing the
  expected keys (graceful degradation).
- All values HTML-escaped via the existing `_h()` helper.
- Numeric values formatted to one decimal place.
- Pass/fail status indicators use the existing `--mh-success` /
  `--mh-error` tokens.

## 6. H3 — non-blocking warning callout

When `theme_json['was_repaired']` is True, the engine modified
something during palette derivation. Stage H surfaces this as a
small callout immediately above the H2 panel:

```html
<div class="mh-theme-warning" role="status"
     style="margin:14px 0;padding:12px 16px;
         border-radius:6px;border:1px solid var(--mh-warning);
         background:rgba(255,180,84,0.10);
         font-size:13px;color:var(--mh-on-surface)">
  <strong style="display:block;margin-bottom:4px;
      color:var(--mh-warning)">
    Theme adjusted for accessibility
  </strong>
  Your brand seed was close to our success-green under
  deuteranopia. We adjusted the success anchor by +18° to keep
  them distinguishable for colour-blind viewers. See
  <em>Decision trace</em> below for full details.
</div>
```

The text is generated from the palette's status anchors compared
to the canonical `STATUS_ANCHORS` table in `theming/palette.py`:

```python
def _repair_summary_text(theme_json: dict) -> Optional[str]:
    """Return a one-sentence plain-English summary of what the
    repair loop did, or None if no repair fired."""
    if not theme_json.get("was_repaired"):
        return None
    palettes = theme_json.get("palettes") or {}
    deltas = []
    from mediahub.theming.palette import STATUS_ANCHORS
    for name, (canonical_hue, _) in STATUS_ANCHORS.items():
        ramp = palettes.get(name) or {}
        actual_hue = ramp.get("hue")
        if isinstance(actual_hue, (int, float)):
            offset = ((actual_hue - canonical_hue + 180) % 360) - 180
            if abs(offset) >= 1.0:
                deltas.append((name, canonical_hue, actual_hue, offset))
    if not deltas:
        return ("MediaHub ran additional checks during palette derivation; "
                "no anchors were moved. See decision trace for details.")
    parts = []
    for name, canon, actual, offset in deltas:
        sign = "+" if offset > 0 else ""
        parts.append(f"{name} (rotated {sign}{offset:.0f}°)")
    listing = ", ".join(parts)
    return (
        f"Your brand seed was close enough to our standard status anchors "
        f"that we adjusted {listing} to keep them distinguishable for "
        f"colour-blind viewers and to satisfy our contrast gates."
    )
```

This is good enough for Stage H. Stage J could refine the text
further (which specific gate fired, which CVD, etc.) — out of
scope here.

## 7. Backwards compatibility

Stage H is purely additive:

- **`PaletteQualityReport.to_summary()`** unchanged — Stage G
  consumers (`theme_store` summary path) keep their existing
  shape.
- **`DerivedTheme.to_json()`** adds new keys; old keys keep
  their values.
- **Old themes on disk** loaded into the H2 panel: missing
  `quality_detail` / `harmonic_fit` keys render the panel with
  empty sections + a "(no detail available)" note.
- **Theme JSON schema version** stays "1" because only additions.

## 8. Test strategy

Five new test files / sections:

### `tests/theming/test_harmony.py`

- The 7 templates are defined per Cohen-Or 2006 §3.
- `fit_harmonic_template([])` (empty list) returns a `HarmonicFit`
  with energy = 0.
- `fit_harmonic_template([0, 90, 180, 270])` (4 hues evenly
  spaced) doesn't crash; rotation search converges.
- `fit_harmonic_template([0, 0, 0])` (3 identical) lands in the
  `i` template with energy ≈ 0.
- `fit_harmonic_template([0, 180])` (2 complementary) lands in
  `I` template with energy ≈ 0.
- Rotation step parameter respected.

### `tests/theming/test_quality_detail.py`

- `PaletteQualityReport.to_detail()` returns a dict with the
  documented keys.
- Each per-check list (`contrast`, `adjacency`, `status_distance`,
  `cvd`) contains the per-row dicts (not just counts).
- The detail dict round-trips through JSON without information
  loss.

### `tests/test_theme_store_quality_detail.py`

- After `BrandKit.ensure_derived_palette()`, the on-disk theme
  JSON carries `quality_detail` AND `harmonic_fit` keys.
- The `quality` (summary) key still exists alongside.
- `schema_version` is still "1".

### `tests/test_audit_panel_render.py`

- `_theme_audit_panel_html(theme_json)` returns a non-empty
  `<details>` block when given a valid theme.
- The block contains:
  - "Captured seed" with the seed hex
  - "Contrast checks" table with at least one row
  - "Decision trace" `<pre>` with the trace text
- Returns "" for None / empty input (graceful).
- Output is HTML-escape-safe.

### `tests/test_repair_callout.py`

- `_repair_summary_text(theme_json)` returns None when
  `was_repaired = False`.
- Returns a non-empty string when `was_repaired = True`.
- The string mentions every status anchor whose hue moved by
  >= 1°.
- The rendered HTML callout appears in `/organisation/setup`
  for a profile whose repair fired.

## 9. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| Cohen-Or fit unstable for empty palettes | Low | Empty hue list → energy 0; tested |
| Detail dict too large for the theme JSON | Low | ~10KB extra; per-profile, not per-request |
| Repair text wrong for unusual repairs | Medium | Built from observable hue offsets, not free text; falls back to neutral wording |
| Panel HTML breaks accessibility | Low | `<details>` is native; ARIA managed automatically |
| Stage G consumers break on new keys | None | additive only — old keys preserved |
| Old themes without quality_detail | Low | Panel renders with empty sections + note |
| Harmonic search too slow | Low | 7 × 72 rotations × ~8 hues = ~4 ms; bounded |
| Panel exposes secrets in trace | Low | Trace only carries colour math + role names; HTML-escaped |

## 10. Audit plan (10 subtasks)

1. `mediahub.theming.harmony` imports cleanly.
2. `fit_harmonic_template([])` returns a HarmonicFit with energy 0.
3. `PaletteQualityReport.to_detail()` includes the per-check rows.
4. `DerivedTheme.to_json()` adds `quality_detail` and
   `harmonic_fit` to the output.
5. On-disk theme JSON for a finalised profile carries the new keys.
6. `_theme_audit_panel_html()` returns a non-empty `<details>`
   for a valid theme.
7. `_repair_summary_text()` returns None when `was_repaired = False`.
8. `_repair_summary_text()` returns prose mentioning the changed
   anchor when `was_repaired = True`.
9. Stage G's 67 tests still pass (additive contract).
10. Stage F's 40 tests still pass.

## 11. Verify plan (10 subtasks)

1. App boots; `/status` returns 200.
2. POST `/api/organisation/finalise` writes a theme JSON
   containing `quality_detail` and `harmonic_fit`.
3. `/organisation/setup` for a profile with a captured brand
   renders the H2 `<details>` panel.
4. The panel `<summary>` text is "Why does my theme look like
   this?".
5. The panel contains the captured-seed hex.
6. The panel contains a contrast-checks table.
7. For a profile whose repair fired (e.g. brand red), the
   `/organisation/setup` page shows the H3 warning callout.
8. The callout text mentions a specific anchor that moved.
9. For a profile whose repair did NOT fire, the callout is
   absent.
10. Existing pytest suite passes (Stage A–G + new Stage H tests).

## 12. Out of scope (deferred)

- Sticky preferences ("don't show me this panel again") — Stage
  J or a future user-preferences refactor.
- Re-deriving the palette client-side (the panel only renders
  the server-computed numbers).
- Per-CVD-type drill-down ("show me only the protan rows").
- Sharing the audit panel as a permalink. The data is per-profile;
  no public route.
- Re-extracting the seed on demand (the brand-DNA capture flow
  handles this on the existing /organisation/setup/capture POST).

Stage H closes the explainability loop. After it, the engine
isn't just adaptive — it's accountable. A committee member who
clicks "Looks right" knows exactly what they're agreeing to.

## 13. References

- Cohen-Or, Sorkine, Gal, Leyvand & Xu (SIGGRAPH 2006),
  *"Color Harmonization"* — the seven harmonic hue templates and
  the energy-based template fit. The original paper uses an
  L1 distance to the nearest band edge; our implementation
  matches the formulation in §3.1 of the paper.
- Sharma, Wu & Dalal (2005), *"The CIEDE2000 Color-Difference
  Formula"* — the brand×status distance gate. Stage B already
  ships the implementation via `coloraide`.
- Andrew Somers, *SAPC-APCA* v0.1.9 — the contrast model used
  in the H2 panel's contrast-pairs table.
- Machado, Oliveira & Fernandes (IEEE TVCG 2009),
  *"A Physiologically-based Model for Simulation of Color Vision
  Deficiency"* — the CVD simulation matrices. The H2 panel
  renders the simulated ΔE2000 per CVD type.
- W3C Design Tokens Format Module (DTCG) — the per-profile JSON
  schema; Stage H additions stay schema-compatible by being
  purely additive (no key renames, no value-shape changes).

The HTML `<details>` element is universally supported (Baseline
since June 2020), so the panel works without JavaScript and is
naturally print-friendly. ARIA semantics are managed by the
browser, not us.

## 14. Why this stage matters

The Phase 1.6 brief opened with: *"Every step should be
explainable and auditable."* Stages A–G delivered the cascade;
Stage H delivers the contract that the cascade can be inspected.
A club whose brand colour was repaired isn't told "we changed
something" — they're told *what* changed, *why*, and what the
engine saw that made it act. That converts the adaptive theming
engine from a black box into an instrument the club can
challenge, validate, or override.
