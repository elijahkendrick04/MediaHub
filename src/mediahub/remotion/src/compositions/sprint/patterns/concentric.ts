// Background pattern — concentric rings (roadmap R1.4).
//
// Three concentric ring outlines with a centre node, tiling into a ripple /
// radar field. Monochrome accent role, low opacity. Pure function of `roles` —
// deterministic, no RNG, no time source (frame-pure).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>` +
      `<g fill='none' stroke='${alpha(a, 0.15)}' stroke-width='1.5'>` +
      `<circle cx='40' cy='40' r='12'/>` +
      `<circle cx='40' cy='40' r='24'/>` +
      `<circle cx='40' cy='40' r='36'/></g>` +
      `<circle cx='40' cy='40' r='2.5' fill='${alpha(a, 0.22)}'/>` +
      `</svg>`,
  );
};

export default { name: "concentric", pattern };
