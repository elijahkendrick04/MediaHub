/**
 * R1.8 — Photo scrim variant system (motion).
 *
 * An additive overlay (auto-discovered by ../registry; NO StoryCard.tsx edit)
 * that paints a *role-driven legibility scrim* over photo cards in one of four
 * deliberately distinct shapes — `gradient` / `edge` / `radial` / `corner`.
 * Each scene already lays its own under-text scrim inside `PhotoLayer`; this is
 * the *finish* on top: it reinforces legibility at the periphery and gives a
 * pack visible scrim variety, while leaving the central band — where the
 * subject and the hero text live — untouched. So it can paint over the scene
 * (text included) without ever reducing the contrast of the copy.
 *
 * Non-negotiables it honours (mediahub-engineering / motion-craft):
 *   - Photo-only. With no attached photo there is nothing to scrim and
 *     darkening a flat brand ground would only muddy it, so non-photo cards
 *     render byte-identically to before this layer existed.
 *   - Role-driven colour ONLY. The scrim is the resolved ground role at a
 *     capped alpha — never an invented hex, never a recolour of the photo
 *     (the photo is evidence).
 *   - Deterministic. The variant is a pure function of the card (its seed,
 *     plus a still↔motion parity special-case), so the same props render the
 *     same frame. No `Math.random`, no wallclock.
 *   - Frame-pure. The scrim eases in off the frame (composed, not a frame-0
 *     pop) and then holds — a scrim is a finish, not a moving element.
 *
 * Stacking order among sprint overlays (lower paints first / underneath):
 *   ~10 background/pattern drift · ~20 photo filters · **30 photo scrim** ·
 *   ~40 foreground cutout · ~50 text effects · ~70 logo · ~90 role transition.
 * 30 sits the scrim above any photo-filter treatment but below a foreground
 * cutout, the on-video text effects, the logo, and the global colour wash.
 */
import { Easing, interpolate } from "remotion";
import type { SceneComponent, SceneCtx } from "../registry";

type ScrimVariant = "gradient" | "edge" | "radial" | "corner";

// Deterministic order indexed by (variationSeed mod 4). `gradient` sits at 0 —
// the gentlest, most neutral shape — so the common seed-0 default card gets the
// calmest scrim, with the more sculpted shapes earned by later seeds.
const VARIANTS: ScrimVariant[] = ["gradient", "edge", "radial", "corner"];

// Peak scrim alpha per variant (0..1), capped low on purpose: this paints OVER
// the scene's own under-text scrim, so it only reinforces the edges and never
// approaches the heavy bottom-band darkening a scene applies beneath its copy.
const PEAK_ALPHA: Record<ScrimVariant, number> = {
  gradient: 0.34,
  edge: 0.3,
  radial: 0.34,
  corner: 0.32,
};

/**
 * Pick the scrim variant deterministically from the card.
 *
 * Still↔motion parity: when the approved still chose the `vignette` photo
 * treatment, the motion scrim is the matching soft radial vignette. Otherwise
 * the seed selects one of the four shapes so a pack reads varied, not samey.
 */
export function scrimVariantFor(card: SceneCtx["card"]): ScrimVariant {
  if ((card.photoTreatment || "").toLowerCase() === "vignette") {
    return "radial";
  }
  const n = VARIANTS.length;
  return VARIANTS[(((card.variationSeed | 0) % n) + n) % n];
}

/** True for a clean #RGB or #RRGGBB role colour — the only inputs we tint. */
function isHexColour(s: string): boolean {
  return /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test((s || "").trim());
}

/**
 * Role colour + 0..1 alpha → #RRGGBBAA. The hue is always the role's own — we
 * only vary the alpha — so the scrim can never introduce a colour the brand
 * did not resolve. Caller guarantees `hex` is a valid #RGB/#RRGGBB.
 */
function withAlpha(hex: string, alpha: number): string {
  let h = hex.trim().slice(1);
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  const a = Math.max(0, Math.min(1, alpha));
  const aa = Math.round(a * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${h}${aa}`;
}

/**
 * The CSS `background` for a variant, painted entirely in the ground role.
 * Every shape keeps the centre fully transparent (a `…00` stop of the SAME
 * hue, which avoids the grey fringing a `transparent`-keyword stop can give),
 * so the subject and hero copy are never darkened.
 */
function scrimBackground(variant: ScrimVariant, ground: string): string {
  const peak = PEAK_ALPHA[variant];
  const at = (mul: number) => withAlpha(ground, peak * mul);
  const clear = withAlpha(ground, 0);
  const backgrounds: Record<ScrimVariant, string> = {
    // Bottom-weighted wash — reinforces lower-third captions; top stays clear.
    gradient: `linear-gradient(0deg, ${at(1)} 0%, ${at(0.55)} 16%, ${clear} 52%)`,
    // Straight-edge frame — darkens all four margins, central band untouched.
    edge: [
      `linear-gradient(90deg, ${at(1)} 0%, ${clear} 13%, ${clear} 87%, ${at(1)} 100%)`,
      `linear-gradient(180deg, ${at(1)} 0%, ${clear} 15%, ${clear} 85%, ${at(1)} 100%)`,
    ].join(", "),
    // Soft cinematic vignette — mirrors the still renderer's `.vignette`.
    radial: `radial-gradient(ellipse 75% 64% at 50% 48%, ${clear} 0%, ${clear} 46%, ${at(1)} 100%)`,
    // Diagonal corner weighting (top-left + bottom-right) — editorial, asymmetric.
    corner: [
      `radial-gradient(ellipse 58% 48% at 0% 0%, ${at(1)} 0%, ${clear} 58%)`,
      `radial-gradient(ellipse 58% 48% at 100% 100%, ${at(1)} 0%, ${clear} 58%)`,
    ].join(", "),
  };
  return backgrounds[variant];
}

const Layer: SceneComponent = ({ ctx }) => {
  const { card, roles, frame } = ctx;
  // Photo-only — see header. Non-photo cards stay identical.
  if (!card.photoSrc) {
    return null;
  }
  const ground = roles.ground || "";
  if (!isHexColour(ground)) {
    // Role-driven only: with no valid ground role we paint nothing rather than
    // invent a colour.
    return null;
  }

  const variant = scrimVariantFor(card);
  // Ease the scrim in with the scene (composed, never a frame-0 pop); it then
  // holds for the rest of the beat.
  const enter = interpolate(frame, [3, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: scrimBackground(variant, ground),
        opacity: enter,
        pointerEvents: "none",
      }}
    />
  );
};

export default { Layer, order: 30 };
