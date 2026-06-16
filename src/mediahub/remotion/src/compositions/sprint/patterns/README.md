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
Keep it monochrome (accent role) and low-opacity so it reads as texture.
