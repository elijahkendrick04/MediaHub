// Background pattern — organic waves (roadmap R1.4).
//
// Three evenly-stacked flowing sine waves (denser than the built-in single
// "water" wave). Each wave returns to its baseline with matching slope at x=0
// and x=120, so the tile repeats seamlessly left-to-right; the 24px row pitch
// wraps cleanly over the 72px tile height. Monochrome accent role, low opacity.
// Pure function of `roles` — deterministic, no RNG, no time source (frame-pure).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='72'>` +
      `<g fill='none' stroke='${alpha(a, 0.16)}' stroke-width='2'>` +
      `<path d='M0,12 Q30,4 60,12 T120,12'/>` +
      `<path d='M0,36 Q30,28 60,36 T120,36'/>` +
      `<path d='M0,60 Q30,52 60,60 T120,60'/></g>` +
      `</svg>`,
  );
};

export default { name: "organic-waves", pattern };
