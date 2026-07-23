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
import {
  StoryCard,
  cardSchema,
  fontStackFor,
  motionBlurSchema,
  MotionBlurSampler,
  type MotionBlur,
} from "./StoryCard";
import { REEL_LAYERS } from "./sprint/reelRegistry";
import { Dither } from "./Dither";
import { LogoDrawOn, LogoDrawConfig } from "./sprint/reel/logo_drawon";

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

// R1.12 — beat-rhythm & duration customisation. Every field is optional with a
// default that reproduces the reel's original skeleton, so a reel rendered with
// no `rhythm` prop (the common case) carves byte-identically to before.
//   coverSec / outroSec — bookend scene seconds (Python mirrors these into the
//     total via reel_duration_for, so the carving here always sums to the total).
//   perCardSec — the per-card base; consumed Python-side to size the total,
//     carried here only for schema parity (the carving works off the total).
//   beatWeights — explicit per-card weights. Empty = keep the default emphasis
//     (top-ranked moment breathes ~25% longer); non-empty overrides it, padding
//     to 1.0 for any card past the supplied list.
const reelRhythmSchema = z.object({
  coverSec: z.number().default(2.0),
  // M17 — 2.5s default outro so the CTA (sponsor thank-you / next-up /
  // follow) is legibly on screen. Mirrored in motion.py's REEL_OUTRO_SEC and
  // the ffmpeg carve; explicit rhythm.outro callers keep full control.
  outroSec: z.number().default(2.5),
  perCardSec: z.number().default(4.0),
  beatWeights: z.array(z.number()).default([]),
});

// R1.13 — custom reel stat chips. The honest stat vocabulary the cover can
// surface plus the operator config that selects / orders / renames them. Every
// value is counted from real card facts (see reelStats); the config only
// chooses WHICH honest chips show, HOW MANY, and their display WORDING — never
// the numbers themselves.
export const DEFAULT_STAT_IDS = ["swims", "pbs", "medals"];
export const DEFAULT_MAX_CHIPS = 3;

const reelStatConfigSchema = z.object({
  // Ordered allow-list of stat ids to surface; empty = the honest default set.
  include: z.array(z.string()).default([]),
  // Cap on how many chips the cover shows (cover space is finite).
  max: z.number().default(DEFAULT_MAX_CHIPS),
  // Per-id display-wording overrides. A "{n}" placeholder marks where the
  // honest count is rendered (one is prepended if absent), so the value still
  // counts up — only the words change, never the number.
  labels: z.record(z.string(), z.string()).default({}),
});

// One honest stat chip: its id, the integer value counted from real card
// facts, and the literal prefix / suffix wrapped around the count-up number.
export type ReelStat = { id: string; value: number; prefix: string; suffix: string };
export type ReelStatConfig = {
  include?: string[];
  max?: number;
  labels?: Record<string, string>;
};

export const meetReelSchema = z.object({
  cards: z.array(cardSchema),
  brand: brandSchema,
  meetName: z.string().default(""),
  // R1.12 — optional beat-rhythm & duration customisation. Absent = the default
  // skeleton (the component fills 2.0/1.0 and the top-card emphasis), so a reel
  // rendered without a rhythm prop is byte-identical. Present = caller
  // customisation, with each inner field defaulted by the schema above.
  rhythm: reelRhythmSchema.optional(),
  // R1.13 — optional stat-chip config. Omitting it keeps the byte-identical
  // default cover (TOP-N SWIMS / PBS / MEDALS). This is the configurable seam;
  // the renderer derives every value from the cards' own facts regardless.
  reelStatConfig: reelStatConfigSchema.optional(),
  // R1.30 — data-driven outro CTA inputs. Both optional; when both are blank
  // the outro falls back to the universal "follow the club" close, so every
  // existing reel renders byte-identically. A sponsor name (honest — sourced
  // from the club's configured sponsor) drives the "proudly supported by"
  // close; a next-meet label drives the "next up" close. Never fabricated:
  // the close only names a sponsor / next meet the caller actually supplied.
  sponsor: z.string().default(""),
  nextMeet: z.string().default(""),
  // M18 — brand-true cover/outro props, resolved Python-side. coverRole* is
  // the APCA-gated role set from the same graphic_renderer resolver the card
  // beats use; coverTypography follows the top card's typography pair; the
  // photo pair feeds the fifth "photo" cover variant (only eligible when a
  // photo exists). ALL optional with "" defaults so a prop-less reel renders
  // byte-identically to before.
  coverRoleGround: z.string().default(""),
  coverRoleSurface: z.string().default(""),
  coverRoleAccent: z.string().default(""),
  coverRoleOnGround: z.string().default(""),
  coverTypography: z.string().default(""),
  coverPhotoSrc: z.string().default(""),
  coverPhotoPos: z.string().default(""),
  // svg-shape-decompose — opt-in logo draw-on for the cover + outro "brand
  // statement" scenes. All three default to inactive/no-op so a prop-less reel
  // renders the exact filled `<img>` logo, byte-identical to before. When
  // active, Python sends the SVG's viewBox and its ordered per-path
  // `{ d, len, stroke }` list (decomposed deterministically Python-side); the
  // stroke draws on then cross-fades into the real filled logo. Zod strips
  // undeclared keys, so these MUST be top-level props (not nested in rhythm).
  logoDrawOn: z.boolean().default(false),
  logoViewBox: z.string().default(""),
  logoPaths: z
    .array(
      z.object({
        d: z.string(),
        len: z.number(),
        stroke: z.string(),
      }),
    )
    .default([]),
  // alpha-export: when true the reel is being rendered for a transparent-
  // background compositing export, so the CoverScreen and OutroScreen full-bleed
  // ground fills are SUPPRESSED (the card beats inherit it via each card's own
  // `transparentBg` prop). Set ONLY by motion.py on the opt-in alpha path; the
  // default false keeps every bookend's DOM byte-identical.
  transparentBg: z.boolean().default(false),
  // true-motion-blur (opt-in): the reel-level shutter-accumulation config. The
  // whip transition lives in the composition chrome (not per-card), so it is a
  // reel-level prop, resolved once Python-side and threaded down to BOTH the whip
  // wrappers AND each <StoryCard> beat's entrance/count-up (via a dedicated prop,
  // never cards_props). `.optional()` (absent => undefined) keeps the inactive DOM
  // the exact current whip feGaussianBlur + unwrapped beats (byte-identical).
  motionBlur: motionBlurSchema.optional(),
});

