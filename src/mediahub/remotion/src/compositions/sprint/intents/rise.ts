import type { IntentProgram } from "../registry";
import { entranceChannels } from "../../../motion/compile";

/**
 * `rise` — a calm lift from below (Canva's "Rise"). The hero settles up and
 * fades over a gentle cubic, the result and chrome following in staggered
 * order. Unlike the spring-driven `bounce_in`, this entrance is compiled from
 * the motion-vocabulary tokens (`src/mediahub/motion/vocabulary.py::rise`) — the
 * same keyframe data the CSS surface uses, so the movement is identical on every
 * surface. Pure function of the frame.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, _mood, base) =>
  entranceChannels("rise", frame, fps, base);

export default { name: "rise", program };
