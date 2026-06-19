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
  or a fade) and any text on top. This file also turns that list into the exact
  instructions FFmpeg needs. It's pure maths — the same timeline always makes the
  same instructions — so it's easy to test and safe to cache.
- **`moments.py`** — finds the **highlight**. It listens for the loud bit (the
  cheer) and watches for the camera cut (the finish), then ranks those moments.
  This is deliberately *not* AI — "which two seconds matter" has to be the same
  answer every time, like deciding which result outranks which. (It *can* ask the
  AI to put a short **name** on a moment, but that's just a label and never
  changes which moment was picked.)
- **`reframe.py`** — **crops** a wide video to an upright shape without chopping
  the swimmer out, by reusing the same "where's the subject" maths the still
  graphics use.
- **`captions.py`** — puts the **spoken words on screen**, using the speech-to-
  text tool (1.4). The words are exactly what was said — no AI writing — and you
  can fix the text or the timing afterwards.
- **`render.py`** — actually **makes the MP4** from a timeline, on the server,
  and remembers it so the same timeline is never rendered twice. If FFmpeg isn't
  there, it says so honestly instead of making a broken file.
- **`clip_maker.py`** — the **star of the show**: it runs all of the above in
  order to turn one raw clip into one finished highlight.
- **`matting.py`** — *optional* "remove the background from the video" (no green
  screen). It's off unless an operator turns it on, and it's honest that it's slow
  and only for short clips.
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
