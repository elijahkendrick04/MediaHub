/**
 * Motion scene for the `ribbon_banner` still archetype (G1.1).
 *
 * Mirrors the still: an award ribbon (chevron-ended sash + hanging tails)
 * carries the achievement label, with the name and result beneath. The motion
 * idea is the AWARD being pinned on: the ribbon unfurls horizontally, the tails
 * drop, then the honour (name + result) settles below it.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { MetaFooter, ClubLogo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();

  // Ribbon unfurls horizontally from the centre.
  const unfurl = interpolate(frame, [5, 5 + 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  // Tails drop after the ribbon is open.
  const tails = interpolate(frame, [16, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Label fades up on the open ribbon.
  const labelIn = interpolate(frame, [14, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.sin),
  });

  const tail: React.CSSProperties = {
    position: "absolute",
    top: "58%",
    width: Math.round(56 * ts),
    height: Math.round(84 * ts),
    background: roles.accent,
    opacity: 0.85 * tails,
    clipPath: "polygon(0 0, 100% 0, 100% 100%, 50% 74%, 0 100%)",
    transform: `translateY(${(1 - tails) * -30}px)`,
  };

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        textAlign: "center",
        padding: `${Math.round(110 * ts)}px ${Math.round(80 * ts)}px ${Math.round(150 * ts)}px`,
      }}
    >
      {/* ribbon assembly */}
      <div style={{ position: "relative", width: "100%", marginBottom: Math.round(56 * ts), flex: "0 0 auto" }}>
        <div style={{ ...tail, left: `calc(50% - ${Math.round(96 * ts)}px)` }} />
        <div style={{ ...tail, right: `calc(50% - ${Math.round(96 * ts)}px)` }} />
        <div
          style={{
            position: "relative",
            zIndex: 2,
            display: "inline-block",
            maxWidth: "88%",
            background: roles.accent,
            color: roles.ground,
            padding: `${Math.round(22 * ts)}px ${Math.round(72 * ts)}px`,
            clipPath: "polygon(0 0, 100% 0, 93% 50%, 100% 100%, 0 100%, 7% 50%)",
            fontSize: Math.round(48 * ts),
            fontWeight: 900,
            lineHeight: 0.94,
            textTransform: "uppercase",
            transform: `scaleX(${0.2 + 0.8 * unfurl})`,
          }}
        >
          <span style={{ display: "inline-block", opacity: labelIn }}>{ctx.label || "STRONG SWIM"}</span>
        </div>
      </div>

      {/* name */}
      <div style={{ fontSize: Math.round(34 * ts), fontWeight: 700, textTransform: "uppercase", color: roles.accent, opacity: anim.secondaryOpacity }}>
        {ctx.firstName}
      </div>
      <div
        style={{
          fontSize: fitLine(ctx.surnameText, Math.round(88 * ts), width - 200),
          fontWeight: 900,
          lineHeight: 0.88,
          letterSpacing: "-0.01em",
          textTransform: "uppercase",
          color: roles.onGround,
          opacity: anim.heroOpacity,
          transform: `translateY(${anim.heroY * 0.4}px)`,
        }}
      >
        {ctx.surnameText}
      </div>

      {/* result */}
      <div style={{ marginTop: Math.round(36 * ts), fontSize: Math.round(17 * ts), fontWeight: 800, letterSpacing: "0.3em", textTransform: "uppercase", color: roles.accent }}>
        RESULT
      </div>
      <div
        style={{
          fontSize: fitLine(ctx.result, Math.round(96 * ts), width - 220),
          fontWeight: 900,
          lineHeight: 0.9,
          letterSpacing: "-0.02em",
          color: roles.onGround,
          fontVariantNumeric: "tabular-nums",
          opacity: anim.resultOpacity,
          transform: `scale(${anim.resultScale})`,
        }}
      >
        {ctx.result}
      </div>
      <div style={{ marginTop: Math.round(20 * ts), fontSize: Math.round(26 * ts), fontWeight: 600, textTransform: "uppercase", color: roles.onGround, opacity: anim.secondaryOpacity * 0.9 }}>
        {ctx.event}
      </div>

      <ClubLogo ctx={ctx} size={88} />
      <MetaFooter ctx={ctx} />
    </div>
  );
};

export default { archetype: "ribbon_banner", Scene };