// The resolved bookend colour roles a cover/outro paints with. Every field
// falls back to the legacy safe pairing (accent text on the primary ground,
// secondary for bars) when Python sent no resolved roles — the pre-M18 look.
export type CoverRoles = {
  ground: string;
  surface: string;
  accent: string;
  onGround: string;
};

type Props = z.infer<typeof meetReelSchema>;
type CardItem = Props["cards"][number];

// The reel's headline face — the same self-hosted brand stack the story
// cards lead with (src/fonts.ts), so cover/outro match the posted card.
const COVER_FONT =
  "'Anton', 'Oswald', 'Impact', 'Helvetica Neue Condensed', 'Arial Narrow', sans-serif";
const BODY_FONT =
  "'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif";

// Honest cover/outro stats — every chip is counted ONLY from the real card
// facts the recognition layer produced (achievementLabel, eventName, heroStat).
// We never read a card's raw .place (heat-vs-final places are ambiguous — a
// medal or win counts only when the label says so) and never invent a number.
// R1.13 makes the set configurable: `config.include` selects/orders the ids,
// `config.max` caps the count, `config.labels` overrides display wording. With
// no config the result is byte-identical to before (TOP-N SWIMS / PBS / MEDALS).
export function reelStats(cards: CardItem[], config?: ReelStatConfig): ReelStat[] {
  const list = cards || [];
  // Uppercased honest facts, computed once per card.
  const labels = list.map((c) => (c.achievementLabel || "").toUpperCase());
  const events = list.map((c) => (c.eventName || "").toUpperCase());
  const heroes = list.map((c) => (c.heroStat || "").toUpperCase());

  const any = (s: string, ...needles: string[]) => needles.some((n) => s.includes(n));
  // Word-boundary helpers for short tokens that would false-match as substrings.
  const seasonBest = (s: string) => /\bSB\b/.test(s) || s.includes("SEASON BEST");
  const isFinal = (s: string) => /\bFINALS?\b/.test(s) && !s.includes("SEMI");
  // A win is counted only when the verified label says so — never from a bare
  // place number — and relay wins additionally require a relay event. Word
  // boundaries keep "CHAMPIONS" (a win) apart from "CHAMPIONSHIP" (a meet name)
  // and catch WIN / WINS / WON / WINNER(S) / WINNING without matching "WINDOW".
  const won = (s: string) =>
    s.includes("GOLD") ||
    s.includes("VICTORY") ||
    /\bCHAMPIONS?\b/.test(s) ||
    /\bWIN(?:S|NER|NERS|NING)?\b/.test(s) ||
    /\bWON\b/.test(s) ||
    /\b1ST\b/.test(s);

  // Honest integer counts, keyed by stat id.
  const counts: Record<string, number> = {
    swims: list.length,
    pbs: labels.filter((l) => l.includes("PB") || l.includes("PERSONAL BEST")).length,
    medals: labels.filter((l) => any(l, "GOLD", "SILVER", "BRONZE", "MEDAL")).length,
    records: labels.filter((l) => l.includes("RECORD")).length,
    seasonBests: labels.filter((l) => seasonBest(l)).length,
    relayWins: list.filter((_, i) => events[i].includes("RELAY") && won(labels[i])).length,
    finals: list.filter((_, i) => isFinal(events[i]) || isFinal(labels[i])).length,
    topSplits: list.filter((_, i) => labels[i].includes("SPLIT") || heroes[i].includes("SPLIT"))
      .length,
  };

  // Default display wording per id, pluralised on the FINAL count so the words
  // never flicker mid count-up. "{n}" marks where the number is rendered.
  const wording = (id: string, n: number): string => {
    const one = n === 1;
    if (id === "swims") return `TOP {n} ${one ? "SWIM" : "SWIMS"}`;
    if (id === "pbs") return `{n} ${one ? "PB" : "PBS"}`;
    if (id === "medals") return `{n} ${one ? "MEDAL" : "MEDALS"}`;
    if (id === "records") return `{n} ${one ? "RECORD" : "RECORDS"}`;
    if (id === "seasonBests") return `{n} ${one ? "SEASON BEST" : "SEASON BESTS"}`;
    if (id === "relayWins") return `{n} ${one ? "RELAY WIN" : "RELAY WINS"}`;
    if (id === "finals") return `{n} ${one ? "FINAL" : "FINALS"}`;
    if (id === "topSplits") return `{n} ${one ? "TOP SPLIT" : "TOP SPLITS"}`;
    return `{n} ${id.toUpperCase()}`;
  };

  const order =
    config && config.include && config.include.length ? config.include : DEFAULT_STAT_IDS;
  const max = Math.max(
    0,
    config && typeof config.max === "number" ? config.max : DEFAULT_MAX_CHIPS,
  );
  const overrides = (config && config.labels) || {};

  const chips: ReelStat[] = [];
  for (const id of order) {
    if (chips.length >= max) break; // cap reached (max 0 → no chips)
    if (!(id in counts)) continue; // ignore unknown ids
    const value = counts[id];
    if (value <= 0) continue; // honest: never render a zero chip
    let tpl = overrides[id] || wording(id, value);
    if (!tpl.includes("{n}")) tpl = `{n} ${tpl}`; // keep the count visible
    const cut = tpl.indexOf("{n}");
    chips.push({ id, value, prefix: tpl.slice(0, cut), suffix: tpl.slice(cut + 3) });
  }
  return chips;
}

