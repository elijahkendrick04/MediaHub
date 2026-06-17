import type { AccentDecoration } from "../registry";

// A vertical accent rail down the left margin edge — the upright counterpart
// to the horizontal "stripe". Accent role only, kept in the left margin so it
// never overlaps the hero text.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  return (
    <div
      style={{
        position: "absolute",
        left: 48,
        top: height * 0.3,
        width: Math.max(5, m * 0.007),
        height: height * 0.34,
        background: roles.accent,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export default { name: "side_rail", decoration };
