/**
 * Scene mode — marquee crawl (R1.2).
 *
 * A stadium ribbon-board: several full-width marquee bands crawl across the
 * frame in ALTERNATING directions at varied speeds, while a pinned centre plate
 * holds the hero (name + verified result) so the message reads even muted.
 * Structurally distinct from the built-in `ticker` scene (a SINGLE accent band
 * at 0.6h with static hero text above): here the crawl is the whole backdrop —
 * a multi-band wall in motion — and the facts are locked on a solid plate the
 * bands never obscure.
 *
 * Honesty: every band carries only the card's real facts, and the crawl uses
 * `ctx.resultFinal` (the verified value), never a mid-count number — a scrolling
 * partial time would read as a different result. Registered for the still-engine
 * archetype `marquee_crawl` (matching `layouts/v2/marquee_crawl.html` ships in
 * its own session, G1.1); when a card carries it this replaces the built-in scene.
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
  seedPick,
} from "../sceneKit";

// Varied crawl speeds (px/sec) — slowest ≈ 3.75× the fastest, so no two bands
// share a tempo (the flat-rhythm monoculture the craft notes warn against).
const SPEEDS = [42, 150, 70, 118, 92];

const Scene: SceneComponent = ({ ctx }: { ctx: SceneCtx }) => {
  const { card, roles, anim, width, height, ts, frame, fps } = ctx;
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  const bandCount = 3 + seedPick(ctx, 3); // 3, 4 or 5 ribbon bands
  const startDir = seedPick(ctx, 2) === 0 ? -1 : 1;
  const accentBelow = seedPick(ctx, 2) === 0;
  const plateFill = accentBelow ? roles.accent : roles.surface;
  const plateInk = accentBelow ? roles.ground : roles.onGround;

  // Honest crawl copy — only the card's real facts; the VERIFIED result, never
  // the mid-count display text.
  const bits = [ctx.label, ctx.surnameText, ctx.event, ctx.resultFinal, card.heroStat, ctx.meet]
    .filter(Boolean)
    .join("   •   ");
  const crawlText = `${bits}   •   ${bits}   •   ${bits}   •   ${bits}   •   `;

  const bands: React.ReactNode[] = [];
  for (let i = 0; i < bandCount; i++) {
    const dir = startDir * (i % 2 === 0 ? 1 : -1);
    const speed = SPEEDS[i % SPEEDS.length];
    const crawl = (frame / fps) * speed;
    const y = Math.round((height * (i + 0.5)) / bandCount);
    // Bands fade in staggered, top-down; the crawl itself is the ambient life.
    const fade = interpolate(frame, [3 + i * 2, 16 + i * 2], [0, 1], {
      ...clamp,
      easing: Easing.out(Easing.cubic),
    });
    const useAccent = i % 3 === 1;
    bands.push(
      <div
        key={`band-${i}`}
        style={{
          position: "absolute",
          left: dir === 1 ? -2600 : 0,
          top: y - Math.round(40 * ts),
          whiteSpace: "nowrap",
          fontSize: Math.round(58 * ts),
          fontWeight: 900,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: useAccent ? roles.accent : roles.onGround,
          opacity: fade * (useAccent ? 0.5 : 0.4),
          transform: `translateX(${dir * crawl}px)`,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {crawlText}
      </div>,
    );
  }

  // Centre plate — scales open from its own midline (cubic), then content
  // resolves. The keyline glow breathes through the readable middle.
  const plateTop = Math.round(height * 0.39);
  const plateH = Math.round(height * 0.23);
  const open = interpolate(frame, [5, 23], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const keyGlow = 0.6 + 0.4 * (0.5 + 0.5 * Math.sin(frame / 21));
  const keyH = Math.max(5, Math.round(7 * ts));

  return (
    <>
      <PhotoFill ctx={ctx} scrim="full" strength={0.5} />

      {bands}

      <ClubLogo ctx={ctx} />

      {/* Centre plate. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: plateTop,
          height: plateH,
          background: plateFill,
          transform: `scaleY(${open})`,
          transformOrigin: "center",
          boxShadow: `0 ${Math.round(30 * ts)}px ${Math.round(70 * ts)}px ${roles.ground}AA`,
        }}
      />
      {/* Accent keylines top & bottom of the plate. */}
      {[plateTop, plateTop + plateH - keyH].map((ty, k) => (
        <div
          key={`key-${k}`}
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: ty,
            height: keyH,
            background: accentBelow ? roles.ground : roles.accent,
            opacity: open * keyGlow,
          }}
        />
      ))}

      {/* Hero on the plate — stacked lines, each fit to the plate width so a
          long surname or result can never bleed off-frame. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: plateTop + Math.round(30 * ts),
          opacity: open,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            fontSize: Math.round(30 * ts),
            fontWeight: 800,
            letterSpacing: "0.14em",
            color: plateInk,
            textTransform: "uppercase",
            opacity: anim.chipOpacity,
            whiteSpace: "nowrap",
          }}
        >
          {ctx.label || "STRONG SWIM"}
          {ctx.firstName ? `  ·  ${ctx.firstName}` : ""}
        </div>
        <KineticWords
          ctx={ctx}
          text={ctx.surnameText}
          style={{
            marginTop: Math.round(4 * ts),
            fontSize: fitLine(ctx.surnameText, Math.round(104 * ts), width - 160),
            fontWeight: 900,
            color: plateInk,
            letterSpacing: "-0.02em",
            lineHeight: 1,
            textTransform: "uppercase",
            opacity: anim.heroOpacity,
            transform: `translateY(${anim.heroY * 0.4}px)`,
          }}
        />
        <div
          style={{
            marginTop: Math.round(10 * ts),
            fontSize: fitLine(ctx.resultFinal, Math.round(96 * ts), width - 160, 0.62),
            fontWeight: 900,
            color: plateInk,
            fontVariantNumeric: "tabular-nums",
            lineHeight: 1,
            letterSpacing: "-0.02em",
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale})`,
            transformOrigin: "left center",
            whiteSpace: "nowrap",
          }}
        >
          {ctx.result}
        </div>
        <div
          style={{
            marginTop: Math.round(10 * ts),
            fontSize: Math.round(32 * ts),
            color: plateInk,
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            opacity: anim.secondaryOpacity * 0.85,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {ctx.event}
          {card.heroStat ? `  —  ${card.heroStat}` : ""}
        </div>
      </div>

      <MetaFooter ctx={ctx} />
    </>
  );
};

export default { archetype: "marquee_crawl", Scene };
