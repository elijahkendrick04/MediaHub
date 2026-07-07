/**
 * R1.11 — On-video text-effect library (additive overlay).
 *
 * A small, owned vocabulary of frame-pure text effects that ride over every
 * card without touching the shared scene components:
 *
 *   glow · outline · 3D-shadow (shadow3d) · stroke-animate · blur-to-focus
 *
 * How it stays additive (no StoryCard.tsx / scene edits)
 * -----------------------------------------------------
 * The scenes render their type with inline styles and no class hooks, and this
 * overlay paints as a *later sibling* of the card — it is never an ancestor of
 * the scene text, so it cannot style it inline. Instead it injects ONE scoped
 * stylesheet rule that reaches the scene's text through CSS inheritance:
 *
 *   - `text-shadow` IS an inherited property, so a value set on the card root
 *     flows down to every text node the scenes drew. glow / outline / shadow3d
 *     / stroke-animate are all expressed as `text-shadow` in `em` units, so the
 *     effect scales with each element's own font-size (a 168px hero gets a bold
 *     keyline; a 16px chip gets a hairline) and reads tasteful everywhere.
 *   - `filter` is NOT inherited, so blur-to-focus sets `filter: blur()` on the
 *     card root alone — one element, no compounding — and the whole composited
 *     frame blooms into focus.
 *
 * The rule is anchored to *this* card's root with `:has()`: the overlay drops an
 * invisible marker as a direct child of the root, and the selector
 * `*:has(> [data-mh-textfx="<id>"])` therefore resolves to exactly that root.
 * `<id>` is a per-instance `useId()`, so two cards in one reel (e.g. a glow card
 * cross-fading into an outline card) never bleed each other's effect. If a
 * runtime lacks `:has()` the rule simply never matches and the text renders
 * unstyled — a safe degrade, never a broken card. (The render Chromium and all
 * current browsers support `:has()`.)
 *
 * Non-negotiables honoured (motion-craft "Hard bounds"):
 *   1. Pure function of the frame — the `<style>` is regenerated every frame
 *      from `interpolate(ctx.frame, …)` (clamped, eased). No CSS @keyframes,
 *      `transition:`, or `animation:` — those don't render under Remotion.
 *   2. Deterministic — the effect is chosen from the brief's `mood` /
 *      `accentStyle`; no `Math.random()` / `Date.now()`. Same props → same render.
 *   3. Brand-exact — every colour comes from the resolved `ctx.roles` (the same
 *      APCA-gated set the still painted); no invented hex.
 *   4. Legibility-positive — outline/shadow use the dark `ground` role behind the
 *      light `onGround` text (a keyline over busy photos *raises* contrast) and
 *      `text-shadow` always paints behind the glyph fill, so the fill stays crisp.
 *   5. Legacy-safe — restraint moods (neutral / minimal / stoic) and brief-less
 *      callers resolve to "none" and the overlay renders nothing, so existing
 *      motion is unchanged; only an expressively-directed card earns an effect.
 *
 * No new prop or cache-key field: the effect derives from axes already in the
 * card payload (`mood`, `accentStyle`), so the render cache key is untouched.
 * (A future explicit director field — P6.7 text-effect tokens — can map onto the
 * same recipes without changing this layer's contract.)
 */
import React from "react";
import { Easing, interpolate } from "remotion";
import type { Roles, SceneComponent, SceneCtx } from "../registry";

type Effect =
  | "none"
  | "glow"
  | "outline"
  | "shadow3d" // roadmap "3D-shadow"
  | "stroke_animate" // roadmap "stroke-animate"
  | "blur_to_focus"; // roadmap "blur-to-focus"

// Mood → effect. Expressive moods earn an effect that matches their feel; the
// restraint moods (neutral / minimal / stoic) are deliberately absent and fall
// through to "none". Every one of the five effects is reachable from this map.
const MOOD_FX: Record<string, Effect> = {
  electric: "glow",
  explosive: "glow",
  fierce: "outline",
  bold: "outline",
  triumphant: "shadow3d",
  celebratory: "shadow3d",
  precise: "stroke_animate",
  calm: "blur_to_focus",
  warm: "blur_to_focus",
};

// When the mood is unmapped (or absent), let the still's accent treatment drive
// the keyline so a card stays in lock-step with the accent the customer
// approved — a drawn underline pairs with `underline`, a frame with `outline`,
// a badge/ribbon with depth.
const ACCENT_FX: Record<string, Effect> = {
  underline: "stroke_animate",
  diagonal_underline: "stroke_animate",
  stripe: "outline",
  frame: "outline",
  badge: "shadow3d",
  ribbon: "shadow3d",
};

function chooseEffect(ctx: SceneCtx): Effect {
  const mood = (ctx.card.mood || "").toLowerCase();
  // Hard restraint: a stoic / minimal card never gets text energy, whatever
  // accent it carries.
  if (mood === "stoic" || mood === "minimal" || mood === "neutral") {
    return "none";
  }
  if (MOOD_FX[mood]) {
    return MOOD_FX[mood];
  }
  const accent = (ctx.card.accentStyle || "").toLowerCase();
  return ACCENT_FX[accent] || "none";
}

