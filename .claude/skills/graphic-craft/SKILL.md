---
name: graphic-craft
description: MediaHub graphic craft for Playwright-rendered still graphics — result cards, athlete spotlights, meet recaps, story graphics. Use whenever you design, edit, or review graphic_renderer layouts/archetypes, typography, data presentation on cards, background/accent treatments, or respond to "the graphics look samey / boring / generic" feedback. Encodes composition density, type registers, data-weight and variety levers adapted to MediaHub's exact, brand-locked, APCA-gated rendering rules.
---

# Graphic craft

How to make MediaHub's still graphics feel art-directed — composed, dense,
branded, varied — while staying what they must be: factually exact,
brand-exact, deterministic renders.

Craft lineage: adapted for MediaHub from HeyGen's HyperFrames skills
(Apache-2.0; reference copy at `vendor/hyperframes-skills-main/`), rewritten
for the Playwright HTML→PNG stack and MediaHub's non-negotiables. Where this
file and `mediahub-engineering` disagree, `mediahub-engineering` wins.

## The stack (real paths — design against these, don't invent)

- Renderer: `src/mediahub/graphic_renderer/render.py::render_brief` —
  HTML/CSS templates → PNG via headless Chromium (Playwright), DPR from
  `MEDIAHUB_RENDER_DPR` (default 2).
- Layouts: 20 v2 **archetypes** (structural skeletons) under
  `graphic_renderer/layouts/v2/*.html` — the originals
  (`big_number_dominant`, `minimal_type_poster`,
  `full_bleed_photo_lower_third`, `duo_athlete_split`, `ticker_strip`,
  `stat_stack_sidebar`, `magazine_cover`, `centered_medal_spotlight`,
  `editorial_numbers_grid`, `split_diagonal_hero`, `quote_led_recap`,
  `triptych_progression`) plus `cornerstone_numeral`, `horizon_band`,
  `scoreline_versus`, `broadcast_scorebug`, `photo_passepartout`,
  `spotlight_disc`, `index_card`, `mega_surname_bleed`. Shared CSS +
  self-hosted fonts in `layouts/_shared.css` (+ `layouts/fonts/*.woff2`,
  rewritten to `file://` at render time).
- Templates: an archetype is **not** the whole design — the renderer layers a
  **style pack** over it (`graphic_renderer/style_packs.py`): a deterministic,
  coherence-pruned bundle of orthogonal levers (ground treatment × surface
  texture × accent geometry × density). Archetype × pack = the **template
  catalog** — 1,000+ unique, brand-safe, explainable templates. The pack is a
  margin-safe, role-coloured *overlay* injected into each archetype's
  `{{ACCENT_DECORATION}}` slot; it never touches the `--mh-*` role tokens, so
  contrast and still↔motion colour parity are unchanged. Variety lives in the
  pack levers, never in generative pixels.
- Direction: the LLM design-spec director (`creative_brief/ai_director.py`
  → `design_spec.py`) emits a structured spec over closed vocabularies
  (`MOODS`, `ACCENT_TREATMENTS`, `FOCAL_ELEMENTS`, `STAT_KEYS`,
  `COLOUR_ROLE_SLOTS`, `MOTION_INTENTS`); `design_spec.normalise()` rejects
  anything outside them. With no provider, the deterministic floor is
  `archetypes.pick_archetype(seed)` / `pick_archetype_avoiding(seed, recent)`.
  **AI judges, maths renders** — keep that split.
- Colour: `render.resolved_role_vars_for_brief` resolves the `--mh-*` CSS
  custom properties (`--mh-primary`, `--mh-surface`, `--mh-accent`,
  `--mh-secondary`, `--mh-on-primary`, `--mh-on-surface`, `--mh-outline`)
  from the BrandKit's derived palette, APCA-gated, medal tints included.
- Fit & focus: `graphic_renderer/autofit.py::fit_font_px` (deterministic
  binary-search text fitting) and `saliency.focus_position` (deterministic
  photo focus → CSS `object-position`).

