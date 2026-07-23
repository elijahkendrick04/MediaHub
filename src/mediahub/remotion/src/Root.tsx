import React from "react";
import { Composition } from "remotion";
import { StoryCard, storyCardSchema } from "./compositions/StoryCard";
import { MeetReel, meetReelSchema } from "./compositions/MeetReel";

const FPS = 30;
const STORY_W = 1080;
const STORY_H = 1920;

const STORY_DURATION_FRAMES = FPS * 6;
const REEL_DURATION_FRAMES = FPS * 15;

const defaultBrand = {
  primary: "#0A2540",
  secondary: "#000000",
  accent: "#FFFFFF",
  displayName: "Your Club",
  shortName: "CLUB",
  logoDataUri: "",
};

const defaultCard = {
  athleteFullName: "Sample Swimmer",
  athleteFirstName: "Sample",
  athleteSurname: "Swimmer",
  eventName: "100m Freestyle LC",
  resultValue: "00:54.32",
  achievementLabel: "NEW PB",
  meetName: "MediaHub Open",
  place: "1",
  variationSeed: 1,
  staggerScale: 0,
  backgroundStyle: "",
  composition: "",
  typographyPair: "",
  accentStyle: "",
  mood: "",
  photoTreatment: "",
  photoSrc: "",
  photoPos: "",
  // M23 footage beat (blank = photo path; production attaches a
  // footage_cache trim via visual/footage.py).
  videoSrc: "",
  videoStartSec: 0,
  videoDurationSec: 0,
  photoSrcs: [] as string[],
  cutoutSrc: "",
  photoMode: "",
  photoScale: 0,
  decorationStrength: 0.5,
  duotoneShadow: "",
  duotoneHighlight: "",
  halftoneTile: 0,
  stickerInk: "",
  stickerRadius: 0,
  washTint: "",
  washMix: 0,
  packGroundFocus: null as number[] | null,
  statChips: [] as { label: string; value: string }[],
  statInk: "",
  pbBars: null as null | { prev: string; now: string; nowPct: number; caption: string },
  bandTopPct: 62,
  breakSolidPct: 58,
  breakFadePct: 66,
  roleOnSurface: "",
  roleOutline: "",
  archetype: "",
  heroStat: "",
  // A valid sample pack so the studio preview demonstrates the style-pack
  // overlay; production passes the still's real pack id (or "" for bare).
  stylePack: "vignette-grain-corner_ticks-standard",
  overlapAccent: "",
  roleMedalRamp: "",
  roleMedalNumeralRamp: "",
  motionIntent: "",
  textGranularity: "word" as "word" | "glyph",
  roleGround: "",
  roleSurface: "",
  roleAccent: "",
  roleOnGround: "",
  captionsJson: "",
  inReel: false,
  meshBg: "",
  // D8 register weight vars mirrored from the still's --mh-wght-* (0 = leave the
  // static cut untouched, matching the schema defaults in StoryCard.tsx).
  wghtKicker: 0,
  wghtMeta: 0,
  wghtData: 0,
  frameShape: "",
  frameRadius: "",
  frameTornFreq: 0,
  frameTornScale: 0,
  frameTornSeed: 0,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="StoryCard"
        component={StoryCard}
        durationInFrames={STORY_DURATION_FRAMES}
        fps={FPS}
        width={STORY_W}
        height={STORY_H}
        schema={storyCardSchema}
        defaultProps={{ card: defaultCard, brand: defaultBrand }}
      />
      <Composition
        id="MeetReel"
        component={MeetReel}
        durationInFrames={REEL_DURATION_FRAMES}
        fps={FPS}
        width={STORY_W}
        height={STORY_H}
        schema={meetReelSchema}
        defaultProps={{
          cards: [defaultCard, defaultCard, defaultCard],
          brand: defaultBrand,
          meetName: "MediaHub Open",
          // R1.30 outro-CTA inputs. Blank by default → the Studio preview
          // shows the universal "follow the club" close; production passes a
          // real sponsor / next-meet label when the club has one.
          sponsor: "",
          nextMeet: "",
          // M18 brand-true cover/outro props. Blank by default → the legacy
          // accent-on-primary pairing; production resolves them Python-side.
          coverRoleGround: "",
          coverRoleSurface: "",
          coverRoleAccent: "",
          coverRoleOnGround: "",
          coverTypography: "",
          coverPhotoSrc: "",
          coverPhotoPos: "",
        }}
      />
    </>
  );
};
