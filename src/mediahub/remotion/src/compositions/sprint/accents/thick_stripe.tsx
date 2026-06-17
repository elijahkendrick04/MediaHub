import type { AccentDecoration } from "../registry";

// Bold horizontal accent bar in the left margin band — the heavyweight
// cousin of the built-in "stripe". Solid accent role only; the fade-in is
// driven entirely by the supplied `opacity` (deterministic, no own clock).
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        top: height * 0.42,
        width: m * 0.18,
        height: Math.max(12, m * 0.016),
        background: roles.accent,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export default { name: "thick_stripe", decoration };
