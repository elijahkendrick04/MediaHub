# AI Video Editing — Landscape, Feasibility & MediaHub Roadmap (2026)

This is the reference map behind the **video suite's AI editing layer** (the
footage path, `src/mediahub/video/`). It catalogues "all the AI video editing
functionality the world has to offer" as of mid-2026, classifies each capability
against MediaHub's deterministic-engine doctrine, and tracks what is **built**,
**planned**, or **deliberately gated**.

It exists so the work can proceed over many focused builds without re-deriving
the landscape each time. It is engineering reference, not a customer document.

## The one distinction that organises everything

Every capability sorts into exactly one of three tiers. Naming the tier matters
more than naming the product, because the tier decides *how* MediaHub may ship it:

| Tier | What it is | MediaHub stance |
|---|---|---|
| **DET** — deterministic CV/DSP/maths | Fixed algorithm (FFmpeg filter, colour science, DSP). Same input → same output. Cannot fabricate. | **Ship freely.** This is the engine. Reproducible, cacheable, honest. |
| **AIJ** — AI judgement | An LLM/vision/audio model decides something non-deterministic *over real facts* (which clip, which order, what hook). Doesn't invent pixels/words of record. | **Route through `media_ai`/`ai_core`, honest-error, deterministic default.** Never fabricates a fact. |
| **GEN** — generative synthesis | A model manufactures new pixels/audio/people (text-to-video, avatars, voice clone, inpainting, ML super-res). Can hallucinate. | **Gated provider slot, off by default, opt-in + disclosed** (like `avatars.py`, `matting.py`). Human approval always. |

A recurring industry finding (confirmed across the 2026 survey): the headline
"AI editor" is *overwhelmingly* deterministic DSP/keyframe work wrapped in
marketing, with genuine ML confined to a few narrow judgement calls and a
clearly-bounded generative tier. **This validates MediaHub's engine boundary** —
the market leaders also keep beat-sync, transitions, ducking, stabilisation,
multicam sync, kinetic type and data-driven sports graphics in deterministic
maths/FFmpeg.

## Capability catalogue

Status legend: ✅ built · 🟦 planned (DET/AIJ, fits the engine) · 🔒 gated
provider slot (GEN, opt-in+disclosed) · ⏸ deferred.

### Tier 1 — Deterministic (the engine; ship freely)

| Capability | Technique / FFmpeg filter | Status |
|---|---|---|
| Shot/scene detection | `select='gt(scene,…)'`, `scdet` | ✅ `moments.py` |
| Highlight detection + ranking | audio-energy (`astats`) + scene cuts, fixed-weight rank | ✅ `moments.py` |
| Auto-reframe / smart-crop | saliency centroid (gradient energy / cutout alpha) | ✅ `reframe.py` |
| Transitions | `xfade` (fade/dissolve/wipe/slide/…) + `concat` cuts | ✅ `edl.py` |
| Speed / slow-mo | `setpts` + `atempo` chain | ✅ `edl.py` |
| **Colour grade / looks / WB / exposure** | `eq` + `colorbalance`; named looks | ✅ `edl.py` (`ColorAdjust`, `LOOKS`) |
| **Video denoise / sharpen** | `hqdn3d`, `unsharp` | ✅ `edl.py` grade |
| **Silence / dead-air removal (jump cuts)** | `silencedetect` → keep-segment plan | ✅ `silence.py` |
| **Stabilisation** | two-pass `vidstabdetect`+`vidstabtransform` | ✅ `enhance.py` |
| **Audio cleanup (denoise + loudness)** | `afftdn` / `arnndn`, `loudnorm` (EBU R128) | ✅ `audio/clean.py` → wired in `audio_post.py` |
| **Music bed + automatic ducking** | library pick + `sidechaincompress` | ✅ `audio_post.py` (+ `audio/`) |
| **Deterministic upscale** | `scale=…:flags=lanczos` | ✅ `enhance.py` |
| Captions / subtitles (timing + render) | ASR → ASS burn (`subtitle_burn`) | ✅ `captions.py` |
| **Karaoke / word-highlight captions** | ASS `\kf` sweep over word stamps | ✅ `caption_render.py` + `captions.windowed_karaoke_track` |
| **Beat-synced cutting** | `audio_mux.track_bpm` → snap clip lengths to the beat grid | ✅ `reel_builder.snap_to_beats` |
| **Frame-interpolated slow-mo** | `minterpolate=mi_mode=mci` via a per-clip `smooth` flag | ✅ `edl.Clip.smooth` + `clip_maker(slow_mo=…)` |
| **Caption editing (text/timing)** | deterministic cue transforms over the burned track | ✅ `captions.py` + `POST …/caption` route |
| Filler-word removal | ASR transcript + lexicon match at stamps | 🟦 (needs ASR) |
| Multicam sync | audio cross-correlation (GCC-PHAT) | ⏸ (not a club-footage need yet) |

### Tier 2 — AI judgement (route through `media_ai`, honest default)

| Capability | What the AI decides | Status |
|---|---|---|
| **Reel auto-director** | order of moments, look, music mood, hook — over detected facts only | ✅ `director.py` |
| Moment naming | a 2–4 word label on a detected moment | ✅ `moments.label_moment` |
| **Hook / title generation** | a short, factual on-screen hook | ✅ `director.suggest_hook` |
| Music mood→track | mood is AI; the *pick* is the deterministic library floor | ✅ `director` + `audio/library` |
| **Clip/virality ranking across clips** | per-beat emphasis weight (over real signal) → screen time | ✅ `director.ClipBeat.weight` |
| **Per-beat durations / multi-beat captions** | the "money shot" earns more seconds; caption N beats, not just the lead | ✅ `reel_builder` (weight + `caption_beats`) |
| B-roll **stock** matching (semantic) | which library clip fits a line | ⏸ (no stock library yet) |
| Caption styling/emphasis pick | which words to emphasise | ⏸ |

