import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";
import {
  EXTRA_ACCENTS,
  EXTRA_INTENTS,
  EXTRA_LAYERS,
  EXTRA_PATTERNS,
  EXTRA_SCENES,
  EXTRA_SPRINGS,
} from "./sprint/registry";

// Exported for MeetReel: ONE schema for a card's props on both compositions,
// so a field added here can never be silently zod-stripped on the reel path.
export const cardSchema = z.object({
  athleteFullName: z.string().default(""),
  athleteFirstName: z.string().default(""),
  athleteSurname: z.string().default(""),
  eventName: z.string().default(""),
  resultValue: z.string().default(""),
  achievementLabel: z.string().default(""),
  meetName: z.string().default(""),
  place: z.string().default(""),
  variationSeed: z.number().default(0),
  // Path A/B variation axes — every field is optional. Empty strings
  // fall back to the variationSeed-driven behaviour, so legacy callers
  // that haven't been updated keep producing the same output they did
  // before this composition learned about the wider variation vocabulary.
  backgroundStyle: z.string().default(""),
  composition: z.string().default(""),
  typographyPair: z.string().default(""),
  accentStyle: z.string().default(""),
  mood: z.string().default(""),
  photoTreatment: z.string().default(""),
  // The card's actual photo (the one the user attached to the still
  // graphic), inlined by motion.py as a JPEG data URI. Empty = no photo
  // layer, which keeps the pre-photo behaviour for older callers.
  photoSrc: z.string().default(""),
  // Saliency object-position for the photo (same deterministic maths as
  // the still renderer's --mh-photo-pos) so faces stay in frame. Empty =
  // the safe "center 28%" default.
  photoPos: z.string().default(""),
  // R1.9: the athlete cut out from their photo (background removed to alpha),
  // inlined by motion.py as a PNG data URI. The cutout sprint layer
  // (sprint/layers/cutout.tsx) composites this as a parallax FOREGROUND plane
  // over the scrimmed full-bleed background photo, giving the card real depth.
  // Empty = no prepared cutout (no sourced photo, or no background remover
  // available), and the layer no-ops — byte-identical to the pre-R1.9 render.
  cutoutSrc: z.string().default(""),
  // Gen v2 (SEQ-4): the still graphic's archetype + measured emphasis line,
  // so the motion render of a card visually matches its still. Empty keeps
  // the pre-v2 behaviour for cards rendered by older callers.
  archetype: z.string().default(""),
  heroStat: z.string().default(""),
  // The still graphic's style pack id (graphic_renderer.style_packs), shape
  // "ground-texture-accentGeo-density". The motion render layers the same
  // ground / texture / accent-geometry overlay over the scene so a card's
  // video carries the still's exact decorative treatment. Empty = bare.
  stylePack: z.string().default(""),
  // The design-spec director's motion language for this card
  // (design_spec.MOTION_INTENTS). Empty = the mood/seed default programme.
  motionIntent: z.string().default(""),
  // Resolved still-parity colour roles: the exact APCA-gated hexes the
  // card's still graphic painted (medal tint included), resolved by the
  // deterministic Python resolver. Empty strings = seed-permutation
  // fallback, the pre-parity behaviour.
  roleGround: z.string().default(""),
  roleSurface: z.string().default(""),
  roleAccent: z.string().default(""),
  roleOnGround: z.string().default(""),
  // Subtitle/caption burn-in track (R1.3): a JSON string of the APCA-gated,
  // frame-timed caption cues built by visual/subtitle_burn.py and painted by
  // sprint/layers/captions.tsx. Empty = no captions (byte-identical render).
  captionsJson: z.string().default(""),
});

const brandSchema = z.object({
  primary: z.string().default("#0A2540"),
  secondary: z.string().default("#000000"),
  accent: z.string().default("#FFFFFF"),
  displayName: z.string().default(""),
  shortName: z.string().default(""),
  logoDataUri: z.string().default(""),
});

export const storyCardSchema = z.object({
  card: cardSchema,
  brand: brandSchema,
});

type Props = z.infer<typeof storyCardSchema>;
type CardProps = Props["card"];
type BrandProps = Props["brand"];
export type Roles = { ground: string; surface: string; accent: string; onGround: string };

// Six palette role permutations — mirror creative_brief/generator.py
// _apply_palette_seed so the static graphic and motion render agree on
// which colour plays which role for a given variationSeed.
function rolesForSeed(brand: BrandProps, seed: number): Roles {
  const p = brand.primary || "#0A2540";
  const s = brand.secondary || "#000000";
  const a = brand.accent || "#FFFFFF";
  const mode = ((seed | 0) % 6 + 6) % 6;
  if (mode === 1) return { ground: s, surface: p, accent: a, onGround: a };
  if (mode === 2) return { ground: a, surface: p, accent: s, onGround: s };
  if (mode === 3) return { ground: p, surface: a, accent: s, onGround: s };
  if (mode === 4) return { ground: s, surface: a, accent: p, onGround: p };
  if (mode === 5) return { ground: a, surface: s, accent: p, onGround: p };
  return { ground: p, surface: s, accent: a, onGround: a };
}

// Resolved still-parity roles win when motion.py supplied them (the same
// APCA-gated set the approved still painted); otherwise fall back to the
// seed permutation so legacy callers render exactly as before.
function resolveRoles(card: CardProps, brand: BrandProps): Roles {
  if (card.roleGround && card.roleAccent) {
    return {
      ground: card.roleGround,
      surface: card.roleSurface || card.roleGround,
      accent: card.roleAccent,
      onGround: card.roleOnGround || card.roleAccent,
    };
  }
  return rolesForSeed(brand, card.variationSeed || 0);
}

