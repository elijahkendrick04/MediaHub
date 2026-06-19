# `motion/` — the brand motion vocabulary

This folder is MediaHub's **dictionary of movements**. Instead of writing the
same "slide up and fade in" by hand in three different places, we describe each
movement **once** here, and three "translators" turn that one description into
the language each renderer speaks.

Think of it like a recipe written once, then cooked on three different stoves.

## What's a "preset"?

A *preset* is one named movement — `rise`, `pop`, `pan_left`, `fade_out`. Each
one is just a list of **keyframes**: "at the start the thing is 40px low and
invisible; by the end it's in place and solid." We also tag each preset with:

- a **family** — is it an entrance (`in`), an idle wiggle (`loop`), or an exit
  (`out`)?
- an **energy** — `calm`, `standard`, or `electric`.
- a **direction** — `up`, `left`, `in`…

The full list lives in [`vocabulary.py`](vocabulary.py).

## The three translators (compilers)

| File | Speaks to | Used for |
| --- | --- | --- |
| [`compile_remotion.py`](compile_remotion.py) | the video engine (Remotion) | reels & story videos |
| [`compile_ffmpeg.py`](compile_ffmpeg.py) | the free video engine (FFmpeg) | photo zoom/pan + fades |
| [`compile_css.py`](compile_css.py) | a web browser | the website & previews |

Why three? Because the video engine can't read browser CSS, and the browser
can't read video-engine code. One source of truth, three outputs — they can
never drift apart.

## The extra movements

- [`paths.py`](paths.py) — **motion paths**: move something *along a curve* (and
  turn it to face the way it's going).
- [`shared_element.py`](shared_element.py) — **shared-element transitions**: the
  same photo glides from where it was in one scene to where it sits in the next,
  instead of cutting.

## Two safety rules built in

- **Reduce-motion.** Every preset has a calmer twin (`.reduced()`) that drops
  the movement and just fades — for people who ask their device for less motion.
- **Caps.** Nothing animates longer than 10 seconds, and one design can't have
  more than 50 animations (keeps renders sane and fast).

## If you change a preset

The video engine reads a **generated** copy of this vocabulary (it can't import
Python). After editing anything here, regenerate that copy:

```bash
python scripts/regen_motion_tokens.py
```

That rewrites `src/mediahub/remotion/src/motion/tokens.generated.ts` and
`src/mediahub/web/static/theme/motion.css`. A test
(`tests/test_motion_tokens_sync.py`) fails if you forget — same idea as the
self-hosted fonts.

Everything here is **deterministic**: the same preset at the same frame always
produces the same value, so videos render identically every time.
