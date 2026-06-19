# `remotion/src/motion/` — the motion vocabulary, in Remotion

This is the **Remotion side** of MediaHub's motion vocabulary (roadmap 1.5). The
movements themselves are defined once in Python (`src/mediahub/motion/`); this
folder lets the video engine speak that same vocabulary.

| File | What it is |
| --- | --- |
| `tokens.generated.ts` | **Generated** — the presets + easing curves, copied from Python. Do not edit by hand. |
| `easing.ts` | Turns an easing name into a Remotion `Easing.bezier` curve. |
| `compile.ts` | Samples a preset frame-by-frame (`interpolate`) and maps it onto a StoryCard's animation channels. |

## Why a generated copy?

Remotion runs in Node/TypeScript and **can't import Python**. So after you edit
any preset in `src/mediahub/motion/`, regenerate this copy:

```bash
python scripts/regen_motion_tokens.py
```

A test (`tests/test_motion_tokens_sync.py`) fails if you forget — exactly like
the self-hosted fonts.

## The one hard rule

CSS `@keyframes` **do not render in Remotion** — only frame-pure `interpolate` /
`spring` do. That's why this folder samples the vocabulary into numbers per
frame (`compile.ts`) instead of emitting CSS. The actual movements are consumed
by the sprint intent files under `compositions/sprint/intents/` (`rise.ts`,
`pop.ts`, `drop_in.ts`), which are one-liners that delegate here.
