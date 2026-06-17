/**
 * Shared scene kit for the G1.1 motion scenes (sprint/scenes/*.tsx).
 *
 * The built-in StoryCard scenes share private helpers (PhotoLayer, LogoChip,
 * BottomStrip, KineticLine, fitLinePx, placeDisplay) that are NOT exported, and
 * G1.1 is "new files only" — so rather than edit StoryCard.tsx we re-home the
 * same small presentational helpers here for the sprint scenes to import. They
 * are deliberately faithful to the built-ins (same scrim maths, same fit
 * heuristic, same per-word stagger) so a sprint scene reads on-brand and stays
 * in lock-step with the still + the rest of the reel.
 *
 * This file sits directly under sprint/ (NOT inside a require.context'd
 * subfolder), so the registry never auto-loads it; only the scene files import
 * it explicitly. Everything is a pure function of ctx + the frame — no
 * wallclock, no randomness — so renders stay deterministic.
 */
import React from "react";
import type { AnimChannels, Roles, SceneCtx } from "./registry";

// Append an 8-bit alpha to a #rrggbb role hex (the StoryCard scrim precedent,
// e.g. `${roles.ground}B0`). Clamped; pass-through for already-aliased values.
export function withAlpha(hex: string, a: number): string {
  const h = (hex || "").trim();
  if (!h.startsWith("#") || h.length < 7) {
    return h;
  }
  const v = Math.max(0, Math.min(255, Math.round(a * 255)));
  return `${h.slice(0, 7)}${v.toString(16).padStart(2, "0")}`;
}

// Single-line fit heuristic (mirrors StoryCard.fitLinePx): shrink basePx so a
// long name/result never overflows its box. Coarse but deterministic.
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

// Display ordinal for a numeric placing ("1" → "1ST"); non-numeric passes
// through untouched — never invent a placing that wasn't detected.
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

// Full-frame photo layer with a brand-ground scrim (the same gradient shapes
// StoryCard.PhotoLayer paints). Returns null with no sourced photo, so a
// data/editorial scene stays bare. Ken Burns rides on anim.photoScale.
export const Photo: React.FC<{
  ctx: SceneCtx;
  scrim?: "none" | "bottom" | "full" | "left";
}> = ({ ctx, scrim = "full" }) => {
  const { card, roles, anim } = ctx;
  if (!card.photoSrc) {
    return null;
  }
  const g = roles.ground;
  const scrimBg =
    scrim === "bottom"
      ? `linear-gradient(180deg, ${withAlpha(g, 0.06)} 0%, ${withAlpha(g, 0.19)} 55%, ${withAlpha(g, 0.91)} 88%)`
      : scrim === "left"
        ? `linear-gradient(90deg, ${withAlpha(g, 0.0)} 50%, ${withAlpha(g, 0.7)} 100%)`
        : `linear-gradient(180deg, ${withAlpha(g, 0.25)} 0%, ${withAlpha(g, 0.69)} 55%, ${withAlpha(g, 0.94)} 100%)`;
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
          transform: `scale(${anim.photoScale})`,
        }}
      />
      {scrim === "none" ? null : (
        <div style={{ position: "absolute", inset: 0, background: scrimBg }} />
      )}
    </>
  );
};

// Brand logo chip pinned to a corner. Null with no logo.
export const Logo: React.FC<{
  ctx: SceneCtx;
  size?: number;
  corner?: "tr" | "tl";
}> = ({ ctx, size = 120, corner = "tr" }) => {
  const { brand, anim, width, ts } = ctx;
  if (!brand.logoDataUri) {
    return null;
  }
  const s = Math.round(size * ts);
  const edge = Math.min(80, width * 0.06);
  return (
    <img
      src={brand.logoDataUri}
      alt={brand.displayName || "club logo"}
      style={{
        position: "absolute",
        top: Math.round(96 * ts),
        ...(corner === "tr" ? { right: edge } : { left: edge }),
        width: s,
        height: s,
        objectFit: "contain",
        opacity: anim.chipOpacity,
      }}
    />
  );
};

// Bottom strip: meet (left) • club (right), on the chip channel.
export const Footer: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { roles, anim, ts, meet, club } = ctx;
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: Math.round(80 * ts),
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: Math.round(28 * ts),
        letterSpacing: "0.08em",
        color: roles.onGround,
        opacity: anim.chipOpacity * 0.85,
        textTransform: "uppercase",
      }}
    >
      <span>{meet}</span>
      <span style={{ fontWeight: 700 }}>{club}</span>
    </div>
  );
};

// Per-word staggered row (mirrors StoryCard.KineticLine) — kinetic_type reveals
// word-by-word; identity under every other intent.
export const KineticWords: React.FC<{
  text: string;
  anim: AnimChannels;
  style: React.CSSProperties;
  startIndex?: number;
}> = ({ text, anim, style, startIndex = 0 }) => {
  const parts = (text || "").split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return null;
  }
  return (
    <div style={style}>
      {parts.map((w, i) => {
        const a = anim.wordAt(startIndex + i);
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

export type { Roles, SceneCtx, AnimChannels };
