/**
 * Motion scene for the `full_height_portrait_split` still archetype (G1.1).
 *
 * Mirrors the still: a full-height portrait on the left ~56%, a full-height info
 * column on the right ~44%, an accent seam between them. The motion idea is a
 * REVEAL: the portrait holds with a slow Ken Burns push (anchored on the
 * saliency focus), the seam draws down, and the column copy steps in from the
 * right — name, event, then the result.
 */
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Footer, KineticWords, Logo, fitLine, withAlpha } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const photoW = Math.round(width * 0.56);
  const colLeft = photoW + Math.round(60 * ts);

  // Seam draws downward.
  const seam = interpolate(frame, [5, 5 + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Column copy steps in from the right.
  const colIn = interpolate(frame, [8, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  // Ambient: slow Ken Burns push on the portrait.
  const kb = 1.0 + 0.04 * interpolate(frame, [0, fps * 5], [0, 1], {
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.sin),
  });

  const colW = width - colLeft - Math.round(60 * ts);
  const surnamePx = fitLine(ctx.surnameText, Math.round(78 * ts), colW);

  return (
    <>
      {/* portrait panel */}
      <div style={{ position: "absolute", left: 0, top: 0, width: photoW, height, overflow: "hidden", background: roles.surface }}>
        {/* no-photo grace: faint surname watermark */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: Math.round(200 * ts),
            fontWeight: 900,
            lineHeight: 0.8,
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: 0.1,
            overflow: "hidden",
            textAlign: "center",
          }}
        >
          {ctx.surnameText}
        </div>
        {card.photoSrc ? (
          <img
            src={card.photoSrc}
            alt=""
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: card.photoPos || "center 28%",
              transform: `scale(${kb})`,
            }}
          />
        ) : null}
        {/* brand-tinted seam scrim */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `linear-gradient(90deg, ${withAlpha(roles.ground, 0)} 60%, ${withAlpha(roles.ground, 0.55)} 100%)`,
          }}
        />
      </div>

      {/* accent seam */}
      <div
        style={{
          position: "absolute",
          left: photoW - Math.round(8 * ts),
          top: 0,
          width: Math.round(8 * ts),
          height,
          background: roles.accent,
          transform: `scaleY(${seam})`,
          transformOrigin: "top center",
        }}
      />

      {/* info column */}
      <div
        style={{
          position: "absolute",
          left: colLeft,
          top: Math.round(92 * ts),
          width: colW,
          opacity: colIn,
          transform: `translateX(${(1 - colIn) * 50}px)`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: Math.round(12 * ts), color: roles.accent, fontSize: Math.round(21 * ts), fontWeight: 800, letterSpacing: "0.2em", textTransform: "uppercase", marginBottom: Math.round(26 * ts) }}>
          <span style={{ width: Math.round(38 * ts), height: Math.round(6 * ts), borderRadius: 4, background: roles.accent }} />
          {ctx.label || "STRONG SWIM"}
        </div>
        <div style={{ fontSize: Math.round(34 * ts), fontWeight: 700, textTransform: "uppercase", color: roles.accent }}>{ctx.firstName}</div>
        <KineticWords
          text={ctx.surnameText}
          anim={anim}
          style={{
            fontSize: surnamePx,
            fontWeight: 900,
            lineHeight: 0.88,
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.4}px)`,
          }}
        />
        <div style={{ marginTop: Math.round(26 * ts), paddingTop: Math.round(20 * ts), borderTop: `${Math.round(4 * ts)}px solid ${roles.accent}`, fontSize: Math.round(26 * ts), fontWeight: 600, textTransform: "uppercase", color: roles.onGround, opacity: anim.secondaryOpacity }}>
          {ctx.event}
        </div>
        <div style={{ marginTop: Math.round(36 * ts), fontSize: Math.round(16 * ts), fontWeight: 800, letterSpacing: "0.28em", textTransform: "uppercase", color: roles.accent }}>RESULT</div>
        <div
          style={{
            fontSize: fitLine(ctx.result, Math.round(72 * ts), colW),
            fontWeight: 900,
            lineHeight: 0.9,
            letterSpacing: "-0.02em",
            color: roles.onGround,
            fontVariantNumeric: "tabular-nums",
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale})`,
            transformOrigin: "left center",
          }}
        >
          {ctx.result}
        </div>
        {ctx.card.heroStat ? (
          <div style={{ marginTop: Math.round(14 * ts), fontSize: Math.round(23 * ts), fontWeight: 700, color: roles.accent, opacity: anim.resultOpacity }}>
            {ctx.card.heroStat}
          </div>
        ) : null}
      </div>

      <Logo ctx={ctx} size={88} corner="tr" />
      <Footer ctx={ctx} />
    </>
  );
};

export default { archetype: "full_height_portrait_split", Scene };
