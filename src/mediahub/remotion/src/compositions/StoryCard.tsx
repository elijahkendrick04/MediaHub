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
  // Path A/B variation axes — every field is optional. Empty strings
  // fall back to the variationSeed-driven behaviour, so legacy callers
  // that haven't been updated keep producing the same output they did
  // before this composition learned about the wider variation vocabulary.
  backgroundStyle: z.string().default(""),
  composition: z.string().default(""),
  typographyPair: z.string().default(""),
  accentStyle: z.string().default(""),
  mood: z.string().default(""),
  photoTreatment: z.string().default(""),
  // The card's actual photo (the one the user attached to the still
  // graphic), inlined by motion.py as a JPEG data URI. Empty = no photo
  // layer, which keeps the pre-photo behaviour for older callers.
  photoSrc: z.string().default(""),
  // Gen v2 (SEQ-4): the still graphic's archetype + measured emphasis line,
  // so the motion render of a card visually matches its still. Empty keeps
  // the pre-v2 behaviour for cards rendered by older callers.
  archetype: z.string().default(""),
  heroStat: z.string().default(""),
});

const brandSchema = z.object({
  primary: z.string().default("#0A2540"),
  secondary: z.string().default("#000000"),
  accent: z.string().default("#FFFFFF"),
  displayName: z.string().default(""),
  shortName: z.string().default(""),
  logoDataUri: z.string().default(""),
});

export const storyCardSchema = z.object({
  card: cardSchema,
  brand: brandSchema,
});

type Props = z.infer<typeof storyCardSchema>;
type CardProps = Props["card"];
type BrandProps = Props["brand"];
type Roles = { ground: string; surface: string; accent: string };

// Six palette role permutations — mirror creative_brief/generator.py
// _apply_palette_seed so the static graphic and motion render agree on
// which colour plays which role for a given variationSeed.
function rolesForSeed(brand: BrandProps, seed: number): Roles {
  const p = brand.primary || "#0A2540";
  const s = brand.secondary || "#000000";
  const a = brand.accent || "#FFFFFF";
  const mode = ((seed | 0) % 6 + 6) % 6;
  if (mode === 1) return { ground: s, surface: p, accent: a };
  if (mode === 2) return { ground: a, surface: p, accent: s };
  if (mode === 3) return { ground: p, surface: a, accent: s };
  if (mode === 4) return { ground: s, surface: a, accent: p };
  if (mode === 5) return { ground: a, surface: s, accent: p };
  return { ground: p, surface: s, accent: a };
}

// Map brief.background_style → an SVG data URI we layer over the ground
// colour at low opacity. Each generator is deliberately monochrome
// (uses the accent role) so the pattern reads as texture, not a
// competing illustration.
function bgPatternFor(style: string, roles: Roles): string {
  const accent = roles.accent || "#FFFFFF";
  const encode = (svg: string) =>
    `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  const stroke = (op: number) =>
    `${accent}${Math.round(op * 255).toString(16).padStart(2, "0")}`;
  switch (style) {
    case "dots":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>` +
        `<circle cx='12' cy='12' r='3' fill='${stroke(0.18)}'/></svg>`,
      );
    case "diagonal":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>` +
        `<path d='M0,40 L40,0' stroke='${stroke(0.16)}' stroke-width='2'/></svg>`,
      );
    case "stripes":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='8'>` +
        `<rect width='40' height='4' fill='${stroke(0.18)}'/></svg>`,
      );
    case "geometric":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>` +
        `<polygon points='60,10 110,90 10,90' fill='none' stroke='${stroke(0.18)}' stroke-width='2'/></svg>`,
      );
    case "halftone":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30'>` +
        `<circle cx='15' cy='15' r='5' fill='${stroke(0.22)}'/></svg>`,
      );
    case "grain":
      // SVG <feTurbulence> rendered server-side is heavy; approximate
      // with sparse noise dots.
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60'>` +
        `<circle cx='6' cy='12' r='1' fill='${stroke(0.18)}'/>` +
        `<circle cx='42' cy='28' r='1' fill='${stroke(0.18)}'/>` +
        `<circle cx='22' cy='48' r='1' fill='${stroke(0.18)}'/></svg>`,
      );
    case "water":
      return encode(
        `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='60'>` +
        `<path d='M0,30 Q30,10 60,30 T120,30' fill='none' stroke='${stroke(0.18)}' stroke-width='2'/></svg>`,
      );
    case "radial":
    case "duotone":
    case "clean":
    default:
      return "";
  }
}

