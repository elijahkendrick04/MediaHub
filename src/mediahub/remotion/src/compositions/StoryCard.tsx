import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
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
import { resolveStagger, type StaggerConfig } from "../motion/compile";
import {
  PhotoFilterDefs,
  photoGradeFilterFor,
  photoHalftoneMaskFor,
} from "./sprint/layers/photo_filters";
import { StatChipsBlock } from "./sprint/sceneKit";

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
  // Entrance-stagger scale (0 = unset → the fixed default delays). >1 loosens
  // the importance separation, <1 tightens it; only the token-compiled entrance
  // intents (drop_in / rise / pop) consume it.
  staggerScale: z.number().default(0),
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
  // M23 footage beat: a normalised, MUTED, keyframe-clean trim of the club's
  // real race clip, staticFile-served from remotion/public/footage_cache/
  // (deterministically chosen + trimmed by visual/footage.py — selector
  // scoring + moment detection, never AI). When set, the photo layer plays
  // it under the EXACT same scrim/filter/treatment stack the photograph
  // uses; empty keeps the photo path byte-identical. The clip has real
  // motion, so the seed-chosen camera channels do not apply to it.
  videoSrc: z.string().default(""),
  videoStartSec: z.number().default(0),
  videoDurationSec: z.number().default(0),
  // M20: additional photos for multi-athlete archetypes (relay_collage /
  // duo_athlete_split / triptych_progression), one JPEG data URI per linked
  // relay athlete resolved by the deterministic media-library selector.
  // Empty = the single-photo behaviour, byte-identical to before.
  photoSrcs: z.array(z.string()).default([]),
  // R1.9: the athlete cut out from their photo (background removed to alpha),
  // inlined by motion.py as a PNG data URI. The cutout sprint layer
  // (sprint/layers/cutout.tsx) composites this as a parallax FOREGROUND plane
  // over the scrimmed full-bleed background photo, giving the card real depth.
  // Empty = no prepared cutout (no sourced photo, no background remover,
  // matte-gate rejection, or a "photo"-mode archetype) — the consumers no-op,
  // byte-identical to the pre-R1.9 render.
  cutoutSrc: z.string().default(""),
  // STILLS-2 / M8 parity: how this card's archetype consumes the athlete
  // photo. "photo" = the still shows the ORIGINAL photograph (rectangular
  // window / full-bleed stage) — the cutout plane must not composite. "" (and
  // "cutout") keep the legacy R1.9 behaviour. Set by motion.py only when it
  // resolved AND the card carries a photo, so cache keys stay stable.
  photoMode: z.string().default(""),
  // M10 crop-intent mirror: the still's --mh-photo-scale zoom (tight_portrait
  // — alpha-bbox-derived, 1.06–1.30). Applied as a static wrapper scale with
  // transform-origin at the saliency focus, multiplying into the cinematic
  // push-in. 0 = no crop zoom (byte-identical).
  photoScale: z.number().default(0),
  // M12 layered-depth twins: the brief's decoration_strength for the
  // role-coloured cutout depth filter. Only attached when non-default, so the
  // schema default mirrors the still's 0.5 fallback.
  decorationStrength: z.number().default(0.5),
  // M10 true brand duotone — the exact ink hexes the still's SVG filter ramps
  // between (shadow = render.darken(--mh-primary, 0.30), highlight = the
  // resolved --mh-accent, medal tints included), computed Python-side by the
  // same maths so the two surfaces can never drift. Empty = no duotone.
  duotoneShadow: z.string().default(""),
  duotoneHighlight: z.string().default(""),
  // M10 real halftone — the mask tile px (round(14 + 18·decoration_strength),
  // the still's _v2_photo_treatment_assets). 0 = no halftone.
  halftoneTile: z.number().default(0),
  // B5 die-cut sticker contour — the resolved on-ground ink hex + the radius px
  // the still computed (render._sticker_outline_css: round(min(w,h)·(0.003 +
  // 0.004·decoration_strength))), so the cutout's 8-direction outline is byte-
  // identical to the still's `img.athlete-cutout { filter }`. Empty/0 = no
  // sticker (the cutout keeps its grounded depth shadow, byte-identical).
  stickerInk: z.string().default(""),
  stickerRadius: z.number().default(0),
  // C5 brand colour-wash — the deep brand tint (render.darken(--mh-primary,
  // 0.20)) + the arithmetic mix fraction (0.18 + 0.24·decoration_strength) the
  // still's _wash_defs_svg composites, so photo_filters rebuilds the identical
  // SVG wash. Empty/0 = the approximate saturate grade (or no grade), which
  // keeps v1 briefs byte-identical.
  washTint: z.string().default(""),
  washMix: z.number().default(0),
  // E6 style-pack ground focus — the resolved saliency focus [fx, fy] in
  // percent, recentring the vignette/spotlight ground ellipse on the subject.
  // null (photo-less cards / non-subject grounds) keeps the fixed centre,
  // byte-identical to the pre-E6 render.
  packGroundFocus: z.array(z.number()).nullable().default(null),
  // M11 data weight — the still's secondary-stat chip row (label/value pairs
  // already selected + trimmed by the still's own tables) and the honest
  // proportional PB bars, with the exact ink hex the still's bay uses.
  // Empty/null = the slots collapse (byte-identical undirected cards).
  statChips: z.array(z.object({ label: z.string(), value: z.string() })).default([]),
  statInk: z.string().default(""),
  pbBars: z
    .object({
      prev: z.string(),
      now: z.string(),
      nowPct: z.number(),
      caption: z.string(),
    })
    .nullable()
    .default(null),
  // M12 band_break placement — computed Python-side from the still's maths
  // (render._band_top_fraction + the stage-relative overlap fade stops) so
  // both surfaces break the band at identical pixels. Defaults mirror the
  // still template's CSS fallbacks (62% / 58% / 66%).
  bandTopPct: z.number().default(62),
  breakSolidPct: z.number().default(58),
  breakFadePct: z.number().default(66),
  // The resolved --mh-on-surface ink for archetypes whose band sits on the
  // surface role (poster_name_behind). "" = fall back to roleOnGround.
  roleOnSurface: z.string().default(""),
  // The still's resolved --mh-outline hairline (a translucent on-colour),
  // passed whenever a consumer renders it (stat chips, band_break's band
  // underline) so no colour literal ever lives in the TSX.
  roleOutline: z.string().default(""),
  // M16: true when this card renders as a beat INSIDE a meet reel. The reel
  // sets it in the TSX itself (never from Python, so cache keys are
  // untouched); it suppresses the story's closing self-fade because in a reel
  // the outgoing transition IS the exit — no more dips through black mid-reel.
  inReel: z.boolean().default(false),
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
  // F7 overlap accent (still parity): "shape:rotation" (e.g. "tab:-4"), the
  // seeded badge/tab/rule/tape the still straddles across a declared anchor.
  // The motion pack layer paints the same shape at a fixed overlap-safe corner.
  // Empty = no overlap accent (bare/legacy card), byte-equivalent.
  overlapAccent: z.string().default(""),
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
  // F9 medal chrome (still parity): the resolved specular ramp CSS
  // (linear-gradient(...)). roleMedalRamp fills the bevelled result chip;
  // roleMedalNumeralRamp is the gate-passing twin that gradient-clips the mega
  // result numeral (emitted only when the ramp's darkest stop clears APCA vs
  // the ground). Empty = no chrome (non-medal / dark-ground numeral), byte-equiv.
  roleMedalRamp: z.string().default(""),
  roleMedalNumeralRamp: z.string().default(""),
  // Subtitle/caption burn-in track (R1.3): a JSON string of the APCA-gated,
  // frame-timed caption cues built by visual/subtitle_burn.py and painted by
  // sprint/layers/captions.tsx. Empty = no captions (byte-identical render).
  captionsJson: z.string().default(""),
  // G1.8 mesh-ground parity: the still's deterministic brand-role gradient
  // mesh as a CSS background-image value (url("data:image/svg+xml;base64,…")),
  // built by the SAME Python engine the still hook runs
  // (graphic_renderer.gradient_mesh via motion._mesh_bg_for_brief) — so the
  // video ground is the mesh the approved still painted, not a re-derivation.
  // Painted on the composition root beneath every content layer, exactly the
  // still's ground override. Empty = the flat roles.ground (byte-identical).
  meshBg: z.string().default(""),
  // D8 (Canva gap analysis): the still's density/mood-coherent supporting weight
  // register (kicker/meta/data over the shipped variable axes), mirrored from
  // render.py so the reel's labels/meta/data carry the same weights the still
  // painted. 0 = the still did not spend the register (standard density + neutral
  // mood), so the scene keeps its static fontWeight and stays byte-identical.
  wghtKicker: z.number().default(0),
  wghtMeta: z.number().default(0),
  wghtData: z.number().default(0),
  // E4 (Canva gap analysis): the still's shaped photo frame on the three
  // windowed archetypes (photo_passepartout / spotlight_disc /
  // full_height_portrait_split). "" / "rect" keeps the plain window (byte-
  // identical). "arch"/"blob" carry the exact border-radius the still computed
  // (frameRadius); "torn_edge" carries the three feTurbulence/feDisplacementMap
  // numbers so the motion filter tears along the same seeded field. The scenes
  // apply the shape to their framed element + a static offset accent echo — the
  // still's geometry mirrored one-to-one.
  frameShape: z.string().default(""),
  frameRadius: z.string().default(""),
  frameTornFreq: z.number().default(0),
  frameTornScale: z.number().default(0),
  frameTornSeed: z.number().default(0),
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

