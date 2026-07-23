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
import React from "react";
import { Easing, interpolate } from "remotion";
import type { SceneComponent } from "../registry";

// ---------------------------------------------------------------------------
// Exact still mirrors (parity pass — M10 true brand duotone / real halftone).
//
// For a v2 archetype card, motion.py passes the still's OWN computed
// parameters: `duotoneShadow`/`duotoneHighlight` (render.darken(--mh-primary,
// 0.30) and the resolved --mh-accent, medal tints included) and `halftoneTile`
// (round(14 + 18·decoration_strength)). The recipes below rebuild the still's
// SVG filter / mask byte-for-byte from those hexes, so the video photo carries
// the identical two-ink duotone / print-dot halftone the approved still
// painted — not the legacy CSS approximation, which is fully suppressed when
// an exact mirror applies (never stacked). Cards without these props (v1
// briefs, untreated photos) keep the legacy grade path unchanged.
// ---------------------------------------------------------------------------

type TreatmentCard = {
  photoSrc?: string;
  photoTreatment?: string;
  photoPos?: string;
  mood?: string;
  variationSeed?: number;
  // blur-family (picked Python-side by motion.py `_focus_blur_style`): one of
  // "directional" | "radial" | "lens" enriches the develop-in focus blur on a
  // legacy-animated graded photo card into a real SVG-filter smear. Absent /
  // "gaussian" = today's isotropic CSS blur() focus-in, byte-identical.
  focusBlurStyle?: string;
  duotoneShadow?: string;
  duotoneHighlight?: string;
  halftoneTile?: number;
  // B5 die-cut sticker contour — the resolved on-ground ink + radius px the
  // still computed (render._sticker_outline_css); only set for a sticker-
  // treated card with a real cutout.
  stickerInk?: string;
  stickerRadius?: number;
  cutoutSrc?: string;
  // C5 brand colour-wash — the deep brand tint hex (render.darken(--mh-primary,
  // 0.20)) + the arithmetic mix fraction (0.18 + 0.24·strength) the still's
  // _wash_defs_svg composites; only set for a wash-treated v2 card.
  washTint?: string;
  washMix?: number;
  // stylize-richer — three held pure-SVG looks, each rebuilt byte-for-byte from
  // the still's _v2_photo_treatment_assets. mosaicBlock = feMorphology dilate
  // radius (render._mosaic_defs_svg); motionTileGrid = the static feTile
  // replicate grid N (render._motion_tile_defs_svg); roughenSeed/roughenScale =
  // the held feTurbulence integer seed (derived from the shared
  // variation_signature) + feDisplacementMap scale (render._roughen_edges_defs_svg).
  // treatmentIntensity is the resolved 0..1 strength (informational parity).
  // 0 / absent on all of them = no stylize look, byte-identical.
  mosaicBlock?: number;
  motionTileGrid?: number;
  roughenSeed?: number;
  roughenScale?: number;
  treatmentIntensity?: number;
};

// The still's exact held halftone grade (render._v2_photo_treatment_assets):
// img.athlete-cutout { filter: grayscale(1) contrast(1.18) brightness(0.98) }.
export const HALFTONE_FILTER = "grayscale(1) contrast(1.18) brightness(0.98)";

// The still's feColorMatrix luminance constant (render._duotone_defs_svg).
const DUOTONE_LUMA =
  "0.2126 0.7152 0.0722 0 0 " +
  "0.2126 0.7152 0.0722 0 0 " +
  "0.2126 0.7152 0.0722 0 0 " +
  "0 0 0 1 0";

