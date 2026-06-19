import type { IntentProgram } from "../registry";
import { entranceChannels } from "../../../motion/compile";

/**
 * `pop` — a scale punch with overshoot (Adobe's "Pop"). The card grows from
 * small with a back-eased curve so it bounces just past full size and settles.
 * Mood gates the overshoot the way `bounce_in` does: a stoic / minimal / DQ-style
 * card swaps to the clean `scale_in` preset (no overshoot), a celebration keeps
 * the punch. Both presets come from the motion vocabulary
 * (`src/mediahub/motion/vocabulary.py`); compiled, not hand-tuned. Pure function
 * of the frame.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, mood, base) => {
  const m = (mood || "").toLowerCase();
  const subdued =
    m.includes("calm") ||
    m.includes("stoic") ||
    m.includes("minimal") ||
    m.includes("precise");
  return entranceChannels(subdued ? "scale_in" : "pop", frame, fps, base);
};

export default { name: "pop", program };
