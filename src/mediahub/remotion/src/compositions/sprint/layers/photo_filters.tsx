// layers/photo_filters.tsx — Motion photo filter stack (roadmap R1.10)
//
// A deterministic, frame-pure brightness / contrast / saturation / blur grade
// applied to the card's photo, driven by brief fields (`photo_treatment`, with a
// tiny `mood` nuance). It is the motion-side parity of the still renderer's
// `graphic_renderer/render.py:_photo_treatment_css` — duotone / halftone /
// vignette read on a card's video exactly as they read on its approved still.
//
// Two design rules make this a safe *additive overlay* (never an edit to a scene):
//
//   1. In-place, never a repaint. The grade rides a `backdrop-filter` div, so it
//      modifies the pixels the scene's PhotoLayer already painted rather than
//      drawing a second copy of the photo. A repaint would sit on top of the
//      scene's text and could occlude a fact; an in-place filter cannot. It is
//      also masked to the photo's subject zone, so the bottom result/strip band
//      and the top chrome (logo, label chip) keep their exact still-matched
//      contrast — only the photo is graded. (If a headless renderer no-ops
//      `backdrop-filter`, the grade simply doesn't apply: an honest, legible
//      degradation, never a broken frame.)
//
//   2. No-op unless the brief asked for a grade. The layer returns null when the
//      card has no photo, or its `photo_treatment` is clean / structural
//      (`cutout`, `frame`, `no-photo`), empty, or unknown. So every photo-less
//      card and every legacy / default caller renders byte-identically to before
//      this file existed — exactly the contract the sprint registry promises.
//
// Pure function of the frame: the grade "develops" in over the first half second
// and the focus-in blur resolves to 0, so the held frame is perfectly sharp (no
// permanent softening of photo or text). No Math.random / Date — same inputs,
// same pixels, every render.
import { Easing, interpolate } from "remotion";
import type { SceneComponent } from "../registry";

// The frame-pure intro: how long the grade takes to develop, the focus-in blur
// it starts from (and resolves to 0), and the deepest a vignette darkens its
// corners. Kept small so the treatment reads as deliberate, never as a glitch.
const DEVELOP_SEC = 0.5;
const FOCUS_IN_BLUR_PX = 4;
const FOCUS_IN_SEC = 0.6;
const VIGNETTE_MAX_ALPHA = 0.4;

// Confine the grade to the photo's subject zone (faces frame at ~center 28%, the
// same default PhotoLayer uses). Transparent over the top chrome (≤9%) and over
// the bottom hero/result/strip band (≥66%, where the scene's scrim has already
// hidden the photo and the facts live), opaque across the subject in between.
const PHOTO_ZONE_MASK =
  "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0) 9%, " +
  "rgba(0,0,0,1) 17%, rgba(0,0,0,1) 48%, rgba(0,0,0,0) 66%)";

// The four held filter levers the roadmap names, plus the grayscale + sepia the
// still's duotone/halftone parity needs. Identity is brightness/contrast/saturate
// = 1, grayscale/sepia = 0 (and blur 0, applied separately as the focus-in).
type FilterStack = {
  brightness: number;
  contrast: number;
  saturate: number;
  grayscale: number;
  sepia: number;
};

// Map brief.photo_treatment → the held grade, in lock-step with the still
// renderer (graphic_renderer/render.py:_photo_treatment_css). `vignette` carries
// only a faint grade here — its real edge-darkening is the radial overlay below,
// the motion-honest analogue of the still's cutout drop-shadow glow. Every clean
// or structural value (cutout / frame / no-photo / "" / unknown) returns null →
// no grade, byte-identical output.
function baseStackFor(treatment: string): FilterStack | null {
  switch ((treatment || "").toLowerCase()) {
    case "duotone":
      // still: grayscale(1) contrast(1.10) brightness(0.96) sepia(0.30)
      return {
        brightness: 0.96,
        contrast: 1.1,
        saturate: 1,
        grayscale: 1,
        sepia: 0.3,
      };
    case "halftone":
      // still: grayscale(0.45) contrast(1.18) brightness(0.96)
      return {
        brightness: 0.96,
        contrast: 1.18,
        saturate: 1,
        grayscale: 0.45,
        sepia: 0,
      };
    case "vignette":
      return {
        brightness: 0.98,
        contrast: 1.05,
        saturate: 1.02,
        grayscale: 0,
        sepia: 0,
      };
    default:
      return null;
  }
}

