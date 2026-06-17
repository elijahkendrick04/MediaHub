// springs/warm.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a soft, inviting ease. Moderate stiffness and mass
// keep it gentle, and the mid-high damping leaves only the faintest give at the
// end — enough to feel alive and human, never bouncy. Slower and softer than
// the neutral default, warmer than the cool `stoic`.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 22, stiffness: 75, mass: 0.9 };

export default { name: "warm", config };
