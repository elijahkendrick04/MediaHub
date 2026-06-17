// springs/contemplative.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a serene, reflective drift. Low stiffness and high
// damping ease it in slowly and smoothly with no overshoot, while a balanced
// mass keeps it weightless rather than heavy — thoughtful, unhurried, the pause
// of a reflective recap. Calmer even than the built-in `calm`, but not as
// leaden as `melancholic`.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 33, stiffness: 55, mass: 1.0 };

export default { name: "contemplative", config };
