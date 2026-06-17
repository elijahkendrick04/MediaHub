/**
 * Motion scene for the `vertical_stat_tower` still archetype (G1.1).
 *
 * Mirrors the still: a header (kicker + name) over full-width stacked tiers —
 * EVENT (surface) → RESULT (dominant accent, tallest) → THE MOVE (optional).
 * The motion idea is CONSTRUCTION: the tiers build in, each from a different
 * direction, with the accent result tier as the keystone that snaps last.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { MetaFooter, KineticWords, ClubLogo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const pad = Math.round(72 * ts);
  // Event tier slides in from the right; move tier fades up — distinct
  // directions from the result tier's scale-in (guardrail: vary entrances).
  const eventIn = interpolate(frame, [9, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const moveIn = interpolate(frame, [20, 32], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.sin),
  });
  // Ambient: the keystone result tier breathes once readable.
  const breathe = 1 + 0.012 * Math.sin((frame / fps) * 2.0) * (frame > fps ? 1 : 0);

  const tier = (bg: string, fg: string): React.CSSProperties => ({
    borderRadius: Math.round(14 * ts),
    background: bg,
    color: fg,
    padding: `${Math.round(24 * ts)}px ${Math.round(32 * ts)}px`,
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
  });
  const label = (c: string): React.CSSProperties => ({
    fontSize: Math.round(16 * ts),
    fontWeight: 800,
    letterSpacing: "0.24em",
    textTransform: "uppercase",
    color: c,
    marginBottom: Math.round(8 * ts),
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        padding: `${Math.round(80 * ts)}px ${pad}px ${Math.round(150 * ts)}px`,
        gap: Math.round(16 * ts),
      }}
    >
      {/* header */}
      <div style={{ flex: "0 0 auto" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: Math.round(14 * ts),
            color: roles.accent,
            fontSize: Math.round(22 * ts),
            fontWeight: 800,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            opacity: anim.chipOpacity,
            transform: `translateX(${(1 - anim.chipOpacity) * -24}px)`,
          }}
        >
          <span style={{ width: Math.round(44 * ts), height: Math.round(7 * ts), borderRadius: 4, background: roles.accent }} />
          {ctx.label || "STRONG SWIM"}
        </div>
        <div style={{ marginTop: Math.round(16 * ts), fontSize: Math.round(38 * ts), fontWeight: 700, textTransform: "uppercase", color: roles.accent, opacity: anim.secondaryOpacity }}>
          {ctx.firstName}
        </div>
        <KineticWords
          text={ctx.surnameText}
          ctx={ctx}
          style={{
            fontSize: fitLine(ctx.surnameText, Math.round(104 * ts), width - pad * 2),
            fontWeight: 900,
            lineHeight: 0.88,
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.5}px)`,
          }}
        />
      </div>

      {/* stacked tiers */}
      <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: Math.round(16 * ts), minHeight: 0 }}>
        <div
          style={{
            ...tier(roles.surface, roles.onGround),
            flex: "0 0 auto",
            opacity: eventIn,
            transform: `translateX(${(1 - eventIn) * 60}px)`,
          }}
        >
          <div style={label(roles.accent)}>EVENT</div>
          <div style={{ fontSize: Math.round(40 * ts), fontWeight: 700, lineHeight: 1.02, textTransform: "uppercase" }}>{ctx.event}</div>
        </div>

        <div
          style={{
            ...tier(roles.accent, roles.ground),
            flex: "1 1 auto",
            minHeight: 0,
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale * breathe})`,
          }}
        >
          <div style={label(roles.ground)}>RESULT</div>
          <div
            style={{
              fontSize: fitLine(ctx.result, Math.round(180 * ts), width - pad * 2 - 64),
              fontWeight: 900,
              lineHeight: 0.9,
              letterSpacing: "-0.02em",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {ctx.result}
          </div>
        </div>

        {ctx.card.heroStat ? (
          <div
            style={{
              ...tier(roles.surface, roles.onGround),
              flex: "0 0 auto",
              opacity: moveIn,
              transform: `translateY(${(1 - moveIn) * 30}px)`,
            }}
          >
            <div style={label(roles.accent)}>THE MOVE</div>
            <div style={{ fontSize: Math.round(32 * ts), fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{ctx.card.heroStat}</div>
          </div>
        ) : null}
      </div>

      <ClubLogo ctx={ctx} size={96} />
      <MetaFooter ctx={ctx} />
    </div>
  );
};

export default { archetype: "vertical_stat_tower", Scene };
