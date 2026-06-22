# Creative-Suite Parity — the MediaHub-shaped Canva / Adobe Express capability map

**Status:** planned · the long-form companion for **Phase 1 — Product (creative
suite + local-AI foundation)** in [`ROADMAP.md`](ROADMAP.md) · evidence bases checked in at

> **Renumber note (2026-06-18).** The roadmap was reordered into build order and
> the creative suite is now **Phase 1**; its work-package IDs were renumbered
> from the old `P6.*` family to the flat `1.*` scheme used throughout this doc
> (e.g. old `P6.3` imagery → **1.2**, with its local-image backend pulled in
> front as **1.1**). The full old→new **ID map**, and the now-superseded "Phase
> C / commercial-gate" sequencing once stated below, are in
> [`ROADMAP.md`](ROADMAP.md). Shipped packages (`P6.1`, `P6.2`) keep their old
> ids as history.
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
4. **Approval before anything leaves the building.** Every surface requires a
   human to review and approve before content is exported; MediaHub never posts
   to a social channel on its own.
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
   carries provenance (1.23).

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
existing single-card renders into a paged PDF via the 1.15 document engine.

**Status — shipped v1 (2026-06-18).** The catalogue and transformer are live:
`club_platform/format_catalog.py` (typed `FormatSpec` registry — per-channel
sizes for every social platform + off-feed club formats: poster, flyer,
certificate, coach card, athlete one-pager, season calendar, wallpapers — with
per-sport availability sourced from the sport profile, `custom_format()` for
any px/mm/cm/in size, and `aspect_class` parity-tested against the renderer);
`turn_into/transform.py` (`transform_design` re-targets an approved design's
brief to any format by re-laying-out the composition for the new aspect through
the design-spec director, with the deterministic per-aspect picker as the
honest floor, preserving the approved palette/headline/stats/photo;
`blank_brief_for_format` is the blank-start escape hatch); the web surface is
`GET /api/formats` + the per-card **Reformat…** control posting to
`POST /api/runs/<run_id>/card/<card_id>/reformat` (serves the re-rendered PNG).
Deferred by design to their owning packages: multi-page composition → 1.15,
print-ready CMYK/bleed output → 1.20, free-form manual element editing →
1.25, save-as-org-format presets and bulk autofill → 1.12/1.13.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Social posts for every platform (IG posts/Stories/Reels, FB posts/covers, TikTok, YouTube thumbnails/banners, X, Pinterest, LinkedIn posts/banners, Tumblr, Lemon8) | ✅ P6.1 per-channel `FormatSpec` presets shipped for IG/FB/X/LinkedIn/Pinterest/TikTok/YouTube sizes (Tumblr/Lemon8 are one more `FormatSpec` row each when asked) |
| C1 | Posters · Flyers · Banners/yard signs (digital design side) | 🆕 P6.1 formats (`poster`, `flyer`, `event_banner`) from meet/fixture data; print output ↗ 1.20 |
| C1 | Business cards | 🆕 P6.1 `coach_card` / committee contact card from roster + brand kit; print ↗ 1.20 |
| C1 | Invitations · Greeting/thank-you cards · Postcards | 🆕 P6.1 club-event formats (awards night invite, volunteer thank-you, sponsor thank-you postcard) fed by `manual_entry` + sponsor kit |
| C1 | Resumes | 🆕 P6.1 `athlete_one_pager` — athlete CV/recruitment sheet from `history/` PBs + spotlight data |
| C1 | Brochures | 🆕 P6.1 `club_prospectus` (multi-page; composed via 1.15) |
| C1 | Wallpapers (desktop/phone) | 🆕 P6.1 `club_wallpaper` format (fan/parent giveaway) from brand tokens + venue/team imagery |
| C1 | Calendars · Planners | 🆕 P6.1 `season_calendar` / training planner from fixtures + key dates (1.14 data) |
| C1 | Worksheets | 🆕 P6.1 training-set sheets / dryland worksheets from coach `manual_entry` |
| C1 | Certificates | 🆕 P6.1 `certificate` — PB/medal/participation certificates auto-filled per swimmer from run data; bulk ↗ 1.13 |
| C1 | Menus | 🆕 P6.1 `event_programme` (gala day programme/canteen sheet) from meet schedule |
| C1 | Photo books | 🆕 P6.1 `season_yearbook` (multi-page, media-library-driven; composed via 1.15) |
| C1 | Logos | 🆕 P6.1 crest/lockup variant generation (monochrome, knockout, badge forms) on top of the shipped DesignTokens lockup vocabulary — assistive, never replacing a club's crest |
| C1 | Custom-size designs (px/mm/in) | ✅ P6.1 `custom_format()` — any px/mm/cm/in canvas, bounds-checked |
| C1 | Multi-design projects ("One Design") | 🆕 P6.1 — a content pack already groups mixed outputs; add mixed-format packs (e.g. recap + poster + certificate batch in one pack) |
| C1 | Blank designs from scratch (preset/custom dimensions) | ✅ P6.1 `blank_brief_for_format()` blank-start seeded from brand tokens; manual editing ↗ 1.25 |
| C10 | 1M+ template library · templates by type/category | 🚫 adapted — archetype catalogue growth (12 → per-format sets) + format catalogue; deliberately *not* a template marketplace |
| C10 | AI template generation from prompt | ✅ shipped — the Tier B design-spec director generates layout specs from data/brief (`creative_brief/ai_director.py`); prompt-first entry ↗ P6.2 |
| C10 | Quick Create | 🆕 P6.1 one-click "make the obvious pack" per event, riding the P1.3 planner's top item |
| C10 | Brand Templates / bulk template autofill | ↗ 1.12 (locked brand formats) + 1.13 (autofill at scale) |
| C2 | Magic Switch (convert design to another format / resize / reformat; deck→doc transforms) | ✅ P6.1 format transformer shipped (`turn_into.transform_design` re-lays-out through the director, deterministic floor); translation half ↗ 1.24 |
| A1 | 220,000+ professional templates | 🚫 adapted — same as C10: archetypes + formats, not blanks |
| A1 | Template categories (social, flyers, posters, banners, logos, invitations, cards, business cards, resumes, cover letters, brochures, menus, pamphlets, leaflets, certificates, worksheets, class schedules, book covers, album covers, product labels, gift certificates, ads, memes, collages, wallpapers, t-shirts) | 🆕 P6.1 — each becomes a `FormatSpec` where it has a club meaning (class schedule → training schedule; book/album cover → yearbook/season-mix cover; gift certificate → fundraiser voucher; meme → `meme` format with club in-jokes via caption engine; ads ↗ 1.14; collages ↗ 1.3; t-shirts ↗ 1.20; product labels ↗ 1.20) |
| A1 | Presentations, documents, web pages, carousels | carousels 🆕 P6.1 multi-image carousel format; presentations/docs ↗ 1.15; web pages ↗ 1.16 |
| A1 | Animated / multi-page / video templates | animated formats ↗ 1.5; multi-page ↗ 1.15 composition; video formats ↗ 1.6 |
| A1 | Print-ready templates; portrait/landscape/square/vertical orientations | 🆕 P6.1 orientation variants per `FormatSpec`; print-readiness ↗ 1.20 |
| A1 | Blank canvas with custom dimensions | 🆕 P6.1 (same escape hatch as C1) |
| A1 | Save any project as a reusable/shareable template + Favorites | 🆕 P6.1 "save as club format" — an approved design becomes a reusable org-scoped `FormatSpec` preset; favourites = pinned formats |
| A1 | Quick replace (swap content fast) | 🆕 P6.1 re-run a saved format against new data (the data-driven analogue of quick-replace) |
| A1 | Brand-controlled / locked templates with style restrictions | ↗ 1.12 brand controls |
| A8 | Switch between presentation and design | 🆕 P6.1 format transformer covers deck↔card transforms |
| A18 | Resize design for any channel (one click) | ✅ P6.1 per-channel re-render from the persisted CreativeBrief (re-layout, not pixel scaling) |
| A2 | Generate coloring pages (text → printable line art) | 🆕 P6.1 `kids_activity_sheet` format (mascot/venue colouring pages for junior sections) via the 1.2 image provider with line-art style |
| A10 | Drawing worksheets (100+ templates) · combine into coloring books | 🆕 P6.1 same `kids_activity_sheet` family; multi-page book via 1.15 |

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
1.4 — honest error until a provider lands); (4) caption text-tools menu
calling `web/ai_caption.py` with operation-specific prompts; (5) memory
writes gated behind explicit "remember this" + an org-visible memory list
(inspect/delete); (6) prompt suggestions derived from the P1.3 planner's
ranked items, not generic. Provider order Gemini→Anthropic as everywhere;
no provider → honest error, the UI's manual controls keep working.