function hexChannels(hex: string): [number, number, number] | null {
  const m = (hex || "").trim().match(/^#([0-9a-fA-F]{6})$/);
  if (!m) {
    return null;
  }
  return [
    parseInt(m[1].slice(0, 2), 16),
    parseInt(m[1].slice(2, 4), 16),
    parseInt(m[1].slice(4, 6), 16),
  ];
}

// True when the card carries the exact-mirror duotone parameters.
function duotoneActive(card: TreatmentCard): boolean {
  return Boolean(card.photoSrc && card.duotoneShadow && card.duotoneHighlight);
}

// Per-colour-pair filter id: inside a reel two beats can be mounted at once
// (the transition overlap) with different resolved inks — a shared id would
// let one card's duotone paint the other's photo.
export function duotoneFilterId(card: TreatmentCard): string {
  const s = (card.duotoneShadow || "").replace("#", "");
  const h = (card.duotoneHighlight || "").replace("#", "");
  return `mh-duotone-${s}-${h}`;
}

// The still's wash saturation constant (render._wash_defs_svg default 0.4,
// formatted ".2f").
const WASH_SATURATION = "0.40";

// True when the card carries the exact-mirror C5 wash parameters.
function washActive(card: TreatmentCard): boolean {
  return Boolean(card.photoSrc && card.washTint && (card.washMix || 0) > 0);
}

// The mix fraction clamped exactly as the still does (max(0, min(0.6, mix))).
function washMixClamped(card: TreatmentCard): number {
  return Math.max(0, Math.min(0.6, card.washMix || 0));
}

// Per-(tint, mix) filter id — same reason as duotone's: two reel beats can be
// mounted at once with different resolved washes, so a shared id would let one
// card's tint paint the other's photo.
export function washFilterId(card: TreatmentCard): string {
  const t = (card.washTint || "").replace("#", "");
  const m = Math.round(washMixClamped(card) * 1000);
  return `mh-wash-${t}-${m}`;
}

// ---------------------------------------------------------------------------
// stylize-richer — three held pure-SVG looks (mosaic / motion_tile /
// roughen_edges), each an exact byte-for-byte mirror of the still's
// _v2_photo_treatment_assets SVG. Held (no time term) and RNG-free — roughen's
// feTurbulence takes an INTEGER seed derived Python-side from the shared
// variation_signature, so still and motion draw the identical silhouette. Each
// is gated on its own param + a photo, so untreated cards stay byte-identical,
// and each carries a per-param filter id (the duotone/wash reasoning) so a reel
// transition overlap can never let one beat's filter paint the other's photo.
// ---------------------------------------------------------------------------

function mosaicActive(card: TreatmentCard): boolean {
  return Boolean(card.photoSrc && (card.mosaicBlock || 0) > 0);
}

export function mosaicFilterId(card: TreatmentCard): string {
  return `mh-mosaic-${Math.round(card.mosaicBlock || 0)}`;
}

function motionTileActive(card: TreatmentCard): boolean {
  return Boolean(card.photoSrc && (card.motionTileGrid || 0) > 1);
}

export function motionTileFilterId(card: TreatmentCard): string {
  return `mh-mtile-${Math.round(card.motionTileGrid || 0)}`;
}

function roughenActive(card: TreatmentCard): boolean {
  return Boolean(card.photoSrc && (card.roughenScale || 0) > 0);
}

export function roughenFilterId(card: TreatmentCard): string {
  const seed = Math.floor(card.roughenSeed || 0);
  const scale = Math.round(card.roughenScale || 0);
  return `mh-roughen-${seed}-${scale}`;
}

// ---------------------------------------------------------------------------
// blur-family — the develop-in focus blur, enriched from the single isotropic
// gaussian into a deterministic family {directional, radial, lens} rendered via
// an animated SVG <filter>. The style is chosen Python-side (motion.py
// `_focus_blur_style`, a pure function of variationSeed + mood) and passed as
// `focusBlurStyle`, so the two surfaces can never drift (the exact-mirror
// philosophy). Like every treatment here it is a MOTION intro only: the
// magnitude rides the same `interpolate(frame) -> 0` develop-in curve, so the
// held frame is a filter NO-OP and still<->motion parity is preserved. Enabled
// ONLY on a legacy-animated graded photo card (never an exact-mirror
// duotone/halftone/wash card, and never stacked), so every other card renders
// byte-identically.
//
// SVG note: feGaussianBlur's `stdDeviation` is an XML attribute, not a CSS
// property, so it cannot ride a CSS var — the only frame-pure route is to
// re-emit the filter markup each frame with an interpolate(frame)-derived
// value. That is why PhotoFilterDefs takes `frame`/`fps` and re-renders (the
// reel whip helper's exact idiom, #reel-whip-*).
// ---------------------------------------------------------------------------

// The three non-gaussian styles. "gaussian" / absent = today's blur() focus-in.
const FOCUS_BLUR_STYLES = ["directional", "radial", "lens"] as const;
// The lens bokeh's highlight lift is bounded and transient — it rides the same
// frame->0 curve, so on the held frame the transfer is identity (slope 1) and
// it can never leave a permanent brightened plate under APCA-gated text.
const FOCUS_LENS_MAX_LIFT = 0.12;

// Deterministic [0,1) from the seed — the integer hash pattern_drift.tsx uses
// (frame-independent, no randomness), so a card's axis pick is stable.
function focusSeedFrac(seed: number): number {
  const s = Math.floor(Math.abs(seed)) || 0;
  return ((((s * 2654435761) % 1000) + 1000) % 1000) / 1000;
}

// True when motion.py enabled the family for this card (a legacy-animated
// graded photo). Every other card keeps the plain gaussian focus-in.
function focusBlurActive(card: TreatmentCard): boolean {
  const style = (card.focusBlurStyle || "").toLowerCase();
  return Boolean(card.photoSrc) && (FOCUS_BLUR_STYLES as readonly string[]).includes(style);
}

// Per-(style, seed) filter id — two reel beats can be mounted at once during a
// transition overlap; a shared id would let one beat's animated blur bleed onto
// the other's photo (the duotoneFilterId / washFilterId reasoning).
export function focusBlurFilterId(card: TreatmentCard): string {
  const style = (card.focusBlurStyle || "gaussian").toLowerCase();
  const seed = Math.floor(Math.abs(card.variationSeed || 0)) || 0;
  return `mh-focus-${style}-${seed}`;
}

// The develop-in blur magnitude at `frame` — the SAME frame-pure curve the
// legacy gaussian focus-in used (FOCUS_IN_BLUR_PX -> 0, eased out), so the
// family resolves to a no-op on the held frame and the photo is left sharp.
function focusBlurMag(frame: number, fps: number): number {
  return interpolate(frame, [0, fps * FOCUS_IN_SEC], [FOCUS_IN_BLUR_PX, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
}

// Percent focus [fx, fy] from an objectPosition string ("center 28%",
// "62% 40%", …) — the axis a radial-zoom streak orients from. Defaults to the
// photo layer's "center 28%".
function focusPercent(pos: string): [number, number] {
  const words: Record<string, number> = {
    left: 0,
    top: 0,
    center: 50,
    right: 100,
    bottom: 100,
  };
  const parts = (pos || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const val = (tok: string, fallback: number): number => {
    if (tok in words) {
      return words[tok];
    }
    const m = tok.match(/^(-?\d+(?:\.\d+)?)%?$/);
    return m ? Number(m[1]) : fallback;
  };
  const fx = parts.length >= 1 ? val(parts[0], 50) : 50;
  const fy = parts.length >= 2 ? val(parts[1], 28) : 28;
  return [fx, fy];
}

// The frame-pure focus-blur <filter> primitives for the active style. Re-built
// each frame from `mag` (the develop-in magnitude), so the intro animates and
// resolves to a no-op (stdDeviation 0 / identity transfer) on the held frame.
function focusBlurPrimitives(
  card: TreatmentCard,
  mag: number,
): React.ReactNode {
  const style = (card.focusBlurStyle || "").toLowerCase();
  if (style === "directional") {
    // A whip streak — a single-axis feGaussianBlur (the reel whip helper's
    // "Bx 0" idiom), the axis quantized from the seed so sibling cards streak
    // differently. edgeMode="duplicate" avoids a transparent halo at the edge.
    const axes: Array<[number, number]> = [
      [mag, 0],
      [0, mag],
      [mag * 0.85, mag * 0.35],
      [mag * 0.35, mag * 0.85],
    ];
    const i = Math.floor(focusSeedFrac(card.variationSeed || 0) * axes.length) % axes.length;
    const [sx, sy] = axes[i];
    return (
      <feGaussianBlur
        in="SourceGraphic"
        stdDeviation={`${sx.toFixed(3)} ${sy.toFixed(3)}`}
        edgeMode="duplicate"
      />
    );
  }
  if (style === "radial") {
    // Zoom-streak approximation — SVG has no single zoom-blur primitive, so a
    // single-axis feGaussianBlur oriented from the saliency focus (photoPos)
    // reads as a cheap, honest radial smear toward the subject.
    const [fx, fy] = focusPercent(card.photoPos || "");
    const horiz = Math.abs(fx - 50) >= Math.abs(fy - 50);
    const sx = horiz ? mag : mag * 0.25;
    const sy = horiz ? mag * 0.25 : mag;
    return (
      <feGaussianBlur
        in="SourceGraphic"
        stdDeviation={`${sx.toFixed(3)} ${sy.toFixed(3)}`}
        edgeMode="duplicate"
      />
    );
  }
  // lens — an isotropic defocus plus a BOUNDED, transient highlight lift for a
  // bokeh bloom. The lift rides the same frame->0 curve (slope 1 = identity on
  // the held frame).
  const lift = Number((1 + FOCUS_LENS_MAX_LIFT * (mag / FOCUS_IN_BLUR_PX)).toFixed(4));
  return (
    <>
      <feGaussianBlur in="SourceGraphic" stdDeviation={`${mag.toFixed(3)}`} result="mh-focus-src" />
      <feComponentTransfer in="mh-focus-src">
        <feFuncR type="linear" slope={lift} intercept={0} />
        <feFuncG type="linear" slope={lift} intercept={0} />
        <feFuncB type="linear" slope={lift} intercept={0} />
      </feComponentTransfer>
    </>
  );
}

// The zero-size SVG defs carrying the real exact-mirror filter for the card:
//   • duotone — the exact markup of the still's _duotone_defs_svg (sRGB
//     interpolation, luminance matrix, per-channel tableValues
//     "(shadow/255).toFixed(4) (highlight/255).toFixed(4)");
//   • wash (C5) — the still's _wash_defs_svg arithmetic recipe: saturate the
//     source, flood the resolved brand tint clipped to SourceAlpha, then
//     feComposite arithmetic mix (k2 = 1-m desaturated source, k3 = m tint);
//   • blur-family — the animated directional/radial/lens focus-blur <filter>
//     (re-emitted each frame with a frame-driven stdDeviation), only when
//     motion.py enabled it via `focusBlurStyle`.
// Rendered by every photo paint site next to its <img>; null unless the card
// carries one treatment's parameters, so untreated cards stay byte-identical.
export const PhotoFilterDefs: React.FC<{
  card: TreatmentCard;
  frame?: number;
  fps?: number;
}> = ({ card, frame = 0, fps = 30 }) => {
  if (duotoneActive(card)) {
    const sh = hexChannels(card.duotoneShadow || "");
    const hi = hexChannels(card.duotoneHighlight || "");
    if (!sh || !hi) {
      return null;
    }
    const t = (lo: number, hiC: number) => `${(lo / 255).toFixed(4)} ${(hiC / 255).toFixed(4)}`;
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={duotoneFilterId(card)} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={DUOTONE_LUMA} />
          <feComponentTransfer>
            <feFuncR type="table" tableValues={t(sh[0], hi[0])} />
            <feFuncG type="table" tableValues={t(sh[1], hi[1])} />
            <feFuncB type="table" tableValues={t(sh[2], hi[2])} />
          </feComponentTransfer>
        </filter>
      </svg>
    );
  }
  if (washActive(card)) {
    const m = washMixClamped(card);
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={washFilterId(card)} colorInterpolationFilters="sRGB">
          <feColorMatrix type="saturate" values={WASH_SATURATION} result="mh-w-desat" />
          <feFlood floodColor={card.washTint} result="mh-w-tint" />
          <feComposite in="mh-w-tint" in2="SourceAlpha" operator="in" result="mh-w-clip" />
          <feComposite
            in="mh-w-desat"
            in2="mh-w-clip"
            operator="arithmetic"
            k1={0}
            k2={Number((1 - m).toFixed(3))}
            k3={Number(m.toFixed(3))}
            k4={0}
          />
        </filter>
      </svg>
    );
  }
  if (mosaicActive(card)) {
    // stylize mosaic — the still's _mosaic_defs_svg feMorphology dilate.
    const r = Math.round(card.mosaicBlock || 0);
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={mosaicFilterId(card)} colorInterpolationFilters="sRGB">
          <feMorphology operator="dilate" radius={r} />
        </filter>
      </svg>
    );
  }
  if (motionTileActive(card)) {
    // stylize motion-tile — the still's _motion_tile_defs_svg static feTile of
    // the centre 1/N subregion. Percentages formatted to 4dp exactly as Python.
    const n = Math.round(card.motionTileGrid || 0);
    const size = (100 / n).toFixed(4);
    const orig = (50 - 50 / n).toFixed(4);
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={motionTileFilterId(card)} x="0%" y="0%" width="100%" height="100%">
          <feOffset
            in="SourceGraphic"
            dx="0"
            dy="0"
            x={`${orig}%`}
            y={`${orig}%`}
            width={`${size}%`}
            height={`${size}%`}
            result="mh-mt-tile"
          />
          <feTile in="mh-mt-tile" />
        </filter>
      </svg>
    );
  }
  if (roughenActive(card)) {
    // stylize roughen-edges — the still's _roughen_edges_defs_svg held
    // feTurbulence (integer seed from the shared variation_signature) +
    // feDisplacementMap. No time term, so still↔motion silhouettes are identical.
    const seed = Math.floor(card.roughenSeed || 0);
    const scale = Math.round(card.roughenScale || 0);
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={roughenFilterId(card)} colorInterpolationFilters="sRGB">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.04"
            numOctaves="2"
            seed={seed}
            result="mh-r-noise"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="mh-r-noise"
            scale={scale}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </svg>
    );
  }
  if (focusBlurActive(card)) {
    // The animated develop-in focus-blur family (directional/radial/lens),
    // re-emitted each frame with a frame-driven stdDeviation so the intro
    // resolves to a no-op on the held frame (sharp photo, parity preserved).
    const mag = focusBlurMag(frame, fps);
    return (
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter id={focusBlurFilterId(card)} x="-20%" y="-20%" width="140%" height="140%">
          {focusBlurPrimitives(card, mag)}
        </filter>
      </svg>
    );
  }
  return null;
};

