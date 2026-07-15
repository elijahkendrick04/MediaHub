# Canva gap analysis — how Canva & co get graphics to look good, and the build list to beat them

*Produced 2026-07-14. Sources: an 18-agent research sweep (web research on Canva /
Adobe Express / PhotoRoom / Material engineering + design literature, six code
inventories of `graphic_renderer/`, six adversarial gap analyses) plus a
hands-on baseline render audit of eight archetypes. This document is the
ranked comparison list; the **Status** column tracks what has shipped.*

---

## Part 1 — Why Canva output looks "designed" (the mechanisms)

Canva's quality is not one feature; it is a stack of mutually reinforcing
mechanisms, most of which are *deterministic craft rules*, not AI:

1. **A reviewed template floor.** Every output inherits a layout that passed a
   human acceptance review (alignment, spacing, hierarchy, contrast, safe
   margins). Nothing the user does can fall below that floor.
2. **Design tokens under everything.** An 8-pt spacing scale, modular type
   scale, and role-based colour system make every gap and size geometrically
   related — the "rhythm" the eye reads as professional.
3. **Real measured typography.** Text autosizes on actual glyph metrics;
   display type is tracked tight, small caps labels tracked open; long
   headlines wrap and balance rather than shrinking to a strip.
4. **Depth everywhere.** Layered elevation shadows with one implied light
   source, hue-tinted darks (never pure black), micro-gradients on surfaces,
   frosted-glass panels, cutout sticker outlines and contact shadows —
   flatness is the #1 amateur tell and Canva systematically removes it.
5. **Photo normalisation.** Auto-enhance (levels/white-balance/clarity) runs
   before any styling; smart crops put faces on thirds lines; brand washes and
   duotones unify mismatched club photography into one campaign.
6. **A full colour system from one seed.** Tonal ramps (Material-HCT-style)
   give containers, tinted surfaces and elevation tiers; neutrals are
   hue-tinted toward the brand; per-node contrast repair bends the theme
   instead of breaking legibility.
7. **Decoration that interacts with content.** Foreground accents overlap
   midground edges (badge half-off a photo, chip straddling a seam), shapes
   sit *behind* headlines, cutouts break their frames — overlap + shadow is
   what reads as art direction rather than clip-art.
8. **Structural honesty about output.** sRGB-pinned exports, 2× rendering, no
   silent font substitution, no upscaled rasters.

MediaHub already has a deep engine (role tokens + APCA gating, 34 archetypes ×
1000+ style packs, true SVG duotone, saliency crops, deterministic autofit
with variable-font axes, gradient meshes, server-side photo recipes). The gaps
below are where Canva's *output* still reads better — each with the concrete
build that closes it inside MediaHub's hard bounds (deterministic, brand-locked,
APCA-gated, self-hosted fonts, no generative foreground pixels, still↔motion
parity).

---

## Part 2 — The comparison list (ranked, with build status)

Legend: **[SHIPPED]** implemented in this change · **[PARTIAL]** first slice
shipped, remainder noted · **[ROADMAP]** specified, not yet built.

### A. Broken windows (defects Canva output would never ship)

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| A1 | No Canva card paints its decoration into the wrong box. Our `magazine_cover` and `triptych_progression` misplace the `{{ACCENT_DECORATION}}` slot inside an inner tag div, so style packs render as a clipped ghost rectangle and the card body gets no treatment. | Move the slot to the root (the documented contract); restore honest tag content (`Result` label / `{{HERO_STAT}}`). | **[SHIPPED]** |
| A2 | Canva badges always read. Our PB rosette / record shield are tinted with the club *primary* and stamped on a ground that *is* the primary — an invisible navy-on-navy smudge on most cards. | Contrast-aware emblem base: walk accent → secondary → primary, require ≥ 0.18 luminance separation from the ground, else derive a visible face from the primary (brand maths, no invented colour). | **[SHIPPED]** |
| A3 | Canva never stamps a sticker over copy. Our badge default anchor collides with the meet name on `stat_stack_sidebar` (unmapped family). | Add the missing anchor-table entries after a collision audit of all unmapped archetypes. | **[SHIPPED]** |
| A4 | Canva monograms look deliberate. Our logo-less fallback renders bare unstyled initials (a stray tiny "C") where the logo belongs. | Render the text-mark fallback as a proper monogram chip: ring + initials as inline SVG inheriting `currentColor`, scaling exactly like the logo image it replaces. | **[SHIPPED]** |
| A5 | Canva numerals are kerned. JetBrains Mono + `tnum` gives the decimal point a full glyph cell, so every result reads "58 . 34" with a hole in the hero stat. | Wrap intra-numeric separators in a narrow (0.55ch) span at fill time and scale the fitted size up by the recovered width, so the numeral is both tighter *and* larger. Mirrored in the Remotion count-up. | **[SHIPPED]** (still + motion mirror) |

