import type { AccentDecoration } from "../registry";

// B6 (Canva gap analysis) — the frosted-glass margin pill, the motion twin of
// the still engine's glass_chip accent (render._accent_decoration_html) and the
// v2 modules' --mh-glass-* glassing. A translucent, brand-tinted panel the
// viewer sees the photo through: the resolved surface role at ~0.30 alpha
// (appended as an 8-digit hex alpha, 0x4D ≈ 0.30) under a backdrop blur+saturate,
// with a light glass edge and the elevation-3 shadow. Held frame in the still,
// animated only by the shared accent opacity so it stays in lock-step with the
// approved still. Registry contract: the exported name IS the brief token.
const decoration: AccentDecoration = (roles, opacity, width, height) => {
  const m = Math.min(width, height);
  const pillW = m * 0.2;
  const pillH = Math.max(24, m * 0.055);
  // roles.surface is the resolved 6-digit brand hex; "4D" is the 0x4D/255≈0.30
  // alpha byte, giving the same translucent tint the still emits from
  // rgba(--mh-surface-rgb, 0.30).
  const fill = `${roles.surface}4D`;
  return (
    <div
      style={{
        position: "absolute",
        left: width * 0.06,
        bottom: height * 0.12,
        width: pillW,
        height: pillH,
        borderRadius: pillH / 2,
        background: fill,
        WebkitBackdropFilter: "blur(12px) saturate(140%)",
        backdropFilter: "blur(12px) saturate(140%)",
        border: "1px solid rgba(255,255,255,0.16)",
        boxShadow: "0 6px 20px rgba(10,12,16,0.26)",
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export default { name: "glass_chip", decoration };
