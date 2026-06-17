/**
 * R1.22 — Colour-role transition animation across the clip (fade / gradient /
 * pulse), APCA-safe every frame.
 *
 * An additive overlay (the registry renders it over the scene in `order`, never
 * touching the shared scene components). It washes a *role* colour across the
 * whole clip so a card's video gently shifts colour-temperature the way graded
 * sports footage does — a fade toward another role, a moving radial light
 * sweep, or a branded heartbeat pulse.
 *
 * The hard promise is the name: **APCA-safe every frame**. A full-frame wash
 * tints the scene's TEXT as well as its background, so naively it could erode
 * legibility. Instead this layer mirrors the still engine's own contrast maths
 * (`theming/contrast.py` SA98G v0.1.9 + the `quality/compliance.py` thresholds)
 * and, for the colour it is washing toward, computes the largest opacity that
 * keeps EVERY text/background role pair the scenes actually paint above the
 * exact APCA `Lc` floor the approved still required. The animation envelope is
 * clamped to that cap on every frame, so the transition is "as much colour
 * shift as legibility allows" and never a frame less legible than the still.
 *
 * House rules honoured (motion-craft):
 *   • Pure function of the frame — Remotion `interpolate` + deterministic
 *     sin/cos of the frame only; no `Math.random`/`Date.now`. Same props →
 *     byte-identical render.
 *   • Brand exact — the wash colour is ONLY a resolved role (`accent`/`surface`),
 *     never an invented hex.
 *   • No full-frame linear gradient on a dark ground (H.264 banding): the
 *     gradient mode is RADIAL; fade/pulse are flat solids (no banding).
 *   • Sometimes stillness — legacy/brief-less cards and the director's `static`
 *     intent get NO wash (byte-identical to the pre-layer render), so a pack
 *     reads as directed rather than uniformly washed.
 *
 * Drop-in contract: default-export `{ Layer, order }` (see ../registry).
 */
import { AbsoluteFill, Easing, interpolate, useVideoConfig } from "remotion";
import type { Roles, SceneComponent } from "../registry";

// ---------------------------------------------------------------------------
// APCA — a faithful TS port of theming/contrast.py (SAPC-APCA v0.1.9).
//
// Kept in lock-step with the Python so "APCA-safe" means the SAME number on
// the motion surface as on the still: the engine guarantees the still's role
// pairs clear these floors, and this layer guarantees the wash never drops them
// below it on any frame.
// ---------------------------------------------------------------------------

const SA98G = {
  mainTRC: 2.4,
  sRco: 0.2126729,
  sGco: 0.7151522,
  sBco: 0.072175,
  normBG: 0.56,
  normTXT: 0.57,
  revTXT: 0.62,
  revBG: 0.65,
  blkThrs: 0.022,
  blkClmp: 1.414,
  scaleBoW: 1.14,
  scaleWoB: 1.14,
  loBoWoffset: 0.027,
  loWoBoffset: 0.027,
  loClip: 0.1,
} as const;

// NOTE: the pure helpers below are additionally `export`ed so the safety maths
// can be unit-tested under Node against the Python APCA reference. The registry
// only ever consumes the DEFAULT export, so these named exports are inert to it.
type RGB = [number, number, number];

