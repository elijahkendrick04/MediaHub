import type { AccentDecoration } from "../registry";

// Solid filled corner tabs (top-left + bottom-right) — the filled counterpart
// to the outline "brackets" and the round "badge". Accent role only,
// margin-safe.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const size = m * 0.045;
  const accent = roles.accent;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 56,
          top: height * 0.41,
          width: size,
          height: size,
          background: accent,
          opacity,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 92,
          bottom: height * 0.19,
          width: size,
          height: size,
          background: accent,
          opacity,
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export default { name: "corner_tabs", decoration };