### B. Depth & light (the strongest "made by a designer" signals)

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| B1 | Layered elevation shadows with one light source; ours are ~14 ad-hoc single-layer `box-shadow`s with inconsistent implied lighting. | `graphic_renderer/elevation.py`: deterministic `--mh-elev-1..5` (contact layer + doubling key-light ramp, constant light direction) + `--mh-elev-drop-N` filter twins; migrate v2 shadows onto the tokens. | **[SHIPPED]** |
| B2 | All darks are hue-tinted toward the brand; ours are pure `rgba(0,0,0,…)` which greys the card out. | Derive `--mh-shadow-rgb` from the resolved ground (keep hue, drop sat, floor lightness); elevation tokens and cutout depth consume it. | **[SHIPPED]** |
| B3 | Surfaces read as lit material (2–3% micro-gradient + lit top edge), not flat hex fills. | Emit `--mh-ground-gradient` (lit→shaded primary, APCA-gated against the shaded endpoint); adopt on the flat-ground archetypes; lit-edge inset in raised elevation tokens. | **[SHIPPED]** |
| B4 | Cutouts sit *in* the scene: contact shadow under the subject + layered contour shadow. Ours float (grounding exists only in the relay collage). | Shared cutout-grounding helper from the collage maths: alpha-bbox-placed contact ellipse + two-layer contour shadow via `--mh-shadow-rgb`, on all cutout-mode archetypes. | **[SHIPPED]** |
| B5 | Die-cut sticker outline around cutouts (also masks rembg fringe). | `sticker` photo treatment: 8-direction stacked drop-shadow contour in a role ink — same maths expressible in the motion grade for parity. | **[SHIPPED]** (still + motion outline plumbing) |
| B6 | Frosted-glass chips over photos (backdrop blur + saturate + light border). | `.mh-glass` recipe gated so ink passes APCA against worst-case backdrop; deploy on photo-led chips. | **[SHIPPED]** |
| B7 | Scrim alpha adapts to the actual pixels under the text. | PIL pre-pass sampling the text-box region, stepping scrim alpha until Lc ≥ 60 clears; decision in the explainability sidecar. | **[SHIPPED]** |

### C. Colour system

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| C1 | Full tonal system from one seed (containers, tinted surfaces); our cards use 3 flat hexes + one fixed darken. | Bridge `theming.palette` ramps into `resolved_role_vars_for_brief`: `--mh-surface-2`, `--mh-lift`, accent-container tokens, all APCA-gated; adopt incrementally. | **[SHIPPED]** (`--mh-surface-2`/`--mh-lift` + container/raised/accent-container ramp tokens, C9 mood-shifted) |
| C2 | Neutrals are never pure black/white — they are tinted toward the brand hue. | `_on_color` returns brand-hue-tinted near-black / near-white (APCA-verified, falls back to pure); `--mh-ink-secondary` for meta text. | **[SHIPPED]** |
| C3 | The whole brand palette gets deployed; our `--mh-secondary` is painted **nowhere**. | Adopt `var(--mh-secondary, var(--mh-accent))` for the supporting register (kicker ticks, ledger rules, minor bays) in a first slice of archetypes. | **[PARTIAL]** (first archetype slice) |
| C4 | Photo colours drive the design (Vibrant→accent, DarkMuted→scrim classification). | `classify_swatches()` on the existing k-means palette; tint scrims/washes/glows from it (non-brand-locked paint only), APCA-gated. | **[SHIPPED]** |
| C5 | Colour-cast unification: soft brand wash between "raw photo" and "full duotone". | `wash` photo treatment: `saturate(0.68)` + brand soft-light overlay scaled by `decoration_strength`; scrims untouched so APCA holds; motion twin. | **[SHIPPED]** |
| C6 | Per-node contrast repair + gate-filtered colourway shuffle. | Slot repair through the tonal ladder before full revert; enumerate gate-surviving permutations for the seed walk. | **[PARTIAL]** (per-slot tonal-ladder repair before revert shipped; gate-surviving permutation enumeration for the seed walk remains) |
| C7 | Effects never hardcode colour: our glitch paints fixed magenta/cyan on every brand. | Derive the glitch dyad from the accent (±140° hue rotations, luminance-matched); keep the old dyad only as the no-brand fallback. | **[SHIPPED]** |
| C8 | Grainy gradients: large soft fields are dithered against banding. | feTurbulence noise layer folded into `gradient_mesh` SVG at 4–6%. | **[SHIPPED]** |
| C9 | Mood moves colour (Bright/Muted/Deep derive different palettes). | Mood → derived-tone table for surface/scrim/mesh only (brand hexes never move), APCA re-gated. | **[SHIPPED]** |
| C10 | One-colour brands get wheel-arithmetic companions (complementary accent). | `derive_companion_accent()` (OKLCH +180°, Cohen-Or scored, APCA-gated) behind an operator opt-in flag. | **[SHIPPED]** |

