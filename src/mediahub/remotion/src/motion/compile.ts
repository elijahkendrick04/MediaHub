// Sample the motion vocabulary inside Remotion — frame-pure.
//
// This is the Remotion "compiler target": it turns a preset's keyframe tokens
// (the single source of truth in src/mediahub/motion/, mirrored into
// tokens.generated.ts) into interpolated values via Remotion's `interpolate`
// and the matching `Easing.bezier`. CSS @keyframes do NOT render in Remotion —
// only this frame-pure path does.
//
// `entranceChannels` maps a preset's generic transform channels onto the
// StoryCard AnimChannels, staggering hero → result → chrome by importance (the
// motion-craft choreography rule), so a sprint intent file becomes a one-liner.

import { interpolate, spring } from "remotion";
import type { AnimChannels } from "../compositions/StoryCard";
import { selectRangeFor, selectorRank } from "../compositions/sprint/rangeSelector";
import { easingFor } from "./easing";
import { MOTION_TOKENS, MotionKeyframe, MotionPresetTokens } from "./tokens.generated";

// ---------------------------------------------------------------------------
// Per-glyph reveal (kinetic_type / cascade opt-in)
// ---------------------------------------------------------------------------
//
// The shared, frame-pure per-character reveal channel. Both type-carried intents
// (kinetic_type in StoryCard, cascade in sprint/intents) drive `glyphAt` through
// this one function so their cadence can never drift, and the stagger step is
// read from the token bundle (MOTION_TOKENS.text.glyphStaggerSec) — never hard-
// coded in the TSX.
//
// APCA-safety (the correction the planner flagged): the per-glyph start is
// CLAMPED so the LAST glyph of a line always reaches opacity 1 within the same
// short absolute budget as the per-word channel (~half a second), regardless of
// glyph count. A long hero line therefore can never carry sub-opacity headline
// glyphs into the resolve/hold phase — held text always clears the APCA floor.
//
// Determinism: a small per-glyph phase jitter is a pure integer mix of the
// card's variationSeed and the glyph index (no Math.random / Date.now), so
// sibling cards scatter differently but every render of the same frame is
// bit-stable.
//
// Range selectors: the glyph's stagger RANK (which glyph reveals when) is no
// longer a bare left-to-right index — it flows through the seeded ORDER × SHAPE
// vocabulary in sprint/rangeSelector.ts (reverse / centre-out / seeded scatter,
// eased in/out), picked from (variationSeed, mood). The DEFAULT selector is
// {index, linear} and `selectorRank` returns the raw integer index for it, so a
// card on the identity path reproduces the plain index ramp byte-for-byte.

const GLYPH_REVEAL_SEC = 0.2; // per-glyph opacity fade duration
const GLYPH_BUDGET_SEC = 0.5; // absolute cap: every glyph is opaque by here

/** Deterministic 32-bit hash of (seed, glyphIndex) — frame-pure, no randomness. */
function glyphHash(seed: number, index: number): number {
  let x = (Math.imul(seed | 0, 73856093) ^ Math.imul(index | 0, 19349663)) >>> 0;
  x = Math.imul(x ^ (x >>> 13), 0x5bd1e995) >>> 0;
  return (x ^ (x >>> 15)) >>> 0;
}

/**
 * Reveal glyph `i` (of `total` in its line) for `frame`. Returns the same
 * `{ y, opacity }` shape as the per-word channel. The glyph's stagger RANK is
 * picked by the seeded ORDER × SHAPE range selector (`selectRangeFor` /
 * `selectorRank`); the resulting offset grows with that rank at the tokenised
 * cadence but is clamped to `GLYPH_BUDGET_SEC - GLYPH_REVEAL_SEC`, so the whole
 * line resolves inside the reveal budget whatever the ordering. The DEFAULT
 * selector ({index, linear}, e.g. every restraint mood) makes `rank === i`, so
 * the identity path is byte-identical to the plain per-glyph index ramp.
 */
