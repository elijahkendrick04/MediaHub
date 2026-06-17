import { Easing, interpolate, spring } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `bounce_in` — a playful, celebratory arrival. The hero DROPS in from above
 * and bounces to rest on a low-damping spring (the overshoot IS the language),
 * and the result PUNCHES up in scale a beat later as the peak moment. The
 * supporting copy and chrome settle calmly underneath so the bounce reads as
 * deliberate, not chaotic.
 *
 * Mood gates the bounce, the way snap_in_then_settle lets the mood flavour its
 * settle: a celebration earns the overshoot, but a stoic / minimal / DQ-style
 * card damps it to a single clean settle. Pure function of the frame only.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, mood, base) => {
  const m = (mood || "").toLowerCase();
  const subdued =
    m.includes("calm") ||
    m.includes("stoic") ||
    m.includes("minimal") ||
    m.includes("precise");

  // Hero: from above, with (or without) a visible bounce.
  const heroBounce = spring({
    frame: Math.max(0, frame - 3),
    fps,
    config: subdued
      ? { damping: 13, stiffness: 150, mass: 0.7 } // one gentle settle
      : { damping: 7, stiffness: 200, mass: 0.7 }, // two visible bounces
  });
  // Result: a snappier bounce on its own delay — a different spring, so the two
  // entrances never share an ease.
  const resultBounce = spring({
    frame: Math.max(0, frame - 9),
    fps,
    config: subdued
      ? { damping: 14, stiffness: 170, mass: 0.6 }
      : { damping: 9, stiffness: 240, mass: 0.6 },
  });

  return {
    ...base,
    heroY: interpolate(heroBounce, [0, 1], [-64, 0]), // drops from above, overshoots past 0
    heroOpacity: interpolate(frame, [3, fps * 0.3], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    heroScale: interpolate(heroBounce, [0, 1], [0.92, 1.0]),
    // Calmer cubic fade on the event line — contrast against the two springs.
    secondaryOpacity: interpolate(frame, [fps * 0.45, fps * 0.95], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
    resultOpacity: interpolate(frame, [fps * 0.3, fps * 0.6], [0, 1], {
      extrapolateRight: "clamp",
    }),
    resultScale: interpolate(resultBounce, [0, 1], [0.72, 1.0]), // bounces up into place
    chipOpacity: interpolate(frame, [fps * 0.8, fps * 1.3], [0, 1], {
      extrapolateRight: "clamp",
    }),
  };
};

export default { name: "bounce_in", program };
