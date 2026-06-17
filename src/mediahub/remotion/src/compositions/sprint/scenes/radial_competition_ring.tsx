/**
 * Motion scene for the `radial_competition_ring` still archetype (G1.1).
 *
 * Mirrors the still: the result sits at the centre of a concentric dial — a
 * tick ring + a thick accent ring + a punched-out core. The motion idea is a
 * GAUGE coming alive: the rings scale in, the tick ring keeps a slow continuous
 * rotation (the ambient beat), and the centre result is the resolve.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { MetaFooter, ClubLogo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const dial = Math.round(Math.min(width * 0.86, height * 0.42, 560));
  const cx = width / 2;
  const cy = height * 0.42;

  // Rings scale in from the centre, decisive snap.
  const ringIn = interpolate(frame, [5, 5 + 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  // Ambient: the tick ring keeps a slow continuous rotation (frame-pure).
  const spin = (frame / fps) * 9;
  // Kicker pill drops from above on the chip channel.
  const kick = interpolate(frame, [3, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const resultPx = fitLine(ctx.result, Math.round(dial * 0.26), dial * 0.62);
  const ring = (d: number): React.CSSProperties => ({
    position: "absolute",
    left: cx - d / 2,
    top: cy - d / 2,
    width: d,
    height: d,
    borderRadius: "50%",
  });

  return (
    <>
      {/* kicker pill */}
      <div
        style={{
          position: "absolute",
          top: height * 0.16,
          left: "50%",
          transform: `translateX(-50%) translateY(${(1 - kick) * -26}px)`,
          padding: `${Math.round(12 * ts)}px ${Math.round(26 * ts)}px`,
          borderRadius: 999,
          background: roles.accent,
          color: roles.ground,
          fontSize: Math.round(24 * ts),
          fontWeight: 800,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          opacity: kick,
          whiteSpace: "nowrap",
          maxWidth: width - 160,
          overflow: "hidden",
        }}
      >
        {ctx.label || "STRONG SWIM"}
      </div>

      {/* tick ring (ambient rotation) */}
      <div
        style={{
          ...ring(dial),
          background: `repeating-conic-gradient(${roles.accent} 0deg 1.3deg, transparent 1.3deg 15deg)`,
          opacity: 0.85 * ringIn,
          transform: `scale(${0.6 + 0.4 * ringIn}) rotate(${spin}deg)`,
        }}
      />
      {/* mask the tick ring down to a thin band */}
      <div style={{ ...ring(dial - Math.round(48 * ts)), background: roles.ground, opacity: ringIn }} />
      {/* the main accent ring */}
      <div
        style={{
          ...ring(dial - Math.round(88 * ts)),
          border: `${Math.round(16 * ts)}px solid ${roles.accent}`,
          background: roles.ground,
          transform: `scale(${0.7 + 0.3 * ringIn})`,
          opacity: ringIn,
        }}
      />

      {/* centre result */}
      <div
        style={{
          position: "absolute",
          left: cx,
          top: cy,
          transform: `translate(-50%,-50%) scale(${anim.resultScale})`,
          textAlign: "center",
          opacity: anim.resultOpacity,
          width: dial * 0.66,
        }}
      >
        <div style={{ fontSize: Math.round(18 * ts), fontWeight: 800, letterSpacing: "0.32em", color: roles.onGround, opacity: 0.7 }}>
          RESULT
        </div>
        <div
          style={{
            marginTop: Math.round(10 * ts),
            fontSize: resultPx,
            fontWeight: 900,
            lineHeight: 0.9,
            letterSpacing: "-0.02em",
            color: roles.accent,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {ctx.result}
        </div>
      </div>

      {/* name + event below the dial */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: cy + dial / 2 + Math.round(40 * ts),
          textAlign: "center",
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY * 0.5}px)`,
        }}
      >
        <div style={{ fontSize: Math.round(34 * ts), fontWeight: 700, textTransform: "uppercase", color: roles.accent }}>
          {ctx.firstName}
        </div>
        <div
          style={{
            fontSize: fitLine(ctx.surnameText, Math.round(92 * ts), width - 200),
            fontWeight: 900,
            lineHeight: 0.92,
            textTransform: "uppercase",
            color: roles.onGround,
          }}
        >
          {ctx.surnameText}
        </div>
        <div style={{ marginTop: Math.round(16 * ts), fontSize: Math.round(27 * ts), fontWeight: 600, textTransform: "uppercase", color: roles.onGround, opacity: anim.secondaryOpacity * 0.9 }}>
          {ctx.event}
        </div>
      </div>

      <ClubLogo ctx={ctx} size={96} />
      <MetaFooter ctx={ctx} />
    </>
  );
};

export default { archetype: "radial_competition_ring", Scene };
