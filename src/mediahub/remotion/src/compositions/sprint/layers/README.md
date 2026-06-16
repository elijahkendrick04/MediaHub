# Additive overlay layers (sprint registry)

Roadmap **R1.6 / R1.8 / R1.9 / R1.10 / R1.11 / R1.22 / R1.23 / R1.24 / R1.25**.
Capabilities that *augment* every card (ambient motion, photo scrims/filters/cutout
compositing, text effects, colour-role transitions, animated logo, staggered reveals)
are additive overlays — add each as its **own file** here, rendered over the scene in
`order`. Never edit the shared scene components.

```tsx
// layers/ambient_drift.tsx
import type { SceneComponent } from "../registry";
const Layer: SceneComponent = ({ ctx }) => { /* additive overlay */ };
export default { Layer, order: 10 };
```

Layers receive the full `SceneCtx` (frame, fps, roles, anim, dims). Pure function of
the frame. Higher `order` paints later (on top).
