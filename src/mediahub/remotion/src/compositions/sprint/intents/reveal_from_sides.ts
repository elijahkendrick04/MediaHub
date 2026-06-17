import { Easing, interpolate, spring } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `reveal_from_sides` — a symmetric, centre-out reveal. The result LEADS:
 * it opens from a compressed scale at the centre, as if panels part from the
 * sides to expose the number, on a clean cubic ease. The hero then rises from
 * below to meet it, one beat behind on a soft spring, and the supporting copy
 * and chrome converge last on an exponential so the card resolves as a frame
 * closing around the headline stat.
 *
 * AnimChannels has no horizontal-translate channel, so the "from the sides"
 * reading is delivered honestly as a centre-out result open with converging
 * chrome — a pure function of the frame. Leading with the result (not the
 * hero) is what sets this apart from `scale_in` and `fade_in`.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, _mood, base) => {
  const openEase = {
    extrapolateLeft: "clamp" as const,
    extrapolateRight: "clamp" as const,
    easing: Easing.out(Easing.cubic),
  };

  // The result opens from a centre slit — the reveal, and it leads.
  const open = interpolate(frame, [3, fps * 0.6], [0, 1], openEase);
  // Hero rises from below to meet it, a beat behind, on a softer spring.
  const heroRise = spring({
    frame: Math.max(0, frame - fps * 0.3),
    fps,
    config: { damping: 20, stiffness: 90, mass: 0.8 },
  });

  return {
    ...base,
    heroY: interpolate(heroRise, [0, 1], [70, 0]),
    heroOpacity: interpolate(frame, [fps * 0.3, fps * 0.75], [0, 1], {
      extrapolateRight: "clamp",
    }),
    heroScale: 1,
    secondaryOpacity: interpolate(frame, [fps * 0.6, fps * 1.05], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
    resultOpacity: interpolate(frame, [3, fps * 0.35], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    resultScale: interpolate(open, [0, 1], [0.5, 1.0]), // centre-out open
    // Chrome converges last on a decisive exp — the frame closing in.
    chipOpacity: interpolate(frame, [fps * 0.85, fps * 1.4], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.exp),
    }),
  };
};

export default { name: "reveal_from_sides", program };
