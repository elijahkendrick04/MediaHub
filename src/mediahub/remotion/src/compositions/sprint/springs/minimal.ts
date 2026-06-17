// springs/minimal.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: quiet and undramatic. A light mass with firm damping
// settles promptly and cleanly with zero overshoot, so the motion reads as a
// restrained fade-into-place rather than an entrance. The understated curve for
// editorial, type-forward cards that want presence without performance.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 30, stiffness: 95, mass: 0.6 };

export default { name: "minimal", config };