// D8 (Canva gap analysis) — fontVariationSettings for a supporting-register
// weight (kicker/meta/data) mirrored from the still's --mh-wght-* vars. A 0 (the
// still did not spend the register) omits the setting, so the scene keeps its
// static fontWeight and renders byte-identically to the pre-D8 reel.
function wghtFvs(weight: number | undefined): React.CSSProperties {
  return weight && weight > 0 ? { fontVariationSettings: `'wght' ${Math.round(weight)}` } : {};
}

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
// D5 parity contract: the display face per pairing mirrors the still side's
// curated table (graphic_renderer/type_pairs.py PAIRINGS), pinned by
// tests/test_typography_pairings.py — a new pairing lands on both surfaces.
// Exported for MeetReel (M18): the reel cover follows the top card's pair.
export function fontStackFor(pair: string): string {
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
    case "grotesk-mono":
      return "'Space Grotesk', 'Archivo', 'Inter', 'Helvetica Neue', Arial, sans-serif";
    case "playfair-editorial":
    case "playfair-mono":
      // The serif display register (D5) — self-hosted Playfair Display.
      return "'Playfair Display', Georgia, 'Times New Roman', serif";
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
  // M15 — the photo camera. Every intent gives the photo layer a slow,
  // seed-chosen camera move (push-in / push-out / lateral drift); `static`
  // stays genuinely still and `parallax` keeps its stronger dual-rate zoom.
  photoScale: number; // slow photo push (≤1.06 so saliency framing holds)
  photoDriftX: number; // lateral drift in % of the photo's own box (≤2%)
  photoDriftY: number; // vertical drift in % of the photo's own box (≤2%)
  // M19 — shared resolve-phase micro-accent: a 0→1→0 pulse at ~70% of the
  // beat, seed/mood-keyed to one of three expressions so sibling cards differ.
  resolveAccent: number;
  resolveAccentKind: "stat" | "underline" | "label" | "none";
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

// M15 — the default cinematic photo camera. Every intent gives the full-bleed
// photo a slow, seed-chosen camera move so club photos never sit frozen:
// push-in, push-out, or a lateral drift left/right (variationSeed % 4). Scale
// stays ≤1.06 and lateral travel ≤2% of the photo's own box so the saliency
// framing (photoPos) always holds. Frame-pure interpolate over the whole clip
// with a sine in-out (motion-language.md's Ken Burns ease). `static` is
// genuinely still; `parallax` keeps its stronger dual-rate treatment (applied
// in its own branch below).
function photoCameraFor(
  intent: string,
  seed: number,
  frame: number,
  durationInFrames: number,
): { photoScale: number; photoDriftX: number; photoDriftY: number } {
  if (intent === "static") {
    return { photoScale: 1, photoDriftX: 0, photoDriftY: 0 };
  }
  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.sin),
  });
  const mode = (((seed | 0) % 4) + 4) % 4;
  if (mode === 1) {
    // Push-out: opens tight, settles into the composed frame.
    return { photoScale: 1.06 - 0.06 * t, photoDriftX: 0, photoDriftY: 0 };
  }
  if (mode === 2) {
    // Lateral drift left, with a whisper of push so the move never reads flat.
    return { photoScale: 1.035 + 0.015 * t, photoDriftX: 1.5 - 3.0 * t, photoDriftY: 0 };
  }
  if (mode === 3) {
    // Lateral drift right.
    return { photoScale: 1.035 + 0.015 * t, photoDriftX: -1.5 + 3.0 * t, photoDriftY: 0 };
  }
  // Push-in — the classic slow Ken Burns toward the saliency focus.
  return { photoScale: 1 + 0.06 * t, photoDriftX: 0, photoDriftY: 0 };
}