// A tiny, deterministic nuance from brief.mood — but only ever a shift on an
// already-active grade, so mood alone can never turn a clean photo graded.
function applyMoodNuance(s: FilterStack, mood: string): FilterStack {
  const m = (mood || "").toLowerCase();
  let dSat = 0;
  let dCon = 0;
  if (/electric|kinetic|snappy|bold|triumph|celebratory/.test(m)) {
    dSat = 0.06;
    dCon = 0.03;
  } else if (/calm|composed|weighty|contemplative|melancholic/.test(m)) {
    dSat = -0.05;
    dCon = -0.02;
  }
  return {
    ...s,
    saturate: Math.max(0, s.saturate + dSat),
    contrast: Math.max(0, s.contrast + dCon),
  };
}

// Interpolate the held grade from identity toward its target by `dev` (0→1), so
// the photo develops into its treatment as the card opens.
function developStack(s: FilterStack, dev: number): FilterStack {
  return {
    brightness: 1 + (s.brightness - 1) * dev,
    contrast: 1 + (s.contrast - 1) * dev,
    saturate: 1 + (s.saturate - 1) * dev,
    grayscale: s.grayscale * dev,
    sepia: s.sepia * dev,
  };
}

// Compose the CSS filter string. All four roadmap levers — brightness, contrast,
// saturate (saturation), blur — are always present, alongside grayscale + sepia.
function cssFilter(s: FilterStack, blurPx: number): string {
  return (
    `brightness(${s.brightness.toFixed(3)}) ` +
    `contrast(${s.contrast.toFixed(3)}) ` +
    `saturate(${s.saturate.toFixed(3)}) ` +
    `grayscale(${s.grayscale.toFixed(3)}) ` +
    `sepia(${s.sepia.toFixed(3)}) ` +
    `blur(${blurPx.toFixed(2)}px)`
  );
}

const Layer: SceneComponent = ({ ctx }) => {
  const { card, frame, fps } = ctx;

  // Gate 1 — no photo means nothing to grade (photo-less cards stay identical).
  if (!card.photoSrc) {
    return null;
  }
  // Gate 2 — a clean / structural / unknown treatment asks for no grade.
  const base = baseStackFor(card.photoTreatment || "");
  if (!base) {
    return null;
  }
  const stack = applyMoodNuance(base, card.mood || "");

  const clamp = {
    extrapolateLeft: "clamp" as const,
    extrapolateRight: "clamp" as const,
  };
  const dev = interpolate(frame, [0, fps * DEVELOP_SEC], [0, 1], clamp);
  // Focus-in blur: starts soft, resolves to 0 — the held frame is always sharp.
  const blurPx = interpolate(
    frame,
    [0, fps * FOCUS_IN_SEC],
    [FOCUS_IN_BLUR_PX, 0],
    {
      ...clamp,
      easing: Easing.out(Easing.cubic),
    },
  );
  const filter = cssFilter(developStack(stack, dev), blurPx);

  const isVignette = (card.photoTreatment || "").toLowerCase() === "vignette";
  const vig = isVignette
    ? interpolate(frame, [0, fps * DEVELOP_SEC], [0, VIGNETTE_MAX_ALPHA], clamp)
    : 0;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backdropFilter: filter,
          WebkitBackdropFilter: filter,
          WebkitMaskImage: PHOTO_ZONE_MASK,
          maskImage: PHOTO_ZONE_MASK,
        }}
      />
      {vig > 0 ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              `radial-gradient(125% 115% at 50% 42%, rgba(0,0,0,0) 46%, ` +
              `rgba(0,0,0,${vig.toFixed(3)}) 100%)`,
          }}
        />
      ) : null}
    </div>
  );
};

export default { Layer, order: 6 };
