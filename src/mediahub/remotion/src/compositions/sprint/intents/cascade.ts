import { Easing, interpolate, spring } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `cascade` — a waterfall down the card. One even interval governs the whole
 * reveal, top to bottom: the hero line cascades in per word, then the event,
 * then the result (with a small scale pop), then the chrome — each layer one
 * step behind the last, like water down steps.
 *
 * Because the hero owns a per-word reveal via `wordAt`, the hero block's own
 * opacity/translate are held at identity (heroOpacity = 1, heroY = 0) — the
 * `KineticLine` parent multiplies block opacity by word opacity, so driving
 * both would double-fade. This mirrors the `kinetic_type` contract; what makes
 * cascade its own language is the *even, stepped, top-to-bottom* rhythm carried
 * across every layer, not just the words.
 */
const program: IntentProgram = (frame, fps, _durationInFrames, _mood, base) => {
  const fallEase = {
    extrapolateLeft: "clamp" as const,
    extrapolateRight: "clamp" as const,
    easing: Easing.out(Easing.cubic),
  };
  const step = fps * 0.2; // the cascade interval between layers (~6 frames @ 30fps)

  return {
    ...base,
    // Hero words own the top of the waterfall — block held on (see note above).
    heroY: 0,
    heroOpacity: 1,
    heroScale: 1,
    // Each lower layer falls one even step later than the one above it.
    secondaryOpacity: interpolate(
      frame,
      [step * 2, step * 2 + fps * 0.3],
      [0, 1],
      fallEase,
    ),
    resultOpacity: interpolate(
      frame,
      [step * 3, step * 3 + fps * 0.3],
      [0, 1],
      fallEase,
    ),
    resultScale: interpolate(
      frame,
      [step * 3, step * 3 + fps * 0.5],
      [0.9, 1.0],
      fallEase,
    ),
    chipOpacity: interpolate(frame, [step * 4, step * 4 + fps * 0.4], [0, 1], {
      extrapolateRight: "clamp",
    }),
    // Per-word hero cascade — a snappy spring drop, tight even stagger, so even
    // a single-word surname still "falls" into place.
    wordAt: (i: number) => {
      const start = 4 + step * 0.5 * i; // ~3-frame stagger per word
      const s = spring({
        frame: Math.max(0, frame - start),
        fps,
        config: { damping: 18, stiffness: 150, mass: 0.5 },
      });
      return {
        y: interpolate(s, [0, 1], [38, 0]),
        opacity: interpolate(frame, [start, start + fps * 0.22], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      };
    },
  };
};

export default { name: "cascade", program };
