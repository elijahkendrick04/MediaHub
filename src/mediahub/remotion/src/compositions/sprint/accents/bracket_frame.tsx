import type { AccentDecoration } from "../registry";

// Four matched corner brackets — a symmetric corner frame, distinct from the
// diagonal two-corner "brackets" and from the solid-edge "frame". Outline
// accent only, evenly inset into all four margins.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const size = m * 0.05;
  const weight = Math.max(3, m * 0.0045);
  const accent = roles.accent;
  const inset = 56;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: inset,
          top: inset,
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
          right: inset,
          top: inset,
          width: size,
          height: size,
          borderRight: `${weight}px solid ${accent}`,
          borderTop: `${weight}px solid ${accent}`,
          opacity,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: inset,
          bottom: inset,
          width: size,
          height: size,
          borderLeft: `${weight}px solid ${accent}`,
          borderBottom: `${weight}px solid ${accent}`,
          opacity,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: inset,
          bottom: inset,
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

export default { name: "bracket_frame", decoration };