## Hard bounds (non-negotiable, inherited)

1. **The card is rendered exactly, not generated.** The time is the time,
   the hex is the brand's hex, the photo is the real athlete. Generative
   imagery is sanctioned only as an abstract background *under* the text
   (`visual/ai_background.py`) — never foreground, stats, people, or logo.
2. **Colour comes from the resolved roles.** Never hardcode a hex in a
   layout; consume `--mh-*` variables. Contrast and medal tints are
   APCA-gated in `theming/` — don't hand-tune around the gate, fix the gate
   input.
3. **Text is measured to fit.** Long names and event titles are normal.
   Use `fit_font_px` (or design for the longest realistic string).
   Truncation and overflow are trust bugs.
4. **Fonts are the seven self-hosted families** (Bebas Neue, Anton, Bowlby
   One, Playfair Display, Space Grotesk, Inter, JetBrains Mono) — never a CDN `<link>`,
   `@import`, or new family outside the fonts workflow
   (`tests/test_self_hosted_fonts.py` guards all surfaces).
5. **Deterministic and explainable.** Same brief + seed → same PNG. Variety
   comes from the brief's levers, not randomness. Every card keeps its
   "why this design" trace.
6. **Still ↔ motion parity.** The motion render mirrors the approved still
   (archetype, roles, photo focus — `tests/test_motion_v2_parity.py`). A
   still-side redesign is a motion-side change too; check both before
   shipping.

## Workflow for any graphic change

1. **Read the brief first** — `archetype`, `mood`, `heroStat`,
   `background_style`, `accent_style`, `typography_pair`, `composition`,
   `photo_treatment`, `decoration_strength` already encode the direction.
2. **Build the layout as zones, then dress it.** Background treatment →
   midground facts → foreground accents. A card with only midground reads
   flat and "generated". → `references/composition.md`
3. **Set the type by register, not by habit.** →
   `references/typography.md`
4. **Give the data weight.** The hero stat is the story — pair it with a
   visual element that makes it tangible. → `references/data-graphics.md`
5. **Self-review against the lazy-defaults list below**, then against the
   brand: every colour a role, every size fitted, APCA clean.
6. **Verify**: render the affected archetypes at story + portrait + square
   sizes with a long-name fixture; run the graphic renderer tests and the
   parity test.

## Lazy defaults to question (the anti-samey list)

The standing complaint is "a standard boring graphic every time"
(`mediahub-engineering/rules/generation-quality.md`). The fix is variety
that stays exact: richer archetype use, varied data emphasis, layout
intelligence — never generative pixels. These are the tells to catch in
review; each is fine *only* as a deliberate choice for this card:

- The same archetype again (rotate via `pick_archetype_avoiding`, or let
  the director's pool diverge — `variation_signature` exists for this).
- Everything centred with equal weight; hero floating in empty space.
- Gradient text; left-edge accent stripe on every card; cyan-on-dark.
- Pure `#000`/`#fff` grounds instead of the brand's tinted roles.
- Identical stat-chip rows on every card regardless of the achievement.
- The same `background_style` ×3 in one content pack.
- Decoration that ignores `decoration_strength` (a stoic club's card
  drowning in confetti dots; a celebratory gold with bare margins).
- A photo cropped to its centre instead of its saliency focus.

A content pack should read like one designer made deliberate per-card
choices — same brand, different decisions.

## References (read on demand)

- `references/composition.md` — frame ≠ web page: density layers, focal
  points, anchoring, split layouts, colour presence at graphic scale.
  **Read for any layout/archetype work.**
- `references/typography.md` — the six-family palette as registers,
  pairing, weight contrast, optical compensation, OpenType for data.
  **Read whenever type changes.**
- `references/data-graphics.md` — making verified numbers feel tangible:
  visual weight, continuity across a pack, honest proportion rules, what
  never to chart.
