import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";
import { StoryCard, cardSchema } from "./StoryCard";
import { REEL_LAYERS } from "./sprint/reelRegistry";

// The reel reuses StoryCard's card schema verbatim (single source of truth):
// zod strips undeclared keys, so a shared schema means a prop added for the
// story can never be silently dropped on its reel beat.

const brandSchema = z.object({
  primary: z.string().default("#0A2540"),
  secondary: z.string().default("#000000"),
  accent: z.string().default("#FFFFFF"),
  displayName: z.string().default(""),
  shortName: z.string().default(""),
  logoDataUri: z.string().default(""),
});

export const meetReelSchema = z.object({
  cards: z.array(cardSchema),
  brand: brandSchema,
  meetName: z.string().default(""),
  // R1.30 — data-driven outro CTA inputs. Both optional; when both are blank
  // the outro falls back to the universal "follow the club" close, so every
  // existing reel renders byte-identically. A sponsor name (honest — sourced
  // from the club's configured sponsor) drives the "proudly supported by"
  // close; a next-meet label drives the "next up" close. Never fabricated:
  // the close only names a sponsor / next meet the caller actually supplied.
  sponsor: z.string().default(""),
  nextMeet: z.string().default(""),
});

type Props = z.infer<typeof meetReelSchema>;
type CardItem = Props["cards"][number];

// The reel's headline face — the same self-hosted brand stack the story
// cards lead with (src/fonts.ts), so cover/outro match the posted card.
const COVER_FONT =
  "'Anton', 'Oswald', 'Impact', 'Helvetica Neue Condensed', 'Arial Narrow', sans-serif";
const BODY_FONT =
  "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif";

// Honest cover/outro stats — derived ONLY from the real card labels the
// recognition layer produced. A medal counts only when the label says so;
// no place-number guessing, no invented numbers.
export function reelStats(cards: CardItem[]): { swims: number; pbs: number; medals: number } {
  const labels = (cards || []).map((c) => (c.achievementLabel || "").toUpperCase());
  return {
    swims: (cards || []).length,
    pbs: labels.filter((l) => l.includes("PB")).length,
    medals: labels.filter(
      (l) =>
        l.includes("GOLD") ||
        l.includes("SILVER") ||
        l.includes("BRONZE") ||
        l.includes("MEDAL"),
    ).length,
  };
}

// Per-beat transitions, picked deterministically so re-renders stay
// byte-identical. The set is split by narrative role (motion-craft
// transitions.md): the entry into the peak (top-ranked) beat earns the one
// bold, mood-chosen cut a reel is allowed, while the connective beats between
// same-rank moments share a single quiet kind so they read as one continuous
// piece rather than a transition showreel.
type TransitionKind =
  | "crossfade"
  | "push"
  | "wipe"
  | "blur"
  | "zoom"
  | "whip"
  | "iris";

export function transitionFor(
  seed: number,
  opts?: { peak?: boolean; mood?: string },
): TransitionKind {
  if (opts?.peak) {
    // The earned, boldest cut — its character derives from the beat's mood:
    // soft moods resolve out of a defocus, percussive moods whip in, a
    // medal/celebration irises open, everything else drives in with momentum.
    const m = (opts.mood || "").toLowerCase();
    if (
      m.includes("calm") ||
      m.includes("stoic") ||
      m.includes("precise") ||
      m.includes("warm") ||
      m.includes("minimal")
    ) {
      return "blur";
    }
    if (m.includes("explosive") || m.includes("electric") || m.includes("fierce")) {
      return "whip";
    }
    if (m.includes("celebratory") || m.includes("triumph") || m.includes("medal")) {
      return "iris";
    }
    return "zoom";
  }
  // Connective beats: one consistent quiet kind, spread only across reels.
  const mode = ((seed | 0) % 3 + 3) % 3;
  if (mode === 1) return "push";
  if (mode === 2) return "wipe";
  return "crossfade";
}

