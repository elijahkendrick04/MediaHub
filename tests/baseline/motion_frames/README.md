# motion_frames — committed reference frames for the motion visual-regression harness

These PNGs are the "this is exactly what the video should look like" answer key
for the frame-by-frame motion check (roadmap R1.27). Each one is a single frame
of a real Remotion composition (a story card or a meet reel), rendered with
frozen, made-up demo data so the only thing that can change the picture is the
composition code itself.

```
motion_frames/<scenario>/frame_<NNNNNN>.png
```

`<NNNNNN>` is the zero-padded frame number. The scenarios and the frames they
capture are defined in `src/mediahub/visual/motion_regression.py`:

- **story_pb** — one story card (a new personal best), frames `0, 18, 34, 60`
  (entrance start → mid-entrance → the spring's overshoot → settled). The card
  holds still after ~1s, so all the distinct states are early.
- **reel_meet** — a three-swimmer meet reel, frames `60, 130, 260, 370, 440`
  (the branded cover, then one settled frame for each of the three cards, then
  the outro). One frame per distinct scene.

## How they're used

`scripts/motion_vr.py check` (and the opt-in test
`tests/test_motion_regression.py::test_committed_baselines_match`) re-renders
these same frames and pixel-diffs them against the pictures here. A difference
bigger than a small tolerance is reported as a visual regression.

## Refreshing them (do this on purpose)

If you deliberately change how a card or reel looks, the baselines must be
re-captured and **eyeballed** before committing — they are never rewritten
automatically by the check (that would let a bug bless itself):

```bash
python scripts/motion_vr.py capture            # refresh all
python scripts/motion_vr.py capture --scenario story_pb
```

This needs Node 18+ and `npm install` inside `src/mediahub/remotion`. Renders
are deterministic (no randomness, no clock, self-hosted fonts), so a re-capture
on the same toolchain reproduces identical frames.
