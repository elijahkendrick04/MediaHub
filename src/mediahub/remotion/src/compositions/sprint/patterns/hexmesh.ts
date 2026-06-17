// Background pattern — hexagonal mesh / honeycomb (roadmap R1.4).
//
// Flat-top hexagons on a 60×34.64 tile (side 20): one centred hex plus the four
// corner hexes, so the tile clips and repeats into a continuous honeycomb.
// Monochrome accent role, low opacity. Pure function of `roles` — deterministic,
// no RNG, no time source (frame-pure).
import type { Roles } from "../registry";

const alpha = (hex: string, op: number): string =>
  `${hex}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
const enc = (svg: string): string =>
  `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;

// Flat-top hexagon outline (side 20, half-height 17.32 ≈ 10√3) centred at (cx,cy).
const hex = (cx: number, cy: number): string =>
  `M${cx + 20},${cy} L${cx + 10},${cy + 17.32} L${cx - 10},${cy + 17.32} ` +
  `L${cx - 20},${cy} L${cx - 10},${cy - 17.32} L${cx + 10},${cy - 17.32} Z`;

const pattern = (roles: Roles): string => {
  const a = roles.accent || "#FFFFFF";
  const cells = [hex(30, 17.32), hex(0, 0), hex(60, 0), hex(0, 34.64), hex(60, 34.64)];
  return enc(
    `<svg xmlns='http://www.w3.org/2000/svg' width='60' height='34.64'>` +
      `<path d='${cells.join(" ")}' fill='none' stroke='${alpha(a, 0.16)}' stroke-width='1.5'/>` +
      `</svg>`,
  );
};

export default { name: "hexmesh", pattern };