function animProgram(
  intent: string,
  mood: string,
  frame: number,
  fps: number,
  durationInFrames: number,
  seed: number,
  stagger?: StaggerConfig,
): AnimChannels {
  const moodSpring = springConfigFor(mood);
  const clampRight = { extrapolateRight: "clamp" as const };
  // Identity word reveal: the parent line owns motion + opacity, so a word
  // contributes nothing extra (no double-applied fades).
  const identityWord = () => ({ y: 0, opacity: 1 });

  // M19 — beat-proportional choreography. Keyframes are FRACTIONS of the
  // clip so a 4s reel beat and a 6s story distribute the same build →
  // breathe → resolve rhythm proportionally (build lands by ~30%) instead of
  // front-loading everything into an absolute 1.5s. The +3 keeps the first
  // animation off frame 0 (a t=0 entrance reads as a jump cut) while staying
  // strictly monotonic for any clip length.
  const at = (f: number) => 3 + (durationInFrames - 3) * f;

  // M19 — the shared resolve-phase micro-accent: a 0→1→0 pulse at ~70% of
  // the beat, seed-picked among three expressions (hero-stat/result pulse,
  // accent underline draw, label chip re-pulse) so sibling cards differ, and
  // mood-scaled so a calm club gets a quieter accent than a celebration.
  const m = (mood || "").toLowerCase();
  const accentAmp = /(calm|stoic|precise|minimal|composed|weighty)/.test(m)
    ? 0.6
    : /(electric|explosive|fierce|celebratory|triumph)/.test(m)
      ? 1.0
      : 0.8;
  const resolvePulse =
    interpolate(
      frame,
      [durationInFrames * 0.68, durationInFrames * 0.74, durationInFrames * 0.84],
      [0, 1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.sin) },
    ) * accentAmp;
  const accentKinds = ["stat", "underline", "label"] as const;
  const resolveAccentKind: AnimChannels["resolveAccentKind"] =
    intent === "static" ? "none" : accentKinds[(((seed | 0) % 3) + 3) % 3];

  const camera = photoCameraFor(intent, seed, frame, durationInFrames);

  // Shared default ramps (the original programme, proportionally timed).
  const defaultSpring = spring({ frame, fps, config: moodSpring });
  const base: AnimChannels = {
    heroY: interpolate(defaultSpring, [0, 1], [120, 0]),
    heroOpacity: interpolate(frame, [at(0.0), at(0.07)], [0, 1], clampRight),
    heroScale: 1,
    secondaryOpacity: interpolate(frame, [at(0.0), at(0.07)], [0, 1], clampRight),
    resultOpacity: interpolate(frame, [at(0.1), at(0.185)], [0, 1], clampRight),
    resultScale: interpolate(frame, [at(0.1), at(0.235)], [0.92, 1.0], clampRight),
    chipOpacity: interpolate(frame, [at(0.17), at(0.26)], [0, 1], clampRight),
    bgDrift: 0,
    photoScale: camera.photoScale,
    photoDriftX: camera.photoDriftX,
    photoDriftY: camera.photoDriftY,
    resolveAccent: resolvePulse,
    resolveAccentKind,
    resultProgress: 1,
    wordAt: identityWord,
  };

  // Kind-specific execution of the resolve accent that lives in the shared
  // channels: the "stat" expression re-pulses the result/hero-stat scale with
  // the same confirmation curve count_up uses. Applied on the way out so
  // every intent (including sprint ones that spread ...base) shares it.
  const withResolveAccent = (ch: AnimChannels): AnimChannels =>
    ch.resolveAccentKind === "stat"
      ? { ...ch, resultScale: ch.resultScale * (1 + 0.04 * ch.resolveAccent) }
      : ch;

  switch (intent) {
    case "fade_in": {
      return withResolveAccent({
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [at(0.0), at(0.115)], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [at(0.05), at(0.165)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.1), at(0.215)], [0, 1], clampRight),
        resultScale: 1,
        chipOpacity: interpolate(frame, [at(0.15), at(0.265)], [0, 1], clampRight),
      });
    }
    case "snap_in_then_settle": {
      // Deliberately overshooting spring — the snap IS the language; the
      // mood only flavours the settle.
      const snap = spring({
        frame,
        fps,
        config: { damping: 9, stiffness: 220, mass: 0.5 },
      });
      return withResolveAccent({
        ...base,
        heroY: interpolate(snap, [0, 1], [90, 0]),
        heroOpacity: interpolate(frame, [at(0.0), at(0.035)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.06), at(0.115)], [0, 1], clampRight),
        resultScale: interpolate(snap, [0, 1], [1.06, 1.0]),
        chipOpacity: interpolate(frame, [at(0.1), at(0.165)], [0, 1], clampRight),
      });
    }
    case "slide_up": {
      const eased = interpolate(frame, [at(0.0), at(0.135)], [1, 0], {
        ...clampRight,
        easing: Easing.out(Easing.cubic),
      });
      return withResolveAccent({
        ...base,
        heroY: eased * 240,
        heroOpacity: interpolate(frame, [at(0.0), at(0.085)], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [at(0.065), at(0.15)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.115), at(0.2)], [0, 1], clampRight),
        chipOpacity: interpolate(frame, [at(0.17), at(0.25)], [0, 1], clampRight),
      });
    }
    case "scale_in": {
      const grow = spring({ frame, fps, config: moodSpring });
      return withResolveAccent({
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [at(0.0), at(0.07)], [0, 1], clampRight),
        heroScale: interpolate(grow, [0, 1], [0.82, 1.0]),
        resultOpacity: interpolate(frame, [at(0.085), at(0.165)], [0, 1], clampRight),
        resultScale: interpolate(grow, [0, 1], [0.82, 1.0]),
        chipOpacity: interpolate(frame, [at(0.15), at(0.235)], [0, 1], clampRight),
      });
    }
    case "crossfade": {
      // Layered opacity beats, no movement: hero → secondary → result → chrome.
      return withResolveAccent({
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [at(0.0), at(0.085)], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [at(0.075), at(0.16)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.15), at(0.235)], [0, 1], clampRight),
        resultScale: 1,
        chipOpacity: interpolate(frame, [at(0.225), at(0.31)], [0, 1], clampRight),
      });
    }
    case "kinetic_type": {
      // Per-word staggered reveal — the type itself carries the energy.
      // The hero line's block opacity is 1; each word owns its reveal.
      return withResolveAccent({
        ...base,
        heroY: 0,
        heroOpacity: 1,
        secondaryOpacity: interpolate(frame, [at(0.1), at(0.165)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.135), at(0.2)], [0, 1], clampRight),
        chipOpacity: interpolate(frame, [at(0.185), at(0.265)], [0, 1], clampRight),
        wordAt: (i: number) => {
          // Word stagger stays tempo-based (it is rhythm, not build phase);
          // the whole sequence remains under ~15 frames for short lines.
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
      });
    }
    case "parallax": {
      // The surfaces drift at different rates across the WHOLE clip — the
      // photo keeps its stronger dual-rate push (no extra lateral drift on
      // top; the depth split IS this intent's camera language).
      const drift = interpolate(frame, [0, durationInFrames], [0, 60]);
      return withResolveAccent({
        ...base,
        bgDrift: drift,
        photoScale: interpolate(frame, [0, durationInFrames], [1.0, 1.07]),
        photoDriftX: 0,
        photoDriftY: 0,
      });
    }
    case "count_up": {
      // The number IS the animation: the result ticks up from zero and
      // settles — with a small confirmation pulse — on the exact verified
      // value, which then holds for the rest of the clip. A calm fade
      // programme carries the layers around it.
      return withResolveAccent({
        ...base,
        heroY: 0,
        heroOpacity: interpolate(frame, [at(0.0), at(0.085)], [0, 1], clampRight),
        secondaryOpacity: interpolate(frame, [at(0.04), at(0.135)], [0, 1], clampRight),
        resultOpacity: interpolate(frame, [at(0.025), at(0.075)], [0, 1], clampRight),
        resultScale: interpolate(
          frame,
          [at(0.26), at(0.295), at(0.33)],
          [1.0, 1.05, 1.0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        ),
        chipOpacity: interpolate(frame, [at(0.15), at(0.235)], [0, 1], clampRight),
        resultProgress: interpolate(frame, [at(0.05), at(0.27)], [0, 1], {
          ...clampRight,
          easing: Easing.out(Easing.cubic),
        }),
      });
    }
    case "static": {
      // Everything present from frame 0 — the card IS the statement. The
      // photo is genuinely still too (stillness as a choice), and no resolve
      // accent fires.
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
        photoDriftX: 0,
        photoDriftY: 0,
        resolveAccent: 0,
        resolveAccentKind: "none",
        resultProgress: 1,
        wordAt: identityWord,
      };
    }
    default: {
      // Sprint intents (R1.1) register their own file under sprint/intents/.
      // They spread ...base, so the M15 photo camera and M19 resolve accent
      // ride along unless a sprint intent deliberately overrides them.
      const extra = EXTRA_INTENTS[intent];
      return withResolveAccent(
        extra ? extra(frame, fps, durationInFrames, mood, base, stagger) : base,
      );
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
    case "poster_spine":
      return "poster";
    case "full_bleed_photo_lower_third":
    case "broadcast_scorebug":
      return "lowerThird";
    case "centered_medal_spotlight":
    case "photo_passepartout":
    case "spotlight_disc":
    case "frame_breakout":
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

// A5 (Canva gap analysis) parity — kern the result numeral's intra-numeric
// separators exactly as the still's render._kern_numeric_seps / _SEP_CSS do:
// every "." / ":" that sits BETWEEN two digits (the same `(?<=\d)[.:](?=\d)`
// contract) is wrapped in a cell carrying margin:0 -0.10em, so the motion
// result numeral holds the identical tightened spacing the approved still
// painted. Digit runs stay bare text between the separator cells. Returns the
// plain string node when nothing was wrapped (a value with no such separator,
// or a non-numeric "DQ"/"—") so those renders are byte-identical to the
// un-kerned output. Pure — no frame/random input; countUpDisplay feeds a fresh
// string each frame and the kerning re-derives identically, so both the mid-
// count frames and the HELD frame carry the same spacing as the still.
function kernNumeric(text: string): React.ReactNode {
  const t = text || "";
  if (t.length < 3 || (t.indexOf(".") < 0 && t.indexOf(":") < 0)) {
    return t;
  }
  const isDigit = (c: string): boolean => c >= "0" && c <= "9";
  const nodes: React.ReactNode[] = [];
  let buf = "";
  let wrapped = 0;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    const isSep =
      (c === "." || c === ":") &&
      i > 0 &&
      isDigit(t[i - 1]) &&
      i + 1 < t.length &&
      isDigit(t[i + 1]);
    if (isSep) {
      if (buf) {
        nodes.push(buf);
        buf = "";
      }
      nodes.push(
        <span key={`sep-${i}`} className="mh-sep" style={{ margin: "0 -0.10em" }}>
          {c}
        </span>,
      );
      wrapped += 1;
    } else {
      buf += c;
    }
  }
  if (!wrapped) {
    return t;
  }
  if (buf) {
    nodes.push(buf);
  }
  return <>{nodes}</>;
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
            {kernNumeric(w)}
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
  const { card, roles, anim, frame, fps } = ctx;
  if (!card.photoSrc && !card.videoSrc) {
    return null;
  }
  // R1.10 photo grade (duotone/halftone/vignette) — photo-element-only, the
  // still's `_photo_treatment_css` scope. "" (no grade) leaves the style
  // byte-identical. The exact M10 mirrors (duotone SVG filter / halftone
  // mask) take over when motion.py passed their parameters.
  const grade = photoGradeFilterFor(card, frame, fps);
  const mask = photoHalftoneMaskFor(card);
  // M10 crop-intent mirror: the still's --mh-photo-scale zoom, applied on a
  // static wrapper (transform-origin = the saliency focus) so it multiplies
  // into the cinematic push-in without fighting the img's camera transform.
  const cropScale = card.photoScale && card.photoScale > 1 ? card.photoScale : 1;
  // M23 — footage beat: the club's real race clip plays as the moving
  // background under the EXACT scrim/filter/treatment stack the photograph
  // uses (duotone/halftone/grade apply identically). MUTED by construction
  // (the trim is audio-stripped server-side; muted here is belt-and-braces),
  // frame-pure (OffthreadVideo frames are a pure function of the frame), and
  // deliberately camera-stable: real motion needs no synthetic push/drift.
  const startFromFrame = Math.max(0, Math.round((card.videoStartSec || 0) * fps));
  const endAtFrame =
    card.videoDurationSec && card.videoDurationSec > 0
      ? Math.max(startFromFrame + 1, Math.round(((card.videoStartSec || 0) + card.videoDurationSec) * fps))
      : undefined;
  const img = card.videoSrc ? (
    <OffthreadVideo
      muted
      src={staticFile(card.videoSrc)}
      startFrom={startFromFrame}
      endAt={endAtFrame}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        objectPosition: card.photoPos || "center 28%",
        ...(grade ? { filter: grade } : {}),
        ...(mask ?? {}),
      }}
    />
  ) : (
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
        // M15 — the seed-chosen camera move: slow push plus (for the drift
        // variants) a lateral travel in % of the photo's own box, small
        // enough that the saliency framing always holds.
        transform: `translate(${anim.photoDriftX}%, ${anim.photoDriftY}%) scale(${anim.photoScale})`,
        ...(grade ? { filter: grade } : {}),
        ...(mask ?? {}),
      }}
    />
  );
  return (
    <>
      <PhotoFilterDefs card={card} />
      {cropScale > 1 && !card.videoSrc ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            transform: `scale(${cropScale})`,
            transformOrigin: card.photoPos || "center 28%",
          }}
        >
          {img}
        </div>
      ) : (
        img
      )}
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
  // motion-craft: a uniform repeating tile (edge-to-edge dots/grid) reads as
  // cheap — the eye locks onto the regular grid instantly. Keep the tile
  // (deterministic, brand-accent texture) but break its uniformity with a
  // seeded radial mask so the texture pools off-centre and fades out to clean
  // ground, reading as ambient depth rather than signage. Frame-pure: the
  // focal point derives only from variationSeed.
  const seed = ctx.card.variationSeed || 0;
  const cx = 20 + (seed % 5) * 15; // 20..80%
  const cy = 24 + ((seed >> 3) % 4) * 16; // 24..72%
  const mask = `radial-gradient(125% 125% at ${cx}% ${cy}%, #000 0%, #000 32%, transparent 76%)`;
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
        WebkitMaskImage: mask,
        maskImage: mask,
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
  // F8 large motifs (mirror style_packs.ACCENT_GEOS).
  "speed_band", "corner_burst", "blob", "variable_halftone",
  // D7 broadcast-angled slab.
  "skew_slab",
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

