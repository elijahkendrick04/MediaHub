/**
 * Motion scene for the `poster_name_behind` still archetype (M12 twin).
 *
 * The classic sports-poster three-plane sandwich, in the still's exact
 * z-order (layouts/v2/poster_name_behind.html):
 *
 *   z0 — radial ground (115% 85% at 50% 10%, surface → ground 76%)
 *   z1 — the MEGA surname plane, Anton register, centred at top 26%
 *   z2 — the athlete CUTOUT standing OVER the name (real depth), carrying the
 *        still's decoration-scaled depth treatment (soft dark lift shadow +
 *        faint accent glow — render._cutout_depth_filter maths)
 *   z3 — the lower-third band on the surface role (5px accent keyline):
 *        event / result chip / hero stat, brand lockup right
 *   z4 — kicker chip top-left + first name below
 *
 * Choreography (back→front build, exactly the plane order): the name plane
 * slide-up-settles first (Easing.out cubic), the cutout enters translateY
 * 4%→0 with scale 1.04→1 while its shadow fades in (Easing.out exp), the band
 * slides up (Easing.out cubic, offset) with the result chip snapping in on an
 * overshooting spring, and the kicker fades last. No saliency pan (the cutout
 * is contain-fit); the only ambient motion is a ≤1.03 push-in on the cutout
 * (Easing.inOut sin). ≥3 distinct easings, first animation off frame 0,
 * stagger by importance under 15 frames.
 *
 * Graces mirror the still: no photo → a deliberate type poster; matte-gate
 * fallback (photoSrc but no cutoutSrc — the SAME gate the still ran) → the
 * ORIGINAL photograph as a full-bleed stage under the brand scrim with the
 * name plane riding above it (.mh-photo-flat), never a broken silhouette.
 *
 * Frame-pure (interpolate/spring only), brand-locked (resolved roles only),
 * fact-exact (ctx fields; the result chip shows ctx.result so count_up still
 * lands on the verified value).
 */
import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneComponent } from "../registry";
import { fitLine, withAlpha } from "../sceneKit";
import { PhotoFilterDefs, photoExactGradeFor, photoHalftoneMaskFor } from "../layers/photo_filters";

const ANTON = "'Anton', 'Bebas Neue', Impact, sans-serif";
const GROTESK = "'Space Grotesk', 'Inter', sans-serif";
const MONO = "'JetBrains Mono', 'Space Grotesk', monospace";

