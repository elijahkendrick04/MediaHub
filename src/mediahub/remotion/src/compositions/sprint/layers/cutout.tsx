/**
 * R1.9 — Cutout-layer compositing in motion (additive sprint overlay).
 *
 * Composites the athlete cut out from their photo (an alpha PNG prepared
 * server-side by `visual/motion.py::_cutout_data_uri_for_brief`, using the
 * same configured background remover the still renderer uses) as a SEPARATE
 * animated FOREGROUND plane with parallax: a sharp subject standing proud of
 * the scrimmed full-bleed background photo the scenes already paint, so the
 * card gains real depth instead of one flat plane.
 *
 * Honest + safe by construction:
 *  - Pure function of the frame (Remotion `interpolate` + frame-derived
 *    sinusoids) — no `Math.random`, no wallclock, byte-identical re-renders.
 *  - The cutout's horizontal drift + vertical float is orthogonal to the
 *    background's vertical drift and slow scale, so the two planes visibly
 *    separate (true parallax). Ambient displacement is held ≤ 24px so the cut
 *    edge never travels far enough to reveal background it can't show.
 *  - Strict no-op when no cutout was prepared (`cutoutSrc === ""`): cards
 *    without a sourced photo (or rendered where no remover is installed) look
 *    exactly as they did before this layer landed.
 *  - The subject stands OPPOSITE the scene's dominant text (composition-aware,
 *    matching StoryCard.compositionLayoutFor) so it frames the copy rather
 *    than covering it; left-side subjects mirror (face inward) like the still.
 */
import React from "react";
import { Easing, interpolate, useVideoConfig } from "remotion";
import type { SceneComponent } from "../registry";
import {
  PhotoFilterDefs,
  photoExactGradeFor,
  photoHalftoneMaskFor,
} from "./photo_filters";

type Placement = { side: "left" | "right"; widthPct: number; heightPct: number };

// The layered-depth archetype scenes (M12 twins) paint the cutout themselves —
// this generic side-standing plane would double the athlete on top of them.
const SCENE_OWNED_ARCHETYPES = new Set(["poster_name_behind", "band_break"]);

// Stand the subject opposite the scene's dominant text. text-right
// compositions pull it left; a centred hero gets a shorter, low-corner figure
// that clears vertically-centred type; everything else takes the still's
// default right side.
function placementFor(composition: string): Placement {
  switch ((composition || "").toLowerCase()) {
    case "right":
      return { side: "left", widthPct: 0.5, heightPct: 0.86 };
    case "center":
      return { side: "right", widthPct: 0.46, heightPct: 0.68 };
    default:
      return { side: "right", widthPct: 0.5, heightPct: 0.86 };
  }
}

const Layer: SceneComponent = ({ ctx }) => {
  const { card, roles, frame, fps } = ctx;
  const { durationInFrames } = useVideoConfig();
  const cutout = card.cutoutSrc || "";
  if (!cutout) {
    // No prepared cutout → render nothing (byte-identical to pre-R1.9).
    return null;
  }
  // STILLS-2 / M8 parity: a "photo"-mode archetype shows the ORIGINAL
  // photograph on the still — never a composited cutout plane (belt-and-braces
  // beside motion.py sending an empty cutoutSrc). The M12 layered archetypes
  // own their cutout choreography in their scenes. M23: a footage beat plays
  // real video — a frozen cutout plane over moving footage would read as a
  // sticker, so footage implies no cutout, ever.
  if (
    card.photoMode === "photo" ||
    card.videoSrc ||
    SCENE_OWNED_ARCHETYPES.has(card.archetype || "")
  ) {
    return null;
  }

  const { side, widthPct, heightPct } = placementFor(card.composition || "");

  // Build: the subject rises into frame and fades in a beat behind the hero
  // text, so it reads as a layered reveal rather than a co-entry. The rise is
  // eased (composed) and the opacity ramp is shorter, so it has settled before
  // it is fully opaque. First motion is offset off frame 0 (never a jump cut).
  const enter = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const riseY = (1 - enter) * 64;
  const opacity = interpolate(frame, [fps * 0.2, fps * 0.62], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Breathe: ambient parallax. A slow Ken-Burns-style push plus frame-derived
  // horizontal drift and vertical float — all on the IMG, so it never fights
  // the wrapper's entrance transform. Drift direction is seed-keyed so sibling
  // cards in a pack don't bob in lockstep. Combined ambient displacement stays
  // ≤ 24px (≈14 + ≈9).
  const dur = Math.max(durationInFrames, fps);
  const push = interpolate(frame, [0, dur], [1.0, 1.05], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.sin),
  });
  const dir = (card.variationSeed | 0) % 2 === 0 ? 1 : -1;
  const secs = frame / fps;
  const driftX = Math.sin(secs * 0.7) * 14 * dir;
  const floatY = Math.cos(secs * 0.55) * 9;

  // Left-side subjects mirror to face into the card — the still's scaleX(-1).
  const mirror = side === "left" ? " scaleX(-1)" : "";
  const ground = roles.ground || "#000000";
  const sideStyle: React.CSSProperties =
    side === "left" ? { left: "-4%" } : { right: "-4%" };

  // M10 exact-mirror grade parity: the still applies its duotone SVG filter /
  // halftone mask to the cutout img itself (img.athlete-cutout), REPLACING the
  // depth shadow (CSS specificity). Mirror exactly; ungraded cards keep the
  // grounded drop-shadow untouched.
  const exactGrade = photoExactGradeFor(card);
  const mask = photoHalftoneMaskFor(card);

  return (
    <div
      style={{
        position: "absolute",
        bottom: "-3%",
        width: `${widthPct * 100}%`,
        height: `${heightPct * 100}%`,
        transform: `translateY(${riseY}px)`,
        opacity,
        ...sideStyle,
      }}
    >
      <PhotoFilterDefs card={card} />
      <img
        src={cutout}
        alt=""
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          objectPosition: "bottom center",
          transform: `translate(${driftX}px, ${floatY}px) scale(${push})${mirror}`,
          transformOrigin: "bottom center",
          // Seat the subject on the scrimmed background with a grounded shadow
          // (the brand ground at alpha) — never recolours the photo itself.
          filter:
            exactGrade ||
            `drop-shadow(0 16px 28px ${ground}AA) drop-shadow(0 3px 7px ${ground}70)`,
          ...(mask ?? {}),
        }}
      />
    </div>
  );
};

export default { Layer, order: 30 };
