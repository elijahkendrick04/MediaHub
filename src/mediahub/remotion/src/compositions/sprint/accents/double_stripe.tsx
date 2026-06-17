import type { AccentDecoration } from "../registry";

// Two stacked accent rules — a rhythmic margin divider. Margin-safe and
// accent-role only; both bars share the supplied `opacity` so the pair fades
// as one element.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const w = m * 0.16;
  const h = Math.max(5, m * 0.007);
  const gap = Math.max(10, m * 0.024);
  const top = height * 0.42;
  const accent = roles.accent;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 80,
          top,
          width: w,
          height: h,
          background: accent,
          opacity,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 80,
          top: top + gap,
          width: w,
          height: h,
          background: accent,
          opacity,
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export default { name: "double_stripe", decoration };
