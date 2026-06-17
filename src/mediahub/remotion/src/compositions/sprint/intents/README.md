# Motion-intent programmes (sprint registry)

Roadmap **R1.1**. Add a new motion language as its **own file** here — never edit
`StoryCard.tsx`'s `animProgram` switch. `registry.ts` auto-discovers this folder
via `require.context` at build time, so parallel sessions never collide.

```ts
// intents/bounce_in.ts
import type { IntentProgram } from "../registry";
const program: IntentProgram = (frame, fps, durationInFrames, mood, base) => ({
  ...base,
  // …compute channels as a pure function of the frame…
});
export default { name: "bounce_in", program };
```

`name` MUST be the exact `motion_intent` token the design-spec director emits
(add it to `creative_brief/design_spec` via that file's sprint-intents package too,
so the still↔motion parity test sees it). Pure function of the frame only — no
`Math.random`, no clock.
