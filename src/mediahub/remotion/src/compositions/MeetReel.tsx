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

const CoverScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
  stats: { swims: number; pbs: number; medals: number };
}> = ({ brand, meetName, durationInFrames, stats }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ts = Math.min(width / 1080, height / 1440, 1);
  const introSpring = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 100, mass: 0.6 },
  });
  const titleY = interpolate(introSpring, [0, 1], [80, 0]);
  const titleOpacity = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
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

  const display = (brand.displayName || brand.shortName || "").toUpperCase();
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
          padding: 96,
          textAlign: "center",
          transform: `translateY(${titleY}px)`,
          opacity: titleOpacity,
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
            }}
          />
        ) : null}
        <div
          style={{
            fontSize: Math.round(38 * ts),
            letterSpacing: "0.2em",
            // Eyebrow stays on accent for contrast against the
            // primary background; the secondary brand colour
            // carries through on the rule below the meet name.
            color: brand.accent || "#FFFFFF",
            opacity: 0.85,
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
            color: brand.accent || "#FFFFFF",
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
            maxWidth: width - 160,
          }}
        >
          {meetName || "WEEKEND HIGHLIGHTS"}
        </div>
        {/* Brand-secondary rule sits between the meet name and the
            club name, mirroring the way print mastheads use a thin
            colour bar to separate title from subtitle. Without this
            the secondary brand colour was absent from the reel cover. */}
        <div
          style={{
            marginTop: Math.round(36 * ts),
            width: 220,
            height: 4,
            background: brand.secondary || brand.accent || "#FFFFFF",
            opacity: 0.9,
          }}
        />
        <div
          style={{
            marginTop: Math.round(28 * ts),
            fontSize: Math.round(40 * ts),
            color: brand.accent || "#FFFFFF",
            letterSpacing: "0.16em",
            fontWeight: 700,
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
          }}
        >
          {display}
        </div>
        <StatChips
          stats={stats}
          accent={brand.accent || "#FFFFFF"}
          ground={brand.primary || "#0A2540"}
          ts={ts}
          opacity={chipsOpacity}
          progress={chipsProgress}
        />
      </div>
    </AbsoluteFill>
  );
};

// Closing beat — logo, club, follow CTA. The reel ends on the brand, not on
// a hard cut out of the last result.
const OutroScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
}> = ({ brand, meetName, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ts = Math.min(width / 1080, height / 1440, 1);
  const grow = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.6 },
  });
  const fadeIn = interpolate(frame, [0, fps * 0.3], [0, 1], {
    extrapolateRight: "clamp",
  });
  const outroFade = interpolate(
    frame,
    [durationInFrames - fps * 0.35, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  const handle = (brand.shortName || brand.displayName || "").toUpperCase();
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
            color: brand.accent || "#FFFFFF",
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
            width: 180,
            height: 4,
            background: brand.secondary || brand.accent || "#FFFFFF",
            opacity: 0.9,
          }}
        />
        {handle ? (
          <div
            style={{
              marginTop: Math.round(30 * ts),
              fontSize: Math.round(34 * ts),
              color: brand.accent || "#FFFFFF",
              letterSpacing: "0.22em",
              fontWeight: 700,
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
              opacity: 0.9,
            }}
          >
            FOLLOW {handle} FOR MORE
          </div>
        ) : null}
        {meetName ? (
          <div
            style={{
              marginTop: Math.round(20 * ts),
              fontSize: Math.round(26 * ts),
              color: brand.accent || "#FFFFFF",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
              opacity: 0.6,
            }}
          >
            {meetName}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const MeetReel: React.FC<Props> = ({ cards, brand, meetName }) => {
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
