# Additive overlay layers (sprint registry)

Roadmap **R1.3 / R1.6 / R1.8 / R1.9 / R1.10 / R1.11 / R1.22 / R1.23 / R1.24 / R1.25**.
Capabilities that *augment* every card (subtitle/caption burn-in, ambient motion, photo
scrims/filters/cutout compositing, text effects, colour-role transitions, animated logo,
staggered reveals) are additive overlays — add each as its **own file** here, rendered
over the scene in `order`. Never edit the shared scene components.

`captions.tsx` (R1.3) reads the frame-timed track `visual/subtitle_burn.py` puts in
`card.captionsJson` and paints one APCA-gated cue at a time over a brand-ground scrim;
it returns null (no-op) when the prop is empty.

```tsx
// layers/ambient_drift.tsx
import type { SceneComponent } from "../registry";
const Layer: SceneComponent = ({ ctx }) => { /* additive overlay */ };
export default { Layer, order: 10 };
```

Layers receive the full `SceneCtx` (frame, fps, roles, anim, dims). Pure function of
the frame. Higher `order` paints later (on top).