// Map brief.typography_pair → a CSS font-family stack. The reel now loads the
// SAME self-hosted brand woff2 as the still graphic (see src/fonts.ts; Council
// 2026-05-31), so each stack LEADS with the real brand face and matches the
// posted card. The system fonts are kept only as a safety net behind it.
function fontStackFor(pair: string): string {
  switch (pair) {
    case "anton-inter":
    case "druk-inter":
    case "oswald-inter":
      // Heavy condensed display → Anton (the still renderer's default headline).
      return "'Anton', 'Oswald', 'Impact', 'Helvetica Neue Condensed', 'Arial Narrow', sans-serif";
    case "bebas-grotesk":
      return "'Bebas Neue', 'Oswald', 'Impact', 'Arial Narrow', sans-serif";
    case "bowlby-inter":
      return "'Bowlby One', 'Archivo Black', 'Impact', sans-serif";
    case "archivo-inter":
      return "'Space Grotesk', 'Archivo', 'Inter', 'Helvetica Neue', Arial, sans-serif";
    default:
      return "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif";
  }
}

// Map mood → spring config. The mood field is set by the AI director
// (e.g. "electric, precise", "calm, weighty", "celebratory") so the
// motion render's energy actually matches the static graphic's vibe.
function springConfigFor(mood: string): { damping: number; stiffness: number; mass: number } {
  const m = (mood || "").toLowerCase();
  if (m.includes("calm") || m.includes("weighty") || m.includes("composed")) {
    return { damping: 30, stiffness: 60, mass: 1.1 };
  }
  if (m.includes("electric") || m.includes("snappy") || m.includes("kinetic")) {
    return { damping: 12, stiffness: 140, mass: 0.6 };
  }
  if (m.includes("celebratory") || m.includes("bold") || m.includes("triumph")) {
    return { damping: 15, stiffness: 110, mass: 0.7 };
  }
  return { damping: 18, stiffness: 90, mass: 0.7 };
}

// Map the still graphic's v2 archetype → the motion scene's structural
// emphasis, so the reel beat for a card reads like its still (SEQ-4).
// Type-led archetypes make the result numeral THE hero; spotlight/centred
// archetypes centre the composition. Unknown / v1 names get no treatment —
// the variationSeed + axis behaviour stays exactly as before.
function archetypeTreatment(archetype: string): {
  typeLed: boolean;
  centred: boolean;
} {
  switch (archetype) {
    case "big_number_dominant":
    case "minimal_type_poster":
    case "editorial_numbers_grid":
    case "stat_stack_sidebar":
    case "ticker_strip":
    case "quote_led_recap":
      return { typeLed: true, centred: archetype !== "stat_stack_sidebar" };
    case "centered_medal_spotlight":
      return { typeLed: false, centred: true };
    default:
      return { typeLed: false, centred: false };
  }
}

// Map brief.composition → where the surname/result block lives. The
// values match the four positions the static renderer supports
// (graphic_renderer/render.py:_composition_overrides_css).
function compositionLayoutFor(
  composition: string,
  width: number,
): { textLeft: number; textAlign: "left" | "right" | "center"; surnameRight: number } {
  switch (composition) {
    case "left":
      return { textLeft: 80, textAlign: "left", surnameRight: -width * 0.06 };
    case "right":
      return { textLeft: width * 0.45, textAlign: "left", surnameRight: width * 0.42 };
    case "center":
      return { textLeft: width * 0.08, textAlign: "center", surnameRight: width * 0.5 };
    case "off-center":
      return { textLeft: width * 0.18, textAlign: "left", surnameRight: -width * 0.02 };
    default:
      return { textLeft: 80, textAlign: "left", surnameRight: -width * 0.06 };
  }
}

// Map brief.accent_style → a small decorative element. Returns null
// when "minimal" or unknown so the composition stays clean.
function accentDecoration(
  style: string,
  roles: Roles,
  opacity: number,
  width: number,
  height: number,
): React.ReactNode {
  const accent = roles.accent;
  switch (style) {
    case "stripe":
      return (
        <div
          style={{
            position: "absolute",
            left: 80,
            top: height * 0.42,
            width: 120,
            height: 6,
            background: accent,
            opacity,
          }}
        />
      );
    case "brackets":
      return (
        <>
          <div
            style={{
              position: "absolute",
              left: 60,
              top: height * 0.43,
              width: 40,
              height: 40,
              borderLeft: `4px solid ${accent}`,
              borderTop: `4px solid ${accent}`,
              opacity,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: width - 100,
              bottom: height * 0.2,
              width: 40,
              height: 40,
              borderRight: `4px solid ${accent}`,
              borderBottom: `4px solid ${accent}`,
              opacity,
            }}
          />
        </>
      );
    case "underline":
      return (
        <div
          style={{
            position: "absolute",
            left: 80,
            top: height * 0.82,
            width: 240,
            height: 4,
            background: accent,
            opacity,
          }}
        />
      );
    case "arrow":
      return (
        <div
          style={{
            position: "absolute",
            left: width - 160,
            top: height * 0.5,
            width: 0,
            height: 0,
            borderTop: "20px solid transparent",
            borderBottom: "20px solid transparent",
            borderLeft: `30px solid ${accent}`,
            opacity,
          }}
        />
      );
    case "ribbon":
      return (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: height * 0.36,
            width: 320,
            height: 48,
            background: accent,
            opacity,
            transform: "skewX(-12deg)",
            transformOrigin: "left center",
          }}
        />
      );
    case "frame":
      return (
        <div
          style={{
            position: "absolute",
            left: 40,
            top: 40,
            right: 40,
            bottom: 40,
            border: `3px solid ${accent}`,
            opacity: opacity * 0.4,
            pointerEvents: "none",
          }}
        />
      );
    case "badge":
      return (
        <div
          style={{
            position: "absolute",
            right: 80,
            bottom: height * 0.22,
            width: 90,
            height: 90,
            borderRadius: "50%",
            border: `4px solid ${accent}`,
            opacity,
          }}
        />
      );
    case "minimal":
    default:
      return null;
  }
}

