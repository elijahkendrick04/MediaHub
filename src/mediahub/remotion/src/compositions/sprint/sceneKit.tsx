/**
 * Scene kit — shared, self-contained helpers for sprint scene modes (R1.2).
 *
 * This file lives directly under `sprint/` (NOT inside a `require.context`-scanned
 * subfolder), so it is shared by the scene drops in `sprint/scenes/` without ever
 * being mistaken for a scene module and without one line of edit to
 * `StoryCard.tsx`. Every scene built on this kit stays:
 *
 *   • frame-pure      — animation is a pure function of `ctx.frame` / `ctx.fps`;
 *                        no `Math.random`, no `Date.now`, no wallclock.
 *   • brand-locked     — colour comes only from the resolved `ctx.roles`
 *                        (ground/surface/accent/onGround); never an invented hex
 *                        beyond ground-derived alpha scrims (the PhotoLayer
 *                        precedent in StoryCard.tsx).
 *   • fact-exact       — text is rendered from the pre-computed `ctx` fields; a
 *                        marquee/crawl carries `ctx.resultFinal` (the verified
 *                        value), never a mid-count number a viewer could screenshot.
 *
 * The helpers mirror the private cousins in `StoryCard.tsx` (`fitLinePx`,
 * `placeDisplay`, `LogoChip`, `BottomStrip`, `KineticLine`) so a sprint scene
 * reads like a built-in one — they are duplicated here only because those are
 * not exported, and the scene seam's whole point is to add capability without
 * touching the shared composition file.
 */
import React from "react";
import type { SceneCtx } from "./registry";
import { photoGradeFilterFor } from "./layers/photo_filters";

// Append an 8-bit alpha to a #rrggbb role hex (the StoryCard scrim precedent,
// e.g. `${roles.ground}B0`) — a named helper for scenes that build their own
// ground-tinted scrims (a split panel, a seam edge) where PhotoFill's
// full-frame gradients don't fit. Pass-through for an already-aliased value.
export function withAlpha(hex: string, a: number): string {
  const h = (hex || "").trim();
  if (!h.startsWith("#") || h.length < 7) {
    return h;
  }
  const v = Math.max(0, Math.min(255, Math.round(a * 255)));
  return `${h.slice(0, 7)}${v.toString(16).padStart(2, "0")}`;
}

// Deterministic single-line fit: shrink a base size until the estimated line
// width (chars × an average heavy-display glyph ratio) fits the box. The cheap
// TSX cousin of the still renderer's measured autofit — long surnames shrink
// instead of bleeding off-frame.
export function fitLine(
  text: string,
  basePx: number,
  maxWidth: number,
  glyphRatio = 0.58,
): number {
  const chars = Math.max(1, (text || "").length);
  const fitted = Math.floor(maxWidth / (chars * glyphRatio));
  return Math.max(36, Math.min(basePx, fitted));
}

// Split into whitespace words for per-word staggered reveals.
export function splitWords(text: string): string[] {
  return (text || "").split(/\s+/).filter(Boolean);
}

// Display ordinal for a real numeric placing ("1" → "1ST"); any non-numeric
// value passes through uppercased — never invent a placing that was not detected.
export function placeOrdinal(place: string): string {
  const m = (place || "").trim().match(/^(\d+)$/);
  if (!m) {
    return (place || "").trim().toUpperCase();
  }
  const n = parseInt(m[1], 10);
  const tens = n % 100;
  const suffix =
    tens >= 11 && tens <= 13
      ? "TH"
      : n % 10 === 1
        ? "ST"
        : n % 10 === 2
          ? "ND"
          : n % 10 === 3
            ? "RD"
            : "TH";
  return `${n}${suffix}`;
}

// A small, bounded, deterministic integer from the card's variation seed — the
// only sanctioned source of per-card variety (keeps parity with the still).
export function seedPick(ctx: SceneCtx, mod: number): number {
  const v = ctx.card.variationSeed | 0;
  return ((v % mod) + mod) % mod;
}

