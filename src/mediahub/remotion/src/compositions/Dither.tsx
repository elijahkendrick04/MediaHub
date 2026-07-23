import React from "react";
import { AbsoluteFill } from "remotion";

// render-banding-dither — a frame-INDEPENDENT ordered-dither debanding overlay.
//
// The motion twin of the still's sprint_hooks/dither_bg overlay: a static
// Bayer-8×8 tile of near-neutral greys, composited with mix-blend "overlay"
// over the scene's big brand fill. It nudges each pixel by at most ±1/255 in an
// ordered pattern — enough to break the 8-bit gradient banding a flat brand
// ground shows, without any hue (luminance only) and without moving the field's
// average colour (the matrix is symmetric about 128, the neutral-under-overlay
// grey). Purely a constant: it never reads useCurrentFrame / Date / random, so
// it is byte-stable across frames and folds nothing dynamic into the render.

// The standard 8×8 Bayer threshold matrix (0..63), symmetric about its midpoint
// so the emitted tile is mean-preserving. Mirrors render._BAYER_8X8.
const BAYER_8X8: number[][] = [
  [0, 32, 8, 40, 2, 34, 10, 42],
  [48, 16, 56, 24, 50, 18, 58, 26],
  [12, 44, 4, 36, 14, 46, 6, 38],
  [60, 28, 52, 20, 62, 30, 54, 22],
  [3, 35, 11, 43, 1, 33, 9, 41],
  [51, 19, 59, 27, 49, 17, 57, 25],
  [15, 47, 7, 39, 13, 45, 5, 37],
  [63, 31, 55, 23, 61, 29, 53, 21],
];

// Max luminance deviation, in 8-bit steps, around the neutral grey. Mirrors
// render._DITHER_AMPLITUDE (±1 ≈ ±1/255).
const DITHER_AMPLITUDE = 1;

function buildDitherUri(): string {
  const span = 2 * DITHER_AMPLITUDE;
  const rects: string[] = [];
  for (let y = 0; y < BAYER_8X8.length; y++) {
    const row = BAYER_8X8[y];
    for (let x = 0; x < row.length; x++) {
      const g = 128 + Math.round(((row[x] - 31.5) / 63.0) * span);
      rects.push(
        `<rect x='${x}' y='${y}' width='1' height='1' fill='rgb(${g},${g},${g})'/>`,
      );
    }
  }
  const svg =
    "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8' " +
    "shape-rendering='crispEdges'>" +
    rects.join("") +
    "</svg>";
  // btoa is available in the Remotion Chromium runtime; the SVG is ASCII-only.
  return `url("data:image/svg+xml;base64,${btoa(svg)}")`;
}

// Computed once at module load — a compile-time constant, not per-frame work.
const DITHER_URI = buildDitherUri();

export const Dither: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundImage: DITHER_URI,
      backgroundSize: "8px 8px",
      backgroundRepeat: "repeat",
      imageRendering: "pixelated",
      mixBlendMode: "overlay",
      pointerEvents: "none",
    }}
  />
);
