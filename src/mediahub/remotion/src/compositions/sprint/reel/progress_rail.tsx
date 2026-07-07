// M20 — reel progress rail: the whole-piece connective tissue every beat was
// missing. A thin accent-role bar along the top edge grows 0→100% across the
// card-beat window, with one tick mark at each beat start, so the viewer
// always feels where they are in the recap. Subdued during the cover's build
// and gone into the outro (the close belongs to the club mark alone).
//
// Frame-pure (interpolate over ctx.frame only — no CSS transitions, no
// wallclock, no randomness) and brand-exact: the only colour painted is the
// resolved accent role threaded through ReelCtx.
import React from "react";
import { Easing, interpolate } from "remotion";
import type { ReelLayer } from "../reelRegistry";

const Layer: ReelLayer = ({ ctx }) => {
  const { frame, fps, width, height, accent, beatStarts, outroStart, cardCount } = ctx;
  if (!cardCount || !beatStarts.length || outroStart <= beatStarts[0]) {
    return null;
  }
  const start = beatStarts[0];
  const span = outroStart - start;

  // Progress across the card-beat window — linear (it is a clock, not a
  // gesture), clamped at both ends.
  const progress = interpolate(frame, [start, outroStart], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Visible only while the beats play: eases in as the first beat lands,
  // eases out across the outro handoff.
  const visible = interpolate(
    frame,
    [start, start + Math.round(fps * 0.4), outroStart, outroStart + Math.round(fps * 0.35)],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.sin) },
  );
  if (visible <= 0) {
    return null;
  }

  const railH = Math.max(4, Math.round(Math.min(width, height) * 0.0055));
  const tickW = Math.max(2, Math.round(railH * 0.6));
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: 0,
        height: railH * 3,
        opacity: visible,
        pointerEvents: "none",
      }}
    >
      {/* Faint full-width track so the remaining time reads too. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: railH,
          background: accent,
          opacity: 0.22,
        }}
      />
      {/* The progress fill. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: `${(progress * 100).toFixed(3)}%`,
          height: railH,
          background: accent,
        }}
      />
      {/* One tick per beat start (the first sits at 0 — skip it). */}
      {beatStarts.slice(1).map((bs, i) => (
        <div
          key={`tick-${i}`}
          style={{
            position: "absolute",
            left: `${(((bs - start) / span) * 100).toFixed(3)}%`,
            top: 0,
            width: tickW,
            height: railH * 2,
            background: accent,
            opacity: 0.8,
          }}
        />
      ))}
    </div>
  );
};

export default { Layer, order: 20 };
