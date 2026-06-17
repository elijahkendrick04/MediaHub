# Background patterns (sprint registry)

Roadmap **R1.4**. Add a new background pattern as its **own file** here — never edit
`StoryCard.tsx`'s `bgPatternFor` switch.

```ts
// patterns/checkerboard.ts
import type { Roles } from "../registry";
const pattern = (roles: Roles): string => `url("data:image/svg+xml;utf8,…")`;
export default { name: "checkerboard", pattern };
```

`name` is the `background_style` brief token. Return a CSS `url(...)` string (or `""`).
Keep it monochrome (accent role) and low-opacity so it reads as texture. The pattern
is a **pure function of `roles`** — no RNG, no time source — so the motion render stays
frame-pure (the tile drifts via `StoryCard`'s `PatternLayer` parallax channel; it never
self-animates). Inline the small `alpha`/`enc` helpers per file rather than sharing a
module, so each pattern stays a self-contained, conflict-free drop-in.

## Shipped (R1.4)

`checkerboard` · `diamonds` · `circuit` · `organic-waves` · `hexmesh` · `concentric`.
Each is keyed by its `background_style` token and rendered automatically by
`bgPatternFor`'s registry fall-through once a brief emits that token — no
`StoryCard.tsx` edit. `tests/test_sprint_patterns.py` pins the drop-in contract
(shape, naming, accent-only colour, frame-purity, valid SVG data URI).
