/**
 * R1.6 — Animated-pattern drift layer (sprint additive overlay).
 *
 * Gives the card's *already-painted* background pattern subtle, per-pattern,
 * frame-pure life during the BREATHE phase of the beat — the 30–70% window
 * (motion-craft) where the content is fully readable and exactly one ambient
 * motion should be alive. Each pattern family drifts in its own idiom, drawn
 * from the rotate / opacity / scale palette:
 *
 *   dot     (dots, halftone)   → breathing scale + opacity twinkle
 *   linear  (stripes, diagonal)→ slow translate along the rule + micro-scale
 *   angular (geometric, water) → gentle rotate (+ drift for water) + shimmer
 *   noise   (grain)            → irregular opacity flicker + micro-scale
 *   generic (sprint patterns)  → soft scale + slow rotate
 *
 * Why an edge-vignette mask: the sprint overlay layers paint OVER the scene
 * (after the hero text/photo), and motion-craft warns a full repeating grid
 * reads as cheap. So the drift is masked transparent through the central
 * content band and only breathes in the margins/corners — it reads as the
 * background coming alive, never as a second grid veiling the time or name.
 *
 * Hard rules honoured (mediahub-engineering / motion-craft):
 *   • Pure function of the frame — Math.sin(frame) only, no CSS @keyframes /
 *     transition / animation, no Date.now, no Math.random. Same props →
 *     byte-identical render.
 *   • Per-card variety (phase + speed) derives deterministically from
 *     variationSeed, never randomness, so it never breaks still↔motion parity.
 *   • Brand-exact — the tile is drawn in the resolved accent role; no new hue.
 *   • No-op (renders null) for clean / radial / duotone / unset backgrounds and
 *     any unknown token with no registered sprint pattern, so cards without a
 *     texture render exactly as they did before this layer landed.
 *
 * The drift-tile vocabulary below is a deliberate parity mirror of
 * StoryCard.tsx::bgPatternFor (same motif geometry, drawn at full accent so
 * the layer's animated opacity is the single subtlety knob). It is kept inline
 * rather than imported so this file is a pure new-file drop with zero edits to
 * the shared composition — the R1.* parallel-merge protocol.
 */
import { Easing, interpolate, useVideoConfig } from "remotion";

import { EXTRA_PATTERNS } from "../registry";
import type { Roles, SceneComponent } from "../registry";

type PatternFamily = "dot" | "linear" | "angular" | "noise" | "generic";

const encode = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

// Drift tile for a background_style token, drawn in the accent role at full
// opacity (the layer animates the real opacity). Parity mirror of bgPatternFor;
// "" for the non-textured grounds so the layer becomes a clean no-op there.
function driftTileFor(style: string, roles: Roles): string {
  const a = roles.accent || "#FFFFFF";
  switch (style) {
    case "dots":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>` +
          `<circle cx='40' cy='40' r='4' fill='${a}'/></svg>`,
      );
    case "halftone":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30'>` +
          `<circle cx='15' cy='15' r='5' fill='${a}'/></svg>`,
      );
    case "diagonal":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>` +
          `<path d='M0,40 L40,0' stroke='${a}' stroke-width='2'/></svg>`,
      );
    case "stripes":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='8'>` +
          `<rect width='40' height='4' fill='${a}'/></svg>`,
      );
    case "geometric":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>` +
          `<polygon points='60,12 108,96 12,96' fill='none' stroke='${a}' stroke-width='2'/></svg>`,
      );
    case "water":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='60'>` +
          `<path d='M0,30 Q30,10 60,30 T120,30' fill='none' stroke='${a}' stroke-width='2'/></svg>`,
      );
    case "grain":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60'>` +
          `<circle cx='8' cy='14' r='1.4' fill='${a}'/>` +
          `<circle cx='44' cy='30' r='1.4' fill='${a}'/>` +
          `<circle cx='24' cy='50' r='1.4' fill='${a}'/></svg>`,
      );
    case "radial":
    case "duotone":
    case "clean":
    case "":
      return "";
    default: {
      // Sprint background patterns (R1.4) register their own tile generator.
      const extra = EXTRA_PATTERNS[style];
      return extra ? extra(roles) : "";
    }
  }
}

function familyFor(style: string): PatternFamily {
  switch (style) {
    case "dots":
    case "halftone":
      return "dot";
    case "stripes":
    case "diagonal":
      return "linear";
    case "geometric":
    case "water":
      return "angular";
    case "grain":
      return "noise";
    default:
      return "generic";
  }
}

// Deterministic [0,1) from the seed — the per-card phase/speed jitter that
// keeps two textured cards in one pack from breathing in lock-step (the
// "same stagger everywhere" monoculture) without any randomness.
function seedFrac(seed: number): number {
  const s = Math.floor(Math.abs(seed)) || 0;
  return (((s * 2654435761) % 1000) + 1000) % 1000 / 1000;
}

type DriftMotion = {
  tx: number;
  ty: number;
  scale: number;
  rotate: number;
  opacityScale: number; // 0..1 multiplier on the family's peak opacity
};

