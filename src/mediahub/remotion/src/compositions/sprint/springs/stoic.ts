// springs/stoic.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: immovable and unhurried. The heaviest damping kills
// any overshoot outright, while the high mass and modest stiffness make the
// arrival deliberate and resolute — nothing bounces, nothing rushes. A shade
// firmer and weightier than the built-in `calm`.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 34, stiffness: 70, mass: 1.2 };

export default { name: "stoic", config };
