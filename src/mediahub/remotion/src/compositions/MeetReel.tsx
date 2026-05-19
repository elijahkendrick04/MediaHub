import React from "react";
import {
  AbsoluteFill,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";
import { StoryCard } from "./StoryCard";

const cardSchema = z.object({
  athleteFullName: z.string().default(""),
  athleteFirstName: z.string().default(""),
  athleteSurname: z.string().default(""),
  eventName: z.string().default(""),
  resultValue: z.string().default(""),
  achievementLabel: z.string().default(""),
  meetName: z.string().default(""),
  place: z.string().default(""),
  variationSeed: z.number().default(0),
  // Variation axes flow through to the inner StoryCard renders so every
  // beat of the reel can carry its own direction (different layout,
  // background pattern, accent, etc.). Empty strings keep the
  // pre-Gemini-director behaviour for cards built by older callers.
  backgroundStyle: z.string().default(""),
  composition: z.string().default(""),
  typographyPair: z.string().default(""),
  accentStyle: z.string().default(""),
  mood: z.string().default(""),
  photoTreatment: z.string().default(""),
});

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

const CoverScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
}> = ({ brand, meetName, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const introSpring = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 100, mass: 0.6 },
  });
  const titleY = interpolate(introSpring, [0, 1], [80, 0]);
  const titleOpacity = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
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
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Inter', 'Helvetica Neue', Arial, sans-serif",
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
              width: 220,
              height: 220,
              objectFit: "contain",
              marginBottom: 48,
            }}
          />
        ) : null}
        <div
          style={{
            fontSize: 38,
            letterSpacing: "0.2em",
            // Eyebrow uses the SECONDARY brand colour. Previously
            // every line on this cover screen used accent, so the
            // secondary the user confirmed never appeared in the
            // reel intro.
            color: brand.secondary || brand.accent || "#FFFFFF",
            opacity: 0.85,
            marginBottom: 36,
            textTransform: "uppercase",
          }}
        >
          Meet Recap
        </div>
        <div
          style={{
            fontSize: 132,
            fontWeight: 900,
            color: brand.accent || "#FFFFFF",
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
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
            marginTop: 36,
            width: 220,
            height: 4,
            background: brand.secondary || brand.accent || "#FFFFFF",
            opacity: 0.9,
          }}
        />
        <div
          style={{
            marginTop: 28,
            fontSize: 40,
            color: brand.accent || "#FFFFFF",
            letterSpacing: "0.16em",
            fontWeight: 700,
            textTransform: "uppercase",
          }}
        >
          {display}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const MeetReel: React.FC<Props> = ({ cards, brand, meetName }) => {
  const { fps, durationInFrames } = useVideoConfig();

  // Allocate the reel: 2s cover + N card scenes + 1s outro accent.
  const safeCards = (cards || []).slice(0, 5);
  if (safeCards.length === 0) {
    return (
      <CoverScreen
        brand={brand}
        meetName={meetName}
        durationInFrames={durationInFrames}
      />
    );
  }

  const coverFrames = Math.round(fps * 2.0);
  const transitionFrames = Math.round(fps * 0.35);
  const remaining = Math.max(0, durationInFrames - coverFrames);
  const perCardFrames = Math.max(
    transitionFrames * 2 + fps * 0.5,
    Math.floor(remaining / safeCards.length) + transitionFrames,
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
      />
    </Sequence>,
  );
  cursor += coverFrames;

  safeCards.forEach((card, i) => {
    const isLast = i === safeCards.length - 1;
    const dur = isLast
      ? Math.max(perCardFrames, durationInFrames - cursor)
      : perCardFrames;
    sequences.push(
      <Sequence
        key={`card-${i}`}
        from={cursor}
        durationInFrames={dur + transitionFrames}
      >
        <CrossfadeWrap fadeInFrames={transitionFrames}>
          <StoryCard card={card} brand={brand} />
        </CrossfadeWrap>
      </Sequence>,
    );
    cursor += dur - transitionFrames;
  });

  return <AbsoluteFill>{sequences}</AbsoluteFill>;
};

// Small wrapper that crossfades its children in over `fadeInFrames`.
const CrossfadeWrap: React.FC<{
  fadeInFrames: number;
  children: React.ReactNode;
}> = ({ fadeInFrames, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, fadeInFrames], [0, 1], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity }}>
      {children}
    </AbsoluteFill>
  );
};
