#!/usr/bin/env node
/**
 * MediaHub Remotion segment renderer — parallel reel composition (roadmap R1.28).
 *
 * Renders several contiguous FRAME RANGES of ONE composition concurrently,
 * each to its own MP4, sharing a single bundle + composition select. The
 * Python side (visual/reel_parallel.py) then concatenates the segments with
 * FFmpeg to reconstruct the full clip.
 *
 * Why this is exact, not approximate: every Remotion composition here is
 * frame-pure — a frame's pixels are a deterministic function of its absolute
 * frame index (useCurrentFrame()), never of wall-clock or render order. With
 * `frameRange: [start, end]` Remotion renders those frames at their TRUE
 * timeline positions (it does not remap the clock), so segment N holds the
 * exact frames the serial render would emit for [start, end]. Concatenating
 * the segments in order is therefore byte-for-byte the serial reel — the
 * cross-beat transition overlaps and the continuous reel overlays are all
 * computed within whichever segment owns each frame. The split is a pure
 * wall-clock optimisation, invisible to the output and to the content cache.
 *
 * Usage:
 *   node render_segments.js --composition <id> --props <props.json> \
 *        --manifest <manifest.json> [--duration <seconds>] \
 *        [--width <px>] [--height <px>] [--concurrency <n>]
 *
 * manifest.json shape:
 *   { "segments": [ { "start": 0, "end": 59, "output": "/abs/seg0.mp4" }, ... ] }
 *   `start`/`end` are inclusive absolute frame indices; `output` is where that
 *   segment's MP4 is written.
 *
 * Render settings (codec, pixel format, chromium options, timeout) mirror
 * render.js exactly so a segment is encoder-compatible with the serial reel
 * and the segments concat cleanly with `-c copy`.
 *
 * Exits 0 on success (every segment written), non-zero on any error with the
 * message on stderr — the Python wrapper treats a non-zero exit as "fall back
 * to the serial render", never as a partial/placeholder reel.
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
  const manifestPath = args.manifest;
  const durationSec = args.duration ? parseFloat(args.duration) : null;
  const widthPx = args.width ? parseInt(args.width, 10) : null;
  const heightPx = args.height ? parseInt(args.height, 10) : null;
  // Tabs per segment render. The wall-clock win comes from running the
  // segments concurrently, so each one stays narrow (default 1 tab) to avoid
  // oversubscribing the CPU when N segments run at once.
  const concurrency = args.concurrency ? Math.max(1, parseInt(args.concurrency, 10)) : 1;

  if (!compositionId || !propsPath || !manifestPath) {
    console.error(
      "Usage: node render_segments.js --composition <id> --props <props.json> --manifest <manifest.json> [--duration <seconds>]",
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

  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (e) {
    console.error(`Failed to read manifest file ${manifestPath}: ${e.message}`);
    process.exit(2);
  }
  const segments = Array.isArray(manifest.segments) ? manifest.segments : [];
  if (segments.length === 0) {
    console.error("manifest has no segments to render");
    process.exit(2);
  }

  // Lazy require so a missing Remotion install fails cleanly (and surfaces
  // via the Python wrapper as a fall-back-to-serial rather than a crash).
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

  const start = Date.now();
  console.error(`[remotion] bundling once for ${segments.length} segments: ${entry}`);
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

  // Validate + clamp the requested frame ranges against the authoritative
  // duration computed from the composition's own fps. Python plans the split
  // at the same 30fps, so this is a belt-and-braces clamp, not a remap.
  const plan = [];
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i] || {};
    const segStart = Math.max(0, parseInt(seg.start, 10));
    let segEnd = parseInt(seg.end, 10);
    if (!Number.isFinite(segStart) || !Number.isFinite(segEnd) || !seg.output) {
      console.error(`segment ${i} is malformed: ${JSON.stringify(seg)}`);
      process.exit(2);
    }
    segEnd = Math.min(segEnd, durationInFrames - 1);
    if (segEnd < segStart) {
      console.error(
        `segment ${i} range [${segStart}, ${segEnd}] is empty after clamping to ${durationInFrames} frames`,
      );
      process.exit(2);
    }
    plan.push({ index: i, start: segStart, end: segEnd, output: seg.output });
  }

  console.error(
    `[remotion] rendering ${plan.length} segments of ${compositionId} ` +
      `(${width}x${height} @ ${composition.fps}fps, ${durationInFrames} frames, ${concurrency} tab(s)/segment)`,
  );

  const renderSegment = async (seg) => {
    fs.mkdirSync(path.dirname(seg.output), { recursive: true });
    await renderMedia({
      composition: { ...composition, durationInFrames, width, height },
      serveUrl,
      codec: "h264",
      outputLocation: seg.output,
      inputProps,
      frameRange: [seg.start, seg.end],
      concurrency,
      chromiumOptions: { disableWebSecurity: true },
      // Mirror render.js: the per-render delayRender budget; Python's outer
      // subprocess timeout is the hard ceiling.
      timeoutInMilliseconds: 120000,
      pixelFormat: "yuv420p",
    });
    if (!fs.existsSync(seg.output) || fs.statSync(seg.output).size < 256) {
      throw new Error(`segment ${seg.index} produced no output at ${seg.output}`);
    }
  };

  // All segments run concurrently; Promise.all rejects on the first failure
  // so a partial split never reports success.
  await Promise.all(plan.map(renderSegment));

  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.error(`[remotion] done → ${plan.length} segments (${elapsed}s)`);
}

main().catch((err) => {
  console.error(`[remotion] segments failed: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
