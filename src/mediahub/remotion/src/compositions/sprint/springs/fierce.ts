// springs/fierce.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: an aggressive, weighted strike. High stiffness drives
// it hard, but a touch more mass and damping than `explosive` keeps the recoil
// controlled — predatory rather than chaotic. There is power behind the punch,
// and it lands with intent instead of flailing.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 13, stiffness: 150, mass: 0.75 };

export default { name: "fierce", config };