// B5 die-cut sticker contour (exact mirror of render._sticker_outline_css): the
// eight zero-blur drop-shadows that trace the cutout's alpha silhouette in the
// card's resolved on-ground ink — the classic Canva/Bleacher-Report sticker
// edge that also hides matting fringe. The radius is passed from Python
// (round(min(w,h)*(0.003+0.004*strength))); the diagonal offset d = max(2,
// round(r·0.7071)) is rebuilt here byte-identically to the still. Returns ""
// unless the card carries the sticker params AND a real cutout — a full-bleed
// rectangle would paint a box halo (the still's cutout_ok gate), so untreated
// cards keep their grounded depth shadow untouched.
export function stickerContourFilter(card: TreatmentCard): string {
  const ink = (card.stickerInk || "").trim();
  const r = Math.round(card.stickerRadius || 0);
  if (!ink || r < 1 || !card.cutoutSrc) {
    return "";
  }
  const d = Math.max(2, Math.round(r * 0.7071));
  const offs: Array<[number, number]> = [
    [r, 0],
    [-r, 0],
    [0, r],
    [0, -r],
    [d, d],
    [d, -d],
    [-d, d],
    [-d, -d],
  ];
  return offs.map(([dx, dy]) => `drop-shadow(${dx}px ${dy}px 0 ${ink})`).join(" ");
}

