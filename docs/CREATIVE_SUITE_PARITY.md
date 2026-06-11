# Creative-Suite Parity — the MediaHub-shaped Canva / Adobe Express capability map

**Status:** planned · the long-form companion for **Phase 6** in
[`ROADMAP.md`](ROADMAP.md) · evidence bases checked in at
[`research/CANVA_FEATURE_INVENTORY_2026.md`](research/CANVA_FEATURE_INVENTORY_2026.md)
and
[`research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md`](research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md)
· added 2026-06-11.

## In plain words (start here)

Canva and Adobe Express are giant "make anything" design tools. The maintainer
asked: *for every single feature those two products have, work out how MediaHub
could build **its own version** — our way, on our engine, not by integrating
theirs — and put it on the plan.* This document is that map.
Every feature in both research inventories appears in exactly one numbered
work-package table below (sometimes with cross-references where two products
ship the same idea), with a note saying whether MediaHub already has it, where
it would live, and how we would build it. The roadmap itself
([`ROADMAP.md`](ROADMAP.md), Phase 6) carries one line per work package; this
file holds the depth.

The one-sentence translation rule: **Canva starts from a blank canvas; MediaHub
starts from the club's data.** So every feature below is re-expressed as
"data in → meaningful thing out", never as a blank template to fill in by hand.

## Doctrine — how a Canva/Adobe feature becomes a MediaHub feature

These rules are applied to every row in this document. They restate standing
policy ([`../CLAUDE.md`](../CLAUDE.md)) plus one explicit maintainer steer
(2026-06-11): MediaHub builds its **own versions** of these capabilities:

1. **Intelligence-first, never a template shop.** A Canva "template" maps to a
   MediaHub **archetype + creative brief** fed by real club data (results,
   rosters, fixtures, history, brand). We ship *formats that fill themselves*,
   not 220,000 blanks. Blank-canvas editing exists only as an escape hatch on
   top of a generated design.
2. **Our own versions, not integrations.** Every capability is a first-party
   MediaHub build on MediaHub seams — we never embed Canva/Adobe (or any
   competing creative suite), their SDKs, or third-party creative apps as
   product components. External services appear only as optional,
   flag-gated **provider slots behind our own interfaces** where first-party
   is genuinely impossible (AI model hosting per the existing
   Gemini→Anthropic doctrine, platform publishing APIs, print *fulfilment*,
   music *rights*) — and the free/first-party path stays the default (P0.3
   discipline).
3. **The deterministic engine stays deterministic.** Parsers, detectors, the
   ranker, and colour-science maths are never AI-replaced. New pixel maths
   (filters, crops, transitions, autofit-class layout maths) is deterministic
   code; new *judgement* (which photo, which tone, which layout, which copy)
   goes through `media_ai.llm` / `ai_core.llm` with honest
   `ProviderNotConfigured` errors — never a heuristic fake.
4. **Approval before anything leaves the building.** Every publishing/scheduling
   feature inherits the P2.3 publish gate, the per-type `AutonomyLevel`
   defaults, the kill switch, and the audit ledger. Nothing in Phase 6 widens
   the autonomy exception.
5. **Hosted-only.** "Desktop app", "works offline", "self-host" features map to
   browser/PWA surfaces of the hosted SaaS — never a customer install
   (ADR-0011).
6. **Self-hosted fonts, always.** Every typography feature rides the existing
   first-party font pipeline (`scripts/fetch_fonts.py` and friends). No Google
   Fonts CDN, ever (`tests/test_self_hosted_fonts.py`).
7. **Standing exclusions hold.** Google Workspace connectors (Gmail, Drive,
   Calendar, Sheets, Docs, Slides) stay excluded; the *capability* (cloud
   import, calendar feeds) is delivered via Dropbox/OneDrive/upload and ICS
   instead. No gray-market LLM proxies (ADR-0007). Keys stay in env/`.env`.
8. **Licensing discipline.** Stock/music/font libraries enter only with clean
   licences (openly-licensed first, paid pools optional behind flags, per
   [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)); every paid provider
   stays optional with a free default (the P0.3 guard).
9. **Safety lines.** No synthetic AI-generated people unless explicitly
   requested per deployment; voice cloning only with recorded consent of the
   voice's owner; minors' content never auto-publishes (ADR-0003); AI media
   carries provenance (P6.22).

## Sequencing — where Phase 6 sits

- **Phase C still outranks everything.** Phase 6 is gated behind the same two
  hard gates as P3/P4/P5 (zero-founder-involvement onboarding; ≥10 clubs paying
  annually). Nothing here weakens "stop polishing and sell".
- **Pull-driven order.** Within Phase 6, items are built in the order paying
  clubs ask for them — the per-item sequence below is a default, not a promise.
- **Shared seams first.** Many packages ride seams that already exist
  (`creative_brief` design specs, `graphic_renderer`, the reel engines,
  `media_library`, `workflow`, `ai_core.ask_with_tools`, provider slots from
  P0.4). Each package names its seams so work lands additively.
- **Overlap rule.** Where a feature is already shipped or already has a roadmap
  ID (P3/P4/P5/PC), the row points there instead of duplicating it. Phase 6
  adds no second home for existing work.

Status legend used in the tables: **✅ shipped** (module named) ·
**🔵 partial** (seam exists, feature incomplete) · **🆕 P6.x** (new work, this
package) · **↗** (lives in another package/phase) · **🚫 adapted** (standing
exclusion; nearest compliant equivalent named).

---

## P6.1 — Smart format catalogue & format transformer

**What Canva/Adobe have.** Hundreds of design types (posters → photo books) and
1M+/220k+ template libraries; resize/reformat any design for any channel
("Magic Switch", "resize for any channel"); save-as-template; multi-page and
multi-design projects.