### Tier 3 — Generative synthesis (gated, opt-in + disclosed, human-approved)

| Capability | Representative providers | Status |
|---|---|---|
| Talking avatars / presenters | HeyGen, Synthesia, D-ID, Hedra | 🔒 `avatars.py` (off by default, disclosure forced) |
| Background removal / matting | rembg/BiRefNet (server), Replicate, PhotoRoom | 🔒 `matting.py` (provider slot) |
| Text-to-video / image-to-video b-roll | Veo 3.1, Sora 2, Kling 3.0, Runway, Pika, Luma | 🔒 `broll.py` (off by default, opt-in + disclosure forced) |
| Lip-sync / dubbing / translation | sync.so, ElevenLabs, Rask, HeyGen Translate | 🔒 `dub.py` (off by default, opt-in + disclosure forced) |
| Object removal / inpainting | Runway Aleph, ProPainter, DiffuEraser, Resolve | 🔒 `object_removal.py` (opt-in + disclosure forced) |
| Eye-contact correction (pixel warp) | NVIDIA Broadcast, Descript | 🔒 `eye_contact.py` (opt-in; a pixel edit — `synthetic=False`) |
| Relighting | IC-Light, SwitchLight/Beeble | ⏸ |
| ML super-resolution ("invent detail") | Real-ESRGAN, Topaz, Resolve Super Scale | 🔒 (distinct from the DET lanczos resize) |
| "Enhance speech" (re-synthesis) | Adobe Podcast, Descript Studio Sound | ⏸ (can hallucinate phonemes — gated) |
| Music **generation** | Soundraw, Beatoven, CapCut | 🔒 `audio/generate.py` slot |

> **Why the GEN line is firm:** the 2026 survey confirms every super-resolution
> upscaler *invents* detail, "enhance speech" can hallucinate phonemes, and
> avatars/lip-sync/inpainting synthesise pixels/audio of record. These belong
> behind a disclosed, opt-in slot with human approval — never shipped as if they
> were faithful, deterministic "cleanup".

## What this build added (the AI editing layer)

The footage path already had ingest → probe → moments → reframe → captions →
EDL → render → projects (one clip → one cut). This build added the **deterministic
enhancement layer** and the **AI reel director** on top:

- **Colour grade + named looks** on the EDL (`ColorAdjust`, `LOOKS`), compiled
  inline (pure colour science); un-graded clips render byte-identically.
- **Audio plan** on the EDL (`AudioPlan`) applied by a soundtrack post-pass
  (`audio_post.py`): voice denoise + loudness + a ducked music bed, video copied.
- **Silence/jump-cut planning** (`silence.py`) — tighten talking clips.
- **Animated (karaoke) captions** (`caption_render.py` + `captions.windowed_karaoke_track`)
  — the word-by-word `\kf` highlight sweep, the signature reel caption look. Added
  in the video package only, so the shared reel engine's caption output stays
  byte-identical (a static track dispatches to the unchanged `subtitle_burn`).
- **Stabilisation + deterministic upscale** (`enhance.py`).
- **AI reel director** (`director.py`) + **multi-clip reel builder**
  (`reel_builder.py`) — the "import several clips → AI edits → one branded reel".
- Wired through `clip_maker` (single clip) and new routes `POST /api/video/reel`
  and `POST /api/video/projects/<id>/enhance`, with editor UI (look picker,
  audio/music/silence toggles, "Direct the reel" multi-select, per-project
  Apply-look / +Music / Stabilise).

Everything obeys the standing rules: facts deterministic, the one judgement (the
director) AI with an honest default, rendering server-side and cached, and a
human approves before export.

## Roadmap — the remaining builds (high value, fits the engine first)

Done across the builds: animated captions, **beat-synced cutting**,
**frame-interpolated slow-mo**, filler-word removal, the **caption-edit route**,
the **visual timeline editor** (manual trim/reorder/speed/smooth/mute/look/
transition + **per-clip colour-grade sliders** + **drag-to-reorder** + a per-clip
**audio-waveform scrubber** (click/drag the strip to trim) + inline caption-text
editing, saving the EDL), **director depth** (per-beat emphasis weights → screen
time, the cross-clip virality judgement, and multi-beat captions offset onto the
assembled timeline), and **all the gated generative seams** — b-roll (`broll.py`),
lip-sync/dubbing (`dub.py`), object-removal/inpainting (`object_removal.py`), and
eye-contact (`eye_contact.py`). Still open:

1. **Wiring the generative seams' networks** — the provider adapters are scaffolded
   and honest-error today; building each network integration is gated on the
   provider moving into `legal.SUBPROCESSORS` (and the club DPA) first. (GEN)
2. **Thumbnail scrubber** — frame thumbnails alongside the audio waveform (the
   waveform — `video/waveform.py`, FFmpeg PCM → normalised peak buckets — already
   ships; thumbnails would need server-side frame extraction). (DET)

Sources for the landscape survey are the 2026 competitor research under
`docs/research/` and the per-cluster web survey captured during this build
(generative models; avatars/lip-sync/dubbing; b-roll/stock; object-removal/
matting/relighting; captions/audio/colour/stabilisation; auto-edit/music/
motion-graphics/multicam/packaging).
