// Background pattern — checkerboard (roadmap R1.4).
//
// A two-cell checker tile. Monochrome in the resolved accent role and low
// opacity so it reads as texture under the card content, never as a competing
// illustration. Pure function of `roles` only — deterministic, no RNG, no time
// source — so the motion render is frame-pure (it drifts via the PatternLayer
// parallax channel, it never self-animates).
//
// The tiny `alpha` / `enc` helpers are inlined deliberately: each sprint
// pattern is a self-contained file with no cross-file dependency, which is what
// keeps parallel sprint sessions merge-conflict-free (see ../registry.ts).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>` +
      `<rect width='40' height='40' fill='${alpha(a, 0.1)}'/>` +
      `<rect x='40' y='40' width='40' height='40' fill='${alpha(a, 0.1)}'/>` +
      `</svg>`,
  );
};

export default { name: "checkerboard", pattern };