const StatChips: React.FC<{
  stats: { swims: number; pbs: number; medals: number };
  accent: string;
  ground: string;
  ts: number;
  opacity: number;
  progress: number;
}> = ({ stats, accent, ground, ts, opacity, progress }) => {
  // The numbers count up to their honest totals as the chips fade in —
  // pure function of the frame-derived progress. Pluralisation follows the
  // FINAL count so the label never flickers between forms mid-count.
  const shown = (n: number) => Math.round(n * Math.max(0, Math.min(1, progress)));
  const chips: string[] = [];
  if (stats.swims > 0) {
    chips.push(`TOP ${shown(stats.swims)} SWIM${stats.swims === 1 ? "" : "S"}`);
  }
  if (stats.pbs > 0) {
    chips.push(`${shown(stats.pbs)} PB${stats.pbs === 1 ? "" : "S"}`);
  }
  if (stats.medals > 0) {
    chips.push(`${shown(stats.medals)} MEDAL${stats.medals === 1 ? "" : "S"}`);
  }
  if (chips.length === 0) {
    return null;
  }
  return (
    <div
      style={{
        marginTop: Math.round(44 * ts),
        display: "flex",
        gap: Math.round(18 * ts),
        justifyContent: "center",
        opacity,
      }}
    >
      {chips.map((c, i) => (
        <div
          key={i}
          style={{
            padding: `${Math.round(12 * ts)}px ${Math.round(24 * ts)}px`,
            border: `3px solid ${accent}`,
            borderRadius: 999,
            color: accent,
            background: `${ground}00`,
            fontSize: Math.round(30 * ts),
            fontWeight: 800,
            letterSpacing: "0.12em",
            fontFamily: BODY_FONT,
          }}
        >
          {c}
        </div>
      ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Cover — a data-driven variant SYSTEM (R1.30). Each meet gets a stable cover
// chosen from its own honest stats + a per-meet seed, so two meets rarely
// share a cover while the SAME meet always re-renders identically (motion is a
// pure function of the frame — no Math.random / Date.now anywhere here).
//
// Legibility contract: the reel cover has no APCA role resolver, so every
// variant paints text only as `accent` on the `primary` ground and uses
// `secondary` purely for bars/rules/bands — the same safe pairing the reel
// has always relied on. Entrances are choreographed PER variant (varied
// easings + directions — motion-craft's anti-monoculture rule); only the
// honest stat-chip count-up and the scene's exit fade are shared.
// ---------------------------------------------------------------------------

// Deterministic 32-bit string hash (FNV-1a). Pure — gives each meet a fixed
// seed so the cover it draws never changes between renders, while different
// meet names land on different covers.
function reelSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export type CoverVariant = "stack" | "masthead" | "spotlight" | "banner";

// Honest, data-driven cover selection. A medal/PB-heavy weekend EARNS the
// stat-forward "spotlight" cover (it leads with a big honest number); a quiet
// weekend never fabricates a hero stat it doesn't have, so spotlight is left
// out of its pool entirely. The per-meet seed then picks within the eligible
// pool, so covers vary across meets without ever lying about the data.
export function coverVariantFor(
  seed: number,
  stats: { swims: number; pbs: number; medals: number },
): CoverVariant {
  const statForward = stats.medals > 0 || stats.pbs >= 2;
  const pool: CoverVariant[] = statForward
    ? ["spotlight", "masthead", "stack", "banner"]
    : ["masthead", "stack", "banner"];
  return pool[seed % pool.length];
}

// The values every cover variant shares: the honest stat-chip count-up
// (opacity + progress) and the scene's exit fade into the first card. The
// chips count up and the cover fades out identically everywhere; the rest of
// each variant's motion is its own.
function useCoverEnv(durationInFrames: number) {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ts = Math.min(width / 1080, height / 1440, 1);
  const chipsOpacity = interpolate(frame, [fps * 0.6, fps * 1.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const chipsProgress = interpolate(frame, [fps * 0.6, fps * 1.5], [0, 1], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const outroFade = interpolate(
    frame,
    [durationInFrames - fps * 0.25, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return { frame, fps, width, height, ts, chipsOpacity, chipsProgress, outroFade };
}

type CoverEnv = ReturnType<typeof useCoverEnv>;
type CoverVariantProps = {
  brand: Props["brand"];
  meetName: string;
  stats: { swims: number; pbs: number; medals: number };
  env: CoverEnv;
};

// Variant 1 — STACK: the classic centred emblem lockup. Logo scales in, the
// meet name springs up under a "Meet Recap" eyebrow, a brand-secondary rule
// grows out, club name and honest chips settle beneath.
const StackCover: React.FC<CoverVariantProps> = ({ brand, meetName, stats, env }) => {
  const { frame, fps, width, ts, chipsOpacity, chipsProgress } = env;
  const accent = brand.accent || "#FFFFFF";
  const intro = spring({ frame, fps, config: { damping: 16, stiffness: 100, mass: 0.6 } });
  const logoScale = spring({
    frame: frame - 2,
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.6 },
  });
  const titleY = interpolate(intro, [0, 1], [80, 0]);
  const titleOpacity = interpolate(frame, [3, fps * 0.5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const eyebrowOpacity = interpolate(frame, [fps * 0.15, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ruleW = interpolate(frame, [fps * 0.45, fps * 0.85], [0, 220], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  const clubY = interpolate(frame, [fps * 0.5, fps * 0.9], [24, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const clubOpacity = interpolate(frame, [fps * 0.5, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
  });
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: 96,
        textAlign: "center",
      }}
    >
      {brand.logoDataUri ? (
        <img
          src={brand.logoDataUri}
          alt={brand.displayName || "club logo"}
          style={{
            width: Math.round(220 * ts),
            height: Math.round(220 * ts),
            objectFit: "contain",
            marginBottom: Math.round(48 * ts),
            transform: `scale(${0.6 + 0.4 * logoScale})`,
            opacity: logoScale,
          }}
        />
      ) : null}
      <div
        style={{
          fontSize: Math.round(38 * ts),
          letterSpacing: "0.2em",
          color: accent,
          opacity: 0.85 * eyebrowOpacity,
          marginBottom: Math.round(36 * ts),
          textTransform: "uppercase",
          fontFamily: BODY_FONT,
          fontWeight: 700,
        }}
      >
        Meet Recap
      </div>
      <div
        style={{
          fontSize: Math.round(132 * ts),
          fontWeight: 900,
          color: accent,
          lineHeight: 1.0,
          letterSpacing: "-0.02em",
          textTransform: "uppercase",
          maxWidth: width - 160,
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
        }}
      >
        {meetName || "WEEKEND HIGHLIGHTS"}
      </div>
      {/* Brand-secondary rule between the meet name and the club name — the
          thin colour bar a print masthead uses to split title from subtitle. */}
      <div
        style={{
          marginTop: Math.round(36 * ts),
          width: ruleW,
          height: 4,
          background: brand.secondary || accent,
          opacity: 0.9,
        }}
      />
      <div
        style={{
          marginTop: Math.round(28 * ts),
          fontSize: Math.round(40 * ts),
          color: accent,
          letterSpacing: "0.16em",
          fontWeight: 700,
          textTransform: "uppercase",
          fontFamily: BODY_FONT,
          transform: `translateY(${clubY}px)`,
          opacity: clubOpacity,
        }}
      >
        {display}
      </div>
      <StatChips
        stats={stats}
        accent={accent}
        ground={brand.primary || "#0A2540"}
        ts={ts}
        opacity={chipsOpacity}
        progress={chipsProgress}
      />
    </div>
  );
};

// Variant 2 — MASTHEAD: editorial, left-aligned. A brand-secondary bar grows
// down the left of a huge left-set headline that slides in from the left out
// of a defocus; the club + honest chips settle as a centred footer. The mix
// of a left hero and a centred footer is a deliberate editorial contrast.
const MastheadCover: React.FC<CoverVariantProps> = ({ brand, meetName, stats, env }) => {
  const { frame, fps, width, height, ts, chipsOpacity, chipsProgress } = env;
  const accent = brand.accent || "#FFFFFF";
  const barH = interpolate(frame, [3, fps * 0.65], [0, Math.round(height * 0.46)], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const titleX = interpolate(
    spring({ frame: frame - 3, fps, config: { damping: 20, stiffness: 85, mass: 0.7 } }),
    [0, 1],
    [-70, 0],
  );
  const titleBlur = interpolate(frame, [3, fps * 0.55], [14, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleOpacity = interpolate(frame, [3, fps * 0.45], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const eyebrowX = interpolate(frame, [fps * 0.1, fps * 0.4], [-44, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  const eyebrowOpacity = interpolate(frame, [fps * 0.1, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
  const logoOpacity = interpolate(frame, [fps * 0.3, fps * 0.7], [0, 1], {
    extrapolateRight: "clamp",
  });
  const footerOpacity = interpolate(frame, [fps * 0.6, fps * 1.0], [0, 1], {
    extrapolateRight: "clamp",
  });
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  return (
    <div style={{ position: "absolute", inset: 0, padding: 96 }}>
      {/* vertical brand bar pinned to the left of the hero block */}
      <div
        style={{
          position: "absolute",
          left: 72,
          top: `calc(50% - ${Math.round(height * 0.3)}px)`,
          width: 12,
          height: barH,
          background: brand.secondary || accent,
          opacity: 0.95,
        }}
      />
      {brand.logoDataUri ? (
        <img
          src={brand.logoDataUri}
          alt={brand.displayName || "club logo"}
          style={{
            position: "absolute",
            top: 84,
            right: 84,
            width: Math.round(120 * ts),
            height: Math.round(120 * ts),
            objectFit: "contain",
            opacity: logoOpacity,
          }}
        />
      ) : null}
      {/* hero — left-aligned masthead headline, vertically centred */}
      <div
        style={{
          position: "absolute",
          left: 104,
          right: 96,
          top: "50%",
          transform: "translateY(-50%)",
          textAlign: "left",
        }}
      >
        <div
          style={{
            fontSize: Math.round(34 * ts),
            letterSpacing: "0.24em",
            color: accent,
            opacity: 0.85 * eyebrowOpacity,
            marginBottom: Math.round(26 * ts),
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
            fontWeight: 700,
            transform: `translateX(${eyebrowX}px)`,
          }}
        >
          Meet Recap
        </div>
        <div
          style={{
            fontSize: Math.round(146 * ts),
            fontWeight: 900,
            color: accent,
            lineHeight: 0.92,
            letterSpacing: "-0.03em",
            textTransform: "uppercase",
            maxWidth: width - 240,
            transform: `translateX(${titleX}px)`,
            filter: `blur(${titleBlur}px)`,
            opacity: titleOpacity,
          }}
        >
          {meetName || "WEEKEND HIGHLIGHTS"}
        </div>
      </div>
      {/* footer — centred club + honest chips */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: Math.round(120 * ts),
          textAlign: "center",
          opacity: footerOpacity,
        }}
      >
        <div
          style={{
            fontSize: Math.round(38 * ts),
            color: accent,
            letterSpacing: "0.18em",
            fontWeight: 700,
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
          }}
        >
          {display}
        </div>
        <StatChips
          stats={stats}
          accent={accent}
          ground={brand.primary || "#0A2540"}
          ts={ts}
          opacity={chipsOpacity}
          progress={chipsProgress}
        />
      </div>
    </div>
  );
};

// Variant 3 — SPOTLIGHT: stat-forward. Leads with the single biggest HONEST
// number the weekend produced (medals → PBs → swims), which counts up and
// lands on EXACTLY that verified total; the meet name plays the supporting
// headline. Only ever selected when the data has a number worth leading with.
const SpotlightCover: React.FC<CoverVariantProps> = ({ brand, meetName, stats, env }) => {
  const { frame, fps, width, ts } = env;
  const accent = brand.accent || "#FFFFFF";
  const hero =
    stats.medals > 0
      ? { n: stats.medals, label: stats.medals === 1 ? "MEDAL" : "MEDALS" }
      : stats.pbs > 0
        ? { n: stats.pbs, label: stats.pbs === 1 ? "PERSONAL BEST" : "PERSONAL BESTS" }
        : { n: stats.swims, label: stats.swims === 1 ? "TOP SWIM" : "TOP SWIMS" };
  // Count up to the honest total and HOLD it — round(n·progress) lands on n
  // exactly at progress 1 (no fabricated intermediate the viewer could
  // screenshot as a different truth).
  const countP = interpolate(frame, [fps * 0.2, fps * 1.2], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const shown = Math.round(hero.n * countP);
  const numScale = spring({
    frame: frame - 2,
    fps,
    config: { damping: 13, stiffness: 130, mass: 0.6 },
  });
  const labelOpacity = interpolate(frame, [fps * 0.5, fps * 0.85], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [fps * 0.7, fps * 1.05], [28, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const titleOpacity = interpolate(frame, [fps * 0.7, fps * 1.05], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ruleW = interpolate(frame, [fps * 0.9, fps * 1.25], [0, 200], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: 96,
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: Math.round(360 * ts),
          fontWeight: 900,
          color: accent,
          lineHeight: 0.86,
          letterSpacing: "-0.04em",
          fontVariantNumeric: "tabular-nums",
          transform: `scale(${0.7 + 0.3 * numScale})`,
        }}
      >
        {shown}
      </div>
      <div
        style={{
          marginTop: Math.round(8 * ts),
          fontSize: Math.round(46 * ts),
          color: accent,
          letterSpacing: "0.18em",
          fontWeight: 800,
          textTransform: "uppercase",
          fontFamily: BODY_FONT,
          opacity: 0.92 * labelOpacity,
        }}
      >
        {hero.label}
      </div>
      <div
        style={{
          marginTop: Math.round(40 * ts),
          width: ruleW,
          height: 4,
          background: brand.secondary || accent,
          opacity: 0.9,
        }}
      />
      <div
        style={{
          marginTop: Math.round(28 * ts),
          fontSize: Math.round(60 * ts),
          fontWeight: 900,
          color: accent,
          lineHeight: 1.0,
          letterSpacing: "-0.01em",
          textTransform: "uppercase",
          maxWidth: width - 200,
          fontFamily: COVER_FONT,
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
        }}
      >
        {meetName || "WEEKEND HIGHLIGHTS"}
      </div>
      <div
        style={{
          marginTop: Math.round(18 * ts),
          fontSize: Math.round(30 * ts),
          color: accent,
          letterSpacing: "0.16em",
          fontWeight: 700,
          textTransform: "uppercase",
          fontFamily: BODY_FONT,
          opacity: 0.8 * titleOpacity,
        }}
      >
        {display}
      </div>
    </div>
  );
};

// Variant 4 — BANNER: a horizontal banded composition. The meet name drops in
// up top, a full-width brand-secondary band wipes across the middle carrying
// the club logo, and the club name + honest chips rise in beneath it. Text
// stays accent-on-primary; only the logo (an image) ever sits on the band.
const BannerCover: React.FC<CoverVariantProps> = ({ brand, meetName, stats, env }) => {
  const { frame, fps, height, ts, chipsOpacity, chipsProgress } = env;
  const accent = brand.accent || "#FFFFFF";
  const titleY = interpolate(
    spring({ frame, fps, config: { damping: 18, stiffness: 100, mass: 0.6 } }),
    [0, 1],
    [-50, 0],
  );
  const titleOpacity = interpolate(frame, [3, fps * 0.5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const bandClip = interpolate(frame, [fps * 0.35, fps * 0.8], [100, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const logoOpacity = interpolate(frame, [fps * 0.6, fps * 0.95], [0, 1], {
    extrapolateRight: "clamp",
  });
  const lowerY = interpolate(frame, [fps * 0.6, fps * 1.0], [40, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const lowerOpacity = interpolate(frame, [fps * 0.6, fps * 1.0], [0, 1], {
    extrapolateRight: "clamp",
  });
  const bandH = Math.round(height * 0.16);
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {/* top — meet title */}
      <div
        style={{
          position: "absolute",
          top: Math.round(height * 0.16),
          left: 0,
          right: 0,
          padding: "0 96px",
          textAlign: "center",
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
        }}
      >
        <div
          style={{
            fontSize: Math.round(40 * ts),
            letterSpacing: "0.22em",
            color: accent,
            opacity: 0.85,
            marginBottom: Math.round(24 * ts),
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
            fontWeight: 700,
          }}
        >
          Meet Recap
        </div>
        <div
          style={{
            fontSize: Math.round(128 * ts),
            fontWeight: 900,
            color: accent,
            lineHeight: 0.98,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
          }}
        >
          {meetName || "WEEKEND HIGHLIGHTS"}
        </div>
      </div>
      {/* middle — brand band carrying the logo (wipes in left→right) */}
      <div
        style={{
          position: "absolute",
          top: `calc(50% - ${Math.round(bandH / 2)}px)`,
          left: 0,
          right: 0,
          height: bandH,
          background: brand.secondary || accent,
          clipPath: `inset(0 ${bandClip}% 0 0)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {brand.logoDataUri ? (
          <img
            src={brand.logoDataUri}
            alt={brand.displayName || "club logo"}
            style={{
              height: Math.round(bandH * 0.62),
              objectFit: "contain",
              opacity: logoOpacity,
            }}
          />
        ) : null}
      </div>
      {/* lower — club + honest chips */}
      <div
        style={{
          position: "absolute",
          top: `calc(50% + ${Math.round(bandH / 2 + 40 * ts)}px)`,
          left: 0,
          right: 0,
          textAlign: "center",
          transform: `translateY(${lowerY}px)`,
          opacity: lowerOpacity,
        }}
      >
        <div
          style={{
            fontSize: Math.round(44 * ts),
            color: accent,
            letterSpacing: "0.16em",
            fontWeight: 800,
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
          }}
        >
          {display}
        </div>
        <StatChips
          stats={stats}
          accent={accent}
          ground={brand.primary || "#0A2540"}
          ts={ts}
          opacity={chipsOpacity}
          progress={chipsProgress}
        />
      </div>
    </div>
  );
};

const CoverScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
  stats: { swims: number; pbs: number; medals: number };
}> = ({ brand, meetName, durationInFrames, stats }) => {
  const env = useCoverEnv(durationInFrames);
  // Data-driven: the variant is a pure function of the meet's identity and its
  // honest stats, so it is stable per meet and varied across meets.
  const variant = coverVariantFor(
    reelSeed(`${meetName}|${stats.swims}|${stats.pbs}|${stats.medals}`),
    stats,
  );
  const Body =
    variant === "spotlight"
      ? SpotlightCover
      : variant === "masthead"
        ? MastheadCover
        : variant === "banner"
          ? BannerCover
          : StackCover;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: brand.primary || "#0A2540",
        fontFamily: COVER_FONT,
        opacity: env.outroFade,
      }}
    >
      <Body brand={brand} meetName={meetName} stats={stats} env={env} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Outro — a data-driven CTA SYSTEM (R1.30). The reel always closes on the
// brand (logo + club, the slowest/simplest motion in the piece — closure, not
// climax), but the call-to-action under it is chosen from the data:
//   • sponsor thanks  — when the club supplied a sponsor name
//   • next meet        — when a next-meet label was supplied
//   • follow the club  — the universal fallback (handle from the brand)
// Honest: it only ever names a sponsor / next meet the caller actually passed.
// ---------------------------------------------------------------------------

export type OutroCtaKind = "sponsor" | "next_meet" | "follow";

// Priority: a paying sponsor's thank-you is the most valuable close, then a
// next-meet nudge, then the always-available follow. Pure function of its
// inputs — deterministic and trivially testable.
export function outroCtaFor(
  brand: { displayName: string; shortName: string },
  sponsor: string,
  nextMeet: string,
): { kind: OutroCtaKind; eyebrow: string; line: string } {
  const s = (sponsor || "").trim();
  if (s) {
    return { kind: "sponsor", eyebrow: "Proudly supported by", line: s.toUpperCase() };
  }
  const nm = (nextMeet || "").trim();
  if (nm) {
    return { kind: "next_meet", eyebrow: "Next up", line: nm.toUpperCase() };
  }
  const handle = (brand.shortName || brand.displayName || "").toUpperCase();
  return { kind: "follow", eyebrow: "", line: handle ? `FOLLOW ${handle} FOR MORE` : "" };
}

const OutroScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
  sponsor: string;
  nextMeet: string;
}> = ({ brand, meetName, durationInFrames, sponsor, nextMeet }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ts = Math.min(width / 1080, height / 1440, 1);
  const accent = brand.accent || "#FFFFFF";
  const grow = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.6 },
  });
  const fadeIn = interpolate(frame, [0, fps * 0.3], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ruleW = interpolate(frame, [fps * 0.25, fps * 0.6], [0, 180], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const ctaOpacity = interpolate(frame, [fps * 0.4, fps * 0.8], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ctaY = interpolate(frame, [fps * 0.4, fps * 0.8], [18, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const outroFade = interpolate(
    frame,
    [durationInFrames - fps * 0.35, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  const cta = outroCtaFor(brand, sponsor, nextMeet);
  // When the close thanks a sponsor but a next meet is ALSO known, the next
  // meet rides along as the quiet secondary line; otherwise the meet just
  // recapped sits there (the historic close).
  const nm = (nextMeet || "").trim();
  const secondary =
    cta.kind === "sponsor" && nm ? `NEXT UP · ${nm.toUpperCase()}` : meetName || "";
  return (
    <AbsoluteFill
      style={{
        backgroundColor: brand.primary || "#0A2540",
        fontFamily: COVER_FONT,
        opacity: outroFade,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          padding: 96,
          opacity: fadeIn,
        }}
      >
        {brand.logoDataUri ? (
          <img
            src={brand.logoDataUri}
            alt={brand.displayName || "club logo"}
            style={{
              width: Math.round(260 * ts),
              height: Math.round(260 * ts),
              objectFit: "contain",
              marginBottom: Math.round(44 * ts),
              transform: `scale(${0.8 + 0.2 * grow})`,
            }}
          />
        ) : null}
        <div
          style={{
            fontSize: Math.round(72 * ts),
            fontWeight: 900,
            color: accent,
            letterSpacing: "0.02em",
            textTransform: "uppercase",
            maxWidth: width - 160,
          }}
        >
          {display}
        </div>
        <div
          style={{
            marginTop: Math.round(26 * ts),
            width: ruleW,
            height: 4,
            background: brand.secondary || accent,
            opacity: 0.9,
          }}
        />
        {cta.eyebrow ? (
          <div
            style={{
              marginTop: Math.round(26 * ts),
              fontSize: Math.round(24 * ts),
              color: accent,
              letterSpacing: "0.22em",
              fontWeight: 700,
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
              opacity: 0.7 * ctaOpacity,
              transform: `translateY(${ctaY}px)`,
            }}
          >
            {cta.eyebrow}
          </div>
        ) : null}
        {cta.line ? (
          <div
            style={{
              marginTop: cta.eyebrow ? Math.round(8 * ts) : Math.round(30 * ts),
              fontSize: cta.kind === "follow" ? Math.round(34 * ts) : Math.round(44 * ts),
              color: accent,
              letterSpacing: "0.16em",
              fontWeight: cta.kind === "follow" ? 700 : 800,
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
              opacity: (cta.kind === "follow" ? 0.9 : 1) * ctaOpacity,
              transform: `translateY(${ctaY}px)`,
            }}
          >
            {cta.line}
          </div>
        ) : null}
        {secondary ? (
          <div
            style={{
              marginTop: Math.round(20 * ts),
              fontSize: Math.round(26 * ts),
              color: accent,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
              opacity: 0.55 * ctaOpacity,
            }}
          >
            {secondary}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const MeetReel: React.FC<Props> = ({ cards, brand, meetName, sponsor, nextMeet }) => {
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const rootFrame = useCurrentFrame();

  // Allocate the reel: 2s cover + rank-weighted card beats + 1s outro.
  const safeCards = (cards || []).slice(0, 5);
  const stats = reelStats(safeCards);
  if (safeCards.length === 0) {
    return (
      <CoverScreen
        brand={brand}
        meetName={meetName}
        durationInFrames={durationInFrames}
        stats={stats}
      />
    );
  }

  const coverFrames = Math.round(fps * 2.0);
  const outroFrames = Math.round(fps * 1.0);
  const transitionFrames = Math.round(fps * 0.35);
  const remaining = Math.max(0, durationInFrames - coverFrames - outroFrames);

  // Rank-weighted beats: the top-ranked moment breathes ~25% longer than
  // the rest (cards arrive ranked from the Python side). Deterministic
  // arithmetic — the same card list always yields the same allocation.
  const weights = safeCards.map((_, i) => (i === 0 && safeCards.length > 1 ? 1.25 : 1.0));
  const weightSum = weights.reduce((a, b) => a + b, 0);
  const minBeat = transitionFrames * 2 + Math.round(fps * 0.5);
  const beatFrames = weights.map((w) =>
    Math.max(minBeat, Math.floor((remaining * w) / weightSum) + transitionFrames),
  );

  let cursor = 0;
  const sequences: React.ReactNode[] = [];
  sequences.push(
    <Sequence
      key="cover"
      from={cursor}
      durationInFrames={coverFrames + transitionFrames}
    >
      <CoverScreen
        brand={brand}
        meetName={meetName}
        durationInFrames={coverFrames + transitionFrames}
        stats={stats}
      />
    </Sequence>,
  );
  cursor += coverFrames;

  // One consistent connective cut for every same-rank handoff, derived from
  // the reel (the top card's seed) so the lower beats feel like one piece.
  const connective = transitionFor(safeCards[0]?.variationSeed || 0);

  safeCards.forEach((card, i) => {
    const dur = beatFrames[i];
    // The first beat is the #1 (top-ranked) moment — its entry off the brand
    // cover is the reel's peak, so it earns the bold, mood-chosen cut.
    const isPeak = i === 0 && safeCards.length > 1;
    const kind = isPeak
      ? transitionFor(card.variationSeed || 0, { peak: true, mood: card.mood })
      : connective;
    sequences.push(
      <Sequence
        key={`card-${i}`}
        from={cursor}
        durationInFrames={dur + transitionFrames}
      >
        <TransitionWrap fadeInFrames={transitionFrames} kind={kind}>
          <StoryCard card={card} brand={brand} />
        </TransitionWrap>
      </Sequence>,
    );
    cursor += dur - transitionFrames;
  });

  // Outro — runs to the end of the reel, whatever rounding left over.
  sequences.push(
    <Sequence
      key="outro"
      from={cursor}
      durationInFrames={Math.max(outroFrames, durationInFrames - cursor)}
    >
      <TransitionWrap fadeInFrames={transitionFrames} kind="crossfade">
        <OutroScreen
          brand={brand}
          meetName={meetName}
          durationInFrames={Math.max(outroFrames, durationInFrames - cursor)}
          sponsor={sponsor}
          nextMeet={nextMeet}
        />
      </TransitionWrap>
    </Sequence>,
  );

  return (
    <AbsoluteFill>
      {sequences}
      {/* Sprint reel-overlay layers — additive, in order (see sprint/reelRegistry). */}
      {REEL_LAYERS.map(({ Layer }, i) => (
        <Layer
          key={`reel-layer-${i}`}
          ctx={{
            frame: rootFrame,
            fps,
            durationInFrames,
            width,
            height,
            cardCount: safeCards.length,
            meetName,
          }}
        />
      ))}
    </AbsoluteFill>
  );
};

// Transition wrapper — eases its children in over `fadeInFrames` with the
// chosen language. Pure function of the frame (no CSS transitions).
const TransitionWrap: React.FC<{
  fadeInFrames: number;
  kind: TransitionKind;
  children: React.ReactNode;
}> = ({ fadeInFrames, kind, children }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  // The incoming beat overlaps the outgoing one for `fadeInFrames`, so the
  // transition reads against the previous beat still on screen (its exit).
  // Each kind eases differently — easing is the adverb (motion-craft).
  const ease = (easing: (n: number) => number) =>
    interpolate(frame, [0, fadeInFrames], [0, 1], {
      extrapolateRight: "clamp",
      easing,
    });

  if (kind === "push") {
    const t = ease(Easing.out(Easing.cubic));
    return (
      <AbsoluteFill
        style={{ opacity: t, transform: `translateY(${(1 - t) * height * 0.12}px)` }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "wipe") {
    const t = ease(Easing.inOut(Easing.cubic));
    const pct = Math.round((1 - t) * 100);
    return (
      <AbsoluteFill style={{ opacity: Math.min(1, t * 2), clipPath: `inset(0 ${pct}% 0 0)` }}>
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "blur") {
    // Soft register shift — the beat resolves out of a defocus. For calm peaks.
    const t = ease(Easing.out(Easing.cubic));
    return (
      <AbsoluteFill style={{ opacity: t, filter: `blur(${(1 - t) * 16}px)` }}>
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "zoom") {
    // Momentum into the headline — scales up to its resting size, decisive.
    const t = ease(Easing.out(Easing.exp));
    return (
      <AbsoluteFill
        style={{ opacity: Math.min(1, t * 1.4), transform: `scale(${0.9 + 0.1 * t})` }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "whip") {
    // High-energy lateral snap with a directional blur that resolves on landing.
    const t = ease(Easing.out(Easing.cubic));
    return (
      <AbsoluteFill
        style={{
          opacity: Math.min(1, t * 1.6),
          transform: `translateX(${(1 - t) * width * 0.5}px)`,
          filter: `blur(${(1 - t) * 14}px)`,
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "iris") {
    // Spotlight reveal opening from the centre — the medal/celebration peak.
    const t = ease(Easing.out(Easing.cubic));
    return (
      <AbsoluteFill
        style={{ opacity: Math.min(1, t * 2), clipPath: `circle(${Math.round(t * 130)}% at 50% 45%)` }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  return <AbsoluteFill style={{ opacity: ease((n) => n) }}>{children}</AbsoluteFill>;
};
