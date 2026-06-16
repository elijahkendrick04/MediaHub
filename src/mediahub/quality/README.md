# quality

Exact, no-AI checks on the content the generator produces.

- **variant_metrics** — measures how varied and non-repetitive a batch is, so a
  set of posts doesn't all look and sound the same.
- **compliance** — the legibility gate: does a card's text actually read on its
  background? (APCA contrast, pass/fail.)
- **colour_audit** — the per-card colour-accessibility report: APCA *and* WCAG
  contrast for every text pair, plus a colourblind simulation (deuteranopia /
  protanopia / tritanopia) that re-checks the colours and previews how the card
  looks to a colourblind viewer.

All deterministic colour-science / maths — no AI, no guessing.
