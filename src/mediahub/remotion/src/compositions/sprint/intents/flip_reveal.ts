import { Easing, interpolate, spring } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `flip_reveal` — elements turn face-up one after another, like cards being
 * flipped onto a table. The hero flips open first on a decisive exponential
 * snap (a compressed scale springing to full), then the result flips a
 * half-beat behind it; a soft settle spring locks the chrome in so nothing
 * ends on a mechanical hard stop.
 *
 * There is no rotation channel in AnimChannels, so the "flip" is expressed
 * honestly as a sharp compressed-scale reveal from a near-zero origin — which
 * reads as a turn, and keeps the programme a pure function of the frame. This
 * differs from `scale_in` (a gentle simultaneous 0.82 -> 1.0) by being sharp,
 * sequential, and from a much tighter origin.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, _mood, base) => {
  const flipEase = {
    extrapolateLeft: "clamp" as const,
    extrapolateRight: "clamp" as const,
    easing: Easing.out(Easing.exp),
  };

  // Hero turns face-up first; the result, the heavier card, a half-beat later.
  const heroFlip = interpolate(frame, [3, fps * 0.5], [0, 1], flipEase);
  const resultFlip = interpolate(frame, [fps * 0.45, fps * 0.95], [0, 1], flipEase);
  // The chrome doesn't flip — it just clicks into place on a quiet settle.
  const settle = spring({
    frame: Math.max(0, frame - fps * 0.9),
    fps,
    config: { damping: 16, stiffness: 130, mass: 0.7 },
  });

  return {
    ...base,
    heroY: 0, // a flip turns; it does not travel
    heroOpacity: interpolate(frame, [3, fps * 0.22], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    heroScale: interpolate(heroFlip, [0, 1], [0.36, 1.0]), // compressed -> full: the turn
    secondaryOpacity: interpolate(frame, [fps * 0.6, fps * 1.05], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
    resultOpacity: interpolate(frame, [fps * 0.45, fps * 0.68], [0, 1], {
      extrapolateRight: "clamp",
    }),
    resultScale: interpolate(resultFlip, [0, 1], [0.32, 1.0]),
    chipOpacity: interpolate(settle, [0, 1], [0, 1]),
  };
};

export default { name: "flip_reveal", program };
