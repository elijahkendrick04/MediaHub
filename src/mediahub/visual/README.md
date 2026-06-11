# visual

The bridge to the video-maker. It lets the Python code make MP4 story cards and
reels. There are two ways it can do that, picked by `MEDIAHUB_REEL_ENGINE`:

- **remotion** (the default) — calls the `remotion` folder (JavaScript) for the
  full animated compositions. Remotion is *not* free for companies above three
  people (it needs a paid Company License), which is why the next engine exists.
- **ffmpeg** (`reel_ffmpeg.py`, free) — takes the card's **own still graphic**
  (the same picture the "Create graphic" button makes), gives it a slow,
  steady zoom, and joins the frames with smooth crossfades using FFmpeg.
  Nothing about it costs money: no Node, no Remotion, no license. A reel is
  the meet-name cover plus one beat per top card, exactly the same length the
  Remotion reel would be. (It renders the story size only; square and
  landscape cuts need the Remotion engine and say so honestly.)

`motion.py` makes the video match the approved still card exactly: it resolves
the same colour roles the still painted (medal tints included), reuses the
still's saliency maths so a photo's subject stays in frame, and forwards the
AI director's layout archetype and `motion_intent` to the composition. It can
render three sizes — story (default), square, landscape — and writes a small
`.json` manifest next to every cached Remotion MP4 saying *why* the video looks
the way it does (which archetype, which motion, where the colours came from).

`reel_engine.py` is the little switchboard that reads the env var and says which
engine is active (the health page shows its answer). Asking for an engine that
isn't ready produces a clear, honest error — never a fake video. The `satori`
name is reserved for a future faster engine (roadmap P5.4).

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

Not done yet (on purpose): burning the subtitles into the video and stitching a whole
narrated meet recap. The `.srt` is produced now; the rest waits until it can be tested
on the real server.