function packGroundGradient(
  ground: string,
  a: number,
  focus: readonly number[] | null = null,
): string | null {
  // E6 — the two subject-framing grounds recentre their ellipse on the
  // saliency focus [fx, fy] when the card carries a photo; null keeps the
  // historic fixed centre (byte-identical), mirroring style_packs._ground_layer.
  const hasFocus = Array.isArray(focus) && focus.length === 2;
  switch (ground) {
    case "vignette": {
      const fx = hasFocus ? focus[0] : 50;
      const fy = hasFocus ? focus[1] : 45;
      return `radial-gradient(115% 95% at ${fx}% ${fy}%, rgba(0,0,0,0) 52%, rgba(0,0,0,${a}) 100%)`;
    }
    case "spotlight": {
      const fx = hasFocus ? focus[0] : 50;
      const fy = hasFocus ? focus[1] : 38;
      return `radial-gradient(60% 50% at ${fx}% ${fy}%, rgba(0,0,0,0) 0%, rgba(0,0,0,${a}) 100%)`;
    }
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
// WCAG relative luminance — mirrors render._rel_luminance for the C3
// secondary-vis guard, so still and motion agree on when the second brand
// colour is visible enough to paint.
function relLuminance(hex: string): number {
  const h = (hex || "").trim().replace(/^#/, "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    return 0;
  }
  const chan = (c: number): number => {
    const x = c / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  };
  return (
    0.2126 * chan(parseInt(full.slice(0, 2), 16)) +
    0.7152 * chan(parseInt(full.slice(2, 4), 16)) +
    0.0722 * chan(parseInt(full.slice(4, 6), 16))
  );
}

// C3 parity: the still's --mh-secondary-vis — the brand secondary when it has
// real luminance separation from the ground, else the accent (mono-accent
// ornament for single-colour kits). Same 0.12 threshold as the Python side.
function secondaryVisFor(brand: BrandProps, ground: string, accent: string): string {
  const sec = brand.secondary || "";
  if (sec && Math.abs(relLuminance(sec) - relLuminance(ground)) >= 0.12) {
    return sec;
  }
  return accent;
}

function packAccentGeometry(
  style: string, width: number, height: number, bold: boolean, accent: string,
  secondaryVis?: string,
): React.ReactNode {
  const sec = secondaryVis || accent;
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
          <div style={{ position: "absolute", left: inset, right: inset, bottom: bottom + gap, height: bh, background: sec, opacity: 0.55 }} />
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
            <span key={i} style={{ width: d, height: d, borderRadius: "50%", background: i % 2 === 0 ? accent : sec, display: "inline-block" }} />
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
    // --- F8 large-motif class (mirrors style_packs._accent_geometry_html) --
    // Painted at z-index 4 (behind content) at capped alpha — background energy,
    // not a margin mark. Fixed (unseeded) geometry so still and motion match.
    case "speed_band": {
      const op = bold ? 0.28 : 0.2;
      const bar = Math.max(4, Math.round(m * 0.01 * mult));
      const gap = bar * 3;
      const bandH = Math.round(height * 0.34);
      const taper = "linear-gradient(0deg, black 0%, transparent 100%)";
      return (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: bandH, zIndex: 4, opacity: op, background: `repeating-linear-gradient(115deg, ${accent} 0 ${bar}px, transparent ${bar}px ${bar + gap}px)`, WebkitMaskImage: taper, maskImage: taper }} />
      );
    }
    case "corner_burst": {
      const op = bold ? 0.26 : 0.18;
      const size = Math.round(m * 0.62);
      const spoke = bold ? 4 : 3;
      const fade = "radial-gradient(100% 100% at 100% 0%, black 0%, transparent 72%)";
      return (
        <div style={{ position: "absolute", right: 0, top: 0, width: size, height: size, zIndex: 4, opacity: op, background: `repeating-conic-gradient(from 198deg at 100% 0%, ${accent} 0deg ${spoke}deg, transparent ${spoke}deg 12deg)`, WebkitMaskImage: fade, maskImage: fade }} />
      );
    }
    case "blob": {
      const op = bold ? 0.22 : 0.16;
      const size = Math.round(m * 0.44 * mult);
      const off = Math.round(m * 0.03);
      const d = "M50 6 C70 6 86 16 90 36 C94 56 84 76 66 88 C48 100 26 96 14 80 C2 64 6 40 20 24 C30 12 40 6 50 6 Z";
      return (
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", left: off, bottom: off, width: size, height: size, zIndex: 4, opacity: op }}>
          <path d={d} style={{ fill: accent }} />
        </svg>
      );
    }
    case "variable_halftone": {
      const op = bold ? 0.3 : 0.22;
      const size = Math.round(m * 0.52);
      return (
        <div style={{ position: "absolute", right: 0, bottom: 0, width: size, height: size, zIndex: 4, opacity: op }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%", display: "block" }}>
            {packHalftoneDots(accent, sec)}
          </svg>
        </div>
      );
    }
    case "skew_slab": {
      const op = bold ? 0.9 : 0.72;
      const slabH = Math.round(height * 0.13 * mult);
      const bottom = Math.round(height * 0.15);
      return (
        <div style={{ position: "absolute", left: "-8%", right: "-8%", bottom, height: slabH, zIndex: 4, opacity: op, background: accent, transform: "skewX(-12deg)" }} />
      );
    }
    default:
      return null;
  }
}

