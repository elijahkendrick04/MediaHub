/**
 * Motion scene for the `band_break` still archetype (M12 twin).
 *
 * A broadcast band broken by the athlete, in the still's exact layering
 * (layouts/v2/band_break.html): ONE cutout painted twice inside a stage
 * spanning top 14% → bottom, both `background: cutout no-repeat bottom
 * center / contain` —
 *
 *   z0 — radial ground (120% 80% at 50% 6%) + faint surname watermark at
 *        top 9% (the mega-name px × 0.62 at 0.10 opacity)
 *   z1 — the full-figure BODY plane (depth-filtered; torso continues below
 *        the band)
 *   z2 — the band at top: bandTopPct% — ground role, 6px accent keyline,
 *        2px outline underline, first / fitted surname / event / hero stat /
 *        result chip
 *   z3 — the HEAD plane, soft-masked to black 0% → black breakSolidPct% →
 *        transparent breakFadePct% (stage-relative stops), painting the head
 *        and shoulders OVER the band's top edge
 *   z4 — slim footer (lockup left, meet right, text-shadowed) + kicker
 *
 * bandTopPct / breakSolidPct / breakFadePct arrive as props computed by the
 * still's own maths (render._band_top_fraction; solid = (top+0.015−0.14)/0.86,
 * fade = solid+0.055) so both surfaces break at identical pixels.
 *
 * Choreography: ground + watermark settle first (sine, atmospheric), the band
 * wipes in AT ITS FINAL y (Easing.out exp horizontal reveal — the band never
 * travels vertically, the figure does), then BOTH cutout planes rise together
 * ~8% so the head visibly breaks the band edge as it settles (the signature
 * beat, Easing.out cubic), the result chip snaps on an overshooting spring,
 * and the footer fades last. Reel exits follow the TransitionSpec
 * matched-velocity rule (no self-exit — the root's inReel gate owns that).
 *
 * Graces mirror the still: no photo → the band + watermark read as a clean
 * broadcast strip; matte-gate fallback (photo but no gated cutout) → the
 * ORIGINAL photograph as an uninterrupted full-bleed stage under the band
 * (no head plane, no watermark, bottom grad) — never a shredded silhouette.
 *
 * The still applies no duotone/halftone here (its filter targets
 * img.athlete-cutout; these planes are background-image divs) — so neither
 * does this scene. Frame-pure, brand-locked, fact-exact throughout.
 */
import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneComponent } from "../registry";
import { fitLine, shadowRgb, withAlpha } from "../sceneKit";

const ANTON = "'Anton', 'Bebas Neue', Impact, sans-serif";
const GROTESK = "'Space Grotesk', 'Inter', sans-serif";
const MONO = "'JetBrains Mono', 'Space Grotesk', monospace";