// Family idiom. `osc`∈[-1,1] is the slow breathe sine; `flick`∈[-1,1] is a
// faster companion sine used only by the noise family for an irregular feel.
function motionFor(
  family: PatternFamily,
  style: string,
  osc: number,
  flick: number,
): { motion: DriftMotion; peak: number } {
  const osc01 = (osc + 1) / 2;
  switch (family) {
    case "dot":
      return {
        peak: 0.16,
        motion: { tx: 0, ty: 0, scale: 1 + 0.03 * osc01, rotate: 0, opacityScale: 0.5 + 0.5 * osc01 },
      };
    case "linear": {
      // Stripes drift across their rule (vertical); diagonals along 45°.
      const along = 8 * osc;
      const diagonal = style === "diagonal";
      return {
        peak: 0.16,
        motion: {
          tx: diagonal ? along * 0.7 : 0,
          ty: diagonal ? along * 0.7 : along,
          scale: 1 + 0.012 * osc01,
          rotate: 0,
          opacityScale: 0.6 + 0.4 * osc01,
        },
      };
    }
    case "angular":
      return {
        peak: 0.14,
        motion: {
          tx: style === "water" ? 6 * osc : 0,
          ty: 0,
          scale: 1 + 0.015 * osc01,
          rotate: 1.4 * osc,
          opacityScale: 0.55 + 0.45 * osc01,
        },
      };
    case "noise": {
      // Two summed sines → a flicker that never settles into one obvious beat.
      const f = (osc + 0.5 * flick) / 1.5; // back into [-1,1]
      return {
        peak: 0.18,
        motion: { tx: 0, ty: 0, scale: 1 + 0.02 * ((f + 1) / 2), rotate: 0, opacityScale: 0.45 + 0.55 * ((f + 1) / 2) },
      };
    }
    default:
      return {
        peak: 0.15,
        motion: { tx: 0, ty: 0, scale: 1 + 0.025 * osc01, rotate: 0.8 * osc, opacityScale: 0.55 + 0.45 * osc01 },
      };
  }
}

const Layer: SceneComponent = ({ ctx }) => {
  // durationInFrames is per-beat inside a reel <Sequence> (the same source the
  // card's outro fade reads), so the breathe window is proportional per card.
  const { durationInFrames } = useVideoConfig();
  const { frame, fps, roles, card } = ctx;

  const style = (card.backgroundStyle || "").toLowerCase();
  const tile = driftTileFor(style, roles);
  if (!tile) {
    // No texture pattern on this card → nothing to drift (byte-identical
    // to the pre-R1.6 render for clean / radial / duotone / bare grounds).
    return null;
  }

  // Breathe-phase envelope: fade the drift in across the build→breathe seam
  // (~28–40%) and back out across breathe→resolve (~66–80%), so the motion is
  // alive only while the card is being read and the transition still owns the
  // exit. inOut-sine keeps the in/out organic, not mechanical.
  const ease = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const, easing: Easing.inOut(Easing.sin) };
  const phaseIn = interpolate(frame, [durationInFrames * 0.26, durationInFrames * 0.4], [0, 1], ease);
  const phaseOut = interpolate(frame, [durationInFrames * 0.66, durationInFrames * 0.8], [1, 0], ease);
  const envelope = phaseIn * phaseOut;
  if (envelope <= 0) {
    // Outside the breathe window the layer contributes nothing — skip the div
    // entirely so build/resolve frames stay exactly as before.
    return null;
  }

  // Slow, frame-pure breathe sine (period ~5–6.5s, seed-jittered), plus a
  // faster companion the noise family folds in for an irregular flicker.
  const sf = seedFrac(card.variationSeed || 0);
  const t = frame / fps;
  const speed = 0.15 + 0.06 * sf; // Hz
  const phase = sf; // cycle offset
  const osc = Math.sin((t * speed + phase) * 2 * Math.PI);
  const flick = Math.sin((t * (speed * 2.6) + phase) * 2 * Math.PI);

  const family = familyFor(style);
  const { motion, peak } = motionFor(family, style, osc, flick);
  const opacity = envelope * peak * motion.opacityScale;

  // Edge-vignette mask: transparent through the central content band, opaque
  // toward the corners — so the drift never washes over the hero text/photo.
  const mask =
    "radial-gradient(ellipse 72% 70% at 50% 46%, transparent 0%, transparent 42%, #000 82%)";

  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        // Larger inset than the static pattern so the scale/rotate never
        // reveals a hard repeat edge inside the frame.
        inset: -120,
        backgroundImage: tile,
        backgroundRepeat: "repeat",
        opacity,
        pointerEvents: "none",
        transform: `translate(${motion.tx}px, ${motion.ty}px) scale(${motion.scale}) rotate(${motion.rotate}deg)`,
        transformOrigin: "center center",
        WebkitMaskImage: mask,
        maskImage: mask,
      }}
    />
  );
};

// Low order: a background-texture treatment paints UNDER the richer overlays
// (photo scrims, text effects, animated logo) that later sprint items drop in.
export default { Layer, order: 5 };
