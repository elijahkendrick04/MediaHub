# Beat direction

How to direct the beats of a meet reel (and the single scene of a story
card) so each one is a *moment*, not a slide. Adapted from HyperFrames'
beat-direction (Apache-2.0, `vendor/hyperframes-skills-main/`), re-aimed at
MediaHub's computed-duration, ranked-card reels.

## The reel's fixed skeleton (don't fight it — direct within it)

`MeetReel.tsx` assembles: **cover (2.0s) → one beat per card (4.0s each,
top-N by rank, capped at 5) → outro (1.0s)**, with total duration computed
by `reel_duration_for`. The skeleton is deterministic; the direction — what
each beat feels like, how it hands off — is where craft lives.

- **Cover** — meet name + honest label-derived stat chips ("TOP 3 SWIMS",
  "2 PBS"). Job: establish the motion language and the brand. It is the
  opening line; whatever pacing you set here is the promise the rest keeps.
- **Card beats** — rank-weighted. The #1 card is the peak of the video:
  it may take the boldest entrance and the most decisive transition *into*
  it. Lower-ranked beats are connective — quieter, consistent.
- **Outro** — club name/logo. No new energy: the slowest, simplest motion
  in the piece. Closure, not climax. This is the only scene allowed to
  animate itself out.

## Per-beat direction: describe the experience, then the pixels

A beat is a world, not a layout. Write what the viewer *experiences*
before any JSX:

- **Mediocre:** "Dark ground. Time in white, 220px. Logo top-left."
- **Directed:** "The ground is already alive — a slow accent glow breathing
  behind the lane. The time SNAPS in with enough force that the glow
  ripples; the swimmer's name settles underneath a half-second later, calm,
  certain. PB badge STAMPS last, like a verdict."

Then express it in the existing prop vocabulary — that's what makes the
direction renderable and deterministic:

1. **Concept** (2–3 sentences) — what should the viewer feel? The
   achievement drives it: a first-ever PB feels different from a county
   gold.
2. **Mood** — one of `MOODS` (`creative_brief/design_spec.py`):
   `explosive`, `celebratory`, `calm`, `stoic`, `precise`, … This selects
   the spring family (see motion-language.md).
3. **Choreography verbs** — every element gets one. If you can't name the
   verb, the element isn't designed yet:
   - *Impact/weight:* SLAMS, PUNCHES, STAMPS, DROPS
   - *Directional:* SLIDES, PUSHES, WIPES, CUTS
   - *Reveals/builds:* DRAWS, FILLS, GROWS, COUNTS UP, ASSEMBLES
   - *Organic/ambient:* FLOATS, DRIFTS, BREATHES, PULSES
   - *Mechanical:* TYPES ON, CLICKS, LOCKS IN, SNAPS
   Verbs follow from the beat's concept, not from an energy lookup — a
   "calm" club's distance-swim beat might still have a time that LOCKS IN.
4. **Depth layers** — every beat has at least two, ideally three:
   - BG: the `backgroundStyle` treatment (dots, diagonal, stripes,
     geometric, halftone, grain, water, radial, duotone, clean) + at most
     one ambient motion.
   - MG: the facts — name, event, time, place.
   - FG: accents from `accentStyle` (brackets, stripe, badge, frame,
     ribbon, arrow, underline…), structural rules, the logo.
5. **Transition out** — named kind + duration + easing, chosen for meaning
   (see transitions.md). Not "transition", but "push left, 12 frames,
   cubic out — next point, same story".

## Mapping `MOTION_INTENTS` to executed motion

The design-spec director emits one `motion_intent` per card from the closed
vocabulary. Execution belongs to the composition; intent → verb examples:

| Intent | The beat should read as |
| --- | --- |
| `fade_in` | Quiet confidence; elements resolve out of the ground |
| `snap_in_then_settle` | Decisive — hero SNAPS, then one soft settle; no wobble after |
| `slide_up` | Momentum; staggered upward entries, overlapped |
| `scale_in` | Arrival; from 0.92–0.96 scale, never from 0 |
| `crossfade` | Continuity; layered dissolve between states |
| `kinetic_type` | The words are the motion — per-word builds, weight shifts |
| `parallax` | Depth; photo and panel travel at different rates |
| `count_up` | The number is the story — see text-and-captions.md exactness rules |
| `static` | Stillness as a choice; only ambient breath, strong layout |

Keep the closed vocabulary closed: a new intent is a schema change
(`design_spec.py` + `StoryCard.tsx` + parity test + cache-key bump), not a
prop you sneak in.

## Rhythm planning (reels)

Declare the rhythm before implementing — name it like
`establish-build-PEAK-settle-out`. Derive it from the cards' ranking and
the club's character, not from a template:

- Where does energy peak? Almost always the top-ranked card — but a
  3-PBs-one-swimmer story might build across beats instead.
- Do beats contrast? Two `explosive` beats back-to-back flatten each other;
  insert a `precise` or `calm` beat between if ranking allows.
- Does the cover promise what the beats deliver? A percussive cover into
  meditative beats reads as broken.

The 4s-per-card timing is fixed; rhythm lives in how much of each 4s is
build vs breathe, how hard the entrance hits, and which transition kind
carries each handoff.

## Narration and SFX cues are facts, not vibes

The narration track (`visual/narration.py`) is a deterministic template
over verified labels — when directing a beat, align the choreography to
where its sentence lands (the time should be on screen while it is spoken),
but never add spoken claims the labels don't carry. Music (operator's
licensed bed via `MEDIAHUB_REEL_MUSIC_DIR`) is picked deterministically and
ducked under narration — beats should land on visual rhythm alone, because
most viewers are muted and silent renders must stay first-class.
