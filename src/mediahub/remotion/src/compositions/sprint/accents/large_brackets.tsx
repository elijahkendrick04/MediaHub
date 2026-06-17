import type { AccentDecoration } from "../registry";

// Oversized corner brackets (top-left + bottom-right) — the large sizing
// variant of the built-in "brackets". Outline accent only, well inside the
// margins so it never collides with the hero text.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const size = m * 0.09;
  const weight = Math.max(4, m * 0.006);
  const accent = roles.accent;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 56,
          top: height * 0.4,
          width: size,
          height: size,
          borderLeft: `${weight}px solid ${accent}`,
          borderTop: `${weight}px solid ${accent}`,
          opacity,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 90,
          bottom: height * 0.18,
          width: size,
          height: size,
          borderRight: `${weight}px solid ${accent}`,
          borderBottom: `${weight}px solid ${accent}`,
          opacity,
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export default { name: "large_brackets", decoration };