// F8 variable-halftone lattice — mirrors style_packs._variable_halftone_svg so
// the still and the video draw the same fading dot wedge (fixed grid + maths).
function packHalftoneDots(accent: string, sec: string): React.ReactNode[] {
  const cols = 10;
  const rows = 10;
  const step = 100 / cols;
  const rMax = step * 0.52;
  const dots: React.ReactNode[] = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const cx = (col + (row % 2 ? 0.5 : 0)) * step + step * 0.25;
      const cy = row * step + step * 0.5;
      const dx = (100 - cx) / 100;
      const dy = (100 - cy) / 100;
      const dist = Math.sqrt(dx * dx + dy * dy) / 1.41421356;
      const r = rMax * Math.max(0, 1 - dist);
      if (r < 0.35) {
        continue;
      }
      const fill = (row + col) % 2 === 0 ? accent : sec;
      dots.push(<circle key={`${row}-${col}`} cx={cx.toFixed(2)} cy={cy.toFixed(2)} r={r.toFixed(2)} style={{ fill }} />);
    }
  }
  return dots;
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

// The pack's ground atmosphere alone — rendered BENEATH the scene content
// (before <Scene>), matching the still's z-order exactly: the still injects
// the ground at z-index 1 while archetype copy sits at z-index 2–3, so a
// top_fade / vignette / mesh ground never dims the card's text there. Texture
// (still z6) and accent geometry (still z8) stay in StylePackLayer above the
// scene. Same parse, same darken-only alphas, same ease-in.
const StylePackGroundLayer: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const pack = parseStylePack(ctx.card.stylePack || "");
  if (!pack) {
    return null;
  }
  const ground = packGroundGradient(
    pack.ground,
    pack.bold ? 0.34 : 0.24,
    ctx.card.packGroundFocus,
  );
  if (!ground) {
    return null;
  }
  const enter = interpolate(ctx.frame, [2, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", opacity: enter }}>
      <div style={{ position: "absolute", inset: 0, background: ground }} />
    </div>
  );
};

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
  const geo = packAccentGeometry(
    pack.accentGeo, width, height, pack.bold, accent,
    secondaryVisFor(ctx.brand, roles.ground || "#0A2540", accent),
  );
  if (geo) {
    children.push(<React.Fragment key="geo">{geo}</React.Fragment>);
  }
  // F7 overlap accent (still parity): the seeded badge/tab/rule/tape the still
  // straddles across a declared anchor. The motion side has no per-layout
  // anchor geometry, so it paints the same shape at a fixed overlap-safe corner
  // (upper-right, straddling the card's top-right third) — the mirror the
  // parity contract asks for.
  const overlap = packOverlapAccent(
    ctx.card.overlapAccent || "", width, height, accent, roles.ground || "#0A2540",
  );
  if (overlap) {
    children.push(<React.Fragment key="overlap">{overlap}</React.Fragment>);
  }

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", opacity: enter }}>
      {children}
    </div>
  );
};