export const StoryCard: React.FC<Props> = ({ card, brand }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const roles = rolesForSeed(brand, card.variationSeed || 0);
  const fontStack = fontStackFor(card.typographyPair || "");
  const springCfg = springConfigFor(card.mood || "");
  const treatment = archetypeTreatment(card.archetype || "");
  // The archetype's centring only fills in when the brief didn't pin an
  // explicit composition — an explicit axis always wins.
  const layout = compositionLayoutFor(
    card.composition || (treatment.centred ? "center" : "left"),
    width,
  );
  const bgPattern = bgPatternFor(card.backgroundStyle || "", roles);
  const resultFontSize = treatment.typeLed ? 196 : 132;

  // Intro: spring-eased big surname swoop + result fade. The spring
  // config is mood-driven so an "electric" card snaps in quickly while
  // a "composed" one settles slowly.
  const introSpring = spring({
    frame,
    fps,
    config: springCfg,
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
        fontFamily: fontStack,
        opacity: outroFade,
      }}
    >
      {/* Athlete photo — full-bleed base layer when the card carries one.
          The ground-colour gradient keeps every text layer legible;
          "no-photo" treatments never receive a photoSrc (motion.py
          strips it before the props reach us). */}
      {card.photoSrc ? (
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
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `linear-gradient(180deg, ${roles.ground}40 0%, ${roles.ground}B0 55%, ${roles.ground}F0 100%)`,
            }}
          />
        </>
      ) : null}

      {/* Background pattern overlay (driven by brief.background_style). */}
      {bgPattern ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage: bgPattern,
            backgroundRepeat: "repeat",
            opacity: 0.85,
            pointerEvents: "none",
          }}
        />
      ) : null}

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

      {/* Accent decoration — driven by brief.accent_style */}
      {accentDecoration(card.accentStyle || "", roles, chipOpacity, width, height)}

      {/* Mega watermark surname behind everything */}
      <div
        style={{
          position: "absolute",
          top: height * 0.18,
          right: layout.surnameRight,
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

      {/* Club logo — top-right corner. Falls back silently when no SVG. */}
      {brand.logoDataUri ? (
        <img
          src={brand.logoDataUri}
          alt={brand.displayName || "club logo"}
          style={{
            position: "absolute",
            top: 100,
            right: 80,
            width: 140,
            height: 140,
            objectFit: "contain",
            opacity: chipOpacity,
          }}
        />
      ) : null}

      {/* Athlete first name */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.45,
          fontSize: 96,
          fontWeight: 700,
          color: roles.accent,
          letterSpacing: "-0.01em",
          opacity: surnameOpacity,
          textAlign: layout.textAlign,
          transform: `translateY(${surnameY * 0.3}px)`,
        }}
      >
        {firstName}
      </div>

      {/* Athlete surname — large hero */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.51,
          fontSize: 168,
          fontWeight: 900,
          color: roles.accent,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          opacity: surnameOpacity,
          textAlign: layout.textAlign,
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
          left: layout.textLeft,
          top: height * 0.65,
          fontSize: 36,
          color: roles.accent,
          opacity: surnameOpacity * 0.85,
          letterSpacing: "0.04em",
          textAlign: layout.textAlign,
        }}
      >
        {event}
      </div>

      {/* Result value — hero metric (type-led archetypes upsize it) */}
      <div
        style={{
          position: "absolute",
          left: layout.textLeft,
          top: height * 0.70,
          fontSize: resultFontSize,
          fontWeight: 800,
          color: roles.accent,
          letterSpacing: "-0.01em",
          opacity: resultOpacity,
          transform: `scale(${resultScale})`,
          transformOrigin: "left center",
          fontVariantNumeric: "tabular-nums",
          textAlign: layout.textAlign,
        }}
      >
        {result || "—"}
      </div>

      {/* Measured emphasis line (e.g. "−0.42s on PB") — only real data,
          rendered as an accent kicker under the result. Collapses when
          the pipeline measured nothing. */}
      {card.heroStat ? (
        <div
          style={{
            position: "absolute",
            left: layout.textLeft,
            top: height * (treatment.typeLed ? 0.795 : 0.78),
            fontSize: 40,
            fontWeight: 700,
            color: roles.accent,
            letterSpacing: "0.08em",
            opacity: resultOpacity * 0.9,
            textAlign: layout.textAlign,
            textTransform: "uppercase",
          }}
        >
          {card.heroStat}
        </div>
      ) : null}

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
