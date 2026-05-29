# Content generation quality ("worth paying for")

## The "samey" problem and the right fix

The standing complaint is that generation produces "a standard boring graphic
every time". The fix (ROADMAP §1.7) is **variety that stays exact and
on-brand**: a richer archetype / layout library, layout intelligence (auto-fit,
saliency crops, varied data-emphasis), and an LLM *design-spec director* that
emits a structured spec a **deterministic renderer executes** ("AI judges, maths
renders") — then generate-a-pool, rank, and run a deterministic
brand-compliance check.

Do **not** "fix samey" by switching to generative pixels: that trades exactness,
brand fidelity, and truth (the moat) for variety. For results content, variety
must never cost correctness.

Relevant files: `creative_brief/generator.py`, `creative_brief/ai_director.py`,
`creative_brief/design_spec.py`, `graphic_renderer/render.py`.

## Captions

Captions are the strongest generative surface and go through the Gemini →
Anthropic path (`web/ai_caption.py`). Keep them brand-voiced (few-shot from the
club's own approved captions), de-duplicated, per-platform, HTML-escaped on
output via `_h()`, and free of AI-tell phrases. Edited-and-approved captions
feed back as future few-shot examples.

## Explainability

Every generated output should be explainable: "why this card?", confidence
scores, and a brand-compliance / quality trace. Preserve the audit trail — it is
a product principle, not a nicety.