// Map brief.background_style → an SVG data URI we layer over the ground
// colour at low opacity. Each generator is deliberately monochrome
// (uses the accent role) so the pattern reads as texture, not a
// competing illustration.
function bgPatternFor(style: string, roles: Roles): string {
  const accent = roles.accent || "#FFFFFF";
  const encode = (svg: string) =>
    `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  const stroke = (op: number) =>
    `${accent}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
  switch (style) {
    case "dots":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>` +
        `<circle cx='12' cy='12' r='3' fill='${stroke(0.18)}'/></svg>`,
      );
    case "diagonal":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>` +
        `<path d='M0,40 L40,0' stroke='${stroke(0.16)}' stroke-width='2'/></svg>`,
      );
    case "stripes":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='8'>` +
        `<rect width='40' height='4' fill='${stroke(0.18)}'/></svg>`,
      );
    case "geometric":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>` +
        `<polygon points='60,10 110,90 10,90' fill='none' stroke='${stroke(0.18)}' stroke-width='2'/></svg>`,
      );
    case "halftone":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30'>` +
        `<circle cx='15' cy='15' r='5' fill='${stroke(0.22)}'/></svg>`,
      );
    case "grain":
      // SVG <feTurbulence> rendered server-side is heavy; approximate
      // with sparse noise dots.
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60'>` +
        `<circle cx='6' cy='12' r='1' fill='${stroke(0.18)}'/>` +
        `<circle cx='42' cy='28' r='1' fill='${stroke(0.18)}'/>` +
        `<circle cx='22' cy='48' r='1' fill='${stroke(0.18)}'/></svg>`,
      );
    case "water":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='60'>` +
        `<path d='M0,30 Q30,10 60,30 T120,30' fill='none' stroke='${stroke(0.18)}' stroke-width='2'/></svg>`,
      );
    case "radial":
    case "duotone":
    case "clean":
      return "";
    default: {
      // Sprint patterns (R1.4) register their own file under sprint/patterns/.
      const extra = EXTRA_PATTERNS[style];
      return extra ? extra(roles) : "";
    }
  }
}

// Map brief.typography_pair → a CSS font-family stack. The reel now loads the
// SAME self-hosted brand woff2 as the still graphic (see src/fonts.ts; Council
// 2026-05-31), so each stack LEADS with the real brand face and matches the
// posted card. The system fonts are kept only as a safety net behind it.
function fontStackFor(pair: string): string {
  switch (pair) {
    case "anton-inter":
    case "druk-inter":
    case "oswald-inter":
      // Heavy condensed display → Anton (the still renderer's default headline).
      return "'Anton', 'Oswald', 'Impact', 'Helvetica Neue Condensed', 'Arial Narrow', sans-serif";
    case "bebas-grotesk":
      return "'Bebas Neue', 'Oswald', 'Impact', 'Arial Narrow', sans-serif";
    case "bowlby-inter":
      return "'Bowlby One', 'Archivo Black', 'Impact', sans-serif";
    case "archivo-inter":
      return "'Space Grotesk', 'Archivo', 'Inter', 'Helvetica Neue', Arial, sans-serif";
    default:
      return "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif";
  }
}

// Map mood → spring config. The mood field is set by the AI director
// (e.g. "electric, precise", "calm, weighty", "celebratory") so the
// motion render's energy actually matches the static graphic's vibe.
function springConfigFor(mood: string): { damping: number; stiffness: number; mass: number } {
  const m = (mood || "").toLowerCase();
  if (m.includes("calm") || m.includes("weighty") || m.includes("composed")) {
    return { damping: 30, stiffness: 60, mass: 1.1 };
  }
  if (m.includes("electric") || m.includes("snappy") || m.includes("kinetic")) {
    return { damping: 12, stiffness: 140, mass: 0.6 };
  }
  if (m.includes("celebratory") || m.includes("bold") || m.includes("triumph")) {
    return { damping: 15, stiffness: 110, mass: 0.7 };
  }
  // Sprint moods (R1.26) register their own file under sprint/springs/; built-in
  // moods above always win, so this only resolves tokens they don't recognise.
  const extra = EXTRA_SPRINGS[m];
  if (extra) {
    return extra;
  }
  return { damping: 18, stiffness: 90, mass: 0.7 };
}

// ---------------------------------------------------------------------------
// Motion-intent programmes (design_spec.MOTION_INTENTS, §5.4)
// ---------------------------------------------------------------------------
//
// The design-spec director picks ONE motion language per card; this is where
// each language is executed as a pure function of the frame. Every programme
// produces the same handful of channels the scenes consume, so an intent and
// a scene compose freely. The "" default reproduces the original spring
// programme exactly (legacy callers see no change).

export type AnimChannels = {
  heroY: number; // translateY of the hero text block (px @ design scale)
  heroOpacity: number;
  heroScale: number;
  secondaryOpacity: number; // event line / supporting copy
  resultOpacity: number;
  resultScale: number;
  chipOpacity: number; // chips, logo, bottom strip, decorations
  bgDrift: number; // background pattern translateY (parallax)
  photoScale: number; // slow photo push (parallax)
  // Numeric count-up progress for the result value (count_up intent).
  // 1 everywhere else, so every other programme renders the verbatim text.
  resultProgress: number;
  // Per-word staggered reveal (kinetic_type); identity elsewhere.
  wordAt: (index: number) => { y: number; opacity: number };
};

// The nine executable intents. Kept in lock-step with
// creative_brief/design_spec.MOTION_INTENTS (tested from Python).
export const MOTION_INTENTS = [
  "fade_in",
  "snap_in_then_settle",
  "slide_up",
  "scale_in",
  "crossfade",
  "kinetic_type",
  "parallax",
  "count_up",
  "static",
] as const;

function animProgram(
  intent: string,
  mood: string,
  frame: number,
  fps: number,
  durationInFrames: number,
): AnimChannels {
  const moodSpring = springConfigFor(mood);
  const clampRight = { extrapolateRight: "clamp" as const };
  // Identity word reveal: the parent line owns motion + opacity, so a word
  // contributes nothing extra (no double-applied fades).
  const identityWord = () => ({ y: 0, opacity: 1 });

  // Shared default ramps (the original programme).
  const defaultSpring = spring({ frame, fps, config: moodSpring });
  const base: AnimChannels = {
    heroY: interpolate(defaultSpring, [0, 1], [120, 0]),
    heroOpacity: interpolate(frame, [0, fps * 0.4], [0, 1], clampRight),
    heroScale: 1,
    secondaryOpacity: interpolate(frame, [0, fps * 0.4], [0, 1], clampRight),
    resultOpacity: interpolate(frame, [fps * 0.6, fps * 1.1], [0, 1], clampRight),
    resultScale: interpolate(frame, [fps * 0.6, fps * 1.4], [0.92, 1.0], clampRight),
    chipOpacity: interpolate(frame, [fps * 1.0, fps * 1.5], [0, 1], clampRight),
    bgDrift: 0,
    photoScale: 1,
    resultProgress: 1,
    wordAt: identityWord,
  };

  switch (intent) {
    case "fade_in": {
      return {
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [0, fps * 0.7], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [fps * 0.3, fps * 1.0], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.6, fps * 1.3], [0, 1], clampRight),
        resultScale: 1,
        chipOpacity: interpolate(frame, [fps * 0.9, fps * 1.6], [0, 1], clampRight),
      };
    }
    case "snap_in_then_settle": {
      // Deliberately overshooting spring — the snap IS the language; the
      // mood only flavours the settle.
      const snap = spring({
        frame,
        fps,
        config: { damping: 9, stiffness: 220, mass: 0.5 },
      });
      return {
        ...base,
        heroY: interpolate(snap, [0, 1], [90, 0]),
        heroOpacity: interpolate(frame, [0, fps * 0.2], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.35, fps * 0.7], [0, 1], clampRight),
        resultScale: interpolate(snap, [0, 1], [1.06, 1.0]),
        chipOpacity: interpolate(frame, [fps * 0.6, fps * 1.0], [0, 1], clampRight),
      };
    }
    case "slide_up": {
      const eased = interpolate(frame, [0, fps * 0.8], [1, 0], {
        ...clampRight,
        easing: Easing.out(Easing.cubic),
      });
      return {
        ...base,
        heroY: eased * 240,
        heroOpacity: interpolate(frame, [0, fps * 0.5], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [fps * 0.4, fps * 0.9], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.7, fps * 1.2], [0, 1], clampRight),
        chipOpacity: interpolate(frame, [fps * 1.0, fps * 1.5], [0, 1], clampRight),
      };
    }
    case "scale_in": {
      const grow = spring({ frame, fps, config: moodSpring });
      return {
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [0, fps * 0.4], [0, 1], clampRight),
        heroScale: interpolate(grow, [0, 1], [0.82, 1.0]),
        resultOpacity: interpolate(frame, [fps * 0.5, fps * 1.0], [0, 1], clampRight),
        resultScale: interpolate(grow, [0, 1], [0.82, 1.0]),
        chipOpacity: interpolate(frame, [fps * 0.9, fps * 1.4], [0, 1], clampRight),
      };
    }
    case "crossfade": {
      // Layered opacity beats, no movement: hero → secondary → result → chrome.
      return {
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [0, fps * 0.5], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [fps * 0.45, fps * 0.95], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.9, fps * 1.4], [0, 1], clampRight),
        resultScale: 1,
        chipOpacity: interpolate(frame, [fps * 1.35, fps * 1.85], [0, 1], clampRight),
      };
    }
    case "kinetic_type": {
      // Per-word staggered reveal — the type itself carries the energy.
      // The hero line's block opacity is 1; each word owns its reveal.
      return {
        ...base,
        heroY: 0,
        heroOpacity: 1,
        secondaryOpacity: interpolate(frame, [fps * 0.6, fps * 1.0], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.8, fps * 1.2], [0, 1], clampRight),
        chipOpacity: interpolate(frame, [fps * 1.1, fps * 1.6], [0, 1], clampRight),
        wordAt: (i: number) => {
          const start = fps * 0.12 * i;
          const s = spring({
            frame: Math.max(0, frame - start),
            fps,
            config: { damping: 14, stiffness: 160, mass: 0.6 },
          });
          return {
            y: interpolate(s, [0, 1], [70, 0]),
            opacity: interpolate(
              frame,
              [start, start + fps * 0.25],
              [0, 1],
              clampRight,
            ),
          };
        },
      };
    }
    case "parallax": {
      // The surfaces drift at different rates across the WHOLE clip.
      const drift = interpolate(frame, [0, durationInFrames], [0, 60]);
      return {
        ...base,
        bgDrift: drift,
        photoScale: interpolate(frame, [0, durationInFrames], [1.0, 1.07]),
      };
    }
    case "count_up": {
      // The number IS the animation: the result ticks up from zero and
      // settles — with a small confirmation pulse — on the exact verified
      // value, which then holds for the rest of the clip. A calm fade
      // programme carries the layers around it.
      return {
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [0, fps * 0.5], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [fps * 0.25, fps * 0.8], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [fps * 0.15, fps * 0.45], [0, 1], clampRight),
        resultScale: interpolate(
          frame,
          [fps * 1.55, fps * 1.75, fps * 1.95],
          [1.0, 1.05, 1.0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        ),
        chipOpacity: interpolate(frame, [fps * 0.9, fps * 1.4], [0, 1], clampRight),
        resultProgress: interpolate(frame, [fps * 0.3, fps * 1.6], [0, 1], {
          ...clampRight,
          easing: Easing.out(Easing.cubic),
        }),
      };
    }
    case "static": {
      // Everything present from frame 0 — the card IS the statement.
      return {
        heroY: 0,
        heroOpacity: 1,
        heroScale: 1,
        secondaryOpacity: 1,
        resultOpacity: 1,
        resultScale: 1,
        chipOpacity: 1,
        bgDrift: 0,
        photoScale: 1,
        resultProgress: 1,
        wordAt: identityWord,
      };
    }
    default: {
      // Sprint intents (R1.1) register their own file under sprint/intents/.
      const extra = EXTRA_INTENTS[intent];
      return extra ? extra(frame, fps, durationInFrames, mood, base) : base;
    }
  }
}

// ---------------------------------------------------------------------------
// Archetype scene system (Gen v2 parity)
// ---------------------------------------------------------------------------
//
// The still engine's archetypes map onto eight structurally distinct motion
// scenes, so a card's video reads like its still instead of every archetype
// collapsing into one hero layout. Each archetype picks the scene group whose
// motion choreography matches its still composition. Unknown / v1 names keep
// the "hero" scene — the pre-parity behaviour.

type SceneMode =
  | "hero"
  | "poster"
  | "lowerThird"
  | "spotlight"
  | "grid"
  | "ticker"
  | "split"
  | "magazine";

function sceneForArchetype(archetype: string): SceneMode {
  switch (archetype) {
    case "big_number_dominant":
    case "minimal_type_poster":
    case "quote_led_recap":
    case "cornerstone_numeral":
    case "mega_surname_bleed":
      return "poster";
    case "full_bleed_photo_lower_third":
    case "broadcast_scorebug":
      return "lowerThird";
    case "centered_medal_spotlight":
    case "photo_passepartout":
    case "spotlight_disc":
      return "spotlight";
    case "editorial_numbers_grid":
    case "stat_stack_sidebar":
    case "index_card":
    case "scoreline_versus":
      return "grid";
    case "ticker_strip":
    case "horizon_band":
      return "ticker";
    case "split_diagonal_hero":
    case "duo_athlete_split":
    case "triptych_progression":
      return "split";
    case "magazine_cover":
      return "magazine";
    default:
      return "hero";
  }
}

// Map brief.composition → where the surname/result block lives. The
// values match the four positions the static renderer supports
// (graphic_renderer/render.py:_composition_overrides_css).
function compositionLayoutFor(
  composition: string,
  width: number,
): { textLeft: number; textAlign: "left" | "right" | "center"; surnameRight: number } {
  switch (composition) {
    case "left":
      return { textLeft: 80, textAlign: "left", surnameRight: -width * 0.06 };
    case "right":
      return { textLeft: width * 0.45, textAlign: "left", surnameRight: width * 0.42 };
    case "center":
      return { textLeft: width * 0.08, textAlign: "center", surnameRight: width * 0.5 };
    case "off-center":
      return { textLeft: width * 0.18, textAlign: "left", surnameRight: -width * 0.02 };
    default:
      return { textLeft: 80, textAlign: "left", surnameRight: -width * 0.06 };
  }
}

// Map brief.accent_style → a small decorative element. Returns null
// when "minimal" or unknown so the composition stays clean.
function accentDecoration(
  style: string,
  roles: Roles,
  opacity: number,
  width: number,
  height: number,
): React.ReactNode {
  const accent = roles.accent;
  switch (style) {
    case "stripe":
      return (
        <div
          style={{
            position: "absolute",
            left: 80,
            top: height * 0.42,
            width: 120,
            height: 6,
            background: accent,
            opacity,
          }}
        />
      );
    case "brackets":
      return (
        <>
          <div
            style={{
              position: "absolute",
              left: 60,
              top: height * 0.43,
              width: 40,
              height: 40,
              borderLeft: `4px solid ${accent}`,
              borderTop: `4px solid ${accent}`,
              opacity,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: width - 100,
              bottom: height * 0.2,
              width: 40,
              height: 40,
              borderRight: `4px solid ${accent}`,
              borderBottom: `4px solid ${accent}`,
              opacity,
            }}
          />
        </>
      );
    case "underline":
      return (
        <div
          style={{
            position: "absolute",
            left: 80,
            top: height * 0.82,
            width: 240,
            height: 4,
            background: accent,
            opacity,
          }}
        />
      );
    case "arrow":
      return (
        <div
          style={{
            position: "absolute",
            left: width - 160,
            top: height * 0.5,
            width: 0,
            height: 0,
            borderTop: "20px solid transparent",
            borderBottom: "20px solid transparent",
            borderLeft: `30px solid ${accent}`,
            opacity,
          }}
        />
      );
    case "ribbon":
      return (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: height * 0.36,
            width: 320,
            height: 48,
            background: accent,
            opacity,
            transform: "skewX(-12deg)",
            transformOrigin: "left center",
          }}
        />
      );
    case "frame":
      return (
        <div
          style={{
            position: "absolute",
            left: 40,
            top: 40,
            right: 40,
            bottom: 40,
            border: `3px solid ${accent}`,
            opacity: opacity * 0.4,
            pointerEvents: "none",
          }}
        />
      );
    case "badge":
      return (
        <div
          style={{
            position: "absolute",
            right: 80,
            bottom: height * 0.22,
            width: 90,
            height: 90,
            borderRadius: "50%",
            border: `4px solid ${accent}`,
            opacity,
          }}
        />
      );
    case "minimal":
      return null;
    default: {
      // Sprint accents (R1.5) register their own file under sprint/accents/.
      const extra = EXTRA_ACCENTS[style];
      return extra ? extra(roles, opacity, width, height) : null;
    }
  }
}

// Split a display line into words for the kinetic_type programme.
function words(text: string): string[] {
  return (text || "").split(/\s+/).filter(Boolean);
}

// Deterministic single-line fit: shrink a base font size until the line's
// estimated width (char count × an average glyph ratio for the heavy display
// faces) fits the box. The cheap TSX cousin of the still renderer's measured
// autofit — long surnames shrink instead of overflowing.
function fitLinePx(text: string, basePx: number, maxWidth: number, glyphRatio = 0.58): number {
  const chars = Math.max(1, (text || "").length);
  const fitted = Math.floor(maxWidth / (chars * glyphRatio));
  return Math.max(40, Math.min(basePx, fitted));
}

// Formatting-preserving numeric count-up for the result value: "1:02.45"
// at 40% renders as "0:24.98" — same shape, same decimal places — and
// settles on the EXACT verified string at progress 1 (the original text is
// returned verbatim, never a reformat). Non-numeric results ("DQ", "—")
// pass through untouched at every progress value. Pure function — the
// count is driven by the frame-derived progress channel.
function countUpDisplay(text: string, progress: number): string {
  const t = (text || "").trim();
  if (progress >= 1 || !t) {
    return text;
  }
  const p = Math.max(0, progress);
  const mTime = t.match(/^(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?$/);
  if (mTime) {
    // Integer maths in fractional-second units so float drift can never
    // produce an impossible reading like "1:60.00" mid-count.
    const minDigits = mTime[1].length;
    const frac = mTime[3] || "";
    const unit = Math.pow(10, frac.length); // ticks per second
    const totalTicks =
      (parseInt(mTime[1], 10) * 60 + parseInt(mTime[2], 10)) * unit +
      (frac ? parseInt(frac, 10) : 0);
    const scaledTicks = Math.floor(totalTicks * p);
    const m = Math.floor(scaledTicks / (60 * unit));
    const restTicks = scaledTicks - m * 60 * unit;
    const secWhole = Math.floor(restTicks / unit);
    const secStr = frac
      ? `${String(secWhole).padStart(2, "0")}.${String(restTicks % unit).padStart(frac.length, "0")}`
      : String(secWhole).padStart(2, "0");
    return `${String(m).padStart(minDigits, "0")}:${secStr}`;
  }
  const mNum = t.match(/^(\d+)(?:\.(\d+))?$/);
  if (mNum) {
    const decimals = (mNum[2] || "").length;
    return (parseFloat(t) * p).toFixed(decimals);
  }
  return text;
}

// Display ordinal for a numeric placing ("1" → "1ST"); non-numeric values
// pass through untouched — never invent a placing that wasn't detected.
function placeDisplay(place: string): string {
  const m = (place || "").trim().match(/^(\d+)$/);
  if (!m) {
    return (place || "").trim().toUpperCase();
  }
  const n = parseInt(m[1], 10);
  const tens = n % 100;
  const suffix =
    tens >= 11 && tens <= 13
      ? "TH"
      : n % 10 === 1
        ? "ST"
        : n % 10 === 2
          ? "ND"
          : n % 10 === 3
            ? "RD"
            : "TH";
  return `${n}${suffix}`;
}

// Staggered word row used by the kinetic_type-aware hero/poster scenes.
const KineticLine: React.FC<{
  text: string;
  anim: AnimChannels;
  style: React.CSSProperties;
  startIndex?: number;
}> = ({ text, anim, style, startIndex = 0 }) => {
  const parts = words(text);
  if (parts.length === 0) {
    return null;
  }
  return (
    <div style={style}>
      {parts.map((w, i) => {
        const a = anim.wordAt(startIndex + i);
        return (
          <span
            key={`${w}-${i}`}
            style={{
              display: "inline-block",
              transform: `translateY(${a.y}px)`,
              opacity: a.opacity,
              marginRight: "0.28em",
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

// Shared per-scene context, built once in the component body.
export type SceneCtx = {
  card: CardProps;
  brand: BrandProps;
  roles: Roles;
  anim: AnimChannels;
  fontStack: string;
  frame: number;
  fps: number;
  width: number;
  height: number;
  ts: number; // type scale — 1.0 at 1080×1920, shrinks for square/landscape
  layout: ReturnType<typeof compositionLayoutFor>;
  surnameText: string;
  firstName: string;
  label: string;
  event: string;
  result: string; // display text — mid-count during the count_up intent
  resultFinal: string; // the verbatim verified value — use for fitting/crawls
  meet: string;
  club: string;
};

const PhotoLayer: React.FC<{ ctx: SceneCtx; scrim?: "bottom" | "full" }> = ({
  ctx,
  scrim = "full",
}) => {
  const { card, roles, anim } = ctx;
  if (!card.photoSrc) {
    return null;
  }
  return (
    <>
      <img
        src={card.photoSrc}
        alt=""
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: card.photoPos || "center 28%",
          transform: `scale(${anim.photoScale})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            scrim === "bottom"
              ? `linear-gradient(180deg, ${roles.ground}10 0%, ${roles.ground}30 55%, ${roles.ground}E8 88%)`
              : `linear-gradient(180deg, ${roles.ground}40 0%, ${roles.ground}B0 55%, ${roles.ground}F0 100%)`,
        }}
      />
    </>
  );
};

