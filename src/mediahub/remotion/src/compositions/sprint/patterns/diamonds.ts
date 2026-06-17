// Background pattern — diamonds / argyle lattice (roadmap R1.4).
//
// A diamond outline whose vertices sit on the tile-edge midpoints, so the tile
// repeats into a seamless argyle lattice, with a faint cross rule for the
// classic argyle weave. Monochrome accent role, low opacity. Pure function of
// `roles` — deterministic, no RNG, no time source (frame-pure).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='56' height='56'>` +
      `<path d='M28,0 L56,28 L28,56 L0,28 Z' fill='none' stroke='${alpha(a, 0.16)}' stroke-width='1.5'/>` +
      `<path d='M28,0 L28,56 M0,28 L56,28' stroke='${alpha(a, 0.07)}' stroke-width='1'/>` +
      `</svg>`,
  );
};

export default { name: "diamonds", pattern };