**Status — shipped v1 (2026-06-18).** The copilot and its surfaces are live:
`assistant/` package — `patch.py` (closed-vocabulary `SpecPatch` +
deterministic validator/applier; out-of-vocabulary ops dropped, colour-role
edits re-checked against the APCA gate and reverted if illegible; every edit
applied/rejected-with-reason and reversible), `tools.py` (bounded read/propose
allow-list for `ask_with_tools` — no publish/post/fetch tool exists),
`copilot.py` (one-turn orchestrator; honest no-provider error leaves the design
untouched), `session.py` (per-card chat + edit log) and `memory.py` (org
preference book — explicit "remember this", inspect/delete, deterministic recall
needing no embedding provider). Magic-Write caption tools (Summarise / Expand /
Rewrite) added to `web/caption_assist.py`; voice via the browser's on-device
speech + an honest server ASR seam (`assistant/asr.py`). Web: a per-card
**Copilot…** panel + `POST …/card/<card>/assistant`, planner-seeded
`…/assistant/suggestions`, `/api/assistant/memory` (+ delete),
`/api/assistant/transcribe`. Deferred to owners: generative image edits →
1.2/1.3, languages → 1.24, review-thread @assistant → 1.18, MCP exposure →
1.21.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Canva AI conversational assistant (text/voice/media prompts; "Design for me") | ✅ P6.2 club content copilot on `ai_core.ask_with_tools` (spec-patch editing) |
| C2 | Canva AI 2.0 — conversational design, iterative agentic editing, layered object intelligence, persistent Memory Library | ✅ P6.2 spec-patch agentic loop + org assistant memory (inspect/delete); layer-aware edits via the DesignSpec's structured fields |
| C2 | Canva AI 2.0 six workflows | split: connectors ↗ 1.21 · scheduling ↗ 1.14 · web research ✅ shipped (`web_research/`) · brand intelligence ↗ 1.12 · Sheets AI ↗ 1.13 · Code 2.0 ↗ 1.16 |
| C2 | Canva Design Model (design-aware model: structure, layering, hierarchy, branding → fully editable output) | 🔵 partial — the Tier B design-spec director is exactly this pattern (LLM emits structured, editable specs; deterministic render); P6.2 extends it from generate-time to edit-time. "Available inside ChatGPT/Claude/Gemini" ↗ 1.21 (MCP server) |
| C2 | Magic Design (AI layout from prompt or uploaded media) | 🔵 partial — director generates from data; 🆕 P6.2 adds prompt-/photo-first entry ("here's a photo, make something") routed into the same brief flow |
| C2 | Magic Write (generate/summarise/expand/rewrite; tone adjustment; context awareness; 100+ languages) | ✅ P6.2 caption text-tools shipped (summarise/expand/rewrite on `web/caption_assist.py`; tone-shift via the tone arg); languages ↗ 1.24 |
| C2 | Brand Voice (writes in your brand's tone) | ✅ shipped — `brand/voice_imitation.py` + learned voice store + few-shot caption examples |
| C2 | Guided Presentations (conversational goal/story/structure flow) | ↗ 1.15, driven by this assistant |
| C2 | Ask @Canva (tag the AI in a comment for feedback/generation) | ↗ 1.18 (assistant joins review threads) |
| A2 | AI Assistant beta (conversational create/edit; generate images; change backgrounds/text; replace objects; position/align/stylise; edit individual layers; toggle on/off; smart prompt suggestions; Imaging Subagent) | 🆕 P6.2 — same copilot; image operations delegate to 1.2 providers; assistant is per-org toggleable; suggestions seeded from the planner |
| A2 | Voice commands via microphone | ✅ P6.2 mic input via browser on-device speech; server ASR seam (`assistant/asr.py`) now backed by the local ASR engine (1.4 — `visual/transcribe.py`, faster-whisper / whisper.cpp), honest-erroring only when no `MEDIAHUB_ASR_PROVIDER` is set |
| A2 | Generate captions / Caption Writer for social posts | ✅ shipped — `web/ai_caption.py` (few-shot brand voice, generate-many-then-dedupe, per-platform variants, AI-tell ban-list, approval loop) |
| A2 | Rewrite / text variations | 🆕 P6.2 text-tools (variations = the shipped generate-many-then-dedupe pattern applied to any text block) |
| A2 | Text to Template (generate fully editable template from a prompt) | 🆕 P6.2 prompt → `FormatSpec` + design spec (editable, brand-locked); catalogue home ↗ P6.1 |
| A2 | Font recommendations (AI-assisted) | ↗ 1.9 (assistant surfaces them) |
| A2 | Music recommendations | ↗ 1.8 |
| C3 | Point-and-click editing (click any subject/text/background to grab/move/remove/replace/adjust) | 🆕 P6.2 click-to-select bound to spec layers (select → patch); pixel-level ops ↗ 1.2/1.3 |

---

## 1.2 — Generative imagery & image-AI services

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
photos before print (1.20 needs this), and product mockups (club merch
previews from 1.20 assets on blanks). Every output is stamped with AI
provenance (1.23) and never fabricates *results data* — generative pixels
are scenery, not facts.

**Build sketch.** (1) `media_ai/imagine.py` provider interface:
`generate(prompt, style, refs)`, `edit(image, mask, instruction)`,
`expand(image, target_box)`, `remove(image, mask)`, `upscale(image, factor)`,
`similar(image)`; (2) wire into media-library asset detail (fix-up actions)
and the card editor (background actions — replacing today's single-purpose
Imagen call); (3) subject lift = cutout provider + saliency, already on disk,
exposed as "lift subject"; (4) text lift (Grab Text) via Gemini vision OCR →
editable text block; (5) style presets curated to sport-editorial looks (no
"3D clay" gimmicks by default); (6) per-org generation quotas ↗ 1.23.
Text-to-video b-roll lands as a reel-scene provider (`visual/` scene source)
strictly opt-in like `MEDIAHUB_GEN_BG`. Layer extraction (Magic Layers) is the
inverse-render problem — scope to AI-image outputs only, where the provider
returns layers natively.

**Build status (2026-06-18) — ✅ 1.2 complete (Builds 1–3 shipped).** **Build 1** (the seam +
solid services + governance): `media_ai/imagine.py` (provider-agnostic facade) +
`media_ai/imagine_providers/` (`base`, `gemini_imagine`, `local_imagine`);
working `generate` + `similar` via Gemini Imagen (sport-editorial style presets,
aspect ratios, no-people default); deterministic `subject_lift` (cutout +
saliency); per-output provenance (IPTC `DigitalSourceType` embedded losslessly +
a `<file>.imagine.json` manifest); a per-org quota ledger
(`observability/imagine_usage.py`); media-library JSON routes + a "Generate an
image" UI panel; and the `MEDIAHUB_GEN_BG` Imagen call generalised behind the
seam (byte-identical renders). **Build 2** (working surfaces that need no 1.1):
**Grab Text** (`imagine.grab_text`, vision-OCR transcribe → editable blocks,
metered); **deterministic product mockups** (`mockups/` — poster/framed-print/
phone-post/flatlay, key-free, brand-tinted, byte-deterministic; feeds 1.20);
and a **generation-history + provenance viewer** (`/media-library/generated`).
The generative **edit family** (`edit`/`expand`/`remove`/`upscale`/
`style_match`) is defined in the seam and **honest-errors by capability**. **The
in-house local backend (1.1) has shipped** — a licence-clean self-hosted
diffusion model (FLUX.1-schnell, Apache-2.0) reached over HTTP at
`MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`, the zero-cloud-key default that lights up the
whole edit family (generate / similar / edit / fill / expand / remove /
style-match), metered and provenance-stamped like the cloud path. **Build 3**
(the studio UI — the last open piece of 1.2): a mask-brush **image studio**
(`web/image_studio.py`, route `/media-library/<asset_id>/studio`) puts the whole
edit family in front of volunteers — paint a mask and Fill/Erase, Expand to a new
canvas, Upscale, Restyle, make Variations, Lift the subject, or Grab text. It is
**capability-probed at runtime** (`/api/media-library/imagine/info`) so only ops
the active provider supports ever appear (honest, never a dead button), shows the
per-org quota live, and saves every result as a provenance-stamped *draft* for
review. Reachable from each library asset row, the cut-out page, the
generated-images history, and — the **card-editor integration** — a "✦ Edit
photo" deep-link on the content-pack photo picker (`api_create_graphic` returns a
`studio_url` for the chosen photo). **With Build 3, 1.2 is complete.** Out of
1.2's scope and tracked elsewhere: text-to-video b-roll (↗ 1.6), provider-native
layer extraction, and 3D (deferred-last). See
[`adr/0023-p6-3-generative-imagery-seam.md`](adr/0023-p6-3-generative-imagery-seam.md)
and [`adr/0024-local-diffusion-image-backend.md`](adr/0024-local-diffusion-image-backend.md).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Magic Media: Text to Image (+ style presets) | 🆕 1.2 `imagine.generate` (Gemini Imagen first), sport-editorial style presets |
| C2 | Dream Lab (15+ styles, reference image, prompt edits, quality tiers, Boost resolution, history, batch) | 🆕 1.2 — reference-image conditioning, generation history per org, batch via 1.13; "Boost" = `upscale` |
| C2 | Magic Media: Text to Video · Create a Video Clip (Veo-3) | 🆕 1.2 opt-in b-roll scene provider (Veo via Gemini API) feeding reel scenes ↗ 1.6 |
| C2 | AI 3D Model Generator / 3D Content Generator | 🆕 1.2 deferred-last: 3D club crest/trophy renders for graphics via provider 3D endpoints when stable; library home ↗ 1.10 |
| C2 | Magic Edit (add/replace via prompt) | 🆕 1.2 `imagine.edit` on media-library assets + card backgrounds |
| C2 | Magic Eraser (remove objects) | 🆕 1.2 `imagine.remove` (mask-brush UI) |
| C2 | Magic Grab (lift/reposition photo subject) | 🔵 partial — cutout providers + `graphic_renderer/saliency.py` shipped; 🆕 1.2 exposes "lift subject" as an editor action |
| C2 | Grab Text (select/edit text inside an image) | 🆕 1.2 vision-OCR lift → editable, brand-fonted text block |
| C2 | Magic Expand (extend borders / change aspect with AI fill) | 🆕 1.2 `imagine.expand` — pairs with saliency crops for story/print canvases |
| C2 | Magic Layers (extract editable layers from AI images) | 🆕 1.2 scoped to provider-native layered outputs |
| C2 | Style Match (unify a design by matching look/feel) | 🆕 1.2 re-style asset to brand tokens (palette/contrast respected via theming maths) |
| C2 | Magic Background (AI backdrop matching subject/layout/style) | ✅ shipped opt-in (`MEDIAHUB_GEN_BG` Imagen backgrounds) → 🆕 1.2 generalises behind `imagine` |
| C2 | Background Generator / Background Changer (+ relighting/blend) | 🆕 1.2 replace-background on cutout subjects with relight blend; procedural backdrop stays the no-key default |
| C2 | AI image upscaler / Enhancer (Upscale) | 🆕 1.2 `imagine.upscale` (print pipeline dependency) |
| C2 | Magic Mockups / Mockups | 🆕 1.2 merch/print mockups (card-on-poster, kit, mug) for 1.20 previews |
| C3 | Magic Eraser · Background Changer/Generator · Upscale · Style Match (photo-editor listings) | ↗ same 1.2 services surfaced in the 1.3 editor |
| C3 | Smartmockups / Mockups (photo-editor listing) | ↗ 1.2 mockups |
| C3 | Background Remover (one-click + Erase/Restore brushes, brush size) | ✅ shipped — `MEDIAHUB_CUTOUT_PROVIDER` (rembg default, Replicate/PhotoRoom optional); 🆕 1.2 adds erase/restore touch-up brushes |
| C3 | Image Cutout (AI cutout) | ✅ shipped (same cutout layer) |
| A2 | Generate Image (styles, effects, colour/tone, lighting, camera angle, reference image, "Show Similar", 100+ prompt languages) | 🆕 1.2 `generate` parameters + `similar`; prompt languages ↗ 1.24 |
| A2 | Generative Fill (insert/remove/replace via brush + prompt) · Insert or replace objects · Remove objects | 🆕 1.2 `edit`/`remove` |
| A2 | Generative Expand / Expand image | 🆕 1.2 `expand` |
| A2 | Generate Similar / on-style variations | 🆕 1.2 `similar` |
| A2 | Generate Video (shot size, camera angle, camera settings) | 🆕 1.2 b-roll provider ↗ 1.6 scenes |
| A3 | Image enhancement via AI Assistant (pose change, object swap, distraction removal) | 🆕 1.2 ops driven from P6.2; pose-change gated by the no-synthetic-people rule (real-athlete edits stay conservative: distraction removal yes, body manipulation no) |
| A3 | Erase tool (brush/quick-select removal) | 🆕 1.2 `remove` with brush UI (Adobe's Erase = same service) |
| A3 | Replace background | 🆕 1.2 replace-background (cutout + generate) |

---

## 1.3 — Photo editor (deterministic ops + assists)

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
ops (erase/fill/background) come from 1.2. Edits are non-destructive: an edit
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
| C3 | Pixel Eraser (manual erase) | 🆕 1.3 manual erase brush on the recipe layer (alpha mask), no AI needed |
| C3 | One-click Enhance / Auto-adjust | 🆕 1.3 `enhance_auto()` deterministic recipe |
| C3 | Filters (adjustable, incl. Mono/Sepia) | 🆕 1.3 filter strip with intensity (deterministic LUTs) |
| C3 | Effects — Duotone, Blur, Pixelate, Vignette, Glitch, Shadows (3D shadow), Auto-Focus | 🆕 1.3 effect ops (duotone honours brand palette via theming maths) |
| C3 | Adjustments (brightness, contrast, saturation, tint, white balance, light, colour, texture) | 🆕 1.3 adjustment sliders |
| C3 | Perspective adjustment (H/V sliders) | 🆕 1.3 perspective transform (deterministic) |
| C3 | Crop, rotate, resize, flip | 🆕 1.3 geometry ops (saliency-suggested crops shipped) |
| C3 | Frames and Grids (single/split-cell) | 🆕 1.3 frame/grid masks; element frames ↗ 1.10 |
| C3 | Focus / Auto-Focus (focal point, fg/bg blur) | 🆕 1.3 depth-ish blur via subject mask (cutout alpha) |
| C3 | Blur Brush (shape/size/intensity) | 🆕 1.3 local blur on recipe layer — also the safeguarding tool (blur a bystander's face) |
| C3 | Colour correction / colour adjustment · Image colour settings | 🆕 1.3 (same adjustment set) |
| C3 | Standalone Photo Editor (web + mobile) | 🆕 1.3 run-independent editor surface; mobile via 1.22 PWA |
| C1 | Photo collages | 🆕 1.3 collage composer (grid `FormatSpec`s) |
| A3 | Remove background (one-click) | ✅ shipped (cutout layer) — listed here for the A-doc; detail ↗ 1.2 |
| A3 | Resize image (social presets + custom) | 🆕 1.3 export-resize; channel presets shared with P6.1 |
| A3 | Crop image (freeform, ratios, social presets) | 🆕 1.3 |
| A3 | Crop into shapes (circle, heart, star, oval, square, triangle…) | 🆕 1.3 shape-mask crops (mask library shared with 1.10 shapes) |
| A3 | Convert image formats (JPG/PNG/SVG/WebP, PNG↔JPG, →SVG, WebP→…) | ↗ 1.19 conversion engine |
| A3 | Photo filters (8 styles + variations; Shuffle; intensity; 30+ Photoshop-powered filters) | 🆕 1.3 filter strip (+ shuffle = random pick UI sugar) |
| A3 | Adjustments (contrast, brightness, highlights, shadow, saturation, warmth, sharpen) | 🆕 1.3 |
| A3 | Effects (duotone, grayscale, blur, opacity, blend modes, golden hour, matte B&W, colour punch) | 🆕 1.3 (blend modes apply at composite time in the renderer) |
| A3 | Photo collages (manual, templates, preset grids) | 🆕 1.3 collage composer |
| A3 | Frames and overlays; crop & shape (rotate, scale, nudge, flip) | 🆕 1.3 + overlays ↗ 1.10 |
| A3 | Create profile pictures | 🆕 1.3 profile-picture presets (club avatar with brand ring) |
| A3 | Enhance in a snap | 🆕 1.3 `enhance_auto()` |
| A3 | Animated images (Spin, Pop, Jitter, Slide, Zoom, Pan, Wobble, Wind, colour/fade/blur) | ↗ 1.5 photo animations |
| A3 | Replace images; set image as page background | 🆕 1.3 asset swap on spec layers (background-set = spec patch via P6.2) |
| A3 | HEIC image import | 🆕 1.3 `pillow-heif` ingest |

---

## 1.6 — Video suite (timeline, captions, clip intelligence, recording)

**What Canva/Adobe have.** Multi-track timeline editors (Video 2.0; layer
videos/audio/graphics), trim/split/splice, scene view + Drop Zone, transitions,
beat sync, AI captions with styled caption layers, video background removal,
speed/reverse/mute, AI highlights/auto-trim, Clip Maker (long → short with
captions + reframing), screen/webcam recording, talking presentations, audio
sync, per-clip filters, video resize, instant reels, 4K, text/titles on video,
avatars.

**The MediaHub shape.** Today MediaHub renders video *programmatically*
(Remotion/FFmpeg reels from card data — already "Instant Reels" for meets).
1.6 adds the **footage path**: clubs upload phone clips of races/celebrations,
and MediaHub turns them into branded reels with the same approval flow. The
centrepiece is **Clip Maker for sport**: ASR (1.4) + scene/audio-energy
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
1.3 recipes applied as FFmpeg filters; (6) avatars: our own opt-in avatar
surface (provider video models behind our media-AI seam, not an embedded
avatar app) — explicitly-requested, clearly-disclosed, per the
no-synthetic-people rule.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Videos (full multi-track editor as a design type) | 🆕 1.6 footage path + EDL timeline over the shipped reel engines |
| C2 | Magic Design for Video / Magic Video (AI social-ready cuts from clips + prompt) | 🆕 1.6 Clip-Maker-for-sport (moments → branded cut) |
| C2 | Magic Animate (one-click animation/transitions across a design) | ↗ 1.5 |
| C4 | Multi-track timeline (Video 2.0): layer video/audio/graphics | 🆕 1.6 EDL timeline (tracks: video, audio, caption, graphic overlays) |
| C4 | Trim, split, splice, layer with precision · direct clip editing from timeline · zoom into timeline | 🆕 1.6 timeline ops |
| C4 | Visual audio waveforms for syncing | 🆕 1.6 waveform strip (deterministic peaks) |
| C4 | Transitions (fade/slide/wipe/chop/dissolve; duration/direction; apply between all pages) | 🔵 crossfades shipped in reels → 🆕 1.6 transition library + apply-all |
| C4 | Animation effects / transitions library | ↗ 1.5 motion presets, applied on video overlays |
| C4 | Beat Sync (auto-match audio beats to cuts) | 🆕 1.6 beat grid (librosa-class onset detection, deterministic) snapping cuts |
| C4 | Captions / Subtitles (AI auto-generate; editable styled caption layer; manual timing) | 🆕 1.4 word-level ASR caption track shipped (`transcribe.caption_track_for_audio` → `subtitle_burn`); the styled editable caption layer on footage is 1.6 |
| C4 | Video Background Remover (no green screen, <90s) | 🆕 1.6 video matting provider slot (flagged) |
| C4 | Speed control (speed up / slow-mo) | 🆕 1.6 per-clip speed (race-finish slow-mo) |
| C4 | Highlights (AI surfaces best clips) · Auto-trim | 🆕 1.6 `moments.py` scoring + suggested trims |
| C4 | Screen recording / online video recorder · record yourself presenting / talking presentations | 🆕 1.6 browser recorder → media library (presenting context ↗ 1.15) |
| C4 | Audio sync | 🆕 1.6 track alignment (waveform-assisted) |
| C4 | Enhance Voice (AI noise cleanup) · Balance All (volume levelling) | ↗ 1.8 audio services, surfaced on the timeline |
| C4 | Video filters, effects, adjustments (per-clip) | 🆕 1.6 1.3-recipes-as-FFmpeg-filters |
| C4 | Video upscaler, video reverse | 🆕 1.6 reverse (FFmpeg) · upscale via provider (1.2 class) — flagged |
| C4 | Magic Resize for video formats/aspect ratios | 🆕 1.6 saliency-tracked reframe (16:9↔9:16↔1:1) |
| C4 | Add text/titles/moving text with animation | 🆕 1.6 title overlays from brand type system (+ 1.5 presets) |
| C4 | Instant Reels (AI transforms footage into reels) | 🔵 data-driven meet reels shipped → 🆕 1.6 footage-driven instant reel |
| C4 | Stock footage library (Artlist etc.); Video Marketplace | ↗ 1.10 stock layer (openly-licensed first) |
| A4 | Multi-track editor; layer timing; adjust layer timing; locate timed objects | 🆕 1.6 timeline + per-layer timing inspector |
| A4 | Edit multiple videos in one file; Scene view (reorder, batch-edit); Drop Zone (compile clips into sequences) | 🆕 1.6 scene strip + drop-zone ("dump your phone clips here" → ordered sequence) |
| A4 | Trim / Crop / Resize video (social presets + custom) | 🆕 1.6 |
| A4 | Merge / combine videos | 🆕 1.6 concat via EDL |
| A4 | Change speed (slow-mo → super-fast) · Reverse · Mute | 🆕 1.6 |
| A4 | Convert video↔GIF/MP4 (GIF→MP4, GIF→Video, download as GIF) | ↗ 1.19 conversion engine |
| A4 | Remove background from video (+ restore) | 🆕 1.6 matting slot (same as C4) |
| A4 | Caption video / auto captions (editable, 100+ languages; reposition) | 🆕 1.6 captions; languages ↗ 1.24 |
| A4 | Video transitions; animations; layer objects (text/photos/elements) | 🆕 1.6 overlay tracks |
| A4 | Add audio to video; voiceover; video self-record (webcam) | 🆕 1.6 audio track + recorder; voiceover ↗ 1.8 |
| A4 | Slip Edit; scene trim/extend with snapping; collapse audio tracks | 🆕 1.6 timeline ergonomics |
| A4 | Video controls in Presentation mode | ↗ 1.15 |
| A4 | 4K video support | 🆕 1.6 4K ingest/export profiles (render cost gated ↗ 1.23 quotas) |
| A4 | Clip Maker (AI long→short, captions, reframing) | 🆕 1.6 Clip-Maker-for-sport |
| A4 | Export/publish directly to Vimeo (add-on) | ↗ P4 publishing adapters (Vimeo as an optional target) |
| A2 | Text to Avatar / AI avatars (studio-grade talking avatar videos) | 🆕 1.6 explicit opt-in only (no-synthetic-people rule); disclosed in-frame; provider behind flag |
| C17 | D-ID AI Presenters, HeyGen, Neiro, DeepReel (avatar apps) | ↗ 1.6 — covered by our own opt-in avatar surface, not by embedding those apps |

---

## 1.8 — Audio engine (music, SFX, voiceover, cleanup, rights)

**Status — shipped (2026-06-19).** The `audio/` package landed: `library.py`
(bundled CC0 SFX/idents/beds + operator/legacy dirs, mood/energy/platform
metadata), `select.py` (AI mood-match via `media_ai`, honest-error, over a
deterministic floor), `ops.py` (trim/fade/gain/speed/extract/concat/mix/convert,
deterministic FFmpeg), `clean.py` (denoise + EBU R128 levelling), `voice.py`
(voice catalogue incl. Welsh + SSML-ish params + per-org pronunciation lexicon,
wired into `visual/voiceover.synthesize` with cache-folding), `rights.py` (licence
ledger + tiered fingerprint + duplicate check), plus `generate.py` (flagged
music/SFX provider slots, honest-error) and `consent.py` (voice cloning/changer
gate + audit, off by default). The reel engine gains an **opt-in** bundled bed
(`MEDIAHUB_REEL_MUSIC_LIBRARY`, byte-parity off) and a Settings → **Audio &
voiceover** surface (library preview, voices, lexicon, own-audio upload + rights,
browser recorder, consent). Honest gaps remaining: chart-music rights and a
connected generation backend stay flagged provider slots (the library is the
default); voice cloning/changer ship the consent gate + audit, not a clone
backend.

**What Canva/Adobe have.** Stock + licensed music libraries (incl. popular
chart tracks with regional/usage caveats; TikTok Commercial Music Library),
SFX libraries, voiceover recording with noise cancellation, AI voiceover/TTS
(45–70+ voices, 20+ languages, pitch/speed/emotion controls, pronunciation
fixes, WAV download), AI music + SFX generation, trimming/volume/fades, up to
50 audio tracks, per-scene sync, upload own audio, audio fingerprint/Content-ID
checks, Enhance Speech, Extract Audio, Vocal Remover, AI dubbing, voice
changer, voice cloning, music recommendations, audio add-ons (EQ, cleaner,
visualizer).

**The MediaHub shape.** Reels need sound. 1.8 gives the reel/video engines a
proper **audio subsystem**: an openly-licensed music pool tagged by energy/
mood (the AI picks a track to match the reel's emotional arc — judgement via
`media_ai`, playback maths deterministic), club SFX (whistle, splash, crowd),
voiceover recording in-browser, the existing TTS surface grown into a real
voice layer (provider seam shipped: edge-tts today, Piper 1.7; add voice
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
fingerprint check on uploads); (2) timeline integration (1.6 tracks, ducking
under voiceover); (3) browser voice recorder; (4) generation (music/SFX) as
optional providers behind flags (Lyria-class via Gemini when available) with
the library as the no-key default; (5) dubbing = translate (1.24) + TTS;
voice *cloning* only with recorded consent of the voice owner, off by
default, per-org enable + audit. Vocal remover / stem split via a local
demucs-class provider slot (flagged; heavy).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | AI voiceovers (multi-language, voices, tone/pacing) | 🔵 TTS shipped (edge-tts opt-in; `MEDIAHUB_TTS_PROVIDER` seam, Piper ↗ 1.7) → 🆕 1.8 voice catalogue + params + pronunciation lexicon |
| C2 | AI music generation (~30s tracks) | 🆕 1.8 optional music-gen provider; licensed library is the default |
| C2 | AI sound effects generation | 🆕 1.8 optional SFX-gen provider; SFX library default |
| C5 | Audio library (stock music, genres) | 🆕 1.8 openly-licensed music pool with mood/energy tags |
| C5 | Popular music library (chart tracks, 60s, regional/non-commercial caveats) | 🚫 adapted — chart-music *rights* can't be built first-party; our own licensed pool stays the default, with a flag-gated rights slot behind our `library` interface + per-platform usability flags |
| C5 | Sound effects library | 🆕 1.8 SFX pool (sport set first) |
| C5 | Voiceover recording / voice recorder (desktop + mobile) with AI noise cancellation | 🆕 1.8 browser recorder + `clean.py` denoise |
| C5 | Audio trimming / clipping · Volume control (0–100, mute) · Fade in/out | 🆕 1.8 `ops.py` |
| C5 | Multiple audio track layering (up to 50) | 🆕 1.8 multi-track mix on the 1.6 timeline (sane cap, ducking built-in) |
| C5 | Audio sync with video / per-scene audio | 🆕 1.8 per-scene assignment in reel specs |
| C5 | Upload own audio (MP3/M4A/WAV, 250MB) | 🆕 1.8 upload + `rights.py` fingerprint/licence attestation |
| C5 | Ditto (Merlin-licensed uploads); audio fingerprint/Content ID checks | 🆕 1.8 `rights.py` (fingerprint check; licensed-pool integrations optional) |
| C5 | Extract Audio · Vocal Remover · Enhance Voice · AI Dubbing · Voice Changer · Text to Speech · AI Voice Cloning | 🆕 1.8 — extract (FFmpeg) · stem-split slot (flagged) · denoise · dubbing (1.24 + TTS) · changer/cloning consent-gated, off by default, audited · TTS = the shipped seam |
| C4 | Enhance Voice (Pro) · Balance All (AI volume levelling) | 🆕 1.8 `clean.py` + loudness normalisation (EBU R128) |
| C7 | Audio elements (in the elements tab) | 🆕 1.8 library exposed as insertable elements |
| A5 | Add audio tracks; adjust (volume, fades, trim, speed) | 🆕 1.8 `ops.py` (+ speed) |
| A5 | Add sound effects (library) | 🆕 1.8 SFX pool |
| A5 | AI voiceover / Generate Speech (45–70+ voices incl. ElevenLabs-supplied, 20+ languages, pitch/speed/emotion/tone, fix pronunciation, WAV download) | 🆕 1.8 voice layer (catalogue, params, lexicon, WAV export ↗ 1.19); premium hosted voices (ElevenLabs-class) = optional provider slots on our own TTS seam |
| A5 | AI voiceover add-ons (AiVOOV, WellSaid) | 🚫 adapted — provider slots behind the same TTS seam, not third-party add-on accounts |
| A5 | Music: royalty-free stock; TikTok Commercial Music Library; music recommendations with thumbs up/down | 🆕 1.8 our own library + AI `select.py` recommendation w/ feedback memory; platform-licensed pools (TikTok-CML-class) only through the same flag-gated rights slot, never a bundled third-party app |
| A5 | Enhance Speech (noise removal) | 🆕 1.8 `clean.py` |
| A5 | Animate from audio (character lip-sync) | ↗ 1.5 mascot animation (audio-driven) |
| A5 | AI Assistant audio controls (volume/fades/trim/speed/mute/timing) | ↗ P6.2 assistant patches audio spec; ops in 1.8 |
| A5 | Audio add-ons (Audio Equalizer, AI Audio Cleaner, Audio Visualizer, Voice Maker…) | 🆕 1.8 EQ + cleaner in `ops.py`/`clean.py`; waveform-visualizer overlay as a reel scene element; "voice maker" = TTS catalogue |
| A6 | Add tone/emotion in voiceovers | 🆕 1.8 TTS emotion/params |
| A2 | Generate Speech / AI voiceover (Firefly Speech) | 🆕 1.8 (same voice layer; counted under A2 in the index) |
| A2 | Enhance Speech (A2 listing) | 🆕 1.8 `clean.py` |

---

## 1.9 — Typography system & text effects

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
1.2 imagery clipped to glyph masks; (6) dynamic text = data-bound text
fields in specs (already how cards work — exposed as a first-class editor
concept).

**Shipped (1.9, 2026-06-20).** Live in four parts: `typography/catalog.{json,py}`
(curated self-hosted catalogue + per-org upload merge, lock-step asset guard),
`graphic_renderer/text_effects.py` (13 deterministic, APCA-policed effects as a
DesignSpec `text_effects` token, wired into the renderer — empty ⇒ byte-identical),
`brand/type_pairing.py` (catalogue-bound AI pairing, honest-error), and
`typography/formatting.py` plus the **Settings → Typography & fonts** web surface
(browse, AI pairing, licence-attested upload now wired to the renderer's
`@font-face`). **One sub-item is deferred to its dependency:** the
*AI-texture-in-glyph* half of Magic Morph / Generate Text Effect needs the **1.2**
generative-imagery backend — the deterministic clip-to-glyph substrate ships now
(gradient fills via `background-clip:text`), and an AI texture flows through the
same mask once 1.2 lands.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C6 | Font library (hundreds of free + premium fonts) | ✅ 1.9 curated self-hosted OFL catalogue (never CDN) |
| C6 | Font upload (custom/purchased, with permissions) | ✅ 1.9 per-org upload + licence attestation → self-hosted pipeline |
| C6 | Font pairing suggestions | ✅ 1.9 `brand/type_pairing.py` via `media_ai` |
| C6 | Text effects (style): Shadow, Lift, Hollow, Splice, Echo, Glitch, Neon, Background | ✅ 1.9 deterministic effect tokens (APCA-policed) |
| C6 | Text effects (shape): Curve | ✅ 1.9 curve-on-path |
| C6 | TypeExtrude (3D extruded text: length, angle, outline) | ✅ 1.9 extrude primitive (layered offsets) |
| C6 | TypeCraft (bend/warp/twist/reshape letters) | ✅ 1.9 warp primitive (SVG deformation) |
| C6 | Text Studio Maker (3,000+ effect templates) | 🚫 adapted — a tokenised effect vocabulary the director composes, not a template pile |
| C6 | Text formatting (colour, alignment, underline, strikethrough, links, lists/markers/levels, line height, size/weight/style) | ✅ 1.9 editor formatting depth |
| C6 | Gradients on text | ✅ 1.9 gradient fills from brand palette |
| C6 | Multilingual support (100+ languages; interface languages) | ↗ 1.24 (fonts here must carry the needed scripts) |
| C6 | Dynamic text / captions | ✅ 1.9 data-bound text fields (cards already do this; surfaced in the editor) |
| C6 | Text animations | ↗ 1.5 kinetic-type presets |
| C2 | Magic Morph (transform text/shapes with AI textures via prompt) | 🔵 1.9 clip-to-glyph substrate shipped (gradient via background-clip:text); AI texture-in-glyph ↗ 1.2 imagery |
| A2 | Generate Text Effect (AI textures/styles on letters) | 🔵 1.9 same texture-in-glyph substrate (gradient now); AI texture ↗ 1.2 |
| A6 | Add/edit text; titles/headings/body defaults; text hierarchy | 🔵 hierarchy exists in specs → ✅ 1.9 editor exposure |
| A6 | Tens of thousands of Adobe Fonts; custom upload; pairing/recommendations; search by style/mood | ✅ 1.9 catalogue + upload + AI pairing + mood search (catalogue tags) |
| A6 | Character/paragraph styling (colour, alignment, underline, strikethrough, size incl. decimals, weight, italic, line height, lists with nesting/markers, links) | ✅ 1.9 formatting depth |
| A6 | Copy text style (paintbrush); uppercase transform; find & replace; spellcheck (primary language) | ✅ 1.9 editor tools (deterministic) |
| A6 | Curved text; shadow effects on text | ✅ 1.9 effect tokens |
| A6 | Text animations | ↗ 1.5 |
| A6 | Auto-create hyperlinks | ✅ 1.9 (links live in PDF/doc/web outputs; plain images ignore them) |

---

## 1.10 — Elements, stock & drawing

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
(rights ledger shared with 1.8); paid stock stays an optional flag-gated
source feeding the same pool; (4) `draw/` annotate layer: pointer-capture freehand, RDP smoothing,
shape-snap (deterministic), stored as a spec layer; (5) shape generator =
1.2 generate with vector-style preset → traced SVG (flagged); (6) custom
emoji/sticker = club mascot pack (cutout + 1.5 animated sticker export);
(7) GIF/sticker search only via licence-clean sources.

**Status — shipped v1 (2026-06-20).** The library is live end-to-end:
`mediahub.elements` ships a 25-element brand-token-recolourable sport-editorial
pack (`models`/`catalog`/`catalog.json` + `recolour` + `render`), painted onto
cards by the auto-discovered `graphic_renderer/sprint_hooks/elements.py`
(opt-in, APCA-gated, byte-identical when off); embedding search reusing the
caption-memory embedder with an honest keyword fallback (`elements/search.py`)
plus contextual suggestions; brand-palette gradient presets (`elements/gradients`);
a licence-clean stock pool (`elements/stock.py` — Openverse/Wikimedia harvest,
shared `Licence`/rights ledger with 1.8, flag-gated paid sources, photo + video)
with org-scoped import; and a deterministic telestration draw layer
(`elements/draw.py` — RDP smoothing, Shape Assist auto-snap, symmetry, SVG +
Pillow render, stored as a spec layer on the asset) wired into the photo editor.
Club mascot stickers (`elements/stickers.py`) promote a cutout into an org-custom
element. Web surface: `/elements`, `/stock`, `/annotate/<asset_id>` + the
`/api/elements*`, `/api/stock/*`, `/api/media-library/<id>/annotate|make-sticker`
routes. **Deferred to 1.2 (generative imagery):** the AI *shape generator*, the
"generate an element" entry and 3D-render elements are an honest seam
(`elements/generate.py` raises `GenerativeElementsUnavailable`) until 1.2 lands.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C7 | Graphics library (1M+ elements) | 🚫 adapted — curated sport-editorial packs, brand-token recolourable |
| C7 | Stickers | ✅ 1.10 sticker packs (+ club mascot stickers; animated ↗ 1.5) |
| C7 | Icons | ✅ 1.10 icon set (sport pictograms first) |
| C7 | Shapes + Shape Generator (AI unique shapes) | ✅ 1.10 shape library; AI generator via 1.2 (honest seam until 1.2) |
| C7 | Lines | ✅ 1.10 line/divider set |
| C7 | Photos library (stock) | ✅ 1.10 our own licence-clean photo pool (open-collection seeded; paid sources flag-gated); venue shots ✅ shipped (`venue_search`) |
| C7 | Stock videos | ✅ 1.10 our own licence-clean stock-video pool (feeds 1.6) |
| C7 | Gradients | ✅ 1.10 gradient presets from brand palette (linear/radial) |
| C7 | Tables · Charts/Graphs (20+ types) · Interactive charts (Flourish embeds) | ↗ 1.11 |
| C7 | Draw / Drawing tools (freehand, Shape Assist) | ✅ 1.10 annotate layer (telestration) |
| C7 | 3D elements (3D Content Generator) | 🆕 1.10 3D-render element pack (crest/trophy renders via 1.2, cached as images) |
| C7 | AI-Powered Elements (generate photos/videos/code/icons/shapes/3D from the Elements tab) | 🆕 1.10 "generate an element" entry → 1.2 services (code widgets ↗ 1.16) |
| C7 | Frames, grids | ✅ 1.10 frame/grid elements (shared masks with 1.3) |
| C7 | Custom emojis | ✅ 1.10 club emoji/mascot pack |
| C7 | Backgrounds | ✅ 1.10 background packs + `venue_search` ✅ + 1.2 generation |
| C4 | Stock footage library (Artlist etc.) / Video Marketplace | ✅ 1.10 our own stock-video pool (licence-clean default; paid sources flag-gated) |
| A10 | Draw with brushes (markers, pencils, paints, colours) | ✅ 1.10 annotate brushes (stylised strokes) |
| A10 | Draw with symmetry; snap to shape; coloring mode (stay in lines) | ✅ 1.10 symmetry mirror + shape-snap; colouring mode pairs with `kids_activity_sheet` (P6.1) |
| A11 | Adobe Stock integration (200M+ assets) | 🚫 adapted — our own curated pool (open-collection seeded) instead of a vendor stock integration; paid sources optional behind flags |
| A11 | Icons, shapes, backgrounds, overlays, frames, graphics, stickers, GIFs | ✅ 1.10 element packs (GIF/sticker sources licence-clean) |
| A11 | Grids | ✅ 1.10 |
| A11 | Gradients (linear/radial, prompt-driven) | ✅ 1.10 presets; prompt-driven gradient = brand-palette interpolation via `media_ai` suggestion |
| A11 | Design elements search & browse; contextual recommendations | ✅ 1.10 embedding search + `context_engine`-aware suggestions |
| A11 | Color themes; apply color themes; custom gradients; import from Adobe Color | ↗ 1.12 palette layer (Adobe-Color import = palette-file import) |
| A11 | QR code generator (custom colour/style/logo; PNG/JPEG/PDF/SVG) | ↗ 1.16 |
| A11 | Charts; tables (add/customize) | ↗ 1.11 |

---

## 1.11 — Charts, infographics & data storytelling

> ✅ **Shipped** (`src/mediahub/charts/`). The deterministic engine (typed chart
> specs → brand-styled SVG: bar/hbar/line/progression/pie/donut/scatter/table/
> medal-table/split-ladder), the data plumbing (`aggregates.py` + `series.py` over
> canonical results / detector output / `club_records`, `csv_input.py` for uploads),
> the two grounded AI surfaces (`recommend.py` picks the lead chart, `insights.py`
> phrases pre-computed facts with a fabricated-number guard + source links), and the
> data-driven diagram formats (`diagrams.py`: committee org chart, season timeline,
> athlete journey, training flow) are all in. Surfaced on the content builder at
> `/runs/<id>/charts`. Scroll-story export + interactive widgets remain forward to
> 1.15/1.16 (static-first, as specified).

**What Canva/Adobe have.** 20+ chart types editable via data table, CSV
import, interactive charts (Flourish: treemaps, packed circles, maps), Magic
Charts (data→chart with recommendations, real-time sync), Magic Insights (AI
analysis: patterns, trends, takeaways), Magic Formulas, infographics,
diagram types (mind maps, flowcharts, org charts, Gantt, timelines, T-charts,
synoptic tables, Kanban, roadmaps, journey maps), scrollable data
storytelling.

**The MediaHub shape.** This is home turf: MediaHub already *owns* clean,
parsed, trustworthy results data — the one thing Canva never has. 1.11 turns
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
+ `history/` + CSV upload (1.13 hub); (3) `charts/recommend.py` — AI picks
chart type + headline stat with reasons (honest-error); (4)
`charts/insights.py` — AI takeaways constrained to provided aggregates
(numbers computed deterministically first; the LLM phrases, never
calculates); (5) diagram `FormatSpec`s (org chart from committee roster,
season timeline from fixtures, journey = athlete career map from history);
(6) scrollytelling = multi-page story export (1.15/1.16) where each page
reveals one chart beat; interactive variants ship as microsite widgets
(1.16), static-first everywhere else.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Infographics | 🆕 1.11 stat-graphic `FormatSpec`s from results data |
| C1 | Mind maps, flowcharts, org charts, Gantt, timeline charts, T-charts, synoptic tables, Kanban boards, roadmaps, customer journey maps | 🆕 1.11 data-driven diagram formats (committee org chart, season timeline/Gantt, training flowcharts, athlete journey); Kanban ↗ 1.14 planner board |
| C2 | Magic Charts (AI data-to-chart + recommendations) | 🆕 1.11 `recommend.py` over canonical results |
| C2 | Magic Insights (AI patterns/trends/takeaways) | 🆕 1.11 `insights.py` — grounded, source-linked takeaways |
| C7 | Tables (table maker) | 🆕 1.11 brand-styled table spec (heat sheets, results tables) |
| C7 | Charts/Graphs (20+ types, editable data table, CSV import) | 🆕 1.11 chart spec library + CSV series input |
| C7 | Interactive charts (Magic Charts, Flourish embeds — treemaps, packed circles, maps) | 🆕 1.11 static-first; interactive widgets on microsites ↗ 1.16 |
| C11 | Magic Charts (data-to-chart, real-time sync) | 🆕 1.11 charts re-render when run data updates (spec-bound series) |
| C11 | Magic Insights (AI data analysis) | 🆕 1.11 `insights.py` |
| C11 | Match & Move animation / Scrollable Designs for data storytelling | scroll-story export 🆕 1.11/1.15; match-&-move motion ↗ 1.5 |
| A11 | Charts (elements listing) | 🆕 1.11 |
| A11 | Tables (add/customize) | 🆕 1.11 |
| C1 (cross-ref A1) | Infographics (Adobe template category) | 🆕 1.11 (same formats; indexed under A1 in the completeness table) |

---

## 1.5 — Animation & motion system

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
motion per scene); 1.5 widens the vocabulary and exposes manual overrides.
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
audio-driven timing: beats from 1.6's beat grid drive preset timing; mascot
lip-sync (animate-from-audio) as a later opt-in on the avatar rule's safe
side (a *mascot*, not a person); (7) caps + reduce-motion mirrored from the
source products as accessibility guardrails.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C8 | Page animations + Element animations (Page/Element/Text tabs) | 🆕 1.5 motion tokens per element/page |
| C8 | Animation presets (free + Pro lists) | 🆕 1.5 preset vocabulary (named set covering the Canva/Adobe families) |
| C8 | Photo movement (Photo Flow/Rise/Zoom) | 🔵 Ken Burns shipped (FFmpeg reel) → 🆕 named photo-motion presets |
| C8 | Create an Animation (Motion Path) + orient-to-path + speed slider | 🆕 1.5 path animations (SVG path + orient flag) |
| C8 | Match & Move (shared-element page transition) | 🆕 1.5 shared-element transitions in both reel engines |
| C8 | Magic Animate (AI one-click animation + transitions) | 🔵 SEQ-4 archetype-matched motion shipped → 🆕 whole-design motion-family assignment |
| C8 | Appear on click / Click order | 🆕 1.5 click/step order (deck surfaces ↗ 1.15) |
| C8 | Show element timing (timing/duration) | 🆕 1.5 timing inspector |
| C8 | Add-on effects combined with base animations | 🆕 1.5 composable `loop` layer on top of in/out |
| C8 | Page transitions (Dissolve/Fade, Slide, Color Wipe, Line Wipe, Circle Wipe, Match & Move) | 🔵 crossfade shipped → 🆕 transition set in both engines |
| C8 | Reduce motion accessibility setting | 🆕 1.5 reduce-motion variants honoured everywhere |
| C8 | Limits (10s per animation; 50 per design) | 🆕 1.5 engineering caps (sanity + render cost) |
| A3 | Animated images (Spin, Pop, Jitter, Slide, Zoom, Pan, Wobble, Wind, colour/fade/blur animations) | 🆕 1.5 photo/sticker animation presets (GIF/MP4 export ↗ 1.19) |
| A12 | Animate all (one click) or per-element (text, icons, shapes, letters, photos, videos) | 🆕 1.5 whole-design family + per-element overrides |
| A12 | In / Loop / Out model; presets (Bungee, Fade, Flicker, Grow, Pop, Shrink, Slide, Spin, Tumble); loops (Blinking, Bob, Breathe, Jitter, Pulse, Wiggle, Yoyo) | 🆕 1.5 in/loop/out is the vocabulary's native model |
| A12 | Visibility/Move/Scale animations; intensity, speed, direction, personality controls | 🆕 1.5 preset parameters |
| A12 | Start/end outside page | 🆕 1.5 off-canvas keyframes |
| A12 | Dynamic physics presets (Wobble, Wind, Breeze, Turbulence, Bounce Loop) | 🆕 1.5 parametric physics-flavoured curves |
| A12 | Page transitions in multi-page designs | 🆕 1.5 |
| A12 | Animate from audio (character animation lip-sync) | 🆕 1.5 mascot lip-sync (audio-driven, opt-in; never a synthetic person) |
| A12 | Animated stickers | 🆕 1.5 animated mascot/sticker exports (↗ 1.10 packs) |
| A12 | Animated images export as GIF | ↗ 1.19 GIF export |
| A8 | Animation sequencing / click order (Adobe presentations) | 🆕 1.5 step order (surfaced in 1.15) |

---

## 1.12 — Brand platform depth

**Status: shipped (2026-06-21).** Multi-kit model (`brand/kits.py`:
primary/sponsor/event/section/personal kits with token locks + sponsor pairing
rules), deterministic Brand Check + AI Brand Assist (`brand/check.py`), brand
home + multi-kit management + Adobe `.ase`/Color-JSON palette import
(`brand/palette_file.py`), governance enforced at approval (token locks +
group-approver rules — `workflow/governance.py`, `workflow/approvals.py`), and
the kit-edit → re-render sweep with diff preview (`brand/resweep.py`). The
coverage table below maps each Canva/Adobe feature to where it now lives.

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
tokens, the theming engine). 1.12 completes it as a **brand platform**:
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
CardStatus transitions (↗ 1.18 for the workflow UI); (5) kit-edit →
re-render sweep over persisted briefs with diff preview; (6) palette-file
import (Adobe Color `.ase`/JSON → kit palette through the existing
evidence-grounded pipeline).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C9 | Brand Kit(s) — logos, colours, fonts, icons, imagery, graphics, brand voice (up to 100 kits) | 🔵 single BrandKit + voice shipped → 🆕 1.12 multi-kit (sponsor/event/section kits) |
| C9 | Brand Kit Builder (auto-extract from website or PDF) | ✅ shipped — URL: P1.5 local brand-DNA; PDF: `brand/guidelines.py` + `dna_capture.py` |
| C9 | Brand Templates (reusable on-brand templates) | 🆕 1.12 locked org formats (a saved `FormatSpec` + kit binding; catalogue ↗ P6.1) |
| C9 | Brand Controls (restrict colours/fonts; require design approval) | 🆕 1.12 token locks + approval-required rule (approval flow ✅ shipped in `workflow/`) |
| C9 | Brand Kit homepage (logos/templates/colours/guidelines/tone/product photography hub) | 🆕 1.12 brand home route |
| C9 | Brand Guidelines accessible in editor with usage guidance | 🔵 guidelines ingestion shipped → 🆕 in-editor surfacing |
| C9 | Brand Assist (real-time on-brand suggestions + auto-fix for colours/fonts/logos/photos/icons) | 🆕 1.12 `brand/check.py` + auto-fix spec patches |
| C9 | Brand folders / linked folders | ↗ 1.18 folders (kit-scoped views) |
| C9 | Color themes / palettes | ✅ shipped — theming engine (DTCG palette, MD3 roles) |
| C9 | Approval workflows (group approvers, approval rules) | 🔵 per-card approval + publish gate shipped → 🆕 group-approver rules ↗ 1.18 |
| C9 | Team-level brand sharing (kits/templates to specific teams) | 🆕 1.12 kit sharing across workspaces (org → section) |
| C9 | Personal Brand Kits | 🆕 1.12 personal kits (e.g. a coach's own side projects) — low priority, same schema |
| C9 | Role-based permissions for AI/brand features | 🆕 1.12 role flags (consumed by 1.23 governance) |
| C9 | Replace logos/images across designs in a few clicks | 🆕 1.12 kit-edit re-render sweep from persisted briefs |
| A13 | Brand kits (logos, colours, fonts, graphics; one-tap apply; multiple kits premium) | 🆕 1.12 multi-kit + one-tap apply (= re-theme via tokens) |
| A13 | Custom fonts in brands; colour themes in brands; apply brand to pages/images/illustrations | 🆕 1.12 (fonts ↗ 1.9 pipeline; apply-to-image = brand-aware duotone/recolour via 1.3) |
| A13 | Brand style restrictions / template control | 🆕 1.12 token locks |
| A13 | Multi-brand referencing (up to 5 brands per template) | 🆕 1.12 sponsor co-branding (multi-kit composition rules) |
| A13 | Brand Check (beta) | 🆕 1.12 `brand/check.py` |
| A13 | Share/leave brands; edit roles | 🆕 1.12 kit membership + roles (rides PC.3 tenancy) |
| A11 | Import color themes from Adobe Color | 🆕 1.12 palette-file import (.ase/JSON) |
| C2 | Canva AI 2.0 brand-intelligence workflow | 🆕 1.12 brand check/assist as assistant tools (via P6.2) |

---

## 1.15 — Documents, decks & the PDF suite

> **Status: ✅ shipped.** Built as the `documents/` package — `DocumentSpec →
> Section → Block` model, brand-tokened paged HTML → PDF (tagged/accessible) +
> PNG previews, the four data-grounded club formats (`meet_programme` /
> `season_report` / `sponsor_proposal` / `agm_deck`) with honest AI outline→draft,
> PPTX/DOCX export + PPTX/DOCX/PDF import (bounded fidelity), PDF utilities
> (merge / organise / images↔PDF), deck→MP4, and the deck presenter surface
> (speaker notes, timer, autoplay/kiosk, phone-as-remote, live-reload). Web
> surface at **Create → Documents** (`/documents`, `/present/<id>`, `/remote`).

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
deck. 1.15 builds one **document engine**: multi-page, brand-tokened
compositions assembled from the same card/chart/text primitives (Playwright
already renders HTML → the engine adds paged HTML → PDF with print CSS), an
AI outline-then-build flow for decks and reports (data-grounded: season
report pulls real aggregates via 1.11), and a **presenter surface** for the
deck format (presenter notes, timer, autoplay, phone-as-remote via the
existing session infra, record-a-talkover via 1.6's recorder). PDF
*utilities* (merge/organise/convert) ship as honest, bounded tools on the
export surface (pypdf-class, deterministic) because committee volunteers
genuinely need them — not as an Acrobat clone.

**Build sketch.** (1) `documents/` package: paged `DocumentSpec` (sections →
blocks: text, card-embed, chart-embed, table, media), HTML/print-CSS
renderer → PDF (Playwright `page.pdf`, CMYK/bleed handled in 1.20); (2)
deck mode: same spec, slide-sized pages + step order (1.5) + presenter
route (notes, timer, remote pairing code) + autoplay; (3) AI flows:
outline→draft for `season_report`, `sponsor_proposal`, `agm_deck`,
`meet_programme` formats (all data-grounded, honest-error); (4) exports:
PDF (standard/print), PPTX/DOCX via deterministic converters
(python-pptx/docx) for take-it-elsewhere editing, deck→MP4 via the reel
engine (each slide a scene); imports: PPTX/DOCX/PDF → blocks (fidelity
bounded and stated); (5) PDF utilities: merge, reorder/rotate/delete pages,
images→PDF, PDF→images, with a11y tagging on export (tagged headings/alt
text from the spec); (6) "Scrollables"/whiteboard-expansion map to the
scroll-story export (1.11) and the planner board (1.14) respectively.
Audience Q&A/polls (Canva Live) ride the microsite widget layer (1.16) as
a meet-night companion page.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Presentations (incl. responsive/cinematic) | 🆕 1.15 deck format on the document engine |
| C1 | Canva Docs (text documents) | 🆕 1.15 club document formats (report/proposal/programme) |
| C1 | Reports · Proposals | 🆕 1.15 `season_report` / `sponsor_proposal` (data-grounded AI drafts) |
| C2 | Guided Presentations (goal/story/structure before slides) | 🆕 1.15 outline-then-build flow driven by the P6.2 assistant |
| C11 | Canva Docs — embed charts/sheets; Scrollables | 🆕 1.15 chart/table embeds (1.11); scroll-story export (1.11/1.16) |
| C12 | Presenter View (previews, notes, timer) · Presenter notes | 🆕 1.15 presenter route |
| C12 | Standard / full-screen / Presenter View modes | 🆕 1.15 view modes |
| C12 | Autoplay (timed transitions) | 🆕 1.15 autoplay (kiosk mode for club foyer screens — a real club use) |
| C12 | Recording yourself presenting / talking presentations | 🆕 1.15 talkover recording (1.6 recorder) |
| C12 | Remote Control (control slides from any device via link/QR) | 🆕 1.15 phone-remote pairing |
| C12 | Canva Live (audience Q&A, reactions, polls) | 🆕 1.15 meet-night companion page via 1.16 widgets (Q&A/poll, moderated) |
| C12 | Magic Shortcuts (presenting keyboard effects: blur, drumroll, confetti, timers) | 🆕 1.15 presenter effects (confetti for medal slides; timer for warm-ups) — small, deterministic |
| C12 | Offline presenting mode | 🆕 1.15 PWA-cached deck (↗ 1.22; hosted-only stands — it's a browser cache, not an install) |
| C12 | Real-time live edits during presentation | 🆕 1.15 live spec reload (long-poll/SSE) |
| C12 | Expand slide to infinite Whiteboard | ↗ 1.14 planner board (the whiteboard analogue) |
| C12 | Turn presentation into a video | 🆕 1.15 deck→MP4 via reel engine |
| C12 | Export as PowerPoint, PDF, video slideshow, or website | 🆕 1.15 PPTX/PDF/MP4 exports; deck→microsite ↗ 1.16 |
| C1 | Whiteboards (infinite canvas) | ↗ 1.14 planner board |
| A7 | Convert to PDF (from Word/Excel/PowerPoint/images) | 🆕 1.15 bounded converters (images/docx/pptx→PDF; spreadsheet→PDF via 1.13 tables) |
| A7 | Convert from PDF (to Word/Excel/PowerPoint/RTF/JPG/PNG) | 🆕 1.15 PDF→images + text extraction (full Office fidelity explicitly bounded) |
| A7 | Edit PDF (text, images, layout, brand colours/fonts) | 🆕 1.15 import-to-spec → edit → re-export (not in-place PDF surgery) |
| A7 | Merge / Combine files into one PDF (+ rotate/delete/reorder) · Organize pages | 🆕 1.15 PDF utilities (pypdf-class, deterministic) |
| A7 | Import PDFs with table/mask fidelity; export with high-fidelity text in 20+ scripts; PDF accessibility tags | 🆕 1.15 import fidelity bounded + tagged-PDF export (fonts w/ script coverage ↗ 1.9) |
| A7 | Export PDFs with gradients; CMYK profile; print PDFs | ↗ 1.20 print pipeline |
| A7 | Free-plan PDF quick-action limits | ↗ 1.23 quota layer (PC.4 packaging decides numbers) |
| A8 | Design and deliver presentations; presentation templates; presenter mode; video controls in presentation | 🆕 1.15 deck format + presenter route (video blocks honour play controls) |
| A8 | Generate presentation (AI, from prompts or uploaded documents) | 🆕 1.15 outline-then-build (upload → grounded draft) |
| A8 | Create documents from templates or scratch; add and format text in documents | 🆕 1.15 document formats + editor |
| A8 | Import PowerPoint; export to PPTX; multi-page zoom controls | 🆕 1.15 PPTX round-trip + canvas zoom |
| A2 | Generate presentation (A2 listing) | 🆕 1.15 (same flow; indexed under A2) |
| C2 | Magic Switch deck→doc/blog transforms | ↗ P6.1 format transformer (uses this engine's specs) |

---

## 1.16 — Club microsites, link-in-bio, forms & interactive widgets

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
data back into the org's data hub (1.13): trial sign-ups, volunteer
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
ADR-0003 — minors' data rules apply hard here), responses into the 1.13
hub + notify hooks; (3) widget catalogue: audited component primitives +
AI composer constrained to them; SSO/password protection per page; (4)
SEO: per-page meta/sitemap/favicon/alt-text (alt text AI-suggested,
human-editable), AI SEO description honest-erroring without provider; (5)
insights: privacy-respecting first-party page analytics (counts, not
tracking) ↗ 1.14 surfaces them; (6) QR generator (deterministic,
brand-coloured with contrast guard, logo-embedded; PNG/SVG/PDF export) for
posters → pages/forms; (7) device preview = responsive preview frames in
the editor.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Websites (multipage, responsive) | 🆕 1.16 data-generated club pages/microsites |
| C1 | Canva Code designs (interactive experiences) | 🆕 1.16 vetted widget catalogue (AI-composed from audited primitives) |
| C13 | Website builder (drag-and-drop, no code, multipage, responsive) | 🆕 1.16 section/block editing on `SiteSpec` (generated-first, edited second) |
| C13 | Templates for websites | 🆕 1.16 site archetypes (meet microsite, link-in-bio, event page, club home) |
| C13 | Free my.canva.site domain (capped free sites) | 🆕 1.16 per-org subdomain on the platform domain |
| C13 | Custom domain purchase | 🚫 adapted — no registrar business; BYO domain only |
| C13 | Bring your own domain | 🆕 1.16 BYO domain (CNAME + managed cert) |
| C13 | SSL, domain lock, WHOIS privacy, password protection, SSO | 🆕 1.16 SSL + password/SSO-protected pages (domain lock/WHOIS = registrar concerns, out with the registrar role) |
| C13 | Website Insights (traffic/views/engagement) | 🆕 1.16 first-party, privacy-respecting page counts → 1.14 analytics |
| C13 | SEO (auto sitemaps, meta title/description, favicon, alt text, AI SEO descriptions) | 🆕 1.16 SEO layer |
| C13 | Canva Forms integration | 🆕 1.16 forms on pages |
| C13 | Canva Code interactivity (calculators, countdowns, widgets) | 🆕 1.16 widget catalogue (countdown-to-meet, medal tally, lane lookup) |
| C13 | Device preview (desktop/tablet/mobile) | 🆕 1.16 responsive preview |
| C13 | Navigation menus, social links, link-in-bio sites | 🆕 1.16 nav blocks + link-in-bio archetype |
| C13 | No native e-commerce (noted limitation) | 🆕 1.16 mirrors it honestly: payment links out to the club's existing store/Stripe links (`ticket_merch_promo` type), no checkout build |
| C11 | Canva Forms (RSVPs, feedback, surveys, sign-ups; responses → Sheets) | 🆕 1.16 forms → 1.13 data hub rows |
| C17 | Canva Code (AI interactive experiences; built on Claude; HTML import; copy/reuse code; publish as website) | 🆕 1.16 widget composer (sandboxed primitives; no arbitrary hosted code) |
| C17 | Canva Code 2.0 (fully interactive from a prompt, responsive, forms to Sheets, SSO-protected publishing) | 🆕 1.16 (same composer + forms + SSO pages) |
| C12 | Export presentation as Canva website | 🆕 1.16 deck→page export |
| A9 | Design webpages; webpage templates; publish/host webpages; export webpage as PDF | 🆕 1.16 pages + PDF snapshot export (via 1.15 renderer) |
| A9 | Navigation bar / TOC with anchor links; enhanced text handling | 🆕 1.16 anchor nav blocks |
| A2 | Generate QR code | 🆕 1.16 QR generator (brand-safe colours, logo embed) |
| A11 | QR code generator (custom colour/style/logo; PNG/JPEG/PDF/SVG output) | 🆕 1.16 (same generator; vector + print exports) |

---

## 1.17 — Email & newsletter design

**What Canva/Adobe have.** Canva Email Design — branded email campaigns,
exportable as HTML; newsletters as a design type.

**The MediaHub shape.** The parent/member **newsletter is already a
`turn_into` output** (text). 1.17 makes it visual and sendable-anywhere:
brand-tokened, email-safe HTML (table-based layout, inlined CSS, dark-mode
aware, bulletproof buttons, image fallbacks — the existing email theming
surface grown into a real composer), assembled automatically from the
period's approved content (results recaps, spotlights, upcoming fixtures
from the planner, sponsor slot) with an AI editorial pass in the club's
voice. Export = paste-ready HTML for the club's existing list tool
(Mailchimp-class) + a hosted web version (1.16 page); direct sending stays
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
| C1 | Canva Email Design (branded campaigns, HTML export) | 🆕 1.17 email-safe composer + HTML export |
| C1 | Newsletters (design type) | 🔵 text newsletter shipped (`turn_into`) → 🆕 1.17 visual newsletter formats |

---

## 1.13 — Data hub, bulk generation & personalisation at scale

**What Canva/Adobe have.** Canva Sheets (visual spreadsheets, media in cells,
sort/freeze/number formats, CSV/XLSX/PDF round-trip), Sheets AI (structured
sheet from a prompt), Magic Formulas, Magic Insights, Bulk Create (many
designs from CSV/XLSX), Magic Studio at Scale (bulk personalised/localised
content from Sheets), Data Autofill via API, Data Connectors (Google
Analytics, HubSpot, Snowflake, Statista) with refresh, bulk
create-and-automate (spreadsheet-driven), batch processing.

**The MediaHub shape.** MediaHub *is* structured-data-first — the canonical
results store is the "sheet". 1.13 makes that store a user-facing **data
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
`pb_discovery`, club CRMs later — each normalised to `canonical.*` (4.4
discipline) with refresh schedules on the `scheduler/`.

**Build sketch.** (1) `data_hub/` package: table registry over the
canonical store + org tables (form responses, rosters, sponsor facts),
grid UI (sort/filter/freeze/format), cell provenance badges, import/export
(CSV/XLSX/PDF print via 1.15); (2) `data_hub/derive.py` — registered
deterministic derivations + AI-suggested (human-confirmed) definitions;
(3) `bulk/` — `bulk_generate(format_spec, row_query, per_row_bindings)` →
batched pipeline runs with progress, queueing into review (rate/quota
caps ↗ 1.23); (4) connector framework: pull adapters with schedules,
normalisation to `canonical.*`, per-source trust metadata feeding
`SafeToPost` provenance; (5) "sheet from a prompt" = AI-scaffolded table
schema (columns + types) for org tables; insights/analysis ↗ 1.11.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C1 | Canva Sheets (visual spreadsheets) | 🆕 1.13 data hub grid over canonical + org tables |
| C2 | Sheets AI (structured spreadsheet from a prompt) | 🆕 1.13 AI-scaffolded org-table schemas |
| C2 | Magic Formulas (AI spreadsheet formulas) | 🆕 1.13 AI-*suggested*, human-confirmed deterministic derivations |
| C2 | Bulk Create (many designs from CSV/Excel/spreadsheet) | 🆕 1.13 `bulk_generate` (review-queued, never auto-published) |
| C2 | Magic Studio at Scale (bulk personalised/localised from Sheets) | 🆕 1.13 per-row personalised packs (+ 1.24 localisation) |
| C11 | Canva Sheets detail (media/links/mentions/dates/drop-downs in cells; sort, freeze, number formatting; CSV/XLSX/PDF up/download) | 🆕 1.13 grid features (media cells link `media_library` assets) |
| C11 | Data autofill (third-party data → brand template via API) | 🆕 1.13 autofill bindings (public API ↗ 1.21) |
| C11 | Bulk Create (C11 listing) | 🆕 1.13 |
| C11 | Data Connectors (Google Analytics, HubSpot, Snowflake, Statista; refresh) | 🚫 adapted — club-relevant connectors instead (Swim England API, rankings, club CRM); scheduled refresh on `scheduler/`; GA-class analytics ↗ 1.14 |
| C11 | Magic Studio at Scale (C11 listing) | 🆕 1.13 |
| C11 | Connect API / Autofill API / Brand Templates API | ↗ 1.21 public API surface |
| A17 | Bulk create & automate (spreadsheet-driven) | 🆕 1.13 |
| A18 | Bulk create (A18 listing) | 🆕 1.13 |
| C19 | Batch processing (Affinity pixel studio) | 🆕 1.13 batch recipe application over media assets (1.3 recipes at scale) |

---

## 1.14 — Planner, calendar, whiteboard & performance analytics

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
1.14 gives it a **calendar body**: month/week board where planned items,
drafts, scheduled posts (draft scheduling shipped) and published results
live together; drag to reschedule (gates re-evaluated on every move);
**club-aware key dates** preloaded (season fixtures, champs deadlines,
awareness days relevant to grassroots sport) rather than generic "National
Donut Day"; per-channel preview (exact crop/safe-zone/caption-truncation
per platform — safe-zone masks also exposed in the editors); and the
**performance loop**: once P4 adapters exist, pull per-post metrics back,
attribute them to post types/archetypes/times, feed the planner's ranking
(the data advantage compounds — "spotlights outperform recaps 3:1 for this
club, schedule more"), with AI-written performance digests via 1.11
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
bulk-generate N creative variants (1.13) tagged for the sponsor, exported
to the ad platform's specs.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C15 | Content Planner (social calendar, schedule/plan, drag-and-drop) | 🔵 planner + draft scheduling shipped → 🆕 1.14 calendar/board UI with drag |
| C15 | Direct publishing (FB Pages/Groups, IG Business, X, LinkedIn, Pinterest, TikTok, Tumblr, Google Business Profile) | ↗ P4.1–P4.3 platform adapters (approval-gated) |
| C15 | Social media holidays pre-loaded | 🆕 1.14 club-aware key-date packs |
| C15 | Pause/edit scheduled posts without re-uploading | 🆕 1.14 schedule mutations (gate re-evaluated) |
| C15 | Social performance analytics / Insights (impressions, clicks, likes, comments) | 🆕 1.14 metrics ingest + attribution (post-P4) |
| C15 | Caption/hashtag/emoji/link editing in planner; save drafts | 🔵 caption editing + drafts shipped → 🆕 inline planner editing |
| C15 | Channel preview before scheduling | 🆕 1.14 per-platform preview frames |
| C15 | Per-channel account permissions (private/team-viewable/team-publishable) | 🆕 1.14 channel ACLs (rides PC.3 roles; publish stays gated) |
| C15 | Canva Grow (AI ad variants from website scan, publish to Meta, performance tracking) | 🚫 adapted — sponsor A/B creative sets prepared for export; no ad spend automation; performance loop via 1.14 analytics |
| C1 | Whiteboards (infinite canvas) | 🆕 1.14 planning board (cards → planner items) |
| C1 | Kanban boards (diagram listing's planning sense) | 🆕 1.14 board columns (idea → drafted → approved → scheduled) |
| C12 | Expand slide to infinite Whiteboard | 🆕 1.14 board link from deck (the deck page becomes a board card) |
| C2 | Canva AI 2.0 scheduling workflow | 🆕 1.14 assistant can propose schedule changes (human confirms; gate applies) |
| A14 | Content Scheduler (plan, preview, schedule, publish to TikTok/IG/FB/Pinterest/LinkedIn/X) | ↗ P4 adapters + 🆕 1.14 calendar |
| A14 | Shared calendars; multi-account | 🆕 1.14 org calendar shared across members (PC.3); multi-account per channel |
| A14 | Grid preview | 🆕 1.14 IG grid preview (planned feed as a grid) |
| A14 | Social media analytics (via Metricool) | 🆕 1.14 our own first-party ingest from the platform APIs (no aggregator dependency) |
| A14 | Social mentions | 🆕 1.14 mention/tag fields per channel post (validated per platform) |
| A14 | Social safe zones | 🆕 1.14 safe-zone overlays in editors + previews |
| A14 | Caption writer (AI) | ✅ shipped (`web/ai_caption.py`) |
| A14 | TikTok Ads Manager | 🚫 adapted — creative prepared to ad specs; spend stays in the platform |
| A14 | Direct publish to Instagram/Vimeo | ↗ P4.2 (+ Vimeo optional target) |
| A14 | Set/connect social accounts | ↗ P4 (human-connected, least-privilege) |
| A14 | Activation cards in calendar | 🆕 1.14 key-date "activation" suggestions on the calendar (planner-generated) |

---

## 1.18 — Collaboration & review

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
| C16 | Real-time co-editing | 🆕 1.18 own patch-merge co-editing on DesignSpecs (presence later, demand-gated) |
| C16 | Comments (tag/mention teammates, reactions) | 🆕 1.18 anchored threads + mentions + reactions |
| C16 | Assigning tasks to teammates | 🆕 1.18 tasks blocking approval |
| C16 | Version history (view/restore) | 🔵 revisions persist today → 🆕 diff + restore UI |
| C16 | Folders (organise and share assets) | 🆕 1.18 collections over runs/packs/assets |
| C16 | Teams (shared brand kits, templates, folders) | 🔵 PC.3 workspaces shipped → 🆕 shared kit/format/collection scoping (kits ↗ 1.12) |
| C16 | Live edits / show live edits during presenting | ↗ 1.15 live spec reload |
| C16 | Lock elements | 🆕 1.18 element locks (patch-time enforced) |
| C16 | Group/role-based permissions (Editors, Viewers, Commenters; enterprise groups) | 🆕 1.18 roles on the membership ledger |
| C16 | Team Context (surfaces brand-relevant content) | 🆕 1.18 org context panel (same context the AI reads) |
| C16 | Ask @Canva (collaborative AI in comments) | 🆕 1.18 tag the P6.2 assistant in threads |
| C9 | Approval workflows (group approvers, approval rules) | 🔵 per-card approval + publish gate shipped → 🆕 1.18 group-approver rules |
| C9 | Brand folders / linked folders | 🆕 1.18 kit-scoped collections |
| C15 | Share links (view/edit/comment); template links | 🆕 1.18 scoped share tokens; "template link" = share a saved `FormatSpec` |
| A15 | Real-time co-editing; invite collaborators | 🆕 1.18 (invites ✅ shipped in PC.3 membership invites) |
| A15 | Comments (incl. on locked objects, contextual commenting) | 🆕 1.18 anchored threads (locked elements still commentable) |
| A15 | Share as view-only links; copy files between accounts | 🆕 1.18 share tokens; copy-between-workspaces (org export/import, isolation-audited) |
| A15 | Version history | 🆕 1.18 |
| A15 | Review & approval workflows (incl. Workfront-class) | 🔵 shipped core → 🆕 group rules; external PM-tool sync deliberately not built (own reviewer flow instead) |
| A15 | Object locking; lock/unlock elements | 🆕 1.18 |
| A15 | Libraries (create/share); Projects (create/share/move/copy); Creative Cloud Libraries | 🆕 1.18 collections + org asset libraries (our own; no CC dependency) |

---

## 1.19 — Export, conversion & delivery engine (quick actions)

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
1.15, WAV via 1.8); (2) export options schema + UI (quality/scale/
transparency/colour profile); (3) bulk export jobs on `scheduler/`
(zip-batched, progress, notify); (4) media-library quick actions (image
convert/resize/crop; video trim/crop/resize/merge/speed/reverse/mute/
caption; GIF↔MP4; images→PDF) calling 1.3/1.6/1.15 ops; (5) share
links unified with 1.18 tokens.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C15 | Export formats: PNG, JPG, PDF (standard + print), SVG, MP4, GIF, PPTX, DOCX, CSV | 🔵 PNG/MP4/ZIP/CSV shipped → 🆕 1.19 SVG/GIF/PPTX/DOCX + print-PDF (1.20 profile) |
| C15 | Export quality settings (10–100); transparent background PNG; single-image merge | 🆕 1.19 options schema (transparent PNG rides the cutout layer; merge = flatten pages to one image) |
| A16 | Quick Actions — Image: Remove background, Resize, Crop, Convert to JPG/PNG/SVG, WebP conversions, Generate QR | 🆕 1.19 utilities (cutout ✅ shipped; QR ↗ 1.16; SVG conversion via trace for raster sources, honest about fidelity) |
| A16 | Quick Actions — Video: Convert to MP4, Video→GIF, Trim, Crop, Resize, Merge, Caption, Change speed, Reverse, Mute, Animate from audio, Clip Maker | 🆕 1.19 utilities over 1.6 ops (animate-from-audio ↗ 1.5; Clip Maker ↗ 1.6) |
| A16 | Quick Actions — Document/PDF: Create/Convert to PDF, Convert/Export from PDF, Combine PDF, Organize pages, Edit PDF | 🆕 1.19 utilities over 1.15 PDF tools |
| A16 | Quick Actions — GIF: GIF to MP4, GIF to Video | 🆕 1.19 transcodes |
| A16 | Free/premium gating of quick actions | ↗ 1.23 quotas (PC.4 decides tiers) |
| A3 | Convert image formats (JPG/PNG/SVG/WebP) | 🆕 1.19 image converters |
| A4 | Convert video to GIF / MP4; GIF→MP4; GIF→Video; download as GIF | 🆕 1.19 video/GIF transcodes |
| A12 | Animated images export as GIF | 🆕 1.19 GIF export of 1.5 animations |
| A18 | Export to PDF/PNG/JPG/PPTX/GIF/MP4/WAV | 🆕 1.19 (WAV via 1.8) |
| A18 | Bulk download | 🆕 1.19 bulk export jobs |
| C12 | Export as PowerPoint / PDF / video slideshow (presentation exports) | ↗ 1.15 via this engine |

---

## 1.20 — Print & merch pipeline

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
resolution vs physical size — pairs with 1.2 upscale, bleed-zone
violations, contrast on paper) so a volunteer can hand any high-street or
online printer a file that won't bounce. *Fulfilment* (the factory) is the
one thing that cannot be first-party: it ships later as an optional,
flag-gated fulfilment slot behind our own order interface — the default
product is always the print-ready file download.

**Build sketch.** (1) print profile on `FormatSpec` (mm/in dimensions,
bleed, safe margins, DPI target); (2) `print_ready/` package: PDF/X export
(CMYK via ICC transform, marks, flattening) on the 1.15/1.19 renderer
path; (3) `print_ready/proof.py` — deterministic preflight with
per-violation explanations (the explainability rule applied to print); (4)
merch graphics: apparel/product `FormatSpec`s (front/back placements,
single/double-sided) + 1.2 mockup previews; (5) fulfilment slot
(optional, later): order schema + provider adapter behind our interface,
flag-gated per P0.3 — no provider hardwired, guarantees/eco options are
provider attributes surfaced honestly.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C14 | 40+ printed product types (business cards, flyers, posters, brochures, postcards, invitations, greeting cards, t-shirts, hoodies, sweatshirts, tote bags, mugs, water bottles, stickers, labels, notebooks, planners, mouse pads, photo books, banners, yard signs, calendars, envelopes) | 🆕 1.20 print/merch `FormatSpec`s for the club-relevant set (designs are P6.1 formats; this adds the physical profiles) |
| C14 | Print Shop (browse products, mockups, paper types, sizes by region) | 🚫 adapted — no shop until a fulfilment slot exists; product profiles + mockups (1.2) browseable |
| C14 | Magic resize for print (one design → any printable product) | 🆕 1.20 print re-render via the P6.1 transformer (real re-layout at print size) |
| C14 | Auto-Proofing (text size, bleed zone, resolution) | 🆕 1.20 deterministic preflight with explanations |
| C14 | CMYK colour support | 🆕 1.20 ICC/CMYK PDF/X export |
| C14 | Delivery options (standard/express/pickup) · Happiness Guarantee · One Print, One Tree · eco paper (240–650gsm) | 🚫 adapted — fulfilment-provider attributes (incl. guarantees/sustainability programmes), surfaced only when the optional fulfilment slot is enabled |
| C1 | T-shirts and apparel (hoodies, sweatshirts, tote bags) · Mugs, water bottles, promotional products · Labels · Stickers (print) · Banners and yard signs | 🆕 1.20 merch/print formats (fundraising kit) |
| A1 | Product labels (template category, print sense) | 🆕 1.20 label formats |
| A18 | Margins/bleed/crop marks | 🆕 1.20 print profile on specs |
| A18 | Print & order (business cards, flyers, mugs, pillows, tote bags, stickers, invitations; US/UK/CA/AU) | 🚫 adapted — print-ready download first; optional fulfilment slot later |
| A7 | Export PDFs with gradients; CMYK colour profile export; print PDFs | 🆕 1.20 print-PDF path (gradients preserved through the renderer) |
| C19 | Affinity Publisher print craft (PDF/X export, preflight, crop/registration marks) | 🆕 1.20 our own equivalents (PDF/X, preflight, marks) |

---

## 1.21 — MediaHub platform: public API, webhooks, automation & agent access

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
OpenAPI spec, rate limits (↗ 1.23); (2) `webhooks/` registry + signed
deliveries on `notify/`'s transport; (3) MCP server exposing the API as
typed tools (read + draft scopes; publishing tools always end at the
approval queue); (4) importers/exporters: SVG import, layered export
(SVG/PSD) for round-trip ↗ 1.25, palette/font/asset bundles; (5)
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
| C17 | Named creative apps (Mockups/Smartmockups, Pixabay, Pexels, Bynder, D-ID, HeyGen, Neiro, DeepReel, Krikey AI Animate, Dynamic QR Codes, Google Drive, Issuu, Soundraw, MelodyMuse, Typecraft, Murf AI, AiVOOV, Colorify, LottieFiles, Flourish, soona, Shopify, Brandfetch, Imagen, DALL·E, Mojo AI, Enhancer, HubSpot, Analytics) | 🚫 adapted — each maps to our own equivalent: mockups/upscale/generation ↗ 1.2 · stock library ↗ 1.10 · avatars (opt-in) ↗ 1.6 · animation ↗ 1.5 · QR ↗ 1.16 · doc publishing ↗ 1.15/1.16 · music/TTS ↗ 1.8 · type effects ↗ 1.9 · charts ↗ 1.11 · brand-DNA ✅ shipped (P1.5, our own Brandfetch) · palette tools ↗ 1.12 · product photos ↗ 1.2+1.3 · commerce/CRM/analytics ↗ 1.14/webhooks (no embedded third-party apps; Google Drive excluded) |
| C17 | Canva Apps SDK (in-editor apps; Image/Video/Text/Content/Design-Editing/Tables/Fonts/Auth APIs) | 🚫 adapted — internal module APIs now; public app SDK only with the long-term marketplace |
| C17 | Canva Connect APIs (Design, Export, Asset, Folder, Autofill, Brand Templates, Comment APIs + webhooks) | 🆕 1.21 our public API + webhooks (same capability set over our engine) |
| C17 | iPaaS integrations (Zapier, Make, Workato) | 🆕 1.21 reached via our API + webhooks + published recipes (their runtimes stay theirs) |
| C17 | Platform integrations (Slack, Salesforce, Gmail, Google Drive, Google Calendar, Notion, Zoom, HubSpot, Microsoft, Atlassian, Linear, Dropbox, OneDrive, Amazon Ads, Meta, Google Ads) | 🚫 adapted — chat notifications via generic webhooks (Slack/Teams/Discord); file import via upload + Dropbox/OneDrive-compatible remote fetch; calendar via our ICS feeds; **GWS connectors stay excluded**; ads ↗ 1.14 (prepare, never spend); CRM/PM-tool embeds not built — webhooks instead |
| C17 | Canva in Claude (bring coded creations into the editor) · Design Model inside ChatGPT/Claude/Gemini | 🆕 1.21 MediaHub MCP server — our engine driveable from Claude/ChatGPT/Gemini |
| C17 | Premium Apps Program, Developer Innovation Fund, app translation | 🚫 adapted — marketplace economics deferred with the marketplace itself |
| C2 | Canva AI 2.0 connectors workflow | 🆕 1.21 assistant reads/writes through the same API scopes (GWS still excluded) |
| A17 | Photoshop (.psd) & Illustrator (.ai) files — open, linked images, convert assets | 🆕 1.21 first-party PSD import (raster layers; `psd-tools`-class) + SVG/AI-as-PDF import; fidelity stated honestly; round-trip ↗ 1.25 |
| A17 | Lightroom integration; Adobe Color themes; AEM Assets; SVG import | SVG import 🆕 1.21; palette files ↗ 1.12; Lightroom/AEM 🚫 adapted — generic import paths, no vendor coupling |
| A17 | Creative Cloud integration; send from Firefly/boards; open in Photoshop/Illustrator | 🚫 adapted — layered export/import round-trip (1.25) instead of CC coupling |
| A17 | Google Drive, OneDrive, Dropbox; Google Photos | Dropbox/OneDrive-compatible remote fetch + upload 🆕 1.21; **Google Drive/Photos excluded** (standing rule) |
| A17 | 400–500+ add-ons (marketplace) | 🚫 adapted — same as C17 marketplace position |
| A17 | Slack, ChatGPT, Microsoft 365 Copilot, Miro integrations | webhooks (Slack) + MCP (ChatGPT/Copilot-class agents) 🆕 1.21; whiteboard-tool embeds not built (board ↗ 1.14) |
| A17 | Amazon/LinkedIn/Google ad creation | ↗ 1.14 ad-spec creative sets (export to specs; no ad-account automation) |
| A17 | Bynder, Frontify connectors | 🚫 adapted — our own brand platform (1.12) is the DAM; asset import/export bundles instead |
| A17 | EA Sports Team Builder; Fantasy Premier League | 🆕 1.21 fun-data spokes done our way: fantasy-league/club-game content via the data hub when a club supplies the data (no vendored game integrations) |
| A17 | Chrome extension | 🚫 adapted — PWA share-target + bookmarklet-class "send to MediaHub" (↗ 1.22), no browser-store extension to start |
| A17 | Express Embed SDK / Express API | 🆕 1.21 read-only embed (signed iframe/oEmbed) + our public API; editable-embed SDK deferred |

---

## 1.22 — Mobile, PWA & access surfaces

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
from phone ↗ 1.15 remote; (5) guest access = 1.18 share tokens; (6)
cross-device sync is inherent (server-side state).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C18 | iOS and Android apps (full editor, photo editor, video editor, voice recorder) | 🚫 adapted — PWA with capture/recorder (1.6/1.8 recorders run in mobile browser); native-store apps only if PWA proves insufficient |
| C18 | Desktop apps (Mac, Windows) | 🚫 adapted — hosted web app only (ADR-0011) |
| C18 | Web browser (cross-platform) | ✅ shipped — the product is the web app |
| C18 | Mobile presenting (present from pocket) | ↗ 1.15 phone-remote + mobile deck view |
| C18 | Mobile photo/video editing | 🆕 1.22 mobile-scoped editing (approve/caption/crop/pick); full editors stay desktop-primary |
| C18 | Designs open in new browser tab by default (toggleable) | 🆕 1.22 small UX preference, noted for completeness |
| A19 | Web (desktop browser), mobile apps (iOS/Android), iPad app, PWA, Chrome extension | 🆕 1.22 PWA (+ share-target replacing the extension); iPad = the responsive web app |
| A19 | Guest/logged-out access | 🆕 1.22 token-scoped guest views (1.18) |
| A19 | Cross-device sync | ✅ inherent (hosted state) |
| A19 | Adobe Express for Education (classrooms, assignments, galleries) | 🚫 adapted — society/education packaging is a PC.4 commercial decision; no classroom LMS build |
| A19 | Free plan and Premium plan; Teams and Enterprise plans; complimentary Premium programs | ↗ PC.4 pricing & packaging (quota mechanics ↗ 1.23) |
| C19 | Affinity: Mac + Windows, works offline after activation | 🚫 adapted — hosted-only; offline tolerance limited to the PWA approval queue |

---

## 1.23 — AI governance, quotas, provenance & content safety

**What Canva/Adobe have.** Canva Shield (input/output moderation, safety
filters, bias mitigation, privacy controls, enterprise indemnification),
real-time AI credit/usage trackers, generative-credit systems with monthly
allocations, Content Credentials on AI output, commercially-safe model
claims, role-based AI permissions, free-tier action limits.

**The MediaHub shape.** MediaHub already has the spine Canva sells as
Shield: the deterministic brand-safety gate, safeguarding rules (minors
never auto-publish), per-org audit ledger, LLM-usage observability, and
honest-error AI. 1.23 completes it as **our own governance layer**:
per-org/per-feature AI quotas (the "credits" analogue — metered on the
existing `observability/` usage store, surfaced live in the workspace,
enforced with honest "quota reached" errors; tier numbers belong to PC.4),
input/output moderation on the new generative surfaces (1.2/1.6/1.8 —
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
membership ledger consumed by UI + API scopes (1.21); (5) free-tier
action limits = the same quota mechanism with PC.4-decided numbers.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | Canva Shield (moderation, safety filters, bias mitigation, privacy controls, indemnification) | 🔵 gate/audit/safeguarding shipped → 🆕 1.23 moderation on generative surfaces + privacy controls; indemnification = a commercial/legal posture (PC.4), not code |
| C2 | Real-time AI credit/usage tracker | 🔵 LLM usage tracked (`observability/`) → 🆕 1.23 live workspace quota panel |
| A2 | Content Credentials attached to AI content; commercially safe models | 🆕 1.23 provenance manifests + model-policy register (which providers are commercially safe, per DEPENDENCY_LICENSING) |
| A2 | Generative credits system (monthly allocations, expiry) | 🆕 1.23 quota ledger (numbers ↗ PC.4) |
| A7 | Free-plan PDF quick-action limits (1/week) | 🆕 1.23 quota mechanism on quick actions (numbers ↗ PC.4) |
| A16 | Free/premium gating of quick actions (Remove background, Erase premium) | 🆕 1.23 same mechanism |
| C9 | Role-based permissions for AI/brand features | 🆕 1.23 role flags (with 1.12/1.18) |
| C8 | Reduce motion accessibility setting | ↗ 1.5 (accessibility guardrail family noted here for governance completeness) |

---

## 1.24 — Localisation & translation

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
language *pair* shown together), bulk localisation via 1.13 rows, dubbing
= 1.24 translation + 1.8 TTS voices per language, and UI localisation
(our own string catalogue; Welsh first as the honest flagship).

**Build sketch.** (1) `localize/` package: translation service (provider-
backed, glossary-constrained, length-budgeted per text slot), language
metadata on captions/specs; (2) bilingual variant flow in the caption
editor + review (side-by-side approval); (3) renderer: script/RTL support
+ font script coverage (1.9 catalogue carries the scripts); (4) UI i18n:
string extraction + `cy` (Welsh) catalogue first; (5) bulk: per-language
rows in `bulk_generate`; (6) dubbing pipeline: transcript (1.4) →
translate → TTS track swap, clearly labelled as AI-dubbed (1.23
provenance).

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C2 | AI Translate / Translate designs (100+ languages, bulk localisation) | 🆕 1.24 translation + layout-aware re-render + bulk via 1.13 |
| C6 | Multilingual support (100+ content languages; interface in 100+ languages) | 🆕 1.24 content languages via providers; UI i18n catalogue (Welsh first, grown by demand) |
| C2 | Magic Write 100+ language support | 🆕 1.24 caption generation in the org's languages (glossary-protected) |
| A2 | Translate (designs, incl. regional variants) | 🆕 1.24 regional variants (en-GB vs en-US spelling already handled in captions — extended) |
| A2 | Translate Video / Translate Audio (AI dubbing, ~5 languages, voice-preserving; enterprise lip-sync) | 🆕 1.24 dub pipeline (translate + per-language TTS; voice-preservation/lip-sync explicitly out until consent-safe; labelled AI-dubbed) |
| A2 | Generate Image 100+ prompt languages | 🆕 1.24 prompt pass-through (providers accept multilingual prompts) |
| A4 | Caption video auto-captions in 100+ languages | 🆕 1.24 caption translation on the 1.6 caption layer |
| A6 | Spellcheck with primary language | ↗ 1.9 (locale-aware dictionaries from the org's language set) |

---

## 1.25 — Pro editor & round-trip (the Affinity-class answer)

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
retouch (1.2), basic vector editing of our SVG elements (node/path ops,
boolean ops, trace via 1.2). **(b) Round-trip, not suite-cloning**: the
deep darkroom/publisher craft (RAW develop, HDR, panorama, focus stack,
liquify, master-page DTP) is explicitly *not rebuilt* — instead MediaHub
exports **layered, editable files** (layered SVG/PSD, print-PDF) so a
club's power user can finish in any pro tool they own, and re-imports the
result as an asset with provenance kept. The publisher-craft needs clubs
actually have (long documents, data merge, preflight) are already covered
by our own 1.15 documents + 1.13 bulk + 1.20 preflight.

**Build sketch.** (1) editor surface: spec-bound canvas with the
fundamentals above (patch-based undo/redo from revision log 1.18); (2)
`graphic_renderer/vector_edit.py` — node/path/boolean ops on element SVGs
(deterministic geometry); (3) curves/levels in 1.3's recipe schema
(16-bit-aware internally where Pillow allows); (4) layered export: SVG
(native) + PSD writer (raster layers) + re-import matching; (5) explicit
non-goals documented (RAW/HDR/panorama/liquify/master-pages) with the
round-trip path as the supported answer.

**Coverage.**

| Source | Feature | MediaHub home / status |
|---|---|---|
| C19 | Affinity by Canva (unified free pro app: Photo/Designer/Publisher) | 🚫 adapted — our own fine-control editor + layered round-trip; no desktop suite (hosted-only) |
| C19 | Pixel/Photo Studio (RAW develop, frequency separation, liquify, HDR merge, panorama stitching, focus stacking, 16/32-bit HDR, adjustment layers, live filter layers, lens correction, PSD compatibility) | 🚫 adapted — curves/levels/adjustment recipes (1.3) + AI retouch (1.2) in-app; RAW/HDR/panorama/focus-stack/liquify = round-trip non-goals; PSD import/export 🆕 1.25 |
| C19 | Batch processing | ↗ 1.13 batch recipes |
| C19 | Vector/Designer Studio (vector tools, path operations, image trace, gradient fill, artboards) | 🆕 1.25 vector node/path/boolean editing on our SVG elements; trace via 1.2; artboards = pages |
| C19 | Layout/Publisher Studio (master pages, AutoFlow, text styles, kerning/leading/ligatures/OpenType/variable fonts, column guides, baseline grids, PDF/X export, preflight, crop/registration marks, data merge) | 🚫 adapted — long-doc needs are ours already: documents ↗ 1.15 (styles/columns/baseline), print craft ↗ 1.20 (PDF/X, preflight, marks), data merge ↗ 1.13; OpenType feature control 🆕 1.25 in the type system; master-page DTP = round-trip non-goal |
| C19 | Additional studios (Slice, Canva AI, Retouching, Color Grading, Typography, Compositing) | 🆕 1.25 slice = per-element export regions; retouch/grade = 1.2/1.3; typography = 1.9; compositing = layers/blend in the editor |
| C19 | Canva AI tools in Affinity (Object Selection, Generative Expand/Fill/Edit, Portrait Blur, Portrait Lighting, Colorize, Super Resolution, Select Sampled Depth, Depth Estimation) | ↗ 1.2 services (object select = cutout+saliency; portrait blur/lighting = subject-mask relight; colorize/super-res = providers; depth tools = provider depth maps feeding focus effects) |
| C19 | Export Affinity projects to Canva | 🆕 1.25 layered import (PSD/SVG) — the equivalent inbound path |
| C19 | v3.1 additions (Tone Brush, Live Tone Blend, pixel-selection-to-curves, Develop tone curves, light UI theme) | 🚫 adapted — tone curves land in 1.3 recipes; the rest are round-trip non-goals; (light UI theme is a web-app theming question, noted) |
| A18 | Layers (work with, multi-select, filter); group/ungroup; align elements; rulers & guides | 🆕 1.25 editor fundamentals |
| A18 | Add/duplicate/reorder pages; resize page; crop page (Fit to Content, custom, presets); change page size | 🆕 1.25 page management (multi-page specs via 1.15) |

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
| C1 Design/content types | 40 | P6.1 (bulk of types) · 1.3 (collages) · 1.6 (videos) · 1.11 (infographics, diagram types) · 1.15 (presentations, docs, reports, proposals) · 1.16 (websites, Code) · 1.17 (email, newsletters) · 1.13 (Sheets) · 1.14 (whiteboards, Kanban) · 1.20 (apparel/promo/labels/stickers/banners) |
| C2 AI / Magic Studio | 40 | P6.2 (assistant, Design Model, Magic Design/Write) · 1.2 (image/video gen + edits) · 1.8 (voice/music/SFX) · 1.9 (Magic Morph) · 1.11 (Charts/Insights) · 1.5 (Magic Animate) · 1.12 (brand intelligence) · 1.15 (Guided Presentations) · 1.16 (Code workflows) · 1.13 (Sheets AI, Formulas, Bulk, at-Scale) · 1.14 (scheduling workflow) · 1.18 (Ask @Canva) · 1.21 (connectors, in-Claude) · 1.23 (Shield, credits) · 1.24 (Translate) · P6.1 (Magic Switch) · shipped (Brand Voice, web research) |
| C3 Photo editing | 22 | 1.3 (editor ops) · 1.2 (AI services incl. BG remover ✅/eraser/changer/upscale/style match/mockups) · P6.2 (point-and-click) |
| C4 Video editing | 27 | 1.6 (suite) · 1.8 (voice cleanup/balance) · 1.10 (stock footage) · 1.5 (animation library) · 1.15 (presenting) · 1.19 (conversions) |
| C5 Audio | 13 | 1.8 (all) |
| C6 Text & typography | 14 | 1.9 (all) · 1.5 (text animations) · 1.24 (multilingual) |
| C7 Elements | 18 | 1.10 (library) · 1.11 (tables/charts) · 1.8 (audio elements) · 1.2 (generation) |
| C8 Animation | 14 | 1.5 (all) · 1.15 (click order surface) · 1.23 (reduce-motion noted) |
| C9 Branding | 15 | 1.12 (platform) · 1.18 (approvals, folders) · 1.23 (role permissions) · shipped (kit builder, palettes) |
| C10 Templates | 5 | P6.1 (catalogue, Quick Create) · 1.12 (brand templates) · 1.13 (bulk autofill) · shipped (AI generation) |
| C11 Data & documents | 13 | 1.13 (Sheets/autofill/connectors/at-scale) · 1.11 (charts/insights/storytelling) · 1.15 (Docs/Scrollables) · 1.16 (Forms) · 1.21 (APIs) |
| C12 Presentations | 16 | 1.15 (all) · 1.16 (Live page, website export) · 1.14 (whiteboard expansion) |
| C13 Websites | 14 | 1.16 (all) · 1.14 (insights surfacing) |
| C14 Print | 20 | 1.20 (all; design side P6.1) |
| C15 Publishing & planning | 12 | 1.14 (planner/analytics/preview/permissions/Grow) · P4 (direct publishing) · 1.19 (export formats/quality) · 1.18 (share links) · shipped (caption editing, drafts) |
| C16 Collaboration | 11 | 1.18 (all) · 1.15 (live edits while presenting) |
| C17 Apps & developer | 10 groups | 1.21 (API/webhooks/MCP/marketplace position/named-app equivalents) · 1.16 (Code 1.0/2.0) · 1.6 (avatar apps) |
| C18 Mobile & desktop | 6 | 1.22 (all) · 1.15 (mobile presenting) |
| C19 Affinity | 10 groups | 1.25 (editor + round-trip) · 1.3/1.2 (retouch/AI tools) · 1.15/1.13/1.20 (publisher craft) · 1.22 (platforms/offline) |
| TL;DR / Key Findings / Recommendations / Caveats | — | context, not features; availability/plan-gating caveats inform 1.23 quotas and the per-item "verify at build time" rule below |

**Adobe Express inventory (A1–A19)**

| Section | Bullets | Mapped in |
|---|---|---|
| A1 Templates & design types | 13 groups | P6.1 (types, save-as-template, quick replace, orientations) · 1.11 (infographics) · 1.15 (presentations/docs) · 1.16 (webpages) · 1.6/1.5 (video/animated) · 1.14 (ads) · 1.3 (collages) · 1.20 (print/t-shirts/labels) · 1.12 (locked templates) |
| A2 AI / Generative (Firefly) | 25 | 1.2 (image gen/fill/expand/remove/similar/video) · P6.2 (assistant, rewrite, text-to-template) · P6.1 (coloring pages) · 1.6 (avatars, Clip Maker ref) · 1.8 (speech/enhance/recommendations) · 1.9 (text effects, font recs) · 1.15 (presentations) · 1.16 (QR) · 1.23 (credentials, credits) · 1.24 (translate/dubbing) · shipped (caption writer) |
| A3 Image / photo editing | 17 | 1.3 (editor) · 1.2 (erase/replace-bg/AI assists; BG remove ✅) · 1.5 (animated images) · 1.19 (conversions, resize presets) |
| A4 Video editing | 17 | 1.6 (suite) · 1.8 (audio) · 1.19 (conversions) · 1.15 (presentation controls) · 1.24 (caption languages) · P4 (Vimeo) |
| A5 Audio | 9 | 1.8 (all) · 1.5 (animate-from-audio) · P6.2 (assistant controls) |
| A6 Text & typography | 8 groups | 1.9 (all) · 1.5 (animations) · 1.24 (translate/spellcheck locales) · 1.8 (voiceover tone) |
| A7 PDF & documents | 9 | 1.15 (PDF suite) · 1.20 (CMYK/print) · 1.23 (free limits) |
| A8 Presentations & documents | 9 | 1.15 (all) · 1.5 (sequencing) · P6.1 (switch presentation↔design) |
| A9 Webpages | 5 | 1.16 (all) |
| A10 Drawing & illustration | 5 | 1.10 (drawing) · P6.1 (worksheets, coloring) |
| A11 Elements & assets | 9 | 1.10 (stock/elements/search) · 1.11 (charts/tables) · 1.12 (color themes/Adobe Color) · 1.16 (QR) |
| A12 Animation | 10 | 1.5 (all) · 1.19 (GIF export) |
| A13 Branding | 6 | 1.12 (all) |
| A14 Scheduling & publishing | 12 | 1.14 (planner/analytics/safe zones/grid/mentions/activation) · P4 (publish/connect) · shipped (caption writer) |
| A15 Collaboration | 8 | 1.18 (all) |
| A16 Quick Actions | 5 groups | 1.19 (toolbox) · 1.6/1.15/1.16 (underlying ops) · 1.23 (gating) |
| A17 Imports & integrations | 12 | 1.21 (API/import/interop/MCP; GWS exclusions) · 1.25 (round-trip) · 1.14 (ads) · 1.12 (palettes) · 1.13 (bulk automate) · 1.22 (extension→PWA) |
| A18 Layout, pages & export | 8 | 1.25 (layers/align/guides/pages) · 1.19 (exports/bulk) · 1.20 (bleed/print-order) · P6.1 (resize-for-channel) · 1.13 (bulk create) |
| A19 Platforms & access | 6 | 1.22 (surfaces/guest/sync/education) · PC.4 (plans) |
| TL;DR / Key Findings / Recommendations / Caveats | — | context, not features; free-vs-premium volatility informs 1.23/PC.4 |

**Build-time verification rule.** The source inventories carry caveats
(regional rollouts, beta flags, plan gating, counts that drift). When a P6
item starts, re-verify the competitor behaviour only if it materially
shapes our own design — we are building our versions, not tracking theirs.

## Relationship to standing decisions

- Phase 6 never overrides: hosted-only (ADR-0011) · approval-first
  (human approval before any external use) · deterministic
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
