import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";
import { ensureBrandFonts } from "./fonts";

// Self-host the brand fonts into the motion renderer (Council 2026-05-31) and
// hold rendering until they load, so reels match the still card / web UI.
ensureBrandFonts();

registerRoot(RemotionRoot);