const PatternLayer: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const bgPattern = bgPatternFor(ctx.card.backgroundStyle || "", ctx.roles);
  if (!bgPattern) {
    return null;
  }
  return (
    <div
      style={{
        position: "absolute",
        inset: -80,
        backgroundImage: bgPattern,
        backgroundRepeat: "repeat",
        opacity: 0.85,
        pointerEvents: "none",
        transform: `translateY(${ctx.anim.bgDrift}px)`,
      }}
    />
  );
};

// ---------------------------------------------------------------------------
// Style-pack overlay — still↔motion parity with graphic_renderer.style_packs.
//
// The still renderer drops a ground / texture / accent-geometry overlay into
// each archetype's {{ACCENT_DECORATION}} slot; this mirrors it verbatim on the
// motion side so a card's video carries the exact same decorative treatment.
// Same lever semantics and the same capped, legibility-safe values: ground is
// darken-only, texture is a low-opacity blended tile (the grain precedent), and
// accent geometry lives in the margins painted in the resolved accent role — so
// no role colour is invented and text contrast is never reduced. Pack id shape:
// "ground-texture-accentGeo-density" (see style_packs.StylePack.id).
// ---------------------------------------------------------------------------

const PACK_GROUNDS = new Set([
  "flat", "top_fade", "bottom_fade", "corner_fade", "vignette", "spotlight", "twotone",
  "dual_fade", "top_corner_fade", "edge_frame", "diagonal_fade",
  // Ground-treatment expansion pack (mirrors style_packs.GROUNDS).
  "gradient_mesh", "bokeh", "light_ray", "paper_weave",
]);
const PACK_TEXTURES = new Set([
  "none", "grain", "dots", "grid", "hatch", "halftone", "crosshatch",
  "weave", "scanline", "carbon", "chevron",
  // Layered (two-texture) surfaces — G1.6, mirrors style_packs._TEXTURE_STACKS.
  "grain_dots", "halftone_weave", "hatch_grid", "crosshatch_grain",
  "dots_scanline", "carbon_hatch", "chevron_grain", "grid_dots",
]);
const PACK_ACCENT_GEOS = new Set([
  "none", "corner_ticks", "side_rule", "baseline_rule", "frame", "wedge", "ring", "corner_blocks",
  "double_rule", "dot_row", "cross_ticks", "corner_arc",
  "hexagons", "deco_corners", "wave_rule", "spiral_flourish", "glitch_divider",
]);