export function glyphRevealAt(
  i: number,
  total: number,
  frame: number,
  fps: number,
  seed: number,
  mood: string,
): { y: number; opacity: number } {
  const staggerSec = MOTION_TOKENS.text.glyphStaggerSec;
  const revealFrames = fps * GLYPH_REVEAL_SEC;
  const maxStart = Math.max(0, fps * GLYPH_BUDGET_SEC - revealFrames);
  // Seeded ORDER × SHAPE rank — identity ({index, linear}) returns the raw `i`.
  const { order, shape } = selectRangeFor(seed, mood);
  const rank = selectorRank(i, total, seed, order, shape);
  // A deterministic sub-step jitter in [0, 0.6) of one glyph step so cards with
  // different seeds scatter their characters instead of a metronomic wipe.
  const jitter = 0.6 * ((glyphHash(seed, i) % 1000) / 1000);
  const start = Math.min((rank + jitter) * staggerSec * fps, maxStart);
  const s = spring({
    frame: Math.max(0, frame - start),
    fps,
    config: { damping: 16, stiffness: 170, mass: 0.6 },
  });
  return {
    y: interpolate(s, [0, 1], [40, 0]),
    opacity: interpolate(frame, [start, start + revealFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  };
}

const REST: Record<string, number> = {
  opacity: 1,
  translateX: 0,
  translateY: 0,
  scale: 1,
  rotate: 0,
  blur: 0,
};

// ---------------------------------------------------------------------------
// Non-bezier interpolation modes (hold / auto / continuous)
// ---------------------------------------------------------------------------
//
// These mirror the Python `_track_tangents` / `_hermite_at` in
// src/mediahub/motion/vocabulary.py EXACTLY — same finite-difference tangents,
// same Hermite basis — so a preset that opts into a mode samples identically on
// every surface. Pure arithmetic, frame-pure (no Math.random / Date.now).

function sign(x: number): number {
  return x > 0 ? 1 : x < 0 ? -1 : 0;
}

/** Catmull-Rom finite-difference tangents (dv/dt) over the (offset,value) track. */
function trackTangents(kfs: MotionKeyframe[], mode: string): number[] {
  const n = kfs.length;
  const m: number[] = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    if (i === 0) {
      const span = kfs[1].offset - kfs[0].offset;
      m[i] = span === 0 ? 0 : (kfs[1].value - kfs[0].value) / span;
    } else if (i === n - 1) {
      const span = kfs[n - 1].offset - kfs[n - 2].offset;
      m[i] = span === 0 ? 0 : (kfs[n - 1].value - kfs[n - 2].value) / span;
    } else {
      const span = kfs[i + 1].offset - kfs[i - 1].offset;
      m[i] = span === 0 ? 0 : (kfs[i + 1].value - kfs[i - 1].value) / span;
      if (
        mode === "auto" &&
        sign(kfs[i].value - kfs[i - 1].value) !== sign(kfs[i + 1].value - kfs[i].value)
      ) {
        m[i] = 0;
      }
    }
  }
  return m;
}

/** Cubic-Hermite value of segment `kfs[i-1] -> kfs[i]` at `t` (mirrors Python). */
function hermiteAt(
  kfs: MotionKeyframe[],
  i: number,
  t: number,
  mode: string,
): number {
  const a = kfs[i - 1];
  const b = kfs[i];
  const span = b.offset - a.offset;
  if (span <= 0) {
    return b.value;
  }
  const tangents = trackTangents(kfs, mode);
  const m0 = tangents[i - 1];
  const m1 = tangents[i];
  const s = (t - a.offset) / span;
  const s2 = s * s;
  const s3 = s2 * s;
  const h00 = 2 * s3 - 3 * s2 + 1;
  const h10 = s3 - 2 * s2 + s;
  const h01 = -2 * s3 + 3 * s2;
  const h11 = s3 - s2;
  return h00 * a.value + h10 * span * m0 + h01 * b.value + h11 * span * m1;
}

export function presetFor(
  name: string,
  reduced = false,
): MotionPresetTokens | undefined {
  const table = reduced ? MOTION_TOKENS.reduced : MOTION_TOKENS.presets;
  return table[name];
}

/** Value of one preset channel at `frame` (loops wrap; entrances clamp). */
export function sampleChannel(
  preset: MotionPresetTokens,
  channel: string,
  frame: number,
  _fps: number,
  opts?: { delayFrames?: number; speed?: number },
): number {
  const kfs = preset.channels[channel];
  if (!kfs || kfs.length === 0) {
    return REST[channel] ?? 0;
  }
  const delay = opts?.delayFrames ?? 0;
  const speed = opts?.speed ?? 1;
  const dur = Math.max(1, preset.durationFrames / speed);
  let local = frame - delay;
  if (preset.loop) {
    local = ((local % dur) + dur) % dur; // wrap (handles negatives)
  }
  const t = local / dur;
  if (t <= kfs[0].offset) {
    return kfs[0].value;
  }
  const last = kfs[kfs.length - 1];
  if (t >= last.offset) {
    return last.value;
  }
  for (let i = 1; i < kfs.length; i++) {
    const a = kfs[i - 1];
    const b = kfs[i];
    if (t <= b.offset) {
      const mode = b.interp;
      if (mode === "hold") {
        // Step: hold the previous value until this offset, jump AT it.
        return t < b.offset ? a.value : b.value;
      }
      if (mode === "auto" || mode === "continuous") {
        return hermiteAt(kfs, i, t, mode);
      }
      const span = b.offset - a.offset || 1;
      const localSeg = (t - a.offset) / span;
      return interpolate(localSeg, [0, 1], [a.value, b.value], {
        easing: easingFor(b.easing),
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
  }
  return last.value;
}

export type StaggerConfig = {
  hero: number;
  secondary: number;
  result: number;
  chip: number;
};

const DEFAULT_STAGGER: StaggerConfig = { hero: 3, secondary: 6, result: 9, chip: 14 };

/**
 * Resolve an entrance-stagger config from a scale multiplier. `scale === 1` (or
 * a non-positive / non-finite value) returns exactly DEFAULT_STAGGER, so an
 * unscaled card is byte-identical to the fixed pre-config delays. Each delay is
 * scaled, rounded to an integer frame (cross-platform-identical), clamped to a
 * sane band, and forced monotonic non-decreasing so a bad scale can never
 * invert the hero → secondary → result → chip importance sequence.
 */
export function resolveStagger(scale: number): StaggerConfig {
  const s = Number.isFinite(scale) && scale > 0 ? scale : 1;
  const clamp = (v: number) => Math.max(0, Math.min(40, Math.round(v)));
  const hero = clamp(DEFAULT_STAGGER.hero * s);
  const secondary = Math.max(hero, clamp(DEFAULT_STAGGER.secondary * s));
  const result = Math.max(secondary, clamp(DEFAULT_STAGGER.result * s));
  const chip = Math.max(result, clamp(DEFAULT_STAGGER.chip * s));
  return { hero, secondary, result, chip };
}

/**
 * Drive the StoryCard AnimChannels from an entrance preset, staggering the
 * layers by importance. Channels the preset doesn't animate fall back to rest
 * (so a scale-only preset leaves heroY at 0, an opacity-only preset leaves
 * scale at 1), and everything else inherits from `base`. `stagger` defaults to
 * the fixed importance delays; a resolved config retunes the separation.
 */
export function entranceChannels(
  presetName: string,
  frame: number,
  fps: number,
  base: AnimChannels,
  stagger: StaggerConfig = DEFAULT_STAGGER,
): AnimChannels {
  const p = presetFor(presetName);
  if (!p) {
    return base;
  }
  return {
    ...base,
    heroY: sampleChannel(p, "translateY", frame, fps, { delayFrames: stagger.hero }),
    heroOpacity: sampleChannel(p, "opacity", frame, fps, { delayFrames: stagger.hero }),
    heroScale: sampleChannel(p, "scale", frame, fps, { delayFrames: stagger.hero }),
    secondaryOpacity: sampleChannel(p, "opacity", frame, fps, {
      delayFrames: stagger.secondary,
    }),
    resultOpacity: sampleChannel(p, "opacity", frame, fps, {
      delayFrames: stagger.result,
    }),
    resultScale: sampleChannel(p, "scale", frame, fps, { delayFrames: stagger.result }),
    chipOpacity: sampleChannel(p, "opacity", frame, fps, { delayFrames: stagger.chip }),
  };
}