const Scene: SceneComponent = ({ ctx }) => {
  const { card, brand, roles, anim, width, height, ts } = ctx;
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const cutout = card.cutoutSrc || "";
  const photoFlat = !cutout && Boolean(card.photoSrc);

  const at = (f: number) => 3 + (durationInFrames - 3) * f;
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  // z0 — watermark settles first: atmospheric fade + drift (organic sine).
  const wmIn = interpolate(frame, [at(0), at(0.1)], [0, 1], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });
  // The scene's one ambient motion: the watermark drifts up a whisper across
  // the whole clip (the figure and band hold still once settled).
  const wmDrift = interpolate(frame, [0, durationInFrames], [0, -Math.round(8 * ts)], {
    ...clamp,
    easing: Easing.inOut(Easing.sin),
  });

  // z2 — the band wipes in horizontally at its final y (decisive).
  const bandWipe = interpolate(frame, [at(0.08), at(0.22)], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.exp),
  });

  // z1 + z3 — both cutout planes rise together ~8% (the signature beat: the
  // head breaks the band edge as it settles).
  const rise = interpolate(frame, [at(0.18), at(0.38)], [0, 1], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const riseY = (1 - rise) * height * 0.08;
  const cutOpacity = interpolate(frame, [at(0.18), at(0.28)], [0, 1], clamp);

  // Result chip snap; footer fades last.
  const chipSnap = spring({
    frame: Math.max(0, frame - at(0.3)),
    fps,
    config: { damping: 9, stiffness: 220, mass: 0.5 },
  });
  const chipIn = interpolate(frame, [at(0.3), at(0.36)], [0, 1], clamp);
  const footIn = interpolate(frame, [at(0.36), at(0.46)], [0, 1], clamp);

  // The still's decoration-scaled depth treatment on the body plane — key +
  // contact layers in the hue-tinted shadow colour (B4 parity with
  // render._cutout_depth_filter / elevation.shadow_rgb).
  const s = Math.max(0, Math.min(1, card.decorationStrength ?? 0.5));
  const sRgb = shadowRgb(roles.ground);
  const depthFilter =
    `drop-shadow(0 ${Math.round(10 + 14 * s)}px ${Math.round(24 + 30 * s)}px rgba(${sRgb},0.45)) ` +
    `drop-shadow(0 2px 5px rgba(${sRgb},0.38)) ` +
    `drop-shadow(0 0 ${Math.round(8 + 22 * s)}px ${withAlpha(roles.accent, 0.18 + 0.2 * s)})`;

  // The still's hairline --mh-outline, resolved Python-side and passed on the
  // props. Fallback: a translucent wash of the on-ground role — never an
  // invented colour (brand-locked rule).
  const outline = card.roleOutline || withAlpha(roles.onGround, 0.2);

  // Type fitting mirrors the still's autofit vars.
  const surname = (card.athleteSurname || card.athleteFullName || "").toUpperCase();
  const megaPx = fitLine(surname, Math.round(240 * ts), width * 0.96, 0.5);
  const surnamePx = fitLine(surname, Math.round(110 * ts), width * 0.62, 0.5);
  const resultPx = fitLine(ctx.resultFinal || "0:00.00", Math.round(76 * ts), width * 0.34, 0.62);

  // Stage-relative overlap fade stops (Python-computed; template defaults
  // 58 / 66 otherwise) — the head plane stays solid a touch past the band's
  // top edge, then dissolves into it.
  const headMask =
    `linear-gradient(180deg, black 0%, black ${card.breakSolidPct ?? 58}%, ` +
    `transparent ${card.breakFadePct ?? 66}%)`;

  // M19 resolve accents, scene-executed.
  const labelPulse = anim.resolveAccentKind === "label" ? 1 + 0.05 * anim.resolveAccent : 1;
  const statPulse = anim.resolveAccentKind === "stat" ? 1 + 0.04 * anim.resolveAccent : 1;

  const stagePlane: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    backgroundImage: `url("${cutout}")`,
    backgroundRepeat: "no-repeat",
    backgroundPosition: "bottom center",
    backgroundSize: "contain",
  };

  return (
    <>
      {/* z0 — the still's radial ground */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(120% 80% at 50% 6%, ${roles.surface} 0%, ${roles.ground} 78%)`,
        }}
      />
      {!photoFlat ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "9%",
            textAlign: "center",
            fontFamily: ANTON,
            fontWeight: 400,
            fontSize: Math.round(megaPx * 0.62),
            lineHeight: 0.84,
            letterSpacing: "0.02em",
            textTransform: "uppercase",
            color: roles.onGround,
            whiteSpace: "nowrap",
            opacity: 0.1 * wmIn,
            transform: `translateY(${wmDrift}px)`,
          }}
        >
          {surname}
        </div>
      ) : null}

      {/* the cutout stage — body plane under the band (or the flat photo) */}
      {photoFlat ? (
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
                "linear-gradient(180deg, rgba(0,0,0,0) 44%, rgba(0,0,0,0.14) 62%, rgba(0,0,0,0.42) 100%)",
              opacity: cutOpacity,
            }}
          />
        </>
      ) : cutout ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, top: "14%" }}>
          <div
            style={{
              ...stagePlane,
              transform: `translateY(${riseY}px)`,
              opacity: cutOpacity,
              filter: depthFilter,
            }}
          />
        </div>
      ) : null}

      {/* z2 — the band, wiping in at its final y */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: `${card.bandTopPct ?? 62}%`,
          background: roles.ground,
          borderTop: `6px solid ${roles.accent}`,
          borderBottom: `2px solid ${outline}`,
          padding: `${Math.round(34 * ts)}px ${Math.round(60 * ts)}px ${Math.round(38 * ts)}px`,
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 18px 44px rgba(0,0,0,0.35)",
          clipPath: `inset(0 ${((1 - bandWipe) * 100).toFixed(2)}% 0 0)`,
          opacity: bandWipe > 0 ? 1 : 0,
        }}
      >
        <div
          style={{
            fontFamily: GROTESK,
            fontWeight: 700,
            fontSize: Math.round(28 * ts),
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: roles.accent,
          }}
        >
          {ctx.firstName}
        </div>
        <div
          style={{
            fontFamily: ANTON,
            fontWeight: 400,
            fontSize: surnamePx,
            lineHeight: 0.86,
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            color: roles.onGround,
            whiteSpace: "nowrap",
          }}
        >
          {surname}
        </div>
        <div
          style={{
            marginTop: Math.round(18 * ts),
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: Math.round(32 * ts),
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontFamily: GROTESK,
                fontWeight: 600,
                fontSize: Math.round(27 * ts),
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                color: roles.onGround,
                opacity: anim.secondaryOpacity,
              }}
            >
              {ctx.event}
            </div>
            {card.heroStat ? (
              <div
                style={{
                  marginTop: Math.round(8 * ts),
                  fontFamily: "'Inter', sans-serif",
                  fontWeight: 600,
                  fontSize: Math.round(22 * ts),
                  color: roles.accent,
                  opacity: anim.chipOpacity,
                }}
              >
                {card.heroStat}
              </div>
            ) : null}
          </div>
          <span
            style={{
              flex: "0 0 auto",
              display: "inline-block",
              padding: `${Math.round(15 * ts)}px ${Math.round(26 * ts)}px`,
              background: roles.accent,
              color: roles.ground,
              fontFamily: MONO,
              fontVariantNumeric: "tabular-nums",
              fontWeight: 700,
              fontSize: resultPx,
              lineHeight: 0.9,
              transform: `scale(${(0.9 + 0.1 * chipSnap) * statPulse})`,
              transformOrigin: "right bottom",
              opacity: chipIn,
            }}
          >
            {ctx.result}
          </span>
        </div>
      </div>

      {/* z3 — the head/shoulders plane, soft-masked OVER the band's edge */}
      {!photoFlat && cutout ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, top: "14%" }}>
          <div
            style={{
              ...stagePlane,
              transform: `translateY(${riseY}px)`,
              opacity: cutOpacity,
              WebkitMaskImage: headMask,
              maskImage: headMask,
            }}
          />
        </div>
      ) : null}

      {/* z4 — kicker + slim footer over the ground */}
      {ctx.label ? (
        <div
          style={{
            position: "absolute",
            top: Math.round(60 * ts),
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
            opacity: interpolate(frame, [at(0.26), at(0.34)], [0, 1], clamp),
            transform: `scale(${labelPulse})`,
            transformOrigin: "left center",
          }}
        >
          {ctx.label}
        </div>
      ) : null}
      <div
        style={{
          position: "absolute",
          left: Math.round(60 * ts),
          right: Math.round(60 * ts),
          bottom: Math.round(44 * ts),
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: Math.round(24 * ts),
          opacity: footIn,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: Math.round(12 * ts) }}>
          {brand.logoDataUri ? (
            <img
              src={brand.logoDataUri}
              alt=""
              style={{ height: Math.round(46 * ts), width: "auto", objectFit: "contain" }}
            />
          ) : null}
          <div
            style={{
              fontFamily: "'Inter', sans-serif",
              fontWeight: 800,
              fontSize: Math.round(19 * ts),
              textTransform: "uppercase",
              color: roles.onGround,
              textShadow: "0 2px 10px rgba(0,0,0,0.5)",
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
              fontSize: Math.round(19 * ts),
              color: roles.onGround,
              opacity: 0.8,
              textAlign: "right",
              textShadow: "0 2px 10px rgba(0,0,0,0.5)",
            }}
          >
            {ctx.meet}
          </div>
        ) : null}
      </div>
    </>
  );
};

export default { archetype: "band_break", Scene };
