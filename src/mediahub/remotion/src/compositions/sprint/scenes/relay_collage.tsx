// Motion scene for the `relay_collage` still archetype (roadmap G1.2).
//
// Auto-discovered by sprint/registry.ts (require.context) and selected whenever
// a card's archetype is `relay_collage`, so the squad/relay video reads like its
// still: a multi-subject STAGE of panels standing on one baseline, a crossing
// NAME BAND, and a DATA STRIP below. The still composites real cutouts; the reel
// carries one photo per card, so the lineup is evoked with brand-tinted panels
// (the card's photo filling the hero panel) — a deliberate, distinct scene
// rather than the single-hero default. All colour comes from the resolved
// `roles` the still painted; entrance rides the shared `anim` channels.
import React from "react";
import { interpolate } from "remotion";
import type { SceneComponent } from "../registry";

const PANELS = 4; // a relay quartet — the squad lineup

const Scene: SceneComponent = ({ ctx }) => {
  const { card, roles, anim, width, height, ts, fontStack, frame, fps } = ctx;

  const stageH = height * 0.58;
  const baselineFromTop = stageH * 0.97;
  const centre = (PANELS - 1) / 2;
  const spread = 0.74;
  const slots = Array.from({ length: PANELS }, (_, i) =>
    0.5 - spread / 2 + (spread * i) / (PANELS - 1),
  );
  const heroIndex = Math.round(centre);

  return (
    <>
      {/* Studio backdrop: a soft centre glow on the brand ground. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(120% 82% at 50% 16%, ${roles.onGround}12 0%, ${roles.ground}00 60%)`,
        }}
      />

      {/* The squad — balanced panels standing on a shared baseline. */}
      {slots.map((cx, i) => {
        const dist = Math.abs(i - centre);
        const panelH = stageH * (0.84 - dist * 0.07);
        const panelW = width * 0.165;
        const cascade = interpolate(
          frame,
          [fps * (0.2 + 0.12 * i), fps * (0.55 + 0.12 * i)],
          [0, 1],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        );
        const stagger = card.motionIntent === "static" ? 1 : cascade;
        const isHero = i === heroIndex && !!card.photoSrc;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: cx * width,
              top: baselineFromTop - panelH,
              width: panelW,
              height: panelH,
              transform: `translateX(-50%) translateY(${(1 - stagger) * 44}px)`,
              opacity: stagger,
              background: isHero
                ? roles.surface
                : i % 2 === 0
                  ? roles.accent
                  : roles.surface,
              borderRadius: 12,
              overflow: "hidden",
              boxShadow: "0 18px 42px rgba(0,0,0,0.34)",
            }}
          >
            {isHero && (
              <img
                src={card.photoSrc}
                alt=""
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  objectPosition: card.photoPos || "center 28%",
                  transform: `scale(${anim.photoScale})`,
                }}
              />
            )}
          </div>
        );
      })}

      {/* Floor shadow under the lineup. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: baselineFromTop,
          height: stageH * 0.16,
          background: `linear-gradient(0deg, ${roles.ground}66 0%, ${roles.ground}00 100%)`,
        }}
      />

      {/* Label chip, top-left. */}
      <div
        style={{
          position: "absolute",
          top: Math.round(120 * ts),
          left: 80,
          padding: `${Math.round(13 * ts)}px ${Math.round(26 * ts)}px`,
          background: roles.accent,
          color: roles.ground,
          fontSize: Math.round(34 * ts),
          fontWeight: 800,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          borderRadius: 6,
          opacity: anim.chipOpacity,
          whiteSpace: "nowrap",
          maxWidth: width - 160,
          overflow: "hidden",
        }}
      >
        {ctx.label || "STRONG SWIM"}
      </div>

      {/* Crossing name band at the stage foot. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: stageH - height * 0.065,
          padding: `${Math.round(18 * ts)}px 80px ${Math.round(22 * ts)}px`,
          background: roles.accent,
          color: roles.ground,
          opacity: anim.chipOpacity,
          transform: `translateY(${anim.heroY * 0.4}px)`,
        }}
      >
        {ctx.firstName && (
          <div
            style={{
              fontSize: Math.round(30 * ts),
              fontWeight: 700,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              fontFamily: fontStack,
            }}
          >
            {ctx.firstName}
          </div>
        )}
        <div
          style={{
            fontSize: Math.round(108 * ts),
            fontWeight: 900,
            lineHeight: 0.9,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
          }}
        >
          {ctx.surnameText}
        </div>
      </div>

      {/* Data strip: event + result, meet + club. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          bottom: Math.round(96 * ts),
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 32,
          opacity: anim.resultOpacity,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: Math.round(24 * ts),
              letterSpacing: "0.22em",
              fontWeight: 700,
              color: roles.accent,
              textTransform: "uppercase",
            }}
          >
            {ctx.event}
          </div>
        </div>
        <div
          style={{
            fontSize: Math.round(96 * ts),
            fontWeight: 900,
            fontVariantNumeric: "tabular-nums",
            color: roles.onGround,
            lineHeight: 0.9,
            whiteSpace: "nowrap",
          }}
        >
          {ctx.result}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          bottom: Math.round(56 * ts),
          display: "flex",
          justifyContent: "space-between",
          fontSize: Math.round(26 * ts),
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: roles.onGround,
          opacity: anim.chipOpacity * 0.82,
        }}
      >
        <span>{ctx.meet}</span>
        <span style={{ fontWeight: 700 }}>{ctx.club}</span>
      </div>
    </>
  );
};

export default { archetype: "relay_collage", Scene };
