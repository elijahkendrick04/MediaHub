import type { AccentDecoration } from "../registry";

// Hairline horizontal rule in the left margin — the delicate cousin of the
// built-in "stripe": longer, thinner, quieter. Accent role only.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        top: height * 0.43,
        width: m * 0.26,
        height: Math.max(2, m * 0.0035),
        background: roles.accent,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export default { name: "thin_stripe", decoration };
