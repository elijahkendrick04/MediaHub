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

// Poster-frame policy (R1.29). Kept in byte-parity with Python's
// audio_mux.poster_time_for / poster_path_for (src/mediahub/visual/audio_mux.py):
// the in-render poster capture below uses these so the thumbnail timestamp and
// sidecar path match exactly what the Python finishing pass expects. If you
// change one formula, change the other — tests/test_motion_poster_in_render.py
// asserts the two stay in sync.
function posterTimeFor(kind, durationSec) {
  const d = Math.max(0.1, Number(durationSec) || 0.1);
  if (kind === "reel") {
    // Reels: land on the brand cover.
    return Math.min(1.5, Math.max(0.0, d - 0.2));
  }
  // Stories: late enough that the layers have animated in.
  return Math.max(0.0, Math.min(d * 0.55, d - 0.2));
}

function posterPathFor(outputPath) {
  // Mirror pathlib's Path(video).with_suffix(".poster.png").
  const ext = path.extname(outputPath);
  const base = ext
    ? outputPath.slice(0, outputPath.length - ext.length)
    : outputPath;
  return base + ".poster.png";
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
  let bundle, getCompositions, renderMedia, renderStill;
  try {
    ({ bundle } = require("@remotion/bundler"));
    ({ selectComposition: getCompositions, renderMedia, renderStill } = require(
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
  const renderElapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.error(`[remotion] rendered → ${outputPath} (${renderElapsed}s)`);

  // R1.29 — progressive in-render poster capture. Snap the poster frame with a
  // Remotion renderStill, reusing the warm serveUrl (no re-bundle). renderStill
  // waits on the same delayRender hook the video did (the fonts hold in
  // src/index.ts), so the thumbnail is a frame-exact, real-font PNG straight
  // from Chromium — no H.264 round-trip and no keyframe-seek approximation. This
  // replaces the post-hoc ffmpeg/ffprobe frame grab the Python side used to run
  // on every render. A poster failure is non-fatal: the video already
  // succeeded, and visual/motion._finish_cached_video falls back to the ffmpeg
  // grab whenever this sidecar is absent or empty.
  const kind = compositionId === "MeetReel" ? "reel" : "story";
  const posterPath = posterPathFor(outputPath);
  const posterFrame = Math.min(
    Math.max(
      0,
      Math.round(posterTimeFor(kind, durationInFrames / composition.fps) * composition.fps),
    ),
    durationInFrames - 1,
  );
  try {
    await renderStill({
      composition: { ...composition, durationInFrames, width, height },
      serveUrl,
      output: posterPath,
      frame: posterFrame,
      inputProps,
      imageFormat: "png",
      chromiumOptions: { disableWebSecurity: true },
      timeoutInMilliseconds: 120000,
      overwrite: true,
    });
    console.error(`[remotion] poster → ${posterPath} (frame ${posterFrame})`);
  } catch (e) {
    console.error(
      `[remotion] poster capture failed (non-fatal): ${e && e.message ? e.message : e}`,
    );
  }

  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.error(`[remotion] done → ${outputPath} (${elapsed}s)`);
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`[remotion] failed: ${err && err.stack ? err.stack : err}`);
    process.exit(1);
  });
}

// Exported for cross-language parity testing — the poster-frame policy above is
// mirrored in Python's visual/audio_mux.py. Requiring this file does not start
// a render thanks to the require.main guard.
module.exports = { posterTimeFor, posterPathFor };
