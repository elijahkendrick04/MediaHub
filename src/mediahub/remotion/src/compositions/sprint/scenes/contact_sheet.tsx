/**
 * Motion scene for the `contact_sheet` still archetype (G1.1).
 *
 * Mirrors the still: sprocket strips bracket a grid of six frames of the same
 * real shot (re-cropped per frame), with one accent-ringed "keeper" carrying the
 * result, over a caption plate. The motion idea is the sheet DEVELOPING: frames
 * blink in across the grid, the keeper snaps to its ring last, and the caption
 * settles. With no photo the frames are clean brand cells (honest — no invented
 * imagery).
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { MetaFooter, ClubLogo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const FRAME_POS = ["center 18%", "left 30%", "right 26%", "center 50%", "", "right 60%"];
const KEEPER = 4; // 0-indexed → frame "05"

const Scene: SceneComponent = ({ ctx }) => {
  const { card, roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();

  const pad = Math.round(64 * ts);
  // Sprocket strips slide in from opposite edges.
  const sprTop = interpolate(frame, [3, 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  // Caption plate rises.
  const cap = interpolate(frame, [18, 32], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.sin) });
  // Each frame blinks in on a staggered schedule.
  const frameAt = (i: number) =>
    interpolate(frame, [6 + i * 3, 6 + i * 3 + 9], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });

  const sprocket: React.CSSProperties = {
    flex: "0 0 auto",
    height: Math.round(22 * ts),
    borderRadius: 4,
    background: `repeating-linear-gradient(90deg, ${roles.surface} 0 18px, transparent 18px 44px)`,
    opacity: 0.7,
  };

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        padding: `${Math.round(72 * ts)}px ${pad}px ${Math.round(140 * ts)}px`,
        gap: Math.round(16 * ts),
      }}
    >
      <div style={{ flex: "0 0 auto", display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 24, opacity: sprTop }}>
        <span style={{ fontSize: Math.round(21 * ts), fontWeight: 700, letterSpacing: "0.16em", textTransform: "uppercase", color: roles.accent }}>Contact Sheet</span>
        <span style={{ fontSize: Math.round(17 * ts), fontWeight: 600, letterSpacing: "0.1em", color: roles.onGround, opacity: 0.7 }}>{ctx.meet}</span>
      </div>

      <div style={{ ...sprocket, transform: `translateX(${(1 - sprTop) * -40}px)` }} />

      {/* frame grid */}
      <div style={{ flex: "1 1 auto", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridAutoRows: "1fr", gap: Math.round(14 * ts), minHeight: 0 }}>
        {FRAME_POS.map((pos, i) => {
          const isKeeper = i === KEEPER;
          const t = isKeeper ? anim.resultOpacity : frameAt(i);
          const sc = isKeeper ? anim.resultScale : 0.92 + 0.08 * t;
          return (
            <div
              key={i}
              style={{
                position: "relative",
                overflow: "hidden",
                borderRadius: Math.round(6 * ts),
                background: roles.surface,
                border: isKeeper ? `${Math.round(5 * ts)}px solid ${roles.accent}` : `2px solid ${roles.surface}`,
                opacity: t,
                transform: `scale(${sc})`,
              }}
            >
              <span style={{ position: "absolute", zIndex: 3, top: 8, left: 8, fontSize: Math.round(14 * ts), fontWeight: 700, color: roles.onGround, opacity: 0.78 }}>
                {String(i + 1).padStart(2, "0")}
              </span>
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
                    objectPosition: (isKeeper ? card.photoPos : pos) || "center 28%",
                  }}
                />
              ) : null}
              {isKeeper ? (
                <>
                  <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, transparent 40%, ${roles.ground})`, opacity: 0.82 }} />
                  <div style={{ position: "absolute", zIndex: 3, left: 12, right: 12, bottom: 12 }}>
                    <div style={{ fontSize: Math.round(13 * ts), fontWeight: 800, letterSpacing: "0.22em", textTransform: "uppercase", color: roles.accent }}>RESULT</div>
                    <div style={{ fontSize: fitLine(ctx.result, Math.round(40 * ts), width / 3 - 40), fontWeight: 900, lineHeight: 0.9, color: roles.onGround, fontVariantNumeric: "tabular-nums" }}>
                      {ctx.result}
                    </div>
                  </div>
                </>
              ) : null}
            </div>
          );
        })}
      </div>

      <div style={{ ...sprocket, transform: `translateX(${(1 - sprTop) * 40}px)` }} />

      {/* caption plate */}
      <div
        style={{
          flex: "0 0 auto",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 28,
          background: roles.surface,
          color: roles.onGround,
          borderRadius: Math.round(14 * ts),
          padding: `${Math.round(24 * ts)}px ${Math.round(30 * ts)}px`,
          opacity: cap,
          transform: `translateY(${(1 - cap) * 30}px)`,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: Math.round(16 * ts), fontWeight: 700, letterSpacing: "0.2em", textTransform: "uppercase", color: roles.accent, marginBottom: Math.round(8 * ts) }}>
            {ctx.label || "STRONG SWIM"}
          </div>
          <div style={{ fontSize: Math.round(28 * ts), fontWeight: 700, textTransform: "uppercase" }}>{ctx.firstName}</div>
          <div style={{ fontSize: fitLine(ctx.surnameText, Math.round(64 * ts), width * 0.6), fontWeight: 900, lineHeight: 0.9, textTransform: "uppercase" }}>
            {ctx.surnameText}
          </div>
          <div style={{ marginTop: Math.round(10 * ts), fontSize: Math.round(22 * ts), fontWeight: 600, textTransform: "uppercase", opacity: 0.9 }}>{ctx.event}</div>
        </div>
      </div>

      <ClubLogo ctx={ctx} size={84} />
      <MetaFooter ctx={ctx} />
    </div>
  );
};

export default { archetype: "contact_sheet", Scene };
