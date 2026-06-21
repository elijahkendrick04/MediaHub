# video

This is the **footage path** — the part of MediaHub that works with real video a
club filmed on a phone, as opposed to the videos MediaHub *draws by itself* from
results data (those live in the `visual` folder). You give it a clip of a race or
a celebration; it gives you back a short, upright, captioned, on-brand highlight
that a person approves before it's downloaded.

It is roadmap item **1.6 — the video suite.**

## The idea, in one line

**Long phone clip → find the best moment → crop it to the right shape → put the
spoken words on screen → brand it → a human says yes → download.**

## The files, simplest first

- **`probe.py`** — *measures* a clip: how long is it, how big is the picture,
  does it have sound. It reads the numbers FFmpeg prints; it never guesses.
- **`edl.py`** — the **timeline**. An "EDL" (Edit Decision List) is just a list
  of which bits of which clips play, in what order, with what joins (a hard cut
  or a fade), any text on top, **what colour grade each clip wears (the `look`),
  and how the soundtrack is built**. This file also turns that list into the exact
  instructions FFmpeg needs. It's pure maths — the same timeline always makes the
  same instructions — so it's easy to test and safe to cache. The colour grade is
  fixed colour-science (brightness/contrast/saturation/warmth/denoise/sharpen +
  named "looks" like *vivid*, *warm*, *mono*), not an AI guess.
- **`moments.py`** — finds the **highlight**. It listens for the loud bit (the
  cheer) and watches for the camera cut (the finish), then ranks those moments.
  This is deliberately *not* AI — "which two seconds matter" has to be the same
  answer every time, like deciding which result outranks which. (It *can* ask the
  AI to put a short **name** on a moment, but that's just a label and never
  changes which moment was picked.)
- **`silence.py`** — finds the **dead air** (the quiet gaps) in a talking clip and
  works out which bits of speech to keep, so a rambly clip tightens into a punchy
  one. Pure maths over what FFmpeg measured — the same clip always cuts the same
  way (like Descript's "remove gaps", done deterministically).
- **`reframe.py`** — **crops** a wide video to an upright shape without chopping
  the swimmer out, by reusing the same "where's the subject" maths the still
  graphics use.
- **`enhance.py`** — the enhancement steps that need their own pass over the file:
  **stabilising** shaky footage (the standard two-pass vidstab) and a clean
  high-quality **resize**. Deterministic; honest if the tools aren't there. The
  per-clip colour grade lives in `edl.py` (it's just filter maths); this file is
  the heavier, file-rewriting work.
- **`captions.py`** — puts the **spoken words on screen**, using the speech-to-
  text tool (1.4). The words are exactly what was said — no AI writing — and you
  can fix the text or the timing afterwards.
- **`caption_render.py`** — draws the captions onto the video. As well as a plain
  caption, it can do the **animated "word-by-word" caption** (the highlight that
  sweeps across each word as it's said — the look every reel app has). It's still
  the exact spoken words, just timed; and it's kept here in the video folder so the
  data-driven reels' captions are left untouched.
- **`audio_post.py`** — builds the **soundtrack** over a finished cut: cleans the
  voice (denoise + even out the loudness), lays a **music bed that automatically
  ducks under the speech**, and lands the whole mix at a sensible level. It reuses
  the audio engine (`audio/`) and only ever re-encodes the *sound* — the picture
  is copied untouched. Plain DSP, same in → same out.
- **`render.py`** — actually **makes the MP4** from a timeline, on the server,
  and remembers it so the same timeline is never rendered twice. If FFmpeg isn't
  there, it says so honestly instead of making a broken file. (It runs the
  soundtrack pass at the end when the timeline asks for one.)
- **`clip_maker.py`** — turns **one** raw clip into one finished highlight, now
  with the look, the audio cleanup/music, and the optional silence-tighten baked in.
- **`director.py`** — the **one judgement call**: given the moments already found
  across several clips, it asks the AI which *order* tells the best story, which
  *look* fits, what *music mood* suits it, and a short on-screen *hook*. It never
  invents a fact — it only arranges the ones detection found — and if there's no
  AI configured it falls back to a sensible default (strongest moments first).
- **`reel_builder.py`** — the **star of the show**: hand it several clips and it
  runs everything above to produce one branded **reel** — the director orders the
  highlights, each is cropped and graded, the lead gets captions, a music bed is
  laid under it, and a human approves before export.
- **`matting.py`** — *optional* "remove the background from the video" (no green
  screen). It's off unless an operator turns it on, and it's honest that it's slow
  and only for short clips.
- **`broll.py`** — *optional* "make up a brand-new clip to cut away to" (a
  text-to-video model). Because that **invents footage that was never filmed**,
  it's off unless an operator turns it on, only ever runs when a person
  deliberately opts in, and **always** stamps the clip as "AI-generated" — the
  same rule as the avatars below.
- **`avatars.py`** — *optional* AI talking-head presenters. MediaHub's rule is
  **no fake people unless you explicitly ask**, so this is off by default, only
  ever runs when a person deliberately opts in, and **always** stamps the video as
  "AI-generated". There is no way to make an undisclosed fake person.
- **`ingest.py`** — files an uploaded clip into the shared **media library**, so
  footage gets the same privacy, permission and approval rules as photos (which
  matters a lot when the footage is of children).
- **`projects.py`** — **saves** the timelines you're working on, one list per
  club, with their approval state.

## The rules it follows (the same as everywhere in MediaHub)

- **Facts are maths; only judgement is AI.** Finding and ranking moments,
  building the timeline, cropping — all deterministic. The one AI bit (naming a
  moment) is optional and never changes a fact.
- **Honest errors.** No FFmpeg, no speech-to-text, no provider key → a clear
  message, never a fake or half-made video.
- **A human approves before anything leaves.** A clip renders for *preview* any
  time, but it has to be approved before it can be exported.
- **It runs on our server**, and every finished video is cached under
  `DATA_DIR/motion_cache/video/` with a little `.json` next to it explaining why
  it looks the way it does.
