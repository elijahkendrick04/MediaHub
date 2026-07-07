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
  backgroundStyle: "",
  composition: "",
  typographyPair: "",
  accentStyle: "",
  mood: "",
  photoTreatment: "",
  photoSrc: "",
  photoPos: "",
  photoSrcs: [] as string[],
  cutoutSrc: "",
  archetype: "",
  heroStat: "",
  // A valid sample pack so the studio preview demonstrates the style-pack
  // overlay; production passes the still's real pack id (or "" for bare).
  stylePack: "vignette-grain-corner_ticks-standard",
  motionIntent: "",
  roleGround: "",
  roleSurface: "",
  roleAccent: "",
  roleOnGround: "",
  captionsJson: "",
  inReel: false,
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