// F7 overlap accent — mirrors style_packs.overlap_accent_html. Placed at a
// fixed overlap-safe point (72% across, 20% down) so it straddles the upper-
// right composition edge like the still's anchored accent. Parses "shape:rot".
function packOverlapAccent(
  id: string, width: number, height: number, accent: string, ground: string,
): React.ReactNode {
  const parts = (id || "").split(":");
  if (parts.length !== 2) {
    return null;
  }
  const shape = parts[0];
  const rotation = parseInt(parts[1], 10);
  if (!Number.isFinite(rotation) || !["badge", "tab", "rule", "tape"].includes(shape)) {
    return null;
  }
  const m = Math.min(width, height);
  const base: React.CSSProperties = {
    position: "absolute",
    left: "72%",
    top: "20%",
    zIndex: 15,
    transform: `translate(-50%,-50%) rotate(${rotation}deg)`,
    boxShadow: "0 6px 16px rgba(0,0,0,0.28)",
  };
  if (shape === "badge") {
    const d = Math.round(m * 0.14);
    return <div style={{ ...base, width: d, height: d, borderRadius: "50%", background: accent, border: `${Math.max(3, Math.round(m * 0.006))}px solid ${ground}` }} />;
  }
  if (shape === "tab") {
    return <div style={{ ...base, width: Math.round(m * 0.2), height: Math.round(m * 0.075), background: accent }} />;
  }
  if (shape === "rule") {
    return <div style={{ ...base, width: Math.round(m * 0.24), height: Math.max(6, Math.round(m * 0.018)), background: accent }} />;
  }
  // tape — accent at 0.6 alpha, multiply-blended, serrated ends.
  const clip = "polygon(0 18%,4% 0,8% 18%,12% 0,100% 0,96% 82%,100% 100%,96% 82%,92% 100%,88% 82%,0 82%)";
  return (
    <div style={{ ...base, width: Math.round(m * 0.26), height: Math.round(m * 0.06), background: accent, opacity: 0.6, mixBlendMode: "multiply", WebkitClipPath: clip, clipPath: clip, boxShadow: "0 2px 8px rgba(0,0,0,0.18)" }} />
  );
}

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
      <span style={{ ...wghtFvs(ctx.card.wghtMeta) }}>{meet}</span>
      <span style={{ fontWeight: 700, ...wghtFvs(ctx.card.wghtMeta) }}>{club}</span>
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
  // M19 — the "label" resolve accent: the chip re-pulses at ~70% of the beat.
  const pulse = anim.resolveAccentKind === "label" ? 1 + 0.05 * anim.resolveAccent : 1;
  return (
    <div
      style={{
        position: "absolute",
        top: top ?? Math.round(140 * ts),
        ...(center
          ? { left: "50%", transform: `translateX(-50%) scale(${pulse})` }
          : { left, transform: `scale(${pulse})`, transformOrigin: "left center" }),
        padding: `${Math.round(14 * ts)}px ${Math.round(28 * ts)}px`,
        background: roles.accent,
        color: roles.ground,
        fontSize: Math.round(36 * ts),
        fontWeight: 800,
        ...wghtFvs(ctx.card.wghtKicker),
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
        {kernNumeric(ctx.result || "—")}
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
// F9 medal chrome: gradient-clip a numeral with the resolved specular ramp so
// the video reads as polished metal like the still. Empty ramp → no override
// (the numeral keeps its role colour), byte-equivalent to the pre-F9 scene.
function medalNumeralStyle(ramp: string): React.CSSProperties {
  if (!ramp) {
    return {};
  }
  return {
    backgroundImage: ramp,
    WebkitBackgroundClip: "text",
    backgroundClip: "text",
    WebkitTextFillColor: "transparent",
    color: "transparent",
  };
}

const PosterScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, ts } = ctx;
  const isQuote = card.archetype === "quote_led_recap";
  const megaIsResult = Boolean(ctx.resultFinal);
  const mega = megaIsResult ? ctx.result : ctx.surnameText;
  // Medal chrome on the mega RESULT numeral only (parity with the still's
  // gradient-clipped .bn__result / .cn__num — uses the gate-passing numeral
  // ramp, so a dark-ground numeral stays flat exactly like the still).
  const megaChrome = megaIsResult ? medalNumeralStyle(card.roleMedalNumeralRamp || "") : {};
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
            ...megaChrome,
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
          {megaIsResult ? ctx.event : kernNumeric(ctx.result)}
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
            {kernNumeric(ctx.result)}
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
// E4 (Canva gap analysis) — shaped photo-frame parity helpers. The still
// reshapes the windowed archetypes' photo well and pairs it with an offset
// accent echo; these mirror that as STATIC geometry in the motion scenes, keyed
// off the SAME numbers Python forwarded so the silhouette matches the still.
// All are no-ops for rect / the lever absent, so unshaped cards are unchanged.
// Per-card so a reel with several torn beats in one DOM never collides ids.
function frameTornId(card: CardProps): string {
  return `mh-frame-torn-motion-${card.frameTornSeed || 0}`;
}

export function hasFrameShape(card: CardProps): boolean {
  const shape = (card.frameShape || "").toLowerCase();
  return shape === "arch" || shape === "blob" || shape === "torn_edge";
}

export function frameClipStyle(card: CardProps): React.CSSProperties {
  const shape = (card.frameShape || "").toLowerCase();
  if (shape === "arch" || shape === "blob") {
    return card.frameRadius ? { borderRadius: card.frameRadius } : {};
  }
  if (shape === "torn_edge") {
    return { filter: `url(#${frameTornId(card)})` };
  }
  return {};
}

// The zero-size torn-edge filter, built from the exact feTurbulence /
// feDisplacementMap numbers the still seeded (graphic_renderer.photo_frame),
// so the motion tear runs along the identical noise field. Null unless torn.
export const FrameTornDef: React.FC<{ card: CardProps }> = ({ card }) => {
  if ((card.frameShape || "").toLowerCase() !== "torn_edge") return null;
  return (
    <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
      <filter
        id={frameTornId(card)}
        x="-12%"
        y="-12%"
        width="124%"
        height="124%"
        colorInterpolationFilters="sRGB"
      >
        <feTurbulence
          type="fractalNoise"
          baseFrequency={card.frameTornFreq || 0.03}
          numOctaves={2}
          seed={card.frameTornSeed || 0}
          result="mh-frame-noise"
        />
        <feDisplacementMap
          in="SourceGraphic"
          in2="mh-frame-noise"
          scale={card.frameTornScale || 14}
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
    </svg>
  );
};

// The offset accent echo — the same shape in the accent role, shifted `off` px
// down-right behind the framed element (which must sit in a position:relative
// box). Rendered only for a real shape, so it never appears on rect cards.
export const FrameEcho: React.FC<{
  card: CardProps;
  accent: string;
  width: number | string;
  height: number | string;
  off: number;
  left?: number;
  top?: number;
  zIndex?: number;
}> = ({ card, accent, width, height, off, left = 0, top = 0, zIndex = -1 }) => {
  if (!hasFrameShape(card)) return null;
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        height,
        background: accent,
        transform: `translate(${off}px, ${off}px)`,
        zIndex,
        ...frameClipStyle(card),
      }}
    />
  );
};

