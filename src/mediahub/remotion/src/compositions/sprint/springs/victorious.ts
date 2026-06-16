// springs/victorious.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a confident, triumphant arrival. Firm stiffness with
// a single celebratory overshoot lands the result like a flag being planted —
// proud, decisive, just enough bounce to punctuate the win. A shade snappier
// than the built-in `celebratory` cluster.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 14, stiffness: 130, mass: 0.7 };

export default { name: "victorious", config };
