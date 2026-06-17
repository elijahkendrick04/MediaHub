# visual

The bridge to the video-maker. It lets the Python code make MP4 story cards and
reels. There are two ways it can do that, picked by `MEDIAHUB_REEL_ENGINE`:

- **remotion** (the default) — calls the `remotion` folder (JavaScript) for the
  full animated compositions. Remotion is *not* free for companies above three
  people (it needs a paid Company License), which is why the next engine exists.
- **ffmpeg** (`reel_ffmpeg.py`, free) — takes the card's **own still graphic**
  (the same picture the "Create graphic" button makes), gives it real camera
  motion, and joins the frames using FFmpeg. Each beat picks a Ken Burns move
  from the card's own number (zoom in or out, a pan in any of four
  directions, a corner zoom, a soft-focus 2.5D **parallax** depth beat, or an
  honest held frame for a "static" card), and each cut between beats
  **mirrors the Remotion reel's choice**: one bold, mood-chosen cut into the
  top moment (a blur for calm, a whip for fierce, an iris for a medal, a zoom
  otherwise) and one quiet, consistent cut everywhere else. Nothing about it
  costs money: no Node, no Remotion, no license. A reel is the meet-name cover
  plus one beat per top card, exactly the same length the Remotion reel would
  be. It renders all four sizes too — story (default), portrait, square and
  landscape — by drawing the still at the chosen shape and keeping the camera
  motion at that size.

`motion.py` makes the video match the approved still card exactly: it resolves
the same colour roles the still painted (medal tints included), reuses the
still's saliency maths so a photo's subject stays in frame, and forwards the
AI director's layout archetype and `motion_intent` to the composition. It can
render four sizes — story (default), portrait, square, landscape — and writes a
small `.json` manifest next to every cached Remotion MP4 saying *why* the video
looks the way it does (which archetype, which motion, where the colours came
from, what audio was mixed). Every finished MP4 also gets a `.poster.png`
sidecar — a single picked frame to use as the thumbnail.

`reel_engine.py` is the little switchboard that reads the env var and says which
engine is active (the health page shows its answer). Asking for an engine that
isn't recognised produces a clear, honest error — never a fake video.

`reel_parallel.py` is an **opt-in speed-up** for the Remotion reel (turn it on
with `MEDIAHUB_REEL_PARALLEL=1`). A reel is one long video, so making it
normally means rendering its frames one after another. This helper instead cuts
the reel's frames into a few equal chunks, renders the chunks **at the same
time** (the Node side, `remotion/render_segments.js`, builds the project once
and then renders every chunk together), and **glues them back** end-to-end with
FFmpeg. Because every frame of these videos always looks the *same* no matter
when it's drawn, gluing the chunks gives the **exact same reel** as the slow way
— it's just faster on a computer with several cores. The glued reel is even
stored under the same name in the cache, so a reel made the fast way and one
made the slow way are interchangeable. If anything is missing (Node, Remotion,
or FFmpeg) or any chunk fails, it quietly falls back to the normal one-pass
render — never a half-made or broken reel.

## voiceover.py + pronunciation.py

`voiceover.py` reads a card's **already-approved caption out loud** and saves it as
an MP3 (plus an `.srt` subtitle file for muted autoplay). It speaks the caption
**word for word** — there is no AI writing a script, because a spoken mistake about a
real swimmer is even harder to spot than a written one. `pronunciation.py` lets a club
fix how a name is said (a plain `{ "written": "spoken" }` list), so the voice never
mangles a swimmer's name.

It's **off by default**: an operator turns it on with `MEDIAHUB_VOICEOVER=1` and by
installing the speech backend. If it isn't available, the app says so honestly (a
clear error) instead of using a fake robot voice. Audio is only made for a card a
human has **approved**.

Which voice engine speaks is picked by `MEDIAHUB_TTS_PROVIDER`: `edge` (the
default, streams from a Microsoft endpoint) or `piper` — the **zero-cost,
fully-offline local** backend, so no cloud service is ever *required* by this
interface. For Piper the operator points `MEDIAHUB_PIPER_MODEL` at a Piper
`.onnx` voice file (or sets `MEDIAHUB_PIPER_VOICE` + `MEDIAHUB_PIPER_VOICE_DIR`);
MediaHub loads it with the `piper-tts` package, synthesises the audio on the
box, and transcodes it to the same MP3 the rest of the pipeline uses. If the
package or the model file is missing it returns an honest error — never a fake
robot voice. (Piper has no word-level timestamps, so its subtitle *timings* are
a deterministic estimate; the spoken words are still the verbatim caption.)