type ParsedPack = { ground: string; texture: string; accentGeo: string; bold: boolean };

// Parse a pack id into its levers, or null for the bare/unknown pack (→ no
// overlay, byte-equivalent to the still's bare card).
function parseStylePack(id: string): ParsedPack | null {
  const parts = (id || "").split("-");
  if (parts.length !== 4) {
    return null;
  }
  const [ground, texture, accentGeo, density] = parts;
  if (
    !PACK_GROUNDS.has(ground) ||
    !PACK_TEXTURES.has(texture) ||
    !PACK_ACCENT_GEOS.has(accentGeo)
  ) {
    return null;
  }
  if (ground === "flat" && texture === "none" && accentGeo === "none") {
    return null; // the bare pack
  }
  return { ground, texture, accentGeo, bold: density === "bold" };
}

function packGroundGradient(ground: string, a: number): string | null {
  switch (ground) {
    case "vignette":
      return `radial-gradient(115% 95% at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,${a}) 100%)`;
    case "spotlight":
      return `radial-gradient(60% 50% at 50% 38%, rgba(0,0,0,0) 0%, rgba(0,0,0,${a}) 100%)`;
    case "top_fade":
      return `linear-gradient(180deg, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 44%)`;
    case "bottom_fade":
      return `linear-gradient(0deg, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 44%)`;
    case "corner_fade":
      return `radial-gradient(125% 125% at 100% 100%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 55%)`;
    case "twotone":
      return `linear-gradient(122deg, rgba(0,0,0,0) 46%, rgba(0,0,0,${a}) 92%)`;
    case "dual_fade":
      return (
        `linear-gradient(180deg, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 30%, ` +
        `rgba(0,0,0,0) 70%, rgba(0,0,0,${a}) 100%)`
      );
    case "top_corner_fade":
      return `radial-gradient(125% 125% at 0% 0%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 55%)`;
    case "edge_frame":
      return (
        `linear-gradient(90deg, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 18%, ` +
        `rgba(0,0,0,0) 82%, rgba(0,0,0,${a}) 100%),` +
        `linear-gradient(180deg, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 18%, ` +
        `rgba(0,0,0,0) 82%, rgba(0,0,0,${a}) 100%)`
      );
    case "diagonal_fade":
      return `linear-gradient(122deg, rgba(0,0,0,${a}) 8%, rgba(0,0,0,0) 54%)`;
    // --- Ground-treatment expansion pack (mirrors style_packs._ground_layer) ---
    case "gradient_mesh":
      return (
        `radial-gradient(62% 55% at 14% 12%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 60%),` +
        `radial-gradient(58% 52% at 86% 18%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 60%),` +
        `radial-gradient(85% 60% at 50% 104%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 58%)`
      );
    case "bokeh":
      return (
        `radial-gradient(20% 14% at 16% 82%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 72%),` +
        `radial-gradient(14% 10% at 82% 14%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 72%),` +
        `radial-gradient(11% 8% at 92% 70%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 72%),` +
        `radial-gradient(9% 6% at 8% 30%, rgba(0,0,0,${a}) 0%, rgba(0,0,0,0) 72%)`
      );
    case "light_ray":
      return (
        `repeating-conic-gradient(from 192deg at 84% -8%, ` +
        `rgba(0,0,0,0) 0deg, rgba(0,0,0,0) 10deg, ` +
        `rgba(0,0,0,${a}) 13deg, rgba(0,0,0,0) 16deg)`
      );
    case "paper_weave":
      return (
        `repeating-linear-gradient(90deg, rgba(0,0,0,${a}) 0, rgba(0,0,0,${a}) 2px, ` +
        `rgba(0,0,0,0) 2px, rgba(0,0,0,0) 14px),` +
        `repeating-linear-gradient(0deg, rgba(0,0,0,${a}) 0, rgba(0,0,0,${a}) 2px, ` +
        `rgba(0,0,0,0) 2px, rgba(0,0,0,0) 14px)`
      );
    default:
      return null;
  }
}

const PACK_TEX_SIZE: Record<string, number> = {
  grain: 160, dots: 18, grid: 32, hatch: 14, crosshatch: 16, halftone: 22,
  weave: 20, scanline: 6, carbon: 8, chevron: 24,
};

// Layered textures (G1.6) — a composite token fuses two base tiles with a
// background-blend-mode, mirroring style_packs._TEXTURE_STACKS so a card's video
// carries the same stacked surface as its still. [base_a, base_b, blend].
const PACK_TEXTURE_STACKS: Record<string, [string, string, string]> = {
  "grain_dots": ["grain", "dots", "soft-light"],
  "halftone_weave": ["halftone", "weave", "overlay"],
  "hatch_grid": ["hatch", "grid", "lighten"],
  "crosshatch_grain": ["crosshatch", "grain", "screen"],
  "dots_scanline": ["dots", "scanline", "screen"],
  "carbon_hatch": ["carbon", "hatch", "overlay"],
  "chevron_grain": ["chevron", "grain", "soft-light"],
  "grid_dots": ["grid", "dots", "lighten"],
};

// White-on-transparent tiles (blended over the ground), mirroring style_packs.
function packTextureImage(texture: string): string | null {
  const enc = (svg: string) => `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  switch (texture) {
    case "grain":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>` +
        `<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter>` +
        `<rect width='100%' height='100%' filter='url(#n)' opacity='0.5'/></svg>`,
      );
    case "dots":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18'>` +
        `<circle cx='3' cy='3' r='1.4' fill='white'/></svg>`,
      );
    case "grid":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32'>` +
        `<path d='M32 0H0V32' fill='none' stroke='white' stroke-width='1'/></svg>`,
      );
    case "hatch":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14'>` +
        `<path d='M-2 16L16 -2' stroke='white' stroke-width='1.4'/></svg>`,
      );
    case "crosshatch":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16'>` +
        `<path d='M-2 18L18 -2M-2 -2L18 18' stroke='white' stroke-width='1.1'/></svg>`,
      );
    case "halftone":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22'>` +
        `<circle cx='6' cy='6' r='3.2' fill='white'/><circle cx='17' cy='17' r='1.6' fill='white'/></svg>`,
      );
    case "weave":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20'>` +
        `<rect x='0' y='8' width='20' height='3' fill='white'/>` +
        `<rect x='8' y='0' width='3' height='20' fill='white'/></svg>`,
      );
    case "scanline":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='6' height='6'>` +
        `<rect width='6' height='1' fill='white'/></svg>`,
      );
    case "carbon":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'>` +
        `<path d='M0 8L8 0' stroke='white' stroke-width='1'/>` +
        `<path d='M-2 2L2 -2' stroke='white' stroke-width='1'/>` +
        `<path d='M6 10L10 6' stroke='white' stroke-width='1'/></svg>`,
      );
    case "chevron":
      return enc(
        `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='12'>` +
        `<path d='M0 12L12 3L24 12' fill='none' stroke='white' stroke-width='1.4'/></svg>`,
      );
    default:
      return null;
  }
}

