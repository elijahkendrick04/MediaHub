// springs/resolute.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a single firm settle with minimal overshoot. High
// damping over a stiff spring lands with conviction and no wobble — decisive.
// Forward-looking: resolves only when a director emits this exact mood.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 22, stiffness: 200, mass: 0.8 };

export default { name: "resolute", config };
