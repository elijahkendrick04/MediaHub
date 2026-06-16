# Accent decorations (sprint registry)

Roadmap **R1.5**. Add a new accent decoration as its **own file** here — never edit
`StoryCard.tsx`'s `accentDecoration` switch.

```tsx
// accents/hexframe.tsx
import type { AccentDecoration } from "../registry";
const decoration: AccentDecoration = (roles, opacity, width, height) => (
  <div style={{ /* margin-safe accent geometry in roles.accent */ }} />
);
export default { name: "hexframe", decoration };
```

`name` is the `accent_style` brief token. Draw in the accent role only, in the
margins, at the supplied opacity.