// Accent geometry confined to the margins, painted in the resolved accent role.
function packAccentGeometry(
  style: string, width: number, height: number, bold: boolean, accent: string,
): React.ReactNode {
  const mult = bold ? 1.35 : 1.0;
  const weight = Math.max(3, Math.round(Math.min(width, height) * 0.006 * mult));
  const m = Math.min(width, height);
  switch (style) {
    case "corner_ticks": {
      const arm = Math.round(m * 0.085 * mult);
      const off = Math.round(m * 0.05);
      return (
        <>
          <div style={{ position: "absolute", left: off, top: off, width: arm, height: arm, borderTop: `${weight}px solid ${accent}`, borderLeft: `${weight}px solid ${accent}` }} />
          <div style={{ position: "absolute", right: off, bottom: off, width: arm, height: arm, borderBottom: `${weight}px solid ${accent}`, borderRight: `${weight}px solid ${accent}` }} />
        </>
      );
    }
    case "corner_blocks": {
      const sq = Math.round(m * 0.05 * mult);
      const off = Math.round(m * 0.045);
      const op = bold ? 0.92 : 0.8;
      return (
        <>
          <div style={{ position: "absolute", left: off, top: off, width: sq, height: sq, background: accent, opacity: op }} />
          <div style={{ position: "absolute", right: off, bottom: off, width: sq, height: sq, background: accent, opacity: op }} />
        </>
      );
    }
    case "frame": {
      const inset = Math.round(m * 0.035);
      return <div style={{ position: "absolute", left: inset, right: inset, top: inset, bottom: inset, border: `${weight}px solid ${accent}`, opacity: bold ? 0.7 : 0.5 }} />;
    }
    case "side_rule": {
      const bw = Math.max(5, Math.round(width * 0.012 * mult));
      const inset = Math.round(height * 0.1);
      return <div style={{ position: "absolute", left: 0, top: inset, bottom: inset, width: bw, background: accent }} />;
    }
    case "baseline_rule": {
      const bh = Math.max(5, Math.round(height * 0.009 * mult));
      const inset = Math.round(width * 0.08);
      const bottom = Math.round(height * 0.06);
      return <div style={{ position: "absolute", left: inset, right: inset, bottom, height: bh, background: accent }} />;
    }
    case "wedge": {
      const size = Math.round(m * 0.16 * mult);
      return <div style={{ position: "absolute", right: 0, top: 0, width: 0, height: 0, borderTop: `${size}px solid ${accent}`, borderLeft: `${size}px solid transparent` }} />;
    }
    case "ring": {
      const d = Math.round(m * 0.16 * mult);
      const off = Math.round(m * 0.06);
      return <div style={{ position: "absolute", right: off, top: off, width: d, height: d, border: `${weight}px solid ${accent}`, borderRadius: "50%", opacity: bold ? 0.85 : 0.65 }} />;
    }
    case "double_rule": {
      const bh = Math.max(4, Math.round(height * 0.007 * mult));
      const inset = Math.round(width * 0.08);
      const bottom = Math.round(height * 0.06);
      const gap = bh * 3;
      return (
        <>
          <div style={{ position: "absolute", left: inset, right: inset, bottom, height: bh, background: accent }} />
          <div style={{ position: "absolute", left: inset, right: inset, bottom: bottom + gap, height: bh, background: accent, opacity: 0.55 }} />
        </>
      );
    }
    case "dot_row": {
      const d = Math.max(7, Math.round(m * 0.013 * mult));
      const bottom = Math.round(height * 0.065);
      const gap = d * 2;
      return (
        <div style={{ position: "absolute", left: 0, right: 0, bottom, display: "flex", justifyContent: "center", gap }}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <span key={i} style={{ width: d, height: d, borderRadius: "50%", background: accent, display: "inline-block" }} />
          ))}
        </div>
      );
    }
    case "cross_ticks": {
      const arm = Math.round(m * 0.028 * mult);
      const off = Math.round(m * 0.06);
      const cross = (key: string, pos: React.CSSProperties) => (
        <React.Fragment key={key}>
          <div style={{ position: "absolute", ...pos, width: arm * 2, height: weight, background: accent }} />
          <div style={{ position: "absolute", ...pos, width: weight, height: arm * 2, background: accent }} />
        </React.Fragment>
      );
      return (
        <>
          {cross("tl", { left: off, top: off })}
          {cross("br", { right: off, bottom: off })}
        </>
      );
    }
    case "corner_arc": {
      const arm = Math.round(m * 0.11 * mult);
      const off = Math.round(m * 0.05);
      return (
        <>
          <div style={{ position: "absolute", left: off, top: off, width: arm, height: arm, borderTop: `${weight}px solid ${accent}`, borderLeft: `${weight}px solid ${accent}`, borderTopLeftRadius: "100%" }} />
          <div style={{ position: "absolute", right: off, bottom: off, width: arm, height: arm, borderBottom: `${weight}px solid ${accent}`, borderRight: `${weight}px solid ${accent}`, borderBottomRightRadius: "100%" }} />
        </>
      );
    }
    // --- G1.5 accent-geometry expansion pack (mirrors style_packs.py) ------
    // Curved/ornamental shapes drawn as stroked inline SVG (the div-border
    // tricks above can't express them); stroke paints the resolved accent,
    // vector-effect keeps it a true `weight` px regardless of viewBox scale.
    case "hexagons": {
      const size = Math.round(m * 0.16 * mult);
      const off = Math.round(m * 0.05);
      const hex = (
        <polygon points="92,50 71,86 29,86 8,50 29,14 71,14" fill="none" vectorEffect="non-scaling-stroke" style={{ stroke: accent, strokeWidth: weight, strokeLinejoin: "round" }} />
      );
      return (
        <>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", left: off, top: off, width: size, height: size }}>{hex}</svg>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", right: off, bottom: off, width: size, height: size }}>{hex}</svg>
        </>
      );
    }
    case "deco_corners": {
      const size = Math.round(m * 0.15 * mult);
      const off = Math.round(m * 0.045);
      const d = "M 64 8 L 8 8 L 8 64 M 50 21 L 21 21 L 21 50 M 38 31 L 31 31 L 31 38";
      const bracket = (
        <path d={d} fill="none" vectorEffect="non-scaling-stroke" style={{ stroke: accent, strokeWidth: weight, strokeLinecap: "square" }} />
      );
      return (
        <>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", left: off, top: off, width: size, height: size }}>{bracket}</svg>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", right: off, bottom: off, width: size, height: size, transform: "rotate(180deg)" }}>{bracket}</svg>
        </>
      );
    }
    case "wave_rule": {
      const inset = Math.round(width * 0.08);
      const inner = Math.max(1, width - 2 * inset);
      const band = Math.max(12, Math.round(height * 0.022 * mult));
      const bottom = Math.round(height * 0.06);
      return (
        <svg viewBox={`0 0 ${inner} ${band}`} preserveAspectRatio="none" style={{ position: "absolute", left: inset, width: inner, bottom, height: band }}>
          <path d={packWavePath(inner, band)} fill="none" style={{ stroke: accent, strokeWidth: weight, strokeLinecap: "round" }} />
        </svg>
      );
    }
    case "spiral_flourish": {
      const size = Math.round(m * 0.15 * mult);
      const off = Math.round(m * 0.05);
      const spiral = (
        <polyline points={packSpiralPoints()} fill="none" vectorEffect="non-scaling-stroke" style={{ stroke: accent, strokeWidth: weight, strokeLinecap: "round", strokeLinejoin: "round" }} />
      );
      return (
        <>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", left: off, top: off, width: size, height: size }}>{spiral}</svg>
          <svg viewBox="0 0 100 100" style={{ position: "absolute", right: off, bottom: off, width: size, height: size, transform: "rotate(180deg)" }}>{spiral}</svg>
        </>
      );
    }
    case "glitch_divider": {
      const bh = Math.max(4, Math.round(height * 0.006 * mult));
      const inset = Math.round(width * 0.08);
      const inner = Math.max(1, width - 2 * inset);
      const bottom = Math.round(height * 0.06);
      const gap = Math.max(2, bh);
      return (
        <>
          <div style={{ position: "absolute", left: inset, width: inner, bottom, height: bh, background: accent }} />
          <div style={{ position: "absolute", left: inset + Math.round(inner * 0.12), width: Math.round(inner * 0.55), bottom: bottom + bh + gap, height: bh, background: accent, opacity: 0.7 }} />
          <div style={{ position: "absolute", left: inset, width: Math.round(inner * 0.34), bottom: bottom + 2 * (bh + gap), height: bh, background: accent, opacity: 0.45 }} />
        </>
      );
    }
    default:
      return null;
  }
}

// A smooth horizontal sine as alternating cubic-bézier humps, in px units
// (the wave SVG's viewBox is the px region itself). Mirrors style_packs._wave_path.
function packWavePath(inner: number, band: number, humps = 7): string {
  const amp = band * 0.3;
  const mid = band / 2;
  const half = inner / humps;
  let d = `M 0 ${mid.toFixed(1)}`;
  let x = 0;
  let up = true;
  while (x < inner - 0.5) {
    const nx = Math.min(x + half, inner);
    const cy = up ? mid - amp : mid + amp;
    const c1 = x + half * 0.36;
    const c2 = x + half * 0.64;
    d += ` C ${c1.toFixed(1)} ${cy.toFixed(1)} ${c2.toFixed(1)} ${cy.toFixed(1)} ${nx.toFixed(1)} ${mid.toFixed(1)}`;
    x = nx;
    up = !up;
  }
  return d;
}

// An Archimedean spiral sampled as a polyline in a 0–100 viewBox, centred at
// (50, 50). Mirrors style_packs._spiral_points.
function packSpiralPoints(steps = 72, turns = 2.4, maxR = 44): string {
  const pts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const ang = t * turns * 2 * Math.PI;
    const r = maxR * t;
    pts.push(`${(50 + r * Math.cos(ang)).toFixed(1)},${(50 + r * Math.sin(ang)).toFixed(1)}`);
  }
  return pts.join(" ");
}

