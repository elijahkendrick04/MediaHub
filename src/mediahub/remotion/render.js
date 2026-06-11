#!/usr/bin/env node
/**
 * MediaHub Remotion CLI entrypoint.
 *
 * Usage:
 *   node render.js --composition <id> --props <path-to-props.json> --output <path-to-output.mp4> [--duration <seconds>] [--width <px>] [--height <px>]
 *
 * Compositions:
 *   StoryCard  — 1080x1920 @ 30fps, default 6s.
 *   MeetReel   — 1080x1920 @ 30fps, default 15s.
 *
 * --width/--height override the composition's declared canvas so the same
 * composition renders the story (1080x1920), square (1080x1080) and
 * landscape (1920x1080) cuts; the TSX lays out responsively from
 * useVideoConfig().
 *
 * Exits 0 on success, non-zero on any error with the error message on stderr.
 *
 * This script is called from Python via subprocess; the Python side owns
 * caching, input shaping, and serving the output MP4.
 */

const path = require("path");
const fs = require("fs");

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
    }
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  const compositionId = args.composition;
  const propsPath = args.props;
  const outputPath = args.output;
  const durationSec = args.duration ? parseFloat(args.duration) : null;
  const widthPx = args.width ? parseInt(args.width, 10) : null;
  const heightPx = args.height ? parseInt(args.height, 10) : null;

  if (!compositionId || !propsPath || !outputPath) {
    console.error(
      "Usage: node render.js --composition <id> --props <props.json> --output <out.mp4> [--duration <seconds>]",
    );
    process.exit(2);
  }

  let inputProps;
  try {
    inputProps = JSON.parse(fs.readFileSync(propsPath, "utf8"));
  } catch (e) {
    console.error(`Failed to read props file ${propsPath}: ${e.message}`);
    process.exit(2);
  }

  // Lazy require so a missing Remotion install fails cleanly (and surfaces
  // via the Python wrapper as a 503 rather than crashing the web process).
  let bundle, getCompositions, renderMedia;
  try {
    ({ bundle } = require("@remotion/bundler"));
    ({ selectComposition: getCompositions, renderMedia } = require(
      "@remotion/renderer",
    ));
  } catch (e) {
    console.error(`Remotion not installed: ${e.message}`);
    process.exit(3);
  }

  const entry = path.resolve(__dirname, "src/index.ts");
  if (!fs.existsSync(entry)) {
    console.error(`Entry not found: ${entry}`);
    process.exit(2);
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  const start = Date.now();
  console.error(`[remotion] bundling: ${entry}`);
  const serveUrl = await bundle({ entryPoint: entry });

  const composition = await getCompositions({
    serveUrl,
    id: compositionId,
    inputProps,
  });

  if (!composition) {
    console.error(`Composition not found: ${compositionId}`);
    process.exit(4);
  }

  let durationInFrames = composition.durationInFrames;
  if (durationSec) {
    durationInFrames = Math.max(1, Math.round(durationSec * composition.fps));
  }
  const width = widthPx && widthPx > 0 ? widthPx : composition.width;
  const height = heightPx && heightPx > 0 ? heightPx : composition.height;

  console.error(
    `[remotion] rendering ${compositionId} (${width}x${height} @ ${composition.fps}fps × ${durationInFrames} frames)`,
  );
  await renderMedia({
    composition: {
      ...composition,
      durationInFrames,
      width,
      height,
    },
    serveUrl,
    codec: "h264",
    outputLocation: outputPath,
    inputProps,
    chromiumOptions: {
      disableWebSecurity: true,
    },
    // Match fonts.ts: the default 30s delayRender budget is too tight for
    // the MeetReel on a 1-CPU deployment. Python's subprocess timeout is
    // 600s, so 120s here stays well inside the outer budget.
    timeoutInMilliseconds: 120000,
    pixelFormat: "yuv420p",
  });
  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.error(`[remotion] done → ${outputPath} (${elapsed}s)`);
}

main().catch((err) => {
  console.error(`[remotion] failed: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
