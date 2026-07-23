// springs/anticipatory.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a heavy pre-load and rebound. The full mass with low
// damping gives a pronounced wind-up-then-release feel — the coil before a
// dive. Forward-looking: resolves only when a director emits this exact mood.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 9, stiffness: 120, mass: 1.0 };

export default { name: "anticipatory", config };