const StylePackLayer: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const pack = parseStylePack(ctx.card.stylePack || "");
  if (!pack) {
    return null;
  }
  const { width, height, frame, roles } = ctx;
  const accent = roles.accent || "#FFFFFF";
  // Ease the whole treatment in with the scene (motion only for feedback).
  const enter = interpolate(frame, [2, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const children: React.ReactNode[] = [];

  const ground = packGroundGradient(pack.ground, pack.bold ? 0.34 : 0.24);
  if (ground) {
    children.push(
      <div key="ground" style={{ position: "absolute", inset: 0, background: ground }} />,
    );
  }
  const stack = PACK_TEXTURE_STACKS[pack.texture];
  if (stack) {
    // Layered surface (G1.6): fuse two tiles with a background-blend-mode, then
    // composite onto the card with the shared low-opacity mix-blend overlay —
    // exactly as legibility-safe as one tile, just richer (mirrors the still).
    const [a, b, blend] = stack;
    const ta = packTextureImage(a);
    const tb = packTextureImage(b);
    if (ta && tb) {
      const sa = PACK_TEX_SIZE[a] || 20;
      const sb = PACK_TEX_SIZE[b] || 20;
      children.push(
        <div
          key="texture"
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage: `${ta}, ${tb}`,
            backgroundSize: `${sa}px ${sa}px, ${sb}px ${sb}px`,
            backgroundRepeat: "repeat, repeat",
            backgroundBlendMode: blend,
            opacity: pack.bold ? 0.15 : 0.1,
            mixBlendMode: "overlay",
          }}
        />,
      );
    }
  } else {
    const tex = packTextureImage(pack.texture);
    if (tex) {
      const size = PACK_TEX_SIZE[pack.texture] || 20;
      const op = pack.texture === "grain" ? (pack.bold ? 0.18 : 0.12) : pack.bold ? 0.16 : 0.1;
      children.push(
        <div
          key="texture"
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage: tex,
            backgroundSize: `${size}px ${size}px`,
            backgroundRepeat: "repeat",
            opacity: op,
            mixBlendMode: "overlay",
          }}
        />,
      );
    }
  }
  const geo = packAccentGeometry(pack.accentGeo, width, height, pack.bold, accent);
  if (geo) {
    children.push(<React.Fragment key="geo">{geo}</React.Fragment>);
  }

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", opacity: enter }}>
      {children}
    </div>
  );
};

const LogoChip: React.FC<{ ctx: SceneCtx; size?: number }> = ({ ctx, size = 140 }) => {
  const { brand, anim, width, ts } = ctx;
  if (!brand.logoDataUri) {
    return null;
  }
  const s = Math.round(size * ts);
  return (
    <img
      src={brand.logoDataUri}
      alt={brand.displayName || "club logo"}
      style={{
        position: "absolute",
        top: Math.round(100 * ts),
        right: Math.min(80, width * 0.06),
        width: s,
        height: s,
        objectFit: "contain",
        opacity: anim.chipOpacity,
      }}
    />
  );
};

const BottomStrip: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { roles, anim, ts, meet, club } = ctx;
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: Math.round(80 * ts),
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: Math.round(28 * ts),
        letterSpacing: "0.08em",
        color: roles.onGround,
        opacity: anim.chipOpacity * 0.85,
        textTransform: "uppercase",
      }}
    >
      <span>{meet}</span>
      <span style={{ fontWeight: 700 }}>{club}</span>
    </div>
  );
};

