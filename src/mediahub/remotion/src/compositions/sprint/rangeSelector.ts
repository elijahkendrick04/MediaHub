// Range selectors — a small, frame-pure vocabulary for the per-glyph reveal.
//
// This is MediaHub's analog of After Effects' text Range Selector: a per-glyph
// reveal is an ORDER (how the glyphs are ranked for staggering) crossed with a
// SHAPE (how that ranking ramp is eased). The per-glyph channel
// (`motion/compile.ts` `glyphRevealAt`) feeds each glyph's (index, total)
// through `selectorRank`, so instead of one left-to-right metronome the
// characters can reveal in reverse, from the centre out, or in a seeded
// scatter — and the stagger ramp can bunch early (ease_in) or late (ease_out).
//
// Determinism / frame-purity: the ONLY entropy is the card's `variationSeed`
// (the sanctioned variety source, mirroring the still). The "seeded" order is a
// self-contained xmur3 -> mulberry32 Fisher-Yates permutation written inline
// here — no Math.random, no Date.now, no new Date — so every render of the same
// card is bit-stable and sibling cards scatter differently.
//
// Byte-identity: the DEFAULT pair is IDENTITY_SELECTOR = { order: "index",
// shape: "linear" }, and `selectorRank` returns the RAW integer index for it
// (no float round-trip), so a card on the identity selector reproduces the
// plain per-glyph index ramp exactly.

import { Easing } from "remotion";

export type RangeOrder = "index" | "reverse" | "center_out" | "seeded";
export type RangeShape = "linear" | "ease_in" | "ease_out" | "ease_in_out";

/** The default / identity pair — the plain left-to-right, unshaped index ramp. */
export const IDENTITY_SELECTOR: { order: RangeOrder; shape: RangeShape } = {
  order: "index",
  shape: "linear",
};

// ---------------------------------------------------------------------------
// Seeded permutation (self-contained; no Math.random / Date.now / new Date)
// ---------------------------------------------------------------------------

/** xmur3 integer seed expander -> a 32-bit state. Pure; the seed is the only input. */
function xmur3(seed: number): number {
  let h = 1779033703 ^ (seed | 0);
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  h ^= h >>> 16;
  return h >>> 0;
}

/** mulberry32 PRNG — deterministic, frame-pure; returns a stepper in [0, 1). */
function mulberry32(a: number): () => number {
  let s = a >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * A stable Fisher-Yates permutation of [0 .. n-1] driven purely by `seed`;
 * `perm[i]` is glyph i's reveal rank. Same seed -> same permutation, every
 * frame — no randomness that could drift between renders.
 */
export function seededPermutation(n: number, seed: number): number[] {
  const arr = Array.from({ length: Math.max(0, n) }, (_v, i) => i);
  const rand = mulberry32(xmur3(seed));
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    const tmp = arr[i];
    arr[i] = arr[j];
    arr[j] = tmp;
  }
  return arr;
}

// ---------------------------------------------------------------------------
// Shape — how the ranking ramp is eased
// ---------------------------------------------------------------------------

/** Ease a normalized ramp value `t` in [0, 1] by `shape` via Remotion `Easing`. */
export function applyShape(t: number, shape: RangeShape): number {
  const x = Math.min(1, Math.max(0, t));
  switch (shape) {
    case "ease_in":
      return Easing.in(Easing.cubic)(x);
    case "ease_out":
      return Easing.out(Easing.cubic)(x);
    case "ease_in_out":
      return Easing.inOut(Easing.cubic)(x);
    case "linear":
    default:
      return x;
  }
}

// ---------------------------------------------------------------------------
// Order — how the glyphs are ranked
// ---------------------------------------------------------------------------

/**
 * The integer rank (reveal position) of glyph `index` within a line of `total`
 * glyphs under `order`. For "index" the RAW `index` is returned unchanged (so
 * the identity path is byte-exact); every other order maps into [0, total-1].
 */
export function orderRank(
  index: number,
  total: number,
  order: RangeOrder,
  seed: number,
): number {
  if (order === "index") {
    return index; // raw — byte-identical to the plain per-glyph ramp
  }
  const n = Math.max(1, total);
  const i = ((index % n) + n) % n;
  switch (order) {
    case "reverse":
      return n - 1 - i;
    case "center_out":
      // Centre glyphs reveal first (rank ~0), edges last (rank ~n-1).
      return Math.abs(i - (n - 1) / 2) * 2;
    case "seeded":
      return seededPermutation(n, seed)[i];
    default:
      return i;
  }
}

/**
 * Glyph `index`'s stagger RANK under (order, shape). Linear keeps the exact
 * integer rank (no float round-trip); a non-linear shape re-eases the rank
 * across [0, total-1]. This is what the per-glyph channel multiplies by the
 * tokenised cadence, so identity (index + linear) === the plain index ramp.
 */
export function selectorRank(
  index: number,
  total: number,
  seed: number,
  order: RangeOrder,
  shape: RangeShape,
): number {
  const rank = orderRank(index, total, order, seed);
  if (shape === "linear") {
    return rank;
  }
  const denom = Math.max(1, total - 1);
  return applyShape(rank / denom, shape) * denom;
}

/**
 * The normalized reveal PHASE in [0, 1] of glyph `index` — `selectorRank`
 * mapped onto [0, 1] and clamped. Exposed for callers/tests that want a
 * resolution-free ramp; the identity selector gives exactly `index/(total-1)`.
 */
export function rangeSelectorPhase(
  index: number,
  total: number,
  seed: number,
  order: RangeOrder,
  shape: RangeShape,
): number {
  const denom = Math.max(1, total - 1);
  const phase = selectorRank(index, total, seed, order, shape) / denom;
  return Math.min(1, Math.max(0, phase));
}

// ---------------------------------------------------------------------------
// Selection — seed + mood -> a tasteful (order, shape) pair
// ---------------------------------------------------------------------------

const ORDERS: RangeOrder[] = ["index", "reverse", "center_out", "seeded"];
const SHAPES: RangeShape[] = ["linear", "ease_in", "ease_out", "ease_in_out"];

/**
 * Pick the (order, shape) pair for a card deterministically from its
 * `variationSeed` and `mood`. Restraint moods keep the plain identity ramp
 * (byte-identical to the pre-selector per-glyph reveal); energetic moods get a
 * seeded scatter easing out; everything else derives a tasteful pair from the
 * seed so sibling cards differ. Frame-pure — the only entropy is the seed,
 * already the sanctioned variety source.
 */
export function selectRangeFor(
  seed: number,
  mood: string,
): { order: RangeOrder; shape: RangeShape } {
  const m = (mood || "").toLowerCase();
  // Restraint moods stay plain — the identity ramp.
  if (/(calm|stoic|precise|minimal|composed|weighty)/.test(m)) {
    return { ...IDENTITY_SELECTOR };
  }
  // Energetic moods: a seeded scatter that bunches late (ease_out) for punch.
  if (/(electric|explosive|fierce|celebratory|triumph)/.test(m)) {
    return { order: "seeded", shape: "ease_out" };
  }
  // Neutral: derive a stable pair from the seed alone so siblings differ.
  const h = xmur3(seed);
  return { order: ORDERS[h % 4], shape: SHAPES[(h >>> 8) % 4] };
}
