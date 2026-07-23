import type { IntentProgram } from "../registry";
import { entranceChannels } from "../../../motion/compile";

/**
 * `drop_in` — the hero falls from ABOVE and overshoots to rest (a back-eased
 * translateY from a negative offset), the opposite direction to `rise`. Where
 * `bounce_in` uses a hand-tuned Remotion spring, `drop_in` is compiled straight
 * from the motion-vocabulary token (`src/mediahub/motion/vocabulary.py::drop_in`),
 * so the same drop renders identically as CSS in the browser. Pure function of
 * the frame.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, _mood, base, stagger) =>
  entranceChannels("drop_in", frame, fps, base, stagger);

export default { name: "drop_in", program };
