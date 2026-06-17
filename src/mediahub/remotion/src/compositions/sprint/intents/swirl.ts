import { interpolate, spring } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `swirl` — a spiralling arrival that keeps breathing. The hero scales up out
 * of a damped overshoot while the background SWAYS on a slow sinusoid and the
 * photo slowly pushes, so the whole frame feels like it is settling out of a
 * swirl. The sway is the one ambient motion that sustains through the breathe
 * phase (frame-pure `Math.sin`, never a CSS loop), so the card never goes
 * dead-still after the entrance.
 *
 * Distinct from `parallax` (linear background drift, no hero motion) and
 * `scale_in` (no sustained ambient motion). Energetic moods spiral a touch
 * wider; the result is unchanged either way.
 */
const program: IntentProgram = (frame, fps, durationInFrames, mood, base) => {
  const m = (mood || "").toLowerCase();
  const energetic =
    m.includes("electric") ||
    m.includes("explosive") ||
    m.includes("celebratory") ||
    m.includes("fierce");

  // Settles out of a damped overshoot — the spiral coming to rest.
  const swirlSpring = spring({
    frame: Math.max(0, frame - 4),
    fps,
    config: energetic
      ? { damping: 10, stiffness: 120, mass: 0.9 }
      : { damping: 14, stiffness: 100, mass: 0.9 },
  });

  // Sustained sway: a slow sinusoid across the clip (sin(0) = 0, so it opens at
  // rest and never jump-cuts). Amplitude in px at design scale, kept small.
  const sway = Math.sin((frame / fps) * Math.PI * 0.9) * (energetic ? 22 : 14);

  return {
    ...base,
    heroY: interpolate(swirlSpring, [0, 1], [54, 0]),
    heroOpacity: interpolate(frame, [4, fps * 0.4], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    heroScale: interpolate(swirlSpring, [0, 1], [0.6, 1.0]), // spirals up to full
    secondaryOpacity: interpolate(frame, [fps * 0.4, fps * 0.95], [0, 1], {
      extrapolateRight: "clamp",
    }),
    resultOpacity: interpolate(frame, [fps * 0.55, fps * 1.05], [0, 1], {
      extrapolateRight: "clamp",
    }),
    resultScale: interpolate(swirlSpring, [0, 1], [0.84, 1.0]),
    chipOpacity: interpolate(frame, [fps * 0.9, fps * 1.5], [0, 1], {
      extrapolateRight: "clamp",
    }),
    bgDrift: sway, // the sustained swirl the scene breathes in
    photoScale: interpolate(frame, [0, durationInFrames], [1.0, 1.06]), // slow push under it
  };
};

export default { name: "swirl", program };