// Honest counts the data-driven cover variant (R1.30) reads from — swims /
// PBs / medals, counted the same honest way reelStats counts them, but
// INDEPENDENT of the operator's chip config: the cover variant reflects what
// the weekend actually produced, not which chips the operator chose to show.
// Named off the `reelStats` prefix so the stat-chip transpile harness (which
// extracts by splitting on "export function reelStats") never mis-grabs it.
function coverStatCounts(cards: CardItem[]): { swims: number; pbs: number; medals: number } {
  const labels = (cards || []).map((c) => (c.achievementLabel || "").toUpperCase());
  return {
    swims: (cards || []).length,
    pbs: labels.filter((l) => l.includes("PB") || l.includes("PERSONAL BEST")).length,
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
// piece rather than a transition showreel. The bold catalog spans a defocus
// resolve, a momentum zoom, a lateral whip, a spotlight iris, a digital
// glitch, a structured slide-stack, and a brand-accent light-sweep.
type TransitionKind =
  | "crossfade"
  | "push"
  | "wipe"
  | "blur"
  | "zoom"
  | "whip"
  | "iris"
  | "glitch"
  | "slide-stack"
  | "light-sweep";

// A transition is a (kind, duration) pair: the cut AND how long it takes.
// `durationSeconds` is the per-card timing field — snappy kinds resolve fast
// (a glitch is a jolt, a whip a flick) while reveals breathe (a blur or a
// light-sweep uses the whole window). It's kept in seconds so the picker
// stays fps-free; the component converts it to frames and caps the result at
// the beat's handoff budget so a transition never runs longer than the
// overlap it has to play against (transitions.md: never eat the next build).
export type TransitionSpec = { kind: TransitionKind; durationSeconds: number };

// Each kind's natural duration. The handoff budget is ~0.35s, so anything at
// 0.35 fills the window exactly — keeping the quiet connective cuts
// (crossfade/push/wipe) byte-identical to the pre-R1.14 timing — while the
// bold peak cuts carry their own snappier or slower character.
const TRANSITION_SECONDS: Record<TransitionKind, number> = {
  crossfade: 0.35,
  push: 0.35,
  wipe: 0.35,
  blur: 0.35,
  iris: 0.34,
  "light-sweep": 0.34,
  zoom: 0.3,
  "slide-stack": 0.3,
  whip: 0.24,
  glitch: 0.18,
};

export function transitionFor(
  seed: number,
  opts?: { peak?: boolean; mood?: string },
): TransitionSpec {
  const at = (kind: TransitionKind): TransitionSpec => ({
    kind,
    durationSeconds: TRANSITION_SECONDS[kind],
  });
  if (opts?.peak) {
    // The earned, boldest cut — its character derives from the beat's mood,
    // and the seed picks between the two cuts that share that character so
    // the peak doesn't read identically across a club's reels: soft moods
    // resolve out of a defocus; percussive moods snap in on a digital glitch
    // or a lateral whip; a medal/celebration opens on a spotlight iris or a
    // brand light-sweep; everything else drives in with a momentum zoom or a
    // structured slide-stack.
    const m = (opts.mood || "").toLowerCase();
    const alt = (((seed | 0) % 2) + 2) % 2 === 1;
    if (
      m.includes("calm") ||
      m.includes("stoic") ||
      m.includes("precise") ||
      m.includes("warm") ||
      m.includes("minimal")
    ) {
      return at("blur");
    }
    if (m.includes("explosive") || m.includes("electric") || m.includes("fierce")) {
      return at(alt ? "glitch" : "whip");
    }
    if (m.includes("celebratory") || m.includes("triumph") || m.includes("medal")) {
      return at(alt ? "light-sweep" : "iris");
    }
    return at(alt ? "slide-stack" : "zoom");
  }
  // Connective beats: one consistent quiet kind, spread only across reels.
  const mode = ((seed | 0) % 3 + 3) % 3;
  if (mode === 1) return at("push");
  if (mode === 2) return at("wipe");
  return at("crossfade");
}

// A transition's frame window: its own per-card duration, floored so it never
// degenerates to nothing and capped at the beat's handoff budget (the overlap
// it plays against). Pure arithmetic — same inputs, same window.
export function transitionFramesFor(
  durationSeconds: number,
  budgetFrames: number,
  fps: number,
): number {
  const floor = Math.min(budgetFrames, Math.max(1, Math.round(fps * 0.13)));
  const want = Math.round(durationSeconds * fps);
  return Math.max(floor, Math.min(budgetFrames, want));
}

const StatChips: React.FC<{
  chips: ReelStat[];
  accent: string;
  ground: string;
  ts: number;
  opacity: number;
  progress: number;
}> = ({ chips, accent, ground, ts, opacity, progress }) => {
  if (!chips || chips.length === 0) {
    return null;
  }
  // Each chip's number counts up to its honest value as the row fades in — a
  // pure function of the frame-derived progress, so re-renders stay
  // byte-identical. The surrounding words were pluralised on the FINAL value
  // (in reelStats), so they never flicker between forms mid-count. flexWrap +
  // nowrap let a configured, longer chip set fall to a second row instead of
  // clipping, while the default three-chip row is unchanged.
  const p = Math.max(0, Math.min(1, progress));
  return (
    <div
      style={{
        marginTop: Math.round(44 * ts),
        display: "flex",
        gap: Math.round(18 * ts),
        justifyContent: "center",
        flexWrap: "wrap",
        opacity,
      }}
    >
      {chips.map((chip, i) => (
        <div
          key={chip.id || i}
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
            whiteSpace: "nowrap",
          }}
        >
          {chip.prefix}
          {Math.round(chip.value * p)}
          {chip.suffix}
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
// honest stat-chip count-up and the scene's exit fade are shared. The chips
// themselves come from R1.13's configurable reelStats; the variant SELECTION
// reads the config-independent coverStatCounts (what the weekend produced).
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

export type CoverVariant = "stack" | "masthead" | "spotlight" | "banner" | "photo";

// Honest, data-driven cover selection. A medal/PB-heavy weekend EARNS the
// stat-forward "spotlight" cover (it leads with a big honest number); a quiet
// weekend never fabricates a hero stat it doesn't have, so spotlight is left
// out of its pool entirely. The per-meet seed then picks within the eligible
// pool, so covers vary across meets without ever lying about the data.
// M18 — the full-bleed "photo" cover joins the pool ONLY when a real club
// photo reached the reel (hasPhoto); without one the pools (and therefore the
// modulo pick) are byte-identical to before.
export function coverVariantFor(
  seed: number,
  counts: { swims: number; pbs: number; medals: number },
  hasPhoto = false,
): CoverVariant {
  const statForward = counts.medals > 0 || counts.pbs >= 2;
  const pool: CoverVariant[] = statForward
    ? ["spotlight", "masthead", "stack", "banner"]
    : ["masthead", "stack", "banner"];
  if (hasPhoto) {
    pool.push("photo");
  }
  return pool[seed % pool.length];
}

// Honest cover eyebrows — a small closed vocabulary so a club's season of
// reels doesn't open with the identical word on every single cover. Every
// option is a truthful label for a meet-results recap (no invented framing).
// The per-meet seed picks one, so the SAME meet always draws the same eyebrow
// and different meets vary. Reads the HIGH bits of the seed to stay
// independent of the cover-variant pick, which reads the low bits.
export const COVER_EYEBROWS = [
  "Meet Recap",
  "Weekend Report",
  "The Highlights",
  "Results",
] as const;

export function coverEyebrowFor(seed: number): string {
  return COVER_EYEBROWS[(seed >>> 5) % COVER_EYEBROWS.length];
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
  eyebrow: string;
  chips: ReelStat[];
  counts: { swims: number; pbs: number; medals: number };
  env: CoverEnv;
  // M18 — resolved bookend roles (APCA-gated Python-side); each variant falls
  // back to the legacy brand pairing when the strings are empty.
  roles: CoverRoles;
  photoSrc: string;
  photoPos: string;
  // svg-shape-decompose — opt-in logo draw-on config (inactive by default, so
  // the variants keep the exact filled `<img>`).
  logoDraw: LogoDrawConfig;
};

// Variant 1 — STACK: the classic centred emblem lockup. Logo scales in, the
// meet name springs up under the seed-picked eyebrow, a brand-secondary rule
// grows out, club name and honest chips settle beneath.
const StackCover: React.FC<CoverVariantProps> = ({
  brand,
  meetName,
  eyebrow,
  chips,
  env,
  roles,
  logoDraw,
}) => {
  const { frame, fps, width, ts, chipsOpacity, chipsProgress } = env;
  const accent = roles.onGround || brand.accent || "#FFFFFF";
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
      <LogoDrawOn
        logoDataUri={brand.logoDataUri}
        alt={brand.displayName || "club logo"}
        style={{
          width: Math.round(220 * ts),
          height: Math.round(220 * ts),
          objectFit: "contain",
          marginBottom: Math.round(48 * ts),
          transform: `scale(${0.6 + 0.4 * logoScale})`,
          opacity: logoScale,
        }}
        draw={logoDraw}
        progress={logoScale}
      />
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
        {eyebrow}
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
          background: roles.surface || brand.secondary || accent,
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
        chips={chips}
        accent={accent}
        ground={roles.ground || brand.primary || "#0A2540"}
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
const MastheadCover: React.FC<CoverVariantProps> = ({
  brand,
  meetName,
  eyebrow,
  chips,
  env,
  roles,
  logoDraw,
}) => {
  const { frame, fps, width, height, ts, chipsOpacity, chipsProgress } = env;
  const accent = roles.onGround || brand.accent || "#FFFFFF";
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
          background: roles.surface || brand.secondary || accent,
          opacity: 0.95,
        }}
      />
      <LogoDrawOn
        logoDataUri={brand.logoDataUri}
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
        draw={logoDraw}
        progress={logoOpacity}
      />
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
          {eyebrow}
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
          chips={chips}
          accent={accent}
          ground={roles.ground || brand.primary || "#0A2540"}
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
const SpotlightCover: React.FC<CoverVariantProps> = ({ brand, meetName, counts, env, roles }) => {
  const { frame, fps, width, ts } = env;
  const accent = roles.onGround || brand.accent || "#FFFFFF";
  const hero =
    counts.medals > 0
      ? { n: counts.medals, label: counts.medals === 1 ? "MEDAL" : "MEDALS" }
      : counts.pbs > 0
        ? { n: counts.pbs, label: counts.pbs === 1 ? "PERSONAL BEST" : "PERSONAL BESTS" }
        : { n: counts.swims, label: counts.swims === 1 ? "TOP SWIM" : "TOP SWIMS" };
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
          background: roles.surface || brand.secondary || accent,
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
const BannerCover: React.FC<CoverVariantProps> = ({
  brand,
  meetName,
  eyebrow,
  chips,
  env,
  roles,
  logoDraw,
}) => {
  const { frame, fps, height, ts, chipsOpacity, chipsProgress } = env;
  const accent = roles.onGround || brand.accent || "#FFFFFF";
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
          {eyebrow}
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
          background: roles.surface || brand.secondary || accent,
          clipPath: `inset(0 ${bandClip}% 0 0)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <LogoDrawOn
          logoDataUri={brand.logoDataUri}
          alt={brand.displayName || "club logo"}
          style={{
            height: Math.round(bandH * 0.62),
            objectFit: "contain",
            opacity: logoOpacity,
          }}
          draw={logoDraw}
          progress={logoOpacity}
        />
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
          chips={chips}
          accent={accent}
          ground={roles.ground || brand.primary || "#0A2540"}
          ts={ts}
          opacity={chipsOpacity}
          progress={chipsProgress}
        />
      </div>
    </div>
  );
};

// Variant 5 — PHOTO (M18): the weekend's own hero photo, full-bleed, under a
// role-colour scrim with masthead type. Earned only when a real club photo
// reached the reel (coverVariantFor pool-gates it on hasPhoto), so this cover
// never fabricates imagery. The photo gets the same slow frame-pure push the
// card beats give theirs; text paints only resolved roles / brand fallbacks.
const PhotoCover: React.FC<CoverVariantProps> = ({
  brand,
  meetName,
  eyebrow,
  chips,
  env,
  roles,
  photoSrc,
  photoPos,
  logoDraw,
}) => {
  const { frame, fps, width, height, ts, chipsOpacity, chipsProgress } = env;
  const accent = roles.onGround || brand.accent || "#FFFFFF";
  const ground = roles.ground || brand.primary || "#0A2540";
  // Slow frame-pure push across the cover's ~2s so the photo never sits flat.
  const push = interpolate(frame, [0, Math.round(fps * 2.35)], [1.0, 1.05], {
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.sin),
  });
  const eyebrowOpacity = interpolate(frame, [fps * 0.15, fps * 0.5], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(
    spring({ frame: frame - 3, fps, config: { damping: 18, stiffness: 95, mass: 0.7 } }),
    [0, 1],
    [56, 0],
  );
  const titleOpacity = interpolate(frame, [3, fps * 0.5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const footerOpacity = interpolate(frame, [fps * 0.55, fps * 0.95], [0, 1], {
    extrapolateRight: "clamp",
  });
  const display = (brand.displayName || brand.shortName || "").toUpperCase();
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <img
        src={photoSrc}
        alt=""
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: photoPos || "center 28%",
          transform: `scale(${push})`,
        }}
      />
      {/* Role scrim — the ground colour carries legibility, top and bottom. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `linear-gradient(180deg, ${ground}88 0%, ${ground}30 38%, ${ground}55 62%, ${ground}E6 100%)`,
        }}
      />
      <LogoDrawOn
        logoDataUri={brand.logoDataUri}
        alt={brand.displayName || "club logo"}
        style={{
          position: "absolute",
          top: 84,
          right: 84,
          width: Math.round(120 * ts),
          height: Math.round(120 * ts),
          objectFit: "contain",
          opacity: eyebrowOpacity,
        }}
        draw={logoDraw}
        progress={eyebrowOpacity}
      />
      {/* Masthead block over the lower scrim. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: Math.round(height * 0.1),
          padding: "0 96px",
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontSize: Math.round(36 * ts),
            letterSpacing: "0.22em",
            color: accent,
            opacity: 0.85 * eyebrowOpacity,
            marginBottom: Math.round(22 * ts),
            textTransform: "uppercase",
            fontFamily: BODY_FONT,
            fontWeight: 700,
          }}
        >
          {eyebrow}
        </div>
        <div
          style={{
            fontSize: Math.round(120 * ts),
            fontWeight: 900,
            color: accent,
            lineHeight: 0.96,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
            maxWidth: width - 160,
            margin: "0 auto",
            transform: `translateY(${titleY}px)`,
            opacity: titleOpacity,
          }}
        >
          {meetName || "WEEKEND HIGHLIGHTS"}
        </div>
        <div style={{ opacity: footerOpacity }}>
          <div
            style={{
              marginTop: Math.round(24 * ts),
              fontSize: Math.round(36 * ts),
              color: accent,
              letterSpacing: "0.16em",
              fontWeight: 700,
              textTransform: "uppercase",
              fontFamily: BODY_FONT,
            }}
          >
            {display}
          </div>
          <StatChips
            chips={chips}
            accent={accent}
            ground={roles.ground || brand.primary || "#0A2540"}
            ts={ts}
            opacity={chipsOpacity}
            progress={chipsProgress}
          />
        </div>
      </div>
    </div>
  );
};

const CoverScreen: React.FC<{
  brand: Props["brand"];
  meetName: string;
  durationInFrames: number;
  chips: ReelStat[];
  counts: { swims: number; pbs: number; medals: number };
  roles: CoverRoles;
  fontStack: string;
  photoSrc: string;
  photoPos: string;
  // M16: only a cover that is the WHOLE reel (no card beats) may fade itself
  // out; inside a real reel the paired exit owns the handoff, so the cover
  // stays fully visible until the first beat's transition takes over.
  selfExit?: boolean;
  // render-banding-dither: true when a card in the reel opted into the dither
  // overlay, so the bookend backgrounds deband the same flat ground the beats
  // do. Default false keeps the cover byte-identical.
  dither?: boolean;
  // svg-shape-decompose — opt-in logo draw-on (inactive by default).
  logoDraw: LogoDrawConfig;
  // alpha-export — suppress the full-bleed ground fill for a transparent export.
  transparentBg?: boolean;
}> = ({
  brand,
  meetName,
  durationInFrames,
  chips,
  counts,
  roles,
  fontStack,
  photoSrc,
  photoPos,
  selfExit = false,
  dither = false,
  logoDraw,
  transparentBg = false,
}) => {
  const env = useCoverEnv(durationInFrames);
  // Data-driven: the variant is a pure function of the meet's identity and its
  // honest stats, so it is stable per meet and varied across meets. The
  // full-bleed photo cover is pool-gated on a photo actually existing (M18).
  const seed = reelSeed(`${meetName}|${counts.swims}|${counts.pbs}|${counts.medals}`);
  const variant = coverVariantFor(seed, counts, Boolean(photoSrc));
  const eyebrow = coverEyebrowFor(seed);
  const Body =
    variant === "photo"
      ? PhotoCover
      : variant === "spotlight"
        ? SpotlightCover
        : variant === "masthead"
          ? MastheadCover
          : variant === "banner"
            ? BannerCover
            : StackCover;
  return (
    <AbsoluteFill
      style={{
        // alpha-export: drop the full-bleed cover ground under the opt-in
        // transparent export (default false → the historic fill, byte-identical).
        ...(transparentBg
          ? {}
          : { backgroundColor: roles.ground || brand.primary || "#0A2540" }),
        fontFamily: fontStack || COVER_FONT,
        opacity: selfExit ? env.outroFade : 1,
      }}
    >
      {dither ? <Dither /> : null}
      <Body
        brand={brand}
        meetName={meetName}
        eyebrow={eyebrow}
        chips={chips}
        counts={counts}
        env={env}
        roles={roles}
        photoSrc={photoSrc}
        photoPos={photoPos}
        logoDraw={logoDraw}
      />
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
  // M18 — the same resolved bookend roles the cover paints with.
  roles: CoverRoles;
  // render-banding-dither: deband the flat outro ground when a card opted in.
  dither?: boolean;
  // svg-shape-decompose — opt-in logo draw-on (inactive by default).
  logoDraw: LogoDrawConfig;
  // alpha-export — suppress the full-bleed ground fill for a transparent export.
  transparentBg?: boolean;
}> = ({
  brand,
  meetName,
  durationInFrames,
  sponsor,
  nextMeet,
  roles,
  dither = false,
  logoDraw,
  transparentBg = false,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const ts = Math.min(width / 1080, height / 1440, 1);
  const accent = roles.onGround || brand.accent || "#FFFFFF";
  // M17 — legible-outro retiming inside the (now 2.5s-default) outro: logo +
  // club settled by ~0.5s, rule drawn right behind them, CTA fully readable
  // by ~0.9s, then a hold of ≥1.2s before the closing fade begins. The outro
  // remains the only scene allowed to animate itself out.
  const grow = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 150, mass: 0.55 },
  });
  const fadeIn = interpolate(frame, [0, fps * 0.25], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ruleW = interpolate(frame, [fps * 0.25, fps * 0.55], [0, 180], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const ctaOpacity = interpolate(frame, [fps * 0.5, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
  });
  const ctaY = interpolate(frame, [fps * 0.5, fps * 0.9], [18, 0], {
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
        // alpha-export: drop the full-bleed outro ground under the opt-in
        // transparent export (default false → the historic fill, byte-identical).
        ...(transparentBg
          ? {}
          : { backgroundColor: roles.ground || brand.primary || "#0A2540" }),
        fontFamily: COVER_FONT,
        opacity: outroFade,
      }}
    >
      {dither ? <Dither /> : null}
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
        <LogoDrawOn
          logoDataUri={brand.logoDataUri}
          alt={brand.displayName || "club logo"}
          style={{
            width: Math.round(260 * ts),
            height: Math.round(260 * ts),
            objectFit: "contain",
            marginBottom: Math.round(44 * ts),
            transform: `scale(${0.8 + 0.2 * grow})`,
          }}
          draw={logoDraw}
          progress={grow}
        />
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
            background: roles.surface || brand.secondary || accent,
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

export const MeetReel: React.FC<Props> = ({
  cards,
  brand,
  meetName,
  rhythm,
  reelStatConfig,
  sponsor,
  nextMeet,
  coverRoleGround,
  coverRoleSurface,
  coverRoleAccent,
  coverRoleOnGround,
  coverTypography,
  coverPhotoSrc,
  coverPhotoPos,
  logoDrawOn,
  logoViewBox,
  logoPaths,
  transparentBg,
  motionBlur,
}) => {
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const rootFrame = useCurrentFrame();
  // svg-shape-decompose — the cover + outro logo draw-on bundle. Active only
  // when the caller opted in AND Python decomposed at least one path; empty
  // otherwise, so the logo stays the exact filled `<img>` (byte-identical).
  const logoDraw: LogoDrawConfig = {
    on: Boolean(logoDrawOn) && (logoPaths || []).length > 0,
    viewBox: logoViewBox || "",
    paths: logoPaths || [],
  };

  // Allocate the reel: cover + rank/weight-carved card beats + outro.
  const safeCards = (cards || []).slice(0, 5);
  // R1.13 chips (configurable display) + R1.30 cover counts (config-independent
  // honest totals the variant SELECTION + spotlight numeral read from).
  const chips = reelStats(safeCards, reelStatConfig);
  const counts = coverStatCounts(safeCards);
  // render-banding-dither: the card beats deband via StoryCard's own <Dither>
  // (each carries the attach-only `dither` prop); the reel's cover/outro
  // bookends deband too when ANY card opted in, so the whole piece is coherent.
  // False (no card opted in) keeps every bookend byte-identical.
  const reelDither = safeCards.some((c) => Boolean(c.dither));
  // M18 — the resolved bookend roles (empty strings = legacy brand pairing)
  // and the top card's typography, shared by the cover AND the outro.
  const coverRoles: CoverRoles = {
    ground: coverRoleGround || "",
    surface: coverRoleSurface || "",
    accent: coverRoleAccent || "",
    onGround: coverRoleOnGround || "",
  };
  const coverFontStack = coverTypography ? fontStackFor(coverTypography) : "";
  if (safeCards.length === 0) {
    return (
      <CoverScreen
        brand={brand}
        meetName={meetName}
        durationInFrames={durationInFrames}
        chips={chips}
        counts={counts}
        roles={coverRoles}
        fontStack={coverFontStack}
        photoSrc={coverPhotoSrc || ""}
        photoPos={coverPhotoPos || ""}
        selfExit
        logoDraw={logoDraw}
        transparentBg={Boolean(transparentBg)}
      />
    );
  }

  // R1.12 — beat-rhythm & duration customisation. The bookend seconds and the
  // per-card beat weights are caller-customisable via the `rhythm` prop; the
  // defaults below reproduce the default 2s cover / 2.5s outro (M17) /
  // top-card-1.25 emphasis exactly, so a rhythm-less reel is byte-identical.
  const coverSec = rhythm && rhythm.coverSec > 0 ? rhythm.coverSec : 2.0;
  const outroSec = rhythm && rhythm.outroSec > 0 ? rhythm.outroSec : 2.5;
  const coverFrames = Math.round(fps * coverSec);
  const outroFrames = Math.round(fps * outroSec);
  const transitionFrames = Math.round(fps * 0.35);
  const remaining = Math.max(0, durationInFrames - coverFrames - outroFrames);

  // Per-card beat weights. With no explicit weights the reel keeps its default
  // emphasis: the top-ranked moment (cards arrive ranked from the Python side)
  // breathes ~25% longer than the connective beats. Explicit caller weights are
  // authoritative and pad to 1.0 for any card beyond the supplied list — Python
  // mirrors the same weights into the total (reel_duration_for), so a card
  // weighted 2× genuinely earns twice the seconds rather than squeezing the
  // others. Deterministic arithmetic — same inputs, same allocation.
  const explicitWeights = (rhythm && rhythm.beatWeights) || [];
  const weights = safeCards.map((_, i) => {
    if (explicitWeights.length > 0) {
      const w = explicitWeights[i];
      return typeof w === "number" && w > 0 ? w : 1.0;
    }
    return i === 0 && safeCards.length > 1 ? 1.25 : 1.0;
  });
  const weightSum = weights.reduce((a, b) => a + b, 0) || 1;
  const minBeat = transitionFrames * 2 + Math.round(fps * 0.5);
  const beatFrames = weights.map((w) =>
    Math.max(minBeat, Math.floor((remaining * w) / weightSum) + transitionFrames),
  );

  // The reel-level connective FALLBACK — the quiet kind derived from the top
  // card's seed. Used only for a lower beat that carries no seed of its own.
  const connective = transitionFor(safeCards[0]?.variationSeed || 0);

  // M16 — paired, velocity-matched transitions: every beat's INCOMING spec is
  // precomputed so the preceding scene (cover or beat) can play the matched
  // exit transform through the SAME window with the SAME kind. The first beat
  // is the #1 (top-ranked) moment — its entry off the brand cover is the
  // reel's peak, so it earns the bold, mood-chosen cut. Every LOWER beat picks
  // its OWN quiet connective kind from ITS card's seed (#1058), so consecutive
  // same-rank handoffs vary within the quiet trio (crossfade/push/wipe) rather
  // than all cutting identically — the peak stays the reel's only bold cut
  // (transitionFor keeps bold kinds peak-only), and a seedless beat falls back
  // to the reel-level `connective`.
  const specs = safeCards.map((card, i) => {
    const isPeak = i === 0 && safeCards.length > 1;
    if (isPeak) {
      return transitionFor(card.variationSeed || 0, { peak: true, mood: card.mood });
    }
    return card.variationSeed ? transitionFor(card.variationSeed) : connective;
  });
  // Per-card timing: the chosen cut's own duration, capped at the handoff
  // budget so it stays inside the beat overlap (never eats the next build).
  const beatFades = specs.map((spec) =>
    transitionFramesFor(spec.durationSeconds, transitionFrames, fps),
  );

  let cursor = 0;
  const sequences: React.ReactNode[] = [];
  const beatStarts: number[] = [];

  // The cover holds fully visible until the first beat's transition takes
  // over (no self-fade dip through black) and plays that spec's exit.
  sequences.push(
    <Sequence
      key="cover"
      from={cursor}
      durationInFrames={coverFrames + transitionFrames}
    >
      <ExitWrap
        kind={specs[0].kind}
        startLocal={coverFrames}
        exitFrames={beatFades[0]}
        mb={motionBlur}
      >
        <CoverScreen
          brand={brand}
          meetName={meetName}
          durationInFrames={coverFrames + transitionFrames}
          chips={chips}
          counts={counts}
          roles={coverRoles}
          fontStack={coverFontStack}
          photoSrc={coverPhotoSrc || ""}
          photoPos={coverPhotoPos || ""}
          dither={reelDither}
          logoDraw={logoDraw}
          transparentBg={Boolean(transparentBg)}
        />
      </ExitWrap>
    </Sequence>,
  );
  cursor += coverFrames;

  safeCards.forEach((card, i) => {
    const dur = beatFrames[i];
    const spec = specs[i];
    const fadeFrames = beatFades[i];
    // The light-sweep glints the club accent across the frame; pass the
    // card's resolved accent (the exact still-parity hex) so it stays
    // brand-true rather than inventing a highlight colour.
    const accent = card.roleAccent || brand.accent || "";
    // The outgoing side of this beat's handoff: the NEXT beat's spec (or the
    // outro's quiet crossfade — no exit transform, the outgoing beat simply
    // holds beneath the dissolve).
    const nextKind = i + 1 < safeCards.length ? specs[i + 1].kind : "crossfade";
    const nextFrames = i + 1 < safeCards.length ? beatFades[i + 1] : transitionFrames;
    beatStarts.push(cursor);
    sequences.push(
      <Sequence
        key={`card-${i}`}
        from={cursor}
        durationInFrames={dur + transitionFrames}
      >
        <ExitWrap
          kind={nextKind}
          startLocal={dur - transitionFrames}
          exitFrames={nextFrames}
          mb={motionBlur}
        >
          <TransitionWrap fadeInFrames={fadeFrames} kind={spec.kind} accent={accent} mb={motionBlur}>
            {/* true-motion-blur: the reel injects the shutter config as a dedicated
                prop so the beat's entrance/count-up blur without ever mutating
                cards_props (which stays byte-identical when off). */}
            <StoryCard card={{ ...card, inReel: true }} brand={brand} motionBlur={motionBlur} />
          </TransitionWrap>
        </ExitWrap>
      </Sequence>,
    );
    cursor += dur - transitionFrames;
  });

  // Outro — runs to the end of the reel, whatever rounding left over.
  const outroStart = cursor;
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
          roles={coverRoles}
          dither={reelDither}
          logoDraw={logoDraw}
          transparentBg={Boolean(transparentBg)}
        />
      </TransitionWrap>
    </Sequence>,
  );

  // M20 — whole-piece chrome data for the reel-overlay layers (progress rail,
  // club mark): the resolved role colours (top card first, then the cover
  // roles, then the raw brand) plus the beat grid the ticks mark.
  const chromeAccent =
    safeCards[0]?.roleAccent || coverRoles.accent || brand.accent || "#FFFFFF";
  const chromeGround =
    safeCards[0]?.roleGround || coverRoles.ground || brand.primary || "#0A2540";
  const chromeOnGround =
    safeCards[0]?.roleOnGround || coverRoles.onGround || brand.accent || "#FFFFFF";

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
            accent: chromeAccent,
            ground: chromeGround,
            onGround: chromeOnGround,
            clubLabel: brand.shortName || brand.displayName || "",
            logoDataUri: brand.logoDataUri || "",
            beatStarts,
            outroStart,
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
  accent?: string;
  // true-motion-blur (opt-in): reel-level shutter config. Absent (the default) =>
  // the whip renders its verbatim feGaussianBlur DOM (byte-identical).
  mb?: MotionBlur;
  children: React.ReactNode;
}> = ({ fadeInFrames, kind, accent, mb, children }) => {
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
    // true-motion-blur (opt-in): replace the single-Gaussian smear with REAL
    // shutter accumulation. The whip's lateral translateX + fade are closed-form
    // functions of the frame, so we resample them at N deterministic sub-frames
    // and composite N copies of the (unchanged) children — a genuine per-sample
    // pan blur, not a fake. The children are a rigid moving layer here (we blur the
    // whip's OWN transform, never re-time the children's internal animation), which
    // is exactly what a whip pan should smear. On the landing frame (t=1) all
    // sub-frames collapse to the resting transform, so the beat resolves clean.
    if (mb) {
      const whipAt = (f: number) => {
        const tt = interpolate(f, [0, fadeInFrames], [0, 1], {
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return { opacity: Math.min(1, tt * 1.6), tx: (1 - tt) * width * 0.5 };
      };
      return (
        <MotionBlurSampler
          frame={frame}
          samples={mb.samples}
          shutter={mb.shutter}
          render={(f) => {
            const w = whipAt(f);
            return (
              <AbsoluteFill style={{ opacity: w.opacity, transform: `translateX(${w.tx}px)` }}>
                {children}
              </AbsoluteFill>
            );
          }}
        />
      );
    }
    // Default (blur off): the verbatim velocity-aligned feGaussianBlur smear.
    // stdDeviation "X 0" blurs only along the X axis — the actual motion vector —
    // a directional smear, not isotropic softening. id is whip-only (peak beat).
    const t = ease(Easing.out(Easing.cubic));
    const whipBlur = (1 - t) * 14;
    return (
      <AbsoluteFill
        style={{
          opacity: Math.min(1, t * 1.6),
          transform: `translateX(${(1 - t) * width * 0.5}px)`,
          filter: "url(#reel-whip-in)",
        }}
      >
        <svg width="0" height="0" style={{ position: "absolute" }}>
          <filter
            id="reel-whip-in"
            x="-50%"
            y="-10%"
            width="200%"
            height="120%"
            filterUnits="objectBoundingBox"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation={`${whipBlur} 0`} edgeMode="duplicate" />
          </filter>
        </svg>
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
  if (kind === "glitch") {
    // Electric/percussive peak — a digital jolt that resolves clean. The
    // slice offset, horizontal jitter and stepped opacity are deterministic
    // functions of the frame (no randomness), all decaying to a stable,
    // brand-exact image by the end of the window.
    const t = ease(Easing.out(Easing.cubic));
    const decay = 1 - t;
    const jitter = Math.round(Math.sin(frame * 2.7) * 26 * decay);
    const slice = Math.max(0, Math.round((Math.sin(frame * 1.9) * 0.5 + 0.5) * 14 * decay));
    // Stepped opacity so the beat appears to "lock in" rather than fade.
    const op = Math.min(1, Math.round(t * 4) / 4 + t * 0.25);
    return (
      <AbsoluteFill
        style={{
          opacity: op,
          transform: `translateX(${jitter}px)`,
          clipPath: `inset(${slice}% 0 ${slice}% 0)`,
          filter: `contrast(${1 + decay * 0.6}) saturate(${1 + decay * 0.5})`,
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "slide-stack") {
    // Structured momentum — the beat slides up and settles onto its rest
    // position, reading like a card landing on a stack. Distinct from `push`
    // (a small fade-nudge) by a fuller travel and a scale settle.
    const t = ease(Easing.out(Easing.cubic));
    const y = (1 - t) * height * 0.22;
    const scale = interpolate(t, [0, 1], [0.96, 1]);
    return (
      <AbsoluteFill
        style={{
          opacity: Math.min(1, t * 2),
          transform: `translateY(${y}px) scale(${scale})`,
          transformOrigin: "center 60%",
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "light-sweep") {
    // Celebration reveal — the beat settles while a soft band of the club's
    // accent light sweeps diagonally across the frame, peaking mid-cut then
    // gone. Brand-exact: the glint is the resolved accent, never an invented
    // colour (falls back to white only when no accent reached the wrapper).
    const t = ease(Easing.inOut(Easing.cubic));
    const sweepX = interpolate(t, [0, 1], [-40, 140]);
    const sweepOpacity = interpolate(t, [0, 0.5, 1], [0, 0.5, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    const glint = accent || "#FFFFFF";
    return (
      <AbsoluteFill style={{ opacity: Math.min(1, t * 1.5), transform: `scale(${0.98 + 0.02 * t})` }}>
        {children}
        <AbsoluteFill
          style={{
            background: `linear-gradient(105deg, transparent ${sweepX - 18}%, ${glint} ${sweepX}%, transparent ${sweepX + 18}%)`,
            opacity: sweepOpacity,
            mixBlendMode: "screen",
            pointerEvents: "none",
          }}
        />
      </AbsoluteFill>
    );
  }
  return <AbsoluteFill style={{ opacity: ease((n) => n) }}>{children}</AbsoluteFill>;
};

// M16 — the paired exit wrapper. While the NEXT scene's TransitionWrap plays
// its entrance, the outgoing scene wrapped here plays the velocity-matched
// exit of the SAME TransitionSpec through the SAME frame window: the outgoing
// side accelerates (Easing.in) as the incoming side decelerates (Easing.out),
// so a push reads as one continuous camera move and a whip mirrors laterally.
// Non-directional kinds (crossfade / wipe / blur / iris / glitch /
// slide-stack / light-sweep entrances that cover or reveal) apply NO exit
// transform — the outgoing beat holds at full opacity beneath the incoming
// treatment, which is exactly what keeps handoffs from dipping through black.
const ExitWrap: React.FC<{
  kind: TransitionKind;
  startLocal: number; // local frame at which the incoming scene starts
  exitFrames: number; // the incoming transition's frame window
  // true-motion-blur (opt-in): reel-level shutter config. Absent (the default) =>
  // the whip exit renders its verbatim feGaussianBlur DOM (byte-identical).
  mb?: MotionBlur;
  children: React.ReactNode;
}> = ({ kind, startLocal, exitFrames, mb, children }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const exitT = (f: number) =>
    interpolate(f, [startLocal, startLocal + Math.max(1, exitFrames)], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    });
  const t = exitT(frame);
  if (t <= 0) {
    return <AbsoluteFill>{children}</AbsoluteFill>;
  }
  if (kind === "push") {
    // Mirrors the incoming push (translateY +12% → 0): the outgoing beat
    // travels up and out at matched velocity.
    return (
      <AbsoluteFill style={{ transform: `translateY(${-t * height * 0.12}px)` }}>
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "whip") {
    // true-motion-blur (opt-in): REAL shutter accumulation for the mirrored exit —
    // resample the closed-form lateral translateX at N deterministic sub-frames and
    // composite N copies of the (rigid) children, the exit twin of the incoming
    // whip's pan blur. On the fully-exited frame all sub-frames collapse, so the
    // handoff resolves clean.
    if (mb) {
      return (
        <MotionBlurSampler
          frame={frame}
          samples={mb.samples}
          shutter={mb.shutter}
          render={(f) => (
            <AbsoluteFill style={{ transform: `translateX(${-exitT(f) * width * 0.5}px)` }}>
              {children}
            </AbsoluteFill>
          )}
        />
      );
    }
    // Default (blur off): mirrors the incoming whip laterally, with the same
    // velocity-aligned (X-axis) feGaussianBlur "X 0", not an isotropic blur.
    const whipBlur = t * 14;
    return (
      <AbsoluteFill
        style={{
          transform: `translateX(${-t * width * 0.5}px)`,
          filter: "url(#reel-whip-out)",
        }}
      >
        <svg width="0" height="0" style={{ position: "absolute" }}>
          <filter
            id="reel-whip-out"
            x="-50%"
            y="-10%"
            width="200%"
            height="120%"
            filterUnits="objectBoundingBox"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation={`${whipBlur} 0`} edgeMode="duplicate" />
          </filter>
        </svg>
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "zoom") {
    // Zoom-through: the outgoing beat scales past the camera and softens as
    // the incoming one arrives beneath its own scale-up.
    return (
      <AbsoluteFill
        style={{ transform: `scale(${1 + 0.15 * t})`, opacity: 1 - 0.5 * t }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (kind === "slide-stack") {
    // The outgoing card recedes slightly as the next one lands on the stack.
    return (
      <AbsoluteFill
        style={{ transform: `translateY(${-t * height * 0.08}px) scale(${1 - 0.03 * t})` }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  // Crossfade / wipe / blur / iris / glitch / light-sweep: hold fully visible
  // beneath the incoming treatment — the transition IS the exit.
  return <AbsoluteFill>{children}</AbsoluteFill>;
};
