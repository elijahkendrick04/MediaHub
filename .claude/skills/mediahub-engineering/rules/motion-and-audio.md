# Motion video (Remotion) and audio

MediaHub renders branded MP4s with Remotion 4.x, **self-hosted on the server**
(`src/mediahub/remotion/`), invoked from `visual/motion.py` (which shells out to
`render.js`). Story cards are 1080×1920 / 6s; meet reels stitch the top-N cards
into ~15s. Output is cached at `DATA_DIR/motion_cache/<hash>.mp4`.

## Rules that come from how video rendering actually works

- **Animation is a pure function of the frame number.** Use Remotion's
  frame-driven interpolation/easing. **CSS transitions/animations and Tailwind
  animation classes do NOT render** — never use them for motion.
- **Compositions are data-driven via typed props.** Drive everything from the
  card payload + `CreativeBrief`, and honour the per-card `variation_seed`
  (`visual/motion.py::auto_variation_seed_for`) so a card's motion render aligns
  with its still graphic. Keep data separate from rendering.
- **Duration is computed from content** (e.g. reel length from card count), not
  hardcoded per call.
- **Cache-key gotcha:** the cache hash includes the card dict + brand +
  duration. If you change the prop / brief shape, **bump the cache key** or
  stale renders serve silently.
- **Smoke-check cheaply:** render a single frame to sanity-check layout / colour
  / timing before committing to a full 30–90s render. The cold render path is
  under-tested (see `docs/TECHNICAL_DEBT.md`) — a one-frame check catches most
  regressions.
- The render reads the **same brand palette JSON** as the web UI and static
  graphic (single source of truth — see `rules/graphics-and-brand.md`).

## Audio (videos are silent today)

The current MP4s have no audio track. If adding voiceover or music:

- **Voiceover:** use a **free, commercially-licensed, self-hostable** TTS that
  runs on the CPU box (e.g. a small Apache-licensed ONNX voice model — the same
  way `rembg` / `onnxruntime` already run server-side), or Google's TTS via the
  existing Gemini key. Keep narration short (clips are 6–15s) so CPU latency
  stays low.
- **Music:** prefer royalty-free libraries with clean commercial licences over
  generating music; verify the licence permits commercial use and
  redistribution.
- **Wiring:** add the audio via Remotion's audio component + an FFmpeg mux in
  `render.js` (currently absent), behind a feature flag.
- **Honest fallback:** if synthesis fails, render **silent** video — never a
  fabricated/placeholder audio track. Most feed video is watched muted, so
  on-screen text / captions must carry the message regardless.
