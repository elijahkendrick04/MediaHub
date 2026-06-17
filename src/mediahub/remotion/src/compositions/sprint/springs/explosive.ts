// springs/explosive.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a violent snap. The lightest-but-one mass and the
// highest stiffness fire the hero toward its mark almost instantly, while the
// low damping lets it punch past the target and recoil — the overshoot IS the
// "explosive" read. Snappier and bouncier than the built-in `electric`.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 10, stiffness: 170, mass: 0.55 };

export default { name: "explosive", config };
