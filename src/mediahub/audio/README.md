# `audio/` — the sound engine

This package gives MediaHub's videos sound: background music, sound effects, and
spoken narration — all rights-clean and explainable. It's roadmap item **1.8**.

A reel with no sound feels flat. But you can't just grab any song off the
internet — that's how clubs get their posts taken down. So this package does two
things at once: it gives you good sound, **and** it keeps the rights tidy.

## What's in here

- **`library.py`** — the catalogue of tracks. MediaHub ships its own small set of
  sound effects and simple music beds (in `assets/`). They're all made by us and
  given away for free (CC0), so any club can use them anywhere. Operators can add
  their own licensed music too. Every track knows its mood ("triumphant"), its
  energy (1–5), and which social platforms it's safe on.
- **`select.py`** — picks the track that *fits* the reel. Three gold medals want
  something triumphant; a quiet meet wants something calm. That's a judgement, so
  it asks the AI (and says so honestly if no AI is set up, falling back to a
  steady default pick).
- **`ops.py`** — the boring-but-essential edits: trim, fade, volume, speed,
  pull the audio out of a video, join clips. Plain maths with FFmpeg — same input
  always gives the same output.
- **`clean.py`** — tidies up a recording: removes hiss (denoise) and makes
  everything the same loudness (the broadcast "EBU R128" standard). Also plain
  maths, no guessing.
- **`voice.py`** — the voices. A list you can choose from (including **Welsh**),
  speed/pitch controls, and the **pronunciation lexicon**: teach MediaHub how to
  say your swimmers' names once, and every video gets them right.
- **`rights.py`** — the rights ledger. When someone uploads their own audio, we
  fingerprint it, record who said it was OK to use and under what licence, and
  warn if the same file shows up again.

## The rules it follows

- The maths stays maths (trim, fades, loudness, the fallback track pick are all
  deterministic — same in, same out).
- The one judgement — *which* track suits the reel — goes through the AI and
  fails honestly if no AI is available. It never pretends.
- Nothing is faked: no made-up track, no made-up licence. Every bundled asset is
  genuinely ours and free to use.

## How the rest of the app uses it

The reel/video engine (`visual/motion.py`, `visual/audio_mux.py`) asks this
package for a track and lays it under the video. The voice layer sits on top of
the existing text-to-speech in `visual/voiceover.py` — this package adds the
catalogue, the controls, and the name lexicon, not a second synthesiser.
