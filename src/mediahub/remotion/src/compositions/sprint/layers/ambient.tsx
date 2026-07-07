import React from "react";
import { Easing, interpolate, useVideoConfig } from "remotion";
import type { SceneComponent } from "../registry";

/**
 * R1.24 — Ambient motion programmes (additive overlay).
 *
 * One slow, sustained atmosphere per card — drift, pan, temperature shift, a
 * breathing glow, or deliberate stillness — alive through the BREATHE phase of
 * the clip (≈30–70%, motion-craft) and faded to nothing across the build and
 * resolve so it never fights an entrance or muddies a transition.
 *
 * Non-negotiables honoured (CLAUDE.md / motion-craft):
 *   • Pure function of the frame — interpolate + sin(frame/period) only; no CSS
 *     animation, no Math.random, no Date.now. Same props → byte-identical pixels.
 *   • Brand-locked — every tint is a resolved colour ROLE (ground/surface/
 *     accent/onGround); no invented hue. "Temperature" is a crossfade between
 *     two brand roles, never a fabricated warm/cool colour.
 *   • Legible every frame — radial glows only (a full-frame linear gradient
 *     bands on dark grounds under H.264); peak alpha capped low so the wash can
 *     never pull text below its APCA target; pointer-events:none; sits beneath
 *     later overlays (low `order`).
 *   • Per-beat variety — the programme is chosen deterministically from the
 *     card's variationSeed (so two cards in a pack differ), its speed/scale
 *     flavoured by mood; a "static" motion intent forces stillness. "Sometimes
 *     stillness" (motion-craft) is one of the programmes.
 *
 * Reel-safe: each reel beat wraps <StoryCard> in a <Sequence>, so
 * useVideoConfig().durationInFrames is the BEAT's length and ctx.frame is the
 * beat-local frame — the breathe window lands per beat, not across the reel.
 */

// Peak overlay alpha — deliberately low, but high enough to survive H.264
// (M19: 0.08 vanished after encoding; 0.14 reads as living atmosphere while
// staying far under the still engine's 0.24–0.34 decorative grounds, so even
// where a glow overlaps text the contrast shift stays tiny).
const PEAK_ALPHA = 0.14;

const AMBIENT_PROGRAMMES = ["drift", "pan", "temperature", "breathe", "still"] as const;
type Programme = (typeof AMBIENT_PROGRAMMES)[number];

const TAU = Math.PI * 2;

