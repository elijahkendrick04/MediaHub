// springs/playful.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: two visible bounces before it settles. The lowest
// damping of the set over a stiff spring reads as bouncy and light-hearted — a
// grin. Forward-looking: resolves only when a director emits this exact mood.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 8, stiffness: 180, mass: 0.65 };

export default { name: "playful", config };