// Club logo, top-right — mirrors StoryCard's LogoChip (chip-channel fade).
export const ClubLogo: React.FC<{ ctx: SceneCtx; size?: number }> = ({
  ctx,
  size = 128,
}) => {
  const { brand, anim, width, ts } = ctx;
  if (!brand.logoDataUri) {
    return null;
  }
  const s = Math.round(size * ts);
  return (
    <img
      src={brand.logoDataUri}
      alt={brand.displayName || "club logo"}
      style={{
        position: "absolute",
        top: Math.round(96 * ts),
        right: Math.min(80, width * 0.06),
        width: s,
        height: s,
        objectFit: "contain",
        opacity: anim.chipOpacity,
      }}
    />
  );
};

// Meet • club footer — mirrors StoryCard's BottomStrip.
export const MetaFooter: React.FC<{ ctx: SceneCtx; tint?: string }> = ({
  ctx,
  tint,
}) => {
  const { roles, anim, ts, meet, club } = ctx;
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: Math.round(76 * ts),
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: Math.round(28 * ts),
        letterSpacing: "0.08em",
        color: tint || roles.onGround,
        opacity: anim.chipOpacity * 0.85,
        textTransform: "uppercase",
      }}
    >
      <span>{meet}</span>
      <span style={{ fontWeight: 700 }}>{club}</span>
    </div>
  );
};

// Per-word staggered line driven by the active intent's `anim.wordAt` channel —
// identity reveal for non-kinetic intents (the parent owns the motion), real
// per-word stagger for `kinetic_type`.
export const KineticWords: React.FC<{
  ctx: SceneCtx;
  text: string;
  style: React.CSSProperties;
  startIndex?: number;
}> = ({ ctx, text, style, startIndex = 0 }) => {
  const parts = splitWords(text);
  if (parts.length === 0) {
    return null;
  }
  return (
    <div style={style}>
      {parts.map((w, i) => {
        const a = ctx.anim.wordAt(startIndex + i);
        return (
          <span
            key={`${w}-${i}`}
            style={{
              display: "inline-block",
              transform: `translateY(${a.y}px)`,
              opacity: a.opacity,
              marginRight: "0.28em",
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

type ScrimMode = "full" | "bottom" | "top" | "radial" | "none";

// Scrimmed photo fill — the card's real photo behind the scene, never warped or
// recoloured beyond a ground-tinted legibility scrim (alpha hex on the ground
// role, exactly the PhotoLayer precedent). Returns null with no photo, so the
// scene falls back to its solid colour field.
export const PhotoFill: React.FC<{
  ctx: SceneCtx;
  scrim?: ScrimMode;
  strength?: number; // 0..1 extra darkening for busy compositions
}> = ({ ctx, scrim = "full", strength = 0 }) => {
  const { card, roles, anim, frame, fps } = ctx;
  if (!card.photoSrc) {
    return null;
  }
  // R1.10 photo grade — photo-element-only, exactly the PhotoLayer precedent.
  const grade = photoGradeFilterFor(card, frame, fps);
  const g = roles.ground;
  const boost = Math.round(Math.max(0, Math.min(1, strength)) * 40)
    .toString(16)
    .padStart(2, "0");
  const gradient =
    scrim === "bottom"
      ? `linear-gradient(180deg, ${g}10 0%, ${g}30 55%, ${g}E8 90%)`
      : scrim === "top"
        ? `linear-gradient(180deg, ${g}E8 0%, ${g}40 45%, ${g}10 100%)`
        : scrim === "radial"
          ? `radial-gradient(circle at 50% 42%, ${g}30 0%, ${g}B0 58%, ${g}F2 100%)`
          : scrim === "none"
            ? `${g}${boost}`
            : `linear-gradient(180deg, ${g}40 0%, ${g}B0 55%, ${g}F0 100%)`;
  return (
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
          objectPosition: card.photoPos || "center 28%",
          // M15 — the shared seed-chosen camera move (push + lateral drift).
          transform: `translate(${anim.photoDriftX}%, ${anim.photoDriftY}%) scale(${anim.photoScale})`,
          ...(grade ? { filter: grade } : {}),
        }}
      />
      <div style={{ position: "absolute", inset: 0, background: gradient }} />
      {boost !== "00" ? (
        <div style={{ position: "absolute", inset: 0, background: `${g}${boost}` }} />
      ) : null}
    </>
  );
};
