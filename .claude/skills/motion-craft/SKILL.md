---
name: motion-craft
description: MediaHub motion craft for Remotion story cards and meet reels. Use whenever you design, edit, or review motion video — StoryCard.tsx / MeetReel.tsx compositions, reel beats and rhythm, scene transitions, on-video text and captions, narration/audio, or "the video feels flat / samey / generic" feedback. Encodes beat direction, choreography, easing language, and transition craft adapted to MediaHub's frame-pure, brand-locked, fact-exact rendering rules.
---

# Motion craft

How to make MediaHub's MP4 output feel *directed* — composed beats, deliberate
rhythm, meaningful transitions — without ever trading away the things the
engine guarantees: exact facts, exact brand, deterministic re-renders.

Craft lineage: adapted for MediaHub from HeyGen's HyperFrames skills
(Apache-2.0; reference copy at `vendor/hyperframes-skills-main/`), rewritten
for the Remotion stack and MediaHub's non-negotiables. Where this file and
`mediahub-engineering` disagree, `mediahub-engineering` wins.

## The stack (real paths — design against these, don't invent)

- Compositions: `src/mediahub/remotion/src/compositions/StoryCard.tsx` (6s,
  one card) and `MeetReel.tsx` (cover → card beats → outro), registered in
  `Root.tsx`, 30fps. Formats: story 1080×1920 (default), portrait 1080×1350,
  square 1080×1080, landscape 1920×1080 (`render.js --width/--height`).
- Invoked from `src/mediahub/visual/motion.py`, cached at
  `DATA_DIR/motion_cache/<hash>.mp4` + `<hash>.json` manifest +
  `<hash>.poster.png`.
- Props carry the card facts plus creative direction:
  `archetype`, `motionIntent`, `mood`, `backgroundStyle`, `accentStyle`,
  `typographyPair`, `composition`, `photoTreatment`, `photoSrc`, `photoPos`,
  `heroStat`, `variationSeed`, and the APCA-gated colour roles
  `roleGround` / `roleSurface` / `roleAccent` / `roleOnGround`.
- Reel duration is computed, never hardcoded:
  `reel_duration_for(n) = 2.0 cover + 4.0 × cards + 1.0 outro` by default. The
  rhythm is caller-customisable (R1.12) — optional per-card beat weights +
  custom cover/outro seconds via `normalise_reel_rhythm`, mirrored into
  `MeetReel.tsx`'s carve and the ffmpeg fallback and folded into the cache key;
  a weighted card earns proportionally more seconds and an uncustomised reel
  stays byte-identical.
- The design-spec director emits `motion_intent` from a closed vocabulary
  (`creative_brief/design_spec.py::MOTION_INTENTS`): `fade_in`,
  `snap_in_then_settle`, `slide_up`, `scale_in`, `crossfade`, `kinetic_type`,
  `parallax`, `count_up`, `static`.

## Hard bounds (non-negotiable, inherited)

1. **Animation is a pure function of the frame.** Remotion
   `interpolate` / `spring` / `Sequence` only. CSS transitions, CSS
   `@keyframes`, and Tailwind animation classes do not render — never use
   them for motion.
2. **Deterministic.** No `Math.random()`, no `Date.now()`. All variation
   derives from `variationSeed` (a seeded PRNG if you need many values).
   Same props → byte-identical render.
3. **Facts are exact.** The time shown is the verified time; a `count_up`
   must land on exactly the true value and hold it. Never animate a number
   through fabricated intermediate text the viewer could screenshot as truth
   — see `references/text-and-captions.md`.
4. **Brand is exact.** Colours come only from the resolved roles
   (`roleGround`/`roleSurface`/`roleAccent`/`roleOnGround`, the same
   APCA-gated set the still painted) or the seed-permutation fallback. Never
   invent a hex. Fonts are the six self-hosted families loaded by
   `fonts.ts` — never a CDN, never a new family without the fonts workflow.
5. **Motion mirrors the approved still.** Archetype → motion scene parity is
   test-enforced (`tests/test_motion_v2_parity.py`); photo focus reuses
   `saliency.focus_position`. Don't fork the motion design away from what
   the customer approved as a still.