const SpotlightScene: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  const ringSize = Math.round(Math.min(width, height) * 0.34);
  // F9 medal chrome: on a medal card the result reads as a bevelled ramp chip
  // (parity with the still's .cm__result pill). Empty ramp → plain accent
  // numeral, byte-equivalent to before.
  const medalRamp = card.roleMedalRamp || "";
  const chipChrome: React.CSSProperties = medalRamp
    ? {
        display: "inline-block",
        padding: `${Math.round(16 * ts)}px ${Math.round(40 * ts)}px`,
        borderRadius: 999,
        background: medalRamp,
        color: roles.ground,
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.28), inset 0 -2px 4px rgba(0,0,0,0.5)",
        border: "1px solid rgba(255,255,255,0.28)",
      }
    : {};
  const place = placeDisplay(card.place || "");
  const shaped = hasFrameShape(card);
  const ringTransform = `scale(${0.8 + 0.2 * anim.heroOpacity}) translateY(${anim.heroY * 0.4}px)`;
  // The ring badge is the spotlight's framed focal element; when the still
  // shaped its photo window, mirror the same silhouette + offset echo onto it.
  const ringChildren = (
    <>
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
    </>
  );
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
        {/* Ring badge with the placing (only real data) or the label. When the
            still shaped this card's photo window, the ring mirrors the same
            silhouette + offset accent echo (E4). */}
        {shaped ? (
          <div
            style={{
              position: "relative",
              width: ringSize,
              height: ringSize,
              transform: ringTransform,
              opacity: anim.heroOpacity,
            }}
          >
            <FrameTornDef card={card} />
            <FrameEcho
              card={card}
              accent={roles.accent}
              width={ringSize}
              height={ringSize}
              off={Math.round(12 * ts)}
            />
            <div
              style={{
                position: "absolute",
                inset: 0,
                border: `${Math.max(5, Math.round(8 * ts))}px solid ${roles.accent}`,
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                alignItems: "center",
                ...frameClipStyle(card),
              }}
            >
              {ringChildren}
            </div>
          </div>
        ) : (
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
              transform: ringTransform,
              opacity: anim.heroOpacity,
            }}
          >
            {ringChildren}
          </div>
        )}

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
            ...chipChrome,
          }}
        >
          {kernNumeric(ctx.result)}
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
                {/* A5 parity — only the hero RESULT tile kerns its numeral
                    (the still kerns RESULT_VALUE alone); other tiles' values,
                    incl. the heroStat "0.42"-style figure, stay un-kerned. */}
                {t.hero ? kernNumeric(t.value) : t.value}
              </div>
            </div>
          );
        })}
        {/* M11 parity — the still's secondary-stat chips + honest PB bars
            flow below the tiles (editorial_numbers_grid / stat_stack_sidebar);
            both collapse to nothing when the props are absent. */}
        <StatChipsBlock ctx={ctx} />
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
        {kernNumeric(ctx.result)}
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
  // M20 — multi-athlete panels: when motion.py resolved extra linked-athlete
  // photos (photoSrcs), the duo split fills its wedge with the second
  // athlete's photo and the triptych stacks up to two framed panels on the
  // wedge. Empty photoSrcs renders byte-identically to the single-photo card.
  const extras = (card.photoSrcs || []).filter(Boolean);
  const duoSrc = card.archetype === "duo_athlete_split" ? extras[0] || "" : "";
  const triptychSrcs =
    card.archetype === "triptych_progression" ? extras.slice(0, 2) : [];
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
      {duoSrc ? (
        // The second athlete rides the wedge itself — a true duo split.
        <div
          style={{
            position: "absolute",
            inset: 0,
            clipPath: `polygon(${width * 0.62}px 0, 100% 0, 100% 100%, ${width * 0.34}px 100%)`,
            transform: `translateX(${sweep}px)`,
            opacity: anim.heroOpacity,
          }}
        >
          <img
            src={duoSrc}
            alt=""
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: "center 28%",
              transform: `translate(${-anim.photoDriftX}%, ${anim.photoDriftY}%) scale(${anim.photoScale})`,
            }}
          />
          {/* Role scrim so the result stays legible on the wedge. */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `linear-gradient(180deg, ${roles.surface}66 0%, ${roles.surface}D8 78%)`,
            }}
          />
        </div>
      ) : null}
      {triptychSrcs.map((src, i) => (
        // Progression panels stacked on the wedge — framed, entering on the
        // chip channel so they settle after the facts.
        <div
          key={`tri-${i}`}
          style={{
            position: "absolute",
            right: Math.round(70 * ts),
            top: height * (0.14 + 0.22 * i),
            width: Math.round(width * 0.24),
            height: Math.round(width * 0.24),
            overflow: "hidden",
            borderRadius: 10,
            border: `3px solid ${roles.accent}`,
            opacity: anim.chipOpacity,
            transform: `translateY(${(1 - anim.chipOpacity) * 30}px)`,
          }}
        >
          <img
            src={src}
            alt=""
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: "center 28%",
              transform: `scale(${anim.photoScale})`,
            }}
          />
        </div>
      ))}
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

      {/* M11 parity — triptych_progression's context-bay stat chips (the
          still's {{STAT_CHIPS}} slot); collapses when the props are absent. */}
      <div style={{ position: "absolute", left: 80, top: height * 0.68, width: width * 0.52 }}>
        <StatChipsBlock ctx={ctx} />
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
        {kernNumeric(ctx.result)}
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
          ctx.event && ctx.result ? `${ctx.event} — ${kernNumeric(ctx.result)}` : ctx.event || ctx.result,
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

