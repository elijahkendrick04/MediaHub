# Mood → spring configs (sprint registry)

Roadmap **R1.26**. Add a new mood's spring config as its **own file** here — never
edit `StoryCard.tsx`'s `springConfigFor`.

```ts
// springs/victorious.ts
import type { SpringConfig } from "../registry";
const config: SpringConfig = { damping: 14, stiffness: 130, mass: 0.7 };
export default { name: "victorious", config };
```

`name` is the lowercased mood token. Built-in moods (calm/electric/celebratory…)
still win; extras only resolve moods the built-ins don't recognise.
