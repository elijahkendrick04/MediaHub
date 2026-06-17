# Reel overlay layers (sprint registry)

Additive overlays rendered over the whole meet reel — decorative cover/outro
flourishes, progress rails, persistent lower-thirds, watermarks. Add each as its
**own file** here; `reelRegistry.ts` auto-discovers the folder via `require.context`,
so parallel sessions never edit `MeetReel.tsx`.

```tsx
// reel/progress_rail.tsx
import type { ReelLayer } from "../reelRegistry";
const Layer: ReelLayer = ({ ctx }) => { /* additive overlay using ctx.frame… */ };
export default { Layer, order: 10 };
```

The structural reel surfaces (beat rhythm R1.12, stats R1.13, transitions R1.14,
cover/outro R1.30) each own a distinct region of `MeetReel.tsx` and so are edited
there directly — they never collide with one another.
