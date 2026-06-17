/**
 * Motion scene for the `staggered_diagonal_offset` still archetype (G1.1).
 *
 * Mirrors the still: type blocks stepped down a descending diagonal (kicker →
 * name → result chip → event), a thin accent rule running the diagonal. The
 * motion idea is the STAIRCASE assembling: the diagonal rule draws across, then
 * each block lands on its step, offset and overlapped, the result chip snapping
 * in as the accent beat.
 */
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { MetaFooter, KineticWords, ClubLogo, fitLine } from "../sceneKit";
import type { SceneComponent } from "../registry";

const Scene: SceneComponent = ({ ctx }) => {
  const { roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();

  // The diagonal guide draws from the left.
  const ruleDraw = interpolate(frame, [4, 4 + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const step = (order: number, ease: (n: number) => number) =>
    interpolate(frame, [8 + order * 5, 8 + order * 5 + 12], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: ease,
    });
  const kick = step(0, Easing.out(Easing.cubic));
  const evt = step(3, Easing.out(Easing.sin));

  const s2 = Math.round(90 * ts);
  const s3 = Math.round(200 * ts);
  const s4 = Math.round(120 * ts);

  return (
    <>
      {/* diagonal guide rule */}
      <div
        style={{
          position: "absolute",
          left: "4%",
          top: "50%",
          width: "116%",
          height: Math.round(5 * ts),
          background: roles.accent,
          opacity: 0.4,
          transform: `translateY(-50%) rotate(34deg) scaleX(${ruleDraw})`,
          transformOrigin: "left center",
        }}
      />

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: `${Math.round(96 * ts)}px ${Math.round(80 * ts)}px`,
          gap: Math.round(30 * ts),
        }}
      >
        {/* step 1 — kicker */}
        <div
          style={{
            marginLeft: 0,
            fontSize: Math.round(24 * ts),
            fontWeight: 800,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: roles.accent,
            opacity: kick,
            transform: `translateX(${(1 - kick) * -40}px)`,
          }}
        >
          {ctx.label || "STRONG SWIM"}
        </div>

        {/* step 2 — name */}
        <div style={{ marginLeft: s2 }}>
          <div style={{ fontSize: Math.round(38 * ts), fontWeight: 700, textTransform: "uppercase", color: roles.accent, opacity: anim.secondaryOpacity }}>
            {ctx.firstName}
          </div>
          <KineticWords
            text={ctx.surnameText}
            ctx={ctx}
            style={{
              fontSize: fitLine(ctx.surnameText, Math.round(96 * ts), width * 0.7),
              fontWeight: 900,
              lineHeight: 0.86,
              letterSpacing: "-0.01em",
              textTransform: "uppercase",
              color: roles.onGround,
              opacity: anim.heroOpacity,
              transform: `translateY(${anim.heroY}px)`,
            }}
          />
        </div>

        {/* step 3 — result chip */}
        <div style={{ marginLeft: s3 }}>
          <div
            style={{
              display: "inline-block",
              background: roles.accent,
              color: roles.ground,
              borderRadius: Math.round(10 * ts),
              padding: `${Math.round(10 * ts)}px ${Math.round(22 * ts)}px`,
              fontSize: Math.round(72 * ts),
              fontWeight: 900,
              lineHeight: 0.9,
              letterSpacing: "-0.02em",
              fontVariantNumeric: "tabular-nums",
              opacity: anim.resultOpacity,
              transform: `scale(${anim.resultScale})`,
              transformOrigin: "left center",
            }}
          >
            {ctx.result}
          </div>
          {ctx.card.heroStat ? (
            <div style={{ marginTop: Math.round(8 * ts), fontSize: Math.round(22 * ts), fontWeight: 700, color: roles.accent, opacity: anim.resultOpacity }}>
              {ctx.card.heroStat}
            </div>
          ) : null}
        </div>

        {/* step 4 — event */}
        <div
          style={{
            marginLeft: s4,
            fontSize: Math.round(28 * ts),
            fontWeight: 600,
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: evt * 0.92,
            transform: `translateY(${(1 - evt) * 24}px)`,
          }}
        >
          {ctx.event}
        </div>
      </div>

      <ClubLogo ctx={ctx} size={92} />
      <MetaFooter ctx={ctx} />
    </>
  );
};

export default { archetype: "staggered_diagonal_offset", Scene };
