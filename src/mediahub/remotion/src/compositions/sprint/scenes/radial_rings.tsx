/**
 * Scene mode — radial rings (R1.2).
 *
 * A radial competition target: concentric accent rings EMANATE outward from a
 * centre that holds the verified result, with the athlete's name seated below
 * and a slow rotating tick-ring giving the dial a heartbeat. Structurally
 * distinct from the built-in `spotlight` scene (a single ring badge over a
 * centred portrait): this is a multi-ring ripple built from the achievement
 * outward, with the number — not a placing badge — at the bullseye.
 *
 * Registered for the still-engine archetype `radial_rings` (the matching
 * `graphic_renderer/layouts/v2/radial_rings.html` ships in its own session,
 * G1.1). When a card carries that archetype this replaces the built-in scene.
 */
import React from "react";
import { Easing, interpolate } from "remotion";
import type { SceneComponent, SceneCtx } from "../registry";
import {
  ClubLogo,
  KineticWords,
  MetaFooter,
  PhotoFill,
  fitLine,
  placeOrdinal,
  seedPick,
} from "../sceneKit";

const Scene: SceneComponent = ({ ctx }: { ctx: SceneCtx }) => {
  const { card, roles, anim, width, height, ts, frame, fps } = ctx;
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  const cx = width / 2;
  const cy = Math.round(height * 0.4);
  const baseR = Math.round(Math.min(width, height) * 0.34);
  const ringCount = 3 + seedPick(ctx, 2); // 3 or 4 emanating rings

  // Build: the bullseye glow blooms first (cubic), then the rings ripple
  // OUTWARD with a per-ring stagger (exp-out — each ring snaps to radius),
  // then text resolves. Outer rings start later, so the motion reads as a
  // pulse leaving the centre. Distinct easings, first move at frame 4.
  const bloom = interpolate(frame, [4, 22], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const place = placeOrdinal(card.place || "");

  const rings: React.ReactNode[] = [];
  for (let i = 0; i < ringCount; i++) {
    const r = Math.round(baseR * (0.52 + (0.48 * (i + 1)) / ringCount));
    const start = 8 + i * 5;
    const grow = interpolate(frame, [start, start + 18], [0, 1], {
      ...clamp,
      easing: Easing.out(Easing.exp),
    });
    // Breathe: only the outermost ring respires through the readable middle.
    const breathe = i === ringCount - 1 ? 1 + 0.018 * Math.sin(frame / 20) : 1;
    rings.push(
      <div
        key={`ring-${i}`}
        style={{
          position: "absolute",
          left: cx - r,
          top: cy - r,
          width: 2 * r,
          height: 2 * r,
          borderRadius: "50%",
          border: `${Math.max(2, Math.round((6 - i) * ts))}px solid ${roles.accent}`,
          opacity: grow * (0.7 - i * 0.13),
          transform: `scale(${grow * breathe})`,
        }}
      />,
    );
  }

  // A slow rotating dashed tick-ring — a frame-pure dial (deterministic;
  // 14°/sec). Sits between the inner and outer rings.
  const tickR = Math.round(baseR * 0.78);
  const spin = (frame / fps) * 14;

  return (
    <>
      <PhotoFill ctx={ctx} scrim="radial" strength={0.4} />

      {/* Centre bloom — a soft accent halo seating the number. */}
      <div
        style={{
          position: "absolute",
          left: cx - baseR,
          top: cy - baseR,
          width: 2 * baseR,
          height: 2 * baseR,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${roles.accent}38 0%, ${roles.ground}00 62%)`,
          opacity: bloom,
        }}
      />

      {rings}

      {/* Rotating tick-ring. */}
      <div
        style={{
          position: "absolute",
          left: cx - tickR,
          top: cy - tickR,
          width: 2 * tickR,
          height: 2 * tickR,
          borderRadius: "50%",
          border: `${Math.max(2, Math.round(3 * ts))}px dashed ${roles.accent}`,
          opacity: bloom * 0.35,
          transform: `rotate(${spin}deg)`,
        }}
      />

      <ClubLogo ctx={ctx} size={104} />

      {/* Label — above the target. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: Math.round(150 * ts),
          textAlign: "center",
          fontSize: Math.round(36 * ts),
          fontWeight: 800,
          letterSpacing: "0.22em",
          color: roles.accent,
          textTransform: "uppercase",
          opacity: anim.chipOpacity,
        }}
      >
        {ctx.label || "STRONG SWIM"}
      </div>

      {/* Bullseye — event + the verified result, dead centre. */}
      <div
        style={{
          position: "absolute",
          left: cx - baseR,
          top: cy - Math.round(86 * ts),
          width: 2 * baseR,
          textAlign: "center",
          transform: `scale(${0.9 + 0.1 * bloom})`,
          transformOrigin: "center top",
        }}
      >
        <div
          style={{
            fontSize: Math.round(30 * ts),
            fontWeight: 700,
            letterSpacing: "0.08em",
            color: roles.onGround,
            textTransform: "uppercase",
            opacity: anim.secondaryOpacity * 0.9,
          }}
        >
          {ctx.event}
        </div>
        <div
          style={{
            marginTop: Math.round(8 * ts),
            fontSize: Math.round(118 * ts),
            fontWeight: 900,
            color: roles.onGround,
            fontVariantNumeric: "tabular-nums",
            lineHeight: 1,
            letterSpacing: "-0.02em",
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale})`,
          }}
        >
          {ctx.result}
        </div>
        {place ? (
          <div
            style={{
              marginTop: Math.round(6 * ts),
              fontSize: Math.round(40 * ts),
              fontWeight: 800,
              letterSpacing: "0.1em",
              color: roles.accent,
              textTransform: "uppercase",
              opacity: anim.resultOpacity,
            }}
          >
            {place}
          </div>
        ) : null}
      </div>

      {/* Name — seated below the target. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: cy + baseR + Math.round(60 * ts),
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontSize: Math.round(38 * ts),
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: roles.onGround,
            textTransform: "uppercase",
            opacity: anim.secondaryOpacity,
          }}
        >
          {ctx.firstName}
        </div>
        <KineticWords
          ctx={ctx}
          text={ctx.surnameText}
          style={{
            marginTop: Math.round(4 * ts),
            fontSize: fitLine(ctx.surnameText, Math.round(120 * ts), width - 160),
            fontWeight: 900,
            color: roles.onGround,
            letterSpacing: "-0.02em",
            lineHeight: 0.98,
            textTransform: "uppercase",
            textAlign: "center",
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.4}px)`,
          }}
        />
        {card.heroStat ? (
          <div
            style={{
              marginTop: Math.round(14 * ts),
              fontSize: Math.round(34 * ts),
              fontWeight: 800,
              letterSpacing: "0.08em",
              color: roles.accent,
              textTransform: "uppercase",
              opacity: anim.resultOpacity * 0.9,
            }}
          >
            {card.heroStat}
          </div>
        ) : null}
      </div>

      <MetaFooter ctx={ctx} />
    </>
  );
};

export default { archetype: "radial_rings", Scene };
