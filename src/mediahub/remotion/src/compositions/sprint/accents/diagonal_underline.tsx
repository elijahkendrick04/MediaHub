import type { AccentDecoration } from "../registry";

// A short accent rule under the headline band, raked a few degrees off
// horizontal — the energetic cousin of the built-in "underline". Accent role
// only, margin-safe; the fade-in is driven entirely by the supplied
// `opacity` (deterministic, no own clock). Geometry mirrors the still
// engine's `_accent_decoration_html("diagonal_underline", …)` 1:1.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        top: height * 0.82,
        width: m * 0.22,
        height: Math.max(4, m * 0.004),
        background: roles.accent,
        opacity,
        transform: "rotate(-6deg)",
        transformOrigin: "left center",
        pointerEvents: "none",
      }}
    />
  );
};

export default { name: "diagonal_underline", decoration };