## narration.py + audio_mux.py — sound on the videos (off by default)

Videos used to be silent. Now, when the operator opts in, they can carry sound:

- `narration.py` writes the spoken script with **zero invention**: a fixed
  template over the *same verified facts the video already shows* (name, event,
  time, label, the honest cover stats). Times get a deterministic spoken form
  ("1:02.45" → "1 minute 2.45 seconds"). There is no AI here. If the script
  would run longer than the video, whole lines are dropped from the bottom of
  the ranking — never sped up, never summarised. The same facts can be spoken
  in five **script-style registers** (`MEDIAHUB_NARRATION_STYLE`): `standard`
  (the default), `compact`, `verbose`, `poetic`, `technical`. A register only
  changes the *phrasing* — never which facts are spoken or their values — so
  every register is equally honest and result-agnostic (a "DQ" or a place is
  never re-spoken as a time). Because the assembled script text is folded into
  the audio cache key, switching registers can never serve a stale mix.
- `audio_mux.py` attaches the sound to the finished MP4 with FFmpeg: the
  narration (spoken by the same `voiceover.py` engine, `MEDIAHUB_VOICEOVER=1`),
  and/or a music bed from `MEDIAHUB_REEL_MUSIC_DIR` — a folder of music files
  the **operator** has licensed (MediaHub ships no music and claims no rights).
  The track is picked deterministically, ducked under the voice, trimmed and
  faded to the video's exact length. The video pixels are never re-encoded.
  If anything fails, the video ships **silent** and the manifest says why —
  never a fake voice or placeholder track. It also pulls the `.poster.png`
  thumbnail frame out of every finished video. Works for both engines
  (Remotion and the free FFmpeg one).

## subtitle_burn.py — captions burned onto the video (off by default)

Most feed video autoplays **muted**, so the words a card/reel narrates have to be
*on the screen* too. `subtitle_burn.py` reads the `.srt` that `voiceover.py`
already makes, picks a caption colour that is **provably legible** on the card's
own brand colour (the same APCA contrast maths the still renderer uses, in
`theming/contrast.py`), and turns it into a frame-timed caption track. The
Remotion video paints that track with `remotion/.../sprint/layers/captions.tsx`;
the free FFmpeg engine burns the same track onto the story frame as an ASS
subtitle. The words are the **verbatim** narration (no AI, no invention) and the
phonetic name fixes never leak on screen. If anything fails, the video simply
renders **without** captions — a missing overlay never breaks or fakes a render.

It's **off by default**: an operator turns it on with `MEDIAHUB_SUBTITLES=1` on
top of `MEDIAHUB_VOICEOVER=1` (captions ride on the narration). With it off,
nothing changes — the renders are byte-identical. (The still+FFmpeg fallback
burns captions on the **story** cut only; reel captions there are a known gap —
the Remotion engine captions reels too.)

## motion_regression.py — the frame-by-frame "did the video still look right?" check

The MP4 path proves two different cards make two *different* videos, but it
can't tell you a code change quietly *broke* a scene (wrong colour, a layer
that stopped painting, a transition that collapsed). `motion_regression.py` is
that safety net — the motion twin of `autotest/visual_regression.py`, which does
the same for the still web surfaces.

How it works: it renders a small, fixed set of **reference frames** from the
real StoryCard / MeetReel compositions (via `remotion/render_frame.js`, which
asks Remotion for single still frames as PNGs) and **pixel-diffs** each one
against a committed "this is what it should look like" picture under
`tests/baseline/motion_frames/`. A frame that drifts more than a small tolerance
(to ignore sub-pixel fuzz) is a regression; a frame with no baseline yet is an
honest *skip*, never a made-up failure. The baselines are only ever written on
purpose by a person — the check never rewrites its own answer key.

Run it by hand with `python scripts/motion_vr.py` (`list` / `capture` /
`check`). The logic is covered everywhere by `tests/test_motion_regression.py`;
the heavier real-render diffs are opt-in via `MEDIAHUB_MOTION_VR=1` so the
everyday test run stays fast. In CI the diff runs as its own workflow
(`.github/workflows/motion-visual-regression.yml`) whenever motion code changes.
