// Background pattern — circuit traces (roadmap R1.4).
//
// Right-angle traces with solder-pad nodes. The traces enter the left edge and
// exit the right edge at the same y (30), so horizontal neighbours connect into
// a continuous board. Monochrome accent role, low opacity. Pure function of
// `roles` — deterministic, no RNG, no time source (frame-pure).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>` +
      `<g fill='none' stroke='${alpha(a, 0.16)}' stroke-width='2'>` +
      `<path d='M0,30 H32 V68 H72 V30 H100'/>` +
      `<path d='M50,0 V22 H82 V52'/>` +
      `<path d='M18,100 V74 H46'/></g>` +
      `<g fill='${alpha(a, 0.24)}'>` +
      `<circle cx='32' cy='30' r='3.5'/><circle cx='72' cy='68' r='3.5'/>` +
      `<circle cx='82' cy='52' r='3.5'/><circle cx='46' cy='74' r='3.5'/></g>` +
      `</svg>`,
  );
};

export default { name: "circuit", pattern };
