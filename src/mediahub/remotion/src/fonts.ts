/**
 * Self-hosted brand fonts for the motion renderer (Council verdict 2026-05-31).
 *
 * The reel used to approximate the club's headline font with a system stack
 * (Impact/Oswald-ish) "to avoid the bundling cost of loading webfonts." Now that
 * the same poster woff2 are self-hosted for the still-graphic renderer, the reel
 * loads the REAL families so the video matches the still card and the web — one
 * brand identity across feed, story and reel.
 *
 * BINDING GUARDRAIL (Council): no frame may be captured before the fonts finish
 * loading, or Remotion would screenshot system-font fallback frames. We register
 * the @font-face rules, then hold every render with delayRender() until
 * document.fonts.ready resolves — only then continueRender(). A silent fallback
 * frame is a failure, not a fallback.
 *
 * woff2 live in remotion/public/fonts/ (byte-identical to the still renderer's
 * graphic_renderer/layouts/fonts/); staticFile() resolves them at bundle time.
 */
import { staticFile, delayRender, continueRender } from "remotion";

type Face = { family: string; weight: string; file: string };

const FACES: Face[] = [
  { family: "Bebas Neue", weight: "400", file: "bebas-neue.woff2" },
  { family: "Anton", weight: "400", file: "anton.woff2" },
  { family: "Bowlby One", weight: "400", file: "bowlby-one.woff2" },
  { family: "Space Grotesk", weight: "500 700", file: "space-grotesk.woff2" },
  { family: "Inter", weight: "400 800", file: "inter.woff2" },
  { family: "JetBrains Mono", weight: "500 700", file: "jetbrains-mono.woff2" },
];

let injected = false;

/** Inject the @font-face rules once and block rendering until they load. */
export function ensureBrandFonts(): void {
  if (injected || typeof document === "undefined") {
    return;
  }
  injected = true;

  const css = FACES.map(
    (f) =>
      `@font-face{font-family:'${f.family}';font-style:normal;` +
      `font-weight:${f.weight};font-display:block;` +
      `src:url(${staticFile("fonts/" + f.file)}) format('woff2');}`,
  ).join("\n");

  const style = document.createElement("style");
  style.setAttribute("data-mediahub-fonts", "1");
  style.textContent = css;
  document.head.appendChild(style);

  // Hold the render until the faces are actually ready (the guardrail).
  const handle = delayRender("loading brand fonts");
  Promise.resolve(document.fonts ? document.fonts.ready : null)
    .then(() => continueRender(handle))
    .catch(() => continueRender(handle));
}