const LabelChip: React.FC<{ ctx: SceneCtx; left?: number; top?: number; center?: boolean }> = ({
  ctx,
  left = 80,
  top,
  center = false,
}) => {
  const { roles, anim, ts, label } = ctx;
  return (
    <div
      style={{
        position: "absolute",
        top: top ?? Math.round(140 * ts),
        ...(center
          ? { left: "50%", transform: "translateX(-50%)" }
          : { left }),
        padding: `${Math.round(14 * ts)}px ${Math.round(28 * ts)}px`,
        background: roles.accent,
        color: roles.ground,
        fontSize: Math.round(36 * ts),
        fontWeight: 800,
        letterSpacing: "0.12em",
        opacity: anim.chipOpacity,
        borderRadius: 6,
        whiteSpace: "nowrap",
        maxWidth: ctx.width - 160,
        overflow: "hidden",
      }}
    >
      {label || "STRONG SWIM"}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Scenes
// ---------------------------------------------------------------------------

// The original hero scene — watermark surname, stacked name/event/result.
const HeroScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts, layout } = ctx;
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />

      {/* Surface band — slim diagonal accent for energy */}
      <div
        style={{
          position: "absolute",
          width: width * 1.6,
          height: Math.round(220 * ts),
          background: roles.surface,
          opacity: 0.85,
          left: -width * 0.3,
          top: height * 0.78,
          transform: "rotate(-6deg)",
        }}
      />

      {accentDecoration(card.accentStyle || "", roles, anim.chipOpacity, width, height)}

      {/* Mega watermark surname behind everything */}
      <div
        style={{
          position: "absolute",
          top: height * 0.18,
          right: layout.surnameRight,
          fontSize: Math.min(width, height) * 0.32,
          fontWeight: 900,
          letterSpacing: "-0.02em",
          color: roles.accent,
          opacity: 0.12,
          lineHeight: 0.9,
          transform: `translateY(${anim.heroY * 0.4}px)`,
          textTransform: "uppercase",
        }}
      >
        {ctx.surnameText}
      </div>

      <LabelChip ctx={ctx} />
      <LogoChip ctx={ctx} />

      {/* Athlete first name */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.45,
          fontSize: Math.round(96 * ts),
          fontWeight: 700,
          color: roles.onGround,
          letterSpacing: "-0.01em",
          opacity: anim.heroOpacity,
          textAlign: layout.textAlign,
          transform: `translateY(${anim.heroY * 0.3}px) scale(${anim.heroScale})`,
          transformOrigin: "left center",
        }}
      >
        {ctx.firstName}
      </div>

      {/* Athlete surname — large hero (kinetic-aware, fit to one line) */}
      <KineticLine
        text={ctx.surnameText}
        anim={anim}
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.51,
          fontSize: fitLinePx(ctx.surnameText, Math.round(168 * ts), width - layout.textLeft - 80),
          fontWeight: 900,
          color: roles.onGround,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          opacity: anim.heroOpacity,
          textAlign: layout.textAlign,
          transform: `translateY(${anim.heroY}px) scale(${anim.heroScale})`,
          transformOrigin: "left center",
          maxWidth: width - 160,
        }}
      />

      {/* Event line */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.65,
          fontSize: Math.round(36 * ts),
          color: roles.onGround,
          opacity: anim.secondaryOpacity * 0.85,
          letterSpacing: "0.04em",
          textAlign: layout.textAlign,
        }}
      >
        {ctx.event}
      </div>

      {/* Result value — hero metric */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.7,
          fontSize: Math.round(132 * ts),
          fontWeight: 800,
          color: roles.onGround,
          letterSpacing: "-0.01em",
          opacity: anim.resultOpacity,
          transform: `scale(${anim.resultScale})`,
          transformOrigin: "left center",
          fontVariantNumeric: "tabular-nums",
          textAlign: layout.textAlign,
        }}
      >
        {ctx.result || "—"}
      </div>

      {/* Measured emphasis line (e.g. "−0.42s on PB") — only real data. */}
      {card.heroStat ? (
        <div
          style={{
            position: "absolute",
            left: layout.textLeft,
            top: height * 0.78,
            fontSize: Math.round(40 * ts),
            fontWeight: 700,
            color: roles.onGround,
            letterSpacing: "0.08em",
            opacity: anim.resultOpacity * 0.9,
            textAlign: layout.textAlign,
            textTransform: "uppercase",
          }}
        >
          {card.heroStat}
        </div>
      ) : null}

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Poster scene — the number (or the name) IS the story, centred, minimal.
const PosterScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, ts } = ctx;
  const isQuote = card.archetype === "quote_led_recap";
  const megaIsResult = Boolean(ctx.resultFinal);
  const mega = megaIsResult ? ctx.result : ctx.surnameText;
  // Fit against the FINAL value so the size never wobbles mid-count.
  const megaSize = fitLinePx(
    megaIsResult ? ctx.resultFinal : ctx.surnameText,
    Math.round((megaIsResult ? 232 : 196) * ts),
    width - 180 * ts,
  );
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />
      <LogoChip ctx={ctx} size={120} />

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          padding: Math.round(90 * ts),
        }}
      >
        {isQuote ? (
          <div
            style={{
              fontSize: Math.round(180 * ts),
              fontWeight: 900,
              color: roles.accent,
              lineHeight: 0.4,
              opacity: anim.heroOpacity * 0.9,
            }}
          >
            “
          </div>
        ) : null}
        <div
          style={{
            fontSize: Math.round(34 * ts),
            letterSpacing: "0.22em",
            color: roles.accent,
            fontWeight: 800,
            textTransform: "uppercase",
            opacity: anim.chipOpacity,
            marginBottom: Math.round(36 * ts),
          }}
        >
          {ctx.label}
        </div>
        <KineticLine
          text={mega}
          anim={anim}
          style={{
            fontSize: megaSize,
            fontWeight: 900,
            color: roles.onGround,
            letterSpacing: "-0.02em",
            lineHeight: 0.95,
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY}px) scale(${anim.heroScale})`,
            fontVariantNumeric: "tabular-nums",
            textTransform: "uppercase",
          }}
        />
        <div
          style={{
            marginTop: Math.round(44 * ts),
            fontSize: Math.round(44 * ts),
            fontWeight: 700,
            color: roles.onGround,
            opacity: anim.secondaryOpacity,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {megaIsResult ? ctx.card.athleteFullName : ctx.event}
        </div>
        <div
          style={{
            marginTop: Math.round(16 * ts),
            fontSize: Math.round(34 * ts),
            color: roles.onGround,
            opacity: anim.secondaryOpacity * 0.8,
            letterSpacing: "0.06em",
          }}
        >
          {megaIsResult ? ctx.event : ctx.result}
        </div>
        {card.heroStat ? (
          <div
            style={{
              marginTop: Math.round(40 * ts),
              padding: `${Math.round(12 * ts)}px ${Math.round(26 * ts)}px`,
              background: roles.accent,
              color: roles.ground,
              fontSize: Math.round(34 * ts),
              fontWeight: 800,
              letterSpacing: "0.1em",
              borderRadius: 6,
              opacity: anim.resultOpacity,
              textTransform: "uppercase",
            }}
          >
            {card.heroStat}
          </div>
        ) : null}
      </div>

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Broadcast lower-third — photo-first, facts in a band along the bottom.
const LowerThirdScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, height, ts } = ctx;
  const bandH = Math.max(height * 0.26, 300 * ts);
  // The band rides the hero channel: it slides up as the intro plays.
  const bandY = anim.heroY;
  return (
    <>
      <PhotoLayer ctx={ctx} scrim="bottom" />
      <PatternLayer ctx={ctx} />
      <LogoChip ctx={ctx} size={120} />

      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: bandH,
          background: roles.surface,
          opacity: 0.94 * anim.heroOpacity,
          transform: `translateY(${bandY}px)`,
        }}
      />
      {/* Accent keyline on top of the band — the broadcast cue. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: bandH,
          height: Math.max(6, Math.round(8 * ts)),
          background: roles.accent,
          opacity: anim.heroOpacity,
          transform: `translateY(${bandY}px)`,
        }}
      />

      <div
        style={{
          position: "absolute",
          left: Math.round(80 * ts),
          right: Math.round(80 * ts),
          bottom: Math.round(60 * ts),
          height: bandH - Math.round(90 * ts),
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          transform: `translateY(${bandY}px)`,
        }}
      >
        <div
          style={{
            fontSize: Math.round(30 * ts),
            letterSpacing: "0.18em",
            color: roles.accent,
            fontWeight: 800,
            textTransform: "uppercase",
            opacity: anim.secondaryOpacity,
          }}
        >
          {ctx.label}
        </div>
        <div
          style={{
            marginTop: Math.round(10 * ts),
            fontSize: Math.round(84 * ts),
            fontWeight: 900,
            color: roles.onGround,
            lineHeight: 1.0,
            textTransform: "uppercase",
            letterSpacing: "-0.01em",
            opacity: anim.heroOpacity,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {card.athleteFullName || ctx.surnameText}
        </div>
        <div
          style={{
            marginTop: Math.round(12 * ts),
            display: "flex",
            alignItems: "baseline",
            gap: Math.round(28 * ts),
            opacity: anim.resultOpacity,
          }}
        >
          <span
            style={{
              fontSize: Math.round(34 * ts),
              color: roles.onGround,
              opacity: 0.85,
              letterSpacing: "0.04em",
            }}
          >
            {ctx.event}
          </span>
          <span
            style={{
              fontSize: Math.round(56 * ts),
              fontWeight: 800,
              color: roles.accent,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {ctx.result}
          </span>
          {card.heroStat ? (
            <span
              style={{
                fontSize: Math.round(30 * ts),
                fontWeight: 700,
                color: roles.onGround,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                opacity: 0.9,
              }}
            >
              {card.heroStat}
            </span>
          ) : null}
        </div>
      </div>

      {/* Meet + club, top-left over the photo. */}
      <div
        style={{
          position: "absolute",
          left: Math.round(80 * ts),
          top: Math.round(100 * ts),
          fontSize: Math.round(28 * ts),
          letterSpacing: "0.1em",
          color: roles.onGround,
          opacity: anim.chipOpacity * 0.9,
          textTransform: "uppercase",
          fontWeight: 700,
        }}
      >
        {ctx.meet}
      </div>
    </>
  );
};

// Medal spotlight — symmetric, ring badge, radial glow.
const SpotlightScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  const ringSize = Math.round(Math.min(width, height) * 0.34);
  const place = placeDisplay(card.place || "");
  return (
    <>
      <PhotoLayer ctx={ctx} />
      {/* Radial glow behind the badge — accent into transparent. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(circle at 50% 38%, ${roles.accent}33 0%, ${roles.ground}00 55%)`,
          opacity: anim.heroOpacity,
        }}
      />
      <PatternLayer ctx={ctx} />
      <LogoChip ctx={ctx} size={110} />

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: height * 0.16,
          textAlign: "center",
        }}
      >
        {/* Ring badge with the placing (only real data) or the label. */}
        <div
          style={{
            width: ringSize,
            height: ringSize,
            borderRadius: "50%",
            border: `${Math.max(5, Math.round(8 * ts))}px solid ${roles.accent}`,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            transform: `scale(${0.8 + 0.2 * anim.heroOpacity}) translateY(${anim.heroY * 0.4}px)`,
            opacity: anim.heroOpacity,
          }}
        >
          <div
            style={{
              fontSize: place ? ringSize * 0.34 : ringSize * 0.16,
              fontWeight: 900,
              color: roles.accent,
              lineHeight: 1,
              textTransform: "uppercase",
              padding: `0 ${Math.round(18 * ts)}px`,
            }}
          >
            {place || ctx.label}
          </div>
          {place ? (
            <div
              style={{
                marginTop: Math.round(8 * ts),
                fontSize: ringSize * 0.1,
                fontWeight: 800,
                letterSpacing: "0.2em",
                color: roles.onGround,
                textTransform: "uppercase",
              }}
            >
              {ctx.label}
            </div>
          ) : null}
        </div>

        <KineticLine
          text={ctx.surnameText}
          anim={anim}
          style={{
            marginTop: Math.round(70 * ts),
            fontSize: fitLinePx(ctx.surnameText, Math.round(140 * ts), width - 160 * ts),
            fontWeight: 900,
            color: roles.onGround,
            letterSpacing: "-0.02em",
            lineHeight: 1,
            textTransform: "uppercase",
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.5}px)`,
          }}
        />
        <div
          style={{
            marginTop: Math.round(18 * ts),
            fontSize: Math.round(40 * ts),
            color: roles.onGround,
            opacity: anim.secondaryOpacity * 0.9,
            letterSpacing: "0.05em",
          }}
        >
          {ctx.firstName}
        </div>
        <div
          style={{
            marginTop: Math.round(34 * ts),
            fontSize: Math.round(36 * ts),
            color: roles.onGround,
            opacity: anim.secondaryOpacity * 0.85,
            letterSpacing: "0.06em",
          }}
        >
          {ctx.event}
        </div>
        <div
          style={{
            marginTop: Math.round(10 * ts),
            fontSize: Math.round(76 * ts),
            fontWeight: 800,
            color: roles.accent,
            fontVariantNumeric: "tabular-nums",
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale})`,
          }}
        >
          {ctx.result}
        </div>
      </div>

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Editorial grid — the facts as staggered stat tiles.
const GridScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts, fontStack, frame, fps } = ctx;
  const tiles: { label: string; value: string; hero?: boolean }[] = [];
  if (ctx.result) tiles.push({ label: "RESULT", value: ctx.result, hero: true });
  if (ctx.event) tiles.push({ label: "EVENT", value: ctx.event });
  if (card.heroStat) tiles.push({ label: "THE MOVE", value: card.heroStat });
  if (card.place) tiles.push({ label: "PLACE", value: placeDisplay(card.place) });
  const sidebar = card.archetype === "stat_stack_sidebar";
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />
      <LabelChip ctx={ctx} />
      <LogoChip ctx={ctx} />

      {/* Header — athlete name. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.24,
          right: 80,
          fontSize: Math.round(108 * ts),
          fontWeight: 900,
          color: roles.onGround,
          lineHeight: 0.98,
          letterSpacing: "-0.02em",
          textTransform: "uppercase",
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY * 0.5}px)`,
        }}
      >
        {ctx.firstName ? `${ctx.firstName} ` : ""}
        {ctx.surnameText}
      </div>

      {/* Stat tiles — staggered in on the chip channel. */}
      <div
        style={{
          position: "absolute",
          left: sidebar ? width * 0.5 : 80,
          right: 80,
          top: height * (sidebar ? 0.42 : 0.46),
          display: "flex",
          flexDirection: "column",
          gap: Math.round(22 * ts),
        }}
      >
        {tiles.map((t, i) => {
          // Frame-based per-tile cascade; the "static" intent shows every
          // tile from frame 0 (its defining feature), all others ramp.
          const cascade = interpolate(
            frame,
            [fps * (0.5 + 0.18 * i), fps * (0.85 + 0.18 * i)],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          const stagger = card.motionIntent === "static" ? 1 : cascade;
          return (
            <div
              key={t.label}
              style={{
                background: t.hero ? roles.accent : roles.surface,
                color: t.hero ? roles.ground : roles.onGround,
                borderRadius: 10,
                padding: `${Math.round((t.hero ? 30 : 22) * ts)}px ${Math.round(34 * ts)}px`,
                opacity: stagger,
                transform: `translateY(${(1 - stagger) * 40}px)`,
              }}
            >
              <div
                style={{
                  fontSize: Math.round(26 * ts),
                  letterSpacing: "0.18em",
                  fontWeight: 800,
                  opacity: 0.75,
                  fontFamily: fontStack,
                }}
              >
                {t.label}
              </div>
              <div
                style={{
                  marginTop: Math.round(6 * ts),
                  fontSize: Math.round((t.hero ? 84 : 48) * ts),
                  fontWeight: 900,
                  fontVariantNumeric: "tabular-nums",
                  lineHeight: 1.02,
                }}
              >
                {t.value}
              </div>
            </div>
          );
        })}
      </div>

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Ticker strip — a sliding wire-service band carries the facts.
const TickerScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, height, ts, frame, fps } = ctx;
  // Honest ticker copy: only the card's real facts, repeated. The crawl
  // always carries the final verified value (a mid-count number scrolling
  // by would read as a different result).
  const bits = [ctx.label, ctx.surnameText, ctx.event, ctx.resultFinal, card.heroStat]
    .filter(Boolean)
    .join("  •  ");
  const tickerText = `${bits}  •  ${bits}  •  ${bits}`;
  // Continuous wire-service crawl — pure function of the frame.
  const crawl = (frame / fps) * 90;
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />
      <LogoChip ctx={ctx} />

      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.3,
          fontSize: Math.round(34 * ts),
          letterSpacing: "0.2em",
          color: roles.accent,
          fontWeight: 800,
          textTransform: "uppercase",
          opacity: anim.secondaryOpacity,
        }}
      >
        {ctx.meet || ctx.club}
      </div>

      <KineticLine
        text={ctx.surnameText}
        anim={anim}
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.36,
          fontSize: fitLinePx(ctx.surnameText, Math.round(150 * ts), ctx.width - 160),
          fontWeight: 900,
          color: roles.onGround,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          textTransform: "uppercase",
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY * 0.6}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.47,
          fontSize: Math.round(72 * ts),
          fontWeight: 800,
          color: roles.onGround,
          fontVariantNumeric: "tabular-nums",
          opacity: anim.resultOpacity,
          transform: `scale(${anim.resultScale})`,
          transformOrigin: "left center",
        }}
      >
        {ctx.result}
      </div>

      {/* The accent ticker band. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: height * 0.6,
          height: Math.round(96 * ts),
          background: roles.accent,
          opacity: anim.heroOpacity,
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
        }}
      >
        <div
          style={{
            whiteSpace: "nowrap",
            fontSize: Math.round(40 * ts),
            fontWeight: 800,
            letterSpacing: "0.06em",
            color: roles.ground,
            textTransform: "uppercase",
            transform: `translateX(${-crawl}px)`,
          }}
        >
          {tickerText}
        </div>
      </div>
      {/* Thin echo band below. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: height * 0.6 + Math.round(108 * ts),
          height: Math.max(4, Math.round(6 * ts)),
          background: roles.surface,
          opacity: anim.chipOpacity,
        }}
      />

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Diagonal split — wedge sweeps in, name on ground, result on the wedge.
const SplitScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  // Wedge sweeps in from the right as the hero channel settles.
  const sweep = (1 - anim.heroOpacity) * width * 0.4;
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />

      {/* Diagonal surface wedge (right side). */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: roles.surface,
          opacity: 0.92,
          clipPath: `polygon(${width * 0.62}px 0, 100% 0, 100% 100%, ${width * 0.34}px 100%)`,
          transform: `translateX(${sweep}px)`,
        }}
      />
      {/* Accent keyline along the diagonal. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: roles.accent,
          clipPath: `polygon(${width * 0.62}px 0, ${width * 0.62 + 14}px 0, ${width * 0.34 + 14}px 100%, ${width * 0.34}px 100%)`,
          transform: `translateX(${sweep}px)`,
          opacity: anim.heroOpacity,
        }}
      />

      <LabelChip ctx={ctx} />
      <LogoChip ctx={ctx} />

      {/* Name — ground side (left). */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.42,
          width: width * 0.52,
          fontSize: Math.round(54 * ts),
          fontWeight: 700,
          color: roles.onGround,
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY * 0.3}px)`,
          textTransform: "uppercase",
        }}
      >
        {ctx.firstName}
      </div>
      <KineticLine
        text={ctx.surnameText}
        anim={anim}
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.47,
          width: width * 0.6,
          fontSize: fitLinePx(ctx.surnameText, Math.round(140 * ts), width * 0.6),
          fontWeight: 900,
          color: roles.onGround,
          letterSpacing: "-0.02em",
          lineHeight: 0.98,
          textTransform: "uppercase",
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.62,
          width: width * 0.5,
          fontSize: Math.round(34 * ts),
          color: roles.onGround,
          opacity: anim.secondaryOpacity * 0.85,
          letterSpacing: "0.05em",
        }}
      >
        {ctx.event}
      </div>

      {/* Result — on the wedge (right, lower). */}
      <div
        style={{
          position: "absolute",
          right: Math.round(70 * ts),
          top: height * 0.68,
          fontSize: Math.round(108 * ts),
          fontWeight: 900,
          color: roles.onGround,
          fontVariantNumeric: "tabular-nums",
          opacity: anim.resultOpacity,
          transform: `scale(${anim.resultScale})`,
          transformOrigin: "right center",
          textAlign: "right",
        }}
      >
        {ctx.result}
      </div>
      {card.heroStat ? (
        <div
          style={{
            position: "absolute",
            right: Math.round(70 * ts),
            top: height * 0.78,
            fontSize: Math.round(36 * ts),
            fontWeight: 800,
            color: roles.accent,
            letterSpacing: "0.08em",
            opacity: anim.resultOpacity * 0.95,
            textTransform: "uppercase",
            textAlign: "right",
          }}
        >
          {card.heroStat}
        </div>
      ) : null}

      <BottomStrip ctx={ctx} />
    </>
  );
};

// Magazine cover — masthead club name, cover-line stack.
const MagazineScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  return (
    <>
      <PhotoLayer ctx={ctx} />
      <PatternLayer ctx={ctx} />

      {/* Masthead. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: Math.round(90 * ts),
          textAlign: "center",
          opacity: anim.chipOpacity,
        }}
      >
        <div style={{ height: 4, background: roles.accent, marginBottom: Math.round(18 * ts) }} />
        <div
          style={{
            fontSize: Math.round(58 * ts),
            fontWeight: 900,
            letterSpacing: "0.12em",
            color: roles.onGround,
            textTransform: "uppercase",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {ctx.club || ctx.meet || "MEET REPORT"}
        </div>
        <div style={{ height: 4, background: roles.accent, marginTop: Math.round(18 * ts) }} />
      </div>

      {/* Issue chip — the achievement label. */}
      <div
        style={{
          position: "absolute",
          right: 80,
          top: Math.round(230 * ts),
          padding: `${Math.round(10 * ts)}px ${Math.round(20 * ts)}px`,
          background: roles.accent,
          color: roles.ground,
          fontSize: Math.round(28 * ts),
          fontWeight: 800,
          letterSpacing: "0.12em",
          opacity: anim.chipOpacity,
          borderRadius: 4,
          textTransform: "uppercase",
        }}
      >
        {ctx.label}
      </div>

      {/* Cover star. */}
      <KineticLine
        text={ctx.surnameText}
        anim={anim}
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.5,
          fontSize: fitLinePx(ctx.surnameText, Math.round(172 * ts), width - 160),
          fontWeight: 900,
          color: roles.onGround,
          letterSpacing: "-0.02em",
          lineHeight: 0.95,
          textTransform: "uppercase",
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY}px)`,
          maxWidth: width - 160,
        }}
      />

      {/* Cover lines. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.66,
          display: "flex",
          flexDirection: "column",
          gap: Math.round(14 * ts),
        }}
      >
        {[
          ctx.firstName && `${ctx.firstName} ${ctx.surnameText}`.trim(),
          ctx.event && ctx.result ? `${ctx.event} — ${ctx.result}` : ctx.event || ctx.result,
          card.heroStat,
        ]
          .filter(Boolean)
          .map((line, i) => (
            <div
              key={i}
              style={{
                fontSize: Math.round((i === 1 ? 52 : 36) * ts),
                fontWeight: i === 1 ? 800 : 600,
                color: i === 1 ? roles.accent : roles.onGround,
                opacity: anim.secondaryOpacity,
                letterSpacing: "0.03em",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {line}
            </div>
          ))}
      </div>

      <BottomStrip ctx={ctx} />
    </>
  );
};

const SCENES: Record<SceneMode, React.FC<{ ctx: SceneCtx }>> = {
  hero: HeroScene,
  poster: PosterScene,
  lowerThird: LowerThirdScene,
  spotlight: SpotlightScene,
  grid: GridScene,
  ticker: TickerScene,
  split: SplitScene,
  magazine: MagazineScene,
};

export const StoryCard: React.FC<Props> = ({ card, brand }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const roles = resolveRoles(card, brand);
  const fontStack = fontStackFor(card.typographyPair || "");
  const anim = animProgram(
    card.motionIntent || "",
    card.mood || "",
    frame,
    fps,
    durationInFrames,
  );
  const mode = sceneForArchetype(card.archetype || "");
  const layout = compositionLayoutFor(card.composition || "left", width);

  // Type scale: 1.0 on the 1080×1920 design canvas; square and landscape
  // cuts shrink type proportionally so the stack still breathes.
  const ts = Math.min(width / 1080, height / 1440, 1);

  // Outro: fade to black on last 0.4s
  const outroFade = interpolate(
    frame,
    [durationInFrames - fps * 0.4, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const ctx: SceneCtx = {
    card,
    brand,
    roles,
    anim,
    fontStack,
    frame,
    fps,
    width,
    height,
    ts,
    layout,
    surnameText: (card.athleteSurname || card.athleteFullName || "")
      .toUpperCase()
      .slice(0, 12),
    firstName: (card.athleteFirstName || "").toUpperCase(),
    label: (card.achievementLabel || "").toUpperCase(),
    event: card.eventName || "",
    result: countUpDisplay(card.resultValue || "", anim.resultProgress),
    resultFinal: card.resultValue || "",
    meet: card.meetName || "",
    club: (brand.displayName || brand.shortName || "").toUpperCase(),
  };

  // A sprint scene (R1.2) registered for this exact archetype replaces the
  // built-in scene; otherwise the parity-mapped built-in scene renders.
  const Scene = EXTRA_SCENES[card.archetype || ""] || SCENES[mode];

  return (
    <AbsoluteFill
      style={{
        backgroundColor: roles.ground,
        fontFamily: fontStack,
        opacity: outroFade,
      }}
    >
      <Scene ctx={ctx} />
      <StylePackLayer ctx={ctx} />
      {/* Sprint overlay layers (R1.6/8/9/10/11/22/23/24/25) — additive, in order. */}
      {EXTRA_LAYERS.map(({ Layer }, i) => (
        <Layer key={`sprint-layer-${i}`} ctx={ctx} />
      ))}
    </AbsoluteFill>
  );
};
