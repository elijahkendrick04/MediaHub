# 1. Replace the enum-permutation generation engine with a design-spec director

- **Status:** Accepted — partially implemented. The parallel bucket (PAR-1 →
  PAR-8) and the spine through Tier A (SEQ-0, SEQ-1) are shipped: the
  12-archetype `layouts/v2` library with the deterministic seeded picker is the
  **production default**, with `MEDIAHUB_GEN_V2=0` as the kill-switch back to
  the legacy engine. The design-spec director + pool/rank/compliance (SEQ-2),
  the enum/menu-picker removal (SEQ-3) and video scene structure (SEQ-4)
  remain to be built. *(Status updated 2026-06-09.)*
- **Date:** 2026-05-21
- **Deciders:** MediaHub maintainer
- **Context source:** [`../research/mediahub-generative-ai-thesis.md`](../research/mediahub-generative-ai-thesis.md)
  (§4A for rejected alternatives, §5 for the surgery); architecture in
  [`../GENERATION.md`](../GENERATION.md).

## Context

A "click generate" on a card produces "a pretty standard boring graphic every
time, that isn't unique every time you press generate." A line-by-line reading of
the generation code (thesis §2) shows exactly why:

- `creative_brief/generator.py` defines variation as a tuple drawn from a bounded,
  hand-authored option space — ~6 layout families plus cosmetic axes (10
  background SVGs, 8 accents, 6 type pairs, 4 compositions, 6 photo treatments, 6
  palette-role rotations). On paper that is ~400k combinations.
- But the only *structural* axis is `layout_family`, and there are only six —
  most achievement cards funnel into `individual_hero` or `big_number_hero`. The
  renderer (`graphic_renderer/render.py`) repaints **one DOM**: backgrounds are
  interchangeable data-URIs, type pairs are CSS `!important` overrides, accents
  are absolutely-positioned overlays, compositions are CSS retargets of the same
  element. So the cosmetic axes change the *paint*, not how the card *reads*.
