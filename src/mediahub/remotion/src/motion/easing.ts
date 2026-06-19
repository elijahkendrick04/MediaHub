// Remotion easing from the generated motion-vocabulary tokens.
//
// Each easing token carries the same cubic-bézier control points the CSS target
// uses, so a preset eases identically in a reel and in the browser. We hand them
// straight to Remotion's `Easing.bezier`.

import { Easing } from "remotion";
import { MOTION_TOKENS } from "./tokens.generated";

export function easingFor(name: string): (t: number) => number {
  const bezier = MOTION_TOKENS.easings[name]?.bezier;
  if (!bezier || bezier.length < 4) {
    return Easing.linear;
  }
  const [x1, y1, x2, y2] = bezier;
  // Bézier control points may overshoot (y outside [0,1]) for back-eases — that
  // is the intended character; Remotion's Easing.bezier handles it.
  return Easing.bezier(x1, y1, x2, y2);
}
