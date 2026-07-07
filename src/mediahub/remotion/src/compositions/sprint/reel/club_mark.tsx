// M20 — persistent club mark: a small corner chip carrying the club's logo
// and/or short name through the card beats, the broadcast-style "channel
// bug" that makes the reel read as one branded piece. Hidden during the
// cover and outro — those scenes ARE the brand statement, so the bug would
// double it.
//
// Frame-pure (interpolate over ctx.frame only) and brand-exact: colours are
// the resolved ground/onGround roles from ReelCtx; the logo is the club's own
// data URI. Renders nothing when the club has neither a label nor a logo.
import React from "react";
import { Easing, interpolate } from "remotion";
import type { ReelLayer } from "../reelRegistry";

const Layer: ReelLayer = ({ ctx }) => {
  const {
    frame,
    fps,
    width,
    height,
    ground,
    onGround,
    clubLabel,
    logoDataUri,
    beatStarts,
    outroStart,
    cardCount,
  } = ctx;
  if (!cardCount || !beatStarts.length || (!clubLabel && !logoDataUri)) {
    return null;
  }
  const start = beatStarts[0];

  // On through the beats only: rises just after the first beat's build
  // starts, gone as the outro takes over.
  const visible = interpolate(
    frame,
    [
      start + Math.round(fps * 0.3),
      start + Math.round(fps * 0.7),
      outroStart - Math.round(fps * 0.1),
      outroStart + Math.round(fps * 0.25),
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.sin) },
  );
  if (visible <= 0) {
    return null;
  }

  const ts = Math.min(width / 1080, height / 1440, 1);
  const markH = Math.round(52 * ts);
  return (
    <div
      style={{
        position: "absolute",
        left: Math.round(34 * ts),
        top: Math.round(34 * ts),
        height: markH,
        display: "flex",
        alignItems: "center",
        gap: Math.round(10 * ts),
        padding: `0 ${Math.round(14 * ts)}px`,
        background: `${ground}C8`,
        borderRadius: markH / 2,
        opacity: visible * 0.92,
        pointerEvents: "none",
      }}
    >
      {logoDataUri ? (
        <img
          src={logoDataUri}
          alt=""
          style={{
            height: Math.round(markH * 0.62),
            width: Math.round(markH * 0.62),
            objectFit: "contain",
          }}
        />
      ) : null}
      {clubLabel ? (
        <span
          style={{
            fontSize: Math.round(22 * ts),
            fontWeight: 800,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: onGround,
            fontFamily:
              "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif",
            whiteSpace: "nowrap",
          }}
        >
          {clubLabel.toUpperCase()}
        </span>
      ) : null}
    </div>
  );
};

export default { Layer, order: 25 };