// The still's exact-mirror grade for the card, or "" when no exact mirror
// applies. Static — the still's SVG filter has no develop-in, so the exact
// mirrors hold from frame 0 (the entrance animation belongs to the scene).
export function photoExactGradeFor(card: TreatmentCard): string {
  if (duotoneActive(card)) {
    return `url(#${duotoneFilterId(card)})`;
  }
  if (washActive(card)) {
    // C5 exact mirror — the still's SVG arithmetic wash, replacing the
    // approximate saturate(0.55) grade whenever motion.py passed the params.
    return `url(#${washFilterId(card)})`;
  }
  if (card.photoSrc && (card.halftoneTile || 0) > 0) {
    return HALFTONE_FILTER;
  }
  // stylize-richer — the three held SVG looks (mutually exclusive per card).
  if (mosaicActive(card)) {
    return `url(#${mosaicFilterId(card)})`;
  }
  if (motionTileActive(card)) {
    return `url(#${motionTileFilterId(card)})`;
  }
  if (roughenActive(card)) {
    return `url(#${roughenFilterId(card)})`;
  }
  return "";
}

// The real halftone's mask style — the still's _halftone_mask_tile_uri tile
// (style-pack dot geometry, two offset circles per tile, radii sized for
// ~2/3 coverage), or null when the card carries no halftone tile.
export function photoHalftoneMaskFor(card: TreatmentCard): React.CSSProperties | null {
  const tile = Math.round(card.halftoneTile || 0);
  if (!card.photoSrc || tile <= 0) {
    return null;
  }
  const t = Math.max(8, tile);
  const c1 = ((t * 6) / 22).toFixed(1);
  const c2 = ((t * 17) / 22).toFixed(1);
  const r1 = (t * 0.42).toFixed(1);
  const r2 = (t * 0.30).toFixed(1);
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' width='${t}' height='${t}'>` +
    `<circle cx='${c1}' cy='${c1}' r='${r1}' fill='white'/>` +
    `<circle cx='${c2}' cy='${c2}' r='${r2}' fill='white'/></svg>`;
  const uri = `url("data:image/svg+xml;utf8,${svg}")`;
  return {
    maskImage: uri,
    maskSize: `${t}px ${t}px`,
    WebkitMaskImage: uri,
    WebkitMaskSize: `${t}px ${t}px`,
  };
}

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
    case "wash":
      // C5 brand colour-wash APPROXIMATION — the desaturation half only. This
      // is the FALLBACK for v1 briefs / cards without the resolved tint: when
      // motion.py passed washTint/washMix the exact SVG mirror above
      // (photoExactGradeFor) takes over and this is never reached.
      return {
        brightness: 0.98,
        contrast: 1.02,
        saturate: 0.55,
        grayscale: 0,
        sepia: 0,
      };
    // "sticker" (B5) is a structural cutout contour, not a grade — the still
    // is authoritative; the outline stack mirrors here once the outline ink
    // reaches the props (roadmap). Falls through to the no-grade default.
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

