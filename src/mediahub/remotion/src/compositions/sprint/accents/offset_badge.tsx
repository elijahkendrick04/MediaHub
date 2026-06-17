import type { AccentDecoration } from "../registry";

// Two concentric rings offset from one another in the bottom-right margin —
// a layered "offset badge" with depth, distinct from the built-in single
// "badge". The back ring sits behind and quieter; both are accent-role
// outlines so nothing is filled over the photo.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const size = m * 0.085;
  const weight = Math.max(3, m * 0.005);
  const off = m * 0.022;
  const accent = roles.accent;
  return (
    <>
      <div
        style={{
          position: "absolute",
          right: 72 - off,
          bottom: height * 0.2 - off,
          width: size,
          height: size,
          borderRadius: "50%",
          border: `${weight}px solid ${accent}`,
          opacity: opacity * 0.5,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 72,
          bottom: height * 0.2,
          width: size,
          height: size,
          borderRadius: "50%",
          border: `${weight}px solid ${accent}`,
          opacity,
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export default { name: "offset_badge", decoration };
