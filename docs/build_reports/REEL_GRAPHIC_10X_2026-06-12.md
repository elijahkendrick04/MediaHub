# Graphic/Reel Builder — 10× Effectiveness & Comprehensiveness Assessment

**Date:** 2026-06-12 · **Scope:** `graphic_renderer/`, `creative_brief/`,
`visual/`, `remotion/`, the motion/reel routes · **Status:** assessment +
first build wave shipped (see §4).

## 1. Where the builder stands

The **still** side already had its overhaul (P1.4 / Appendix A spine,
2026-06-10): 12 v2 archetypes, the Tier-B design-spec director with
pool→rank→APCA-compliance, deterministic autofit + saliency, single-source
colour roles, 5 output sizes. The **motion/reel** side caught up on *parity*
(archetype scenes, motion intents, role parity, 3 formats, data-driven reel
length, rank-weighted beats) — but it is still the thinner surface, and it is
where the next order-of-magnitude lives.

## 2. The assessment — every credible 10× axis

| # | Axis | What's missing today | Verdict |
|---|------|----------------------|---------|
| A | **Sound** | Every MP4 is silent. The voiceover primitive (verbatim text → MP3+SRT, honest errors) exists but never reaches a video. Sound is the single highest-engagement lever on social video; competitors all ship it. | **Build now** (this wave) |
| B | **Motion vocabulary** | 8 intents, but not the most characteristic sports-graphic move: the **numeric count-up** (the time/score counts up and settles on the exact verified value). | **Build now** |
| C | **Format coverage** | Motion renders story/square/landscape but not the 4:5 **portrait** feed cut (1080×1350) — the Instagram/Facebook feed standard the stills already support. | **Build now** |
| D | **Posters/previews** | No poster frame beside any MP4 (platforms and the review UI need thumbnails); no cheap pre-render preview. Cold-render path is known debt. | **Build now** (posters); preview-frame endpoint deferred until a UI consumes it |
| E | **Reel narrative depth** | Cover stats are static chips; no aggregate "by the numbers" moment. | **Build now** (animated count-up chips on the cover — zero structural risk); a dedicated tally *beat* changes `reel_duration_for` across both engines — deferred, designed below |
| F | **Music** | No music bed. Licence-clean *pools* + rights ledger are P6.6's full scope. | **Build the seam now**: operator-supplied licensed directory (`MEDIAHUB_REEL_MUSIC_DIR`), deterministic track pick, ducked under narration. Licensing stays with the operator; off by default |
| G | **Burned-in captions** | SRT exists; not burned into MP4s. | Defer — on-screen card text already carries the message muted; burn-in rides the new mux seam later |
| H | **More still archetypes** (relay quad, season-progression chart, head-to-head) | 12 archetypes shipped; chart/relay archetypes need per-card data series not yet proven present on every card. | Defer — needs a data-availability spike first (P6.9 charts) |
| I | **Motion-token presets / shared-element transitions** (P6.10) | Transitions are 3 fixed kinds. | Partially now (count-up + richer cover); full tokenised vocabulary is its own package |
| J | **EDL footage path, ASR captions, clip-maker** (P6.5) | No real-footage path. | Defer — separate phase, new deps |
| K | **Satori fast-path** (P5.4) | Chromium-weight rendering. | Defer — performance, not capability |

**Why A+B+C+D+E+F is the right first wave:** they compound on each other
(narrated reel + count-up + portrait + poster ships as one coherent "video
that competes on social" upgrade), none of them touches the deterministic
engine, none adds a paid dependency, and all are testable in CI without a
network.

## 3. Hard rules this build honours

- **Zero invention in audio.** The narration script is a fixed deterministic
  template over the *same verified card facts the video already displays*
  (name, event, time, label, honest cover stats). No LLM writes a word.
  Times are spoken via a deterministic spoken-form transform
  ("1:02.45" → "1 minute 2.45 seconds").
- **Honest silent fallback.** If TTS synthesis or the mux fails, the video
  ships **silent** and the manifest records why — never a fake/placeholder
  track. Off by default (`MEDIAHUB_VOICEOVER=1` opt-in, same gate as the
  caption voiceover; music only when the operator points
  `MEDIAHUB_REEL_MUSIC_DIR` at their own licensed files).
- **Cache-key discipline.** Audio-off render hashes are byte-identical to
  before (existing caches stay valid). Audio-on renders fold the audio plan
  into the content hash, so silent and narrated artefacts can never collide.
- **Pure-function-of-frame animation.** Count-up is frame-interpolated and
  settles on the exact verified value; no CSS animation.
- **Engine symmetry.** The audio layer applies to both the Remotion engine
  and the free FFmpeg engine (it is a post-render mux, engine-agnostic).

## 4. What this wave ships

1. `visual/narration.py` — deterministic fact-only narration scripts
   (story + reel), spoken-form time transform, no AI imports.
2. `visual/audio_mux.py` — FFmpeg audio assembly: voiceover + optional
   ducked music bed, trimmed/faded to video length; poster-frame extraction;
   deterministic music pick from the operator's directory.
3. `visual/motion.py` — audio plan wiring for both engines, `portrait`
   (1080×1350) motion format, poster PNG sidecars beside cached MP4s and
   run outputs, manifest `audio` + `poster` fields.
4. `visual/reel_ffmpeg.py` — accepts the audio plan (cache-key folded),
   muxes after assembly.
5. `remotion/` — `count_up` motion intent (formatting-preserving digit
   count-up on the result), animated count-up cover stat chips on the reel.
6. `creative_brief/design_spec.py` + `ai_director.py` — `count_up` joins
   the closed `MOTION_INTENTS` vocabulary and the director prompt.
7. `web.py` — reel file route serves the poster (`?poster=1`), additive.
8. Tests for all of the above; env inventory regenerated.

## 5. Deferred designs (next waves, in order of value)

- **Tally beat** ("BY THE NUMBERS"): extend `reel_duration_for(n, tally=…)`
  + a `TallyScreen` in `MeetReel.tsx` + a `weekend_numbers`-layout still in
  the FFmpeg engine, keeping both engines and the duration contract in
  lock-step. Cache keys already include duration, so no silent staleness.
- **Burned-in captions**: `subtitles=` filter on the existing mux seam,
  styled from brand tokens, APCA-checked.
- **Pre-render preview frame**: `--frame` mode (renderStill) in `render.js`
  once a UI surface consumes it.
- **Chart/relay archetypes**: spike on per-card progression-series
  availability (`pb_discovery` history), then 2–3 new v2 archetypes via the
  existing filesystem-scanned slot convention.
- **Licence-clean first-party music pool + rights ledger** (P6.6 proper),
  beat-synced cuts.
