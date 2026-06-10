# Generation Engine v2

The single canonical reference for MediaHub's **v2 content-generation
architecture**: the design-spec director that replaces the enum-permutation
"menu-picker" engine. It documents the brand-token contract, the archetype
library and its `layouts/v2` slot convention, the LLM design-spec director, the
pool/rank/compliance step, the caption extensions, and the video path — all
gated behind the `MEDIAHUB_GEN_V2` flag.

> **Status: specified, staged, not yet built.** This describes the *target*
> architecture from the thesis, not as-shipped code. Build order, owners, and
> per-stage prompts live in [`ROADMAP.md`](ROADMAP.md) Appendix A (SEQ-0 → SEQ-4,
> PAR-1 → PAR-8); every spine stage is flag-gated until the SEQ-3 cutover so
> production never regresses. The full diagnosis, cost model, and rejected
> alternatives are in
> [`research/mediahub-generative-ai-thesis.md`](research/mediahub-generative-ai-thesis.md);
> the field study is in
> [`research/generation-engine-competitor-evaluation.md`](research/generation-engine-competitor-evaluation.md).
> The architecture-decision record is [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md).

---

## 1. Why v2 exists (the one-paragraph diagnosis)

Today "click generate" selects a tuple from a bounded, hand-authored option
space — `creative_brief/generator.py` offers ~6 layout families plus cosmetic
axes (10 background SVGs, 8 accents, 6 type pairs, 6 palette rotations), and
`creative_brief/ai_director.py` constrains the LLM to *pick from those enums*
("never propose a value outside the listed vocabulary"). The axes that vary are
cosmetic, not structural: the renderer repaints **one DOM**, so two generations
read as the same card with different paint. That is the precise, code-level
cause of "boring and not unique." v2 keeps the deterministic engine and the
renderer substrate, and replaces the *variation mechanism* with real layout
intelligence and an LLM that designs rather than picks. See thesis §2 for the
line-by-line diagnosis.

## 2. The governing principle

**Deterministic where it must be true; generative where it must be fresh.**

| Layer | What it covers | How it is produced |
|---|---|---|
| **Data layer** | Names, times, PB badges, placings, brand colours, logo | Rendered symbolically and **deterministically** — accurate, on-brand, cheap, explainable. *This is the moat; never AI-touched.* |
| **Direction layer** | Which archetype, which emphasis, which crop, which hook, which mood | **Generative** — the LLM art-director (`media_ai.llm` / `ai_core.llm`) emits a structured spec the renderer executes. |
| **Art layer** | Backgrounds, textures, optional B-roll | **Optionally generative** via a commercial-safe API (Bria/Recraft), behind its own flag, *backgrounds only*. |

