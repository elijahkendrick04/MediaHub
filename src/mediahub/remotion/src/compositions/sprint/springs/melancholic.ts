// springs/melancholic.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a slow, weighted descent. The heaviest mass and the
// lowest stiffness draw the motion out into a long, mournful settle, and the
// high damping forbids any lift at the end — it arrives and stays, with no
// rebound. Heavier and slower than every built-in; the gravity of a hard loss.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 32, stiffness: 50, mass: 1.4 };

export default { name: "melancholic", config };