**The MediaHub shape.** One **format catalogue** that extends the post-type
taxonomy ([`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md)) with *off-feed*
formats clubs actually need — certificates, meet programmes, posters,
newsletters, yearbooks, training worksheets, season calendars, sponsor
proposals, membership cards — every one generated from run data + `BrandKit`
the same way cards are today, with confidence scores and explainability. A
**format transformer** generalises the shipped `turn_into` package (one meet →
seven outputs) into "turn *this* into *that*": any approved design re-targeted
to any catalogue format/size, with the design-spec director re-laying-out
content rather than naively scaling (the Magic-Switch behaviour). Each format =
a `FormatSpec` (canvas size(s), bleed/safe zones, data requirements via
`media_requirements`, archetype set, caption style) registered in
`club_platform/post_types.py`'s catalogue layer; rendering rides
`graphic_renderer` + `creative_brief` untouched.

**Build sketch.** (1) `club_platform/format_catalog.py` — `FormatSpec` registry
keyed by slug, with per-sport availability from `sport_profiles`; (2) a
catalogue UI on the pack/review surface ("make this a poster/certificate/…");
(3) `turn_into` v2 — `transform(design, target_format)` through the director;
(4) per-channel size presets (IG post/story/reel cover, FB cover, X, LinkedIn,
Pinterest, TikTok, YouTube thumbnail/banner) as `FormatSpec` data, replacing
nothing; (5) custom-size + blank-start escape hatch that still seeds from brand
tokens. Multi-page formats (programmes, yearbooks, photo books) compose
existing single-card renders into a paged PDF via the P6.12 document engine.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Social posts for every platform (IG posts/Stories/Reels, FB posts/covers, TikTok, YouTube thumbnails/banners, X, Pinterest, LinkedIn posts/banners, Tumblr, Lemon8) | 🔵 feed/story/reel shipped for IG-class sizes → 🆕 P6.1 per-channel `FormatSpec` presets for the rest |
| C1 | Posters · Flyers · Banners/yard signs (digital design side) | 🆕 P6.1 formats (`poster`, `flyer`, `event_banner`) from meet/fixture data; print output ↗ P6.19 |
| C1 | Business cards | 🆕 P6.1 `coach_card` / committee contact card from roster + brand kit; print ↗ P6.19 |
| C1 | Invitations · Greeting/thank-you cards · Postcards | 🆕 P6.1 club-event formats (awards night invite, volunteer thank-you, sponsor thank-you postcard) fed by `manual_entry` + sponsor kit |
| C1 | Resumes | 🆕 P6.1 `athlete_one_pager` — athlete CV/recruitment sheet from `history/` PBs + spotlight data |
| C1 | Brochures | 🆕 P6.1 `club_prospectus` (multi-page; composed via P6.12) |
| C1 | Wallpapers (desktop/phone) | 🆕 P6.1 `club_wallpaper` format (fan/parent giveaway) from brand tokens + venue/team imagery |
| C1 | Calendars · Planners | 🆕 P6.1 `season_calendar` / training planner from fixtures + key dates (P6.16 data) |
| C1 | Worksheets | 🆕 P6.1 training-set sheets / dryland worksheets from coach `manual_entry` |
| C1 | Certificates | 🆕 P6.1 `certificate` — PB/medal/participation certificates auto-filled per swimmer from run data; bulk ↗ P6.15 |
| C1 | Menus | 🆕 P6.1 `event_programme` (gala day programme/canteen sheet) from meet schedule |
| C1 | Photo books | 🆕 P6.1 `season_yearbook` (multi-page, media-library-driven; composed via P6.12) |
| C1 | Logos | 🆕 P6.1 crest/lockup variant generation (monochrome, knockout, badge forms) on top of the shipped DesignTokens lockup vocabulary — assistive, never replacing a club's crest |
| C1 | Custom-size designs (px/mm/in) | 🆕 P6.1 custom `FormatSpec` dimensions incl. print units |
| C1 | Multi-design projects ("One Design") | 🆕 P6.1 — a content pack already groups mixed outputs; add mixed-format packs (e.g. recap + poster + certificate batch in one pack) |
| C1 | Blank designs from scratch (preset/custom dimensions) | 🆕 P6.1 blank-start escape hatch seeded from brand tokens; manual editing ↗ P6.24 |
| C10 | 1M+ template library · templates by type/category | 🚫 adapted — archetype catalogue growth (12 → per-format sets) + format catalogue; deliberately *not* a template marketplace |
| C10 | AI template generation from prompt | ✅ shipped — the Tier B design-spec director generates layout specs from data/brief (`creative_brief/ai_director.py`); prompt-first entry ↗ P6.2 |
| C10 | Quick Create | 🆕 P6.1 one-click "make the obvious pack" per event, riding the P1.3 planner's top item |
| C10 | Brand Templates / bulk template autofill | ↗ P6.11 (locked brand formats) + P6.15 (autofill at scale) |
| C2 | Magic Switch (convert design to another format / resize / reformat; deck→doc transforms) | 🆕 P6.1 format transformer (`turn_into` v2 through the director); translation half ↗ P6.23 |
| A1 | 220,000+ professional templates | 🚫 adapted — same as C10: archetypes + formats, not blanks |
| A1 | Template categories (social, flyers, posters, banners, logos, invitations, cards, business cards, resumes, cover letters, brochures, menus, pamphlets, leaflets, certificates, worksheets, class schedules, book covers, album covers, product labels, gift certificates, ads, memes, collages, wallpapers, t-shirts) | 🆕 P6.1 — each becomes a `FormatSpec` where it has a club meaning (class schedule → training schedule; book/album cover → yearbook/season-mix cover; gift certificate → fundraiser voucher; meme → `meme` format with club in-jokes via caption engine; ads ↗ P6.16; collages ↗ P6.4; t-shirts ↗ P6.19; product labels ↗ P6.19) |
| A1 | Presentations, documents, web pages, carousels | carousels 🆕 P6.1 multi-image carousel format; presentations/docs ↗ P6.12; web pages ↗ P6.13 |
| A1 | Animated / multi-page / video templates | animated formats ↗ P6.10; multi-page ↗ P6.12 composition; video formats ↗ P6.5 |
| A1 | Print-ready templates; portrait/landscape/square/vertical orientations | 🆕 P6.1 orientation variants per `FormatSpec`; print-readiness ↗ P6.19 |
| A1 | Blank canvas with custom dimensions | 🆕 P6.1 (same escape hatch as C1) |
| A1 | Save any project as a reusable/shareable template + Favorites | 🆕 P6.1 "save as club format" — an approved design becomes a reusable org-scoped `FormatSpec` preset; favourites = pinned formats |
| A1 | Quick replace (swap content fast) | 🆕 P6.1 re-run a saved format against new data (the data-driven analogue of quick-replace) |
| A1 | Brand-controlled / locked templates with style restrictions | ↗ P6.11 brand controls |
| A8 | Switch between presentation and design | 🆕 P6.1 format transformer covers deck↔card transforms |
| A18 | Resize design for any channel (one click) | 🆕 P6.1 per-channel re-render from the persisted CreativeBrief (not pixel scaling) |
| A2 | Generate coloring pages (text → printable line art) | 🆕 P6.1 `kids_activity_sheet` format (mascot/venue colouring pages for junior sections) via the P6.3 image provider with line-art style |
| A10 | Drawing worksheets (100+ templates) · combine into coloring books | 🆕 P6.1 same `kids_activity_sheet` family; multi-page book via P6.12 |

---

## P6.2 — Conversational creative assistant & agentic editing

**What Canva/Adobe have.** Canva AI / AI 2.0 (conversational creation, voice
prompts, iterative agentic editing, layered object intelligence, Memory
Library, "Design for me"), the Canva Design Model, Magic Write
(generate/summarise/expand/rewrite, tone, 100+ languages), Adobe's AI Assistant
beta (conversational edit, voice commands, Imaging Subagent, smart prompt
suggestions), rewrite/text variations, text-to-template.

**The MediaHub shape.** A **club content copilot**: one conversational surface
(extending the shipped `free_text_chat` brief-builder) that can *create* ("make
a poster for Saturday's gala"), *edit iteratively* ("swap the photo, make the
headline punchier, more navy"), and *explain* ("why did this card outrank that
one?"). It operates by emitting **design-spec edits** — structured patches to
the persisted CreativeBrief/DesignSpec — executed by the deterministic
renderer, so the agent never paints pixels and every step stays auditable and
reversible. Tool calls ride the shipped `ai_core.ask_with_tools` bounded loop
with a fixed allow-list (read run data, read brand tokens, propose spec patch,
request render preview, never publish). Org-scoped **assistant memory** (the
Memory-Library analogue) extends the shipped semantic caption memory
(`memory/`, sqlite-vec) to remember preferences ("we never show times for
8-and-unders"). Magic-Write-class text tools (rewrite, shorten, expand, tone
shift) are added as caption-editor actions on the shipped caption engine.

**Build sketch.** (1) `assistant/` package: session store, tool registry,
spec-patch schema + validator (APCA/brand-token compliance re-checked per
patch); (2) chat UI panel on review/pack pages; (3) voice input as
browser-side speech capture feeding the same endpoint (ASR provider seam,
P5.3 — honest error until a provider lands); (4) caption text-tools menu
calling `web/ai_caption.py` with operation-specific prompts; (5) memory
writes gated behind explicit "remember this" + an org-visible memory list
(inspect/delete); (6) prompt suggestions derived from the P1.3 planner's
ranked items, not generic. Provider order Gemini→Anthropic as everywhere;
no provider → honest error, the UI's manual controls keep working.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Canva AI conversational assistant (text/voice/media prompts; "Design for me") | 🆕 P6.2 club content copilot on `free_text_chat` + `ai_core.ask_with_tools` |
| C2 | Canva AI 2.0 — conversational design, iterative agentic editing, layered object intelligence, persistent Memory Library | 🆕 P6.2 spec-patch agentic loop + org assistant memory (extends `memory/`); layer-aware edits via the DesignSpec's structured layers |
| C2 | Canva AI 2.0 six workflows | split: connectors ↗ P6.20 · scheduling ↗ P6.16 · web research ✅ shipped (`web_research/`) · brand intelligence ↗ P6.11 · Sheets AI ↗ P6.15 · Code 2.0 ↗ P6.13 |
| C2 | Canva Design Model (design-aware model: structure, layering, hierarchy, branding → fully editable output) | 🔵 partial — the Tier B design-spec director is exactly this pattern (LLM emits structured, editable specs; deterministic render); P6.2 extends it from generate-time to edit-time. "Available inside ChatGPT/Claude/Gemini" ↗ P6.20 (MCP server) |
| C2 | Magic Design (AI layout from prompt or uploaded media) | 🔵 partial — director generates from data; 🆕 P6.2 adds prompt-/photo-first entry ("here's a photo, make something") routed into the same brief flow |
| C2 | Magic Write (generate/summarise/expand/rewrite; tone adjustment; context awareness; 100+ languages) | 🔵 captions shipped (`web/ai_caption.py`, tone via voice profile) → 🆕 P6.2 editor text-tools (summarise/expand/rewrite/tone-shift) on any text block; languages ↗ P6.23 |
| C2 | Brand Voice (writes in your brand's tone) | ✅ shipped — `brand/voice_imitation.py` + learned voice store + few-shot caption examples |
| C2 | Guided Presentations (conversational goal/story/structure flow) | ↗ P6.12, driven by this assistant |
| C2 | Ask @Canva (tag the AI in a comment for feedback/generation) | ↗ P6.17 (assistant joins review threads) |
| A2 | AI Assistant beta (conversational create/edit; generate images; change backgrounds/text; replace objects; position/align/stylise; edit individual layers; toggle on/off; smart prompt suggestions; Imaging Subagent) | 🆕 P6.2 — same copilot; image operations delegate to P6.3 providers; assistant is per-org toggleable; suggestions seeded from the planner |
| A2 | Voice commands via microphone | 🆕 P6.2 voice input over the ASR provider seam (P5.3) |
| A2 | Generate captions / Caption Writer for social posts | ✅ shipped — `web/ai_caption.py` (few-shot brand voice, generate-many-then-dedupe, per-platform variants, AI-tell ban-list, approval loop) |
| A2 | Rewrite / text variations | 🆕 P6.2 text-tools (variations = the shipped generate-many-then-dedupe pattern applied to any text block) |
| A2 | Text to Template (generate fully editable template from a prompt) | 🆕 P6.2 prompt → `FormatSpec` + design spec (editable, brand-locked); catalogue home ↗ P6.1 |
| A2 | Font recommendations (AI-assisted) | ↗ P6.7 (assistant surfaces them) |
| A2 | Music recommendations | ↗ P6.6 |
| C3 | Point-and-click editing (click any subject/text/background to grab/move/remove/replace/adjust) | 🆕 P6.2 click-to-select bound to spec layers (select → patch); pixel-level ops ↗ P6.3/P6.4 |

---

## P6.3 — Generative imagery & image-AI services

**What Canva/Adobe have.** Text-to-image (Magic Media, Dream Lab, Firefly
Generate Image with styles/reference images), text-to-video clips (Veo-3,
Firefly Video), generative fill/expand/remove (Magic Edit/Eraser/Expand,
Generative Fill/Expand), subject lift (Magic Grab), text lift (Grab Text),
layer extraction (Magic Layers), style match, background generate/change,
upscale/enhance, generate-similar, mockups, 3D generation.

**The MediaHub shape.** One **image-AI provider layer** (`media_ai/imagine.py`)
behind which every generative-image capability sits, mirroring the LLM
wrapper's provider doctrine: Gemini-first (Imagen/Veo via the existing
`MEDIAHUB_GEN_BG` seam, generalised), optional alternates behind flags, honest
`ProviderNotConfigured` otherwise. Capabilities are exposed where volunteers
need them: backdrop generation for cards (shipped, opt-in), photo fix-ups on
media-library assets (remove the bin behind the podium = generative remove;
extend a too-tight crop for a story canvas = generative expand), subject lift
to feed the existing cutout/compositing path, upscale for low-res phone
photos before print (P6.19 needs this), and product mockups (club merch
previews from P6.19 assets on blanks). Every output is stamped with AI
provenance (P6.22) and never fabricates *results data* — generative pixels
are scenery, not facts.

**Build sketch.** (1) `media_ai/imagine.py` provider interface:
`generate(prompt, style, refs)`, `edit(image, mask, instruction)`,
`expand(image, target_box)`, `remove(image, mask)`, `upscale(image, factor)`,
`similar(image)`; (2) wire into media-library asset detail (fix-up actions)
and the card editor (background actions — replacing today's single-purpose
Imagen call); (3) subject lift = cutout provider + saliency, already on disk,
exposed as "lift subject"; (4) text lift (Grab Text) via Gemini vision OCR →
editable text block; (5) style presets curated to sport-editorial looks (no
"3D clay" gimmicks by default); (6) per-org generation quotas ↗ P6.22.
Text-to-video b-roll lands as a reel-scene provider (`visual/` scene source)
strictly opt-in like `MEDIAHUB_GEN_BG`. Layer extraction (Magic Layers) is the
inverse-render problem — scope to AI-image outputs only, where the provider
returns layers natively.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Magic Media: Text to Image (+ style presets) | 🆕 P6.3 `imagine.generate` (Gemini Imagen first), sport-editorial style presets |
| C2 | Dream Lab (15+ styles, reference image, prompt edits, quality tiers, Boost resolution, history, batch) | 🆕 P6.3 — reference-image conditioning, generation history per org, batch via P6.15; "Boost" = `upscale` |
| C2 | Magic Media: Text to Video · Create a Video Clip (Veo-3) | 🆕 P6.3 opt-in b-roll scene provider (Veo via Gemini API) feeding reel scenes ↗ P6.5 |
| C2 | AI 3D Model Generator / 3D Content Generator | 🆕 P6.3 deferred-last: 3D club crest/trophy renders for graphics via provider 3D endpoints when stable; library home ↗ P6.8 |
| C2 | Magic Edit (add/replace via prompt) | 🆕 P6.3 `imagine.edit` on media-library assets + card backgrounds |
| C2 | Magic Eraser (remove objects) | 🆕 P6.3 `imagine.remove` (mask-brush UI) |
| C2 | Magic Grab (lift/reposition photo subject) | 🔵 partial — cutout providers + `graphic_renderer/saliency.py` shipped; 🆕 P6.3 exposes "lift subject" as an editor action |
| C2 | Grab Text (select/edit text inside an image) | 🆕 P6.3 vision-OCR lift → editable, brand-fonted text block |
| C2 | Magic Expand (extend borders / change aspect with AI fill) | 🆕 P6.3 `imagine.expand` — pairs with saliency crops for story/print canvases |
| C2 | Magic Layers (extract editable layers from AI images) | 🆕 P6.3 scoped to provider-native layered outputs |
| C2 | Style Match (unify a design by matching look/feel) | 🆕 P6.3 re-style asset to brand tokens (palette/contrast respected via theming maths) |
| C2 | Magic Background (AI backdrop matching subject/layout/style) | ✅ shipped opt-in (`MEDIAHUB_GEN_BG` Imagen backgrounds) → 🆕 P6.3 generalises behind `imagine` |
| C2 | Background Generator / Background Changer (+ relighting/blend) | 🆕 P6.3 replace-background on cutout subjects with relight blend; procedural backdrop stays the no-key default |
| C2 | AI image upscaler / Enhancer (Upscale) | 🆕 P6.3 `imagine.upscale` (print pipeline dependency) |
| C2 | Magic Mockups / Mockups | 🆕 P6.3 merch/print mockups (card-on-poster, kit, mug) for P6.19 previews |
| C3 | Magic Eraser · Background Changer/Generator · Upscale · Style Match (photo-editor listings) | ↗ same P6.3 services surfaced in the P6.4 editor |
| C3 | Smartmockups / Mockups (photo-editor listing) | ↗ P6.3 mockups |
| C3 | Background Remover (one-click + Erase/Restore brushes, brush size) | ✅ shipped — `MEDIAHUB_CUTOUT_PROVIDER` (rembg default, Replicate/PhotoRoom optional); 🆕 P6.3 adds erase/restore touch-up brushes |
| C3 | Image Cutout (AI cutout) | ✅ shipped (same cutout layer) |
| A2 | Generate Image (styles, effects, colour/tone, lighting, camera angle, reference image, "Show Similar", 100+ prompt languages) | 🆕 P6.3 `generate` parameters + `similar`; prompt languages ↗ P6.23 |
| A2 | Generative Fill (insert/remove/replace via brush + prompt) · Insert or replace objects · Remove objects | 🆕 P6.3 `edit`/`remove` |
| A2 | Generative Expand / Expand image | 🆕 P6.3 `expand` |
| A2 | Generate Similar / on-style variations | 🆕 P6.3 `similar` |
| A2 | Generate Video (shot size, camera angle, camera settings) | 🆕 P6.3 b-roll provider ↗ P6.5 scenes |
| A3 | Image enhancement via AI Assistant (pose change, object swap, distraction removal) | 🆕 P6.3 ops driven from P6.2; pose-change gated by the no-synthetic-people rule (real-athlete edits stay conservative: distraction removal yes, body manipulation no) |
| A3 | Erase tool (brush/quick-select removal) | 🆕 P6.3 `remove` with brush UI (Adobe's Erase = same service) |
| A3 | Replace background | 🆕 P6.3 replace-background (cutout + generate) |

---

## P6.4 — Photo editor (deterministic ops + assists)

**What Canva/Adobe have.** A full photo editor: filters with intensity,
adjustments (brightness/contrast/saturation/warmth/tint/highlights/shadows/
sharpen/texture/white balance), effects (duotone, blur, pixelate, vignette,
glitch, grayscale, sepia, golden hour, matte B&W, colour punch, blend modes,
opacity), perspective sliders, crop/rotate/resize/flip, crop-to-shape, frames
and grids/overlays, focus/auto-focus + blur brush, one-click enhance, collages,
profile pictures, HEIC import, a standalone editor surface.

**The MediaHub shape.** A **media-library photo editor** — volunteers shoot on
phones in bad pool light; the wedge feature is *make this photo usable on a
card in 10 seconds*. All tone/colour/geometry operations are deterministic
Pillow/numpy pixel maths (consistent with the colour-science rule — fast,
reproducible, no LLM per slider). One-click **Enhance** is a deterministic
auto-levels/white-balance/denoise recipe tuned for indoor pools (and is allowed
to *suggest* via AI which recipe fits, through `media_ai`, never silently). AI
ops (erase/fill/background) come from P6.3. Edits are non-destructive: an edit
recipe stored beside the original in `media_library`, applied at render time,
so the same asset can carry different recipes per card.

**Build sketch.** (1) `media_library/photo_ops.py` — pure functions per
operation + a serialisable `EditRecipe`; (2) editor UI on asset detail
(sliders, filter strip with intensity, crop/rotate/flip, crop-to-shape mask
library, perspective); (3) `enhance_auto()` recipe + per-club tuning memory;
(4) collage/grid composer as a `FormatSpec` (photo grid formats) reusing
frames; (5) HEIC ingest via `pillow-heif` at upload; (6) profile-picture
export (square/circle crop presets per platform); (7) the "standalone editor"
is simply this surface reachable without a run. `score_asset` stays untouched
— recipes don't change selection maths.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C3 | Pixel Eraser (manual erase) | 🆕 P6.4 manual erase brush on the recipe layer (alpha mask), no AI needed |
| C3 | One-click Enhance / Auto-adjust | 🆕 P6.4 `enhance_auto()` deterministic recipe |
| C3 | Filters (adjustable, incl. Mono/Sepia) | 🆕 P6.4 filter strip with intensity (deterministic LUTs) |
| C3 | Effects — Duotone, Blur, Pixelate, Vignette, Glitch, Shadows (3D shadow), Auto-Focus | 🆕 P6.4 effect ops (duotone honours brand palette via theming maths) |
| C3 | Adjustments (brightness, contrast, saturation, tint, white balance, light, colour, texture) | 🆕 P6.4 adjustment sliders |
| C3 | Perspective adjustment (H/V sliders) | 🆕 P6.4 perspective transform (deterministic) |
| C3 | Crop, rotate, resize, flip | 🆕 P6.4 geometry ops (saliency-suggested crops shipped) |
| C3 | Frames and Grids (single/split-cell) | 🆕 P6.4 frame/grid masks; element frames ↗ P6.8 |
| C3 | Focus / Auto-Focus (focal point, fg/bg blur) | 🆕 P6.4 depth-ish blur via subject mask (cutout alpha) |
| C3 | Blur Brush (shape/size/intensity) | 🆕 P6.4 local blur on recipe layer — also the safeguarding tool (blur a bystander's face) |
| C3 | Colour correction / colour adjustment · Image colour settings | 🆕 P6.4 (same adjustment set) |
| C3 | Standalone Photo Editor (web + mobile) | 🆕 P6.4 run-independent editor surface; mobile via P6.21 PWA |
| C1 | Photo collages | 🆕 P6.4 collage composer (grid `FormatSpec`s) |
| A3 | Remove background (one-click) | ✅ shipped (cutout layer) — listed here for the A-doc; detail ↗ P6.3 |
| A3 | Resize image (social presets + custom) | 🆕 P6.4 export-resize; channel presets shared with P6.1 |
| A3 | Crop image (freeform, ratios, social presets) | 🆕 P6.4 |
| A3 | Crop into shapes (circle, heart, star, oval, square, triangle…) | 🆕 P6.4 shape-mask crops (mask library shared with P6.8 shapes) |
| A3 | Convert image formats (JPG/PNG/SVG/WebP, PNG↔JPG, →SVG, WebP→…) | ↗ P6.18 conversion engine |
| A3 | Photo filters (8 styles + variations; Shuffle; intensity; 30+ Photoshop-powered filters) | 🆕 P6.4 filter strip (+ shuffle = random pick UI sugar) |
| A3 | Adjustments (contrast, brightness, highlights, shadow, saturation, warmth, sharpen) | 🆕 P6.4 |
| A3 | Effects (duotone, grayscale, blur, opacity, blend modes, golden hour, matte B&W, colour punch) | 🆕 P6.4 (blend modes apply at composite time in the renderer) |
| A3 | Photo collages (manual, templates, preset grids) | 🆕 P6.4 collage composer |
| A3 | Frames and overlays; crop & shape (rotate, scale, nudge, flip) | 🆕 P6.4 + overlays ↗ P6.8 |
| A3 | Create profile pictures | 🆕 P6.4 profile-picture presets (club avatar with brand ring) |
| A3 | Enhance in a snap | 🆕 P6.4 `enhance_auto()` |
| A3 | Animated images (Spin, Pop, Jitter, Slide, Zoom, Pan, Wobble, Wind, colour/fade/blur) | ↗ P6.10 photo animations |
| A3 | Replace images; set image as page background | 🆕 P6.4 asset swap on spec layers (background-set = spec patch via P6.2) |
| A3 | HEIC image import | 🆕 P6.4 `pillow-heif` ingest |

---

## P6.5 — Video suite (timeline, captions, clip intelligence, recording)

**What Canva/Adobe have.** Multi-track timeline editors (Video 2.0; layer
videos/audio/graphics), trim/split/splice, scene view + Drop Zone, transitions,
beat sync, AI captions with styled caption layers, video background removal,
speed/reverse/mute, AI highlights/auto-trim, Clip Maker (long → short with
captions + reframing), screen/webcam recording, talking presentations, audio
sync, per-clip filters, video resize, instant reels, 4K, text/titles on video,
avatars.

**The MediaHub shape.** Today MediaHub renders video *programmatically*
(Remotion/FFmpeg reels from card data — already "Instant Reels" for meets).
P6.5 adds the **footage path**: clubs upload phone clips of races/celebrations,
and MediaHub turns them into branded reels with the same approval flow. The
centrepiece is **Clip Maker for sport**: ASR (P5.3) + scene/audio-energy
analysis finds the moments (race finish, cheer spike), reframes 16:9 → 9:16
around the subject (saliency on motion), burns styled captions from the
transcript, and stitches with the brand's motion system. A **timeline editor**
(in-browser, edit-decision-list over the FFmpeg engine) covers manual trim/
split/reorder/transitions/speed/mute/text-overlays without pretending to be
Premiere. Webcam/screen recording uses browser MediaRecorder into the media
library (coach announcements, "talking recap"). Every renderer feature stays
server-side (CLAUDE.md), cache-keyed under `DATA_DIR/motion_cache`.

**Build sketch.** (1) `video/` package: probe/ingest (clip metadata,
proxies), `edl.py` (edit decision list → FFmpeg filter graph; Remotion
equivalent comp), `moments.py` (deterministic energy/scene-cut scoring +
optional AI moment labelling via Gemini video understanding, honest-error
without provider); (2) caption layer: ASR seam → word-timed captions →
styled burn-in (brand fonts, safe zones) with an edit UI for timing/text;
(3) background removal for short clips via matting provider slot (server
`rembg`-video/MODNet class, cloud optional) — flagged, honest about 90s-class
limits; (4) recorder UI → media library; (5) per-clip filter/adjust =
P6.4 recipes applied as FFmpeg filters; (6) avatars: our own opt-in avatar
surface (provider video models behind our media-AI seam, not an embedded
avatar app) — explicitly-requested, clearly-disclosed, per the
no-synthetic-people rule.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Videos (full multi-track editor as a design type) | 🆕 P6.5 footage path + EDL timeline over the shipped reel engines |
| C2 | Magic Design for Video / Magic Video (AI social-ready cuts from clips + prompt) | 🆕 P6.5 Clip-Maker-for-sport (moments → branded cut) |
| C2 | Magic Animate (one-click animation/transitions across a design) | ↗ P6.10 |
| C4 | Multi-track timeline (Video 2.0): layer video/audio/graphics | 🆕 P6.5 EDL timeline (tracks: video, audio, caption, graphic overlays) |
| C4 | Trim, split, splice, layer with precision · direct clip editing from timeline · zoom into timeline | 🆕 P6.5 timeline ops |
| C4 | Visual audio waveforms for syncing | 🆕 P6.5 waveform strip (deterministic peaks) |
| C4 | Transitions (fade/slide/wipe/chop/dissolve; duration/direction; apply between all pages) | 🔵 crossfades shipped in reels → 🆕 P6.5 transition library + apply-all |
| C4 | Animation effects / transitions library | ↗ P6.10 motion presets, applied on video overlays |
| C4 | Beat Sync (auto-match audio beats to cuts) | 🆕 P6.5 beat grid (librosa-class onset detection, deterministic) snapping cuts |
| C4 | Captions / Subtitles (AI auto-generate; editable styled caption layer; manual timing) | 🆕 P6.5 ASR captions (P5.3 seam) + styled editable layer |
| C4 | Video Background Remover (no green screen, <90s) | 🆕 P6.5 video matting provider slot (flagged) |
| C4 | Speed control (speed up / slow-mo) | 🆕 P6.5 per-clip speed (race-finish slow-mo) |
| C4 | Highlights (AI surfaces best clips) · Auto-trim | 🆕 P6.5 `moments.py` scoring + suggested trims |
| C4 | Screen recording / online video recorder · record yourself presenting / talking presentations | 🆕 P6.5 browser recorder → media library (presenting context ↗ P6.12) |
| C4 | Audio sync | 🆕 P6.5 track alignment (waveform-assisted) |
| C4 | Enhance Voice (AI noise cleanup) · Balance All (volume levelling) | ↗ P6.6 audio services, surfaced on the timeline |
| C4 | Video filters, effects, adjustments (per-clip) | 🆕 P6.5 P6.4-recipes-as-FFmpeg-filters |
| C4 | Video upscaler, video reverse | 🆕 P6.5 reverse (FFmpeg) · upscale via provider (P6.3 class) — flagged |
| C4 | Magic Resize for video formats/aspect ratios | 🆕 P6.5 saliency-tracked reframe (16:9↔9:16↔1:1) |
| C4 | Add text/titles/moving text with animation | 🆕 P6.5 title overlays from brand type system (+ P6.10 presets) |
| C4 | Instant Reels (AI transforms footage into reels) | 🔵 data-driven meet reels shipped → 🆕 P6.5 footage-driven instant reel |
| C4 | Stock footage library (Artlist etc.); Video Marketplace | ↗ P6.8 stock layer (openly-licensed first) |
| A4 | Multi-track editor; layer timing; adjust layer timing; locate timed objects | 🆕 P6.5 timeline + per-layer timing inspector |
| A4 | Edit multiple videos in one file; Scene view (reorder, batch-edit); Drop Zone (compile clips into sequences) | 🆕 P6.5 scene strip + drop-zone ("dump your phone clips here" → ordered sequence) |
| A4 | Trim / Crop / Resize video (social presets + custom) | 🆕 P6.5 |
| A4 | Merge / combine videos | 🆕 P6.5 concat via EDL |
| A4 | Change speed (slow-mo → super-fast) · Reverse · Mute | 🆕 P6.5 |
| A4 | Convert video↔GIF/MP4 (GIF→MP4, GIF→Video, download as GIF) | ↗ P6.18 conversion engine |
| A4 | Remove background from video (+ restore) | 🆕 P6.5 matting slot (same as C4) |
| A4 | Caption video / auto captions (editable, 100+ languages; reposition) | 🆕 P6.5 captions; languages ↗ P6.23 |
| A4 | Video transitions; animations; layer objects (text/photos/elements) | 🆕 P6.5 overlay tracks |
| A4 | Add audio to video; voiceover; video self-record (webcam) | 🆕 P6.5 audio track + recorder; voiceover ↗ P6.6 |
| A4 | Slip Edit; scene trim/extend with snapping; collapse audio tracks | 🆕 P6.5 timeline ergonomics |
| A4 | Video controls in Presentation mode | ↗ P6.12 |
| A4 | 4K video support | 🆕 P6.5 4K ingest/export profiles (render cost gated ↗ P6.22 quotas) |
| A4 | Clip Maker (AI long→short, captions, reframing) | 🆕 P6.5 Clip-Maker-for-sport |
| A4 | Export/publish directly to Vimeo (add-on) | ↗ P4 publishing adapters (Vimeo as an optional target) |
| A2 | Text to Avatar / AI avatars (studio-grade talking avatar videos) | 🆕 P6.5 explicit opt-in only (no-synthetic-people rule); disclosed in-frame; provider behind flag |
| C17 | D-ID AI Presenters, HeyGen, Neiro, DeepReel (avatar apps) | ↗ P6.5 — covered by our own opt-in avatar surface, not by embedding those apps |

---

## P6.6 — Audio engine (music, SFX, voiceover, cleanup, rights)

**What Canva/Adobe have.** Stock + licensed music libraries (incl. popular
chart tracks with regional/usage caveats; TikTok Commercial Music Library),
SFX libraries, voiceover recording with noise cancellation, AI voiceover/TTS
(45–70+ voices, 20+ languages, pitch/speed/emotion controls, pronunciation
fixes, WAV download), AI music + SFX generation, trimming/volume/fades, up to
50 audio tracks, per-scene sync, upload own audio, audio fingerprint/Content-ID
checks, Enhance Speech, Extract Audio, Vocal Remover, AI dubbing, voice
changer, voice cloning, music recommendations, audio add-ons (EQ, cleaner,
visualizer).

**The MediaHub shape.** Reels need sound. P6.6 gives the reel/video engines a
proper **audio subsystem**: an openly-licensed music pool tagged by energy/
mood (the AI picks a track to match the reel's emotional arc — judgement via
`media_ai`, playback maths deterministic), club SFX (whistle, splash, crowd),
voiceover recording in-browser, the existing TTS surface grown into a real
voice layer (provider seam shipped: edge-tts today, Piper P5.2; add voice
catalogue, rate/pitch/emotion params, pronunciation overrides for athlete
names — a genuinely loved feature for results content), and **rights
discipline**: every track carries licence metadata, platform-specific
usability flags (what's safe for IG vs TikTok), and an upload fingerprint
check; chart-music libraries are explicitly *not* bundled until a licensed
provider integration exists (honest gap, flagged provider slot).

**Build sketch.** (1) `audio/` package: `library.py` (tracks + licence
metadata + mood/energy tags + platform flags), `select.py` (AI pick via
`media_ai`, honest-error), `ops.py` (trim/fade/gain/duck/extract — FFmpeg,
deterministic), `voice.py` (TTS provider seam extension: voice catalogue,
SSML-ish params, per-org pronunciation lexicon), `clean.py` (denoise/level —
RNNoise/ffmpeg loudnorm class, deterministic), `rights.py` (licence ledger +
fingerprint check on uploads); (2) timeline integration (P6.5 tracks, ducking
under voiceover); (3) browser voice recorder; (4) generation (music/SFX) as
optional providers behind flags (Lyria-class via Gemini when available) with
the library as the no-key default; (5) dubbing = translate (P6.23) + TTS;
voice *cloning* only with recorded consent of the voice owner, off by
default, per-org enable + audit. Vocal remover / stem split via a local
demucs-class provider slot (flagged; heavy).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | AI voiceovers (multi-language, voices, tone/pacing) | 🔵 TTS shipped (edge-tts opt-in; `MEDIAHUB_TTS_PROVIDER` seam, Piper ↗ P5.2) → 🆕 P6.6 voice catalogue + params + pronunciation lexicon |
| C2 | AI music generation (~30s tracks) | 🆕 P6.6 optional music-gen provider; licensed library is the default |
| C2 | AI sound effects generation | 🆕 P6.6 optional SFX-gen provider; SFX library default |
| C5 | Audio library (stock music, genres) | 🆕 P6.6 openly-licensed music pool with mood/energy tags |
| C5 | Popular music library (chart tracks, 60s, regional/non-commercial caveats) | 🚫 adapted — chart-music *rights* can't be built first-party; our own licensed pool stays the default, with a flag-gated rights slot behind our `library` interface + per-platform usability flags |
| C5 | Sound effects library | 🆕 P6.6 SFX pool (sport set first) |
| C5 | Voiceover recording / voice recorder (desktop + mobile) with AI noise cancellation | 🆕 P6.6 browser recorder + `clean.py` denoise |
| C5 | Audio trimming / clipping · Volume control (0–100, mute) · Fade in/out | 🆕 P6.6 `ops.py` |
| C5 | Multiple audio track layering (up to 50) | 🆕 P6.6 multi-track mix on the P6.5 timeline (sane cap, ducking built-in) |
| C5 | Audio sync with video / per-scene audio | 🆕 P6.6 per-scene assignment in reel specs |
| C5 | Upload own audio (MP3/M4A/WAV, 250MB) | 🆕 P6.6 upload + `rights.py` fingerprint/licence attestation |
| C5 | Ditto (Merlin-licensed uploads); audio fingerprint/Content ID checks | 🆕 P6.6 `rights.py` (fingerprint check; licensed-pool integrations optional) |
| C5 | Extract Audio · Vocal Remover · Enhance Voice · AI Dubbing · Voice Changer · Text to Speech · AI Voice Cloning | 🆕 P6.6 — extract (FFmpeg) · stem-split slot (flagged) · denoise · dubbing (P6.23 + TTS) · changer/cloning consent-gated, off by default, audited · TTS = the shipped seam |
| C4 | Enhance Voice (Pro) · Balance All (AI volume levelling) | 🆕 P6.6 `clean.py` + loudness normalisation (EBU R128) |
| C7 | Audio elements (in the elements tab) | 🆕 P6.6 library exposed as insertable elements |
| A5 | Add audio tracks; adjust (volume, fades, trim, speed) | 🆕 P6.6 `ops.py` (+ speed) |
| A5 | Add sound effects (library) | 🆕 P6.6 SFX pool |
| A5 | AI voiceover / Generate Speech (45–70+ voices incl. ElevenLabs-supplied, 20+ languages, pitch/speed/emotion/tone, fix pronunciation, WAV download) | 🆕 P6.6 voice layer (catalogue, params, lexicon, WAV export ↗ P6.18); premium hosted voices (ElevenLabs-class) = optional provider slots on our own TTS seam |
| A5 | AI voiceover add-ons (AiVOOV, WellSaid) | 🚫 adapted — provider slots behind the same TTS seam, not third-party add-on accounts |
| A5 | Music: royalty-free stock; TikTok Commercial Music Library; music recommendations with thumbs up/down | 🆕 P6.6 our own library + AI `select.py` recommendation w/ feedback memory; platform-licensed pools (TikTok-CML-class) only through the same flag-gated rights slot, never a bundled third-party app |
| A5 | Enhance Speech (noise removal) | 🆕 P6.6 `clean.py` |
| A5 | Animate from audio (character lip-sync) | ↗ P6.10 mascot animation (audio-driven) |
| A5 | AI Assistant audio controls (volume/fades/trim/speed/mute/timing) | ↗ P6.2 assistant patches audio spec; ops in P6.6 |
| A5 | Audio add-ons (Audio Equalizer, AI Audio Cleaner, Audio Visualizer, Voice Maker…) | 🆕 P6.6 EQ + cleaner in `ops.py`/`clean.py`; waveform-visualizer overlay as a reel scene element; "voice maker" = TTS catalogue |
| A6 | Add tone/emotion in voiceovers | 🆕 P6.6 TTS emotion/params |
| A2 | Generate Speech / AI voiceover (Firefly Speech) | 🆕 P6.6 (same voice layer; counted under A2 in the index) |
| A2 | Enhance Speech (A2 listing) | 🆕 P6.6 `clean.py` |

---

## P6.7 — Typography system & text effects

**What Canva/Adobe have.** Huge font libraries, custom font upload, AI font
pairing, search by style/mood, text effects (Shadow, Lift, Hollow, Splice,
Echo, Glitch, Neon, Background, Curve), 3D extrusion and warp apps, effect
template packs, gradients on text, rich formatting (lists, links, line height,
decimals, strikethrough), copy-style, find & replace, spellcheck, dynamic
text, generated AI text effects.

**The MediaHub shape.** Grow the brand type system, keeping the two standing
rules absolute: fonts are **self-hosted on every surface** (web, Playwright
renderer, Remotion — the existing fetch/regen scripts extend to a curated
library), and pairing-class *judgement* ("which face fits this club")
goes through `media_ai` while the rendering maths (curve paths, autofit,
extrusion geometry) stays deterministic CSS/SVG. Club font upload matters for
crest-locked brands (licence attestation at upload, then the font joins the
self-hosted pipeline for that org only). Text effects ship as a tokenised
effect vocabulary in the DesignSpec (the director can request `neon` or
`splice` only where APCA contrast still passes — the theming engine polices
it).

**Build sketch.** (1) extend the font pipeline: `fonts/catalog.json`
(curated OFL faces + per-org uploads under `DATA_DIR/fonts/<org>/`),
`scripts/fetch_fonts.py` regen, renderer + Remotion font registration kept in
lock-step (`tests/test_self_hosted_fonts.py` extended); (2)
`graphic_renderer/text_effects.py` — deterministic effect primitives
(shadow/lift/hollow/splice/echo/glitch/neon/background, curve-on-path,
extrude via layered offsets, warp via SVG path deformation) exposed as
DesignSpec tokens; (3) AI pairing: `brand/type_pairing.py` proposes pairings
from the catalogue with reasons (honest-error without provider); (4) editor
formatting depth (lists, links, line-height, strikethrough, decimal sizes,
copy-style, find & replace, spellcheck via browser/`hunspell`-class —
deterministic); (5) "generate text effect" (AI texture inside letterforms) =
P6.3 imagery clipped to glyph masks; (6) dynamic text = data-bound text
fields in specs (already how cards work — exposed as a first-class editor
concept).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C6 | Font library (hundreds of free + premium fonts) | 🆕 P6.7 curated self-hosted OFL catalogue (never CDN) |
| C6 | Font upload (custom/purchased, with permissions) | 🆕 P6.7 per-org upload + licence attestation → self-hosted pipeline |
| C6 | Font pairing suggestions | 🆕 P6.7 `brand/type_pairing.py` via `media_ai` |
| C6 | Text effects (style): Shadow, Lift, Hollow, Splice, Echo, Glitch, Neon, Background | 🆕 P6.7 deterministic effect tokens (APCA-policed) |
| C6 | Text effects (shape): Curve | 🆕 P6.7 curve-on-path |
| C6 | TypeExtrude (3D extruded text: length, angle, outline) | 🆕 P6.7 extrude primitive (layered offsets) |
| C6 | TypeCraft (bend/warp/twist/reshape letters) | 🆕 P6.7 warp primitive (SVG deformation) |
| C6 | Text Studio Maker (3,000+ effect templates) | 🚫 adapted — a tokenised effect vocabulary the director composes, not a template pile |
| C6 | Text formatting (colour, alignment, underline, strikethrough, links, lists/markers/levels, line height, size/weight/style) | 🆕 P6.7 editor formatting depth |
| C6 | Gradients on text | 🆕 P6.7 gradient fills from brand palette |
| C6 | Multilingual support (100+ languages; interface languages) | ↗ P6.23 (fonts here must carry the needed scripts) |
| C6 | Dynamic text / captions | 🆕 P6.7 data-bound text fields (cards already do this; surfaced in the editor) |
| C6 | Text animations | ↗ P6.10 kinetic-type presets |
| C2 | Magic Morph (transform text/shapes with AI textures via prompt) | 🆕 P6.7 AI texture-in-glyph (P6.3 imagery clipped to masks) |
| A2 | Generate Text Effect (AI textures/styles on letters) | 🆕 P6.7 same texture-in-glyph service |
| A6 | Add/edit text; titles/headings/body defaults; text hierarchy | 🔵 hierarchy exists in specs → 🆕 P6.7 editor exposure |
| A6 | Tens of thousands of Adobe Fonts; custom upload; pairing/recommendations; search by style/mood | 🆕 P6.7 catalogue + upload + AI pairing + mood search (catalogue tags) |
| A6 | Character/paragraph styling (colour, alignment, underline, strikethrough, size incl. decimals, weight, italic, line height, lists with nesting/markers, links) | 🆕 P6.7 formatting depth |
| A6 | Copy text style (paintbrush); uppercase transform; find & replace; spellcheck (primary language) | 🆕 P6.7 editor tools (deterministic) |
| A6 | Curved text; shadow effects on text | 🆕 P6.7 effect tokens |
| A6 | Text animations | ↗ P6.10 |
| A6 | Auto-create hyperlinks | 🆕 P6.7 (links live in PDF/doc/web outputs; plain images ignore them) |

---

## P6.8 — Elements, stock & drawing

**What Canva/Adobe have.** Million-element graphic/sticker/icon/shape/line
libraries, AI shape generator, stock photo/video/audio integrations (Pexels,
Pixabay, Adobe Stock's 200M+), gradients, backgrounds, frames/grids, custom
emojis, GIFs, 3D elements, drawing tools (brushes, symmetry, snap-to-shape,
colouring mode, Shape Assist), element search with contextual recommendations.

**The MediaHub shape.** A **sport-editorial element library** — small and
curated beats huge and generic. Ship element packs that clubs actually
compose: sport pictograms (strokes, distances, lane ropes, podium), score/
stat chips, ribbons/badges/medals, dividers, texture overlays, frames — all
recolourable through brand tokens (SVG with token slots), so every element is
automatically on-brand. Stock comes in licence-clean via Openverse/Wikimedia
(+ optional paid pools behind flags) and through the shipped `venue_search`
(pool/venue backdrops). Element *choice* is already AI territory (the
director); the elements tab adds human browse + AI search ("something for a
relay") via embeddings over element descriptions. Drawing is a light
annotate layer (freehand → smoothed SVG, Shape Assist snap) for coach
telestration on photos — not an illustration suite.

**Build sketch.** (1) `elements/` package: SVG element packs with token
slots + metadata (sport, mood, tags, embedding); loader + org-custom packs;
(2) search: embedding index (reuses `memory/` sqlite-vec infra) + tag
filters; contextual suggestions from card context (`context_engine`); (3)
our own stock library: `elements/stock.py` curates a licence-clean pool
seeded by harvesting open collections (Openverse/Wikimedia as *sources*,
not in-product pickers), licence/attribution metadata persisted per asset
(rights ledger shared with P6.6); paid stock stays an optional flag-gated
source feeding the same pool; (4) `draw/` annotate layer: pointer-capture freehand, RDP smoothing,
shape-snap (deterministic), stored as a spec layer; (5) shape generator =
P6.3 generate with vector-style preset → traced SVG (flagged); (6) custom
emoji/sticker = club mascot pack (cutout + P6.10 animated sticker export);
(7) GIF/sticker search only via licence-clean sources.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C7 | Graphics library (1M+ elements) | 🚫 adapted — curated sport-editorial packs, brand-token recolourable |
| C7 | Stickers | 🆕 P6.8 sticker packs (+ club mascot stickers; animated ↗ P6.10) |
| C7 | Icons | 🆕 P6.8 icon set (sport pictograms first) |
| C7 | Shapes + Shape Generator (AI unique shapes) | 🆕 P6.8 shape library; AI generator via P6.3 → traced SVG |
| C7 | Lines | 🆕 P6.8 line/divider set |
| C7 | Photos library (stock) | 🆕 P6.8 our own licence-clean photo pool (open-collection seeded; paid sources flag-gated); venue shots ✅ shipped (`venue_search`) |
| C7 | Stock videos | 🆕 P6.8 our own licence-clean stock-video pool (feeds P6.5) |
| C7 | Gradients | 🆕 P6.8 gradient presets from brand palette (linear/radial) |
| C7 | Tables · Charts/Graphs (20+ types) · Interactive charts (Flourish embeds) | ↗ P6.9 |
| C7 | Draw / Drawing tools (freehand, Shape Assist) | 🆕 P6.8 annotate layer (telestration) |
| C7 | 3D elements (3D Content Generator) | 🆕 P6.8 3D-render element pack (crest/trophy renders via P6.3, cached as images) |
| C7 | AI-Powered Elements (generate photos/videos/code/icons/shapes/3D from the Elements tab) | 🆕 P6.8 "generate an element" entry → P6.3 services (code widgets ↗ P6.13) |
| C7 | Frames, grids | 🆕 P6.8 frame/grid elements (shared masks with P6.4) |
| C7 | Custom emojis | 🆕 P6.8 club emoji/mascot pack |
| C7 | Backgrounds | 🆕 P6.8 background packs + `venue_search` ✅ + P6.3 generation |
| C4 | Stock footage library (Artlist etc.) / Video Marketplace | 🆕 P6.8 our own stock-video pool (licence-clean default; paid sources flag-gated) |
| A10 | Draw with brushes (markers, pencils, paints, colours) | 🆕 P6.8 annotate brushes (stylised strokes) |
| A10 | Draw with symmetry; snap to shape; coloring mode (stay in lines) | 🆕 P6.8 symmetry mirror + shape-snap; colouring mode pairs with `kids_activity_sheet` (P6.1) |
| A11 | Adobe Stock integration (200M+ assets) | 🚫 adapted — our own curated pool (open-collection seeded) instead of a vendor stock integration; paid sources optional behind flags |
| A11 | Icons, shapes, backgrounds, overlays, frames, graphics, stickers, GIFs | 🆕 P6.8 element packs (GIF/sticker sources licence-clean) |
| A11 | Grids | 🆕 P6.8 |
| A11 | Gradients (linear/radial, prompt-driven) | 🆕 P6.8 presets; prompt-driven gradient = brand-palette interpolation via `media_ai` suggestion |
| A11 | Design elements search & browse; contextual recommendations | 🆕 P6.8 embedding search + `context_engine`-aware suggestions |
| A11 | Color themes; apply color themes; custom gradients; import from Adobe Color | ↗ P6.11 palette layer (Adobe-Color import = palette-file import) |
| A11 | QR code generator (custom colour/style/logo; PNG/JPEG/PDF/SVG) | ↗ P6.13 |
| A11 | Charts; tables (add/customize) | ↗ P6.9 |

---

## P6.9 — Charts, infographics & data storytelling

**What Canva/Adobe have.** 20+ chart types editable via data table, CSV
import, interactive charts (Flourish: treemaps, packed circles, maps), Magic
Charts (data→chart with recommendations, real-time sync), Magic Insights (AI
analysis: patterns, trends, takeaways), Magic Formulas, infographics,
diagram types (mind maps, flowcharts, org charts, Gantt, timelines, T-charts,
synoptic tables, Kanban, roadmaps, journey maps), scrollable data
storytelling.

**The MediaHub shape.** This is home turf: MediaHub already *owns* clean,
parsed, trustworthy results data — the one thing Canva never has. P6.9 turns
the canonical store + `history/` into **stat graphics**: season progression
lines per swimmer, PB drop charts, medal tables, club-record boards,
relay-split bars, attendance/entry trends — every chart a brand-themed SVG
rendered deterministically (the numbers are sacred; no LLM draws axes), with
the *choice* of which chart tells the story made by the AI ("Magic Charts"
behaviour) and **Insights** — AI-written takeaways grounded in detector
output ("8 of 12 swimmers PB'd — best conversion this season"), each
takeaway carrying its source rows (explainability rule). Diagram formats
(org chart, season timeline/roadmap, training flowchart) become data-driven
`FormatSpec`s fed from roster/fixtures.

**Build sketch.** (1) `charts/` package: typed chart specs (bar, line, pie,
donut, scatter, table, medal table, progression, split ladder…) → SVG via a
deterministic renderer (matplotlib-free, brand-token styled), embedded into
cards/docs/sites; (2) data plumbing: chart series builders over `canonical.*`
+ `history/` + CSV upload (P6.15 hub); (3) `charts/recommend.py` — AI picks
chart type + headline stat with reasons (honest-error); (4)
`charts/insights.py` — AI takeaways constrained to provided aggregates
(numbers computed deterministically first; the LLM phrases, never
calculates); (5) diagram `FormatSpec`s (org chart from committee roster,
season timeline from fixtures, journey = athlete career map from history);
(6) scrollytelling = multi-page story export (P6.12/P6.13) where each page
reveals one chart beat; interactive variants ship as microsite widgets
(P6.13), static-first everywhere else.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Infographics | 🆕 P6.9 stat-graphic `FormatSpec`s from results data |
| C1 | Mind maps, flowcharts, org charts, Gantt, timeline charts, T-charts, synoptic tables, Kanban boards, roadmaps, customer journey maps | 🆕 P6.9 data-driven diagram formats (committee org chart, season timeline/Gantt, training flowcharts, athlete journey); Kanban ↗ P6.16 planner board |
| C2 | Magic Charts (AI data-to-chart + recommendations) | 🆕 P6.9 `recommend.py` over canonical results |
| C2 | Magic Insights (AI patterns/trends/takeaways) | 🆕 P6.9 `insights.py` — grounded, source-linked takeaways |
| C7 | Tables (table maker) | 🆕 P6.9 brand-styled table spec (heat sheets, results tables) |
| C7 | Charts/Graphs (20+ types, editable data table, CSV import) | 🆕 P6.9 chart spec library + CSV series input |
| C7 | Interactive charts (Magic Charts, Flourish embeds — treemaps, packed circles, maps) | 🆕 P6.9 static-first; interactive widgets on microsites ↗ P6.13 |
| C11 | Magic Charts (data-to-chart, real-time sync) | 🆕 P6.9 charts re-render when run data updates (spec-bound series) |
| C11 | Magic Insights (AI data analysis) | 🆕 P6.9 `insights.py` |
| C11 | Match & Move animation / Scrollable Designs for data storytelling | scroll-story export 🆕 P6.9/P6.12; match-&-move motion ↗ P6.10 |
| A11 | Charts (elements listing) | 🆕 P6.9 |
| A11 | Tables (add/customize) | 🆕 P6.9 |
| C1 (cross-ref A1) | Infographics (Adobe template category) | 🆕 P6.9 (same formats; indexed under A1 in the completeness table) |

---

## P6.10 — Animation & motion system

**What Canva/Adobe have.** Page/element/text animations with preset libraries
(Canva: Block/Fade/Pan/Rise/Tumble/Breathe/Typewriter/Ascend/Shift/Bounce/
Burst/Roll/Skate/Drift/Tectonic/Baseline + Pop/Stomp/Neon/Scrapbook/Slide/
Merge/Flicker; Adobe: Bungee/Fade/Flicker/Grow/Pop/Shrink/Slide/Spin/Tumble +
loops Blinking/Bob/Breathe/Jitter/Pulse/Wiggle/Yoyo), photo motion
(Flow/Rise/Zoom; Spin/Pop/Jitter/Slide/Zoom/Pan/Wobble/Wind), custom motion
paths with orient-to-path, Match & Move shared-element transitions, click
order/timing, add-on effects, page transitions (dissolve, slide, wipes,
match-&-move), dynamic physics presets (Wobble/Wind/Breeze/Turbulence/Bounce
Loop), in/loop/out model with intensity/speed/direction/personality, animate
from audio, Magic Animate (AI one-click), animated stickers, reduce-motion,
limits (10s per animation, 50 per design).

**The MediaHub shape.** A **brand motion vocabulary**: a tokenised preset
library (named easings, durations, energy levels) implemented once and
consumed by both reel engines (Remotion comps and the FFmpeg engine's filter
recipes), plus CSS keyframe export for web/story HTML surfaces. The
*selection* of motion is the SEQ-4 pattern already shipped (archetype-matched
motion per scene); P6.10 widens the vocabulary and exposes manual overrides.
"Magic Animate" = the director assigns one coherent motion family to a whole
design (it must pass the no-over-animation UI rule — motion for feedback and
hierarchy, not decoration). Match & Move is the reel crossfade grown into
shared-element transitions (same athlete photo morphs position/size between
scenes). Reduce-motion is honoured end-to-end (a still-respecting variant of
every preset).

**Build sketch.** (1) `motion/vocabulary.py` — preset registry (`in/loop/out`
× energy × direction), each preset defined as keyframe data; compilers:
Remotion (`remotion/src/motion/`), FFmpeg filter recipe, CSS keyframes; (2)
DesignSpec motion tokens (per-element `enter/loop/exit`, per-page transition,
click/timing order for deck surfaces); (3) shared-element transition support
in both engines (position/scale/colour interpolation keyed by stable element
ids); (4) physics-flavoured presets implemented as parametric curves
(deterministic — no simulation per render); (5) photo-motion (Ken Burns
family: shipped in the FFmpeg engine) extended with the named presets; (6)
audio-driven timing: beats from P6.5's beat grid drive preset timing; mascot
lip-sync (animate-from-audio) as a later opt-in on the avatar rule's safe
side (a *mascot*, not a person); (7) caps + reduce-motion mirrored from the
source products as accessibility guardrails.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C8 | Page animations + Element animations (Page/Element/Text tabs) | 🆕 P6.10 motion tokens per element/page |
| C8 | Animation presets (free + Pro lists) | 🆕 P6.10 preset vocabulary (named set covering the Canva/Adobe families) |
| C8 | Photo movement (Photo Flow/Rise/Zoom) | 🔵 Ken Burns shipped (FFmpeg reel) → 🆕 named photo-motion presets |
| C8 | Create an Animation (Motion Path) + orient-to-path + speed slider | 🆕 P6.10 path animations (SVG path + orient flag) |
| C8 | Match & Move (shared-element page transition) | 🆕 P6.10 shared-element transitions in both reel engines |
| C8 | Magic Animate (AI one-click animation + transitions) | 🔵 SEQ-4 archetype-matched motion shipped → 🆕 whole-design motion-family assignment |
| C8 | Appear on click / Click order | 🆕 P6.10 click/step order (deck surfaces ↗ P6.12) |
| C8 | Show element timing (timing/duration) | 🆕 P6.10 timing inspector |
| C8 | Add-on effects combined with base animations | 🆕 P6.10 composable `loop` layer on top of in/out |
| C8 | Page transitions (Dissolve/Fade, Slide, Color Wipe, Line Wipe, Circle Wipe, Match & Move) | 🔵 crossfade shipped → 🆕 transition set in both engines |
| C8 | Reduce motion accessibility setting | 🆕 P6.10 reduce-motion variants honoured everywhere |
| C8 | Limits (10s per animation; 50 per design) | 🆕 P6.10 engineering caps (sanity + render cost) |
| A3 | Animated images (Spin, Pop, Jitter, Slide, Zoom, Pan, Wobble, Wind, colour/fade/blur animations) | 🆕 P6.10 photo/sticker animation presets (GIF/MP4 export ↗ P6.18) |
| A12 | Animate all (one click) or per-element (text, icons, shapes, letters, photos, videos) | 🆕 P6.10 whole-design family + per-element overrides |
| A12 | In / Loop / Out model; presets (Bungee, Fade, Flicker, Grow, Pop, Shrink, Slide, Spin, Tumble); loops (Blinking, Bob, Breathe, Jitter, Pulse, Wiggle, Yoyo) | 🆕 P6.10 in/loop/out is the vocabulary's native model |
| A12 | Visibility/Move/Scale animations; intensity, speed, direction, personality controls | 🆕 P6.10 preset parameters |
| A12 | Start/end outside page | 🆕 P6.10 off-canvas keyframes |
| A12 | Dynamic physics presets (Wobble, Wind, Breeze, Turbulence, Bounce Loop) | 🆕 P6.10 parametric physics-flavoured curves |
| A12 | Page transitions in multi-page designs | 🆕 P6.10 |
| A12 | Animate from audio (character animation lip-sync) | 🆕 P6.10 mascot lip-sync (audio-driven, opt-in; never a synthetic person) |
| A12 | Animated stickers | 🆕 P6.10 animated mascot/sticker exports (↗ P6.8 packs) |
| A12 | Animated images export as GIF | ↗ P6.18 GIF export |
| A8 | Animation sequencing / click order (Adobe presentations) | 🆕 P6.10 step order (surfaced in P6.12) |

---

## P6.11 — Brand platform depth

**What Canva/Adobe have.** Multiple brand kits (up to 100), Brand Kit Builder
(auto-extract from website/PDF), brand templates, Brand Controls (restrict
colours/fonts; require approval), a Brand Kit homepage (logos, templates,
colours, guidelines, tone, product photography), in-editor brand guidelines,
Brand Assist (real-time on-brand suggestions + auto-fix), Brand Check (beta),
brand folders, colour themes, approval workflows with group approvers,
team-level kit sharing, personal kits, role-based permissions, replace
logo/image across designs, one-tap apply, multi-brand referencing (up to 5
per design).

**The MediaHub shape.** MediaHub's brand layer is already deep (BrandKit,
brand-DNA-from-URL P1.5, PDF guidelines ingestion, voice imitation, DTCG
tokens, the theming engine). P6.11 completes it as a **brand platform**:
multiple kits per org with roles — primary club kit, **sponsor kits**
(sponsor co-branding is a first-class club need: lockup pairing rules, clear
space, sponsor-safe placements), event sub-brands (annual gala identity),
and team/section kits — plus **brand governance**: locked tokens (a
volunteer can't ship off-palette), a Brand Check pass that scores any design
against the kit (deterministic checks: palette ΔE, font compliance, logo
clear-space, contrast — plus AI advisory notes), auto-fix proposals, and a
brand home page per org assembling kit + guidelines + tone + approved
imagery. "Replace across designs" = regenerate affected packs from their
persisted briefs after a kit edit (the data-driven advantage: nothing is
hand-placed).

**Build sketch.** (1) multi-kit schema on `ClubProfile` (kit id per pack/
format; sponsor kits with pairing rules consumed by the sponsor_activation
type); (2) `brand/check.py` — deterministic compliance scorer (reuses
theming maths: CIEDE2000 distance to palette, APCA, clear-space geometry) +
`media_ai` advisory layer; auto-fix = spec patches (P6.2 machinery); (3)
brand home route assembling kit, guidelines (shipped ingestion), voice
profile, do/don't imagery; (4) governance: per-role token locks
(`workflow`-level enforcement at approval), group-approver rules on
CardStatus transitions (↗ P6.17 for the workflow UI); (5) kit-edit →
re-render sweep over persisted briefs with diff preview; (6) palette-file
import (Adobe Color `.ase`/JSON → kit palette through the existing
evidence-grounded pipeline).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C9 | Brand Kit(s) — logos, colours, fonts, icons, imagery, graphics, brand voice (up to 100 kits) | 🔵 single BrandKit + voice shipped → 🆕 P6.11 multi-kit (sponsor/event/section kits) |
| C9 | Brand Kit Builder (auto-extract from website or PDF) | ✅ shipped — URL: P1.5 local brand-DNA; PDF: `brand/guidelines.py` + `dna_capture.py` |
| C9 | Brand Templates (reusable on-brand templates) | 🆕 P6.11 locked org formats (a saved `FormatSpec` + kit binding; catalogue ↗ P6.1) |
| C9 | Brand Controls (restrict colours/fonts; require design approval) | 🆕 P6.11 token locks + approval-required rule (approval flow ✅ shipped in `workflow/`) |
| C9 | Brand Kit homepage (logos/templates/colours/guidelines/tone/product photography hub) | 🆕 P6.11 brand home route |
| C9 | Brand Guidelines accessible in editor with usage guidance | 🔵 guidelines ingestion shipped → 🆕 in-editor surfacing |
| C9 | Brand Assist (real-time on-brand suggestions + auto-fix for colours/fonts/logos/photos/icons) | 🆕 P6.11 `brand/check.py` + auto-fix spec patches |
| C9 | Brand folders / linked folders | ↗ P6.17 folders (kit-scoped views) |
| C9 | Color themes / palettes | ✅ shipped — theming engine (DTCG palette, MD3 roles) |
| C9 | Approval workflows (group approvers, approval rules) | 🔵 per-card approval + publish gate shipped → 🆕 group-approver rules ↗ P6.17 |
| C9 | Team-level brand sharing (kits/templates to specific teams) | 🆕 P6.11 kit sharing across workspaces (org → section) |
| C9 | Personal Brand Kits | 🆕 P6.11 personal kits (e.g. a coach's own side projects) — low priority, same schema |
| C9 | Role-based permissions for AI/brand features | 🆕 P6.11 role flags (consumed by P6.22 governance) |
| C9 | Replace logos/images across designs in a few clicks | 🆕 P6.11 kit-edit re-render sweep from persisted briefs |
| A13 | Brand kits (logos, colours, fonts, graphics; one-tap apply; multiple kits premium) | 🆕 P6.11 multi-kit + one-tap apply (= re-theme via tokens) |
| A13 | Custom fonts in brands; colour themes in brands; apply brand to pages/images/illustrations | 🆕 P6.11 (fonts ↗ P6.7 pipeline; apply-to-image = brand-aware duotone/recolour via P6.4) |
| A13 | Brand style restrictions / template control | 🆕 P6.11 token locks |
| A13 | Multi-brand referencing (up to 5 brands per template) | 🆕 P6.11 sponsor co-branding (multi-kit composition rules) |
| A13 | Brand Check (beta) | 🆕 P6.11 `brand/check.py` |
| A13 | Share/leave brands; edit roles | 🆕 P6.11 kit membership + roles (rides PC.3 tenancy) |
| A11 | Import color themes from Adobe Color | 🆕 P6.11 palette-file import (.ase/JSON) |
| C2 | Canva AI 2.0 brand-intelligence workflow | 🆕 P6.11 brand check/assist as assistant tools (via P6.2) |

---

## P6.12 — Documents, decks & the PDF suite

**What Canva/Adobe have.** Collaborative docs with embedded charts and
"Scrollables", presentations (presenter view/notes, remote control, Canva
Live audience Q&A/polls, Magic Shortcuts, autoplay, offline presenting,
live edits while presenting, record-yourself, expand-to-whiteboard,
deck→video, exports), AI presentation generation, full PDF tooling (convert
to/from Word/Excel/PowerPoint, edit PDF, merge, organise pages, accessibility
tags, 20+ scripts, gradients, CMYK), document import/export (PPTX, DOCX),
multi-page management.

**The MediaHub shape.** Clubs run on three documents: the **meet programme**,
the **committee/season report**, and the **sponsor proposal** — plus the AGM
deck. P6.12 builds one **document engine**: multi-page, brand-tokened
compositions assembled from the same card/chart/text primitives (Playwright
already renders HTML → the engine adds paged HTML → PDF with print CSS), an
AI outline-then-build flow for decks and reports (data-grounded: season
report pulls real aggregates via P6.9), and a **presenter surface** for the
deck format (presenter notes, timer, autoplay, phone-as-remote via the
existing session infra, record-a-talkover via P6.5's recorder). PDF
*utilities* (merge/organise/convert) ship as honest, bounded tools on the
export surface (pypdf-class, deterministic) because committee volunteers
genuinely need them — not as an Acrobat clone.

**Build sketch.** (1) `documents/` package: paged `DocumentSpec` (sections →
blocks: text, card-embed, chart-embed, table, media), HTML/print-CSS
renderer → PDF (Playwright `page.pdf`, CMYK/bleed handled in P6.19); (2)
deck mode: same spec, slide-sized pages + step order (P6.10) + presenter
route (notes, timer, remote pairing code) + autoplay; (3) AI flows:
outline→draft for `season_report`, `sponsor_proposal`, `agm_deck`,
`meet_programme` formats (all data-grounded, honest-error); (4) exports:
PDF (standard/print), PPTX/DOCX via deterministic converters
(python-pptx/docx) for take-it-elsewhere editing, deck→MP4 via the reel
engine (each slide a scene); imports: PPTX/DOCX/PDF → blocks (fidelity
bounded and stated); (5) PDF utilities: merge, reorder/rotate/delete pages,
images→PDF, PDF→images, with a11y tagging on export (tagged headings/alt
text from the spec); (6) "Scrollables"/whiteboard-expansion map to the
scroll-story export (P6.9) and the planner board (P6.16) respectively.
Audience Q&A/polls (Canva Live) ride the microsite widget layer (P6.13) as
a meet-night companion page.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Presentations (incl. responsive/cinematic) | 🆕 P6.12 deck format on the document engine |
| C1 | Canva Docs (text documents) | 🆕 P6.12 club document formats (report/proposal/programme) |
| C1 | Reports · Proposals | 🆕 P6.12 `season_report` / `sponsor_proposal` (data-grounded AI drafts) |
| C2 | Guided Presentations (goal/story/structure before slides) | 🆕 P6.12 outline-then-build flow driven by the P6.2 assistant |
| C11 | Canva Docs — embed charts/sheets; Scrollables | 🆕 P6.12 chart/table embeds (P6.9); scroll-story export (P6.9/P6.13) |
| C12 | Presenter View (previews, notes, timer) · Presenter notes | 🆕 P6.12 presenter route |
| C12 | Standard / full-screen / Presenter View modes | 🆕 P6.12 view modes |
| C12 | Autoplay (timed transitions) | 🆕 P6.12 autoplay (kiosk mode for club foyer screens — a real club use) |
| C12 | Recording yourself presenting / talking presentations | 🆕 P6.12 talkover recording (P6.5 recorder) |
| C12 | Remote Control (control slides from any device via link/QR) | 🆕 P6.12 phone-remote pairing |
| C12 | Canva Live (audience Q&A, reactions, polls) | 🆕 P6.12 meet-night companion page via P6.13 widgets (Q&A/poll, moderated) |
| C12 | Magic Shortcuts (presenting keyboard effects: blur, drumroll, confetti, timers) | 🆕 P6.12 presenter effects (confetti for medal slides; timer for warm-ups) — small, deterministic |
| C12 | Offline presenting mode | 🆕 P6.12 PWA-cached deck (↗ P6.21; hosted-only stands — it's a browser cache, not an install) |
| C12 | Real-time live edits during presentation | 🆕 P6.12 live spec reload (long-poll/SSE) |
| C12 | Expand slide to infinite Whiteboard | ↗ P6.16 planner board (the whiteboard analogue) |
| C12 | Turn presentation into a video | 🆕 P6.12 deck→MP4 via reel engine |
| C12 | Export as PowerPoint, PDF, video slideshow, or website | 🆕 P6.12 PPTX/PDF/MP4 exports; deck→microsite ↗ P6.13 |
| C1 | Whiteboards (infinite canvas) | ↗ P6.16 planner board |
| A7 | Convert to PDF (from Word/Excel/PowerPoint/images) | 🆕 P6.12 bounded converters (images/docx/pptx→PDF; spreadsheet→PDF via P6.15 tables) |
| A7 | Convert from PDF (to Word/Excel/PowerPoint/RTF/JPG/PNG) | 🆕 P6.12 PDF→images + text extraction (full Office fidelity explicitly bounded) |
| A7 | Edit PDF (text, images, layout, brand colours/fonts) | 🆕 P6.12 import-to-spec → edit → re-export (not in-place PDF surgery) |
| A7 | Merge / Combine files into one PDF (+ rotate/delete/reorder) · Organize pages | 🆕 P6.12 PDF utilities (pypdf-class, deterministic) |
| A7 | Import PDFs with table/mask fidelity; export with high-fidelity text in 20+ scripts; PDF accessibility tags | 🆕 P6.12 import fidelity bounded + tagged-PDF export (fonts w/ script coverage ↗ P6.7) |
| A7 | Export PDFs with gradients; CMYK profile; print PDFs | ↗ P6.19 print pipeline |
| A7 | Free-plan PDF quick-action limits | ↗ P6.22 quota layer (PC.4 packaging decides numbers) |
| A8 | Design and deliver presentations; presentation templates; presenter mode; video controls in presentation | 🆕 P6.12 deck format + presenter route (video blocks honour play controls) |
| A8 | Generate presentation (AI, from prompts or uploaded documents) | 🆕 P6.12 outline-then-build (upload → grounded draft) |
| A8 | Create documents from templates or scratch; add and format text in documents | 🆕 P6.12 document formats + editor |
| A8 | Import PowerPoint; export to PPTX; multi-page zoom controls | 🆕 P6.12 PPTX round-trip + canvas zoom |
| A2 | Generate presentation (A2 listing) | 🆕 P6.12 (same flow; indexed under A2) |
| C2 | Magic Switch deck→doc/blog transforms | ↗ P6.1 format transformer (uses this engine's specs) |

---

## P6.13 — Club microsites, link-in-bio, forms & interactive widgets

**What Canva/Adobe have.** Drag-and-drop multipage responsive websites, free
subdomains, custom domains (purchase or BYO), SSL/privacy/password/SSO,
website insights, SEO controls (sitemaps, meta, favicon, alt text, AI SEO
descriptions), device preview, nav menus/link-in-bio, Canva Code 1.0/2.0
(AI-generated interactive widgets/experiences, forms to Sheets,
SSO-protected publishing), Canva Forms (RSVPs, surveys, sign-ups → Sheets),
QR codes, webpage export as PDF, single-page Adobe webpages with TOC/anchor
navigation.

**The MediaHub shape.** Not a website builder — **club pages generated from
club data**: a meet microsite (entry info, programme, live session updates,
results recap as they land), a club link-in-bio page (latest approved posts,
join/trial form, sponsors), an event page with RSVP. Pages are generated
the same way cards are (brand tokens + data + archetype layouts), hosted on
the existing infrastructure under `club.mediahub.app`-style subdomains
(BYO domain supported; we don't become a registrar), and updated by the
pipeline (a new approved recap auto-refreshes the meet page — publishing
gates apply since pages are outward-facing). **Forms** capture structured
data back into the org's data hub (P6.15): trial sign-ups, volunteer
rotas, kit orders, RSVPs — each submission a typed row, exportable, GDPR-
deletable. **Widgets** (the Canva-Code analogue) are a vetted catalogue —
countdown-to-meet, live medal tally, lane-draw lookup, poll/Q&A — generated
as sandboxed, self-contained components (AI-assembled from audited
primitives, never arbitrary hosted code), embeddable on pages.

**Build sketch.** (1) `sites/` package: `SiteSpec` (pages → sections →
blocks, reusing document blocks + card embeds), static-first render to
hosted HTML (cache-busted, per-org path/subdomain routing, SSL via the
platform), edit-in-place via spec patches; (2) `forms/` package: form
schema, public submit endpoint (rate-limited, spam-filtered, isolation per
ADR-0003 — minors' data rules apply hard here), responses into the P6.15
hub + notify hooks; (3) widget catalogue: audited component primitives +
AI composer constrained to them; SSO/password protection per page; (4)
SEO: per-page meta/sitemap/favicon/alt-text (alt text AI-suggested,
human-editable), AI SEO description honest-erroring without provider; (5)
insights: privacy-respecting first-party page analytics (counts, not
tracking) ↗ P6.16 surfaces them; (6) QR generator (deterministic,
brand-coloured with contrast guard, logo-embedded; PNG/SVG/PDF export) for
posters → pages/forms; (7) device preview = responsive preview frames in
the editor.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Websites (multipage, responsive) | 🆕 P6.13 data-generated club pages/microsites |
| C1 | Canva Code designs (interactive experiences) | 🆕 P6.13 vetted widget catalogue (AI-composed from audited primitives) |
| C13 | Website builder (drag-and-drop, no code, multipage, responsive) | 🆕 P6.13 section/block editing on `SiteSpec` (generated-first, edited second) |
| C13 | Templates for websites | 🆕 P6.13 site archetypes (meet microsite, link-in-bio, event page, club home) |
| C13 | Free my.canva.site domain (capped free sites) | 🆕 P6.13 per-org subdomain on the platform domain |
| C13 | Custom domain purchase | 🚫 adapted — no registrar business; BYO domain only |
| C13 | Bring your own domain | 🆕 P6.13 BYO domain (CNAME + managed cert) |
| C13 | SSL, domain lock, WHOIS privacy, password protection, SSO | 🆕 P6.13 SSL + password/SSO-protected pages (domain lock/WHOIS = registrar concerns, out with the registrar role) |
| C13 | Website Insights (traffic/views/engagement) | 🆕 P6.13 first-party, privacy-respecting page counts → P6.16 analytics |
| C13 | SEO (auto sitemaps, meta title/description, favicon, alt text, AI SEO descriptions) | 🆕 P6.13 SEO layer |
| C13 | Canva Forms integration | 🆕 P6.13 forms on pages |
| C13 | Canva Code interactivity (calculators, countdowns, widgets) | 🆕 P6.13 widget catalogue (countdown-to-meet, medal tally, lane lookup) |
| C13 | Device preview (desktop/tablet/mobile) | 🆕 P6.13 responsive preview |
| C13 | Navigation menus, social links, link-in-bio sites | 🆕 P6.13 nav blocks + link-in-bio archetype |
| C13 | No native e-commerce (noted limitation) | 🆕 P6.13 mirrors it honestly: payment links out to the club's existing store/Stripe links (`ticket_merch_promo` type), no checkout build |
| C11 | Canva Forms (RSVPs, feedback, surveys, sign-ups; responses → Sheets) | 🆕 P6.13 forms → P6.15 data hub rows |
| C17 | Canva Code (AI interactive experiences; built on Claude; HTML import; copy/reuse code; publish as website) | 🆕 P6.13 widget composer (sandboxed primitives; no arbitrary hosted code) |
| C17 | Canva Code 2.0 (fully interactive from a prompt, responsive, forms to Sheets, SSO-protected publishing) | 🆕 P6.13 (same composer + forms + SSO pages) |
| C12 | Export presentation as Canva website | 🆕 P6.13 deck→page export |
| A9 | Design webpages; webpage templates; publish/host webpages; export webpage as PDF | 🆕 P6.13 pages + PDF snapshot export (via P6.12 renderer) |
| A9 | Navigation bar / TOC with anchor links; enhanced text handling | 🆕 P6.13 anchor nav blocks |
| A2 | Generate QR code | 🆕 P6.13 QR generator (brand-safe colours, logo embed) |
| A11 | QR code generator (custom colour/style/logo; PNG/JPEG/PDF/SVG output) | 🆕 P6.13 (same generator; vector + print exports) |

---

## P6.14 — Email & newsletter design

**What Canva/Adobe have.** Canva Email Design — branded email campaigns,
exportable as HTML; newsletters as a design type.

**The MediaHub shape.** The parent/member **newsletter is already a
`turn_into` output** (text). P6.14 makes it visual and sendable-anywhere:
brand-tokened, email-safe HTML (table-based layout, inlined CSS, dark-mode
aware, bulletproof buttons, image fallbacks — the existing email theming
surface grown into a real composer), assembled automatically from the
period's approved content (results recaps, spotlights, upcoming fixtures
from the planner, sponsor slot) with an AI editorial pass in the club's
voice. Export = paste-ready HTML for the club's existing list tool
(Mailchimp-class) + a hosted web version (P6.13 page); direct sending stays
out of scope until P4-class adapters exist for an email provider (then it
inherits the publish gate like any channel).

**Build sketch.** (1) `email_design/` package: email-safe block renderer
(subset of document blocks compiled to table HTML; snapshot-tested across
major client quirks), newsletter `FormatSpec`s; (2) auto-assembly from
workflow state (approved cards in date range) + planner items; (3) exports:
.html download, copy-to-clipboard, hosted view; (4) provider adapter slot
(flagged, later) for direct send with list management explicitly *not*
rebuilt — we integrate, we don't become a CRM.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Canva Email Design (branded campaigns, HTML export) | 🆕 P6.14 email-safe composer + HTML export |
| C1 | Newsletters (design type) | 🔵 text newsletter shipped (`turn_into`) → 🆕 P6.14 visual newsletter formats |

---

## P6.15 — Data hub, bulk generation & personalisation at scale

**What Canva/Adobe have.** Canva Sheets (visual spreadsheets, media in cells,
sort/freeze/number formats, CSV/XLSX/PDF round-trip), Sheets AI (structured
sheet from a prompt), Magic Formulas, Magic Insights, Bulk Create (many
designs from CSV/XLSX), Magic Studio at Scale (bulk personalised/localised
content from Sheets), Data Autofill via API, Data Connectors (Google
Analytics, HubSpot, Snowflake, Statista) with refresh, bulk
create-and-automate (spreadsheet-driven), batch processing.

**The MediaHub shape.** MediaHub *is* structured-data-first — the canonical
results store is the "sheet". P6.15 makes that store a user-facing **data
hub**: browse/edit canonical tables (athletes, results, fixtures, records,
form responses, sponsor facts) with provenance per cell (parsed vs
hand-entered — the ambiguity-flagging rule made visible), CSV/XLSX
import/export, and derived columns computed deterministically (age-group,
season-best — "formulas" are real code, with AI available to *suggest* a
derivation, never to silently compute it). **Bulk generation** is the
killer feature Canva can't ground: "certificates for all 47 PB swimmers",
"a spotlight per graduating senior", "a localized recap per language" —
one click, each output flowing through the normal review queue (bulk never
bypasses approval). Connectors pull *club-relevant* sources: the Swim
England approved-systems API (PC.6a), rankings sites already integrated in
`pb_discovery`, club CRMs later — each normalised to `canonical.*` (P3.4
discipline) with refresh schedules on the `scheduler/`.

**Build sketch.** (1) `data_hub/` package: table registry over the
canonical store + org tables (form responses, rosters, sponsor facts),
grid UI (sort/filter/freeze/format), cell provenance badges, import/export
(CSV/XLSX/PDF print via P6.12); (2) `data_hub/derive.py` — registered
deterministic derivations + AI-suggested (human-confirmed) definitions;
(3) `bulk/` — `bulk_generate(format_spec, row_query, per_row_bindings)` →
batched pipeline runs with progress, queueing into review (rate/quota
caps ↗ P6.22); (4) connector framework: pull adapters with schedules,
normalisation to `canonical.*`, per-source trust metadata feeding
`SafeToPost` provenance; (5) "sheet from a prompt" = AI-scaffolded table
schema (columns + types) for org tables; insights/analysis ↗ P6.9.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Canva Sheets (visual spreadsheets) | 🆕 P6.15 data hub grid over canonical + org tables |
| C2 | Sheets AI (structured spreadsheet from a prompt) | 🆕 P6.15 AI-scaffolded org-table schemas |
| C2 | Magic Formulas (AI spreadsheet formulas) | 🆕 P6.15 AI-*suggested*, human-confirmed deterministic derivations |
| C2 | Bulk Create (many designs from CSV/Excel/spreadsheet) | 🆕 P6.15 `bulk_generate` (review-queued, never auto-published) |
| C2 | Magic Studio at Scale (bulk personalised/localised from Sheets) | 🆕 P6.15 per-row personalised packs (+ P6.23 localisation) |
| C11 | Canva Sheets detail (media/links/mentions/dates/drop-downs in cells; sort, freeze, number formatting; CSV/XLSX/PDF up/download) | 🆕 P6.15 grid features (media cells link `media_library` assets) |
| C11 | Data autofill (third-party data → brand template via API) | 🆕 P6.15 autofill bindings (public API ↗ P6.20) |
| C11 | Bulk Create (C11 listing) | 🆕 P6.15 |
| C11 | Data Connectors (Google Analytics, HubSpot, Snowflake, Statista; refresh) | 🚫 adapted — club-relevant connectors instead (Swim England API, rankings, club CRM); scheduled refresh on `scheduler/`; GA-class analytics ↗ P6.16 |
| C11 | Magic Studio at Scale (C11 listing) | 🆕 P6.15 |
| C11 | Connect API / Autofill API / Brand Templates API | ↗ P6.20 public API surface |
| A17 | Bulk create & automate (spreadsheet-driven) | 🆕 P6.15 |
| A18 | Bulk create (A18 listing) | 🆕 P6.15 |
| C19 | Batch processing (Affinity pixel studio) | 🆕 P6.15 batch recipe application over media assets (P6.4 recipes at scale) |

---

## P6.16 — Planner, calendar, whiteboard & performance analytics

**What Canva/Adobe have.** Content Planner (calendar, drag-and-drop
scheduling, pause/edit scheduled posts, pre-loaded social holidays),
channel preview, per-channel account permissions, social analytics/insights
(impressions, clicks, likes, comments; Metricool-powered in Adobe), caption/
hashtag editing in the planner, drafts, shared calendars, multi-account,
grid preview, social safe zones, mentions, activation cards, ad-creation
engines (Canva Grow: AI ad variants from a website scan, publish to Meta,
performance tracking; TikTok Ads Manager), whiteboards/Kanban as planning
canvases.

**The MediaHub shape.** The P1.3 planner already *decides what to post*;
P6.16 gives it a **calendar body**: month/week board where planned items,
drafts, scheduled posts (draft scheduling shipped) and published results
live together; drag to reschedule (gates re-evaluated on every move);
**club-aware key dates** preloaded (season fixtures, champs deadlines,
awareness days relevant to grassroots sport) rather than generic "National
Donut Day"; per-channel preview (exact crop/safe-zone/caption-truncation
per platform — safe-zone masks also exposed in the editors); and the
**performance loop**: once P4 adapters exist, pull per-post metrics back,
attribute them to post types/archetypes/times, feed the planner's ranking
(the data advantage compounds — "spotlights outperform recaps 3:1 for this
club, schedule more"), with AI-written performance digests via P6.9
insights. A **planning whiteboard** (free-form board with cards, the
Canva-whiteboard/Kanban analogue) covers committee brainstorms that
become planner items. Sponsor/ad variants: generate A/B creative sets for
a sponsor activation (paid distribution stays a human action in the ad
platform — MediaHub prepares, never spends).

**Build sketch.** (1) calendar UI over `workflow/schedule` + planner
output + posting log (drag = schedule mutation through the gate); (2)
key-date packs per sport profile + org-entered dates (already a P1.3
direct signal — surfaced editable); (3) channel preview renderer (platform
frame mocks + truncation rules as data); (4) `analytics/` — our own
first-party metrics ingest straight from the platform APIs (post-P4; no
third-party aggregator dependency), attribution store keyed by post id →
type/archetype/time, planner feature inputs + insight digests; (5) board surface (`plan/board`):
draggable idea cards promote to planner items; (6) ad-variant set =
bulk-generate N creative variants (P6.15) tagged for the sponsor, exported
to the ad platform's specs.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C15 | Content Planner (social calendar, schedule/plan, drag-and-drop) | 🔵 planner + draft scheduling shipped → 🆕 P6.16 calendar/board UI with drag |
| C15 | Direct publishing (FB Pages/Groups, IG Business, X, LinkedIn, Pinterest, TikTok, Tumblr, Google Business Profile) | ↗ P4.1–P4.3 platform adapters (approval-gated) |
| C15 | Social media holidays pre-loaded | 🆕 P6.16 club-aware key-date packs |
| C15 | Pause/edit scheduled posts without re-uploading | 🆕 P6.16 schedule mutations (gate re-evaluated) |
| C15 | Social performance analytics / Insights (impressions, clicks, likes, comments) | 🆕 P6.16 metrics ingest + attribution (post-P4) |
| C15 | Caption/hashtag/emoji/link editing in planner; save drafts | 🔵 caption editing + drafts shipped → 🆕 inline planner editing |
| C15 | Channel preview before scheduling | 🆕 P6.16 per-platform preview frames |
| C15 | Per-channel account permissions (private/team-viewable/team-publishable) | 🆕 P6.16 channel ACLs (rides PC.3 roles; publish stays gated) |
| C15 | Canva Grow (AI ad variants from website scan, publish to Meta, performance tracking) | 🚫 adapted — sponsor A/B creative sets prepared for export; no ad spend automation; performance loop via P6.16 analytics |
| C1 | Whiteboards (infinite canvas) | 🆕 P6.16 planning board (cards → planner items) |
| C1 | Kanban boards (diagram listing's planning sense) | 🆕 P6.16 board columns (idea → drafted → approved → scheduled) |
| C12 | Expand slide to infinite Whiteboard | 🆕 P6.16 board link from deck (the deck page becomes a board card) |
| C2 | Canva AI 2.0 scheduling workflow | 🆕 P6.16 assistant can propose schedule changes (human confirms; gate applies) |
| A14 | Content Scheduler (plan, preview, schedule, publish to TikTok/IG/FB/Pinterest/LinkedIn/X) | ↗ P4 adapters + 🆕 P6.16 calendar |
| A14 | Shared calendars; multi-account | 🆕 P6.16 org calendar shared across members (PC.3); multi-account per channel |
| A14 | Grid preview | 🆕 P6.16 IG grid preview (planned feed as a grid) |
| A14 | Social media analytics (via Metricool) | 🆕 P6.16 our own first-party ingest from the platform APIs (no aggregator dependency) |
| A14 | Social mentions | 🆕 P6.16 mention/tag fields per channel post (validated per platform) |
| A14 | Social safe zones | 🆕 P6.16 safe-zone overlays in editors + previews |
| A14 | Caption writer (AI) | ✅ shipped (`web/ai_caption.py`) |
| A14 | TikTok Ads Manager | 🚫 adapted — creative prepared to ad specs; spend stays in the platform |
| A14 | Direct publish to Instagram/Vimeo | ↗ P4.2 (+ Vimeo optional target) |
| A14 | Set/connect social accounts | ↗ P4 (human-connected, least-privilege) |
| A14 | Activation cards in calendar | 🆕 P6.16 key-date "activation" suggestions on the calendar (planner-generated) |

---

## P6.17 — Collaboration & review

**What Canva/Adobe have.** Real-time co-editing, comments with
mentions/reactions (including on locked objects, contextual commenting),
task assignment, version history with restore, folders/projects/libraries,
teams with shared assets, element locking, role permissions
(Editor/Viewer/Commenter + enterprise groups), review & approval workflows,
share links (view/edit/comment), copy files between accounts, Team Context,
an AI you can tag in comments.

**The MediaHub shape.** Committee reality: one volunteer drafts, a coach
checks names, the chair approves. MediaHub builds **its own review layer**
on the shipped workflow spine (CardStatus, approval signal, per-org
memberships from PC.3): threaded comments anchored to a card/spec element,
@mentions with notify hooks (`notify/`), task assignment ("check lane-4
name") that blocks approval until resolved, full version history (every
spec/caption revision already persists — add diff view + restore), element
locking (lock the sponsor strip), role-based permissions on workspace
membership, and share links (view/comment) for people outside the
workspace — e.g. a parent confirming a name — without an account, token-
scoped and expiring. The assistant (P6.2) can be tagged in a thread to
explain or propose a fix as a spec patch. True simultaneous cursors-on-
canvas co-editing is built as our own last-writer-wins → patch-merge model
on DesignSpecs (specs are structured, so merges are tractable); live
cursor presence ships later and only if clubs actually ask.

**Build sketch.** (1) `collab/` package: comment threads (anchor = run/
card/spec-element id), tasks, mention notify; (2) revisions: spec/caption
revision log + diff/restore UI; (3) locks: per-element lock flags enforced
at patch time; (4) share tokens: scoped, expiring view/comment links
(isolation-audited per ADR-0003); (5) roles: Editor/Reviewer/Approver/
Viewer on the membership ledger; group-approver rules (n-of-m sign-off for
`sponsor_activation`, safeguarding-sensitive types); (6) folders/projects:
org-level grouping over runs/packs/assets (the existing stores gain a
`collection` field); (7) Team Context = the org's brand/recent-content
context the assistant already reads — surfaced to humans too.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C16 | Real-time co-editing | 🆕 P6.17 own patch-merge co-editing on DesignSpecs (presence later, demand-gated) |
| C16 | Comments (tag/mention teammates, reactions) | 🆕 P6.17 anchored threads + mentions + reactions |
| C16 | Assigning tasks to teammates | 🆕 P6.17 tasks blocking approval |
| C16 | Version history (view/restore) | 🔵 revisions persist today → 🆕 diff + restore UI |
| C16 | Folders (organise and share assets) | 🆕 P6.17 collections over runs/packs/assets |
| C16 | Teams (shared brand kits, templates, folders) | 🔵 PC.3 workspaces shipped → 🆕 shared kit/format/collection scoping (kits ↗ P6.11) |
| C16 | Live edits / show live edits during presenting | ↗ P6.12 live spec reload |
| C16 | Lock elements | 🆕 P6.17 element locks (patch-time enforced) |
| C16 | Group/role-based permissions (Editors, Viewers, Commenters; enterprise groups) | 🆕 P6.17 roles on the membership ledger |
| C16 | Team Context (surfaces brand-relevant content) | 🆕 P6.17 org context panel (same context the AI reads) |
| C16 | Ask @Canva (collaborative AI in comments) | 🆕 P6.17 tag the P6.2 assistant in threads |
| C9 | Approval workflows (group approvers, approval rules) | 🔵 per-card approval + publish gate shipped → 🆕 P6.17 group-approver rules |
| C9 | Brand folders / linked folders | 🆕 P6.17 kit-scoped collections |
| C15 | Share links (view/edit/comment); template links | 🆕 P6.17 scoped share tokens; "template link" = share a saved `FormatSpec` |
| A15 | Real-time co-editing; invite collaborators | 🆕 P6.17 (invites ✅ shipped in PC.3 membership invites) |
| A15 | Comments (incl. on locked objects, contextual commenting) | 🆕 P6.17 anchored threads (locked elements still commentable) |
| A15 | Share as view-only links; copy files between accounts | 🆕 P6.17 share tokens; copy-between-workspaces (org export/import, isolation-audited) |
| A15 | Version history | 🆕 P6.17 |
| A15 | Review & approval workflows (incl. Workfront-class) | 🔵 shipped core → 🆕 group rules; external PM-tool sync deliberately not built (own reviewer flow instead) |
| A15 | Object locking; lock/unlock elements | 🆕 P6.17 |
| A15 | Libraries (create/share); Projects (create/share/move/copy); Creative Cloud Libraries | 🆕 P6.17 collections + org asset libraries (our own; no CC dependency) |

---

## P6.18 — Export, conversion & delivery engine (quick actions)

**What Canva/Adobe have.** Export to PNG/JPG/PDF (standard + print)/SVG/MP4/
GIF/PPTX/DOCX/CSV/WAV, quality sliders, transparent PNG, single-image merge,
bulk download, and a one-click "Quick Actions" toolbox (convert image/video/
GIF formats, trim/crop/resize/merge/caption video, mute, reverse, speed,
PDF actions).

**The MediaHub shape.** One **first-party export engine** every surface
calls: cards (PNG/JPG/SVG/PDF), reels (MP4/GIF/WebM), audio (WAV/MP3),
documents (PDF/PPTX/DOCX), data (CSV/XLSX/JSON), packs (ZIP — shipped),
with per-format options (quality, scale, transparent background,
print-vs-screen PDF), bulk export across a pack/date range, and stable
share/download links. The "quick actions" toolbox is the same engine
exposed as utilities on the media library (convert/resize/trim without
making a post) — genuinely useful to volunteers and zero new philosophy:
every action is deterministic FFmpeg/Pillow/pypdf-class code we own.

**Build sketch.** (1) `export_engine/` package: format registry +
per-format renderer adapters (most already exist — renderer PNG, reel MP4,
pack ZIP; add SVG export from spec, GIF/WebM transcode, PPTX/DOCX via
P6.12, WAV via P6.6); (2) export options schema + UI (quality/scale/
transparency/colour profile); (3) bulk export jobs on `scheduler/`
(zip-batched, progress, notify); (4) media-library quick actions (image
convert/resize/crop; video trim/crop/resize/merge/speed/reverse/mute/
caption; GIF↔MP4; images→PDF) calling P6.4/P6.5/P6.12 ops; (5) share
links unified with P6.17 tokens.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C15 | Export formats: PNG, JPG, PDF (standard + print), SVG, MP4, GIF, PPTX, DOCX, CSV | 🔵 PNG/MP4/ZIP/CSV shipped → 🆕 P6.18 SVG/GIF/PPTX/DOCX + print-PDF (P6.19 profile) |
| C15 | Export quality settings (10–100); transparent background PNG; single-image merge | 🆕 P6.18 options schema (transparent PNG rides the cutout layer; merge = flatten pages to one image) |
| A16 | Quick Actions — Image: Remove background, Resize, Crop, Convert to JPG/PNG/SVG, WebP conversions, Generate QR | 🆕 P6.18 utilities (cutout ✅ shipped; QR ↗ P6.13; SVG conversion via trace for raster sources, honest about fidelity) |
| A16 | Quick Actions — Video: Convert to MP4, Video→GIF, Trim, Crop, Resize, Merge, Caption, Change speed, Reverse, Mute, Animate from audio, Clip Maker | 🆕 P6.18 utilities over P6.5 ops (animate-from-audio ↗ P6.10; Clip Maker ↗ P6.5) |
| A16 | Quick Actions — Document/PDF: Create/Convert to PDF, Convert/Export from PDF, Combine PDF, Organize pages, Edit PDF | 🆕 P6.18 utilities over P6.12 PDF tools |
| A16 | Quick Actions — GIF: GIF to MP4, GIF to Video | 🆕 P6.18 transcodes |
| A16 | Free/premium gating of quick actions | ↗ P6.22 quotas (PC.4 decides tiers) |
| A3 | Convert image formats (JPG/PNG/SVG/WebP) | 🆕 P6.18 image converters |
| A4 | Convert video to GIF / MP4; GIF→MP4; GIF→Video; download as GIF | 🆕 P6.18 video/GIF transcodes |
| A12 | Animated images export as GIF | 🆕 P6.18 GIF export of P6.10 animations |
| A18 | Export to PDF/PNG/JPG/PPTX/GIF/MP4/WAV | 🆕 P6.18 (WAV via P6.6) |
| A18 | Bulk download | 🆕 P6.18 bulk export jobs |
| C12 | Export as PowerPoint / PDF / video slideshow (presentation exports) | ↗ P6.12 via this engine |

---

## P6.19 — Print & merch pipeline

**What Canva/Adobe have.** 40+ print product types (cards, flyers, posters,
brochures, apparel, mugs, stickers, labels, notebooks, photo books, banners,
calendars, envelopes, mouse pads, pillows, tote bags), Print Shop browsing,
magic-resize-for-print, Auto-Proofing (text size, bleed, resolution), CMYK,
delivery/pickup options, guarantees, sustainability programs, eco paper
stocks.

**The MediaHub shape.** Clubs print constantly — posters for the leisure-
centre noticeboard, meet programmes, certificates, banners for the gala,
kit and merch for fundraising. MediaHub builds **its own print-readiness
layer** (the part that's actually engineering): print `FormatSpec`s with
physical dimensions, bleed/margins/crop marks, CMYK-profile PDF/X export,
and **deterministic auto-proofing** (minimum text size at print DPI, image
resolution vs physical size — pairs with P6.3 upscale, bleed-zone
violations, contrast on paper) so a volunteer can hand any high-street or
online printer a file that won't bounce. *Fulfilment* (the factory) is the
one thing that cannot be first-party: it ships later as an optional,
flag-gated fulfilment slot behind our own order interface — the default
product is always the print-ready file download.

**Build sketch.** (1) print profile on `FormatSpec` (mm/in dimensions,
bleed, safe margins, DPI target); (2) `print_ready/` package: PDF/X export
(CMYK via ICC transform, marks, flattening) on the P6.12/P6.18 renderer
path; (3) `print_ready/proof.py` — deterministic preflight with
per-violation explanations (the explainability rule applied to print); (4)
merch graphics: apparel/product `FormatSpec`s (front/back placements,
single/double-sided) + P6.3 mockup previews; (5) fulfilment slot
(optional, later): order schema + provider adapter behind our interface,
flag-gated per P0.3 — no provider hardwired, guarantees/eco options are
provider attributes surfaced honestly.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C14 | 40+ printed product types (business cards, flyers, posters, brochures, postcards, invitations, greeting cards, t-shirts, hoodies, sweatshirts, tote bags, mugs, water bottles, stickers, labels, notebooks, planners, mouse pads, photo books, banners, yard signs, calendars, envelopes) | 🆕 P6.19 print/merch `FormatSpec`s for the club-relevant set (designs are P6.1 formats; this adds the physical profiles) |
| C14 | Print Shop (browse products, mockups, paper types, sizes by region) | 🚫 adapted — no shop until a fulfilment slot exists; product profiles + mockups (P6.3) browseable |
| C14 | Magic resize for print (one design → any printable product) | 🆕 P6.19 print re-render via the P6.1 transformer (real re-layout at print size) |
| C14 | Auto-Proofing (text size, bleed zone, resolution) | 🆕 P6.19 deterministic preflight with explanations |
| C14 | CMYK colour support | 🆕 P6.19 ICC/CMYK PDF/X export |
| C14 | Delivery options (standard/express/pickup) · Happiness Guarantee · One Print, One Tree · eco paper (240–650gsm) | 🚫 adapted — fulfilment-provider attributes (incl. guarantees/sustainability programmes), surfaced only when the optional fulfilment slot is enabled |
| C1 | T-shirts and apparel (hoodies, sweatshirts, tote bags) · Mugs, water bottles, promotional products · Labels · Stickers (print) · Banners and yard signs | 🆕 P6.19 merch/print formats (fundraising kit) |
| A1 | Product labels (template category, print sense) | 🆕 P6.19 label formats |
| A18 | Margins/bleed/crop marks | 🆕 P6.19 print profile on specs |
| A18 | Print & order (business cards, flyers, mugs, pillows, tote bags, stickers, invitations; US/UK/CA/AU) | 🚫 adapted — print-ready download first; optional fulfilment slot later |
| A7 | Export PDFs with gradients; CMYK colour profile export; print PDFs | 🆕 P6.19 print-PDF path (gradients preserved through the renderer) |
| C19 | Affinity Publisher print craft (PDF/X export, preflight, crop/registration marks) | 🆕 P6.19 our own equivalents (PDF/X, preflight, marks) |

---

## P6.20 — MediaHub platform: public API, webhooks, automation & agent access

**What Canva/Adobe have.** Apps marketplaces (430+/500+ third-party apps),
Apps SDKs, Connect/Express APIs (design, export, asset, folder, autofill,
brand templates, comments + webhooks), iPaaS (Zapier/Make/Workato),
platform integrations (Slack, Salesforce, Notion, Zoom, HubSpot, Microsoft,
Dropbox, OneDrive, Google Drive/Photos/Calendar/Gmail, Atlassian, Linear,
ads platforms), "Canva in Claude"/Design Model inside ChatGPT/Claude/Gemini,
embed SDKs, Chrome extensions, file-format interop (PSD/AI open + convert,
Lightroom, SVG import), DAM connectors (Bynder, Frontify, AEM), developer
funds.

**The MediaHub shape.** MediaHub becomes a **platform of its own**: a
versioned public API (org-scoped tokens, least-privilege scopes) exposing
what the product already does — submit results/data, trigger pipeline runs,
list/approve cards (approval via API still counts as the human signal),
render/export, query the data hub, manage forms/sites — plus **our own
webhooks** (run finished, card approved, pack exported, form submitted) so
clubs and federations wire MediaHub into anything (including, via *their*
Zapier/Make accounts, the long tail — we publish recipes, we don't embed
their runtimes). An **MCP server** exposes the same API as tools so a club
volunteer can drive MediaHub from Claude/ChatGPT/Gemini — our version of
"Canva in Claude", pointed at our own engine. File-format interop is
first-party importers/exporters (SVG in/out, layered PSD export for
round-trip, palette files), never a dependency on the other suite. A
third-party app marketplace is explicitly long-term (after the API
stabilises and only if demand is real); until then "apps" are our own
modules.

**Build sketch.** (1) `api_public/` blueprint: token issuance/scopes on
the membership ledger, versioned REST endpoints over existing internals,
OpenAPI spec, rate limits (↗ P6.22); (2) `webhooks/` registry + signed
deliveries on `notify/`'s transport; (3) MCP server exposing the API as
typed tools (read + draft scopes; publishing tools always end at the
approval queue); (4) importers/exporters: SVG import, layered export
(SVG/PSD) for round-trip ↗ P6.24, palette/font/asset bundles; (5)
notification posts to chat tools via plain incoming-webhook URLs (our
generic webhook channel already exists in `notify/` — Slack/Teams/Discord
reachable without bespoke SDKs); (6) embed: signed iframe/oEmbed of
approved cards/packs for club websites (read-only; full Embed-SDK editing
deferred); (7) GWS exclusion holds — no Gmail/Drive/Calendar connectors;
cloud-file import via Dropbox/OneDrive-compatible generic remote-fetch +
upload, calendar *export* via ICS feeds (our own), never a GWS API
dependency.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C17 | Canva Apps Marketplace (430 apps; >half AI-powered; $50M fund) | 🚫 adapted — our own module system now; third-party marketplace explicitly long-term, demand-gated |
| C17 | Named creative apps (Mockups/Smartmockups, Pixabay, Pexels, Bynder, D-ID, HeyGen, Neiro, DeepReel, Krikey AI Animate, Dynamic QR Codes, Google Drive, Issuu, Soundraw, MelodyMuse, Typecraft, Murf AI, AiVOOV, Colorify, LottieFiles, Flourish, soona, Shopify, Brandfetch, Imagen, DALL·E, Mojo AI, Enhancer, HubSpot, Analytics) | 🚫 adapted — each maps to our own equivalent: mockups/upscale/generation ↗ P6.3 · stock library ↗ P6.8 · avatars (opt-in) ↗ P6.5 · animation ↗ P6.10 · QR ↗ P6.13 · doc publishing ↗ P6.12/P6.13 · music/TTS ↗ P6.6 · type effects ↗ P6.7 · charts ↗ P6.9 · brand-DNA ✅ shipped (P1.5, our own Brandfetch) · palette tools ↗ P6.11 · product photos ↗ P6.3+P6.4 · commerce/CRM/analytics ↗ P6.16/webhooks (no embedded third-party apps; Google Drive excluded) |
| C17 | Canva Apps SDK (in-editor apps; Image/Video/Text/Content/Design-Editing/Tables/Fonts/Auth APIs) | 🚫 adapted — internal module APIs now; public app SDK only with the long-term marketplace |
| C17 | Canva Connect APIs (Design, Export, Asset, Folder, Autofill, Brand Templates, Comment APIs + webhooks) | 🆕 P6.20 our public API + webhooks (same capability set over our engine) |
| C17 | iPaaS integrations (Zapier, Make, Workato) | 🆕 P6.20 reached via our API + webhooks + published recipes (their runtimes stay theirs) |
| C17 | Platform integrations (Slack, Salesforce, Gmail, Google Drive, Google Calendar, Notion, Zoom, HubSpot, Microsoft, Atlassian, Linear, Dropbox, OneDrive, Amazon Ads, Meta, Google Ads) | 🚫 adapted — chat notifications via generic webhooks (Slack/Teams/Discord); file import via upload + Dropbox/OneDrive-compatible remote fetch; calendar via our ICS feeds; **GWS connectors stay excluded**; ads ↗ P6.16 (prepare, never spend); CRM/PM-tool embeds not built — webhooks instead |
| C17 | Canva in Claude (bring coded creations into the editor) · Design Model inside ChatGPT/Claude/Gemini | 🆕 P6.20 MediaHub MCP server — our engine driveable from Claude/ChatGPT/Gemini |
| C17 | Premium Apps Program, Developer Innovation Fund, app translation | 🚫 adapted — marketplace economics deferred with the marketplace itself |
| C2 | Canva AI 2.0 connectors workflow | 🆕 P6.20 assistant reads/writes through the same API scopes (GWS still excluded) |
| A17 | Photoshop (.psd) & Illustrator (.ai) files — open, linked images, convert assets | 🆕 P6.20 first-party PSD import (raster layers; `psd-tools`-class) + SVG/AI-as-PDF import; fidelity stated honestly; round-trip ↗ P6.24 |
| A17 | Lightroom integration; Adobe Color themes; AEM Assets; SVG import | SVG import 🆕 P6.20; palette files ↗ P6.11; Lightroom/AEM 🚫 adapted — generic import paths, no vendor coupling |
| A17 | Creative Cloud integration; send from Firefly/boards; open in Photoshop/Illustrator | 🚫 adapted — layered export/import round-trip (P6.24) instead of CC coupling |
| A17 | Google Drive, OneDrive, Dropbox; Google Photos | Dropbox/OneDrive-compatible remote fetch + upload 🆕 P6.20; **Google Drive/Photos excluded** (standing rule) |
| A17 | 400–500+ add-ons (marketplace) | 🚫 adapted — same as C17 marketplace position |
| A17 | Slack, ChatGPT, Microsoft 365 Copilot, Miro integrations | webhooks (Slack) + MCP (ChatGPT/Copilot-class agents) 🆕 P6.20; whiteboard-tool embeds not built (board ↗ P6.16) |
| A17 | Amazon/LinkedIn/Google ad creation | ↗ P6.16 ad-spec creative sets (export to specs; no ad-account automation) |
| A17 | Bynder, Frontify connectors | 🚫 adapted — our own brand platform (P6.11) is the DAM; asset import/export bundles instead |
| A17 | EA Sports Team Builder; Fantasy Premier League | 🆕 P6.20 fun-data spokes done our way: fantasy-league/club-game content via the data hub when a club supplies the data (no vendored game integrations) |
| A17 | Chrome extension | 🚫 adapted — PWA share-target + bookmarklet-class "send to MediaHub" (↗ P6.21), no browser-store extension to start |
| A17 | Express Embed SDK / Express API | 🆕 P6.20 read-only embed (signed iframe/oEmbed) + our public API; editable-embed SDK deferred |

---

## P6.21 — Mobile, PWA & access surfaces

**What Canva/Adobe have.** Native iOS/Android apps (full editing), iPad
apps, desktop apps (Mac/Windows), PWA, Chrome extension, mobile presenting,
mobile photo/video editing, guest/logged-out access, cross-device sync,
education programs, offline-after-activation desktop suites.

**The MediaHub shape.** Hosted-only stands (ADR-0011): there is no desktop
install and no native-store app to start — there is **one responsive web
app, made properly mobile**, then a **PWA**: installable, share-target
("share photo from camera roll → MediaHub media library" — the single
highest-value mobile behaviour for poolside volunteers), camera capture
into the library, push-class notifications via the existing `notify/`
channels, and an offline-tolerant **approval queue** (review/approve/edit
captions on the bus; actions sync when back online — browser cache, not an
install). Mobile editing focuses on the volunteer jobs: approve, caption
tweak, photo pick, quick crop — not full canvas surgery on a phone.
Education/team programmes are a PC.4 packaging note (university societies
are already a target segment), not engineering.

**Build sketch.** (1) PWA manifest + service worker (app-shell caching,
share-target API, offline queue with idempotent sync against the workflow
API); (2) mobile-first passes on review/approve/planner surfaces (the
RESPONSIVE_DESIGN.md programme extended); (3) capture: `<input capture>`
+ media-library quick-upload with on-device downscale; (4) presenting
from phone ↗ P6.12 remote; (5) guest access = P6.17 share tokens; (6)
cross-device sync is inherent (server-side state).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C18 | iOS and Android apps (full editor, photo editor, video editor, voice recorder) | 🚫 adapted — PWA with capture/recorder (P6.5/P6.6 recorders run in mobile browser); native-store apps only if PWA proves insufficient |
| C18 | Desktop apps (Mac, Windows) | 🚫 adapted — hosted web app only (ADR-0011) |
| C18 | Web browser (cross-platform) | ✅ shipped — the product is the web app |
| C18 | Mobile presenting (present from pocket) | ↗ P6.12 phone-remote + mobile deck view |
| C18 | Mobile photo/video editing | 🆕 P6.21 mobile-scoped editing (approve/caption/crop/pick); full editors stay desktop-primary |
| C18 | Designs open in new browser tab by default (toggleable) | 🆕 P6.21 small UX preference, noted for completeness |
| A19 | Web (desktop browser), mobile apps (iOS/Android), iPad app, PWA, Chrome extension | 🆕 P6.21 PWA (+ share-target replacing the extension); iPad = the responsive web app |
| A19 | Guest/logged-out access | 🆕 P6.21 token-scoped guest views (P6.17) |
| A19 | Cross-device sync | ✅ inherent (hosted state) |
| A19 | Adobe Express for Education (classrooms, assignments, galleries) | 🚫 adapted — society/education packaging is a PC.4 commercial decision; no classroom LMS build |
| A19 | Free plan and Premium plan; Teams and Enterprise plans; complimentary Premium programs | ↗ PC.4 pricing & packaging (quota mechanics ↗ P6.22) |
| C19 | Affinity: Mac + Windows, works offline after activation | 🚫 adapted — hosted-only; offline tolerance limited to the PWA approval queue |

---

## P6.22 — AI governance, quotas, provenance & content safety

**What Canva/Adobe have.** Canva Shield (input/output moderation, safety
filters, bias mitigation, privacy controls, enterprise indemnification),
real-time AI credit/usage trackers, generative-credit systems with monthly
allocations, Content Credentials on AI output, commercially-safe model
claims, role-based AI permissions, free-tier action limits.

**The MediaHub shape.** MediaHub already has the spine Canva sells as
Shield: the deterministic brand-safety gate, safeguarding rules (minors
never auto-publish), per-org audit ledger, LLM-usage observability, and
honest-error AI. P6.22 completes it as **our own governance layer**:
per-org/per-feature AI quotas (the "credits" analogue — metered on the
existing `observability/` usage store, surfaced live in the workspace,
enforced with honest "quota reached" errors; tier numbers belong to PC.4),
input/output moderation on the new generative surfaces (P6.3/P6.5/P6.6 —
prompt screening + output safety via the provider's safety settings plus
our own checks), **provenance stamps** on every AI-generated asset (C2PA-
style manifest where tooling allows, always at minimum our own signed
audit metadata: model, prompt hash, editor, timestamps — extending the
shipped provenance/trust vocabulary), role-based feature permissions
(which members may use generation, spend quota, enable autonomy), and a
per-org AI activity view (who generated what, where it was used).

**Build sketch.** (1) `governance/` package: quota ledger (feature ×
org × period) over observability usage events; enforcement decorator on
AI entry points; workspace usage panel; (2) moderation pass in
`media_ai`/`imagine` wrappers (provider safety settings + screening,
honest-block with reason); (3) provenance: asset-sidecar manifests in
`media_library` + export-time embedding (C2PA libs optional), surfaced on
review UI ("AI backdrop — generated 2026-06-11"); (4) role flags on the
membership ledger consumed by UI + API scopes (P6.20); (5) free-tier
action limits = the same quota mechanism with PC.4-decided numbers.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Canva Shield (moderation, safety filters, bias mitigation, privacy controls, indemnification) | 🔵 gate/audit/safeguarding shipped → 🆕 P6.22 moderation on generative surfaces + privacy controls; indemnification = a commercial/legal posture (PC.4), not code |
| C2 | Real-time AI credit/usage tracker | 🔵 LLM usage tracked (`observability/`) → 🆕 P6.22 live workspace quota panel |
| A2 | Content Credentials attached to AI content; commercially safe models | 🆕 P6.22 provenance manifests + model-policy register (which providers are commercially safe, per DEPENDENCY_LICENSING) |
| A2 | Generative credits system (monthly allocations, expiry) | 🆕 P6.22 quota ledger (numbers ↗ PC.4) |
| A7 | Free-plan PDF quick-action limits (1/week) | 🆕 P6.22 quota mechanism on quick actions (numbers ↗ PC.4) |
| A16 | Free/premium gating of quick actions (Remove background, Erase premium) | 🆕 P6.22 same mechanism |
| C9 | Role-based permissions for AI/brand features | 🆕 P6.22 role flags (with P6.11/P6.17) |
| C8 | Reduce motion accessibility setting | ↗ P6.10 (accessibility guardrail family noted here for governance completeness) |

---

## P6.23 — Localisation & translation

**What Canva/Adobe have.** AI Translate for designs (100+ languages, bulk
localisation, regional variants), 100+ language Magic-Write/prompt support,
interface in 100+ languages, AI dubbing into ~5 target languages preserving
the original voice, multilingual captions (100+ languages), localisation at
scale via Sheets.

**The MediaHub shape.** Welsh-language club content is a real, local,
differentiating need (Swansea wedge — bilingual clubs are normal in Wales),
then EU club markets later. **Our own localisation layer**: translate any
caption/card/document/site into target languages through the existing LLM
providers (translation is judgement → `media_ai`, honest-error; sporting
terms protected by a per-sport glossary so "PB" and event names survive),
**layout-aware** re-render after translation (autofit absorbs text
expansion; RTL support in the renderer when a script needs it), per-org
default language(s) + per-post bilingual variants (one approval covers a
language *pair* shown together), bulk localisation via P6.15 rows, dubbing
= P6.23 translation + P6.6 TTS voices per language, and UI localisation
(our own string catalogue; Welsh first as the honest flagship).

**Build sketch.** (1) `localize/` package: translation service (provider-
backed, glossary-constrained, length-budgeted per text slot), language
metadata on captions/specs; (2) bilingual variant flow in the caption
editor + review (side-by-side approval); (3) renderer: script/RTL support
+ font script coverage (P6.7 catalogue carries the scripts); (4) UI i18n:
string extraction + `cy` (Welsh) catalogue first; (5) bulk: per-language
rows in `bulk_generate`; (6) dubbing pipeline: transcript (P5.3) →
translate → TTS track swap, clearly labelled as AI-dubbed (P6.22
provenance).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | AI Translate / Translate designs (100+ languages, bulk localisation) | 🆕 P6.23 translation + layout-aware re-render + bulk via P6.15 |
| C6 | Multilingual support (100+ content languages; interface in 100+ languages) | 🆕 P6.23 content languages via providers; UI i18n catalogue (Welsh first, grown by demand) |
| C2 | Magic Write 100+ language support | 🆕 P6.23 caption generation in the org's languages (glossary-protected) |
| A2 | Translate (designs, incl. regional variants) | 🆕 P6.23 regional variants (en-GB vs en-US spelling already handled in captions — extended) |
| A2 | Translate Video / Translate Audio (AI dubbing, ~5 languages, voice-preserving; enterprise lip-sync) | 🆕 P6.23 dub pipeline (translate + per-language TTS; voice-preservation/lip-sync explicitly out until consent-safe; labelled AI-dubbed) |
| A2 | Generate Image 100+ prompt languages | 🆕 P6.23 prompt pass-through (providers accept multilingual prompts) |
| A4 | Caption video auto-captions in 100+ languages | 🆕 P6.23 caption translation on the P6.5 caption layer |
| A6 | Spellcheck with primary language | ↗ P6.7 (locale-aware dictionaries from the org's language set) |

---

## P6.24 — Pro editor & round-trip (the Affinity-class answer)

**What Canva/Adobe have.** Affinity by Canva (free pro suite: pixel/photo
studio with RAW, frequency separation, liquify, HDR merge, panorama, focus
stacking, 16/32-bit, adjustment/live-filter layers, lens correction, PSD
compatibility; vector/designer studio with path ops, image trace,
artboards; publisher studio with master pages, AutoFlow, OpenType
typography, baseline grids, data merge, preflight; extra studios; AI
retouch tools; export-to-Canva), plus editor fundamentals in both products
(layers panel, multi-select/filter, group/ungroup, align, rulers & guides,
page management, fit-to-content).

**The MediaHub shape.** Two honest moves. **(a) Our own fine-control
editor** on the DesignSpec — the missing manual layer between "regenerate"
and "ship": layers panel (reorder/hide/lock/opacity/blend), multi-select,
group/ungroup, align/distribute, rulers/guides/snapping, nudge, per-page
management (add/duplicate/reorder/resize/fit-to-content), direct text/image
swap — all spec patches through the same validated pipeline as P6.2, so
manual edits stay brand-checked and auditable. Plus targeted pro-image
tools where volunteers hit walls: curves/levels (deterministic), AI
retouch (P6.3), basic vector editing of our SVG elements (node/path ops,
boolean ops, trace via P6.3). **(b) Round-trip, not suite-cloning**: the
deep darkroom/publisher craft (RAW develop, HDR, panorama, focus stack,
liquify, master-page DTP) is explicitly *not rebuilt* — instead MediaHub
exports **layered, editable files** (layered SVG/PSD, print-PDF) so a
club's power user can finish in any pro tool they own, and re-imports the
result as an asset with provenance kept. The publisher-craft needs clubs
actually have (long documents, data merge, preflight) are already covered
by our own P6.12 documents + P6.15 bulk + P6.19 preflight.

**Build sketch.** (1) editor surface: spec-bound canvas with the
fundamentals above (patch-based undo/redo from revision log P6.17); (2)
`graphic_renderer/vector_edit.py` — node/path/boolean ops on element SVGs
(deterministic geometry); (3) curves/levels in P6.4's recipe schema
(16-bit-aware internally where Pillow allows); (4) layered export: SVG
(native) + PSD writer (raster layers) + re-import matching; (5) explicit
non-goals documented (RAW/HDR/panorama/liquify/master-pages) with the
round-trip path as the supported answer.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C19 | Affinity by Canva (unified free pro app: Photo/Designer/Publisher) | 🚫 adapted — our own fine-control editor + layered round-trip; no desktop suite (hosted-only) |
| C19 | Pixel/Photo Studio (RAW develop, frequency separation, liquify, HDR merge, panorama stitching, focus stacking, 16/32-bit HDR, adjustment layers, live filter layers, lens correction, PSD compatibility) | 🚫 adapted — curves/levels/adjustment recipes (P6.4) + AI retouch (P6.3) in-app; RAW/HDR/panorama/focus-stack/liquify = round-trip non-goals; PSD import/export 🆕 P6.24 |
| C19 | Batch processing | ↗ P6.15 batch recipes |
| C19 | Vector/Designer Studio (vector tools, path operations, image trace, gradient fill, artboards) | 🆕 P6.24 vector node/path/boolean editing on our SVG elements; trace via P6.3; artboards = pages |
| C19 | Layout/Publisher Studio (master pages, AutoFlow, text styles, kerning/leading/ligatures/OpenType/variable fonts, column guides, baseline grids, PDF/X export, preflight, crop/registration marks, data merge) | 🚫 adapted — long-doc needs are ours already: documents ↗ P6.12 (styles/columns/baseline), print craft ↗ P6.19 (PDF/X, preflight, marks), data merge ↗ P6.15; OpenType feature control 🆕 P6.24 in the type system; master-page DTP = round-trip non-goal |
| C19 | Additional studios (Slice, Canva AI, Retouching, Color Grading, Typography, Compositing) | 🆕 P6.24 slice = per-element export regions; retouch/grade = P6.3/P6.4; typography = P6.7; compositing = layers/blend in the editor |
| C19 | Canva AI tools in Affinity (Object Selection, Generative Expand/Fill/Edit, Portrait Blur, Portrait Lighting, Colorize, Super Resolution, Select Sampled Depth, Depth Estimation) | ↗ P6.3 services (object select = cutout+saliency; portrait blur/lighting = subject-mask relight; colorize/super-res = providers; depth tools = provider depth maps feeding focus effects) |
| C19 | Export Affinity projects to Canva | 🆕 P6.24 layered import (PSD/SVG) — the equivalent inbound path |
| C19 | v3.1 additions (Tone Brush, Live Tone Blend, pixel-selection-to-curves, Develop tone curves, light UI theme) | 🚫 adapted — tone curves land in P6.4 recipes; the rest are round-trip non-goals; (light UI theme is a web-app theming question, noted) |
| A18 | Layers (work with, multi-select, filter); group/ungroup; align elements; rulers & guides | 🆕 P6.24 editor fundamentals |
| A18 | Add/duplicate/reorder pages; resize page; crop page (Fit to Content, custom, presets); change page size | 🆕 P6.24 page management (multi-page specs via P6.12) |

---

## Completeness index — every source section accounted for

How to audit: every bullet in the two research inventories appears as a row
(or an explicitly-listed item within a grouped row) in exactly one package
table above — cross-references (↗) mark the rows that *also* surface
elsewhere. This index lists, per source section, where its bullets live.
If a future research refresh adds bullets, they must be added to a package
table **and** this index in the same change.

**Canva inventory (C1–C19)**

| Section | Bullets | Mapped in |
|---|---|---|
| C1 Design/content types | 40 | P6.1 (bulk of types) · P6.4 (collages) · P6.5 (videos) · P6.9 (infographics, diagram types) · P6.12 (presentations, docs, reports, proposals) · P6.13 (websites, Code) · P6.14 (email, newsletters) · P6.15 (Sheets) · P6.16 (whiteboards, Kanban) · P6.19 (apparel/promo/labels/stickers/banners) |
| C2 AI / Magic Studio | 40 | P6.2 (assistant, Design Model, Magic Design/Write) · P6.3 (image/video gen + edits) · P6.6 (voice/music/SFX) · P6.7 (Magic Morph) · P6.9 (Charts/Insights) · P6.10 (Magic Animate) · P6.11 (brand intelligence) · P6.12 (Guided Presentations) · P6.13 (Code workflows) · P6.15 (Sheets AI, Formulas, Bulk, at-Scale) · P6.16 (scheduling workflow) · P6.17 (Ask @Canva) · P6.20 (connectors, in-Claude) · P6.22 (Shield, credits) · P6.23 (Translate) · P6.1 (Magic Switch) · shipped (Brand Voice, web research) |
| C3 Photo editing | 22 | P6.4 (editor ops) · P6.3 (AI services incl. BG remover ✅/eraser/changer/upscale/style match/mockups) · P6.2 (point-and-click) |
| C4 Video editing | 27 | P6.5 (suite) · P6.6 (voice cleanup/balance) · P6.8 (stock footage) · P6.10 (animation library) · P6.12 (presenting) · P6.18 (conversions) |
| C5 Audio | 13 | P6.6 (all) |
| C6 Text & typography | 14 | P6.7 (all) · P6.10 (text animations) · P6.23 (multilingual) |
| C7 Elements | 18 | P6.8 (library) · P6.9 (tables/charts) · P6.6 (audio elements) · P6.3 (generation) |
| C8 Animation | 14 | P6.10 (all) · P6.12 (click order surface) · P6.22 (reduce-motion noted) |
| C9 Branding | 15 | P6.11 (platform) · P6.17 (approvals, folders) · P6.22 (role permissions) · shipped (kit builder, palettes) |
| C10 Templates | 5 | P6.1 (catalogue, Quick Create) · P6.11 (brand templates) · P6.15 (bulk autofill) · shipped (AI generation) |
| C11 Data & documents | 13 | P6.15 (Sheets/autofill/connectors/at-scale) · P6.9 (charts/insights/storytelling) · P6.12 (Docs/Scrollables) · P6.13 (Forms) · P6.20 (APIs) |
| C12 Presentations | 16 | P6.12 (all) · P6.13 (Live page, website export) · P6.16 (whiteboard expansion) |
| C13 Websites | 14 | P6.13 (all) · P6.16 (insights surfacing) |
| C14 Print | 20 | P6.19 (all; design side P6.1) |
| C15 Publishing & planning | 12 | P6.16 (planner/analytics/preview/permissions/Grow) · P4 (direct publishing) · P6.18 (export formats/quality) · P6.17 (share links) · shipped (caption editing, drafts) |
| C16 Collaboration | 11 | P6.17 (all) · P6.12 (live edits while presenting) |
| C17 Apps & developer | 10 groups | P6.20 (API/webhooks/MCP/marketplace position/named-app equivalents) · P6.13 (Code 1.0/2.0) · P6.5 (avatar apps) |
| C18 Mobile & desktop | 6 | P6.21 (all) · P6.12 (mobile presenting) |
| C19 Affinity | 10 groups | P6.24 (editor + round-trip) · P6.4/P6.3 (retouch/AI tools) · P6.12/P6.15/P6.19 (publisher craft) · P6.21 (platforms/offline) |
| TL;DR / Key Findings / Recommendations / Caveats | — | context, not features; availability/plan-gating caveats inform P6.22 quotas and the per-item "verify at build time" rule below |

**Adobe Express inventory (A1–A19)**

| Section | Bullets | Mapped in |
|---|---|---|
| A1 Templates & design types | 13 groups | P6.1 (types, save-as-template, quick replace, orientations) · P6.9 (infographics) · P6.12 (presentations/docs) · P6.13 (webpages) · P6.5/P6.10 (video/animated) · P6.16 (ads) · P6.4 (collages) · P6.19 (print/t-shirts/labels) · P6.11 (locked templates) |
| A2 AI / Generative (Firefly) | 25 | P6.3 (image gen/fill/expand/remove/similar/video) · P6.2 (assistant, rewrite, text-to-template) · P6.1 (coloring pages) · P6.5 (avatars, Clip Maker ref) · P6.6 (speech/enhance/recommendations) · P6.7 (text effects, font recs) · P6.12 (presentations) · P6.13 (QR) · P6.22 (credentials, credits) · P6.23 (translate/dubbing) · shipped (caption writer) |
| A3 Image / photo editing | 17 | P6.4 (editor) · P6.3 (erase/replace-bg/AI assists; BG remove ✅) · P6.10 (animated images) · P6.18 (conversions, resize presets) |
| A4 Video editing | 17 | P6.5 (suite) · P6.6 (audio) · P6.18 (conversions) · P6.12 (presentation controls) · P6.23 (caption languages) · P4 (Vimeo) |
| A5 Audio | 9 | P6.6 (all) · P6.10 (animate-from-audio) · P6.2 (assistant controls) |
| A6 Text & typography | 8 groups | P6.7 (all) · P6.10 (animations) · P6.23 (translate/spellcheck locales) · P6.6 (voiceover tone) |
| A7 PDF & documents | 9 | P6.12 (PDF suite) · P6.19 (CMYK/print) · P6.22 (free limits) |
| A8 Presentations & documents | 9 | P6.12 (all) · P6.10 (sequencing) · P6.1 (switch presentation↔design) |
| A9 Webpages | 5 | P6.13 (all) |
| A10 Drawing & illustration | 5 | P6.8 (drawing) · P6.1 (worksheets, coloring) |
| A11 Elements & assets | 9 | P6.8 (stock/elements/search) · P6.9 (charts/tables) · P6.11 (color themes/Adobe Color) · P6.13 (QR) |
| A12 Animation | 10 | P6.10 (all) · P6.18 (GIF export) |
| A13 Branding | 6 | P6.11 (all) |
| A14 Scheduling & publishing | 12 | P6.16 (planner/analytics/safe zones/grid/mentions/activation) · P4 (publish/connect) · shipped (caption writer) |
| A15 Collaboration | 8 | P6.17 (all) |
| A16 Quick Actions | 5 groups | P6.18 (toolbox) · P6.5/P6.12/P6.13 (underlying ops) · P6.22 (gating) |
| A17 Imports & integrations | 12 | P6.20 (API/import/interop/MCP; GWS exclusions) · P6.24 (round-trip) · P6.16 (ads) · P6.11 (palettes) · P6.15 (bulk automate) · P6.21 (extension→PWA) |
| A18 Layout, pages & export | 8 | P6.24 (layers/align/guides/pages) · P6.18 (exports/bulk) · P6.19 (bleed/print-order) · P6.1 (resize-for-channel) · P6.15 (bulk create) |
| A19 Platforms & access | 6 | P6.21 (surfaces/guest/sync/education) · PC.4 (plans) |
| TL;DR / Key Findings / Recommendations / Caveats | — | context, not features; free-vs-premium volatility informs P6.22/PC.4 |

**Build-time verification rule.** The source inventories carry caveats
(regional rollouts, beta flags, plan gating, counts that drift). When a P6
item starts, re-verify the competitor behaviour only if it materially
shapes our own design — we are building our versions, not tracking theirs.

## Relationship to standing decisions

- Phase 6 never overrides: hosted-only (ADR-0011) · approval-first
  publishing + autonomy guardrails (P2.3, AUTONOMY_MODEL) · deterministic
  engine boundary · Gemini-first honest-error AI · self-hosted fonts ·
  GWS + 9router exclusions (CLAUDE.md, ADR-0007) · the ADR-0003 isolation
  invariant (forms/share-links/sites are new outward surfaces and inherit
  it hard).
- Phase C gates still apply: no P6 item starts before the
  commercial-readiness and traction gates (see ROADMAP "Standing
  context"); within Phase 6, build what paying clubs pull first.
- The Council convenes only where Phase 6 touches its triggers (outward
  deployment shape — e.g. the fulfilment slot, custom-domain serving,
  the public API's auth model; anything brushing the deterministic
  engine). Ordinary P6 feature work ships on engineering judgement.
