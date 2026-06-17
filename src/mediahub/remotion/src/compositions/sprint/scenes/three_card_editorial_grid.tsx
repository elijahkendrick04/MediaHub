/**
 * Motion scene for the `three_card_editorial_grid` still archetype (G1.1).
 *
 * Mirrors the still: a masthead row, three inset editorial cards (WHO / RESULT /
 * CONTEXT), a foot row. The motion idea is DEALING the cards in — each enters
 * from a different direction, and the lifted accent RESULT card scales in last
 * as the keeper, so the eye lands on the figure.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { Footer, Logo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();

  const pad = Math.round(64 * ts);
  // Masthead wipes in from the left.
  const mast = interpolate(frame, [4, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Side cards deal in from opposite directions; centre uses the result channel.
  const whoIn = interpolate(frame, [8, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const ctxIn = interpolate(frame, [12, 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.sin),
  });

  const cardW = (width - pad * 2 - Math.round(48 * ts)) / 3;
  const card = (bg: string, fg: string): React.CSSProperties => ({
    flex: "1 1 0",
    minWidth: 0,
    background: bg,
    color: fg,
    borderRadius: Math.round(18 * ts),
    padding: `${Math.round(32 * ts)}px ${Math.round(26 * ts)}px`,
    display: "flex",
    flexDirection: "column",
  });
  const lab = (c: string): React.CSSProperties => ({
    fontSize: Math.round(15 * ts),
    fontWeight: 800,
    letterSpacing: "0.22em",
    textTransform: "uppercase",
    color: c,
    marginBottom: Math.round(18 * ts),
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        padding: `${Math.round(78 * ts)}px ${pad}px ${Math.round(150 * ts)}px`,
        gap: Math.round(30 * ts),
      }}
    >
      {/* masthead */}
      <div
        style={{
          flex: "0 0 auto",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 24,
          paddingBottom: Math.round(22 * ts),
          borderBottom: `${Math.round(5 * ts)}px solid ${roles.accent}`,
          opacity: mast,
          transform: `translateX(${(1 - mast) * -40}px)`,
        }}
      >
        <div style={{ fontSize: Math.round(56 * ts), fontWeight: 900, lineHeight: 0.9, textTransform: "uppercase", color: roles.onGround }}>
          {ctx.label || "STRONG SWIM"}
        </div>
        <div style={{ fontSize: Math.round(22 * ts), fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase", color: roles.accent, textAlign: "right" }}>
          {ctx.meet}
        </div>
      </div>

      {/* three cards */}
      <div style={{ flex: "1 1 auto", display: "flex", gap: Math.round(24 * ts), minHeight: 0 }}>
        <div style={{ ...card(roles.surface, roles.onGround), opacity: whoIn, transform: `translateX(${(1 - whoIn) * -50}px)` }}>
          <div style={lab(roles.accent)}>ATHLETE</div>
          <div style={{ fontSize: Math.round(30 * ts), fontWeight: 700, textTransform: "uppercase" }}>{ctx.firstName}</div>
          <div
            style={{
              fontSize: fitLine(ctx.surnameText, Math.round(56 * ts), cardW - 56),
              fontWeight: 900,
              lineHeight: 0.9,
              textTransform: "uppercase",
            }}
          >
            {ctx.surnameText}
          </div>
        </div>

        <div
          style={{
            ...card(roles.accent, roles.ground),
            justifyContent: "center",
            opacity: anim.resultOpacity,
            transform: `translateY(${-14 * ts}px) scale(${anim.resultScale})`,
          }}
        >
          <div style={lab(roles.ground)}>RESULT</div>
          <div
            style={{
              fontSize: fitLine(ctx.result, Math.round(76 * ts), cardW - 56),
              fontWeight: 900,
              lineHeight: 0.9,
              letterSpacing: "-0.02em",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {ctx.result}
          </div>
        </div>

        <div style={{ ...card(roles.surface, roles.onGround), opacity: ctxIn, transform: `translateX(${(1 - ctxIn) * 50}px)` }}>
          <div style={lab(roles.accent)}>EVENT</div>
          <div style={{ fontSize: Math.round(24 * ts), fontWeight: 600, lineHeight: 1.16, textTransform: "uppercase" }}>{ctx.event}</div>
          {ctx.card.heroStat ? (
            <div style={{ marginTop: "auto", paddingTop: Math.round(18 * ts) }}>
              <div style={{ ...lab(roles.accent), marginBottom: Math.round(5 * ts), fontSize: Math.round(13 * ts) }}>HIGHLIGHT</div>
              <div style={{ fontSize: Math.round(22 * ts), fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{ctx.card.heroStat}</div>
            </div>
          ) : null}
        </div>
      </div>

      <Logo ctx={ctx} size={92} />
      <Footer ctx={ctx} />
    </div>
  );
};

export default { archetype: "three_card_editorial_grid", Scene };
