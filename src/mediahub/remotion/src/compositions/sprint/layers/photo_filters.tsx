// layers/photo_filters.tsx — Motion photo filter stack (roadmap R1.10)
//
// A deterministic, frame-pure brightness / contrast / saturation / blur grade
// applied to the card's photo, driven by brief fields (`photo_treatment`, with a
// tiny `mood` nuance). It is the motion-side parity of the still renderer's
// `graphic_renderer/render.py:_photo_treatment_css` — duotone / halftone /
// vignette read on a card's video exactly as they read on its approved still.
//
// Two design rules keep this exactly still-parity (never a scene-wide wash):
//
//   1. Photo-element-only. The grade is a CSS `filter` applied by the photo
//      paint sites (`PhotoLayer` / the scene kit's `PhotoFill`) directly on
//      their own `<img>` via `photoGradeFilterFor` — the same way the still
//      applies `_photo_treatment_css` to the photo element alone. Scene text,
//      chips and strips are never graded, whatever the layout puts mid-frame,
//      so the resolved APCA-gated roles keep their exact still-matched
//      contrast. (An earlier revision graded a fixed vertical band with a
//      masked `backdrop-filter`, which also washed any copy inside the band —
//      retired for this per-element parity.)
//
//   2. No-op unless the brief asked for a grade. `photoGradeFilterFor` returns
//      "" when the card has no photo, or its `photo_treatment` is clean /
//      structural (`cutout`, `frame`, `no-photo`), empty, or unknown. So every
//      photo-less card and every legacy / default caller renders
//      byte-identically — exactly the contract the sprint registry promises.
//
// The default-exported Layer now carries only the vignette's radial
// edge-darkening overlay (the one treatment whose character is a frame effect,
// not a photo grade); it keeps the same registry drop-in contract.
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

// The grade a card's photo holds at `frame`, as a CSS `filter` string — or ""
// when the card asks for none (no photo / clean / structural / unknown
// treatment), so ungraded cards stay byte-identical. Applied by the photo
// paint sites (PhotoLayer / PhotoFill) on their own <img> element — exactly
// the still renderer's photo-element-only `_photo_treatment_css` scope, so
// scene text painted over the photo is never washed.
export function photoGradeFilterFor(
  card: { photoSrc?: string; photoTreatment?: string; mood?: string },
  frame: number,
  fps: number,
): string {
  // Gate 1 — no photo means nothing to grade (photo-less cards stay identical).
  if (!card.photoSrc) {
    return "";
  }
  // Gate 2 — a clean / structural / unknown treatment asks for no grade.
  const base = baseStackFor(card.photoTreatment || "");
  if (!base) {
    return "";
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
  return cssFilter(developStack(stack, dev), blurPx);
}

const Layer: SceneComponent = ({ ctx }) => {
  const { card, frame, fps } = ctx;

  // The overlay half of the treatment: only the vignette paints a frame
  // effect (its radial edge-darkening). The photo grade itself rides the
  // photo <img> via photoGradeFilterFor — see the header.
  if (!card.photoSrc) {
    return null;
  }
  if ((card.photoTreatment || "").toLowerCase() !== "vignette") {
    return null;
  }
  const vig = interpolate(frame, [0, fps * DEVELOP_SEC], [0, VIGNETTE_MAX_ALPHA], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
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
