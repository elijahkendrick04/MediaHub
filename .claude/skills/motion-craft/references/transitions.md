# Transitions

A transition tells the viewer how two beats relate. Crossfade says "this
continues". Push says "next point". A hard cut says "wake up". Choose for
meaning, not novelty. Adapted from HyperFrames' transitions craft
(Apache-2.0, `vendor/hyperframes-skills-main/`), rebuilt for frame-pure
Remotion — there is no GSAP, no WebGL shader package, no CSS transition
here, and there must never be.

## The non-negotiable discipline

1. **Every beat handoff uses a transition.** No raw jump cuts between reel
   beats (a *designed* hard cut is a transition — an accidental one is a
   bug).
2. **Every element enters via animation.** Nothing pops in fully formed.
3. **Exit animations are banned** except in the outro. The outgoing beat's
   content stays fully visible until the transition starts — the transition
   IS the exit. Emptying a beat before its handoff gives the transition
   nothing to work with.
4. **The outro may fade itself out.** It's the only scene that owns its own
   exit.

## What exists today

`MeetReel.tsx::transitionFor(seed)` picks deterministically from three
kinds via `variationSeed % 3`: **crossfade**, **push**, **wipe**. That's a
deliberately small, exact set — extend it with intent, not bulk:

- A new kind must be frame-pure (interpolated transforms / opacity /
  `clipPath` / `filter` values computed from the frame).
- It must read correctly at 30fps after H.264 — test on dark grounds where
  banding and mushy blurs show first.
- It joins the deterministic picker (or a brief-driven selection) — never a
  random pick, and the same seed must keep producing the same cut so
  re-renders stay byte-identical.
- Bump the motion cache key if the selection logic or prop shape changes.

## A frame-pure catalog to draw from

Concepts portable to Remotion, each implementable with `interpolate` on the
outgoing and incoming beat containers. Durations in frames @30fps:

| Kind | Feel / use | Sketch |
| --- | --- | --- |
| Crossfade | "This continues" — related beats | opacity A 1→0, B 0→1 over 8–12f |
| Push (l/r/up) | "Next point" — list progression | A translateX 0→−15%, B +100%→0, cubic out, 9–15f |
| Wipe | Editorial page-turn | `clipPath: inset()` edge sweep over B, 9–12f |
| Blur-through | Soft register shift | A blurs 0→16px & fades; B enters 16→0px blur, 8–12f |
| Zoom-through | Momentum into the peak beat | A scale 1→1.15 + fade; B 0.92→1, exp out, 10–14f |
| Iris | Spotlight reveal (medal beat) | `clipPath: circle(r%)` 0→120% from the saliency focus point |
| Blinds | Structured, precise clubs | 4–8 `inset()` strips staggered 1–2f apart |
| Light wash | Celebration flash | full-frame brand-accent overlay opacity 0→0.85→0 across the cut, 6–8f |
| Whip pan | High-energy adjacent beats | A translateX 0→−40% w/ directional blur; B mirrors in, both `Easing.in/out(Easing.cubic)` velocity-matched, 8–10f |
| Hard cut | Percussion; rapid-fire sequence | instant swap on a beat boundary — design it, don't default to it |

Avoid: repeating geometric grids/tiles/dot arrays (reads cheap), star/lens
flare shapes (reads as clip-art), anything requiring per-pixel warping
(that's shader territory — out of scope for this stack), and transitions
longer than ~18 frames (they eat the next beat's build).

## Velocity matching

For directional kinds (push, whip, zoom-through): the outgoing side
accelerates (`Easing.in`), the incoming side decelerates (`Easing.out`),
and their fastest points meet at the cut. The viewer reads one continuous
camera move instead of two animations. If the exit covers 40% of the frame
in its last 3 frames, the entrance should cover ≈40% in its first 3.

## Energy → character calibration

Derive the character from the beat being entered (its `mood`), then pick a
kind with that character:

- **Soft/organic** (calm, warm, stoic): dissolves and blurs; 12–18f; sine
  in-out. Nothing percussive.
- **Directional/purposeful** (precise, bold): push, wipe, blinds; 9–15f;
  clean cubic deceleration.
- **Percussive/instant** (explosive, electric, fierce): zoom-through, whip,
  light wash, designed hard cut; 5–9f.

One primary character per reel, with 1–2 contrasting accents — usually the
entry into the top-ranked beat. Five "wow" transitions in a 15s reel flatten
all of them.

## Narrative position

- **Cover → first beat** sets the motion language; make it the reel's
  *typical* transition, not its boldest.
- **Between same-rank beats** — near-invisible; consistency over flair.
- **Into the peak (top-ranked) beat** — the earned, boldest cut.
- **Into the outro** — the simplest and slowest in the reel; let the viewer
  exhale onto the club mark.