const Scene: SceneComponent = ({ ctx }) => {
  const { card, brand, roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const cutout = card.cutoutSrc || "";
  // Matte-gate grace: the gate rejected the cutout (or none was preparable)
  // but the original photograph is here — the still's .mh-photo-flat path.
  const photoFlat = !cutout && Boolean(card.photoSrc);
  const onSurface = card.roleOnSurface || roles.onGround;

  // Proportional keyframes (M19 convention): fractions of the clip, first
  // animation off frame 0.
  const at = (f: number) => 3 + (durationInFrames - 3) * f;
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  // z1 — name plane: slide-up-settle (composed, reliable).
  const nameEnter = interpolate(frame, [at(0), at(0.14)], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const nameY = (1 - nameEnter) * Math.round(90 * ts);
  const nameOpacity = interpolate(frame, [at(0), at(0.08)], [0, 1], clamp);

  // z2 — cutout: rises 4%→0 with scale 1.04→1, decisive (premium snap).
  const cutEnter = interpolate(frame, [at(0.06), at(0.22)], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.exp),
  });
  const cutOpacity = interpolate(frame, [at(0.06), at(0.14)], [0, 1], clamp);
  // The only ambient motion: a ≤1.03 push-in on the cutout alone (no pan).
  const push = interpolate(frame, [at(0.22), durationInFrames], [1.0, 1.03], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });

  // z3 — band: slides up from below the frame, offset behind the cutout.
  const bandEnter = interpolate(frame, [at(0.12), at(0.26)], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  // Result chip: snap_in_then_settle (deliberately overshooting spring).
  const chipSnap = spring({
    frame: Math.max(0, frame - at(0.18)),
    fps,
    config: { damping: 9, stiffness: 220, mass: 0.5 },
  });
  // z4 — kicker + first name fade last (fastest, opacity-led).
  const kickerIn = interpolate(frame, [at(0.24), at(0.32)], [0, 1], clamp);

  // The still's decoration-scaled depth treatment (render._cutout_depth_filter),
  // faded in with the entrance so the lift reads as the subject settling.
  const s = Math.max(0, Math.min(1, card.decorationStrength ?? 0.5));
  const dy = Math.round(10 + 14 * s);
  const dBlur = Math.round(24 + 30 * s);
  const glow = Math.round(8 + 22 * s);
  const glowA = (0.18 + 0.2 * s) * cutEnter;
  const depthFilter =
    `drop-shadow(0 ${dy}px ${dBlur}px rgba(0,0,0,${(0.45 * cutEnter).toFixed(3)})) ` +
    `drop-shadow(0 0 ${glow}px ${withAlpha(roles.accent, glowA)})`;
  // M10 grade parity: the still's duotone/halftone REPLACES the depth filter
  // on the cutout img (img.athlete-cutout specificity).
  const exactGrade = photoExactGradeFor(card);
  const mask = photoHalftoneMaskFor(card);

  // Mega name: full surname (never the 12-char ticker slice), Anton-fitted to
  // the 96%-wide plane like the still's autofit (--mh-fit-mega-name-px).
  const megaText = (card.athleteSurname || card.athleteFullName || "").toUpperCase();
  const megaPx = fitLine(megaText, Math.round(280 * ts), width * 0.96, 0.5);

  // M19 resolve accents: the kicker chip re-pulses on "label"; the result
  // chip on "stat" (the shared confirmation beat, scene-executed).
  const labelPulse = anim.resolveAccentKind === "label" ? 1 + 0.05 * anim.resolveAccent : 1;
  const statPulse = anim.resolveAccentKind === "stat" ? 1 + 0.04 * anim.resolveAccent : 1;

  const resultPx = fitLine(ctx.resultFinal || "0:00.00", Math.round(78 * ts), width * 0.5, 0.62);

  return (
    <>
      {/* z0 — the still's radial ground */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(115% 85% at 50% 10%, ${roles.surface} 0%, ${roles.ground} 76%)`,
        }}
      />

      {photoFlat ? (
        // Matte-gate grace: full-bleed original under the brand scrim.
        <>
          <img
            src={card.photoSrc}
            alt=""
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: card.photoPos || "center 26%",
              opacity: cutOpacity,
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                `linear-gradient(180deg, ${withAlpha(roles.ground, 0.34)} 0%, ` +
                `rgba(0,0,0,0.10) 46%, ${withAlpha(roles.ground, 0.62)} 100%)`,
              opacity: cutOpacity,
            }}
          />
        </>
      ) : null}

      {/* z1 — the mega surname plane (above the flat photo, under the cutout) */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "26%",
          width: "96%",
          transform: `translateX(-50%) translateY(${nameY}px)`,
          textAlign: "center",
          fontFamily: ANTON,
          fontWeight: 400,
          fontSize: megaPx,
          lineHeight: 0.84,
          letterSpacing: "-0.03em",
          textTransform: "uppercase",
          color: roles.onGround,
          whiteSpace: "nowrap",
          opacity: nameOpacity * (photoFlat ? 0.98 : 0.94),
        }}
      >
        {megaText}
      </div>

      {/* z2 — the athlete cutout standing OVER the name */}
      {cutout ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            top: "16%",
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "center",
            transform: `translateY(${(1 - cutEnter) * height * 0.04}px) scale(${
              1.04 - 0.04 * cutEnter
            })`,
            transformOrigin: "bottom center",
            opacity: cutOpacity,
          }}
        >
          <PhotoFilterDefs card={card} />
          <img
            src={cutout}
            alt=""
            style={{
              maxWidth: "88%",
              maxHeight: "100%",
              objectFit: "contain",
              objectPosition: "bottom center",
              display: "block",
              transform: `scale(${push})`,
              transformOrigin: "bottom center",
              filter: exactGrade || depthFilter,
              ...(mask ?? {}),
            }}
          />
        </div>
      ) : null}

      {/* z3 — the lower-third band over the cutout's lower body */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          transform: `translateY(${(1 - bandEnter) * 100}%)`,
          background: roles.surface,
          borderTop: `5px solid ${roles.accent}`,
          padding: `${Math.round(34 * ts)}px ${Math.round(60 * ts)}px ${Math.round(42 * ts)}px`,
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: Math.round(32 * ts),
        }}
      >
        <div
          style={{
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            gap: Math.round(10 * ts),
          }}
        >
          <div
            style={{
              fontFamily: GROTESK,
              fontWeight: 600,
              fontSize: Math.round(30 * ts),
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: onSurface,
              opacity: anim.secondaryOpacity,
            }}
          >
            {ctx.event}
          </div>
          <div
            style={{
              display: "inline-block",
              alignSelf: "flex-start",
              padding: `${Math.round(14 * ts)}px ${Math.round(26 * ts)}px`,
              background: roles.accent,
              color: roles.ground,
              fontFamily: MONO,
              fontVariantNumeric: "tabular-nums",
              fontWeight: 700,
              fontSize: resultPx,
              lineHeight: 0.9,
              transform: `scale(${(0.9 + 0.1 * chipSnap) * statPulse})`,
              transformOrigin: "left bottom",
              opacity: interpolate(frame, [at(0.18), at(0.24)], [0, 1], clamp),
            }}
          >
            {ctx.result}
          </div>
          {card.heroStat ? (
            <div
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 600,
                fontSize: Math.round(23 * ts),
                color: onSurface,
                opacity: 0.84 * anim.chipOpacity,
              }}
            >
              {card.heroStat}
            </div>
          ) : null}
        </div>
        <div
          style={{
            flex: "0 0 auto",
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: Math.round(12 * ts),
            textAlign: "right",
            opacity: anim.chipOpacity,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: Math.round(14 * ts) }}>
            {brand.logoDataUri ? (
              <img
                src={brand.logoDataUri}
                alt=""
                style={{ height: Math.round(54 * ts), width: "auto", objectFit: "contain" }}
              />
            ) : null}
            <div
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 800,
                fontSize: Math.round(21 * ts),
                textTransform: "uppercase",
                color: onSurface,
              }}
            >
              {ctx.club}
            </div>
          </div>
          {ctx.meet ? (
            <div
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 500,
                fontSize: Math.round(18 * ts),
                color: onSurface,
                opacity: 0.72,
              }}
            >
              {ctx.meet}
            </div>
          ) : null}
        </div>
      </div>

      {/* z4 — kicker chip + first name, over every plane */}
      {ctx.label ? (
        <div
          style={{
            position: "absolute",
            top: Math.round(64 * ts),
            left: Math.round(60 * ts),
            display: "inline-flex",
            alignItems: "center",
            padding: `${Math.round(14 * ts)}px ${Math.round(22 * ts)}px`,
            background: roles.accent,
            color: roles.ground,
            fontFamily: GROTESK,
            fontWeight: 800,
            fontSize: Math.round(25 * ts),
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            opacity: kickerIn,
            transform: `scale(${labelPulse})`,
            transformOrigin: "left center",
          }}
        >
          {ctx.label}
        </div>
      ) : null}
      {ctx.firstName ? (
        <div
          style={{
            position: "absolute",
            top: Math.round(140 * ts),
            left: Math.round(60 * ts),
            fontFamily: GROTESK,
            fontWeight: 700,
            fontSize: Math.round(34 * ts),
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: roles.onGround,
            opacity: kickerIn,
          }}
        >
          {ctx.firstName}
        </div>
      ) : null}
    </>
  );
};

export default { archetype: "poster_name_behind", Scene };
