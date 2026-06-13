# Motion language

How motion *means* things in MediaHub video. Adapted from HyperFrames'
motion-principles (Apache-2.0, `vendor/hyperframes-skills-main/`), translated
from GSAP timelines to Remotion's frame-pure model.

## The monoculture checklist

These defaults aren't wrong individually — they're wrong as *defaults*. When
every card animates the same way, the club's feed looks generated no matter
how good the brand is. Before shipping, scan for:

- **Same ease on every tween.** A cubic ease-out everywhere is the video
  equivalent of one font weight. No more than two independent tweens in a
  scene share an ease.
- **Same duration on every tween.** 12–15 frames on everything flattens
  rhythm. Slowest ≈ 3× fastest within a scene.
- **Same entrance direction.** Slide-up-and-fade on every element is the
  universal generated-video entrance. From-left, from-right, scale, blur-in,
  opacity-only, letter-tracking — each says something different.
- **Same stagger everywhere.** A 2-frame stagger in one beat and a 5-frame
  stagger in the next makes the beats feel like different moments.
- **Ambient slow-zoom on every scene.** Vary it: slow pan, breathing scale on
  a glow, drift, nothing. Stillness after motion has real weight.
- **First animation at frame 0.** Offset the opening 3–9 frames so the scene
  reads as composed.

The card's `variationSeed` exists precisely so two cards in the same pack can
make *different* deliberate choices deterministically. Use it to pick among
alternatives; never use it as an excuse for randomness that breaks parity
with the approved still.

## Easing is emotion, not technique

The motion is the verb; the easing is the adverb. The same slide-in feels
confident with an exponential out, dreamy with a sine in-out, playful with a
spring overshoot. Choose the adverb from the card's `mood`, deliberately.

Remotion vocabulary (no GSAP here — these are the house tools):

| Tool | Character | Typical MediaHub use |
| --- | --- | --- |
| `Easing.out(Easing.cubic)` | Composed, reliable | Default entrance for supporting elements |
| `Easing.out(Easing.exp)` | Premium, decisive snap | Hero stat reveal, `snap_in_then_settle` |
| `Easing.inOut(Easing.sin)` | Organic, no hard edges | Ambient drift, breathing glows, Ken Burns |
| `Easing.in(Easing.cubic)` | Accelerates away | Exits (outro only), outgoing push/wipe |
| `Easing.inOut(Easing.cubic)` | Neutral reposition | Elements moving between positions mid-scene |
| `spring()` | Physical, alive | Entrances that should feel like objects |
| Stepped (floor over interpolated value) | Mechanical, digital | Tick counters, type-on; use sparingly |

Direction rules that survive every style:

- `.out` for entering. `.in` for leaving. `.inOut` for moving within the
  scene. An ease-in entrance feels sluggish; an ease-out exit feels
  reluctant — these reversals are the most common easing bugs.

### The mood → spring table (already in the codebase — extend, don't fork)

`StoryCard.tsx` selects spring configs from the brief's `mood` (vocabulary in
`creative_brief/design_spec.py::MOODS`):

- calm / weighty moods → `{ damping: 30, stiffness: 60 }` — settles slow, no
  overshoot. Stoic, precise, minimal.
- electric / kinetic moods → `{ damping: 12, stiffness: 140 }` — fast with
  visible overshoot. Explosive, celebratory, fierce.

When adding mood handling, slot new moods into this scale rather than
inventing a parallel mechanism. Keep overshoot subtle for institutional
clubs; a medal celebration earns the bounce, a DQ notice does not.

## Speed expresses weight (in frames @ 30fps)

- **5–9 frames** — percussive, kinetic. Something happens *to* the frame.
- **9–15 frames** — comfortable, professional. The workhorse range.
- **15–24 frames** — deliberate; the element asks for attention.
- **24+ frames** — atmospheric; the motion is part of what the scene *is*.

Mix ranges. A headline that settles over 21 frames while its label snaps in
over 7 creates hierarchy without touching size or colour.

## Scene structure: build, breathe, resolve

Every beat (a StoryCard scene, a reel card beat) has three phases:

- **Build (0–30%)** — elements enter, staggered by importance.
- **Breathe (30–70%)** — content fully readable, exactly one ambient motion
  alive. This is where the viewer actually reads the time and the name.
- **Resolve (70–100%)** — the transition takes over (reel) or the outro
  fades (final scene). In a 4-second reel beat that's ~36 frames of build,
  ~48 of breathe, ~36 of handoff — protect the breathe phase; facts need
  reading time.

## Choreography is hierarchy

Whatever moves first is read as most important. For a result card that is:
the achievement (`heroStat` / `achievementLabel`), then the athlete, then
the event/meet metadata, then decoratives. Stagger in that order — not DOM
order — and overlap entrances rather than queueing them.

## Image motion treatment

Photos never sit flat, and never lie:

- **Ken Burns** — scale 1.0 → 1.04 over the beat with `Easing.inOut(Easing.sin)`.
  Anchor the zoom on the saliency focus (`photoPos`, from
  `saliency.focus_position`) so the motion drifts toward the athlete, not
  the lane rope.
- **Parallax** (`motion_intent: parallax`) — background photo and foreground
  panel translate at different rates; keep the displacement small (≤ 24px)
  so the cutout edge never reveals fabricated background.
- **Cutout treatment** (`photoTreatment: cutout`) — the cutout may enter
  separately from its panel, but its final composition must match the still.
- Never warp, recolour beyond the duotone treatments, or generatively
  extend a photo. The photo is evidence.

## Remotion load-bearing rules

The HyperFrames originals guard GSAP/capture-engine bugs; these are the
equivalents that actually bite in this stack:

- **Everything derives from `useCurrentFrame()` / `useVideoConfig()`.** Any
  value that changes over time is computed from the frame. No
  `useEffect`-driven state for motion, no wallclock, no `requestAnimationFrame`.
- **Clamp your interpolations.** Default extrapolation extends beyond the
  input range — an opacity tween overshoots past 1 or below 0 and flashes.
  Use `extrapolateLeft/Right: "clamp"` unless overshoot is the design.
- **`spring()` needs the real `fps`** from `useVideoConfig()` — hardcoding
  30 breaks the day a format changes. Give springs ~20+ frames before the
  beat ends or they're cut mid-settle.
- **Scope scenes with `<Sequence>`.** A Sequence unmounts its children
  outside its frame window — that's the deterministic "hard kill" HyperFrames
  needs manual `tl.set()` calls for. Don't hand-roll visibility with
  opacity math across the whole timeline when a Sequence boundary does it
  exactly.
- **Local frame inside a Sequence starts at 0.** Computing against the
  global frame inside a sequenced beat is the classic off-by-`from` bug —
  entrances that already happened or never come.
- **Don't stack two competing transforms on one element.** Entrance
  translate + Ken Burns scale on the same `<Img>` makes one overwrite the
  other in the style object. Wrap: entrance on the wrapper, ambient on the
  child.
- **Loops are finite and frame-derived.** A breathing glow is
  `Math.sin(frame / period)` — never a CSS animation, never an unbounded JS
  loop.
- **Poster frame matters.** `<hash>.poster.png` is taken from the render;
  make sure the hero frame (not a half-entered build frame) is what a
  paused/preview viewer sees — check the beat's build timing against the
  poster extraction point in `visual/motion.py`.
