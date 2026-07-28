import { Easing, interpolate } from "remotion";
import type { IntentProgram } from "../registry";

/**
 * `text_scramble` — a deterministic typewriter/scramble "decode" of the result
 * string. The value's characters are present from frame 0 (length-preserving,
 * so nothing reflows), each position spinning through decoy glyphs until it
 * settles left-to-right onto its true glyph — the whole string decoding into
 * the EXACT verified value by the end of the build phase.
 *
 * The decode itself lives in StoryCard's `scrambleReveal`, driven by the
 * `textRevealProgress` channel this programme ramps 0→1 over the same ~5–30%
 * build window `count_up` uses for `resultProgress`. Every other intent leaves
 * `textRevealProgress` at 1 (identity), so this is the only programme that
 * decodes the string — no other card changes. A calm hero/secondary/chip fade
 * carries the surrounding layers so they still land while the number resolves.
 *
 * Frame-pure: `textRevealProgress` is a pure `interpolate(frame, …)`; the glyph
 * choice inside `scrambleReveal` is an integer hash of (variationSeed, position,
 * quantised-progress-tick) — no wall-clock or random source of any kind.
 */
const program: IntentProgram = (
  frame,
  _fps,
  durationInFrames,
  _mood,
  base,
) => {
  // Beat-proportional keyframes (mirrors StoryCard's `at`): fractions of the
  // clip so a short reel beat and a long story distribute the same rhythm.
  const at = (f: number) => 3 + (durationInFrames - 3) * f;
  const clampRight = { extrapolateRight: "clamp" as const };

  return {
    ...base,
    // The number is the statement: hold the hero block on and let the decode
    // carry the energy, with a calm supporting fade around it.
    heroY: 0,
    heroOpacity: interpolate(frame, [at(0.0), at(0.09)], [0, 1], clampRight),
    secondaryOpacity: interpolate(frame, [at(0.04), at(0.14)], [0, 1], clampRight),
    resultOpacity: interpolate(frame, [at(0.02), at(0.075)], [0, 1], clampRight),
    resultScale: 1,
    chipOpacity: interpolate(frame, [at(0.16), at(0.25)], [0, 1], clampRight),
    // The decode window: 0→1 over ~5–30% of the clip, then held at 1 (the
    // verbatim value) for the rest — the same build phase count_up resolves in.
    textRevealProgress: interpolate(frame, [at(0.05), at(0.3)], [0, 1], {
      ...clampRight,
      extrapolateLeft: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
  };
};

export default { name: "text_scramble", program };
