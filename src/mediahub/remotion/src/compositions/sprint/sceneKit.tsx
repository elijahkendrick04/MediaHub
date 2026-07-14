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
import { Easing, interpolate, useVideoConfig } from "remotion";
import type { SceneCtx } from "./registry";
import {
  PhotoFilterDefs,
  photoGradeFilterFor,
  photoHalftoneMaskFor,
} from "./layers/photo_filters";

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

// The still renderer's hue-tinted shadow colour (graphic_renderer/elevation.py
// shadow_rgb): keep the resolved ground's hue, drop saturation to 40% (+0.12,
// capped 0.45), floor lightness into 0.06–0.14 — so motion shadows carry the
// brand's cast exactly like the approved still's, never neutral black.
// Same HLS maths, same constants; parity is byte-level on the emitted triple.
export function shadowRgb(groundHex: string): string {
  const h = (groundHex || "").trim().replace(/^#/, "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    return "10,12,16";
  }
  const r = parseInt(full.slice(0, 2), 16) / 255;
  const g = parseInt(full.slice(2, 4), 16) / 255;
  const b = parseInt(full.slice(4, 6), 16) / 255;
  // rgb → hls (Python colorsys convention)
  const maxc = Math.max(r, g, b);
  const minc = Math.min(r, g, b);
  const l = (maxc + minc) / 2;
  let hDeg = 0;
  let s = 0;
  if (maxc !== minc) {
    const d = maxc - minc;
    s = l > 0.5 ? d / (2 - maxc - minc) : d / (maxc + minc);
    if (maxc === r) {
      hDeg = ((g - b) / d) % 6;
    } else if (maxc === g) {
      hDeg = (b - r) / d + 2;
    } else {
      hDeg = (r - g) / d + 4;
    }
    hDeg /= 6;
    if (hDeg < 0) {
      hDeg += 1;
    }
  }
  const s2 = Math.min(0.45, s * 0.4 + 0.12);
  const l2 = Math.max(0.06, Math.min(0.14, l * 0.25));
  // hls → rgb (colorsys convention)
  const hue = (m1: number, m2: number, hh: number): number => {
    let t = hh;
    if (t < 0) {
      t += 1;
    }
    if (t > 1) {
      t -= 1;
    }
    if (t < 1 / 6) {
      return m1 + (m2 - m1) * 6 * t;
    }
    if (t < 1 / 2) {
      return m2;
    }
    if (t < 2 / 3) {
      return m1 + (m2 - m1) * (2 / 3 - t) * 6;
    }
    return m1;
  };
  const m2 = l2 <= 0.5 ? l2 * (1 + s2) : l2 + s2 - l2 * s2;
  const m1 = 2 * l2 - m2;
  const r2 = Math.round(hue(m1, m2, hDeg + 1 / 3) * 255);
  const g2 = Math.round(hue(m1, m2, hDeg) * 255);
  const b2 = Math.round(hue(m1, m2, hDeg - 1 / 3) * 255);
  return `${r2},${g2},${b2}`;
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
  // The exact M10 mirrors (duotone SVG filter / halftone mask) take over when
  // motion.py passed their parameters.
  const grade = photoGradeFilterFor(card, frame, fps);
  const mask = photoHalftoneMaskFor(card);
  // M10 crop-intent mirror — static wrapper scale at the saliency focus, so
  // it multiplies into the camera push without fighting the img transform.
  const cropScale = card.photoScale && card.photoScale > 1 ? card.photoScale : 1;
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
  const img = (
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
        ...(mask ?? {}),
      }}
    />
  );
  return (
    <>
      <PhotoFilterDefs card={card} />
      {cropScale > 1 ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            transform: `scale(${cropScale})`,
            transformOrigin: card.photoPos || "center 28%",
          }}
        >
          {img}
        </div>
      ) : (
        img
      )}
      <div style={{ position: "absolute", inset: 0, background: gradient }} />
      {boost !== "00" ? (
        <div style={{ position: "absolute", inset: 0, background: `${g}${boost}` }} />
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// M11 parity — secondary-stat chips + honest proportional PB bars.
//
// The motion twin of the still's _stat_chips_html / _pb_bars_html: motion.py
// already ran the still's own selection (secondary_stats ∩ hero_stat_options,
// hero-line fact skipped, label-trimmed values, cap 4) and passes the finished
// label/value pairs plus the exact ink hex the still's bay uses (`statInk`),
// so this component only mirrors the GEOMETRY (the continuity grammar): a 1px
// outline chip of Inter-caps label over JetBrains-Mono tnum value, and the
// zero-based proportional before/after bars. Renders null when the card
// carries neither prop — undirected cards stay byte-identical.
//
// Beat phase: the chips cascade in on the chip channel late in the build
// (stagger by importance, whole sequence < 15 frames); the NOW bar draws to
// its honest width through the early breathe and holds.
// ---------------------------------------------------------------------------

export const StatChipsBlock: React.FC<{ ctx: SceneCtx }> = ({ ctx }) => {
  const { card, roles, anim, ts, frame, fps } = ctx;
  const { durationInFrames } = useVideoConfig();
  const chips = (card.statChips || []).filter((c) => c && c.label && c.value);
  const bars = card.pbBars || null;
  if (chips.length === 0 && !bars) {
    return null;
  }
  const ink = card.statInk || roles.onGround;
  // The still's hairline --mh-outline, resolved Python-side and passed on the
  // props (motion.py attaches it whenever chips/bars attach). Fallback: a
  // translucent wash of the resolved ink role — never an invented colour.
  const outline = card.roleOutline || withAlpha(ink, 0.2);
  const at = (f: number) => 3 + (durationInFrames - 3) * f;
  // NOW bar draw — resolves early in the breathe so the honest proportion is
  // readable for most of the beat.
  const draw = interpolate(frame, [at(0.22), at(0.4)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const bar = (
    label: string,
    value: string,
    pct: number,
    fill: string,
    valueInk: string,
    grow: number,
  ) => (
    <div
      key={label}
      style={{ display: "flex", alignItems: "center", gap: Math.round(16 * ts), minWidth: 0 }}
    >
      <div
        style={{
          flex: `0 0 ${Math.round(108 * ts)}px`,
          fontFamily: "'Inter', sans-serif",
          fontWeight: 700,
          fontSize: Math.round(15 * ts),
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: ink,
          opacity: 0.78 * anim.chipOpacity,
        }}
      >
        {label}
      </div>
      <div style={{ flex: "1 1 auto", minWidth: 0 }}>
        <div
          style={{
            width: `${(pct * grow).toFixed(1)}%`,
            height: Math.round(26 * ts),
            background: fill,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            overflow: "hidden",
            opacity: anim.chipOpacity,
          }}
        >
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontVariantNumeric: "tabular-nums",
              fontWeight: 700,
              // D8 — the still's data-register weight (0 ⇒ omit, byte-identical).
              fontVariationSettings:
                card.wghtData && card.wghtData > 0 ? `'wght' ${Math.round(card.wghtData)}` : undefined,
              fontSize: Math.round(17 * ts),
              color: valueInk,
              padding: `0 ${Math.round(10 * ts)}px`,
              whiteSpace: "nowrap",
              opacity: grow,
            }}
          >
            {value}
          </span>
        </div>
      </div>
    </div>
  );
  return (
    <div>
      {chips.length > 0 ? (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: Math.round(14 * ts),
            marginTop: Math.round(26 * ts),
          }}
        >
          {chips.map((c, i) => {
            // Importance-ordered cascade: 3-frame stagger keeps the whole
            // row's entrance under 15 frames (motion-craft stagger bound).
            const enter = interpolate(
              frame,
              [at(0.2) + i * 3, at(0.2) + i * 3 + Math.round(fps * 0.3)],
              [0, 1],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.out(Easing.exp),
              },
            );
            return (
              <div
                key={`${c.label}-${i}`}
                style={{
                  border: `1px solid ${outline}`,
                  padding: `${Math.round(18 * ts)}px ${Math.round(24 * ts)}px`,
                  minWidth: 0,
                  opacity: enter * anim.chipOpacity,
                  transform: `translateY(${(1 - enter) * 18}px)`,
                }}
              >
                <div
                  style={{
                    fontFamily: "'Inter', sans-serif",
                    fontWeight: 700,
                    fontSize: Math.round(17 * ts),
                    letterSpacing: "0.22em",
                    textTransform: "uppercase",
                    color: roles.accent,
                    marginBottom: Math.round(8 * ts),
                  }}
                >
                  {c.label}
                </div>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', 'Space Grotesk', monospace",
                    fontVariantNumeric: "tabular-nums",
                    fontWeight: 700,
                    // D8 — the still's data-register weight (0 ⇒ omit, byte-identical).
                    fontVariationSettings:
                      card.wghtData && card.wghtData > 0
                        ? `'wght' ${Math.round(card.wghtData)}`
                        : undefined,
                    fontSize: Math.round(30 * ts),
                    lineHeight: 1.05,
                    color: ink,
                  }}
                >
                  {c.value}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      {bars ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: Math.round(10 * ts),
            marginTop: Math.round(28 * ts),
          }}
        >
          {bar("Previous", bars.prev, 100.0, withAlpha(ink, 0.26), ink, 1)}
          {bar("Now", bars.now, bars.nowPct, roles.accent, roles.ground, draw)}
          <div
            style={{
              fontFamily: "'Inter', sans-serif",
              fontWeight: 600,
              fontSize: Math.round(15 * ts),
              color: roles.accent,
              letterSpacing: "0.06em",
              opacity: anim.chipOpacity,
            }}
          >
            {bars.caption}
          </div>
        </div>
      ) : null}
    </div>
  );
};
