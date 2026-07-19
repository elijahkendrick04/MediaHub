# On-video text and captions

Type in motion for story cards and reels. Adapted from HyperFrames'
typography/captions/text-effects craft (Apache-2.0,
`vendor/hyperframes-skills-main/`); the effect recipes below are MediaHub's
own, written frame-pure for Remotion.

## The fixed type palette

Fonts are the seven self-hosted families loaded by `remotion/src/fonts.ts`
(byte-identical woff2 to the still renderer): **Bebas Neue, Anton, Bowlby
One, Playfair Display** (display), **Space Grotesk** 500/700, **Inter** 400/800 (text),
**JetBrains Mono** 500/700 (data). The brief's `typographyPair` picks the
pairing. Your levers are register, weight contrast, size, tracking, and
motion — never a new family, never a CDN (`tests/test_self_hosted_fonts.py`
guards this).

- Pair across registers (display + text, text + mono), not two lookalikes.
- Weight contrast must be extreme enough to read in motion at a glance:
  Inter 400 vs 800, not 400 vs 600.
- Track display sizes slightly tight (−0.02 to −0.04em) — encoding eats
  letter detail; loose display tracking reads gappy on video.
- Light-on-dark optics: same weight reads heavier and tighter on dark
  grounds; prefer the lighter weight option and add a touch of line-height.
- `font-variant-numeric: tabular-nums` on every time, split, and counter —
  proportional digits wobble when they change.

## Reading time is a budget

Text on video has a deadline the viewer doesn't control:

- A line shown for 3 seconds must be readable in 2. Fewer words, larger.
- Type minimums: headlines 60px+, body 20px+, labels 16px+ — at 1080-wide
  formats, err larger. If you're writing a sub-24px font size, justify it.
- Word grouping for caption-style text: high energy 2–3 words per group,
  conversational 3–5. One group visible at a time; group boundaries on
  sentence/phrase breaks.
- Measure, don't hope: long athlete/event names are normal (relay teams,
  "100m Individual Medley"). The still renderer fits text deterministically
  (`graphic_renderer/autofit.py::fit_font_px`); motion layouts must follow
  the same instinct — compute size from the actual string, or design the
  layout so the longest realistic string fits. Truncated names are a
  trust bug, not a style choice.

## Per-word emphasis on facts

Emphasis belongs on the *verified* facts: the time, "PB", the medal, the
delta. Honest emphasis tools, all frame-pure:

- **Weight/colour pop** — the fact in `roleAccent` or the heavier weight.
- **Scale beat** — the fact enters last and 1 size class larger; or a
  single ≤1.06 scale pulse as the narration says it. One pulse — repeated
  pulsing reads as an ad.
- **Marker sweep** — accent bar behind the fact, `scaleX` 0→1 from the
  left over 9–12 frames (`transformOrigin: left`), text above it. Pairs
  with the `underline` / `stripe` accent treatments from the still.
- **Draw-on underline / circle** — SVG path with `strokeDashoffset`
  interpolated to 0. Use the brief's `accentStyle`; don't add hand-drawn
  energy to a `stoic` card.

## MediaHub's named text effects (frame-pure recipes)

A small owned vocabulary — name these in beat direction instead of
describing motion long-hand. All recipes: `f` is the local Sequence frame,
durations @30fps, every interpolate clamped.

- **`rise-in`** — translateY 24→0 + opacity 0→1, 12f, `Easing.out(Easing.cubic)`.
  The workhorse. Vary the offset axis per element so it isn't the only verb.
- **`blur-in`** — `filter: blur(12px→0)` + opacity, 12–15f. Soft register;
  good for meet metadata.
- **`mask-reveal`** — wrapper `clipPath: inset(0 0 100% 0 → 0)`, 10–14f,
  text itself static. Editorial; strong for headlines.
- **`slam-in`** — scale 1.4→1 + opacity 0→1 in 5–7f, `Easing.out(Easing.exp)`,
  then a 2f settle. For `snap_in_then_settle` heroes. Never from scale 0 —
  real objects don't appear from nothing; start ≥0.9 for gentle, ≤1.5 for
  slams.
