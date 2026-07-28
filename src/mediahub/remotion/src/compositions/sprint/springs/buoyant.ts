// springs/buoyant.ts — roadmap R1.26 (mood → easing curve).
//
// Easing-curve character: a light, springy overshoot that lifts past its mark
// and floats down — airy and optimistic, softer than energetic's repeated
// give. Forward-looking: resolves only when a director emits this exact mood.
import type { SpringConfig } from "../registry";

const config: SpringConfig = { damping: 10, stiffness: 150, mass: 0.6 };

export default { name: "buoyant", config };