// The grade head — brightness / contrast / saturate / grayscale / sepia — the
// part identical whether the tail is the gaussian blur() or the blur-family's
// url(#…) filter. Kept separate so both paths emit byte-identical head bytes.
function cssFilterHead(s: FilterStack): string {
  return (
    `brightness(${s.brightness.toFixed(3)}) ` +
    `contrast(${s.contrast.toFixed(3)}) ` +
    `saturate(${s.saturate.toFixed(3)}) ` +
    `grayscale(${s.grayscale.toFixed(3)}) ` +
    `sepia(${s.sepia.toFixed(3)})`
  );
}

// Compose the CSS filter string. All four roadmap levers — brightness, contrast,
// saturate (saturation), blur — are always present, alongside grayscale + sepia.
function cssFilter(s: FilterStack, blurPx: number): string {
  return `${cssFilterHead(s)} blur(${blurPx.toFixed(2)}px)`;
}

// The grade a card's photo holds at `frame`, as a CSS `filter` string — or ""
// when the card asks for none (no photo / clean / structural / unknown
// treatment), so ungraded cards stay byte-identical. Applied by the photo
// paint sites (PhotoLayer / PhotoFill) on their own <img> element — exactly
// the still renderer's photo-element-only `_photo_treatment_css` scope, so
// scene text painted over the photo is never washed.
export function photoGradeFilterFor(
  card: TreatmentCard,
  frame: number,
  fps: number,
): string {
  // Gate 1 — no photo means nothing to grade (photo-less cards stay identical).
  if (!card.photoSrc) {
    return "";
  }
  // Exact still mirrors first (parity pass): when motion.py passed the M10
  // duotone/halftone parameters, the legacy CSS approximation is suppressed
  // entirely — the exact grade is the only one applied (never stacked).
  const exact = photoExactGradeFor(card);
  if (exact) {
    return exact;
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
  const developed = developStack(stack, dev);
  // blur-family: when motion.py enabled a directional/radial/lens intro, the
  // family REPLACES only the plain blur() tail with the animated SVG filter
  // (PhotoFilterDefs emits its markup). The grade head is byte-identical, so a
  // family intro rides the same develop-in as the gaussian it enriches.
  if (focusBlurActive(card)) {
    return `${cssFilterHead(developed)} url(#${focusBlurFilterId(card)})`;
  }
  // Focus-in blur: starts soft, resolves to 0 — the held frame is always sharp.
  const blurPx = focusBlurMag(frame, fps);
  return cssFilter(developed, blurPx);
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
