/**
 * logo_anim.tsx — Dynamic logo sizing + scene-aware animated logo reveal
 * (roadmap R1.23). An additive overlay: rendered over every StoryCard scene by
 * the sprint layer registry, as a pure function of the frame.
 *
 * What it does
 * ------------
 * Each built-in scene paints a *static* corner logo chip that simply fades in
 * on the shared `chipOpacity` channel (StoryCard `LogoChip`). This overlay
 * gives that same mark a real, scene-aware *entrance* — a drop, a scale-pop, a
 * slide off the matching edge — and a per-scene *size* drawn from a
 * small / medium / large / auto system. It re-renders the brand logo at the
 * chip's exact resting slot, lands there before the static chip's own (later,
 * slower) fade becomes visible, then holds — so a render shows a single,
 * choreographed logo, never a double image.
 *
 * Why an overlay (and why it cannot just edit the scene)
 * ------------------------------------------------------
 * The generator sprint keeps every capability in its own file so parallel
 * sessions never touch `StoryCard.tsx` (see sprint/registry.ts). That means no
 * new prop field (zod strips undeclared keys) and no edit to the shared
 * `LogoChip`. The overlay therefore works purely from the existing `SceneCtx`
 * and is designed to *coincide* with the static chip at rest rather than fight
 * it: same image, same slot, same per-scene size → one logo on screen.
 *
 * Brand-locked + fact-exact: the only thing ever drawn is the operator's own
 * `brand.logoDataUri`; nothing is invented. Deterministic: the slot, the size
 * and every entrance channel are pure functions of `frame` / `fps`, so renders
 * stay byte-identical and motion cache keys hold.
 */
import React from "react";
import { Easing, interpolate } from "remotion";
import type { SceneComponent } from "../registry";

// Scene families mirror StoryCard.tsx `sceneForArchetype`, kept as a local copy
// so the overlay never reaches into scene internals. An archetype StoryCard has
// not mapped here falls through to "hero" — exactly StoryCard's own default —
// so the logo is always sized and animated (never blank, never a crash).
type SceneMode =
  | "hero"
  | "poster"
  | "lowerThird"
  | "spotlight"
  | "grid"
  | "ticker"
  | "split"
  | "magazine";

function sceneModeFor(archetype: string): SceneMode {
  switch (archetype) {
    case "big_number_dominant":
    case "minimal_type_poster":
    case "quote_led_recap":
    case "cornerstone_numeral":
    case "mega_surname_bleed":
      return "poster";
    case "full_bleed_photo_lower_third":
    case "broadcast_scorebug":
      return "lowerThird";
    case "centered_medal_spotlight":
    case "photo_passepartout":
    case "spotlight_disc":
      return "spotlight";
    case "editorial_numbers_grid":
    case "stat_stack_sidebar":
    case "index_card":
    case "scoreline_versus":
      return "grid";
    case "ticker_strip":
    case "horizon_band":
      return "ticker";
    case "split_diagonal_hero":
    case "duo_athlete_split":
    case "triptych_progression":
      return "split";
    case "magazine_cover":
      return "magazine";
    default:
      return "hero";
  }
}

// ---------------------------------------------------------------------------
// Dynamic sizing
// ---------------------------------------------------------------------------
// small / medium / large are the three distinct logo sizes the built-in scenes
// already use (110 / 120 / 140 px at the 1080×1920 design scale). "auto" — the
// only tier reachable today, there being no operator field — maps each scene to
// the size its static chip uses, so the animated mark lands exactly on top of
// it (parity, no second logo). The explicit tiers stay available for a future
// caller that wires a logo-size field through.
export type LogoSizeTier = "small" | "medium" | "large" | "auto";

const LOGO_TIER_PX: Record<Exclude<LogoSizeTier, "auto">, number> = {
  small: 110, // SpotlightScene's chip
  medium: 120, // Poster / LowerThird chips
  large: 140, // Hero / Grid / Ticker / Split chips (the LogoChip default)
};

function autoTierFor(mode: SceneMode): Exclude<LogoSizeTier, "auto"> {
  switch (mode) {
    case "spotlight":
      return "small";
    case "poster":
    case "lowerThird":
    case "magazine":
      // poster / lowerThird match their chip; magazine has no static chip, so
      // it simply gains a tasteful, medium brand bug in the same slot.
      return "medium";
    default:
      return "large";
  }
}

export function logoBasePx(mode: SceneMode, tier: LogoSizeTier): number {
  const resolved = tier === "auto" ? autoTierFor(mode) : tier;
  return LOGO_TIER_PX[resolved];
}