This is MediaHub's existing doctrine ("judgement through `media_ai.llm`;
parsers/detectors/ranker/colour-science deterministic") applied to graphics. No
diffusion model ever renders the data text — that is the single most important
constraint and the reason accuracy (JTBD #3) is never traded for polish.

## 3. The pipeline, before and after

```
LEGACY (kill-switch MEDIAHUB_GEN_V2=0):
  card data ─▶ creative_brief.generator (random/seed enum tuple)
                 └─ ai_director: LLM PICKS a tuple from fixed enums
            ─▶ graphic_renderer.render (repaint one DOM) ─▶ 1 PNG

v2 (the default; Tier A live, Tier B pending SEQ-2):
  card data ─▶ DesignTokens contract (roles, lockups, type, voice)   [Layer 1]
            ─▶ ai_director: LLM EMITS a DesignSpec (schema-constrained) [Layer 3]
                 (archetype + colour roles + hero stat + hook + crop + mood)
            ─▶ render N candidates over the layouts/v2 archetypes      [Layer 2]
            ─▶ deterministic compliance + legibility check (APCA/ΔE2000)[Layer 4]
            ─▶ rank with the existing ranker ─▶ ranked shortlist of distinct cards
```

The route (`POST /api/runs/<run_id>/cards/<card_id>/create-graphic`), the
`CreativeBrief` dataclass, `render_html_to_png`, the asset pipeline, captions,
and Remotion are all **kept and extended** — never deleted. Only the
enum-permutation variation mechanism and the menu-picker prompt are removed (at
the SEQ-3 cutover, after the replacement is proven).

## 4. The `MEDIAHUB_GEN_V2` flag

A single environment flag gates the engine. **v2 Tier A is the production
default**; the flag is now a kill-switch, not an opt-in.

- **Name:** `MEDIAHUB_GEN_V2` — env-read. **Unset (or any non-kill value) = v2
  ON.** Set `0` / `false` / `off` / `no` to fall back to the legacy engine
  (the deployment-wide kill-switch; see `graphic_renderer/archetypes.is_enabled`).
- **Kill-switch engaged:** the old enum-permutation engine runs byte-identical
  to its pre-v2 behaviour. The v2 files sit inert.
- **Default (v2 on, Tier A):** rendering uses the `--mh-*` brand-role tokens,
  the `layouts/v2` archetype library with the deterministic seeded picker, the
  autofit hero sizing, and the saliency photo position. The design-spec
  director and the pool/rank/compliance shortlist are **not yet wired** —
  they land with SEQ-2.
- **Provider unavailable:** Tier A is already the **deterministic
  archetype-picker floor** (seed-rotated over the v2 archetypes) — a real,
  legible card, never a fabricated or broken one. This honours the project's
  "honest error, never a fake fallback" rule and remains the floor under the
  SEQ-2 director.
- **Cutover (SEQ-3):** once the SEQ-2 director wins the A/B in review and the
  suite is green, the dead enum/menu-picker code is removed via CLAUDE.md's
  gated-removal process. A second flag, `MEDIAHUB_GEN_BG` (default off),
  independently gates optional generative backgrounds (SEQ-4, Tier C).

Read the flag in the route and in `resolve_design_tokens(profile_id)`; everything
downstream branches on it. Seed the director and **cache the spec** (not just the
PNG) so a given card re-renders identically — preserving today's cache-hit
behaviour.

---

## 5. Layer 1 — the brand-token contract (`DesignTokens`)

**Problem it fixes:** brand identity is applied as styling (3 colours + 1 logo),
not as a machine contract a generator can reason over.

**Build:** promote today's flat `BrandKit` (`brand/kit.py`) to a typed
`DesignTokens` object — *additively*, keeping `primary_colour` /
`secondary_colour` / `accent_colour` as derived aliases so nothing breaks. This
extends the Adaptive Theming Engine's DTCG `derived_palette` (ROADMAP §1.6 Stage
G); it does **not** fork or duplicate it. The contract adds three
generation-specific things on top of the theming tokens:

- **Colour *roles*, not slots** — `brand`, `accent`, `surface`, `on-surface`,
  `sponsor-safe`, each carrying a `brightness` value (reuse the existing
  APCA/ΔE2000 numbers from `theming/`) and a `when_to_use` description, so the
  director picks the *legible* colour for background vs text and the renderer can
  guarantee contrast.
- **Logo lockups by context** — replace the single `logo_svg` with `logos[]`
  typed by `form` (icon / horizontal / stacked / mono) and `theme` (light / dark).
  A story card on a dark photo needs the light-knockout mono mark; a feed card
  needs the full lockup. Extend `theming/logo_chip.py` to *select* the lockup for
  a given background.
- **Type pairing, motion, and voice** — typed `title`/`body` fonts with a scale;
  timing/easing tokens for Remotion; a structured `voice` profile (examples,
  banned phrases, emoji policy) the caption store populates.

The semantic `brightness` + `when_to_use` metadata is what lets an LLM *read* the
tokens — the difference between "applied a brand kit" and "obeys a brand
contract." A single helper, `resolve_design_tokens(profile_id) -> dict`, returns
the full contract (with role descriptions) and is injected into every generator's
context: the caption LLM, the design-spec director, and the Remotion brief.