- **`track-in`** — letterSpacing 0.3em→normal + opacity, 15–21f. Cinematic;
  cover lines.
- **`type-on`** — characters revealed by `Math.floor(interpolate(f, …))`
  count, stepped, with no cursor after completion. Mechanical register;
  splits/mono data only.
- **`count-up`** — see exactness below.
- **`word-cascade`** — per-word `rise-in` staggered 2–4f, total under 15f.
  For `kinetic_type` intents.

If a new effect earns a name, add it here with its recipe so reels and
story cards reuse it as one design system — that's what keeps a pack
feeling art-directed instead of assembled.

## Card-wide text-effect overlay (R1.11)

The recipes above are per-element entrances you choreograph inside a scene. The
**text-effect overlay** (`sprint/layers/text_fx.tsx`) is the complementary
*card-wide* layer: it dresses every text node a scene already drew, without
editing the scene, by injecting one scoped stylesheet rule that reaches the
type through CSS inheritance (`text-shadow` is inherited; `filter` is set on the
card root alone). It's chosen deterministically from the brief — expressive
`mood` first, the still's `accentStyle` as the fallback — and the restraint
moods (`neutral` / `minimal` / `stoic`) and brief-less callers resolve to
*none*, so legacy motion is unchanged and only a directed card earns an effect.

- **`glow`** — soft `roleAccent` halo (`text-shadow: 0 0 0.08em / 0.18em /
  0.34em`, `em` so it scales per element). Fades in with the text's own opacity.
  Moods: `electric`, `explosive`.
- **`outline`** — a dark `roleGround` keyline (8-direction `em` `text-shadow`)
  that *raises* legibility over busy photos and never hollows the fill (shadows
  paint behind). Moods: `fierce`, `bold`; accent `stripe` / `frame`.
- **`shadow3d`** (roadmap "3D-shadow") — stepped down-right extrude in
  `roleGround`. Moods: `triumphant`, `celebratory`; accent `badge` / `ribbon`.
- **`stroke_animate`** (roadmap "stroke-animate") — the keyline draws on:
  width `0 → 0.026em` over ~0.5s, `Easing.out(Easing.cubic)`, then held. Mood:
  `precise`; accent `underline` / `diagonal_underline`.
- **`blur_to_focus`** (roadmap "blur-to-focus") — the whole card blooms:
  `filter: blur(~15px → 0)` on the root over ~0.6s. The card-level cousin of
  the per-element `blur-in` above. Moods: `calm`, `warm`.

Like everything else here it's frame-pure (the rule is rebuilt each frame from
`interpolate(frame, …)`, never a CSS `@keyframes`/`transition`) and brand-exact
(colours only from the resolved roles).

## Count-up exactness (non-negotiable)

`count_up` is a motion intent precisely because a swim time is the story.
Rules:

- The animation must end exactly on the verified value and hold it through
  the breathe phase — never settle "near" it, never overshoot past it and
  come back through different digits.
- Format-preserve while counting: a 1:02.45 counts within `M:SS.hh`
  structure (tabular-nums), not as a float that re-formats at the end.
- Intermediate values are presentation, not claims — keep the count fast
  (≤20f) and finish before narration speaks the number, so no paused frame
  shows a wrong time for long. If the layout can't guarantee that, use
  `slam-in` on the final value instead. When in doubt: the exact number,
  instantly, is always correct.

## Placement per format

- **story 1080×1920** — keep facts inside the central safe band; platform
  chrome eats the top ~250px and bottom ~320px. Caption groups sit lower
  middle, never the extreme bottom.
- **portrait 1080×1350 / square 1080×1080** — anchor to a zone (left/top or
  right/bottom) per the still's `composition` prop; centred-and-floating
  everything is a web habit, not a frame.
- **landscape 1920×1080** — captions bottom 80–120px, centred; keep clear
  of the photo's saliency focus (`photoPos`) — never cover the athlete's
  face.
- One caption group at a time; `<Sequence>` windows own visibility, so a
  group can't linger past its end by construction — don't re-implement
  visibility with opacity arithmetic.
