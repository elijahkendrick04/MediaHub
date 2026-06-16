// springs/precise.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: fast and exact. High stiffness with a light mass
// moves it quickly, but the high damping makes it stop dead on target with no
// overshoot at all — a clean, surgical arrival. This is the `precise`
// signature: the speed of `electric` without the bounce.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 26, stiffness: 130, mass: 0.6 };

export default { name: "precise", config };
