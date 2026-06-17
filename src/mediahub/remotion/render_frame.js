#!/usr/bin/env node
/**
 * MediaHub Remotion still-frame renderer — the Node half of the frame-by-frame
 * motion visual-regression harness (roadmap R1.27).
 *
 * Where render.js produces a finished MP4, this script renders one or more
 * *individual frames* of the SAME compositions (StoryCard / MeetReel) to PNG
 * via Remotion's `renderStill`. Those PNGs are the reference frames the Python
 * harness (visual/motion_regression.py) pixel-diffs against committed baselines.
 *
 * Usage:
 *   node render_frame.js --composition <id> --props <props.json> \
 *        --output-dir <dir> --frames "0,45,170" \
 *        [--duration <seconds>] [--width <px>] [--height <px>] [--scale <n>]
 *
 * The composition is bundled ONCE, then each requested frame is rendered as
 * `<output-dir>/frame_<NNNNNN>.png`. A single JSON line describing the written
 * files is printed to STDOUT (everything else goes to stderr) so the Python
 * caller can parse the result deterministically:
 *
 *   {"composition":"StoryCard","fps":30,"durationInFrames":180,
 *    "width":1080,"height":1920,
 *    "frames":[{"frame":0,"path":"/.../frame_000000.png"}, ...]}
 *
 * Exits 0 on success, non-zero on any error with the message on stderr. Frame
 * indices are clamped into [0, durationInFrames-1] so a caller asking for a
 * frame past the (possibly shortened) clip never crashes the render.
 *
 * Determinism: the StoryCard/MeetReel compositions use no Math.random and no
 * wall clock, fonts are self-hosted and held by delayRender until
 * document.fonts.ready, and the same props + frame always paint the same
 * pixels — which is what makes pixel-diffing meaningful.
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

function parseFrames(spec, durationInFrames) {
  // "0,45,170" → [0, 45, 170], clamped into range, de-duplicated, sorted.
  const raw = String(spec || "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((s) => parseInt(s, 10))
    .filter((n) => Number.isFinite(n));
  const last = Math.max(0, durationInFrames - 1);
  const clamped = raw.map((n) => Math.min(Math.max(0, n), last));
  return Array.from(new Set(clamped)).sort((a, b) => a - b);
}

function padFrame(n) {
  return String(n).padStart(6, "0");
}

async function main() {
  const args = parseArgs(process.argv);
  const compositionId = args.composition;
  const propsPath = args.props;
  const outputDir = args["output-dir"];
  const framesSpec = args.frames;
  const durationSec = args.duration ? parseFloat(args.duration) : null;
  const widthPx = args.width ? parseInt(args.width, 10) : null;
  const heightPx = args.height ? parseInt(args.height, 10) : null;
  const scale = args.scale ? parseFloat(args.scale) : 1;

  if (!compositionId || !propsPath || !outputDir || !framesSpec) {
    console.error(
      "Usage: node render_frame.js --composition <id> --props <props.json> " +
        "--output-dir <dir> --frames \"0,45,170\" [--duration <seconds>] " +
        "[--width <px>] [--height <px>] [--scale <n>]",
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

  // Lazy require so a missing Remotion install fails cleanly (matches render.js).
  let bundle, selectComposition, renderStill;
  try {
    ({ bundle } = require("@remotion/bundler"));
    ({ selectComposition, renderStill } = require("@remotion/renderer"));
  } catch (e) {
    console.error(`Remotion not installed: ${e.message}`);
    process.exit(3);
  }

  const entry = path.resolve(__dirname, "src/index.ts");
  if (!fs.existsSync(entry)) {
    console.error(`Entry not found: ${entry}`);
    process.exit(2);
  }

  fs.mkdirSync(outputDir, { recursive: true });

  const start = Date.now();
  console.error(`[remotion-frame] bundling: ${entry}`);
  const serveUrl = await bundle({ entryPoint: entry });

  const composition = await selectComposition({
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

  const frames = parseFrames(framesSpec, durationInFrames);
  if (frames.length === 0) {
    console.error(`No valid frames parsed from --frames "${framesSpec}"`);
    process.exit(2);
  }

  const resolved = {
    ...composition,
    durationInFrames,
    width,
    height,
  };

  console.error(
    `[remotion-frame] rendering ${compositionId} ` +
      `(${width}x${height} @ ${composition.fps}fps) frames=[${frames.join(",")}]`,
  );

  const written = [];
  for (const frame of frames) {
    const output = path.join(outputDir, `frame_${padFrame(frame)}.png`);
    await renderStill({
      composition: resolved,
      serveUrl,
      output,
      frame,
      inputProps,
      imageFormat: "png",
      scale,
      chromiumOptions: {
        disableWebSecurity: true,
      },
    });
    if (!fs.existsSync(output) || fs.statSync(output).size < 64) {
      console.error(`Frame ${frame} reported success but ${output} is missing/empty`);
      process.exit(5);
    }
    written.push({ frame, path: output });
  }

  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.error(
    `[remotion-frame] done → ${written.length} frame(s) in ${outputDir} (${elapsed}s)`,
  );

  // The ONLY thing on stdout: a single JSON line for the Python caller.
  process.stdout.write(
    JSON.stringify({
      composition: compositionId,
      fps: composition.fps,
      durationInFrames,
      width,
      height,
      frames: written,
    }) + "\n",
  );
}

main().catch((err) => {
  console.error(`[remotion-frame] failed: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
