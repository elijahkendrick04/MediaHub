/**
 * Motion scene for the `timeline_progression` still archetype (G1.1).
 *
 * Mirrors the still: an accent spine down the left margin threaded through
 * milestone nodes — kicker → athlete → the dominant accent RESULT disc →
 * context. The motion idea is the JOURNEY: the spine draws downward, then each
 * node lights up in sequence top→bottom, with the result disc as the peak beat.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Footer, KineticWords, Logo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const railLeft = Math.round(120 * ts);
  const colLeft = railLeft + Math.round(70 * ts);

  // The spine draws downward (scaleY) — the connective gesture, eased long.
  const railGrow = interpolate(frame, [4, 4 + 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // A node lights up on a staggered schedule (importance order, overlapped).
  const nodeAt = (order: number) =>
    interpolate(
      frame,
      [7 + order * 5, 7 + order * 5 + 11],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.exp) },
    );
  // Ambient: the result dot breathes through the readable phase.
  const breathe =
    1 + 0.05 * Math.sin((frame / fps) * 2.2) * (frame > fps ? 1 : 0);

  const surnamePx = fitLine(ctx.surnameText, Math.round(96 * ts), width * 0.6);

  const Dot: React.FC<{ top: number; big?: boolean; t: number }> = ({ top, big, t }) => {
    const d = Math.round((big ? 40 : 26) * ts);
    return (
      <div
        style={{
          position: "absolute",
          left: railLeft - d / 2 + Math.round(3 * ts),
          top,
          width: d,
          height: d,
          borderRadius: "50%",
          background: big ? roles.accent : roles.ground,
          border: `${Math.round(6 * ts)}px solid ${roles.accent}`,
          transform: `scale(${(big ? breathe : 1) * (0.4 + 0.6 * t)})`,
          opacity: t,
        }}
      />
    );
  };

  return (
    <>
      {/* the connective spine */}
      <div
        style={{
          position: "absolute",
          left: railLeft,
          top: height * 0.13,
          bottom: height * 0.16,
          width: Math.round(6 * ts),
          borderRadius: 3,
          background: roles.accent,
          opacity: 0.55,
          transform: `scaleY(${railGrow})`,
          transformOrigin: "top center",
        }}
      />

      {/* node 1 — kicker */}
      <Dot top={height * 0.16} t={nodeAt(0)} />
      <div
        style={{
          position: "absolute",
          left: colLeft,
          top: height * 0.15,
          right: 80,
          fontSize: Math.round(28 * ts),
          fontWeight: 800,
          letterSpacing: "0.2em",
          textTransform: "uppercase",
          color: roles.accent,
          opacity: nodeAt(0),
          transform: `translateX(${(1 - nodeAt(0)) * -30}px)`,
        }}
      >
        {ctx.label || "STRONG SWIM"}
      </div>

      {/* node 2 — athlete */}
      <Dot top={height * 0.3} t={nodeAt(1)} />
      <div style={{ position: "absolute", left: colLeft, top: height * 0.27, right: 80 }}>
        <div
          style={{
            fontSize: Math.round(40 * ts),
            fontWeight: 700,
            textTransform: "uppercase",
            color: roles.accent,
            opacity: anim.secondaryOpacity,
          }}
        >
          {ctx.firstName}
        </div>
        <KineticWords
          text={ctx.surnameText}
          anim={anim}
          style={{
            marginTop: Math.round(4 * ts),
            fontSize: surnamePx,
            fontWeight: 900,
            lineHeight: 0.9,
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.5}px)`,
          }}
        />
      </div>

      {/* node 3 — the RESULT disc (peak beat) */}
      <Dot top={height * 0.52} big t={nodeAt(2)} />
      <div
        style={{
          position: "absolute",
          left: colLeft,
          top: height * 0.5,
          right: 80,
          background: roles.accent,
          color: roles.ground,
          borderRadius: Math.round(16 * ts),
          padding: `${Math.round(22 * ts)}px ${Math.round(30 * ts)}px`,
          opacity: anim.resultOpacity,
          transform: `scale(${anim.resultScale})`,
          transformOrigin: "left center",
        }}
      >
        <div style={{ fontSize: Math.round(17 * ts), fontWeight: 800, letterSpacing: "0.3em", opacity: 0.8 }}>
          RESULT
        </div>
        <div
          style={{
            marginTop: Math.round(6 * ts),
            fontSize: Math.round(96 * ts),
            fontWeight: 900,
            lineHeight: 0.9,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {ctx.result}
        </div>
        <div style={{ marginTop: Math.round(8 * ts), fontSize: Math.round(26 * ts), fontWeight: 600, textTransform: "uppercase" }}>
          {ctx.event}
        </div>
      </div>

      {/* node 4 — context */}
      <Dot top={height * 0.74} t={nodeAt(3)} />
      <div
        style={{
          position: "absolute",
          left: colLeft,
          top: height * 0.72,
          right: 80,
          fontSize: Math.round(27 * ts),
          fontWeight: 600,
          color: roles.onGround,
          opacity: nodeAt(3) * 0.9,
          transform: `translateY(${(1 - nodeAt(3)) * 24}px)`,
        }}
      >
        {ctx.meet}
        {ctx.card.heroStat ? (
          <div style={{ marginTop: Math.round(8 * ts), color: roles.accent, fontWeight: 800, fontSize: Math.round(23 * ts) }}>
            {ctx.card.heroStat}
          </div>
        ) : null}
      </div>

      <Logo ctx={ctx} size={104} />
      <Footer ctx={ctx} />
    </>
  );
};

export default { archetype: "timeline_progression", Scene };