// #RRGGBB / #RGB → #RRGGBBAA. Anything else passes through untinted rather than
// emitting a malformed colour string.
function withAlpha(hex: string, a: number): string {
  const h = (hex || "").trim();
  const aa = Math.round(Math.max(0, Math.min(1, a)) * 255)
    .toString(16)
    .padStart(2, "0");
  if (/^#[0-9a-fA-F]{6}$/.test(h)) return `${h}${aa}`;
  if (/^#[0-9a-fA-F]{3}$/.test(h)) {
    const r = h[1];
    const g = h[2];
    const b = h[3];
    return `#${r}${r}${g}${g}${b}${b}${aa}`;
  }
  return h || "#FFFFFF";
}

// Mood → ambient energy (a speed + amplitude scalar). Mirrors the mood scale
// the spring table uses: calm/minimal breathe slow and small; electric/explosive
// run a touch faster and wider. Kept gentle — this is atmosphere, not a feature.
function ambientEnergy(mood: string): number {
  const m = (mood || "").toLowerCase();
  if (/(calm|stoic|precise|minimal|composed|weighty)/.test(m)) return 0.78;
  if (/(electric|explosive|fierce|kinetic|snappy)/.test(m)) return 1.28;
  if (/(celebratory|bold|triumph|warm)/.test(m)) return 1.12;
  return 1.0;
}

// A soft brand-role radial glow anchored at (cx%, cy%). Radial (never linear)
// so it cannot band on a dark ground; the role colour fades to its own
// transparent stop by `spread`%.
function glow(role: string, cx: number, cy: number, alpha: number, spread = 60): React.CSSProperties {
  return {
    position: "absolute",
    inset: 0,
    background: `radial-gradient(circle at ${cx.toFixed(2)}% ${cy.toFixed(2)}%, ${withAlpha(
      role,
      alpha,
    )} 0%, ${withAlpha(role, 0)} ${spread.toFixed(0)}%)`,
  };
}

const Layer: SceneComponent = ({ ctx }) => {
  const { frame, roles, card } = ctx;
  const { durationInFrames, fps } = useVideoConfig();

  // Trapezoidal breathe-phase envelope, eased in/out: nothing during the build
  // (no frame-0 jump, no fighting entrances), full through the breathe window,
  // gone again before resolve so the transition/outro stays clean.
  const d = durationInFrames;
  const env = interpolate(frame, [d * 0.1, d * 0.26, d * 0.74, d * 0.9], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.sin),
  });
  if (env <= 0) {
    return null;
  }

  const energy = ambientEnergy(card.mood || "");
  const seed = (card.variationSeed | 0) >>> 0;
  // A "static" card animates nothing by design — honour the director with
  // ambient stillness rather than drift.
  const programme: Programme =
    (card.motionIntent || "") === "static"
      ? "still"
      : AMBIENT_PROGRAMMES[seed % AMBIENT_PROGRAMMES.length];

  // One slow cycle keyed to clip length and mood (a longer clip drifts slower),
  // with a seeded phase so two same-programme cards aren't in lockstep.
  const baseCycle = (d / fps) * 1.15; // seconds per cycle at energy 1.0
  const period = Math.max(1, (fps * baseCycle) / energy); // frames per cycle
  const phase = ((seed % 7) / 7) * TAU;
  const osc = Math.sin((frame / period) * TAU + phase); // −1..1 (sinusoidal, inOut by nature)
  const osc01 = osc * 0.5 + 0.5; // 0..1

  const a = PEAK_ALPHA * env;
  let children: React.ReactNode = null;

  switch (programme) {
    case "pan": {
      // A wide, soft light slowly panning across the frame.
      const cx = interpolate(osc01, [0, 1], [24, 76]);
      children = <div style={glow(roles.accent, cx, 38, a, 70)} />;
      break;
    }
    case "temperature": {
      // Two brand-role glows crossfading in antiphase — the ambient tint drifts
      // "warm↔cool" while every colour stays a resolved role.
      const warm = a * (0.45 + 0.55 * osc01);
      const cool = a * (0.45 + 0.55 * (1 - osc01));
      children = (
        <>
          <div style={glow(roles.accent, 28, 26, warm, 64)} />
          <div style={glow(roles.surface, 74, 78, cool, 64)} />
        </>
      );
      break;
    }
    case "breathe": {
      // A glow that breathes — scale and alpha oscillate together. Held high in
      // the frame so it sits behind decoratives, not the main text block.
      const scale = 1 + 0.06 * osc;
      children = (
        <div
          style={{
            ...glow(roles.accent, 50, 40, a * (0.6 + 0.4 * osc01), 56),
            transform: `scale(${scale.toFixed(4)})`,
            transformOrigin: "50% 40%",
          }}
        />
      );
      break;
    }
    case "still": {
      // Deliberate stillness — a fixed faint glow that does not move. Stillness
      // after motion has weight (motion-craft); the envelope still breathes it
      // in and out so it never pops on or off.
      children = <div style={glow(roles.accent, 50, 40, a * 0.7, 58)} />;
      break;
    }
    case "drift":
    default: {
      // A soft glow drifting on a slow diagonal Lissajous path (two periods, so
      // it never simply retraces its own line).
      const cx = 50 + 16 * Math.sin((frame / period) * TAU + phase);
      const cy = 42 + 12 * Math.sin((frame / (period * 1.4)) * TAU + phase * 1.3);
      children = <div style={glow(roles.accent, cx, cy, a, 60)} />;
      break;
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      {children}
    </div>
  );
};

// Low order: ambient is background atmosphere, so it paints beneath any later
// overlay (text effects, captions, animated logo) that registers above it.
export default { Layer, order: 5 };
