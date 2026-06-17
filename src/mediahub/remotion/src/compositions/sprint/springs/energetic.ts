// springs/energetic.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a playful, buoyant bounce. The lightest mass of the
// set with low damping gives a lively, repeated give before it settles — upbeat
// and spirited rather than the single hard recoil of `explosive`. The kinetic
// joy of a team on a roll.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 11, stiffness: 135, mass: 0.5 };

export default { name: "energetic", config };