// M19 — the "underline" resolve accent: a short accent rule that draws in at
// ~70% of the beat (left→right) near the lower text region, then recedes with
// the pulse. Scene-agnostic (it lives in the frame's margin), painted in the
// resolved accent role only, and skipped entirely for the other accent kinds.
const ResolveAccentLayer: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { anim, roles, ts, frame, height } = ctx;
  const { durationInFrames } = useVideoConfig();
  if (anim.resolveAccentKind !== "underline" || anim.resolveAccent <= 0) {
    return null;
  }
  const draw = interpolate(
    frame,
    [durationInFrames * 0.68, durationInFrames * 0.76],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) },
  );
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: Math.round(150 * ts),
        width: Math.round(220 * ts * draw),
        height: Math.max(4, Math.round(5 * ts)),
        background: roles.accent,
        opacity: anim.resolveAccent,
        pointerEvents: "none",
      }}
    />
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
    card.variationSeed || 0,
    card.staggerScale && card.staggerScale > 0 ? resolveStagger(card.staggerScale) : undefined,
  );
  const mode = sceneForArchetype(card.archetype || "");
  const layout = compositionLayoutFor(card.composition || "left", width);

  // Type scale: 1.0 on the 1080×1920 design canvas; square and landscape
  // cuts shrink type proportionally so the stack still breathes.
  const ts = Math.min(width / 1080, height / 1440, 1);

  // Outro: fade to black on last 0.4s — but ONLY for the standalone story.
  // Inside a reel (card.inReel, set by MeetReel.tsx) the beat's exit belongs
  // to the paired transition (M16): the outgoing content stays fully visible
  // until the incoming beat's transition takes over, so handoffs never dip
  // through black.
  const outroFade = card.inReel
    ? 1
    : interpolate(
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
        // G1.8 mesh ground — the still's exact SVG, under every content layer
        // (the still hook overrides the ground element's background-image the
        // same way). Absent = the flat brand ground, byte-identical.
        ...(card.meshBg
          ? {
              backgroundImage: card.meshBg,
              backgroundSize: "cover",
              backgroundPosition: "center",
              backgroundRepeat: "no-repeat",
            }
          : {}),
        fontFamily: fontStack,
        opacity: outroFade,
      }}
    >
      {/* Pack ground BENEATH the scene (the still's z1-under-copy order). */}
      <StylePackGroundLayer ctx={ctx} />
      <Scene ctx={ctx} />
      <ResolveAccentLayer ctx={ctx} />
      <StylePackLayer ctx={ctx} />
      {/* Sprint overlay layers (R1.6/8/9/10/11/22/23/24/25) — additive, in order. */}
      {EXTRA_LAYERS.map(({ Layer }, i) => (
        <Layer key={`sprint-layer-${i}`} ctx={ctx} />
      ))}
    </AbsoluteFill>
  );
};
