# Typography

Type carries most of a result card. Adapted from HyperFrames' typography
craft (Apache-2.0, `vendor/hyperframes-skills-main/`), constrained to
MediaHub's fixed, self-hosted type palette.

## The palette is fixed — the craft is in the use

Seven families, self-hosted on every surface (`layouts/_shared.css`,
`remotion/src/fonts.ts`, `web/static/theme/fonts.css`):

| Family | Register | Voice |
| --- | --- | --- |
| Bebas Neue | Display, condensed | Scoreboard, athletic, vertical |
| Anton | Display, heavy | Poster impact, slab confidence |
| Bowlby One | Display, rounded | Playful, junior-club warmth |
| Playfair Display 400–900 | Display, serif | Editorial, elegant, quote register |
| Space Grotesk 500/700 | Text/display hybrid | Contemporary, technical edge |
| Inter 400/800 | Text | Neutral information carrier |
| JetBrains Mono 500/700 | Mono | Data, splits, timestamps, labels |

Pairings are curated quadruples — `graphic_renderer/type_pairs.py` binds an
atomic (display, kicker, body, data) set per `typography_pair`, seed-keyed
with mood subsets; the data register never leaves JetBrains Mono.

Never add a family ad hoc and never reference a CDN — the refresh path is
`scripts/fetch_renderer_fonts.py` / `fetch_fonts.py` plus the test guard
(`tests/test_self_hosted_fonts.py`). Within the palette, the levers are
pairing, weight, optical size, tracking, case, and (in motion) entrance.

## Registers: voices in a conversation, not sizes on a scale

Assign families to *communicative modes*, then keep the assignment stable
across the card (and across the pack):

- **One voice performs, one recedes.** One expressive display family per
  card; the second family carries information quietly. Two display faces
  shouting on one card cancel each other.
- **Cross registers when pairing.** Display + text (Anton + Inter), text +
  mono (Space Grotesk + JetBrains Mono). Never two near-alike faces —
  similarity without identity reads as a mistake the viewer feels but
  can't name.
- **Data speaks mono.** Splits, deltas, dates, lane/heat labels in
  JetBrains Mono make the facts feel instrumented — and separate the
  data voice from the headline voice.
- **The brief's `typography_pair` is the decision** — execute it; don't
  re-decide per element. If a pairing is wrong for a mood, that's a
  director/vocabulary fix, not an inline override.

## Weight and contrast

- Weight contrast must be visible at feed-thumbnail size: Inter 400 vs
  800, Space Grotesk 500 vs 700 *plus* a size jump. 400-vs-600-same-size
  is web subtlety that vanishes at arm's length.
- Hierarchy needs ≤3 levels visible at a glance: hero, support, metadata.
  If a card has five type sizes, it has no hierarchy.
- Case is a register tool: Bebas/Anton are caps-native (display lines);
  keep sentence case available for quotes (`quote_led_recap`) so the
  card's one humane element reads as speech, not signage.

## Optical corrections (the invisible 10%)

- **Light-on-dark reads heavier and tighter** than the same setting on
  light. On dark grounds prefer the lighter available weight for body-size
  text and open line-height slightly (+0.05–0.1).
- **Track display sizes tight** (−0.02 to −0.04em) — large condensed caps
  set loose fall apart into letters; PNG compression exaggerates it.
- **Track small caps/labels open** (+0.04 to +0.12em) — small type set
  tight smears at DPR 2 feed scale.
- Don't fake weights or condense via `transform: scaleX` — use the real
  cuts; faux distortion is visible in the strokes.

## OpenType for data

- `font-variant-numeric: tabular-nums` on every time, split column, delta
  and counter — proportional digits ruin vertical alignment in
  `editorial_numbers_grid` / `stat_stack_sidebar` and wobble in motion
  count-ups.
- `all-small-caps` for unit/label abbreviations (PB, SC, LC) where the
  family supports it — less shouting than full caps at small sizes.
- Keep ligatures off in mono data (`font-variant-ligatures: none`).

## Fit is part of the design

`autofit.py::fit_font_px` exists because "Annabelle Featherstonehaugh-
Smythe" and "4×100m Medley Relay" are normal inputs, not edge cases:

- Design each text slot around its *longest realistic* string, then let
  `fit_font_px` close the gap deterministically (it errs slightly small —
  safe).
- A name must never truncate, ellipsise, or overflow its panel — that's a
  trust bug in a results product.
- Avoid manual `<br>` in fact strings; let measured wrapping break lines.
  Deliberate stacked display lines (one word per line) are a layout
  choice, made in the archetype, not in the data.
- Glanceability budget: a feed viewer gives a card ~2 seconds. The hero
  fact must land in one fixation — if it competes with four same-weight
  lines, refit the hierarchy, not the font size.