// ---------------------------------------------------------------------------
// Scene-aware entrance
// ---------------------------------------------------------------------------
// Each scene family reveals the logo with motion that matches its choreography:
// the broadcast lower-third and the wire-service ticker slide off the right
// edge, the poster pops up in scale, the spotlight badge swells symmetrically,
// the editorial grid drops crisply from above. Every entrance is a pure
// function of a 0→1 progress and resolves to the identity transform
// (dx=0, dy=0, scale=1) at p=1, so it parks exactly on the static chip.
type Entrance = { dx: number; dy: number; scale: number };

function entranceFor(mode: SceneMode, p: number): Entrance {
  // Ease the raw reveal progress; `inv` is 1 at the start, 0 once parked.
  const e = interpolate(p, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const inv = 1 - e;
  switch (mode) {
    case "lowerThird":
    case "ticker":
    case "split":
      // Slide in from the right edge — the broadcast / wire-service motion.
      return { dx: inv * 160, dy: 0, scale: 1 };
    case "poster":
      // Scale-pop: the poster is about size, so the logo grows into place.
      return { dx: 0, dy: 0, scale: 0.7 + 0.3 * e };
    case "spotlight":
      // Symmetric badge swell, matching the ring badge it sits above.
      return { dx: 0, dy: 0, scale: 0.6 + 0.4 * e };
    case "grid":
      // Editorial drop from above, crisp and square.
      return { dx: 0, dy: inv * -70, scale: 1 };
    case "magazine":
      // Masthead elegance — a gentle settle from slightly small, no slide.
      return { dx: 0, dy: 0, scale: 0.88 + 0.12 * e };
    case "hero":
    default:
      // Hero: drops in from above with a small scale lift.
      return { dx: 0, dy: inv * -90, scale: 0.92 + 0.08 * e };
  }
}

// The reveal opens a few frames in — never frame 0, since a t=0 entrance reads
// as a jump cut (motion-craft) — and is fully parked before any scene's static
// chip starts to fade in. The earliest static chip appears at fps*0.6 (the
// snap_in_then_settle intent's `chipOpacity` in StoryCard), so ending the
// reveal at fps*0.52 always finishes first and the two never read as two logos.
// The "static" motion intent shows everything from frame 0, so its logo skips
// the entrance entirely and sits at rest immediately, coincident with the
// always-on static chip.
const REVEAL_START_SEC = 0.12;
const REVEAL_END_SEC = 0.52;

const Layer: SceneComponent = ({ ctx }) => {
  const { brand, card, frame, fps, width, ts } = ctx;
  // Nothing to reveal without a logo — this mirrors the static chip's own
  // guard, so logo-less brands render byte-identically to before the overlay.
  if (!brand.logoDataUri) {
    return null;
  }

  const mode = sceneModeFor(card.archetype || "");
  const isStatic = (card.motionIntent || "") === "static";
  const revealStart = fps * REVEAL_START_SEC;
  const revealEnd = fps * REVEAL_END_SEC;

  // Progress along the reveal (0→1); the static intent is parked from frame 0.
  const p = isStatic
    ? 1
    : interpolate(frame, [revealStart, revealEnd], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
  const move = entranceFor(mode, p);

  // Opacity reaches full a touch before the transform settles, so the mark is
  // legible as it lands, then holds at 1 (the slower static-chip fade catches
  // up underneath at the same slot — so there is never a second visible logo).
  const opacity = isStatic
    ? 1
    : interpolate(
        frame,
        [revealStart, revealStart + (revealEnd - revealStart) * 0.7],
        [0, 1],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );

  const sizePx = Math.round(logoBasePx(mode, "auto") * ts);
  // Exactly the static LogoChip slot (StoryCard): top 100·ts, right min(80, 6%).
  const top = Math.round(100 * ts);
  const right = Math.min(80, width * 0.06);

  return (
    <img
      src={brand.logoDataUri}
      alt={brand.displayName || "club logo"}
      style={{
        position: "absolute",
        top,
        right,
        width: sizePx,
        height: sizePx,
        objectFit: "contain",
        opacity,
        transform: `translate(${move.dx}px, ${move.dy}px) scale(${move.scale})`,
        transformOrigin: "top right",
        pointerEvents: "none",
      }}
    />
  );
};

// order 50: paints late, so the animated mark sits above the scene's decorative
// layers and on top of the static chip it coincides with.
export default { Layer, order: 50 };