// Append an alpha byte to a #RRGGBB role colour; pass anything else through
// untouched so we never fabricate a colour. `alpha` is 0–255.
function withAlpha(hex: string, alpha: number): string {
  if (typeof hex === "string" && hex.length === 7 && hex[0] === "#") {
    const a = Math.max(0, Math.min(255, Math.round(alpha)));
    return hex + a.toString(16).padStart(2, "0");
  }
  return hex;
}

// A multi-direction `em` text-shadow keyline (a faux outline that scales with
// each element's font-size and keeps the glyph fill crisp on top). `w` is the
// stroke width in em; 0 yields no shadow (used while a stroke animates on).
function keyline(colour: string, w: number): string {
  if (w <= 0) {
    return "none";
  }
  const o = w.toFixed(4);
  const d = (w * 0.72).toFixed(4); // diagonals a touch tighter
  return [
    `${o}em 0 0 ${colour}`,
    `-${o}em 0 0 ${colour}`,
    `0 ${o}em 0 ${colour}`,
    `0 -${o}em 0 ${colour}`,
    `${d}em ${d}em 0 ${colour}`,
    `-${d}em ${d}em 0 ${colour}`,
    `${d}em -${d}em 0 ${colour}`,
    `-${d}em -${d}em 0 ${colour}`,
  ].join(", ");
}

// The text-shadow / filter declarations for one effect at one frame. Returns
// the CSS body (without selector) to drop into the scoped rule.
function declarationsFor(
  effect: Effect,
  roles: Roles,
  frame: number,
  fps: number,
  minDim: number,
): string {
  const ink = roles.ground || "#000000"; // dark brand role → legible keyline
  const accent = roles.accent || "#FFFFFF";
  const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

  switch (effect) {
    case "glow": {
      // Soft accent halo. Inherited; fades in with the text's own opacity ramp.
      const a = withAlpha(accent, 0xcc);
      const b = withAlpha(accent, 0x66);
      return `text-shadow: 0 0 0.08em ${a}, 0 0 0.18em ${a}, 0 0 0.34em ${b};`;
    }
    case "outline": {
      // A steady dark keyline around every glyph (legibility over photos).
      return `text-shadow: ${keyline(ink, 0.03)};`;
    }
    case "shadow3d": {
      // Stepped down-right extrude in the ground role for depth.
      const soft = withAlpha(ink, 0x99);
      return (
        `text-shadow: 0.024em 0.024em 0 ${ink}, 0.048em 0.048em 0 ${ink}, ` +
        `0.072em 0.072em 0 ${soft}, 0.096em 0.096em 0.02em ${soft};`
      );
    }
    case "stroke_animate": {
      // Keyline drawn on: width 0 → target over ~0.5s, then held. Frame-driven
      // (this whole rule is rebuilt each frame), so it stays frame-pure.
      const t = interpolate(frame, [3, 3 + fps * 0.5], [0, 1], {
        ...clamp,
        easing: Easing.out(Easing.cubic),
      });
      return `text-shadow: ${keyline(ink, 0.032 * t)};`;
    }
    case "blur_to_focus": {
      // The whole card blooms into focus. `filter` is not inherited, so this
      // applies once to the root only — no compounding down the tree.
      const maxBlur = Math.max(8, Math.round(minDim * 0.014));
      const b = interpolate(frame, [3, 3 + fps * 0.6], [maxBlur, 0], {
        ...clamp,
        easing: Easing.out(Easing.cubic),
      });
      return b > 0.05 ? `filter: blur(${b.toFixed(2)}px);` : "";
    }
    default:
      return "";
  }
}

const Layer: SceneComponent = ({ ctx }) => {
  // Unique per card instance → the scoped selector can never match a sibling
  // card's root, so reels with mixed effects don't bleed. Strip the punctuation
  // React adds (":r0:") so the value is a clean CSS attribute token.
  const fxId = React.useId().replace(/[^a-zA-Z0-9]/g, "");
  const effect = chooseEffect(ctx);
  if (effect === "none") {
    return null; // legacy-safe: restraint / brief-less cards render unchanged
  }

  const minDim = Math.min(ctx.width, ctx.height);
  const body = declarationsFor(effect, ctx.roles, ctx.frame, ctx.fps, minDim);
  if (!body) {
    return null; // e.g. blur already resolved to 0 — nothing to inject
  }

  // `:has(> …)` resolves to this card's root (the marker is a direct child of
  // it). `text-shadow` always paints behind the glyph fill, so the keyline
  // never hollows the type — no `paint-order` needed.
  const css = `*:has(> [data-mh-textfx="${fxId}"]){${body}}`;

  return (
    <>
      <style>{css}</style>
      <span
        data-mh-textfx={fxId}
        aria-hidden
        style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
      />
    </>
  );
};

export default { Layer, order: 60 };