/** Parse `#RGB` / `#RRGGBB` → RGB 0-255, or null for anything else. */
export function hexToRgb(hex: string): RGB | null {
  let h = (hex || "").trim().replace(/^#/, "");
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (h.length < 6 || /[^0-9a-fA-F]/.test(h.slice(0, 6))) {
    return null;
  }
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/** sRGB 0-255 → APCA screen-luminance Y (simple-mode 2.4 exponent). */
function srgbToY([r, g, b]: RGB): number {
  const lin = (c: number) => Math.pow(c / 255, SA98G.mainTRC);
  return SA98G.sRco * lin(r) + SA98G.sGco * lin(g) + SA98G.sBco * lin(b);
}

/** Black-level soft clamp (only the very-dark end). */
function softClamp(y: number): number {
  return y < SA98G.blkThrs
    ? y + Math.pow(SA98G.blkThrs - y, SA98G.blkClmp)
    : y;
}

/** Signed APCA Lc for text `fg` on background `bg` (RGB in). */
export function apcaLc(fg: RGB, bg: RGB): number {
  const yTxt = softClamp(srgbToY(fg));
  const yBg = softClamp(srgbToY(bg));
  let out: number;
  if (yBg > yTxt) {
    const sapc =
      (Math.pow(yBg, SA98G.normBG) - Math.pow(yTxt, SA98G.normTXT)) *
      SA98G.scaleBoW;
    if (sapc < SA98G.loClip) return 0;
    out = sapc - SA98G.loBoWoffset;
  } else {
    const sapc =
      (Math.pow(yBg, SA98G.revBG) - Math.pow(yTxt, SA98G.revTXT)) *
      SA98G.scaleWoB;
    if (sapc > -SA98G.loClip) return 0;
    out = sapc + SA98G.loWoBoffset;
  }
  return out * 100;
}

/**
 * Composite `over` onto `base` at `alpha` in sRGB-gamma space — exactly how
 * headless Chromium composites a semi-transparent solid layer (source-over),
 * so the predicted blended colour matches what Remotion actually renders.
 */
export function over(base: RGB, paint: RGB, alpha: number): RGB {
  return [
    base[0] + (paint[0] - base[0]) * alpha,
    base[1] + (paint[1] - base[1]) * alpha,
    base[2] + (paint[2] - base[2]) * alpha,
  ];
}

// ---------------------------------------------------------------------------
// APCA thresholds — mirror quality/compliance.py.
// ---------------------------------------------------------------------------

export const LC_LARGE = 45; // names, result numeral, chip, accent runs
export const LC_SUPPORT = 60; // smaller supporting text (labels, meta lines)

type GuardPair = { fg: RGB; bg: RGB; lc: number };

/**
 * The text→background role pairs the scenes actually paint (StoryCard.tsx),
 * keyed to compliance.py's `_ROLE_PAIRS`. `onGround`-on-`ground` carries the
 * small labels too, so it is guarded at the stricter support floor. Unparseable
 * roles drop out (never part of a scored pair) rather than throwing.
 */
export function guardedPairs(roles: Roles): GuardPair[] {
  const g = hexToRgb(roles.ground);
  const s = hexToRgb(roles.surface);
  const a = hexToRgb(roles.accent);
  const on = hexToRgb(roles.onGround);
  const pairs: GuardPair[] = [];
  if (on && g) pairs.push({ fg: on, bg: g, lc: LC_SUPPORT }); // name + labels on ground
  if (on && s) pairs.push({ fg: on, bg: s, lc: LC_LARGE }); // text on surface panel
  if (a && g) pairs.push({ fg: a, bg: g, lc: LC_LARGE }); // accent run on ground
  if (g && a) pairs.push({ fg: g, bg: a, lc: LC_LARGE }); // chip text on accent
  if (g && s) pairs.push({ fg: g, bg: s, lc: LC_LARGE }); // dark text on light surface
  return pairs;
}

// The aesthetic ceiling on the wash. The APCA cap below is the hard safety
// governor; this just keeps the *intended* peak tasteful before the gate even
// considers legibility. The scan only ever needs to probe up to here.
const WASH_MAX = 0.5;

// A hair above the floating-point scan floor — below this an "active" wash is
// invisible, so we paint nothing (and keep the frame byte-identical to base).
const STEP_EPS = 0.004;

/**
 * The largest wash opacity (toward `paint`) that keeps every guarded pair that
 * STARTS legible at or above its `Lc` floor.
 *
 * A prefix scan, not a binary search: it returns the largest α such that *all*
 * α' ≤ α are safe, so it stays correct even if a contrast curve is not strictly
 * monotone in α. Pairs that are already below their floor at rest (e.g. a
 * gold-accent-on-ground card where accent sits right at the headline floor) are
 * not text on this card — guarding them would wrongly force α to 0 — so they're
 * skipped. Deterministic and cheap (a ≈50-probe scan per frame).
 */
export function maxSafeAlpha(paint: RGB, pairs: GuardPair[]): number {
  const live = pairs.filter((p) => Math.abs(apcaLc(p.fg, p.bg)) >= p.lc);
  if (live.length === 0) return 0;
  // 0.01 steps: fine enough that a polarity-crossover dip (where a mixed-hue
  // pair's |Lc| passes through the floor as both colours wash toward `paint`)
  // is always wider than one step, so the scan can't step over an unsafe
  // sliver. ≈50 probes × a few pairs per frame — negligible beside the encode.
  const STEP = 0.01;
  let safe = 0;
  for (let i = 1; i * STEP <= WASH_MAX + 1e-9; i++) {
    const alpha = i * STEP;
    const ok = live.every(
      (p) =>
        Math.abs(apcaLc(over(p.fg, paint, alpha), over(p.bg, paint, alpha))) >=
        p.lc,
    );
    if (!ok) break;
    safe = alpha;
  }
  return safe;
}

// ---------------------------------------------------------------------------
// Transition plan — derived deterministically from the APPROVED brief.
//
// No new prop / no StoryCard.tsx edit: the layer reads the director's `mood`
// and the card's `variationSeed` (already on every v2 card) to pick a mode and
// the role it washes toward. Stillness is a real, meaningful state — not an
// arbitrary gate — so the wash is honest about when it is and isn't directed.
// ---------------------------------------------------------------------------

type Mode = "fade" | "gradient" | "pulse";

// Minimal fields this layer reads from the card prop (kept local so the layer
// never widens the shared schema).
type CardLike = {
  mood?: string;
  motionIntent?: string;
  variationSeed?: number;
  roleGround?: string;
};

/** The transition mode for this card, or null for deliberate stillness. */
export function planMode(card: CardLike): Mode | null {
  const hasDirection = !!(card.mood || card.roleGround || card.motionIntent);
  if (!hasDirection) return null; // legacy/brief-less caller → inert (pre-layer output)
  if (card.motionIntent === "static") return null; // director chose a still card

  const m = (card.mood || "").toLowerCase();
  if (/electric|explosive|celebratory|triumph|fierce|bold/.test(m)) {
    return "pulse"; // a branded heartbeat for energetic / celebratory cards
  }
  if (/calm|stoic|minimal|precise|neutral/.test(m)) {
    return "fade"; // a slow directional temperature shift for composed cards
  }
  if (/warm/.test(m)) {
    return "gradient"; // a moving light for warm cards
  }
  // Unknown / mixed mood → the seed decides deterministically (per-card variety).
  const pick = (((card.variationSeed ?? 0) | 0) % 3 + 3) % 3;
  return pick === 0 ? "fade" : pick === 1 ? "gradient" : "pulse";
}

/** Which role colour to wash toward — always a real role, never invented. */
export function washTarget(roles: Roles, seed: number): string {
  const even = (((seed | 0) % 2) + 2) % 2 === 0;
  let target = even ? roles.accent : roles.surface;
  // Washing toward the ground itself is a no-op; fall back to the other role
  // so the transition is always visible when the palette allows.
  if (target.toLowerCase() === roles.ground.toLowerCase()) {
    target = target === roles.accent ? roles.surface : roles.accent;
  }
  return target;
}

// Per-mode intended peak (before the APCA cap). The gradient is localised
// (radial falloff), so it can intend a touch more at its centre.
const PEAK: Record<Mode, number> = { fade: 0.42, gradient: 0.5, pulse: 0.4 };
const PULSE_CYCLES = 2; // heartbeats across the whole clip

// ---------------------------------------------------------------------------
// The layer.
// ---------------------------------------------------------------------------

const Layer: SceneComponent = ({ ctx }) => {
  const { durationInFrames } = useVideoConfig();
  const card = ctx.card as CardLike;

  const mode = planMode(card);
  if (!mode) return null; // deliberate stillness → nothing painted

  const targetHex = washTarget(ctx.roles, (card.variationSeed ?? 0) | 0);
  const paint = hexToRgb(targetHex);
  if (!paint) return null; // unparseable role → bail rather than guess

  // The hard safety governor: the most we can wash and still clear every
  // text pair's APCA floor. Constant for the card (depends only on roles +
  // target), recomputed per frame for purity — cheap relative to the encode.
  const cap = maxSafeAlpha(paint, guardedPairs(ctx.roles));
  if (cap < STEP_EPS) return null; // palette too fragile for any safe wash

  // Normalised clip progress 0→1 (frame 0 → 0, so the opening frame is exactly
  // the un-washed scene).
  const t = Math.min(
    1,
    Math.max(0, ctx.frame / Math.max(1, durationInFrames - 1)),
  );

  // Per-mode animation envelope (0..1), all starting at 0 on frame 0.
  let env: number;
  let cx = 50;
  let cy = 32;
  if (mode === "fade") {
    // Slow directional rise to a held shift — a colour-role fade across the clip.
    env = interpolate(t, [0, 0.9], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.sin),
    });
  } else if (mode === "gradient") {
    // A radial light that sweeps across the frame while breathing in and out.
    env = Math.sin(Math.PI * Math.min(1, t / 0.97));
    cx = interpolate(t, [0, 1], [18, 82]); // sweep left → right
    cy = interpolate(t, [0, 1], [26, 40]); // a gentle vertical drift
  } else {
    // Branded heartbeat — returns fully to the base at each trough.
    env = 0.5 - 0.5 * Math.cos(2 * Math.PI * PULSE_CYCLES * t);
  }

  const alpha = Math.min(env * PEAK[mode], cap);
  if (alpha < STEP_EPS) return null;

  // Flat solids for fade/pulse (no banding); a RADIAL gradient for the sweep
  // (never a full-frame linear on a dark ground). The wash composites with the
  // default `source-over` the APCA cap was computed against.
  const background =
    mode === "gradient"
      ? `radial-gradient(circle at ${cx.toFixed(2)}% ${cy.toFixed(2)}%, ` +
        `${targetHex} 0%, transparent 72%)`
      : targetHex;

  return (
    <AbsoluteFill
      aria-hidden
      style={{ background, opacity: alpha, pointerEvents: "none" }}
    />
  );
};

export default { Layer, order: 5 };
