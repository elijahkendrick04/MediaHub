/**
 * Scene mode — vertical split (R1.2).
 *
 * Two stacked colour fields meeting at an animated horizontal seam: the athlete
 * identity lives in the upper field (over their photo when present), the verified
 * result in the lower field. Structurally distinct from the built-in `split`
 * scene (a diagonal LEFT/RIGHT wedge) and from `lowerThird` (a band floating over
 * a full-bleed photo): here the frame is cut top/bottom into two solid colour
 * fields, and the lower field RISES from the seam as its signature move.
 *
 * Registered for the still-engine archetype `vertical_split` (the matching
 * `graphic_renderer/layouts/v2/vertical_split.html` ships in its own session,
 * G1.1). When a card carries that archetype this replaces the built-in scene.
 */
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

const Scene: SceneComponent = ({ ctx }: { ctx: SceneCtx }) => {
  const { card, roles, anim, width, height, ts, frame } = ctx;

  // Seam a touch above centre so the result field carries visual weight.
  const seamY = Math.round(height * 0.54);
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  // Variant: which field wears the accent fill (deterministic per card).
  const accentBelow = seedPick(ctx, 2) === 0;
  const lowerFill = accentBelow ? roles.accent : roles.surface;
  const lowerInk = accentBelow ? roles.ground : roles.onGround;

  // Build: top content slides DOWN into place (cubic-out), the lower panel
  // RISES from the seam (scaleY from the top edge, exp-out — decisive), the
  // seam rule WIPES across (inOut), and content resolves last. Three distinct
  // easings, staggered by importance, first move at frame 3 (never frame 0).
  const topDrop = interpolate(frame, [3, 19], [1, 0], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const rise = interpolate(frame, [8, 26], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.exp),
  });
  const wipeDir = seedPick(ctx, 2) === 0 ? "left" : "right";
  const wipe = interpolate(frame, [16, 32], [0, 1], {
    ...clamp,
    easing: Easing.inOut(Easing.cubic),
  });
  // Breathe: the seam glow respires gently through the readable middle.
  const glow = 0.4 + 0.25 * (0.5 + 0.5 * Math.sin(frame / 22));

  const seamH = Math.max(8, Math.round(12 * ts));

  return (
    <>
      {/* Upper field — photo (scrimmed to its own lower edge) or solid ground. */}
      <div style={{ position: "absolute", left: 0, top: 0, right: 0, height: seamY, overflow: "hidden" }}>
        <PhotoFill ctx={ctx} scrim="bottom" />
      </div>

      {/* Lower field — rises from the seam. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: seamY,
          right: 0,
          bottom: 0,
          background: lowerFill,
          transform: `scaleY(${rise})`,
          transformOrigin: "top center",
        }}
      />

      {/* Seam rule — accent bar that wipes across, with a breathing glow. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: seamY - seamH / 2,
          height: seamH,
          background: roles.accent,
          transform: `scaleX(${wipe})`,
          transformOrigin: wipeDir === "left" ? "left center" : "right center",
          boxShadow: `0 0 ${Math.round(40 * ts)}px ${roles.accent}`,
          opacity: 0.7 + 0.3 * glow,
        }}
      />

      <ClubLogo ctx={ctx} />

      {/* Label chip — upper field, top-left. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: Math.round(150 * ts),
          padding: `${Math.round(13 * ts)}px ${Math.round(26 * ts)}px`,
          background: roles.accent,
          color: roles.ground,
          fontSize: Math.round(34 * ts),
          fontWeight: 800,
          letterSpacing: "0.12em",
          borderRadius: 6,
          textTransform: "uppercase",
          opacity: anim.chipOpacity,
          maxWidth: width - 160,
          overflow: "hidden",
          whiteSpace: "nowrap",
        }}
      >
        {ctx.label || "STRONG SWIM"}
      </div>

      {/* Identity — upper field, dropping in. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: seamY - Math.round(300 * ts),
          transform: `translateY(${topDrop * -height * 0.1}px)`,
        }}
      >
        <div
          style={{
            fontSize: Math.round(40 * ts),
            fontWeight: 600,
            color: roles.onGround,
            letterSpacing: "0.06em",
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
            marginTop: Math.round(6 * ts),
            fontSize: fitLine(ctx.surnameText, Math.round(150 * ts), width - 160),
            fontWeight: 900,
            color: roles.onGround,
            letterSpacing: "-0.02em",
            lineHeight: 0.96,
            textTransform: "uppercase",
            opacity: anim.heroOpacity,
          }}
        />
      </div>

      {/* Event + result — lower field, resolving after the rise. */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: seamY + Math.round(64 * ts),
          opacity: rise,
        }}
      >
        <div
          style={{
            fontSize: Math.round(36 * ts),
            color: lowerInk,
            opacity: anim.secondaryOpacity * 0.9,
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          {ctx.event}
        </div>
        <div
          style={{
            marginTop: Math.round(14 * ts),
            fontSize: Math.round(132 * ts),
            fontWeight: 900,
            color: lowerInk,
            fontVariantNumeric: "tabular-nums",
            lineHeight: 1,
            letterSpacing: "-0.02em",
            opacity: anim.resultOpacity,
            transform: `scale(${anim.resultScale})`,
            transformOrigin: "left center",
          }}
        >
          {ctx.result}
        </div>
        {card.heroStat ? (
          <div
            style={{
              marginTop: Math.round(16 * ts),
              fontSize: Math.round(38 * ts),
              fontWeight: 800,
              color: accentBelow ? roles.ground : roles.accent,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              opacity: anim.resultOpacity * 0.95,
            }}
          >
            {card.heroStat}
          </div>
        ) : null}
      </div>

      <MetaFooter ctx={ctx} tint={accentBelow ? roles.ground : roles.onGround} />
    </>
  );
};

export default { archetype: "vertical_split", Scene };
