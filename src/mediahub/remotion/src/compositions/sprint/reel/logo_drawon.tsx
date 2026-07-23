// svg-shape-decompose — opt-in logo draw-on for the reel's two "brand
// statement" scenes (cover + outro). The persistent club_mark bug and the
// per-card logo overlay are deliberately untouched.
//
// The brand logo is normally an opaque `<img src={dataUri}>` (a base64 SVG),
// so no per-path element exists to trim-path. This component keeps that exact
// `<img>` as the RESTING frame (brand fidelity + still↔motion parity) and,
// ONLY when the caller opted in AND Python decomposed the SVG into per-path
// data, overlays an inline `<svg>` whose paths stroke on via
// strokeDasharray/strokeDashoffset, then cross-fades into the real filled
// `<img>` so the settled logo is pixel-identical to the original.
//
// Frame-pure: `progress` is the site's own interpolate/spring clock (a pure
// function of useCurrentFrame); the per-path stagger is a closed-form function
// of index + progress. Path lengths are computed Python-side (deterministic
// arc-length), so the browser never measures them at render time. No wall-clock
// reads and no randomness.
//
// Brand-locked: the transient stroke uses each path's OWN resolved
// fill/stroke colour — never an invented hue.
import React from "react";
import { interpolate } from "remotion";

export type LogoDrawPath = { d: string; len: number; stroke: string };

export type LogoDrawConfig = {
  // Active only when the caller opted in AND at least one path decomposed.
  on: boolean;
  viewBox: string;
  paths: LogoDrawPath[];
};

type LogoDrawOnProps = {
  logoDataUri: string;
  alt: string;
  style: React.CSSProperties;
  draw: LogoDrawConfig;
  // The site's local reveal clock (0→1): StackCover's logoScale, MastheadCover's
  // logoOpacity, Outro's grow — a pure function of the frame.
  progress: number;
};

// The stroke completes over this fraction of the local clock, leaving a tail
// for the fill cross-fade; each path is staggered inside it.
const DRAW_END = 0.85;
const PATH_SPAN = 0.55;
// The filled <img> fades in over the final stretch so the settled frame is the
// exact original logo.
const FILL_START = 0.7;

export const LogoDrawOn: React.FC<LogoDrawOnProps> = ({
  logoDataUri,
  alt,
  style,
  draw,
  progress,
}) => {
  // No logo → render nothing, byte-identical to the sites' `logoDataUri ? … :
  // null` guard.
  if (!logoDataUri) {
    return null;
  }
  // Inactive → the EXACT original `<img>` DOM (each site passes its own full
  // style object verbatim), so a feature-off reel is byte-identical.
  if (!draw || !draw.on || !draw.paths || draw.paths.length === 0) {
    return <img src={logoDataUri} alt={alt} style={style} />;
  }

  const p = Math.min(1, Math.max(0, progress));
  const fillIn = interpolate(p, [FILL_START, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const n = draw.paths.length;
  const gap = n > 1 ? (DRAW_END - PATH_SPAN) / (n - 1) : 0;

  // Split the original img style so the wrapper occupies the EXACT same box the
  // img would have — positioning (position/top/right/margin/transform) and the
  // site's opacity clock ride on the wrapper; the img keeps its intrinsic
  // sizing (width/height/objectFit) so a width-less site (a band logo sized by
  // its own aspect ratio) still measures correctly. The svg then overlays that
  // box precisely, and at rest (fillIn→1, svg gone) the settled logo matches
  // the original filled `<img>`.
  const {
    width,
    height,
    objectFit,
    opacity: styleOpacity,
    position,
    ...boxRest
  } = style;
  const baseOpacity = typeof styleOpacity === "number" ? styleOpacity : 1;

  return (
    <div
      style={{
        ...boxRest,
        position: position ?? "relative",
        display: "inline-flex",
        opacity: baseOpacity,
      }}
    >
      <img
        src={logoDataUri}
        alt={alt}
        style={{ width, height, objectFit, display: "block", opacity: fillIn }}
      />
      {fillIn < 1 ? (
        <svg
          viewBox={draw.viewBox || undefined}
          preserveAspectRatio="xMidYMid meet"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            overflow: "visible",
            pointerEvents: "none",
          }}
        >
          {draw.paths.map((path, i) => {
            const start = i * gap;
            const pLocal = interpolate(p, [start, start + PATH_SPAN], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const len = path.len > 0 ? path.len : 1;
            return (
              <path
                key={i}
                d={path.d}
                fill="none"
                stroke={path.stroke}
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={len}
                strokeDashoffset={len * (1 - pLocal)}
              />
            );
          })}
        </svg>
      ) : null}
    </div>
  );
};

export default LogoDrawOn;