**Bootstrap (onboarding):** "paste your club website / Instagram → pre-fill a
*draft* brand kit," using the existing `brand/link_handlers/` +
`brand/link_learners/` (optionally a Brandfetch call). Always a draft for human
confirmation — extraction is unreliable for small clubs, and the human-approval
rule forbids auto-trust.

The expanded object (extending today's flat `BrandKit`):

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

## 6. Layer 2 — the archetype library + layout intelligence (Tier A, ships first)

**Problem it fixes:** only ~6 structural skeletons exist, and the cosmetic axes
don't change how a card *reads*.

This tier is **fully deterministic, no AI, brand-safe, ~$0 marginal cost**, and
is expected to resolve "samey" on its own — it ships before any LLM-director
work.

1. **12–20 structurally distinct archetypes** replacing the 6 families, authored
   as token-driven HTML templates under `graphic_renderer/layouts/v2/` (see the
   slot convention in §7). Each *reads* differently at a glance — the property the
   background/accent/font axes never provided.
2. **Auto-fit text** (`autofit.fit_font_px`) — text shrinks to its box so long
   names/events never overflow a layout. This is what lets one archetype absorb
   variable content gracefully.
3. **Saliency-aware crops** (`saliency.best_crop`) — produce multiple valid crops
   of a photo (tight portrait / rule-of-thirds action / wide); the archetype's
   `crop_intent` dictates which it consumes. Deterministic maths, consistent with
   the colour-science rule.
4. **Varied data-emphasis** — the ranker exposes, *read-only*, a ranked list of
   emphasis angles (lead with time / PB delta / placing / relay split); the brief
   varies which is hero. Genuine freshness sourced from MediaHub's own
   intelligence layer — **the ranker's scoring is not changed**.

A **deterministic archetype-picker** (seeded by the existing
`auto_variation_seed_for`, stable per card, different across cards) selects among
the v2 archetypes. This is both the no-AI path and the fallback floor when no
provider is configured. With the flag on, a 10-card pack should use **≥6 distinct
archetypes** (today: ~1–2).

**Catalog (all 12 live, growing):** `split_diagonal_hero`,
`full_bleed_photo_lower_third`, `editorial_numbers_grid`,
`centered_medal_spotlight`, `magazine_cover`, `ticker_strip`,
`stat_stack_sidebar`, `triptych_progression`, `quote_led_recap`,
`big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`.
Every archetype ships a `<name>.notes.md` (composition + when the director
should pick it — the SEQ-2 director's catalog entries), enforced by
`tests/test_gen_v2_tier_a.py::test_archetype_has_authoring_notes`.

## 7. The `layouts/v2` slot convention (authoritative)

> Author each archetype against this convention **exactly** so the SEQ-1 wiring
> can load every file uniformly. This is the contract copied from
> [`ROADMAP.md`](ROADMAP.md) Appendix A → PAR-7; if the two ever diverge, the
> roadmap is the source of truth.

**Each archetype owns one new file** `src/mediahub/graphic_renderer/layouts/v2/<name>.html`
(plus its `<name>.notes.md`). Files are disjoint, so archetypes can be
authored independently and never conflict.

**Slot convention (author against this exactly):** use `{{PLACEHOLDER}}` string
substitution (**not** Jinja), and reference brand colours **only** via CSS custom
properties (`var(--mh-primary)`, `var(--mh-on-primary)`, `var(--mh-surface)`,
`var(--mh-on-surface)`, `var(--mh-accent)`, `var(--mh-outline)`) — **never**
hardcode a hex. Available text placeholders: `{{ATHLETE_FULL_NAME}}`,
`{{ATHLETE_FIRST_NAME}}`, `{{ATHLETE_SURNAME_DISPLAY}}`, `{{EVENT_NAME}}`,
`{{RESULT_VALUE}}`, `{{ACHIEVEMENT_LABEL}}`, `{{MEET_NAME}}`, `{{CLUB_FULL}}`,
`{{HERO_STAT}}`, `{{LOGO_BLOCK}}`, `{{ATHLETE_IMG_BLOCK}}`,
`{{ACCENT_DECORATION}}`, `{{SPONSOR_BLOCK}}`. Canvas is `{{WIDTH}}×{{HEIGHT}}`.
Include `{{BASE_CSS}}` at the top. The archetype must read *structurally distinct*
from `individual_hero` / `big_number_hero` at a glance.

**Placeholder reference:**

| Placeholder | Substituted with |
|---|---|
| `{{ATHLETE_FULL_NAME}}` | Full athlete name |
| `{{ATHLETE_FIRST_NAME}}` | First name |
| `{{ATHLETE_SURNAME_DISPLAY}}` | Surname, as displayed |
| `{{EVENT_NAME}}` | Event (e.g. "100m Freestyle") |
| `{{RESULT_VALUE}}` | The result/time |
| `{{ACHIEVEMENT_LABEL}}` | Achievement tag (e.g. "PERSONAL BEST") |
| `{{MEET_NAME}}` | Meet name |
| `{{CLUB_FULL}}` | Full club name |
| `{{HERO_STAT}}` | The chosen hero stat (from the ranker's emphasis list) |
| `{{LOGO_BLOCK}}` | Resolved logo lockup HTML (form/theme chosen for the ground) |
| `{{ATHLETE_IMG_BLOCK}}` | Athlete image/cutout HTML (cropped per `crop_intent`) |
| `{{ACCENT_DECORATION}}` | Accent/decoration overlay HTML |
| `{{SPONSOR_BLOCK}}` | Sponsor lockup HTML (sponsor-safe) |
| `{{WIDTH}}` / `{{HEIGHT}}` | Canvas dimensions |
| `{{BASE_CSS}}` | Shared base stylesheet — include at the top |

**CSS colour variables (the only legal way to reference brand colour):**
`--mh-primary`, `--mh-on-primary`, `--mh-surface`, `--mh-on-surface`,
`--mh-accent`, `--mh-outline`. These resolve from the DesignTokens roles (§5) at
render time. **No hex literals in colour positions.**

**Authoring rules:**

- Self-contained HTML/CSS — **no JS, no network, no hex literals**.
- A *structurally distinct* portrait composition that reads well at both
  **1080×1350** and **1080×1920** — a genuinely different layout, not a reskin of
  an existing family.
- Add a one-paragraph `<name>.notes.md` describing the composition and **when the
  director should pick it** (this feeds the director's archetype catalog).
- Create only the file(s) under `layouts/v2/`. Do **not** touch `render.py` or any
  other file — SEQ-1 wires the directory; until then the files are inert and
  cannot be fully render-tested. Validate that the HTML is well-formed and every
  placeholder/variable matches this convention.

**Self-check before opening a PAR-7 PR:** exactly one new
`layouts/v2/<name>.html` (+ its notes); only CSS-variable colours (grep for
`#` hex in colour positions → none); every placeholder on the allow-list above;
`{{BASE_CSS}}` present; structurally distinct from the existing families; no other
file changed.

## 8. Layer 3 — the LLM design-spec director (Tier B, the strategic play)

**Problem it fixes:** the menu-picker can only select a cosmetic tuple; it cannot
design.

**Build:** rewrite `ai_director.ai_creative_direction` so that — given the card
data, the `DesignTokens` contract, and the archetype catalog (with the
`when_to_use` descriptions from each `.notes.md`) — the LLM emits a **structured
design spec** under JSON-schema-constrained decoding via `ai_core`. The renderer
executes it deterministically. The LLM now makes *compositional judgements* (what
to emphasise, how to arrange, what mood) — what it is good at — while never
touching a pixel or an exact hex.

Every field is either an enum the renderer knows, a token *role* (never a hex), or
generated copy — so a hallucinated value **normalises to a safe default** and the
output is always brand-legal. The `rationale` field feeds the existing "why this
design" explainability surface, so the director's judgement is auditable —
extending the moat, not bypassing it. Keep the SEQ-1 deterministic
archetype-picker as the fallback floor when no provider is configured.

```json
{
  "archetype": "split_diagonal_hero",
  "colour_roles": { "ground": "brand", "surface": "on-surface",
                    "headline": "surface", "accent": "accent-strong" },
  "focal_element": "athlete_cutout",
  "crop_intent": "rule_of_thirds_action",
  "hero_stat": "pb_delta",                 // chosen from the ranker's emphasis list
  "secondary_stats": ["final_time", "event"],
  "headline_hook": "TWO SECONDS FASTER",   // LLM-generated, not table-picked
  "accent_treatment": "diagonal_underline",
  "logo_lockup": "mono_light",             // resolved against the dark ground
  "mood": "explosive",
  "motion_intent": "snap_in_then_settle",
  "rationale": "PB delta is the story; action crop + diagonal energy match the swimmer's drive."
}
```

The spec lives in `creative_brief/design_spec.py` (PAR-4), which owns the schema
and the normalisation of a malformed LLM response down to a legal, legible card.

## 9. Layer 4 — generate a pool, rank, and brand-compliance-check

**Problem it fixes:** MediaHub emits one graphic; the field emits a ranked pool.

**Build (`content_pack_visual/integration.py`):**

1. The director produces **N candidate specs** (default 5), varying
   archetype/emphasis/crop/hook.
2. Render the pool — cheap, near-zero marginal cost on the existing Playwright
   substrate; cache hits are free.
3. Run a **deterministic brand-compliance + legibility check**: contrast via the
   existing APCA/ΔE2000 gates, correct logo lockup for the background, sponsor-safe
   zones. This attaches an **explainable compliance score** to each candidate
   (Adobe GenStudio's per-variant brand-% pattern, but computed *deterministically*
   here, not via a second LLM).
4. Score diversity with `quality/variant_metrics.py` (PAR-5), **rank with the
   existing ranker**, and return a **ranked shortlist**.

The create-graphic route response is extended *additively* to return the shortlist
+ per-candidate compliance score, while the legacy single-visual fields stay
populated from the top candidate so existing callers keep working. This delivers
JTBD #1 (distinctive) and #4 (ranked options), and reuses the moat (ranker +
explainability) for *visual* selection. Off-brand candidates are caught before a
human ever sees them — target ≥99% compliance pass-rate on shipped candidates.

## 10. Captions — extend, don't replace

`web/ai_caption.py` is already the one strong generative surface (LLM-only,
Gemini-primary / Claude-failover, honest-error, voice profile, brand-DNA
injection, recent-caption dedupe). v2 extends it inside the same architecture
(all five shipped with PAR-1):

- **Few-shot injection** of up to 5 of the club's own past captions (the
  strongest single lever — few-shot beats adjective tone). The live caption
  route merges two sources: Cap-2b semantic recall (moment-matched, needs an
  embedding backend) and the plain `web/caption_examples.py` store of recently
  approved captions, which works for every club from the first approval.
- **Generate-many-then-dedupe** — `generate_caption_candidates`: 4–6
  candidates, trigram de-dup against recent + each other, returned ranked
  freshest-first.
- **Per-platform variants** — `generate_platform_variants`: feed / story / X /
  LinkedIn length + tone from one approved source caption.
- **Approval-loop store** — the content-pack approval seam
  (`workflow/pack.py`) appends each approved card's final caption (edits
  included) to the club's few-shot store, alongside Cap-2b semantic capture.
- **AI-tell ban-list** — "delve," "elevate," "in the world of," reflexive
  exclamation marks.

## 11. Video — inherits the fix, then gains data-driven structure

`visual/motion.py` already forwards the brief's axes to Remotion and caches by
content hash. Because the brief gets richer (archetype, hero stat, tokens), the
motion output gets richer for free — the reel's look matches the still.

Then add the one thing template tools structurally cannot do and Remotion can:
**data-driven scene structure** — a 5-PB weekend becomes a structurally different
reel from a single medal (variable `durationInFrames` / scene count derived from
the number of ranked moments).

**Optional Tier C, behind `MEDIAHUB_GEN_BG` (default off):** activate the dormant
`visual/ai_background.py` hook (already imported at `render.py`) via a
commercial-safe API (Bria/Recraft) for **backgrounds only**, composited under the
deterministic text with the existing contrast guardrails. Never the data layer.
Generative *video B-roll* (Veo/Sora) is the only expensive ingredient (~$6–11 per
15s reel) and is reserved for an opt-in premium tier — never the default.

---

## 12. What is removed, kept, and protected

**Removed from the live path (at the SEQ-3 cutover, once v2 is proven):**

| Removed (file:symbol) | Why | Disposition |
|---|---|---|
| `ai_director.py:_system_prompt` (closed-vocabulary "return one of these enums") | Makes the LLM a menu-picker, not a designer | Replaced by the design-spec emitter (§8) |
| `generator.py:random_variation_profile` + `_legacy_axes_from_seed` | "Variation" = random tuple from cosmetic enums | Deleted as live path; deterministic archetype-picker is the floor |
| `generator.py:_PHRASE_TABLES` + `_phrase_for_seed` | Canned hook tables read as templated | Replaced by LLM-generated hooks |
| `BACKGROUND_STYLES` / `ACCENT_STYLES` / `TYPOGRAPHY_PAIRS` / `COMPOSITIONS` / `PHOTO_TREATMENTS` as the *variation surface* | Cosmetic axes masquerading as variety | Demoted to renderer-internal building blocks the archetypes compose, or removed |
| `_PALETTE_PERMUTATIONS` as the *only* palette variation | Six rotations of three colours is not brand intelligence | Superseded by the token-role contract (§5) |

The *mechanism* (enum permutation + menu-picker + phrase tables + 6-skeleton
ceiling) is genuinely deleted from the live path. The *substrate* it ran on is
**extended, not deleted** — production depends on it, and CLAUDE.md forbids
breaking it. SEQ-3 is a route/data-structure-adjacent removal and **must** follow
CLAUDE.md's gated process: the 15-step breakage check before, the 15-step
verification after, and a dead-code sweep.

**Kept and protected (the moat and the substrate):**

| Kept | Role | Change |
|---|---|---|
| `recognition*/`, `pb_discovery/`, `legacy/swim_content_v5/ranker_v3.py` | Detection + ranking (the moat) | **Unchanged**; *new read-only* accessor exposes ranked emphasis angles |
| `theming/` (DTCG `derived_palette`, ΔE2000/APCA logo-chip) | Colour science | **Unchanged**; becomes the source of the token contract |
| `graphic_renderer/render.py:render_html_to_png` + asset pipeline | Render substrate (HTML→PNG, cutouts, logo prep) | **Kept**; SVG/CSS primitives become archetype building blocks |
| `web/ai_caption.py` | The one strong generative surface | **Extended** (§10), not replaced |
| `visual/motion.py` + `remotion/` | Video compositor | **Kept**; inherits richness from the new brief |
| create-graphic route + `content_pack_visual/integration.py:create_visual_for_item` | The pipeline contract | **Kept**; internals swapped behind the same signature |
| `media_library/selector.py:score_asset` | Deterministic photo pick | **Kept** (per project rule); feeds crop intent |

**Accuracy / explainability is explicitly unchanged.** Rendered data accuracy
stays 100% (it is deterministic — any drop is a bug), and every card keeps its
"why this card / why this design" explanation.

## 13. Build status & sequencing

Full prompts (implementation + verification) per stage are in
[`ROADMAP.md`](ROADMAP.md) Appendix A. Status as of 2026-06-09:

**Parallel bucket — ✅ ALL SHIPPED:** PAR-1 caption quality pack (live: the
approval seam feeds the few-shot store, the caption route injects it) · PAR-2
auto-fit · PAR-3 saliency crop · PAR-4 design-spec schema · PAR-5 variant
metrics · PAR-6 brand bootstrap · PAR-7 archetype templates (all 12 live, each
with director notes) · PAR-8 docs/ADR (this document).

**Spine:** SEQ-0 + SEQ-1 (Tier A) ✅ shipped — v2 is the production default
with `MEDIAHUB_GEN_V2=0` as the kill-switch. SEQ-2 (design-spec director +
pool/rank/compliance shortlist), SEQ-3 (cutover + gated removal of the
enum/menu-picker engine) and SEQ-4 (video scene structure) are 🔵 in flight in
a separate build session — not yet merged here; that workstream owns updating
this status when each stage lands.

**Sequential spine (in order, flag-gated):**

```
SEQ-0 DesignTokens contract + MEDIAHUB_GEN_V2 flag
  └▶ SEQ-1 Tier A (archetype library + layout intelligence) — the immediate fix
       └▶ SEQ-2 Tier B (design-spec director + pool/rank/compliance)
            └▶ SEQ-3 cutover + gated removal of the enum/menu-picker engine
                 └▶ SEQ-4 video data-driven scene structure (+ optional Tier C)
```

**Fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (parallel) → SEQ-0 →
SEQ-1. That delivers Tier A — deterministic, brand-safe, ~$0 marginal cost — with
no LLM-director work required to resolve the core complaint.

**Cost (thesis §6):** a fully-featured pack (Tier A+B + captions, no generative
video) costs roughly **$0.15–0.30** in marginal API spend; ~$0.50 with optional
generated backgrounds; ~90%+ gross margin on generation. The budget only breaks if
generative *video* is made a default rather than a premium — which v2 explicitly
avoids.

## 14. Acceptance criteria (thesis §8C)

v2 is "done" when, with `MEDIAHUB_GEN_V2` on:

1. **Structural distinctiveness:** a 10-card pack uses ≥6 distinct archetypes; a
   5-candidate pool spans ≥4 (today ~1–2). Measured by `quality/variant_metrics.py`.
2. **On-brand fidelity:** the deterministic compliance check passes ≥99% of
   shipped candidates; off-brand candidates are caught before a human sees them.
3. **Caption non-repetition:** consecutive captions for a card are below the
   overlap threshold; zero ban-list phrases ship.
4. **Human-acceptance rate** (approved without manual redesign) rises vs the old
   engine in the review-UI A/B.
5. **Cost & latency:** marginal API cost/pack < ~$0.50 (Tier A+B); cold render
   within today's 30–90s; cache-hit behaviour preserved.
6. **No moat regression:** rendered data accuracy stays 100% (deterministic); every
   card keeps its "why this card / why this design" explanation.
7. **Suite green** throughout (no new failures, no weakened tests), and SEQ-3's
   gated-removal checklists are completed and recorded.

## 15. Where to read next

- The plan, diagnosis, and cost model: [`research/mediahub-generative-ai-thesis.md`](research/mediahub-generative-ai-thesis.md) (§5 is the surgery).
- The field study: [`research/generation-engine-competitor-evaluation.md`](research/generation-engine-competitor-evaluation.md).
- Build order, owners, and per-stage prompts: [`ROADMAP.md`](ROADMAP.md) Appendix A.
- The decision record: [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md).
- The theming token plumbing this extends: [`THEMING.md`](THEMING.md).
- How a card is built today: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`UPLOAD_TO_CARDS.md`](UPLOAD_TO_CARDS.md).