### D. Typography craft

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| D1 | Autofit measures the real font; ours fits everything as Anton off a Helvetica table, so a Bowlby/Grotesk display card can overflow and heroes render small. | Measured per-family width factors (fontTools over the shipped woff2) + pass the pair-resolved display family into every fit call. | **[SHIPPED]** |
| D2 | Size-dependent optical tracking (tight display, open small caps). | `tracking_for_px()` ramp emitted as `--mh-track-*` vars; fitted hero slots consume them; tracking folded into fit width maths. | **[SHIPPED]** |
| D3 | Long names wrap and balance everywhere; ours only on 6 of 34 archetypes. | Threshold-triggered `fit_balanced` (when single-line fit < 0.55× cap) with per-archetype opt-out, verified by a long-name render sweep. | **[SHIPPED]** |
| D4 | The full text-effect vocabulary actually gets used (ours hides half of it from the director) and effects have intensity. | List all 14 tokens + craft guidance in the director prompt; `subtle/standard/loud` intensity tiers. | **[PARTIAL]** (vocabulary + guidance shipped; intensity tiers roadmap) |
| D5 | Curated font *sets* incl. a serif register. | Add one self-hosted serif display via the fonts workflow; pairing table of (display, kicker, body, data) quadruples. | **[SHIPPED]** |
| D6 | Per-word emphasis (one accent word / highlight pill in a headline). | Fact-gated `emphasis_word` DesignSpec field wrapping a literal match, APCA-gated treatments. | **[SHIPPED]** |
| D7 | Rotated/vertical type (spines, skewed slabs, full-arc badge text). | Vertical-rl spines + skew-slab archetypes + full-arc `curve` extension. | **[SHIPPED]** (`poster_spine` vertical spine + `skew_slab` accent lever + full-arc `curve`) |
| D8 | Weight contrast via the shipped variable axes (400↔800, density-coherent). | Register weight vars from density/mood consumed via `font-variation-settings`. | **[SHIPPED]** |
| D9 | Non-Latin names keep a display-weight register. | Self-host Noto Bold/Black cuts under the display aliases. | **[SHIPPED]** |

### E. Photo intelligence

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| E1 | Always-on measured auto-enhance normalises every source photo. | `measure_photo()` + `auto_recipe()` in `photo_adjust.py` (deterministic PIL; empty recipe for healthy photos). | **[SHIPPED]** |
| E2 | Smart crops: multi-scale candidate scoring, thirds placement, headroom, punch-in on distant subjects. | smartcrop-style scorer on the existing saliency grid; thirds snapping as deterministic default. | **[SHIPPED]** |
| E3 | Filter presets carry a tinted overlay + one intensity knob. | `tint_overlay` op (brand-derived hexes only) + recipe `intensity` lerp. | **[SHIPPED]** |
| E4 | Shaped photo masks: arch, blob, torn edge — plus the offset echo. | `photo_frame_shape` lever on windowed archetypes (deterministic seeded shapes). | **[SHIPPED]** |
| E5 | The pop-out composition (subject breaking the frame). | `frame_breakout` archetype from existing alpha-bbox + double-paint machinery. | **[SHIPPED]** |
| E6 | Vignettes centre on the subject, not the canvas. | Thread the saliency focus into the pack ground gradients (needs motion parity plumbing). | **[SHIPPED]** (still + motion parity) |

