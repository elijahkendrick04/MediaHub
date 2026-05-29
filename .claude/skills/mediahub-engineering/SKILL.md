---
name: mediahub-engineering
description: MediaHub domain knowledge for agents working in this repo. Use whenever you touch the pipeline, content generation, rendering (Remotion motion or Playwright graphics), AI surfaces, brand/theming, or content quality. Encodes the deterministic-engine boundary, the AI honest-error rule, and the conventions that keep "is this a PB?" accurate and every card exact and on-brand.
metadata:
  tags: mediahub, pipeline, generation, rendering, brand, ai-surfaces
---

## When to use

Load this whenever you are editing MediaHub code. It captures the rules that
aren't obvious from any single file but, if broken, silently degrade accuracy,
trust, or brand fidelity. Read the relevant rule file before changing that area.

## The one-paragraph mental model

MediaHub turns structured sport results into ranked, branded, ready-to-post
content: **ingest → detect → rank → brand → generate → approve → export.** The
moat is the *intelligence* (sport-grounded detection + ranking), not the
rendering. Two layers must never blur:

- **Deterministic engine** (parsers, detectors, ranker, colour-science,
  mathematical scoring) — accuracy-critical, never AI-replaced.
- **AI judgement surfaces** (captions, creative direction, brand/palette
  interpretation, tagging) — go through `media_ai.llm` / `ai_core.llm`, and
  fail honestly when no provider is configured.

## Non-negotiables (full detail in `rules/`)

1. **Never AI-replace the deterministic engine.** Parsers, detectors, the
   ranker, and colour-science stay deterministic. → `rules/deterministic-engine.md`
2. **AI surfaces fail honestly — never fabricate.** No regex/template "fake
   caption", stub profile, or made-up palette. Surface the error.
   → `rules/ai-surfaces.md`
3. **Video animation is a pure function of the frame.** No CSS/Tailwind
   animation in compositions; data-driven typed props; honest silent fallback
   for audio. → `rules/motion-and-audio.md`
4. **Graphics are exact, not generative.** The result card is rendered
   deterministically (Playwright HTML→PNG); generative imagery is only abstract
   background *under* the text. Text is measured to fit.
   → `rules/graphics-and-brand.md`
5. **Fix "samey" with variety that stays exact + on-brand**, never with
   generative approximation. → `rules/generation-quality.md`
6. **Respect the repo's spine:** `DATA_DIR`, `url_for()`, feature flags,
   `_h()` escaping, multi-tenant isolation, and the gated removal process.
   → `rules/conventions-and-security.md`

## Structure of a smart change

- Read the relevant rule file first.
- Keep the deterministic / judgement split intact.
- Add or update a test; run `python -m pytest tests/ -q` and confirm **no new
  failures** vs the branch point (check the current baseline — don't assume a
  count).
- For any route / data-structure removal, follow `CLAUDE.md`'s 15-step breakage
  check + 15-step verification + dead-code sweep.