6. **Cache-key gotcha.** The cache hash covers card props + brand + duration
   + audio plan. Change the prop/brief shape → bump the cache key, or stale
   renders serve silently.
7. **Audio is honest.** Narration is the deterministic fact-only template
   (`visual/narration.py` — no LLM); on any synthesis/mux failure the video
   ships silent with the reason in the manifest. Most feed video plays
   muted: on-screen text must carry the message regardless.

## Workflow for any motion change

1. **Read the direction first.** The card props already carry intent:
   `motionIntent`, `mood`, `archetype`, `heroStat`. Honour them — the
   director chose them; your job is to execute them well.
2. **Plan beats before pixels.** For multi-scene work (the reel), write the
   rhythm down before coding: which beat is the peak, which are connective.
   → `references/beat-direction.md`
3. **Layout before animation.** Build each scene's *hero frame* — the moment
   when everything is entered and readable — as static JSX/CSS first.
   Entrances animate FROM offsets TO that layout; the layout is ground
   truth. Catch overlap in stillness, not in playback.
4. **Choreograph entrances; transitions own exits.** Every element enters
   via animation (nothing pops in fully formed). Elements do NOT animate out
   before a beat transition — the transition is the exit. Only the final
   scene (outro) may fade itself out. → `references/transitions.md`
5. **Apply the guardrails below.** Then self-review against the monoculture
   list in `references/motion-language.md`.
6. **Verify cheaply first.** Render a single frame to sanity-check layout,
   colour roles, and type sizes before a full 30–90s render. Then run
   `tests/test_motion_v2_parity.py` and the motion/audio tests; a full
   render of one card + one reel before shipping a composition change.

## Animation guardrails

- First animation starts at frame 3–9 (0.1–0.3s), never frame 0 — a t=0
  entrance reads as a jump cut.
- At least 3 distinct easings per scene; no more than two tweens share one.
  Easing is the adverb — vary it deliberately (`references/motion-language.md`).
- Vary entrance directions within a scene: up, from-left, scale, blur-in,
  opacity-only. `y: 30 → 0, opacity: 0 → 1` on everything is the
  signature of generated video.
- Stagger in order of importance, not DOM order; overlap entrances; keep a
  whole stagger sequence under ~15 frames (500ms).
- Exits (where allowed) are faster than entrances — build ≈ 0.4s, remove
  ≈ 0.25s.
- The slowest motion in a scene should be roughly 3× the fastest — uniform
  speed flattens hierarchy.
- Every scene: build (0–30%) → breathe (30–70%, one ambient motion, content
  readable) → resolve (70–100%). All-build scenes feel like slideshows.
- Ambient motion varies per beat (drift, breathe, slow pan, temperature
  shift — sometimes stillness). Slow-zoom-on-everything is monoculture.
- No full-frame linear gradients on dark grounds (H.264 banding) — radial,
  or solid + localised glow. No repeating geometric overlays (tile grids,
  uniform dots): the eye sees the grid instantly and reads it as cheap.
- Type minimums at video distance: headlines 60px+, body 20px+, data labels
  16px+; `font-variant-numeric: tabular-nums` on any animated or stacked
  number.

## References (read on demand)

- `references/motion-language.md` — easing as emotion (Remotion `Easing` +
  the mood→spring table), speed as weight in frames, the monoculture
  checklist, image motion treatment, Remotion-specific load-bearing rules.
  **Read for any animation work.**
- `references/beat-direction.md` — per-beat direction format (concept, mood,
  choreography verbs, depth layers), rhythm planning for reels, mapping the
  `MOTION_INTENTS` vocabulary to executed motion. **Read for reel work.**
- `references/transitions.md` — what each transition kind *means*, the
  current `transitionFor(seed)` set (crossfade/push/wipe), how to add new
  kinds frame-pure, velocity matching, narrative position. **Read before
  touching beat handoffs.**
- `references/text-and-captions.md` — on-video type, reading time, word
  grouping, per-word emphasis on facts, MediaHub's named text-effect
  vocabulary with frame-pure recipes, count-up exactness.
- `references/narration-and-audio.md` — pacing budgets (2.4 words/sec),
  number pronunciation via `spoken_time`, script structure for reels, music
  bed and honest-silence rules.
