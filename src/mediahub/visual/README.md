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
  be. (It renders the story size only; square and landscape cuts need the
  Remotion engine and say so honestly.)

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
default, streams from a Microsoft endpoint) or `piper` — the reserved **local**
slot, so no cloud service is ever *required* by this interface. Piper's actual
implementation arrives with roadmap P5.2; until then choosing it returns an
honest error.

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

Not done yet (on purpose): burning the `.srt` subtitles into the video frames.
The subtitle file is produced now; the burn-in rides the same mux seam later.
