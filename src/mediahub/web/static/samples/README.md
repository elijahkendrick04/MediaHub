# Sample output thumbnails (landing page)

These four `.svg` files are the inline thumbnails used by the **UI 1.3** display
headline on the home page — the Samara-inspired band that reads
*"From a results sheet [img] to a story [img], a feed graphic [img] and a
reel [img]."* (built in `web.py` → `home()`, styled in
`../theme/theme-components.css` under "UI 1.3").

They show the shape of the pipeline at a glance:

- **`results-sheet.svg`** — the **input**: a Hytek-style A4 results listing
  (Event 14, 100m freestyle) on paper-cream. This is what a club uploads.
- **`story-card.svg`** — a story-card **output** (9:16): athlete name, the time
  as the hero numeral, the PB delta on a medal-gold chip.
- **`feed-graphic.svg`** — a feed-graphic **output**: a podium bar chart
  (gold / silver / bronze) of the night's finals.
- **`reel.svg`** — a motion-reel **output**: a branded poster frame with the
  play affordance and a progress timeline.

## Why hand-built SVG (and not a pixel export)

These are **first-party, brand-accurate illustrations of the output formats**,
not literal engine renders. The real still graphics come out of the
Playwright/Chromium renderer (`graphic_renderer/`) and reels out of Remotion as
PNG/MP4 — heavy artefacts that don't belong checked-in as marketing chrome. Hand
authoring them as tiny SVGs keeps them:

- **self-contained** — pure vector, **no external fetch** (no remote `<image>`,
  no webfont `@import`, no CDN); they honour the same no-external-fetch rule the
  fonts do, and are served straight from `/static/samples/`.
- **on-brand** — the exact "Podium After Dark" palette (lane-yellow `#D4FF3A`,
  medal-gold `#F4D58D`, paper-cream `#F5F2E8`, pit-wall black `#0A0B11`) and the
  same facts as the larger sample row further down the page.
- **crisp + tiny** — a few KB each, sharp at any inline size.

All four share a `0 0 144 200` viewBox so the row reads evenly inline. If you
restyle the brand palette, update the hex values here to match (they're
hard-coded because an `<img>`-loaded SVG can't inherit the page's CSS variables).

Guarded by `tests/test_ui_1_3_inline_headline.py` (presence, well-formedness,
self-containment, served-as-SVG, and the home-page band).
