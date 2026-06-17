/**
 * Subtitle / caption burn-in overlay — roadmap R1.3.
 *
 * Most feed video autoplays muted, so the words a card/reel narrates have to be
 * on the screen too. The Python engine (`visual/subtitle_burn.py`) reads the
 * voiceover SRT, picks an APCA-gated ink + brand-ground scrim, and hands this
 * layer a frame-timed track via `card.captionsJson`. We just paint it.
 *
 * Frame-pure and additive: when `captionsJson` is empty (every render that
 * hasn't opted into subtitles) this returns null, so the composition is
 * byte-identical to before the seam landed. One cue is visible at a time —
 * each rides its own `<Sequence>` window, so a group can never linger past its
 * end by construction (motion-craft: don't re-implement visibility with opacity
 * arithmetic).
 */
import React from "react";
import { interpolate, Sequence, useCurrentFrame, Easing } from "remotion";
import type { SceneComponent, SceneCtx } from "../registry";

// Captions are body text, not display — lead with the readable Inter stack (the
// same self-hosted family MeetReel uses for chips), never a CDN.
const CAPTION_FONT =
  "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif";

type Cue = { from: number; dur: number; text: string };
type CaptionTrack = { color: string; scrim: string; cues: Cue[] };

function parseTrack(json: string): CaptionTrack | null {
  if (!json) {
    return null;
  }
  try {
    const t = JSON.parse(json) as CaptionTrack;
    if (!t || !Array.isArray(t.cues) || t.cues.length === 0) {
      return null;
    }
    return t;
  } catch {
    return null;
  }
}

// Append an 8-bit alpha to a #RRGGBB hex (solid scrim band — no full-frame
// gradient, so no H.264 banding on dark grounds).
function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return /^#[0-9a-fA-F]{6}$/.test(hex) ? `${hex}${a}` : hex;
}

const CaptionCue: React.FC<{
  cue: Cue;
  color: string;
  scrim: string;
  ctx: SceneCtx;
}> = ({ cue, color, scrim, ctx }) => {
  const frame = useCurrentFrame(); // Sequence-relative
  const { ts, width, height } = ctx;
  const landscape = width > height;

  // rise-in: the workhorse caption entrance (translateY 16→0 + opacity 0→1,
  // ~9 frames, ease-out cubic). Pure function of the frame.
  const enter = interpolate(frame, [0, 9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const y = (1 - enter) * 16;

  // Lower band; a touch higher on tall cuts so it clears the platform chrome
  // (~bottom 320px on story) and the card's own bottom strip.
  const bottom = Math.round(height * (landscape ? 0.09 : 0.14));

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
        opacity: enter,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          maxWidth: Math.round(width * 0.82),
          margin: `0 ${Math.round(width * 0.06)}px`,
          padding: `${Math.round(14 * ts)}px ${Math.round(28 * ts)}px`,
          background: withAlpha(scrim, 0.82),
          color,
          borderRadius: Math.round(14 * ts),
          fontFamily: CAPTION_FONT,
          fontSize: Math.round(42 * ts),
          fontWeight: 800,
          lineHeight: 1.18,
          letterSpacing: "0.005em",
          textAlign: "center",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {cue.text}
      </div>
    </div>
  );
};

const Layer: SceneComponent = ({ ctx }) => {
  const track = parseTrack(ctx.card.captionsJson || "");
  if (!track) {
    return null;
  }
  // The engine resolves the APCA-gated ink + scrim; fall back to the card's
  // resolved roles if an older payload omitted them.
  const color = track.color || ctx.roles.onGround || "#FFFFFF";
  const scrim = track.scrim || ctx.roles.ground || "#0A0B11";
  return (
    <>
      {track.cues.map((cue, i) => (
        <Sequence key={`cap-${i}`} from={cue.from} durationInFrames={cue.dur}>
          <CaptionCue cue={cue} color={color} scrim={scrim} ctx={ctx} />
        </Sequence>
      ))}
    </>
  );
};

// High order so captions paint on top of the scene and every decorative layer.
export default { Layer, order: 90 };
