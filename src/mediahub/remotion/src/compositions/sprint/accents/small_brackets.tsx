import type { AccentDecoration } from "../registry";

// Compact corner brackets (top-left + bottom-right) — the small sizing
// variant of the built-in "brackets": tighter and lighter for a restrained
// frame. Outline accent only.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const size = m * 0.035;
  const weight = Math.max(2, m * 0.0035);
  const accent = roles.accent;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 64,
          top: height * 0.44,
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
          right: 96,
          bottom: height * 0.22,
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

export default { name: "small_brackets", decoration };
