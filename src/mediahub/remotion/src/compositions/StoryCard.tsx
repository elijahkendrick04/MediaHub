import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";

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
});

const brandSchema = z.object({
  primary: z.string().default("#0A2540"),
  secondary: z.string().default("#000000"),
  accent: z.string().default("#FFFFFF"),
  displayName: z.string().default(""),
  shortName: z.string().default(""),
});

export const storyCardSchema = z.object({
  card: cardSchema,
  brand: brandSchema,
});

type Props = z.infer<typeof storyCardSchema>;

// Variation-seed driven palette role swap. Mirrors the seed=1 behaviour in
// src/mediahub/creative_brief/generator.py:_apply_palette_seed so motion
// renders stay visually consistent with the static graphic for the same card.
function rolesForSeed(
  brand: Props["brand"],
  seed: number,
): { ground: string; surface: string; accent: string } {
  const p = brand.primary || "#0A2540";
  const s = brand.secondary || "#000000";
  const a = brand.accent || "#FFFFFF";
  const mode = ((seed | 0) % 4 + 4) % 4;
  if (mode === 1) return { ground: s, surface: p, accent: a };
  if (mode === 2) return { ground: a, surface: p, accent: s };
  if (mode === 3) return { ground: p, surface: a, accent: s };
  return { ground: p, surface: s, accent: a };
}

export const StoryCard: React.FC<Props> = ({ card, brand }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const roles = rolesForSeed(brand, card.variationSeed || 0);

  // Intro: spring-eased big surname swoop + result fade
  const introSpring = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 90, mass: 0.7 },
  });
  const surnameY = interpolate(introSpring, [0, 1], [120, 0]);
  const surnameOpacity = interpolate(frame, [0, fps * 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });
  const resultOpacity = interpolate(frame, [fps * 0.6, fps * 1.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const resultScale = interpolate(frame, [fps * 0.6, fps * 1.4], [0.92, 1.0], {
    extrapolateRight: "clamp",
  });
  const chipOpacity = interpolate(frame, [fps * 1.0, fps * 1.5], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Outro: fade to black on last 0.4s
  const outroFade = interpolate(
    frame,
    [durationInFrames - fps * 0.4, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const surnameText = (card.athleteSurname || card.athleteFullName || "")
    .toUpperCase()
    .slice(0, 12);
  const firstName = (card.athleteFirstName || "").toUpperCase();
  const label = (card.achievementLabel || "").toUpperCase();
  const event = card.eventName || "";
  const result = card.resultValue || "";
  const meet = card.meetName || "";
  const club = (brand.displayName || brand.shortName || "").toUpperCase();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: roles.ground,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Inter', 'Helvetica Neue', Arial, sans-serif",
        opacity: outroFade,
      }}
    >
      {/* Surface band — slim diagonal accent for energy */}
      <div
        style={{
          position: "absolute",
          width: width * 1.6,
          height: 220,
          background: roles.surface,
          opacity: 0.85,
          left: -width * 0.3,
          top: height * 0.78,
          transform: "rotate(-6deg)",
        }}
      />

      {/* Mega watermark surname behind everything */}
      <div
        style={{
          position: "absolute",
          top: height * 0.18,
          right: -width * 0.06,
          fontSize: Math.min(width, height) * 0.32,
          fontWeight: 900,
          letterSpacing: "-0.02em",
          color: roles.accent,
          opacity: 0.12,
          lineHeight: 0.9,
          transform: `translateY(${surnameY * 0.4}px)`,
          textTransform: "uppercase",
        }}
      >
        {surnameText}
      </div>

      {/* Achievement chip */}
      <div
        style={{
          position: "absolute",
          top: 140,
          left: 80,
          padding: "14px 28px",
          background: roles.accent,
          color: roles.ground,
          fontSize: 36,
          fontWeight: 800,
          letterSpacing: "0.12em",
          opacity: chipOpacity,
          borderRadius: 6,
        }}
      >
        {label || "STRONG SWIM"}
      </div>

      {/* Athlete first name */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.45,
          fontSize: 96,
          fontWeight: 700,
          color: roles.accent,
          letterSpacing: "-0.01em",
          opacity: surnameOpacity,
          transform: `translateY(${surnameY * 0.3}px)`,
        }}
      >
        {firstName}
      </div>

      {/* Athlete surname — large hero */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.51,
          fontSize: 168,
          fontWeight: 900,
          color: roles.accent,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          opacity: surnameOpacity,
          transform: `translateY(${surnameY}px)`,
          maxWidth: width - 160,
        }}
      >
        {surnameText}
      </div>

      {/* Event line */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.65,
          fontSize: 36,
          color: roles.accent,
          opacity: surnameOpacity * 0.85,
          letterSpacing: "0.04em",
        }}
      >
        {event}
      </div>

      {/* Result value — hero metric */}
      <div
        style={{
          position: "absolute",
          left: 80,
          top: height * 0.70,
          fontSize: 132,
          fontWeight: 800,
          color: roles.accent,
          letterSpacing: "-0.01em",
          opacity: resultOpacity,
          transform: `scale(${resultScale})`,
          transformOrigin: "left center",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {result || "—"}
      </div>

      {/* Bottom strip — meet + club */}
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          bottom: 80,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 28,
          letterSpacing: "0.08em",
          color: roles.accent,
          opacity: chipOpacity * 0.85,
          textTransform: "uppercase",
        }}
      >
        <span>{meet}</span>
        <span style={{ fontWeight: 700 }}>{club}</span>
      </div>
    </AbsoluteFill>
  );
};
