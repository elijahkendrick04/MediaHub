# Scene modes (sprint registry)

Roadmap **R1.2**. Add a new structurally-distinct scene as its **own file** here —
never edit `StoryCard.tsx`'s scene switch.

```tsx
// scenes/radial_rings.tsx
import type { SceneComponent } from "../registry";
const Scene: SceneComponent = ({ ctx }) => { /* full-frame scene */ };
export default { archetype: "radial_rings", Scene };
```

`archetype` is the still-engine archetype id (drop the matching
`graphic_renderer/layouts/v2/<archetype>.html` in its own session — G1.1). When a
card's archetype matches, this scene replaces the built-in scene; the parity test
counts it as covered.