- `creative_brief/ai_director.py` constrains the LLM to **return strict JSON whose
  every field is one of the fixed enums** ("never propose a value outside the
  listed vocabulary"). The LLM is a *menu-picker*, not a designer — "AI-directed"
  and "random" produce the same class of output. When no provider is configured,
  the system degrades to pure random tuple selection.

The result: two generations of the same swim read as the same card with different
paint. This fails three of the five jobs-to-be-done — distinctive (#1), ranked
options (#4), every format (#5) — while the moat (true + explainable, #3) is
strong and must be preserved.

The companion field study (16 clusters, 10-agent verification) found the 2026
field has converged on a different and better pattern: **exact, brand-critical,
data-bearing content is rendered deterministically, with generative models
confined to art/mood and orchestrated by an LLM acting as art-director.** MediaHub
already does this for captions and is architecturally a bespoke version of the
programmatic-graphics industry (Bannerbear/Abyssale/Creatomate). It does not need
a pixel model to stop being boring; it needs the intelligence layer between its
data and its renderer — the layer those products built and MediaHub skipped.

Two project rules constrain *how* this is fixed: CLAUDE.md forbids casually
removing routes/data structures production depends on (so "removal" means ripping
out the variation mechanism behind a stable interface, not deleting the route or
renderer), and the "no fake fallback" rule (an honest error beats a fabricated
caption) extends to graphics — a missing director falls back to a real
deterministic card, never a broken or invented one.

## Decision

Replace the **enum-permutation variation mechanism and the menu-picker prompt**
with a **design-spec director over a layout-intelligence layer**, keeping the
deterministic engine, the renderer substrate, and the captions. Concretely, insert
four layers between the data and the renderer (thesis §5, detailed in
[`../GENERATION.md`](../GENERATION.md)):

1. **A brand-token contract** (`DesignTokens`) — promote the flat `BrandKit` to a
   typed object with colour *roles* (each carrying `brightness` + `when_to_use`
   from the existing APCA/ΔE2000 maths), logo lockups by form/theme, type pairing,
   motion, and a structured voice profile. Additive: the old flat fields remain as
   derived aliases. Extends the Adaptive Theming Engine's `derived_palette`; does
   not fork it.
2. **An archetype library + layout intelligence (Tier A)** — 12–20 structurally
   distinct, token-driven templates under `graphic_renderer/layouts/v2/` (authored
   to a fixed slot convention), plus auto-fit text, saliency-aware crops, and
   ranker-sourced data-emphasis variation. Fully deterministic, ~$0 marginal cost;
   expected to fix "samey" on its own.
3. **An LLM design-spec director (Tier B)** — the LLM emits a schema-constrained
   `DesignSpec` (archetype, colour-role assignment, hero stat, generated hook, crop
   intent, mood, `rationale`) that the renderer executes deterministically. Every
   field is an enum, a token *role*, or generated copy — so a hallucination
   normalises to a legal card. The LLM never renders a pixel or an exact hex.
4. **Pool, rank, and a deterministic brand-compliance check** — emit N candidate
   specs, render the pool, score each against APCA/ΔE2000 contrast + correct logo
   lockup + sponsor-safe zones, rank with the existing ranker, and return an
   explainable shortlist.

The whole change is gated behind `MEDIAHUB_GEN_V2` (default off), with the
deterministic archetype-picker as the fallback floor. Captions are *extended* (few-
shot, generate-many-dedupe, per-platform, approval loop), not replaced. Video
*inherits* the richer brief and gains data-driven scene structure; generative art
is opt-in behind a second flag. Only at the SEQ-3 cutover — after v2 wins an A/B in
the review UI and the suite is green — is the dead enum/menu-picker code removed,
via CLAUDE.md's gated-removal process.

**The dividing line is fixed:** the data layer (names, times, PB badges, colours,
logo) stays deterministic and accurate (the moat); the direction layer (archetype,
emphasis, crop, hook, mood) becomes generative; the art layer (backgrounds) is
optionally generative. No non-deterministic model ever touches the data.

## Alternatives considered

Per thesis §4A, five plausible alternatives were considered and rejected:

1. **End-to-end generative graphics (an image model paints the whole card).**
   *Rejected.* No diffusion model reliably renders exact text/numbers (intrinsic to
   pixel-space generation, not a version-bump fix); text-leaders plateau at "good
   for short headlines" with a 5–10% defect rate on multi-field strings. For a
   product whose value *is* accuracy, a card that occasionally shows the wrong time
   is categorically unacceptable — it would destroy the moat (#3) to chase the
   polish (#1). The single most important rejected path.

2. **Buy a programmatic-graphics API (replace `render.py` with
   Bannerbear/Abyssale).** *Rejected.* They are architecturally identical to what
   MediaHub already owns (same headless-render core); MediaHub would pay a
   per-image metered tax forever to rent capabilities (auto-fit, smart crop) it can
   build once on its existing substrate, and would lose the tight coupling to its
   own brief/token/ranker objects. Buy the *patterns*, not the API.

3. **Switch video from Remotion to a managed API (Creatomate/Shotstack).**
   *Rejected.* Remotion's economics (free ≤3 people, $100/mo at 4+, ~$0.017/min
   compute) beat the metered alternatives at scale, and only code-based Remotion
   supports data-driven scene structure (a 5-PB weekend ≠ a single medal).
   Migrating would be costly rework that loses capability.

4. **Generative video as the default reel engine (Veo/Sora paint the reel).**
   *Rejected as default, kept as premium.* ~$6–11 per 15s reel, non-deterministic
   and re-roll-prone, plus the text-accuracy failure — ruinous as a default for a
   multi-tenant SaaS. Retained only as an opt-in, premium-priced B-roll layer under
   deterministic text.

5. **Fine-tune a custom model per club (à la Adobe Custom Models).** *Rejected for
   now.* These are visual-*style* fine-tunes on 10–30 images, not brand-*rule*
   reasoning, with vendor lock-in and a per-club training cost that does not fit a
   long-tail-of-clubs business. The token-contract + few-shot approach achieves
   on-brand output with no training, no lock-in, and per-club cost of zero.

The throughline: buy commodity *capability patterns*, build the *intelligence and
the contract*, rent generative *art* only where it is safe and cheap, and never
let a non-deterministic model touch the data. Every rejection protects either the
moat (accuracy/explainability) or the unit economics.

## Consequences

**Positive**

- Fixes the stated problem: structural distinctiveness rises from ~1–2 archetypes
  per pack to ≥6; one card yields a ranked pool of ≥4 distinct candidates instead
  of one.
- Brand fidelity becomes a contract, not a coat of paint: the deterministic
  compliance check catches off-brand candidates before a human sees them (target
  ≥99% pass-rate on shipped candidates).
- The director's `rationale` extends the existing explainability surface, so design
  *judgement* becomes auditable — widening the moat rather than bypassing it.
- Cheap: marginal generation cost is cents per pack (~$0.15–0.50), ~90%+ gross
  margin; the dominant cost is human (authoring archetypes), not compute.
- Tier A is independently valuable, deterministic, and ships first — de-risking the
  whole plan, since it requires no LLM at all.
- Captions and video inherit the lift from the richer brief with little extra work.

**Negative / costs**

- Authoring 12–20 archetypes is the long pole (~4–8 weeks). *Mitigation:* start
  with 12 and grow; the slot convention lets archetypes be authored in parallel,
  one file each.
- LLM layout judgement is uneven. *Mitigation:* a tight archetype vocabulary,
  schema-constrained decoding, the deterministic floor, and the
  pool-rank-compliance filter catching poor specs before a human sees them.
- A second feature flag (`MEDIAHUB_GEN_BG`) and the staged spine add temporary
  complexity until the SEQ-3 cutover removes the dead path.
- Brand auto-extraction is inaccurate for small clubs. *Mitigation:* always a
  draft for human confirmation, never auto-trusted.

**Neutral**

- The create-graphic route, the `CreativeBrief` dataclass, `render_html_to_png`,
  the asset pipeline, and Remotion are extended behind their existing signatures —
  not deleted. The SEQ-3 removal of `random_variation_profile`,
  `_legacy_axes_from_seed`, `_PHRASE_TABLES`/`_phrase_for_seed`, and the
  closed-vocabulary `_system_prompt` is the only structural deletion, and it
  follows CLAUDE.md's gated-removal process (15-step breakage check + 15-step
  verification + dead-code sweep).
- Rendered data accuracy and the "why this card" explanation are unchanged —
  explicitly preserved as the moat.
- Caching behaviour is preserved by seeding the director and caching the *spec*
  (not just the PNG).
