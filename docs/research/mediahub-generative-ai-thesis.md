# Making MediaHub's Generative Content Worth Paying For

**A diagnosis of why "click generate" produces a boring, repeating graphic — and a surgical plan, grounded in the actual code, to replace the generation system with a genuinely generative one without sacrificing the deterministic, explainable engine that is MediaHub's moat. With a full cost model.**

**Date:** May 2026
**Companion documents:** `docs/research/generation-engine-competitor-evaluation.md` (how the 2026 field generates content, mechanism by mechanism — read first); `docs/ROADMAP.md` (the product roadmap, with the build-prompt appendices).
**Status:** research + plan. No code is changed by this document; it specifies the surgery and its cost for review before implementation.

---

## 0. Methodology and evidence base

This thesis is built on three evidence streams, deliberately kept separable so a reader can weight each appropriately:

1. **A direct reading of MediaHub's generation code** — `web/web.py` (the create-graphic route ~line 18242), `content_pack_visual/integration.py` (the per-card pipeline), `creative_brief/generator.py` and `creative_brief/ai_director.py` (the variation engine and the LLM director), `graphic_renderer/render.py` (the HTML→PNG renderer and its hand-authored primitives), `web/ai_caption.py` (the caption surface), and `visual/motion.py` (the Remotion path). Every claim in §2 cites a file and symbol; the diagnosis is grounded in what the code *actually does*, not in the product's self-description.
2. **A 16-cluster competitor study** (the companion `generation-engine-competitor-evaluation.md`), in which sixteen research agents each examined a slice of the 2026 field — design platforms, image/video models, programmatic engines, ad-creative tools, social suites, caption/brand-voice tools, brand-as-data systems, generative-layout research, sports-content automation, and bleeding-edge startups — against live web sources, separating vendor marketing from verified fact.
3. **A 10-agent verification pass** that independently re-checked the evaluation's load-bearing claims and whose corrections are folded into both documents (summarised in §9). Where a number could not be confirmed against a primary source it is flagged; where a structural claim survived independent checking it is relied upon.

The epistemic posture is the one MediaHub's own product demands: **trust the architecture, verify the numbers.** The structural conclusions (deterministic data layer, layout-intelligence gap, tokens-as-contract, pool-and-rank, Remotion-as-spine) are cross-checked and robust; specific prices and model versions are May-2026 snapshots to be re-verified at implementation. No claim that drives a removal or a spend decision rests on an unverified figure.

## 1. The problem, stated precisely

The brief is blunt and correct: *"the current click-to-generate generates a pretty standard boring graphic every time, that isn't unique every time you press generate."* This document does three things. First, it diagnoses **exactly why** that happens, grounded in a line-by-line reading of MediaHub's generation code rather than speculation. Second, it specifies the **surgery** — what to remove from the hard code and soft code, what to keep, and the replacement architecture, sequenced so the product never goes dark. Third, it builds a **cost model** — per card, per club, at scale — so the decision is made with eyes open.

The companion evaluation establishes the industry context and one liberating conclusion that governs everything here: **the field has decided that exact, brand-critical, data-bearing content is rendered *deterministically*, with generative models confined to art/background/mood and orchestrated by an LLM acting as art-director.** MediaHub already does exactly this for *captions* and is architecturally a bespoke version of the entire programmatic-graphics industry (Bannerbear, Abyssale, Creatomate). It does **not** need a pixel model to stop being boring; it needs the *intelligence layer between its data and its renderer* — the layer those mature products built and MediaHub skipped. The whole surgery follows from that.

### 1.1 What "worth paying for" actually requires

The companion evaluation's job-to-be-done analysis (§1A there) decomposes the buyer's need into five components; restating them here as the acceptance criteria the surgery must hit:

1. **Distinctive** — output that doesn't look like a template a follower can recognise. *Currently failing.* A card that looks identical every week signals "automated tool" and devalues the achievement, suppressing the reposts that are a club's entire distribution mechanism.
2. **Unmistakably on-brand** — right colours, right logo lockup for the background, club voice. *Partially working* (brand colours/logo are applied; lockup-by-context and a brand-compliance check are missing).
3. **True and explainable** — no wrong time, no hallucinated PB, with "why this card?" provenance. *Working, and it is the moat.*
4. **Ranked options, fast** — a shortlist of genuinely different, on-brand, accurate candidates to choose from. *Currently failing* — MediaHub emits one graphic.
5. **Every format I post** — feed, story, reel, multi-photo in one action. *Partially working* (multi-format render exists; the variety within it is thin).

The defensible willingness-to-pay concentrates on #3 (where MediaHub is strong); the "not worth paying for" feeling originates in #1, #4, #5. **The surgery is therefore aimed squarely at distinctiveness, ranked options, and format breadth — built on top of, not instead of, the truth-and-explainability engine.**

---

## 2. Exactly what MediaHub does today — the diagnosis, grounded in code

This section is deliberately concrete. Every claim is tied to a file and a mechanism, because a vague diagnosis produces a vague fix.

### 2.1 The end-to-end pipeline

A "click generate" on a card hits `POST /api/runs/<run_id>/cards/<card_id>/create-graphic` (`src/mediahub/web/web.py:18242`). The route:

1. **Decides the variation** (`web.py` ~18388–18423): if `?stable=true`, it derives a deterministic seed from the card id via `auto_variation_seed_for(card_id)`; if `?variation_seed=N`, it forces that seed; otherwise it builds a fresh `random_variation_profile(angle)` and sets `ai_directed=True`.
2. **Calls `create_visual_for_item()`** (`src/mediahub/content_pack_visual/integration.py:123`), which runs the pipeline for one card:
   - **(a) Requirements evaluation** — `media_requirements.evaluator.evaluate()` (deterministic; decides which assets/photos are available and whether confidence is high enough).
   - **(b) Creative brief** — `creative_brief.generator.generate()` (`generator.py:195`) builds a `CreativeBrief`, optionally asking the AI director for direction.
   - **(c) Render** — `graphic_renderer.variants.render_all_formats()` fills the chosen HTML template and screenshots it to PNG(s) via Playwright/Chromium.
   - **(d) Persist** — writes the PNG + a JSON sidecar.
3. **Returns** JSON with the brief, the visuals, the `variation_seed`, `ai_directed`, and an explanation.

Captions are a *separate* surface: `POST /api/runs/<run_id>/swim/<swim_id>/caption` → `web/ai_caption.py:generate_caption_for_tone()` → the LLM via `ai_core`. Video is a third surface: `visual/motion.py` shells out to Remotion. The three surfaces do not share a generation engine; they share only the `BrandKit` and the per-card `variation_seed`.

### 2.2 The variation engine — and the precise reason output is "samey"

The heart of the matter is `creative_brief/generator.py`. It defines a `VariationProfile` (line 116) with what *looks* like a rich eight-axis variation surface:

- `layout_family` — one of **6–7 hand-authored families** (`_GENERIC_FAMILIES`, line 907: `individual_hero, big_number_hero, text_led_recap, weekend_numbers, athlete_spotlight, story_card`; plus `medal_card`).
- `palette_role_index` — one of **6 fixed permutations** of the club's three brand colours (`_PALETTE_PERMUTATIONS`, line 803). *Colours never change — only which colour plays primary/secondary/accent rotates.*
- `background_style` — one of **10 hand-authored SVG patterns** (`BACKGROUND_STYLES`, line 56: water, halftone, diagonal, radial, geometric, clean, stripes, dots, duotone, grain).
- `accent_style` — one of **8 hand-coded decorations** (`ACCENT_STYLES`, line 72: brackets, stripe, badge, frame, minimal, ribbon, arrow, underline).
- `typography_pair` — one of **6 hand-written CSS override blocks** (`TYPOGRAPHY_PAIRS`, line 86).
- `composition` — one of **4** (right/left/center/off-center).
- `photo_treatment` — one of **6** (cutout/vignette/duotone/frame/halftone/no-photo).
- `decoration_strength`, `hook_phrase`, `mood`.

On paper that is ~6 × 6 × 10 × 8 × 6 × 4 × 6 ≈ **414,720 combinations** — which makes "it's not unique" sound wrong. It is not wrong, for two precise reasons the ad-creative industry illuminates:

**Reason 1 — the axes that vary are cosmetic, not structural.** Swapping the background SVG from "halftone" to "dots," or the accent from "brackets" to "underline," does not change how the card *reads*. The eye registers the same **six layout skeletons**, because the `layout_family` is the only *structural* axis and there are only six of them — and most achievement cards funnel into `individual_hero` or `big_number_hero`. The renderer (`graphic_renderer/render.py`) confirms this: backgrounds are interchangeable data-URIs plugged into one CSS variable (`_background_pattern_for`, line 360), typography pairs are CSS `!important` overrides on the same DOM (`_TYPOGRAPHY_OVERRIDES`, line 385), accents are absolutely-positioned overlay `<div>`s (`_accent_decoration_html`, line 434), and compositions are CSS retargets of the same `.athlete-wrap` element (`_composition_overrides_css`, line 510). **It is the same card with different paint, not a different card.** Perceived distinctiveness lives in *layout/composition*, where there is almost no variety.

**Reason 2 — the AI is a menu-picker, not a designer.** When `use_ai_director=True`, `generator.py` calls `ai_director.ai_creative_direction()` (`ai_director.py:235`). Reading that function: it asks Gemini/Claude to **return STRICT JSON whose every field is constrained to the fixed enums above** (`_system_prompt`, line 126 — "Never propose a value outside the listed vocabulary"). The LLM cannot invent a layout, a composition, a background, or a colour. It can only *select a tuple from the same small Cartesian product the random picker draws from.* So "AI-directed" and "random" produce the **same class of output** — a permutation of six skeletons in different paint. The one genuinely generative thing the director contributes is the `hook_phrase` (a short headline) and `mood` word; everything else is a constrained pick. And when no provider is configured, the system silently degrades to `random_variation_profile()` (line 931) — pure random tuple selection.

**Reason 3 (compounding) — first-hit bias.** A club rendering ~10 cards/week never explores the exotic tail of even the cosmetic space; the *modal* tuple dominates, so successive generations look like minor reskins. The recent-signature dedupe (`generator.py:976`, tries 12 times to avoid the last 6 signatures) prevents *exact* repeats but not *family* repeats — two `individual_hero` cards with different backgrounds still read as "the same card."

**Traced concretely — what actually differs when you press generate twice on the same swim.** Take Hannah's 100m Freestyle PB. Click one: the picker lands on `individual_hero`, palette-role 2, background `halftone`, accent `brackets`, fonts `anton-inter`, composition `right`, hook (from `_PHRASE_TABLES`) "PERSONAL BEST." Click two: the dedupe avoids that exact signature, so it lands on `individual_hero` (again — there are only six families and this angle favours it), palette-role 4, background `dots`, accent `underline`, fonts `oswald-inter`, composition `right`, hook "BEST EVER." To the *system*, those are two different signatures — mission accomplished. To the *swimmer's eye*, they are the same card: surname behind, athlete on the right, time in a chip, logo bottom-left — with the dots slightly different from the halftone and a marginally different headline. The *structure* — the thing the eye reads — is identical, because `layout_family` barely moved and the renderer painted the same DOM. That is the gap between "technically a different signature" and "actually looks fresh," and it is why the user's complaint is correct even though the option-space is, on paper, enormous.

**This is the complete, code-level diagnosis: MediaHub's "generation" is the selection of a tuple from a bounded, hand-authored option space dominated by ~6 layout skeletons, with an LLM that can only pick from that menu and a renderer that only repaints one DOM. There is no generative *design*; there is parameterised reskinning.** That is precisely why it feels boring and non-unique, and it is exactly the failure mode the companion evaluation documents even in Canva (template-bound sameness) and Predis ("looks like every other account").

### 2.3 What is actually good and must be preserved

The diagnosis is not "MediaHub's generation is bad." Three parts are genuinely strong and the surgery must protect them:

- **Captions (`web/ai_caption.py`)** are the one truly generative surface and are well-built: 100% LLM (Gemini-primary, Claude-failover via `ai_core`), **no fake template fallback** (raises `ClaudeUnavailableError` — an honest error beats a fabricated caption, per the project's standing rule), with tone descriptors, brand-DNA injection (`brand.context.brand_context_for_llm`), a learned voice profile (`_voice_profile_prose`), recent-caption de-duplication, and an anti-cache nonce. This is roughly *where the field is* and needs extension, not replacement.
- **The deterministic engine** — parsing (HY3/SDIF/PDF), PB/achievement detection, the 7-factor ranker, and colour-science (the DTCG `derived_palette`, ΔE2000/APCA logo-chip logic in `theming/`) — is the moat and is correctly deterministic. The render mechanism itself (`render.py`: HTML→PNG via Playwright, network-free with base64-embedded assets) is the *correct* architecture, identical to the programmatic-graphics industry's.
- **The motion path (`visual/motion.py`)** already threads the brief's variation axes into Remotion compositions and caches by content hash — architecturally sound; it inherits the *same* "thin variety" problem from upstream (it can only forward the six-skeleton axes it is given), so fixing the brief fixes the video too.
- **A dormant generative hook already exists**: `render.py:1131` imports `mediahub.visual.ai_background` (Replicate-gated, off unless `REPLICATE_API_TOKEN` is set) to optionally generate a brand-aware background. This is a real foothold for Tier C.

---

## 3. The gap, surface by surface

Mapping MediaHub against the field (full evidence in the companion evaluation) yields an asymmetric gap:

| Surface | Field's best practice | MediaHub today | Gap size |
|---|---|---|---|
| **Caption** | LLM + few-shot real examples + facts/style split + generate-many-then-rank + per-platform variants + approval-loop learning + off-brand flag | LLM with voice profile, brand DNA, recent-caption dedupe, honest-error | **Small** — extend, don't replace |
| **Graphic** | Deterministic render + layout-intelligence (auto-fit, saliency crop, archetype library) + LLM design-spec direction + tokens-as-constraint + ranked pool + compliance check | 6 hand-authored skeletons, LLM menu-picks cosmetic axes, one output | **Large** — the priority for surgery |
| **Video** | Programmatic compositor for data + generative B-roll under accurate overlays + data-driven scene structure | Remotion, forwards the same thin axes, cached | **Medium** — enrich, don't rebuild |

The headline: **the work is concentrated on the graphic surface; the caption surface needs incremental extension; the video surface is architecturally correct and inherits its fix from the graphic surface.** None of it requires surrendering the deterministic data layer.

---

## 3A. Is MediaHub really "far behind"? A calibrated verdict

The brief states the worry plainly: *"I am very far behind competitors when it comes to the generative AI graphic/video/caption generation."* That feeling is half-right, and the half it gets wrong is the more important half. A calibrated answer, separating the *generation-polish* layer from the *intelligence* layer:

**Where MediaHub genuinely is behind (the polish layer):**
- **Graphic distinctiveness and layout intelligence** — far behind. It has six structural skeletons and no auto-fit, smart-crop, or design-system; Bannerbear/Abyssale/Canva have all of it. This is the real source of "samey," and it is the most visible gap.
- **Ranked-options UX** — behind. It emits one graphic; AdCreative/OpusClip/Anyword emit a scored pool.
- **Multi-format breadth and distribution** — behind. The social suites (Predis/Ocoya) generate carousels/video and schedule to many channels; MediaHub stops at approval/export.
- **Brand-as-data depth** — behind. Three colours + one logo vs Brandfetch/Frontify's typed brand systems and Adobe's compliance scoring.
- **Real-time / agentic UX** — behind the bleeding edge (Krea's live canvas, Lovart's campaign agents).

**Where MediaHub is at parity (the surfaces it already did well):**
- **Captions** — roughly at the field's level (LLM, voice profile, brand DNA, honest-error). Needs few-shot + pool-and-dedupe polish, not a rebuild.
- **Video architecture** — Remotion is the *correct, verified-cheapest* choice; the gap is upstream richness, not the engine.

**Where MediaHub is *ahead* of the entire field (the intelligence layer — the expensive, defensible part):**
- **Data-grounded moment detection** — it turns a raw HY3/SDIF/PDF into "this is a PB / a first sub-60 / a county qualifier." *No generalist generator does this*, and the verification pass confirmed *no swim-data platform does it either*. FanWord does storyline detection but for college *written* recaps; WSC/Spiideo detect from *video*, not structured results.
- **Content-worthiness ranking + explainability + accuracy** — the deterministic ranker, confidence scores, "why this card," and source-grounding. The generalists *cannot* offer this from a vague prompt and would hallucinate it.
- **The *combination*** — structured-data ingestion → detection → ranking → branding → generation → approval, for grassroots clubs. Nobody else has the whole chain for this buyer.

**The verdict that matters:** MediaHub is behind exactly where catching up is *cheap and well-understood* (layout intelligence is weeks of deterministic engineering — Tier A) and ahead exactly where catching up is *expensive and slow* (a deterministic, accurate, explainable sport-data engine takes years and domain knowledge to build well). **That is a strong position misread as a weak one.** A competitor looking at MediaHub has to build the hard intelligence layer from scratch; MediaHub looking at competitors has to build a layout-variation layer that the programmatic-graphics industry has already commoditised and documented. The strategic error would be to panic about the visible polish gap and neglect the invisible moat; the correct move is to close the cheap gap fast (the surgery below) while widening the expensive one.

## 3B. MediaHub vs the field, mechanism by mechanism

A comparative reading of *what MediaHub does* against *what each competitor cluster does*, with the strategic implication for each. This is the comparison the brief asks for — grounded in the companion evaluation's mechanism map and the verification pass.

**vs. Design platforms (Canva, Adobe).** *They:* generate from a prompt — Canva's Design Model emits layered, editable output; Adobe GenStudio mass-produces brand-constrained variants and scores each for compliance (verified: a % via Azure OpenAI). *MediaHub:* fills one of six fixed templates and screenshots it; no layering, no editability, no compliance score. *Behind on:* generative breadth, editable output, brand-compliance scoring. *Ahead on:* Canva/Adobe start from a blank prompt and a human who must know what to make; MediaHub starts from *verified, ranked facts*. *Implication:* steal two specific mechanisms — Adobe's per-variant brand-compliance score (but compute it *deterministically* via MediaHub's existing contrast/logo gates, not a second LLM) and Canva's "emit structured, editable layers, not a flat PNG" — and decline to chase Canva's general-purpose design surface, which is not MediaHub's job.

**vs. Programmatic engines (Bannerbear, Abyssale, Creatomate — MediaHub's literal architectural twin).** *They:* fill named-layer templates and render headless, exactly like MediaHub, but add auto-fit text, smart/saliency crop, face detection, Smart-Layers auto-reflow, and a *library* of templates. *MediaHub:* the identical render core, none of the layout intelligence, six templates. *Behind on:* precisely those layout-intelligence features — and nothing else; the render substrate is the same (verified: HCTI is "exactly like Chrome," which is what MediaHub's Playwright path is). *Ahead on:* these tools have *zero* content intelligence — you must tell them what to render. *Implication:* **this is the cheapest, most direct catch-up in the entire analysis** — adopt auto-fit + saliency crop + an archetype library and MediaHub *is* a sport-aware Bannerbear, which is a strong place to be. Tier A of the surgery is exactly this.

**vs. Ad-creative engines (AdCreative, Smartly, Arcads, Icon).** *They:* ingest a brand kit + a data feed and generate *many* on-brand variants via a combinatorial matrix (layout × colour-role × crop × hook × CTA), then *rank* them by a predicted-performance score and surface a shortlist. *MediaHub:* generates one variant, no matrix, no ranking of visual options. *Behind on:* variation breadth and the generate-pool-then-rank pattern — the single biggest cause of "samey" relative to this cluster. *Ahead on:* their "feed" is a product catalogue; MediaHub's "feed" is *ranked meaningful moments* (a PB, a first medal) — inherently more distinct source material than "blue running shoe, $89." *Implication:* adopt the combinatorial matrix + pool-rank wholesale (it maps onto MediaHub's existing ranker), and exploit the fact that MediaHub's variants are about genuinely different *real events*, so its pool is more naturally diverse than an ad tool permuting one product.

**vs. Social suites (Predis, Ocoya, Simplified).** *They:* one prompt → caption + carousel + reel + schedule, end-to-end. *MediaHub:* generate + brand + approve, stopping before scheduling, and only one graphic. *Behind on:* multi-format breadth (carousels, native video) and integrated scheduling/distribution. *Ahead on:* data intelligence and explainability — and tellingly, Predis is *documented as samey* ("looks like every other account"; verified critique), the exact weakness MediaHub shares. *Implication:* MediaHub and Predis have the *same* sameness problem, but MediaHub can fix it from a position of strength — its source material is genuinely differentiated real moments, not generic prompts — while adding the table-stakes breadth (multi-format) and, later, optional scheduling. The companion business dissertation covers the distribution/scheduling roadmap; this thesis focuses on making the *generation* worth distributing.

**vs. Caption & brand-voice tools (Jasper, Copy.ai, Lately).** *They:* model brand voice via few-shot examples, facts/style separation, engagement-loop learning, and generate-many-then-rank. *MediaHub:* already does LLM captions with voice profiles, brand DNA, recent-caption dedupe, honest-error — genuinely close. *Behind on:* few-shot-from-the-club's-own-posts, per-platform variants, and an approval-feedback loop. *Ahead on:* captions are grounded in *verified achievement data*, so they can be specific and true in a way a generic brand-voice tool cannot. *Implication:* this is the *one surface that is not far behind* — extend it (§5.6), don't rebuild it. Verification confirmed the cheap recipe (few-shot beats adjectives; facts/style split; generate-many-dedupe).

**vs. Sports-automation incumbents (WSC, Gipper, Content Stadium, FanWord, Spiideo).** *They:* WSC/Spiideo auto-generate highlights from *video feeds* (enterprise); Gipper/Content Stadium provide *manual* branded templates (a human types the score); FanWord detects storylines for *written* college recaps. *MediaHub:* the only one combining structured-results ingestion → automated moment detection → branded *graphic* generation → approval, for *grassroots* clubs. *Behind on:* Gipper's template library/polish and Content Stadium's data-provider integrations. *Ahead on:* the *combination* — verification confirmed nobody else does data-driven branded content for grassroots from results files. *Implication:* the moat is the *whole chain*, not any single link; defend it by making the generation excellent (this surgery) and by adopting an integration posture toward swim-data incumbents (the real threat) so MediaHub ingests their exports rather than competing on data custody.

**vs. Bleeding-edge agents (Lovart, Genspark, Krea, Hedra).** *They:* agentic multi-asset campaign generation from a goal; real-time iterative design. *MediaHub:* a batch pipeline. *Behind on:* agentic UX and real-time iteration. *Ahead on:* grounding — these agents start from a vague prompt and have no notion of "what actually matters"; MediaHub starts from verified, ranked facts. *Implication:* frame MediaHub as a *vertical content agent* — "upload results → the agent detects the moments and produces a full branded pack" — which is the agentic pattern *with* the grounding the generalists lack. The design-spec director (Tier B) is the first step toward that agentic framing.

**The thread through every comparison:** MediaHub is behind on the *commoditised* layers (layout variation, multi-format, brand-as-data, agentic UX) and ahead on the *defensible* layer (grounded detection + ranking + explainability + accuracy). Every "steal" identified is a commodity capability with a known implementation; every "moat" is something the competitor would have to build from scratch. That asymmetry is the whole strategic case for the surgery: spend a few months buying back the commodity gap, and the result is a product that is both *as polished as* the generators and *more trustworthy than* any of them — which is exactly what makes generation worth paying for.

## 4. Strategic frame — what to build, what to buy, what never to compete on

Three strategic commitments shape the surgery; getting them right matters more than any single feature.

**4.1 The moat is the intelligence layer; the generation layer is commodity — so build the *bridge*, buy the *pixels*.** The verification pass confirmed the white space is real (no swim-data platform — SwimTopia, Hy-Tek, Swimcloud — auto-generates content or detects content-worthy moments as of May 2026) and confirmed the moat is narrow: deterministic parsing + PB/achievement detection + content-worthiness ranking + explainability. It also confirmed that raw generation is commoditising fast (Higgsfield/Krea/Pollo all wrap the same Sora/Veo/Kling). The strategic conclusion: **MediaHub must never compete on "which model we wrap." It builds the layer between its data and a renderer — the layout intelligence and the LLM art-direction — and treats every pixel/video model (Recraft, Bria, Veo, Flux) as an interchangeable, swappable backend behind that layer.** This is the same posture as its existing Gemini→Anthropic caption failover, extended to imagery.

**4.2 Deterministic where it must be true; generative where it must be fresh.** The single principle that resolves every design tension: the *data layer* (names, times, PB badges, brand colours, logo) is rendered symbolically and deterministically (accurate, on-brand, cheap, explainable — the moat); the *direction layer* (which archetype, which emphasis, which crop, which hook, which mood) is generative (the LLM art-director); and the *art layer* (backgrounds, textures, optional B-roll) is optionally generative via a commercial-safe API. This is MediaHub's own stated doctrine ("judgement through `media_ai.llm`; parsers/detectors/ranker/colour-science deterministic"), and the verification pass confirmed it is exactly where the best of the field has landed.

**4.3 Never go dark, and never lie.** Two project rules constrain *how* the surgery is done. First, CLAUDE.md mandates additive change and forbids removing routes/data structures that production depends on — so "full removal" of the current system means *ripping out the variation mechanism behind a stable interface*, not deleting the route or the renderer substrate the product runs on. Second, the "no fake fallback" rule (an honest error beats a fabricated caption) extends to graphics: if the new director is unavailable, the system falls back to a *real* deterministic archetype, never to a fabricated or broken card. The surgery is therefore staged behind a feature flag with a deterministic floor, so production never regresses.

**4.4 A note on the build-vs-buy boundary, with corrected economics.** The verification pass firmed up the numbers that decide this:
- **Keep Remotion for video** (licence figures verified exact: free ≤3 people, $100/mo Automators floor at 4+, ~$0.017/min Lambda compute) — it is cheapest at scale and uniquely supports data-driven scene structure. Managed alternatives (Creatomate verified at ~$41/$99/$249/mo, Shotstack $0.30/min) are a metered tax that worsens with success.
- **Keep the Playwright HTML→PNG renderer** — it is the same architecture as Bannerbear/HCTI and is already paid for.
- **Buy generative imagery only at the art layer**, and only from a commercial-safe API (Bria, ~$0.08/image, licensed-data + indemnity) or a brand-controlled one (Recraft, vector + palette input) — never from a model that would render the data text.

---

## 4A. Alternatives considered and rejected

A thesis should show its work on the paths *not* taken. Five plausible alternatives were considered and rejected, each for a concrete reason grounded in the evaluation and verification:

**(1) End-to-end generative graphics (an image model paints the whole card).** *Rejected.* The verification pass confirmed the core finding: no diffusion model reliably renders exact text/numbers (intrinsic to pixel-space generation, not a version-bump fix), and even text-leaders plateau at "good for short headlines" with a 5–10% defect rate on multi-field strings. For a product whose value *is* accuracy, a card that occasionally shows the wrong time is categorically unacceptable — it would destroy the moat (JTBD #3) to chase the polish (JTBD #1). This is the single most important rejected path.

**(2) Buy a programmatic-graphics API (replace `render.py` with Bannerbear/Abyssale).** *Rejected.* They are architecturally *identical* to what MediaHub already owns (verified: same headless-render core); MediaHub would pay a per-image metered tax forever to rent capabilities (auto-fit, smart crop) it can build once on its existing substrate, and would lose the tight coupling to its own brief/token/ranker objects. Buy the *features' design* (the patterns), not the API.

**(3) Switch video from Remotion to a managed API (Creatomate/Shotstack).** *Rejected.* Verification confirmed Remotion's economics (free ≤3 people, $100/mo at 4+, ~$0.017/min compute) beat the metered alternatives (Creatomate ~$41–249/mo, Shotstack $0.30/min) at scale, *and* only code-based Remotion supports data-driven scene structure (a 5-PB weekend ≠ a single medal). Migrating would be costly rework that loses capability.

**(4) Generative video as the default reel engine (Veo/Sora paint the reel).** *Rejected as default, kept as premium.* Verified cost (~$6–11 per 15s reel, non-deterministic, re-roll-prone) plus the text-accuracy failure makes it ruinous as a default for a multi-tenant SaaS. It is retained only as an opt-in, premium-priced B-roll layer under deterministic text.

**(5) Fine-tune a custom model per club (à la Adobe Custom Models).** *Rejected for now.* Verification confirmed these are visual-*style* fine-tuning on 10–30 images, not brand-*rule* reasoning, with vendor lock-in and a per-club training cost that does not fit a long-tail-of-clubs business. The token-contract + few-shot approach achieves on-brand output with no training, no lock-in, and per-club cost of zero — the right fit for the grassroots model.

The throughline: **buy commodity *capability patterns*, build the *intelligence and the contract*, rent generative *art* only where it is safe and cheap, and never let a non-deterministic model touch the data.** Every rejection protects either the moat (accuracy/explainability) or the unit economics.

## 5. The surgery — removal, retention, and the replacement architecture

This is the core of the brief: *"heavily dissect how to integrate and make the generative AI work, in terms of surgery and taking the current system fully out of the website's hard and soft code."* Here it is, file by file. The guiding shape: **rip out the bounded-enum permutation engine and the menu-picker; keep the renderer substrate, the deterministic engine, and the captions; insert a brand-token contract, an archetype library, an LLM design-spec director, and a pool-rank-comply step in between.**

### 5.1 What is removed (the "full removal" of the current generation behaviour)

These are the parts that *cause* the boring/samey output and should be removed as the live generation path (retained only as a deterministic fallback floor, then deleted once the replacement is proven):

| Remove (file:symbol) | Why it's the problem | Disposition |
|---|---|---|
| `creative_brief/ai_director.py:_system_prompt` (the closed-vocabulary "return one of these enums" prompt) | Makes the LLM a *menu-picker*, not a designer — the root cause that "AI-directed" ≈ "random" | **Replace** with a design-spec emitter (§5.4) |
| `creative_brief/generator.py:random_variation_profile` + `_legacy_axes_from_seed` (random/seed tuple pickers) | "Variation" = random selection from cosmetic enums; produces reskins of 6 skeletons | **Delete** as live path; keep one deterministic archetype-picker as fallback floor |
| `generator.py:BACKGROUND_STYLES / ACCENT_STYLES / TYPOGRAPHY_PAIRS / COMPOSITIONS / PHOTO_TREATMENTS` as the *variation surface* | Cosmetic axes masquerading as variety; the eye sees the same skeleton | **Demote** to renderer-internal building blocks the *archetypes* compose, not the user-facing variation knob |
| `generator.py:_PHRASE_TABLES` + `_phrase_for_seed` (6 canned hook tables) | Hooks drawn from a fixed table read as templated | **Replace** with LLM-generated hooks (already partially done via `ai_fresh_hook`) |
| `generator.py:_PALETTE_PERMUTATIONS` as the *only* palette variation (6 role rotations) | Six rotations of three colours is not brand intelligence | **Supersede** with the token-role contract (§5.3); keep rotation as one tactic the director can invoke |
| The implicit "6 hand-authored `layouts/*.html` = the entire structural space" assumption | Only 6 structural skeletons → everything reads the same | **Replace** with a 12–20-archetype, token-driven library (§5.3) |

Note the honest framing of "full removal": the *mechanism* (enum permutation + menu-picker + phrase tables + 6-skeleton ceiling) is genuinely deleted from the live path. The *substrate* it ran on — the `CreativeBrief` dataclass, the route, `render_html_to_png`, the asset pipeline — is **extended, not deleted**, because production depends on it and CLAUDE.md forbids breaking it. Trying to literally delete the renderer or the route would be reckless and is not what "make the generative AI work" requires.

### 5.2 What is kept and protected (the moat and the substrate)

| Keep (file) | Role | Change |
|---|---|---|
| `recognition*/`, `pb_discovery/`, `legacy/swim_content_v5/ranker_v3.py` | Detection + ranking — the moat | **Unchanged** (deterministic, per project rule); *new* read: expose ranked *emphasis angles* (§5.3.4) |
| `theming/` (DTCG `derived_palette`, ΔE2000/APCA logo-chip) | Colour science | **Unchanged**; becomes the source of the token contract |
| `graphic_renderer/render.py:render_html_to_png` + asset pipeline (`_maybe_cut_out_athlete`, `_prepare_logo_data_uri`) | The render substrate (HTML→PNG, cutouts, logo prep) | **Kept**; the SVG/CSS primitives become archetype building blocks |
| `web/ai_caption.py` | The one strong generative surface | **Extended** (§5.6), not replaced |
| `visual/motion.py` + `remotion/` | Video compositor | **Kept**; inherits richness from the new brief (§5.7) |
| `web.py` create-graphic route + `content_pack_visual/integration.py:create_visual_for_item` | The pipeline contract | **Kept**; internals swapped behind the same signature |
| `media_library/selector.py:score_asset` | Deterministic photo pick | **Kept** (per project rule); feeds crop intent |

### 5.3 New Layer 1 — the brand-token contract (and bootstrapping it)

**Problem it fixes:** brand identity is applied as styling (3 colours + 1 logo), not as a machine contract a generator obeys — so output is on-brand-ish but not richly on-brand, and the generator has nothing structured to reason over.

**Build:** promote `BrandKit` (currently in `brand/kit.py`) to a typed **DesignTokens** object, modelled on Brandfetch's verified schema (the verification pass confirmed its shape):
- **Colour roles, not slots:** `brand`, `accent`, `surface`, `on-surface`, `sponsor-safe`, each carrying a `brightness` value (MediaHub's APCA/ΔE2000 already computes contrast — reuse it) so the director can pick the *right* colour for background vs text and the renderer can guarantee legibility.
- **Logo lockups by context:** replace the single `logo_svg` with `logos[]` typed by `theme` (light/dark) and `form` (icon/horizontal/stacked/mono) — a story card on a dark photo needs the light-knockout mono mark; a feed card needs the full lockup. `theming/logo_chip.py` already decides chip treatment; extend it to *select the lockup*.
- **Type pairing + motion tokens:** typed `title`/`body` fonts with a type scale; timing/easing tokens for Remotion.

**Bootstrap (onboarding):** add "paste your club website / Instagram → pre-fill your brand kit." MediaHub already has `brand/link_handlers/` (instagram/website/facebook/twitter/tiktok) and `link_learners/`; a Brandfetch call (verified API; free Logo tier; ~$99/mo for 100 brands paid) or the existing crawlers populate a **draft** the operator confirms (extraction accuracy for small clubs is poor — never auto-trust, per the human-approval rule).

**Wire it through:** the resolved token set is injected into *every* generator's context — the caption LLM (`ai_caption.py`), the new design-spec director (§5.4), and the Remotion brief — as explicit constraints. This is the "tokens-as-contract" pattern (verification flagged it as prevalent best-practice rather than a settled "consensus," and noted tokens need *semantic* naming + `when_to_use` metadata to be usable by an LLM — so the token object must carry role descriptions, not just hex).

The expanded `DesignTokens` object (extending today's flat `BrandKit`) sketches out roughly as:

```json
{
  "colours": {
    "brand":      { "hex": "#A30D2D", "brightness": 0.28, "when_to_use": "dominant ground / large fills" },
    "accent":     { "hex": "#FFD86E", "brightness": 0.86, "when_to_use": "highlights, chips, rules — never body text on light" },
    "surface":    { "hex": "#0B0B0C", "brightness": 0.05, "when_to_use": "panels behind text on photos" },
    "on_surface": { "hex": "#FFFFFF", "brightness": 1.00, "when_to_use": "text on brand/surface" }
  },
  "logos": [
    { "form": "full_horizontal", "theme": "light", "svg": "..." },
    { "form": "mono_light",      "theme": "dark",  "svg": "..." },
    { "form": "icon",            "theme": "any",   "svg": "..." }
  ],
  "type": { "title": "Anton", "body": "Inter", "scale": "1.25" },
  "motion": { "in": "spring(0.6,18)", "hold_ms": 1800, "out": "ease-out-200" },
  "voice": { "examples": ["…3 past captions…"], "banned": ["delve","elevate"], "emoji": "sparing" }
}
```

The `brightness` + `when_to_use` fields are what let the director (and the deterministic compliance check) pick the *legible* role for each slot — the difference between "applied a brand kit" and "obeys a brand contract." MediaHub's APCA/ΔE2000 maths already produces the brightness/contrast numbers; this just gives them a home the generators can read.

### 5.3.1 New Layer 2 — the archetype library + layout intelligence (Tier A, ship first)

**Problem it fixes:** only ~6 structural skeletons; cosmetic axes don't change how a card *reads*.

**Build (deterministic, no AI, brand-safe — the immediate win):**
1. **12–20 structurally distinct archetypes** replacing the 6 families — `hero-photo-left/stat-stack-right`, `full-bleed-photo/lower-third`, `editorial-numbers-grid`, `centered-medal-spotlight`, `split-diagonal`, `magazine-cover`, `ticker-strip`, `triptych`, etc. Each is a token-driven template (slots reference token *roles*, never hardcoded hex), authored on the existing `render.py` substrate. This is the single highest-ROI change (the evaluation's worked example: 8 new *structural* archetypes beat 10 new background textures).
2. **Auto-fit text** (Bannerbear's verified core feature) — text shrinks to its box so long names/events never break a layout; this is what lets one archetype absorb variable content gracefully.
3. **Saliency-aware crops** — produce multiple valid crops of a photo (tight portrait / rule-of-thirds action / wide); the archetype dictates which it consumes. Deterministic maths, consistent with the colour-science rule.
4. **Varied data-emphasis** — the ranker exposes a *ranked list* of emphasis angles (lead with time / PB delta / placing / relay split); the brief varies which is hero. Genuine freshness from MediaHub's own intelligence layer.

These combine combinatorially and are fully deterministic — so this tier ships *before* any LLM-direction work and fixes the stated "samey" problem on its own.

### 5.4 New Layer 3 — the LLM art-director emitting a design-spec JSON (Tier B, the strategic play)

**Problem it fixes:** the menu-picker can't design; it can only select a cosmetic tuple.

**Build:** rewrite `ai_director.ai_creative_direction` so that, given the card data + the DesignTokens contract + the archetype catalog (with semantic descriptions), the LLM emits a **structured design spec** under JSON-schema-constrained decoding — `archetype` (enum over the 12–20), `colour_role_assignment`, `focal_element`, `hero_stat` (chosen from the ranker's emphasis list), `headline_hook` (generated, not table-picked), `crop_intent`, `accent_treatment`, `motion_intent`. The renderer executes it deterministically. The LLM now makes *compositional judgements* (what to emphasise, how to arrange, what mood) — the thing it's good at — while never touching a pixel or an exact hex. This is exactly MediaHub's caption pattern applied to layout, and the pattern the verification pass confirmed as real research (PosterLlama, RALF, VASCAR all genuine) and emerging practice (Google's DESIGN.md — real, alpha). Keep a deterministic archetype-picker as the fallback floor when the provider is unavailable (the "no fake fallback" rule: a real simple card, never a broken one).

**Concretely, the design spec the director emits looks like this** (illustrative — the renderer consumes it deterministically; the LLM never positions a pixel):

```json
{
  "archetype": "split_diagonal_hero",
  "colour_roles": { "ground": "brand", "surface": "on-surface",
                    "headline": "surface", "accent": "accent-strong" },
  "focal_element": "athlete_cutout",
  "crop_intent": "rule_of_thirds_action",
  "hero_stat": "pb_delta",            // chosen from the ranker's emphasis list
  "secondary_stats": ["final_time", "event"],
  "headline_hook": "TWO SECONDS FASTER",   // LLM-generated, not table-picked
  "accent_treatment": "diagonal_underline",
  "logo_lockup": "mono_light",        // resolved against the dark ground
  "mood": "explosive",
  "motion_intent": "snap_in_then_settle",
  "rationale": "PB delta is the story; action crop + diagonal energy match the swimmer's drive."
}
```

Every field is either an enum the renderer knows, a token *role* (never a hex), or generated copy — so a hallucinated value normalises to a safe default and the output is always brand-legal. The `rationale` field feeds straight into the existing "why this design" explainability surface, so the director's *judgement* becomes auditable — extending the moat rather than bypassing it.

**The proposed archetype catalog (Tier A's deliverable)** — 12 to start, growing — gives the structural variety the six families lack. A starting set: `split_diagonal_hero`, `full_bleed_photo_lower_third`, `editorial_numbers_grid`, `centered_medal_spotlight`, `magazine_cover`, `ticker_strip`, `stat_stack_sidebar`, `triptych_progression`, `quote_led_recap`, `big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`. Each is authored once on the existing `render.py` substrate with token-role slots (not hardcoded colours), and each *reads* differently at a glance — which is the property the current background/accent/font axes do not provide. The director chooses among them; the deterministic floor rotates among them by seed when no provider is available.

### 5.5 New Layer 4 — generate a pool, rank, and brand-compliance-check

**Problem it fixes:** MediaHub emits one graphic; the field emits a ranked pool.

**Build:** the director produces **N candidate specs** (varying archetype/emphasis/crop/hook); render them (cheap — Playwright is near-zero marginal cost); run a **deterministic brand-compliance + legibility check** (contrast via the existing APCA/ΔE2000 gates; correct logo lockup for background; sponsor-safe zones) that attaches an explainable score to each (Adobe GenStudio's verified per-variant brand-% score, but computed *deterministically* here rather than via a second LLM); rank with the existing ranker; surface a **shortlist** in the approval UI. This delivers JTBD components #1 and #4 (distinctive + ranked options) and reuses the moat (ranker + explainability) for *visual* selection.

### 5.6 Captions — extend, don't replace (small, high-ROI)

`ai_caption.py` is already strong. Add, per the verification-confirmed brand-voice recipe: (a) **few-shot injection** of 3–5 of the club's own past captions (the strongest single lever — verified consensus that few-shot beats adjective tone); (b) **generate-many-then-dedupe** (4–6 candidates, embedding/n-gram de-dup against recent) to kill repetition; (c) **per-platform variants** (feed/story/X length+tone) from one source; (d) an **approval-loop store** that feeds edited+approved captions back into the per-club few-shot set (Lately's verified engagement-loop, scaled down); (e) an explicit **AI-tell ban-list** ("delve," "elevate," reflexive exclamation marks). All inside the existing Gemini→Anthropic architecture.

### 5.7 Video — inherits the fix, then gains data-driven structure

`visual/motion.py` already forwards the brief's axes to Remotion and caches by hash. Because the brief gets richer (archetype, emphasis, tokens), the motion output gets richer for free. Then add the one thing template tools structurally can't do and Remotion can (verified): **data-driven scene structure** — a 5-PB weekend becomes a structurally different reel from a single medal (variable `durationInFrames`/scene count in code). Optional Tier C: activate the dormant `visual/ai_background` hook (`render.py:1131`) via Bria/Recraft for *branded B-roll/background only*, composited under deterministic text with the contrast guardrails the verification confirmed exist as research (TextCenGen, Neural Contrast).

---

## 6. Cost analysis

The headline cost finding is the reassuring one: **because the data layer stays deterministic, the generative spend is confined to *direction* (LLM calls — cents) and *optional art* (image API — cents), with generative *video* as the only expensive ingredient, kept opt-in and premium-priced.** The architecture is cheap precisely because it does not generate the thing that must be accurate.

### 6.1 Variable (marginal) cost, per content pack of ~10 cards

Assumptions: Gemini 2.5 Flash as primary (cheap, fast); a "pool" of N≈5 candidate specs per card; figures are May-2026 order-of-magnitude and should be re-checked at integration (LLM pricing moves).

| Component | Mechanism | Marginal cost | Notes |
|---|---|---|---|
| Layout direction (Tier B) | ~1 LLM design-spec call/card (emit N specs in one structured call) | **~$0.003–0.01/card → ~$0.05–0.10/pack** | Gemini Flash; context = data + tokens + archetype catalog |
| Captions (extended) | 4–6 candidate generations/card, dedupe | **~$0.01–0.02/card → ~$0.10–0.20/pack** | Already in production; marginally more calls |
| Static render | Playwright HTML→PNG, N candidates | **~$0 (CPU on existing server)** | Same substrate as today; cache hits free |
| Generative background (Tier C, optional) | Bria/Recraft, backgrounds only, cached per seed | **~$0.04–0.08/card *when used* → ~$0.20–0.40/pack** | Off by default; cache amortises across re-renders |
| Story video (Remotion) | ~6s @ ~$0.017/min Lambda (or near-zero on container) | **~$0.002/story** | Verified Remotion Lambda rate |
| Meet reel (Remotion) | ~15s deterministic | **~$0.004/reel** | Cache hit = free |
| **Generative B-roll video (opt-in premium)** | Veo 3.1 ~$0.40/sec (Veo 3 $0.75) | **~$6/15s reel (Veo 3.1); ~$11 (Veo 3)** | **The only expensive item — gate behind a premium tier, never default** |

**So a fully-featured pack (Tier A+B + captions, no generative video) costs roughly $0.15–0.30 in marginal API spend; add optional generated backgrounds and it's ~$0.50.** Generative *video B-roll* is the one ingredient that breaks the budget (~$6–11/reel, non-deterministic, re-roll-prone), which is exactly why the architecture confines it to an opt-in premium and keeps Remotion as the deterministic spine.

### 6.2 Per-club and at-scale

A typical club producing ~10 cards/week (~40/month) plus a few reels:
- **Variable cost/club/month:** ~$0.60–1.20 (LLM direction + captions) + ~$1–3 if generative backgrounds enabled + pennies of Remotion compute ≈ **under $5/club/month**, excluding opt-in generative video.
- **Fixed cost:** Remotion company licence **$100/month flat** (required at 4+ staff; verified) amortised across *all* clubs; Gemini/Anthropic already in the stack; Bria/Recraft only if Tier C is enabled (usage-based, no minimum at low volume).

At **100 clubs**: variable ≈ $60–120/month + $100 Remotion + optional image-API ≈ **~$200–400/month total infrastructure for generation**, against ~$1,500–4,000/month of revenue at $15–40/club (the price band the evaluation's grassroots comparables — Gipper $625–3,000/yr, Trace $180–300/yr — support). **Gross margin on generation is ~90%+.** The unit economics only break if generative *video* is made a default rather than a premium — the model explicitly avoids that.

### 6.3 Pricing implication — what this lets MediaHub charge, and why

The cost structure has a direct commercial consequence. Because marginal generation cost is **cents per pack** (Tier A+B) rising to perhaps **$0.50** with generative backgrounds, MediaHub can price at the grassroots band the verification pass confirmed — Gipper at $625/$1,500/$3,000/yr (≈$52–250/mo) for *manual* templates; Trace at $180–300/yr — and enjoy ~90%+ gross margin. The pricing logic writes itself: a club paying, say, **£15–40/month** for "upload results → a pack of distinct, on-brand, provably-true posts in every format, ready to approve" is getting something Gipper (manual, no intelligence) and Canva (generic, no data) cannot offer, at a cost of goods of well under a pound. The *premium* tier is generative video B-roll and higher render volumes, where the ~$6/reel cost is passed through with margin to clubs that want it. Crucially, the willingness-to-pay sits on JTBD component #3 (true + explainable) — the part MediaHub already owns — so the surgery's job is to remove the *reasons not to pay* (boring, samey, single-format output) rather than to invent the reason to pay, which already exists. This is why the surgery is high-ROI: it converts a product that *works but feels not-worth-it* into one whose visible output finally matches the value of its invisible intelligence.

### 6.4 Build cost (engineering effort — honest estimate for a small team)

| Workstream | Scope | Rough effort |
|---|---|---|
| Phase 0 — token contract + feature flag + deterministic floor | Promote `BrandKit`→DesignTokens; semantic role metadata; flag scaffolding | ~1 week |
| Phase 1 — **Tier A** archetype library + auto-fit + saliency crops + data-emphasis | Author 12–20 token-driven archetypes (the long pole); layout-intelligence infra | **~4–8 weeks** (authoring-bound) |
| Phase 2 — **Tier B** design-spec director + schema + pool/rank/compliance | Rewrite `ai_director`; JSON-schema decode; render-pool; deterministic compliance score | ~2–4 weeks |
| Phase 3 — caption extensions + Brandfetch bootstrap | Few-shot store, dedupe, per-platform variants, URL→brand-kit draft | ~1–2 weeks |
| Phase 4 — video data-driven structure + optional Tier C backgrounds | Variable scene counts in Remotion; activate `ai_background` via Bria | ~2 weeks |

These overlap; realistically a **2–3 month focused effort**, with **Tier A shippable inside the first month** and already fixing the stated problem. The dominant cost is *human* (authoring archetypes and tuning the director prompt), not *compute* — which is the correct shape for an intelligence-layer product.

---

## 7. Phased roadmap (sequenced so production never regresses)

- **Phase 0 — Foundations (≈week 1).** Promote `BrandKit` → typed `DesignTokens` (colour roles + brightness + semantic descriptions, logo lockups, type pairs, motion tokens). Add a `MEDIAHUB_GEN_V2` feature flag. Wire the deterministic archetype-picker as the fallback floor. *No user-visible change yet.*
- **Phase 1 — Tier A, the immediate fix (≈weeks 1–5).** Ship the 12–20 archetype library + auto-fit text + saliency crops + data-emphasis behind the flag. **A/B against the current engine in the review UI.** This alone is expected to resolve "boring/samey," with zero new API cost and full brand-safety. Gate on the existing test suite (`pytest tests/`) + visual QA + the human-approval workflow.
- **Phase 2 — Tier B, the strategic layer (≈weeks 4–8).** Replace the menu-picker with the design-spec director (schema-constrained); add the generate-N → rank → brand-compliance shortlist. Pilot behind the flag against Tier A; keep the deterministic floor on provider failure.
- **Phase 3 — Captions + onboarding (≈weeks 6–9).** Few-shot example store, generate-many-dedupe, per-platform variants, AI-tell ban-list; "paste your club URL → draft brand kit."
- **Phase 4 — Video + optional generative art (≈weeks 8–12).** Data-driven scene structure in Remotion; opt-in Tier C generative backgrounds (Bria) behind approval. Generative *video B-roll* only as a premium-priced experiment.
- **Cutover.** Once Tier A+B beat the current engine in review and tests are green, flip `MEDIAHUB_GEN_V2` on by default and delete the dead enum-permutation/menu-picker/phrase-table code (the literal "full removal," now safe because the replacement is proven).

---

## 8. Risks and honest caveats

- **LLM layout judgement is uneven** (verification-flagged). *Mitigation:* tight archetype vocabulary, schema-constrained decoding, the deterministic fallback floor, and the pool-rank-compliance filter catching poor specs before a human ever sees them. Tier A works without the LLM at all, de-risking the whole plan.
- **Authoring 12–20 archetypes is the long pole.** *Mitigation:* start with 12, grow over time; this is exactly the "template library as a design system" the programmatic-graphics leaders invested in (verified).
- **Brand auto-extraction is inaccurate for small clubs** (verification-confirmed Brandfetch is "decent for major brands, weaker for niche"). *Mitigation:* always a draft-for-human-confirmation, never auto-trusted — consistent with MediaHub's approval rule.
- **Generative-art copyright + legibility risk.** *Mitigation:* commercial-safe Bria (licensed data + indemnity — verified) for art only; deterministic contrast guardrails (existing APCA/ΔE2000) under all text; human approval.
- **Cost creep from generative video.** *Mitigation:* it is opt-in and premium-priced; Remotion is the default spine (verified cheapest at scale).
- **Determinism/repro for caching.** *Mitigation:* seed the director, cache the *spec* (not just the PNG), so a given card re-renders identically — preserving the current cache-hit behaviour.
- **Scope risk** (trying to do everything at once). *Mitigation:* Tier A is independently valuable and ships first; everything after is incremental and flag-gated.
- **The moat is narrow and per-sport** (verification-confirmed). *Mitigation, beyond this surgery:* race the *content-intelligence* layer (this work) and adopt an *integration* posture toward swim-data incumbents (ingest a SwimTopia/Swimcloud export as readily as a raw HY3) so MediaHub sits downstream as the content brain rather than competing on data custody.

---

## 8A. The target experience — what "generate" should feel like after the surgery

It helps to describe the destination concretely, because the surgery's success is measured by the experience, not the architecture. Today, a committee volunteer clicks "generate" on Hannah's PB and gets one card; clicking again gives a near-identical one; they shrug and post it. After the surgery:

1. **They click "generate" once and get a *shortlist*** — say five candidates that are *structurally* different (a split-diagonal hero, an editorial numbers grid, a magazine-cover treatment, a big-number-dominant card, a minimal type poster), each unmistakably the club's brand (right colours in the right roles, the correct logo lockup for each background), each carrying the exact, true data, and each tagged with a small **explainable badge**: "98% on-brand · PB delta is the story · why this design."
2. **They pick the one they like** — or click "more like #3" and get fresh variants in that direction (the regenerate-as-you-tweak loop the bleeding edge has normalised, powered by another cheap director call).
3. **They tweak the caption in plain language** — "make it warmer, mention the relay" — and the caption LLM, primed with the club's own past posts as few-shot examples, returns options that sound like the club, not like AI.
4. **They get every format at once** — feed, story, and a 15-second reel that is *structurally* matched to the moment (a multi-PB weekend produces a different reel from a single medal), all from the same approved direction.
5. **They approve, and it's logged** — the approval feeds back into the club's voice/style memory, so next week's options are a little more "them."

That experience — *distinctive, on-brand, true, ranked, multi-format, and learning* — is what a club will pay for, and every element of it is delivered by the layers in §5 with marginal cost in cents. The contrast with "press generate, get the same boring card" is the entire point of the project.

## 8B. Before and after, surface by surface

| | Today | After the surgery |
|---|---|---|
| **Structural variety** | 6 skeletons, mostly 2 in practice | 12–20 archetypes, LLM-directed + seed-rotated |
| **What the LLM does** | Picks a tuple from fixed enums (menu) | Emits a structured design spec (art-direction) |
| **Brand** | 3 colours + 1 logo applied as styling | Typed token contract (roles, lockups, voice) injected as constraints |
| **Output** | One graphic | Ranked pool of distinct candidates + compliance score |
| **Layout intelligence** | None | Auto-fit text, saliency crops, data-emphasis |
| **Captions** | Strong LLM, one output | + few-shot from club posts, generate-many-dedupe, per-platform, approval loop |
| **Video** | Remotion, thin axes forwarded | + data-driven scene structure; optional generative B-roll |
| **Accuracy / explainability** | Deterministic, source-grounded (the moat) | **Unchanged — preserved and extended** |
| **Marginal cost** | ~$0 | ~$0.15–0.50/pack (cents) |

The table makes the thesis's core claim visible: every row that changes is a *commodity capability being added on top*, while the one row that is the moat — accuracy and explainability — is explicitly unchanged. The surgery adds without subtracting from what matters.

## 8C. Success metrics — how we will know the surgery worked

The project should be judged against measurable outcomes, not vibes. Proposed metrics, gated per phase:

- **Structural distinctiveness (the headline metric).** Across the N candidates for one card, and across the cards in one pack, measure *archetype diversity* (distinct structural archetypes / candidates) and a perceptual-distance score between rendered candidates (e.g. embedding distance on the rendered PNGs). Target: a pack of 10 cards uses ≥6 distinct archetypes; a 5-candidate pool for one card spans ≥4 archetypes. *Today this is ~1–2.*
- **On-brand fidelity.** The deterministic compliance check (contrast pass-rate, correct logo lockup for background, palette-role legality) should pass ≥99% of *shipped* candidates, with violations caught *before* the human sees them.
- **Caption non-repetition.** N-gram/embedding overlap between consecutive captions for the same card below a threshold; zero of the AI-tell ban-list phrases in shipped captions.
- **Human-acceptance rate.** % of generated candidates approved without manual redesign — the truest "worth it" signal. Track before/after the flag flip.
- **Cost and latency.** Marginal API cost/pack stays under ~$0.50 (Tier A+B); cold render under the current 30–90s; cache-hit behaviour preserved.
- **No regression on the moat.** Accuracy of rendered data (name/event/time/PB label) stays at 100% (it is deterministic — any drop is a bug), and every card retains its "why this card / why this design" explanation.

**Decision points for the reviewer (you), before implementation starts:**
1. **Start with Tier A only, or commit to Tier A+B?** Tier A alone fixes "samey" deterministically in ~weeks; A+B makes it a defensible feature but adds the LLM-director work.
2. **Enable generative backgrounds (Tier C)?** Adds aesthetic range and ~$0.20–0.40/pack, plus a Bria/Recraft dependency — opt-in or skip.
3. **Generative video B-roll — premium feature now, or later?** It is the only expensive item; recommend "later, premium-priced."
4. **Brand-bootstrap via Brandfetch, or own crawlers only?** Brandfetch is faster to ship (~$99/mo) but adds a dependency; the existing `link_handlers/` could do it in-house more cheaply but slower.
5. **Do you want me to begin implementation** (starting Phase 0–1 behind the `MEDIAHUB_GEN_V2` flag), or is this document the deliverable for now?

## 9. Verification pass — results and corrections folded in

Per the brief, after the evaluation a **ten-agent verification pass** independently re-checked its load-bearing factual claims against fresh sources. Summary:

| # | Cluster checked | Result | Corrections folded in |
|---|---|---|---|
| 1 | Text-rendering failure (the core thesis) | **Core CONFIRMED** | Softened "OpenAI's *own* docs" → industry/community best practice (not a verbatim OpenAI quote); noted Kling 3.0 markets *improved* (not fixed) video text |
| 2 | Programmatic image APIs (Bannerbear/Abyssale/HCTI) | **All CONFIRMED** | Noted Abyssale $12 is annual rate; "headless Chrome" for Bannerbear is reported not vendor-stated |
| 3 | Remotion + programmatic video | **Remotion exact; CONFIRMED** | **Creatomate corrected to ~$41/$99/$249** (was $29/$99/$499) |
| 4 | Generative video cost/capability | **CONFIRMED** | **Veo split clarified: $0.50/$0.75 = Veo 3; Veo 3.1 ≈ $0.40/sec, Fast tiers cheaper** — $11.25/reel is the high end |
| 5 | Canva mechanics | **All 6 CONFIRMED** | "World's first foundation model"/perf stats remain flagged as vendor marketing; Connect API has a dev-only exception |
| 6 | Adobe GenStudio/Firefly | **All 6 CONFIRMED** | Brand-% via Azure OpenAI confirmed; Dec-2025 lawsuit is SlimLM/Books3 *text*, not Firefly-image-specific (kept "contested" via the Midjourney-in-Stock thread) |
| 7 | Image-model brand control | **Mixed** | **Midjourney "no API/worst text" is stale (fixed)**; Recraft "no colour drift" softened to vendor-worded; Ideogram *does* have palette controls |
| 8 | Sports content automation (the moat) | **Critical absence CONFIRMED** | **Gipper corrected to $625/$1,500/$3,000**; WSC $ and Spectatr funding/"down-market" flagged unverified |
| 9 | Caption/brand-voice | **5 CONFIRMED, 1 partial** | Vendor % claims (Copy.ai 85–90%, Anyword CTR) remain flagged as marketing; few-shot consensus solid |
| 10 | Brand-as-data + layout research | **CONFIRMED** | **DESIGN.md = real but alpha (April 2026)**; "GPT-5 <0.1% schema" softened to "mechanism reliable, figure unverified"; tokens-"consensus" softened to prevalent best-practice; all 6 research papers verified real |

**Net effect on the plan:** none of the corrections changes the architecture — they tighten the *numbers* the cost model uses (Creatomate, Veo 3 vs 3.1, Gipper) and the *attribution* of a few claims (Sora guidance, DESIGN.md maturity, Midjourney's current state). The structural conclusions — exact data must be rendered deterministically; "samey" is a layout-intelligence gap; on-brand comes from tokens-as-contract + a compliance check; distinctiveness comes from widening *structural* axes and ranking a pool; the swim-data white space is real; Remotion is the right video spine — all survived verification intact. The most important *positive* confirmation is the moat one: **as of May 2026 no swim-data platform auto-generates branded content or detects content-worthy moments**, so the window for MediaHub to make this surgery and own the quadrant is genuinely open.

---

## 10. Conclusion

MediaHub's "boring, samey graphic" is not a mystery and not a sign that it needs to buy a generative pixel model. It is the precise, diagnosable consequence of a generation system that selects a tuple from a bounded, hand-authored option space dominated by six layout skeletons, with an LLM constrained to *pick from that menu* rather than *design*, painting one DOM in different colours. The companion evaluation shows that the entire 2026 field — including the market leaders MediaHub fears — has converged on a different and better pattern that MediaHub is unusually well-positioned to execute, because it already half-implements it for captions and already owns the deterministic, explainable engine that is the hard part: **a deterministic renderer driven by an LLM art-director over a rich layout-intelligence layer, with brand identity threaded through as a token contract, output as a ranked pool of genuinely distinct variants, behind a brand-compliance and human-approval gate.**

The surgery is therefore not a teardown of the engine but a *replacement of its weakest layer*: rip out the enum-permutation variation mechanism and the menu-picker (the literal cause of the sameness), keep the renderer substrate and the moat, and insert the token contract, the archetype library, the design-spec director, and the pool-rank-comply step in between. Tier A alone — deterministic, brand-safe, ~$0 marginal cost — fixes the stated problem inside a month; Tier B turns it into a defensible product feature; the captions and video inherit the lift. The cost is dominated by human effort (authoring archetypes), not compute, with ~90%+ gross margin on generation and generative video confined to a priced premium. And the strategic prize is real and time-bound: the verification pass confirms nobody else is turning a club's results into ranked, on-brand, *distinctive*, provably-true content — yet. This document specifies how to make that worth paying for; the next step is to decide which phase to start, and to begin with Tier A.

One last reframing, because the brief carried real anxiety about being "very far behind." The honest, evidence-backed conclusion is the opposite of the fear: MediaHub is behind on the *cheap, commoditised, weeks-of-work* layer (layout variation) and ahead on the *expensive, slow, defensible* layer (grounded detection, ranking, explainability, accuracy) that the entire field — Canva, Adobe, the ad-creative engines, the generalist agents — cannot offer for a club at all. The competitors that look intimidating are intimidating at exactly the thing that is easiest to copy, and helpless at exactly the thing that took MediaHub years to build. The surgery in this document is, in essence, a few months of well-understood engineering to convert a product whose *visible output* undersells its *invisible intelligence* into one where the two finally match. That is not a catch-up project from behind; it is a finishing project from a lead that has been hidden by a thin, fixable rendering layer. The recommendation is to start that finishing project with Tier A, prove it in the review UI against the current engine, and let the ranked, distinctive, on-brand, provably-true output speak for itself.

---

## Appendix A — File-change manifest (what an implementer touches)

A concrete map from the surgery to the codebase, so the plan is actionable rather than abstract. Paths are under `src/mediahub/`.

**Phase 0 (foundations):**
- `brand/kit.py` — extend `BrandKit` → `DesignTokens` (colour roles + `brightness` + `when_to_use`, `logos[]` by form/theme, type pairing, motion tokens). Additive; keep the old flat fields as derived aliases so nothing breaks.
- `theming/` — expose the existing APCA/ΔE2000 contrast numbers as the `brightness`/legality source for token roles; no maths change.
- new `creative_brief/gen_v2/` package + a `MEDIAHUB_GEN_V2` flag read in the route.

**Phase 1 (Tier A — the immediate fix):**
- `graphic_renderer/layouts/` — author 12–20 new token-driven archetype templates (the long pole); slots reference token *roles*, not hex.
- `graphic_renderer/render.py` — add `auto_fit_text()` (shrink-to-box) and a `saliency_crop()` helper feeding the cutout pipeline; keep `render_html_to_png` unchanged.
- `creative_brief/generator.py` — add an archetype-picker (seed-rotated) as the deterministic floor; expose the ranker's *emphasis-angle list* (read-only into the brief). Begin demoting `BACKGROUND_STYLES`/`ACCENT_STYLES`/etc. to renderer-internal building blocks.
- `legacy/swim_content_v5/ranker_v3.py` — *read-only* addition: surface the ranked emphasis angles it already computes (no scoring change, per the deterministic-engine rule).

**Phase 2 (Tier B — director + pool):**
- `creative_brief/ai_director.py` — replace `_system_prompt`/`ai_creative_direction` with a design-spec emitter under JSON-schema-constrained decoding (via `ai_core`); delete the closed-enum vocabulary.
- `content_pack_visual/integration.py` — `create_visual_for_item` emits N candidate specs, renders the pool, runs the deterministic compliance check, ranks, returns a shortlist (extend the return shape; keep the signature).
- `web/web.py` — the create-graphic route returns the ranked shortlist + compliance scores (additive to the existing JSON).

**Phase 3 (captions + onboarding):**
- `web/ai_caption.py` — add few-shot example injection, generate-many-dedupe, per-platform variants, AI-tell ban-list; an approval-feedback store under the club profile.
- `brand/link_handlers/` + `brand/link_learners/` — wire a "URL → draft brand kit" onboarding path (optionally via Brandfetch); always draft-for-confirmation.

**Phase 4 (video + optional art):**
- `remotion/src/compositions/` — variable scene counts driven by the brief (data-driven structure).
- `visual/ai_background.py` — activate behind a flag via Bria/Recraft for backgrounds only, with the contrast guardrails; it is already imported at `render.py:1131`.

**Cutover:** once `MEDIAHUB_GEN_V2` wins the A/B in review and tests are green, flip the default and delete the dead `random_variation_profile`, `_PHRASE_TABLES`, `_legacy_axes_from_seed`, and the old enum-permutation path — the literal "full removal," now safe.

Tests: extend `tests/` with archetype-diversity assertions, compliance-pass-rate checks, and a "data accuracy is 100%" guard; the existing suite (~253 passed) is the regression floor.

*— End of thesis.*