### F. Systemic (the floor Canva enforces by review)

| # | Canva is better because… | Build | Status |
|---|---|---|---|
| F1 | Design-token substrate (spacing scale, shared components) under every template. | `--mh-sp-*` canvas-scaled scale + shared component CSS; migrate archetypes incrementally with an on-scale lint. | **[PARTIAL]** (`--mh-sp-*` scale + shared component CSS + footer/lockup migration shipped, guarded by the `test_layout_spacing` ratchet; per-archetype migration ongoing) |
| F2 | One design reflows across all aspect ratios. | Geometry context vars (`--mh-margin/--mh-col/--mh-short`) + calc() migration, byte-identical on certified formats. | **[PARTIAL]** (`--mh-short`/`--mh-margin`/`--mh-col` geometry context vars + calc() substrate shipped; per-archetype reflow migration ongoing) |
| F3 | Layout admission review → automated archetype lint (margins, overlaps, single dominant element, empty-slot collapse). | `tests/test_archetype_lint.py` parametrised over the catalog. | **[SHIPPED]** (static hex/font lints always-on; rendered structural sweep opt-in via `MEDIAHUB_ARCHETYPE_LINT=1`) |
| F4 | Content-fit layout pick (long name → multiline-capable layout; data-rich → stat-slot layout). | `score_archetype(card)` eligibility filter in front of the existing seeded walk. | **[SHIPPED]** |
| F5 | Post-compose sanity: no silent font substitution, no >1.5× raster upscale, sRGB-pinned exports. | `document.fonts.check` assertion + naturalWidth guard + `--force-color-profile=srgb`. | **[SHIPPED]** |
| F6 | Measured layout scoring (whitespace band, centroid balance, collision reject) picking among K candidate packs. | Deterministic evaluate()-based scorer over the seeded candidate walk. | **[ROADMAP]** |
| F7 | Decoration that overlaps content edges (anchored badges/tabs/tape with seeded rotation). | Declarative overlap anchors in layouts + an overlap accent class in style packs. | **[SHIPPED]** (still + motion) |
| F8 | Physical panel silhouettes (ticket stubs, notches, perforation) and large expressive motifs (speed bands, bursts, variable halftone). | Component CSS + new `ACCENT_GEOS` motif class (weight-capped). | **[SHIPPED]** |
| F9 | Medal chrome: specular ramps + bevels so gold visibly outranks silver. | Deterministic 7-stop ramp from the medal tint, gradient-clipped numerals + bevelled chips behind the APCA gate. | **[SHIPPED]** (still + motion) |

---

## Part 3 — What shipped in this change (build log)

See the PR description for the diff-level summary. Everything shipped follows
the house rules: deterministic (same brief + seed → same PNG), brand-locked
(all colour via resolved `--mh-*` roles or maths on them), APCA-gated where
ink meets ground, self-hosted fonts only, no generative pixels, and
byte-identical output wherever a lever is absent.

The canva-roadmap build wave has since closed nearly all of the outstanding
rows: all of A–E's depth/colour/typography/photo levers ship (A5, B5–B7, C1,
C4, C9, C10, D5–D9, E2–E6), and the systemic floor now carries the archetype
lint (F3), content-fit archetype scoring (F4), the render-time floor (F5) and
the decoration/motif/medal-chrome levers (F7–F9). What remains, honestly:

- **[PARTIAL]** — **C6** (per-slot contrast repair shipped; gate-surviving
  permutation enumeration for the seed walk remains), **F1** (spacing scale +
  component CSS + first migrations shipped; per-archetype migration ongoing
  behind the `test_layout_spacing` ratchet), **F2** (geometry context vars +
  calc() substrate shipped; per-archetype reflow migration ongoing), plus the
  earlier **C3** (`--mh-secondary` deployed on a first archetype slice) and
  **D4** (effect vocabulary + guidance shipped; `subtle/standard/loud`
  intensity tiers roadmap).
- **[ROADMAP]** — **F6** (measured layout scoring over K candidate packs) is
  the sole fully-unbuilt row; its concrete build lives in the corresponding gap
  dossier (workflow run `wf_821d999c-70e`).
