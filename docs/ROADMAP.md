# MediaHub Roadmap

The plan — **one document, in depth**. It opens with the two live lists (what’s
**to do** and what’s **completed**; one line per item, each with a stable ID),
and the rest of the document is the full long-form plan those lists index: the
plain-words overview, the commercial reality check, the phase essays with
per-item detail, the cross-cutting investments, and **Appendices A/B/C** (the
PAR-*/SEQ-*/Step-N build & verification prompts). The decided strategy lives in
the ADRs and companion docs linked under [Standing context](#standing-context).

## Changelog (manual — strategy/roadmap engine)

Newest first; hand-maintained by the daily roadmap engine. (The auto-refreshed **Status** block below is machine-managed — do not hand-edit it.)

- **2026-06-12** — **Compliance-readiness audit: Phase C was pushing "go sell" with zero legal/compliance surface in place** (maintainer instruction "assess how the roadmap told me to sell with no compliance"). Root cause: Phase C was composed entirely from the 2026 *scaling* diligence, whose question was "what blocks revenue?" — so every PC item is a revenue mechanic, and "lawful to operate" was never an exit criterion. Compliance only ever entered the plan through side doors: as a data-*acquisition* risk (PC.6(a)'s "prefer the official API over scraping") and as a sellable *feature* (W.2 consent manager, filed in the optional pick-list). Engineering-shaped safety shipped (ADR-0003 isolation, publish-gate safeguarding rule, initials-first wall) because code review owns it; the document/contract/registration half (terms, privacy notice, DPA, ICO registration, deletion/export rights, breach process) had no owning channel and fell through. Fix: a third **compliance-readiness ("lawful-to-sell") exit gate** on Phase C — no paid contract before it holds — implemented as four new sell-gate items **PC.11–PC.14** (legal & privacy pack; minors' consent gate, promoting W.2 to load-bearing; data lifecycle & rights; operational trust pack: transactional email/password reset, backups + restore drill, support + incident runbook, billing hygiene). Decision recorded in [`adr/0015-compliance-readiness-sell-gate.md`](adr/0015-compliance-readiness-sell-gate.md). [compliance audit]
- **2026-06-11** — **Phase C build-out: PC.7 + PC.8 + PC.10 shipped; PC.4's `/pricing` gate enforced** (maintainer instruction "complete PC.4/6/7/8/10"): the public try-before-signup demo (`/try`, watermarked ≤3-card preview, capped, sandboxed, self-cleaning, claimable on conversion), the sponsor manager + per-sponsor exposure reports (`/sponsors`, deterministic rotation, exposure ledger, monthly report), and the public achievements wall + embed + RSS/JSON (`/wall/<token>`, opt-in, approved-only, initials-first, structurally revocable). PC.4's remaining engineering gap closed — `/pricing` now reads `pc4_pricing_gate` and commits a list price only from ≥5 revealed annual payments (the highest tested price that cleared). PC.6 was audited build-complete (lead ledger, cold-share + referral-debt readouts, NGB application drafted + tracked); what remains on PC.4/PC.6 is the founder's selling motion, which code cannot close. [completion pass]
- **2026-06-11** — **Phase 6 — Creative-suite breadth added** (maintainer instruction): every content-creation feature in the two checked-in competitor inventories ([Canva](research/CANVA_FEATURE_INVENTORY_2026.md), [Adobe Express](research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md)) now has a MediaHub-shaped build plan — **our own first-party versions, not integrations of theirs** — organised into 24 gated work packages (P6.1–P6.24) with a feature-by-feature coverage index proving nothing was missed. Long-form mapping: [`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md). Phase 6 sits behind the Phase C gates like P3/P4/P5; standing rules (hosted-only, approval-first, deterministic engine, Gemini-first honest-error AI, GWS exclusion) all hold. [roadmap engine]
- **2026-06-11** — Daily scan: no material change. Competitor watch (Gipper, SwimTopia, TeamUnify, Swimcloud) shows no results-ingestion / auto-graphics move; platform policies (Instagram Graph API, TikTok Content-Posting audit gate, Bluesky/Mastodon) unchanged vs last run; Swim England’s club-management data API (Swim Club Manager / Swim Manager / SportsEngine; “more in 2026”) is already captured under PC.6 + ADR-0012 and only reinforces — does not change — the queued Route C go/no-go. No roadmap statuses changed (engineering shipped since 2026-06-08, e.g. publish kill-switch #288 and per-type autonomy #297, is tracked by the auto-Status block, not the strategy layer). Source: swimming.org (Sept 2025). [roadmap engine]

## Status (auto-updated)

Refreshes on every push to `main` via
[`.github/workflows/roadmap-autoupdate.yml`](../.github/workflows/roadmap-autoupdate.yml)
(landed through an auto-merge PR — `main` requires PRs). Put a directive line
in any commit message to move an item:

> `roadmap: <ID> <status>` — `<ID>` is an item ID from the lists below
> (`PC.3`, `P1.2`, …); `<status>` is `done` · `wip` · `blocked` · `todo`.
> `done` **moves the item to Completed** (date-stamped); any other status
> moves it back to To do with the matching badge.

<!-- ROADMAP:LAST_UPDATED -->
**Last updated:** 2026-06-12 · `7b8d8b8bb` · Merge pull request #348: docs(roadmap): compliance-readiness sell gate — PC.11–PC.14 + ADR-0015
<!-- /ROADMAP:LAST_UPDATED -->

**Recent activity**

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-06-12 | `1e77c9b06` | docs(roadmap): compliance-readiness sell gate — PC.11–PC.14 + ADR-0015 |
| 2026-06-12 | `950a19f7e` | Full-suite verification fixes: env inventory, wall-token route swept by isolation invariants |
| 2026-06-11 | `943dff64a` | Phase C build-out: PC.7 try-demo, PC.8 sponsor manager, PC.10 public wall; close PC.4's /pricing gat |
| 2026-06-11 | `23b91e2ed` | chore: format the whole back-catalogue and make repo hygiene blocking |
| 2026-06-11 | `db4953273` | style: ruff-format (pinned 0.8.4) on touched files |
| 2026-06-11 | `64ca81ee6` | Motion ↔ still parity: archetype scenes, motion intents, role parity, formats, reel narrative |
| 2026-06-11 | `fe6e607c3` | docs(roadmap): add Phase 6 — our own creative suite (P6.1–P6.24) |
| 2026-06-11 | `eaf6da84b` | docs(roadmap): absorb the June 2026 ideas backlog into the plan |
| 2026-06-11 | `f99ba5fd6` | Skip Render deploys for docs-only roadmap bot merges |
<!-- /ROADMAP:ACTIVITY -->

## To do

Ordered by priority: **Phase C (commercialise) outranks everything**; **Phase W**
(deepen the swimming wedge) is an ungated, selectable backlog picked from only in
support of the sell; P3/P4/P5 are gated behind Phase C's exit criteria (see
Standing context).

<!-- ROADMAP:TODO -->
- **PC.4** · Phase C 🥇 — Pricing & packaging by revealed willingness-to-pay: quote real annual prices to the first hand-sold clubs; keep `/pricing` at "TBC" until ≥5 clubs have paid annual at a tested price · 🔵 **IN PROGRESS**
- **PC.6** · Phase C 🥇 — Go-to-market: warm-first hand-sell of the first ~10 clubs (local Swansea/South-Wales base + referrals; cold capped) and apply for Swim England's approved-systems data API · 🔵 **IN PROGRESS**
- **PC.11** · Phase C 🥇 (sell gate) — Legal & privacy pack: public Terms + Privacy Notice with versioned signup acceptance, club DPA (Art. 28 processor terms), published subprocessor register + transfer disclosures, ICO registration (founder action) · ❌ **NOT STARTED**
- **PC.12** · Phase C 🥇 (sell gate) — Minors' consent & safeguarding gate: W.2's consent ledger enforced at generation + public wall + publish gate, plus a Children's-Code pass on the public surfaces · ❌ **NOT STARTED**
- **PC.13** · Phase C 🥇 (sell gate) — Data lifecycle & rights: self-serve account/org deletion, org-level data export (SAR/portability), documented retention schedule · ❌ **NOT STARTED**
- **PC.14** · Phase C 🥇 (sell gate) — Operational trust pack: transactional-email seam (password reset, verification, breach notice, member invites), DATA_DIR backup + restore drill, support contact + incident runbook, VAT/invoice hygiene · ❌ **NOT STARTED**
- **PC.9** · Phase C 🥇 — In-product referral engine: codes, tracked intros, Stripe-coupon reward on a paid referral · ❌ **NOT STARTED**
- **W.1** · Phase W (selectable) — Athlete registry + milestone detectors (identity across runs; 50th race, debuts, comebacks) · ❌ **NOT STARTED**
- **W.2** · Phase W → PC.12 sell gate (promoted 2026-06-12) — Consent & safeguarding manager: per-athlete photo/name/initials-only consent enforced at generation + publish gate · ❌ **NOT STARTED**
- **W.3** · Phase W (selectable) — Club records engine + deterministic "NEW CLUB RECORD" detector outranking PBs · ❌ **NOT STARTED**
- **W.4** · Phase W (selectable) — Season-current qualifying-time packs ("Qualified for Counties!") as curated versioned datasets · ❌ **NOT STARTED**
- **W.5** · Phase W (selectable) — LENEX (.lef/.lxf) ingestion: the open SportSystems/European interchange format · ❌ **NOT STARTED**
- **W.6** · Phase W (selectable) — Data-driven meet previews from entry/psych-sheet files (replaces the form-based stub) · ❌ **NOT STARTED**
- **W.7** · Phase W (selectable) — Live meet mode: watch a club-controlled live-results URL, queue cards mid-gala for approval · ❌ **NOT STARTED**
- **W.8** · Phase W (selectable) — Season wraps / monthly recap packs from accumulated run history · ❌ **NOT STARTED**
- **W.9** · Phase W (selectable) — Magic-link mobile approvals (signed expiring review links; no login) · ❌ **NOT STARTED**
- **W.10** · Phase W (selectable) — OCR fallback for scanned/photographed result PDFs with per-row uncertainty flags · ❌ **NOT STARTED**
- **W.11** · Phase W (selectable) — Result-grounded alt-text on every exported/published card · ❌ **NOT STARTED**
- **W.12** · Phase W (selectable) — Print exports: per-swimmer PB certificates + A4 noticeboard posters · ❌ **NOT STARTED**
- **W.13** · Phase W (selectable) — Bilingual captions (Welsh first) per-workspace language setting · ❌ **NOT STARTED**
- **W.14** · Phase W (selectable) — Engagement feedback loop: approval telemetry now; platform metrics after P4.2 · ❌ **NOT STARTED**
- **P3.1** · Phase 3 (gated) — Second-sport engine adapter: `recognition_football`/`_basketball` + `register_sport(...)` · ❌ **NOT STARTED**
- **P3.2** · Phase 3 (gated) — Sports-data API spokes (`nba_api`, openfootball, fixture generators) normalised to `canonical.*` · ❌ **NOT STARTED**
- **P3.3** · Phase 3 (gated) — Running/athletics parsers (chip-timing CSV, client-side FIT) · ❌ **NOT STARTED**
- **P3.4** · Phase 3 (gated) — Normalise all spokes to the canonical schema; flag ambiguous rows for review · ❌ **NOT STARTED**
- **P4.1** · Phase 4 (gated) — Bluesky (AT Protocol) + Mastodon adapters — the free/open posting targets first · ❌ **NOT STARTED**
- **P4.2** · Phase 4 (gated) — Instagram Graph / Facebook / TikTok / YouTube adapters, least-privilege, human-connected · ❌ **NOT STARTED**
- **P4.3** · Phase 4 (gated) — X adapter as a paid, optional target (pay-per-use API) · ❌ **NOT STARTED**
- **P4.4** · Phase 4 (gated) — Demote Buffer to optional; remove it from the critical path · ❌ **NOT STARTED**
- **P4.5** · Phase 4 (gated) — Email digest delivery: the existing newsletter actually sends (member lists, unsubscribe, Resend-seamed) · ❌ **NOT STARTED**
- **P4.6** · Phase 4 (gated) — Telegram channel publishing (free Bot API; native PNG+MP4) + a WhatsApp share stopgap · ❌ **NOT STARTED**
- **P5.1** · Phase 5 (gated) — Ollama local LLM provider behind the existing `ai_core.llm` interface · ❌ **NOT STARTED**
- **P5.2** · Phase 5 (gated) — Piper local TTS replaces edge-tts · ❌ **NOT STARTED**
- **P5.3** · Phase 5 (gated) — whisper.cpp / faster-whisper local ASR for reel captions · ❌ **NOT STARTED**
- **P5.4** · Phase 5 (gated) — Satori graphics fast-path (~100× lighter than headless Chromium; rides the reel-engine seam P0.1 shipped) · ❌ **NOT STARTED**
- **P6.1** · Phase 6 (gated) — Smart format catalogue + format transformer: every Canva/Adobe-class design type as a data-driven club `FormatSpec` (certificates, posters, programmes, yearbooks, per-channel sizes); `turn_into` v2 re-targets any approved design · ❌ **NOT STARTED**
- **P6.2** · Phase 6 (gated) — Conversational creative assistant: agentic spec-patch editing on `ai_core.ask_with_tools`, Magic-Write-class text tools, org assistant memory, voice input via the ASR seam · ❌ **NOT STARTED**
- **P6.3** · Phase 6 (gated) — Generative imagery suite behind our own `media_ai` provider seam: generate / edit / fill / expand / remove / subject-lift / upscale / style-match / mockups, provenance-stamped · ❌ **NOT STARTED**
- **P6.4** · Phase 6 (gated) — Photo editor: deterministic non-destructive edit recipes (filters, adjustments, crop/perspective, collages, blur brush, HEIC) on `media_library` assets · ❌ **NOT STARTED**
- **P6.5** · Phase 6 (gated) — Video suite: footage path + EDL timeline over the shipped reel engines, ASR captions, Clip-Maker-for-sport, saliency reframe, browser recorders, opt-in disclosed avatars · ❌ **NOT STARTED**
- **P6.6** · Phase 6 (gated) — Audio engine: own licence-clean music/SFX pools + rights ledger, voice layer on the TTS seam (catalogue, params, name-pronunciation lexicon), denoise/levelling, consent-gated voice features · ❌ **NOT STARTED**
- **P6.7** · Phase 6 (gated) — Typography system: curated self-hosted font catalogue + per-org uploads, AI pairing, deterministic text-effect tokens (shadow/neon/curve/extrude/warp), formatting depth · ❌ **NOT STARTED**
- **P6.8** · Phase 6 (gated) — Element & stock libraries: brand-token-recolourable sport-editorial packs, own open-collection-seeded stock pools, embedding search, annotate/draw layer · ❌ **NOT STARTED**
- **P6.9** · Phase 6 (gated) — Charts & insights: deterministic brand-styled stat graphics from canonical results/history + grounded AI takeaways and chart recommendations; diagram formats · ❌ **NOT STARTED**
- **P6.10** · Phase 6 (gated) — Motion vocabulary: tokenised animation presets/transitions compiled to Remotion + FFmpeg + CSS, shared-element transitions, motion paths, reduce-motion variants · ❌ **NOT STARTED**
- **P6.11** · Phase 6 (gated) — Brand platform depth: multi-kit (sponsor/event/section co-branding), deterministic brand check + AI auto-fix, token locks, brand home, kit-edit re-render sweep · ❌ **NOT STARTED**
- **P6.12** · Phase 6 (gated) — Document engine: meet programmes / season reports / sponsor proposals / AGM decks, presenter surface (notes, remote, autoplay), PPTX/DOCX round-trip, PDF utilities · ❌ **NOT STARTED**
- **P6.13** · Phase 6 (gated) — Club microsites + link-in-bio + forms + QR + vetted interactive widgets (countdowns, medal tally, polls), data-generated and publish-gated · ❌ **NOT STARTED**
- **P6.14** · Phase 6 (gated) — Email & newsletter composer: email-safe branded HTML auto-assembled from the period's approved content; export-first, send-adapter later · ❌ **NOT STARTED**
- **P6.15** · Phase 6 (gated) — Data hub + bulk personalisation: user-facing canonical tables with provenance, CSV/XLSX round-trip, deterministic derived columns, review-queued bulk generation ("certificates for all 47 PB swimmers") · ❌ **NOT STARTED**
- **P6.16** · Phase 6 (gated) — Planner calendar/board: drag-reschedule through the publish gate, club-aware key dates, per-channel previews + safe zones, first-party performance-analytics loop feeding the planner · ❌ **NOT STARTED**
- **P6.17** · Phase 6 (gated) — Collaboration & review: anchored comments/mentions/tasks, version diff + restore, element locks, roles, group approvers, expiring share tokens · ❌ **NOT STARTED**
- **P6.18** · Phase 6 (gated) — Export & conversion engine: SVG/GIF/PPTX/DOCX/WAV/print-PDF additions, quality/transparency options, bulk export jobs, media-library quick-action utilities · ❌ **NOT STARTED**
- **P6.19** · Phase 6 (gated) — Print & merch pipeline: physical-dimension FormatSpecs, CMYK PDF/X export, deterministic preflight with explanations, mockups; optional flag-gated fulfilment slot later · ❌ **NOT STARTED**
- **P6.20** · Phase 6 (gated) — MediaHub platform surface: versioned public API + signed webhooks + MCP server (drive MediaHub from Claude/ChatGPT/Gemini-class agents), first-party file interop (SVG/PSD/palettes); GWS stays excluded · ❌ **NOT STARTED**
- **P6.21** · Phase 6 (gated) — Mobile PWA: installable share-target capture to media library, offline-tolerant approval queue, mobile-first review/caption/crop; hosted-only stands · ❌ **NOT STARTED**
- **P6.22** · Phase 6 (gated) — AI governance: per-org/per-feature quota ledger on `observability/`, generative moderation, provenance manifests on AI media, role-based feature permissions · ❌ **NOT STARTED**
- **P6.23** · Phase 6 (gated) — Localisation: glossary-protected translation with layout-aware re-render, bilingual approval pairs (Welsh-first), bulk per-language variants, AI-dub pipeline, UI i18n · ❌ **NOT STARTED**
- **P6.24** · Phase 6 (gated) — Pro editor & round-trip: layers/align/guides/page management as validated spec patches, vector node/boolean ops, curves/levels recipes, layered SVG/PSD export-import; deep darkroom/DTP stays a round-trip non-goal · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO -->

## Completed

<!-- ROADMAP:DONE -->
- ✅ **P0.2** · Phase 0 — Cutout free-by-default: in-process rembg is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`); Replicate/PhotoRoom opt-in *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P5.5** · Phase 5 — rembg cutout shipped as the default (MODNet noted as optional upgrade) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P1.1** · Phase 1 — Sport-profile schema + loader + `AutonomyLevel` + swimming/football YAML profiles (inert scaffolding) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P2.1** · Phase 2 — Orchestration backbone the in-process way: `scheduler/` exactly-once SQLite runner + `autonomy/` bounded narrow-tool runner (Temporal rejected by Council) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **PC.1** · Phase C — Self-serve signup + auth: `/signup` `/login` `/logout`, bcrypt, signed session cookie, `users.jsonl` ledger *(completed 2026-06-09, PR #267)*
- ✅ **PC.2** · Phase C — Stripe billing + subscription lifecycle: Checkout, Customer Portal, signed webhook; honest-503 until the operator sets `STRIPE_*` keys *(completed 2026-06-09, PR #267)*
- ✅ **PC.5** · Phase C — Free-self-host tension resolved: **hosted-only**, no customer self-host tier (maintainer decision; ADR-0011) *(completed 2026-06-09)*
- ✅ **P2.4** · Phase 2 — Per-type autonomy controls in the workspace: Settings → Autonomy tab, per-profile per-type policy defaulting to approval_required, publish gate + global kill switch *(completed 2026-06-09, PR #297)*
- ✅ **P1.4** · Phase 1 — Generative Content Engine v2, complete: Appendix A spine SEQ-0→4 (tokens, Tier B director/pool/APCA compliance ranking, gated SEQ-3 cutover with the A/B review approved, data-driven video) + the full PAR-1→8 bucket (12/12 archetype catalog); v2 is the default engine, `MEDIAHUB_GEN_V2=0` is the kill switch; evidence in `build_reports/SEQ_SPINE_2026-06-10.md` and `build_reports/GEN_QUALITY_BASELINE.md` *(completed 2026-06-10, PRs #259/#300/#301)*
- ✅ **P0.1** · Phase 0 — Free reel fallback shipped: `MEDIAHUB_REEL_ENGINE=ffmpeg` renders story cards + meet reels from the cards’ own still graphics via FFmpeg (`visual/reel_ffmpeg.py`) — no Node, no Remotion license *(completed 2026-06-10)*
- ✅ **P0.3** · Phase 0 — Every paid dependency provably optional behind a flag with a free default wired — pinned by `tests/test_paid_deps_optional.py` against the DEPENDENCY_LICENSING §2 register *(completed 2026-06-10)*
- ✅ **P0.4** · Phase 0 — Local-capable provider slot on every AI surface: LLM (OpenAI-compatible endpoints incl. Ollama, both wrappers), TTS (`MEDIAHUB_TTS_PROVIDER` with the `piper` slot), ASR (guarded — none may land unslotted), graphics (server-side stills + ffmpeg reel engine + cutout `server` default) — pinned by `tests/test_local_provider_slots.py` *(completed 2026-06-10)*
- ✅ **P0.5** · Phase 0 — AGPL isolation enforced: SearXNG stays a stock, venv-isolated, HTTP-only sidecar; `tests/test_agpl_isolation.py` fails the build on any in-process AGPL import, manifest entry, or Dockerfile drift *(completed 2026-06-10)*
- ✅ **P1.2** · Phase 1 — Realise the post-type taxonomy in code (extend vs layer on `club_platform.content_types` — Council-gated data-model call) *(completed 2026-06-11)*
- ✅ **P1.3** · Phase 1 — Cross-source planner (the strategy brain): fuse own/external/direct signals into a ranked plan keyed by sport profile *(completed 2026-06-11)*
- ✅ **P1.5** · Phase 1 — Brand-DNA-from-URL with no paid API (local scrape + local model + material-color-utilities) *(completed 2026-06-11)*
- ✅ **P2.2** · Phase 2 — Human-approval signal = the autonomy toggle (gated types pause on `workflow.CardStatus` QUEUE → APPROVED → POSTED) *(completed 2026-06-11)*
- ✅ **P2.3** · Phase 2 — Single per-type publish gate: provenance/trust + brand-safety + rate limit + global kill switch on `SafeToPost`; reconcile the two `AutonomyLevel` enums *(completed 2026-06-11)*
- ✅ **PC.3** · Phase C 🥇 — True multi-tenancy: org → workspace in one shared instance (the #1 scaling fix; single-instance-per-club collapses at ~15–40 clubs). Schema needs operator/Council sign-off — it touches the locked ADR-0003 isolation invariant *(completed 2026-06-11)*
- ✅ **PC.7** · Phase C 🥇 — Instant try-before-signup demo: paste a results file, get a watermarked 3-card preview, no account *(completed 2026-06-12)*
- ✅ **PC.8** · Phase C 🥇 — Sponsor manager + per-sponsor exposure reports (clubs fund the subscription from sponsor money) *(completed 2026-06-12)*
- ✅ **PC.10** · Phase C 🥇 — Public club achievements page + website embed/RSS of approved cards ("powered by MediaHub") *(completed 2026-06-12)*
<!-- /ROADMAP:DONE -->

## Standing context

The short list of decided, load-bearing principles — full reasoning in the
linked ADRs and research docs:

- **Hosted-only SaaS.** No customer self-host or local-install path, free or
  paid — a decided commercial principle
  ([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md)).
- **Commercialise before generalise.** Phase C outranks all capability work.
  Two hard gates before P3/P4/P5 start: *(1)* a club can sign up, pay, and
  publish with zero founder involvement; *(2)* **≥10 clubs paying annually**
  ([SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md)).
- **Stop polishing and sell.** P1.4 cleared the "sellable wedge" bar; further
  graphics work sits strictly behind Phase C sell-side progress.
- **Lawful-to-sell before sold.** No paid contract before the
  compliance-readiness gate holds: versioned Terms + Privacy Notice accepted at
  signup, a club DPA, ICO registration, the minors' consent gate (PC.12),
  deletion/export rights (PC.13), and password-reset / breach-notice / backup
  basics (PC.14)
  ([ADR-0015](adr/0015-compliance-readiness-sell-gate.md)).
- **The deterministic engine is the moat.** Parsers, detectors, the ranker,
  and colour-science stay AI-free; AI judgement goes through
  `media_ai.llm`/`ai_core.llm` with honest errors, never heuristic fakes
  (see [`../CLAUDE.md`](../CLAUDE.md)).
- **Human approval before anything publishes externally. Always.**
- **PC.3 is Council-gated.** The org → workspace schema touches the locked
  cross-tenant isolation invariant
  ([ADR-0003](adr/0003-pilot-safety-invariant-lock.md)) and needs
  operator/Council sign-off before implementation.
- **NGB channel, reality-checked.** Swim England **data-API access is real —
  apply**; promotional NGB endorsement is down-weighted to speculative
  ([ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)).

**Companion docs:** [POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md) ·
[CONTENT_PLANNER](CONTENT_PLANNER.md) ·
[AUTONOMY_MODEL](AUTONOMY_MODEL.md) · [SPORT_PROFILES](SPORT_PROFILES.md) ·
[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md) ·
[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md) · [THEMING](THEMING.md) ·
[GENERATION](GENERATION.md) ·
[CREATIVE_SUITE_PARITY](CREATIVE_SUITE_PARITY.md) (Phase 6 long-form) ·
research base in
[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md) ·
June 2026 ideas backlog (feeds Phase W + PC.7–PC.10 + P4.5/P4.6) in
[research/PRODUCT_IDEAS_2026-06.md](research/PRODUCT_IDEAS_2026-06.md) ·
new-starter path: [START_HERE](../START_HERE.md) + [GLOSSARY](../GLOSSARY.md).

The long-form plan follows — same document, full depth.

---


## In plain words (start here)

A **roadmap** is our plan for what to build next, and *why*. MediaHub is being
**redirected**: from "swimming results → social posts" into a **content-strategy
brain** for sports teams — software that works out *what a team should post*,
drafts it, and (where a team allows it) publishes it largely on its own. Swimming
becomes the **first example** of a general pattern, not the whole product.

The plan now has **seven stages, Phase 0 to Phase 6**:

- **Phase 0 — De-risk:** make sure nothing in the core forces a hidden fee.
  *(✅ done — 2026-06-10.)*
- **Phase 1 — Strategy brain:** the "what should we post?" thinking, the list of
  post types, and a settings sheet per sport.
- **Phase 2 — Autonomy:** per-post-type controls for how much MediaHub may post on
  its own, with strong safety guardrails.
- **Phase 3 — More sports & inputs:** football, basketball, running, and more.
- **Phase 4 — Post directly:** publish straight to the platforms (and stop needing
  the paid Buffer service).
- **Phase 5 — Free AI everywhere:** run the AI locally so there are no per-use fees.
- **Phase 6 — Our own creative suite:** MediaHub's own version of everything
  Canva and Adobe Express can make — but filled in automatically from the
  club's data instead of starting from a blank page.

> These stages **supersede** the previous three-stage plan (*Parity →
> Distinction → Leadership*). That older plan's detailed build prompts are kept in
> the appendices for reference.

> **Ahead of all six in priority (added 2026-06)** sits a new
> **Phase C — Commercialise & Distribute**: self-serve signup, billing, true
> multi-tenancy, sane pricing, a real way to reach clubs — and, added
> 2026-06-12, the **legal/compliance pack** (terms, privacy, a club data
> agreement, minors' consent, data rights, backups) that makes the first sale
> lawful and trustworthy. The numbered phases
> describe *capability*; **Phase C is about getting paid for it** — and a hard-nosed
> scaling diligence
> ([research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md))
> concludes that **comes first.** So the order is now *commercialise, then generalise*:
> the expansions (Phases 3–5) wait until clubs can sign up and pay on their own. The
> reasoning sits under **"A commercial reality check"** below and is recorded in
> **[adr/0011-commercial-reconcile-revenue-reality.md](adr/0011-commercial-reconcile-revenue-reality.md)**.

> **Beside the stages sits a pick-list (added 2026-06-11): Phase W — make the
> swimming product deeper.** Fourteen researched extras — things like club
> records, photo-consent tracking, live updates during a gala, printable
> certificates, Welsh captions. It has no fixed order and no gate; we pull an
> item from it whenever it helps win or keep a club. The research behind all of
> it (22 ideas; the other eight became Phase C and Phase 4 items) lives in
> [`research/PRODUCT_IDEAS_2026-06.md`](research/PRODUCT_IDEAS_2026-06.md).

Each task carries a little badge so you can see how it's going:
✅ done · 🔵 in progress · ⚠️ stuck · ❌ not started yet.

The **"Last updated"** line and the **"Recent activity"** table further down update
themselves automatically whenever we ship something — you don't edit those by hand.

> New to the team? Read **[../START_HERE.md](../START_HERE.md)** first, then come
> back here. Tricky word? See **[../GLOSSARY.md](../GLOSSARY.md)**. The strategy
> behind this rebuild lives in five companion docs —
> **[POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md)** ·
> **[AUTONOMY_MODEL](AUTONOMY_MODEL.md)** ·
> **[SPORT_PROFILES](SPORT_PROFILES.md)** ·
> **[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md)** ·
> **[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md)** — with the evidence base in
> **[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md)** and the
> decision recorded in
> **[adr/0004-roadmap-rebuild-multisport-autonomy.md](adr/0004-roadmap-rebuild-multisport-autonomy.md)**.

---

> **Reading this:** the single forward-looking roadmap for MediaHub, organised as
> **Phase 0–6**. Only *not-yet-done* work is tracked in detail; shipped work is
> summarised under **"Where we are today."** The previous spine's build and
> verification prompts live in the appendices: **Appendix A** (Generative Content
> Engine v2), **Appendix B** (growth & expansion — *legacy sequence, superseded*),
> and **Appendix C** (Adaptive Theming Engine verification).

**Strategic thesis:** MediaHub is a **content-strategy brain, not a results
parser.** The moat is the intelligence layer — ingest → detect → rank → brand →
generate → approve → export — now **generalised across sports** and made **largely
autonomous**, delivered as a **hosted SaaS** (hosted-only — no customer self-host
tier; a decided principle, see [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)).
Results ingestion is one spoke among many.

**A commercial reality check (2026-06) — *commercialise before generalising*.** The
thesis above is a **capability** thesis. A 2026 scaling diligence
([research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md)) weighed it
against market data and concluded the **binding constraint is distribution and
monetisation, not more capability** — and that this roadmap, being 100% an engineering
plan with no commercial track, was missing its most important phase. The load-bearing
conclusions, now encoded below:

> ⚠️ **All revenue figures here are hypotheses/estimates, not facts** — see the
> diligence report and its caveats. No pre-launch solo venture can have high confidence
> of any specific revenue number; the confidence attaches to the *decisions*, not the
> outcome.

- **Swimming-only is mathematically capped at ≈ £150k–£400k ARR** (~1,300 UK&I
  affiliated clubs; ~2,740 USA Swimming clubs). £1M ARR at £30/mo would need ~2,778
  paying clubs — more than *every* UK affiliated club. **£1M+ requires multi-sport
  breadth *and* institutional buyers (schools / governing bodies) *and* almost certainly
  a second person.**
- **"£1M/month" (~£12M ARR) is dropped as a stated goal** — not realistic for a
  solo→small team on any evidence reviewed. The most likely *good* outcome is a
  £150k–£400k sustainable swimming business, with a low-double-digit-% shot at £1M+ only
  via sport/segment expansion plus a second person.
- **Single-instance-per-club can't scale**, and **"truly free, no hidden fees"
  self-host — as framed — cannibalises revenue.** True multi-tenancy is delivered by
  **Phase C**. The self-host tension is now **resolved (2026-06-09): hosted-only, no
  customer self-host tier** — the "no-hidden-fees / truly-free self-host" product
  principle is retired in favour of hosted SaaS (maintainer decision, see
  [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)).
- **The incumbent-bolts-on-content threat is currently LOW but is a *time advantage,
  not a moat*;** the horizontal commodity (Canva / Predis / Gipper's auto-achievement
  graphics) is the real pressure on price and narrative.

**Consequence for the plan:** a new **Phase C — Commercialise & Distribute** becomes the
**top priority**, ahead of the expansion phases. P3 (multi-sport), P4 (direct publishing)
and P5 (local-AI) are **deferred — not deleted** — behind two gates: *a club can sign up,
pay, and publish with zero founder involvement*, and *≥10 clubs paying annually*. Recorded
in [adr/0011-commercial-reconcile-revenue-reality.md](adr/0011-commercial-reconcile-revenue-reality.md).

**Realistic revenue by horizon (estimates — outcome odds, not guarantees).** The
≈ £150k–£400k swimming-only ceiling above is a *saturation* figure; the table below
decomposes it into horizons tied to the **PC.6 warm-first funnel's** club-count trajectory
and the candidate **Club £49–£99/mo billed annually** price (≈ £588–£1,188 per club per
year — **PC.4, unvalidated**). The *club-count↔ARR arithmetic and the sequencing are
>95%-confidence-correct*; the *probability bands are honest estimates of the outcome*,
flagged `[ESTIMATE]`, not commitments — they decline across horizons because each is
conditional on the one before (compounding execution risk).

| Horizon | Paying clubs | ARR @ £588–£1,188/club | Outcome probability `[ESTIMATE]` | Binding constraint |
|---|---|---|---|---|
| **H1 — Validation** (≤ ~12 mo) | ~10 (the traction gate) | ≈ £6k–£12k | **~40–55%**, *conditional on the founder actually running the warm + referral motion* — the dominant failure mode is the motion not being run, not the close rate | Founder selling-time; first revealed WTP (PC.4) |
| **H2 — Early scale** (~1–2 yr) | ~30–60 | ≈ £18k–£71k | **~25–40%** — conditional on H1 + referral compounding + retention holding (annual prepay essential) | **PC.3 multi-tenancy** — single-instance ops collapse ~15–40 clubs |
| **H3 — Swimming ceiling** (~2–4+ yr) | ~125–680 (price-dependent) | **≈ £150k–£400k** | **~10–20%** — needs sustained multi-year execution, meaningful UK *and* US penetration, and almost certainly a second person | Market size (~1,300 UK&I + ~2,740 USA clubs) + support capacity |
| **H4 — £1M+ ARR** | (out of wedge) | **≥ £1M** | **low-double-digit-%** — only via multi-sport breadth (Route A) *and* institutional buyers (Route B) *and* a second person | Out-of-wedge expansion; not swimming-only |
| **£1M/month (~£12M ARR)** | — | ~£12M | **not realistic** on any evidence reviewed | Directional north star only |

> **Sequencing caveat (load-bearing):** every horizon past **~15–40 clubs is gated on PC.3
> (true multi-tenancy)**, which is currently ⚠️ BLOCKING / escalated. Without it, per-club
> ops cost rises linearly against fixed founder hours and caps revenue *below* the H3
> market math regardless of demand — so the £150k–£400k ceiling is only reachable *if PC.3
> ships*. Club-count↔ARR arithmetic and the ~£150k–£400k anchor derive from the sourced
> market sizes and candidate price above (see
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)); the
> per-horizon probability bands are flagged estimates, consistent with the diligence's
> low-double-digit-% confidence on £1M+.

### External research pass — June 2026 (confirms & sharpens)

A fresh external market-and-scalability pass (June 2026) re-ran the diligence against
current sources. It **changed no figure** — the ≈ £150k–£400k swimming-only ceiling, the
dropped "£1M/month" goal, and the H1–H4 horizons above all stand — and **sharpened three
points** (full evidence + sources:
[`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md), *Evidence
refresh — cycle 5*):

- **White-space, verified and narrowed.** No swim-data incumbent — **SwimTopia,
  TeamUnify / SportsEngine, Swimcloud, Hy-Tek / MeetMobile, Swim Club Manager, Swim
  Manager** — ingests a result file and emits branded, ranked content; they stop at
  PB / results display + *manual* sharing. **Gipper** ships swimming graphic *templates*
  (meet-day, results, commitment) but **does not ingest HY3 / SDIF / result files** — a
  volunteer still keys the numbers in. So the *result-file → ranked, branded content* path
  is undefended **today** — a **time advantage, not a moat** (no patent; any incumbent
  holding clean results + PBs could bolt it on). **Watch item: Gipper adding result-file
  ingestion would close the head-start.**
- **Platform publishing is gated by API policy** (sharpens Phase 4): Instagram needs a
  Business / Creator account + a connected Facebook Page + Meta **App Review**
  (~2–4 weeks/permission) + **Business Verification**; TikTok's *unaudited* Content-Posting
  client can post only **private (SELF_ONLY), ≤5 users / 24h** until it passes an audit. So
  ship **Bluesky + Mastodon first** (P4.1) and keep Instagram / TikTok behind human approval
  and the audit timeline (P4.2) — "launch-day IG/TikTok auto-posting" is on the EXCLUDE list.
- **Results-data acquisition is a ToS / CMA / GDPR question** — much of it is *minors'*
  competition data. **Prefer the official Swim England approved-systems API over scraping**
  (reinforces PC.6(a) and the [ADR-0003](adr/0003-pilot-safety-invariant-lock.md) isolation
  lock).

**The high-probability do / don't filter (only what the evidence supports):**

- **✅ INCLUDE:** warm-first hand-sell from the Swansea / South-East-Wales swim network ·
  manual-first (concierge) delivery · flat **annual** pricing set by revealed WTP (PC.4) ·
  a referral engine (2 named intros per signed club) · the Swim England approved-systems
  API application (PC.6(a)) · Stripe switched on (PC.2 ✅) · ship **PC.3** true
  multi-tenancy (the #1 operator/Council-gated scaling fix) · **Bluesky + Mastodon** as the
  first free publish targets (P4.1).
- **🚫 EXCLUDE:** paid ads · viral-growth assumptions · VC fundraising · US expansion
  before UK validation · multi-sport before ≥10 paying clubs · reliance on NGB
  *promotional* endorsement ([ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)) ·
  launch-day Instagram / TikTok auto-posting · ToS-breaching scraping of results data.

---

---

## Where we are today (June 2026)

Three facts shape the work ahead.

1. **The intelligence layer is the moat and is already ahead — for swimming.**
   Brand-DNA + guidelines ingestion, voice imitation, the AI-derived operating
   profile, the Adaptive Theming Engine, swim recognition, and the
   render/caption/pack pipeline all ship and are live. The reframe does not throw
   any of this away — it **generalises** it.

2. **The product is operator-managed and turnkey.** Configuration (LLM keys, Buffer
   token, cutout provider) is set once via env vars at deploy time; the end user
   never sees a settings screen.

3. **Most of the new architecture already has a home in the code.** The new
   concepts map onto existing seams — `recognition.registry.register_sport`,
   `club_platform.content_types`, `workflow.CardStatus`, `ClubProfile.org_type` —
   so this is generalisation, not a rewrite. See
   [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md).

**Verified shipped (✅)** — confirmed against the code this rebuild:

- Brand-DNA / guidelines ingestion (`brand/dna_capture.py`, `guidelines.py`),
  voice imitation (`brand/voice_imitation.py`, `voice/learned/`), and the AI
  operating profile (`brand/derived.py`).
- Adaptive Theming Engine (`theming/`, the former §1.6 — see [`THEMING.md`](THEMING.md)
  and Appendix C); single DTCG palette consumed by web + motion + email + graphic.
- Swim recognition (`recognition_swim/` on the sport-agnostic `recognition` bus),
  PB verification (`pb_discovery/`), ranker (deterministic).
- `graphic_renderer` (Playwright → PNG) and Remotion reels (`remotion/` +
  `visual/motion.py`).
- `edge-tts` voiceover (optional, `MEDIAHUB_VOICEOVER=1`, honest-errors when absent).
- Buffer publishing path (`publishing/buffer.py`; human clicks Schedule — no autopost).
- Content packs (`content_pack/`, `workflow/pack.py`).
- **Free cutout by default** — in-process `rembg` (`MEDIAHUB_CUTOUT_PROVIDER=server`);
  Replicate/PhotoRoom are optional paid alternates. *(This is Phase-5 substitution
  already done.)*
- Cross-tenant run isolation invariant (`_can_access_run`,
  `tests/test_run_route_isolation_invariant.py`) — see
  [`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md).
- Gemini→Anthropic provider failover (`media_ai/llm.py`, `ai_core/llm.py`).
- **Self-serve signup + auth + Stripe billing** (`web/auth.py`, `web/billing.py`): routes
  `/signup` `/login` `/logout`, bcrypt + a signed session cookie, a `users.jsonl` ledger,
  plus Stripe Checkout + Customer Portal + a signed webhook. Merged **PR #267**
  (2026-06-09); billing **honest-503s until `STRIPE_*` keys are set**. This is
  **PC.1 + PC.2** — see Phase C.

**Not yet shipped (❌)** — the reframe's new surface:

- ~~The content-strategy brain as the hub~~ → **shipped 2026-06-10 (P1.3):**
  the cross-source planner fuses own/external/direct signals into a ranked,
  explainable per-org plan keyed by sport profile (`/plan`); its external
  spokes stay thin until P3's data sources land.
- Multi-sport beyond swimming (the `register_sport` seam exists; only swimming is
  registered; `football.yaml` now *plans* via the profile but has no detector engine).
- Per-content-type **autonomy toggles in the UI** (the *runner* now exists — see
  below — but the per-post-type toggle and workspace control do not, and the
  `sport_profiles.AutonomyLevel` enum that was meant to drive them is still inert).
- **Direct-to-platform** publishing (only Buffer today).
- The **local-AI substitution layer** (Ollama / Piper / whisper.cpp / Satori absent;
  rembg present).
- **The rest of the commercial layer** — ~~true multi-tenancy missing~~ → **shipped
  2026-06-11 (PC.3,** [`adr/0014`](adr/0014-org-workspace-multitenancy-schema.md)**)**:
  org → workspace membership binding in one shared instance, with PC.4's revealed-WTP
  instrumentation and PC.6's funnel tooling landing alongside it on
  `/operator/commercial`. The **build side of Phase C is now fully closed**; what stays
  open is the sell side — billing keys unset, prices unvalidated (**PC.4** gate), no
  clubs sold (**PC.6** gate) — so there are still **zero paying customers**. The
  "build/sell imbalance" of the 2026 scaling diligence is now entirely a *selling*
  imbalance; see Phase C below.

**Shipped (✅ 2026-06-10):** the Generative Content Engine v2 — the full
Appendix A **Sequential Spine** (SEQ-0 → SEQ-4) merged in **PR #301** on top of
Tier A (PR #259): the DesignTokens contract (`brand/design_tokens.py` +
lockup selection), the Tier B design-spec director with the candidate
pool / APCA compliance ranking / additive `?candidates=N` route, the **SEQ-3
cutover** (the old enum-permutation engine removed under the gated 15+15-step
process; `MEDIAHUB_GEN_V2=0` remains the kill switch; the "A/B beats the old
engine" gate was reviewed and approved — 6/6 vs ≤1/6 approvable), and the
SEQ-4 video stage (data-driven reel scene structure, archetype-matched
motion, opt-in `MEDIAHUB_GEN_BG`). v2 is the **default engine**; the
archetype library stands at 11/12 (PAR-7's `duo_athlete_split` outstanding,
picked up automatically when it lands). Evidence:
[`build_reports/SEQ_SPINE_2026-06-10.md`](build_reports/SEQ_SPINE_2026-06-10.md);
suite 3628 passed / 1 skipped. The sport-profile scaffolding remains inert.

**Shipped (✅ 2026-06-10): Phase 0 complete.** The de-risk phase closed in one
pass: the **P0.1 free reel engine** (`MEDIAHUB_REEL_ENGINE=ffmpeg` — story cards
and meet reels rendered from the cards' own still graphics by FFmpeg, no
Node/Remotion), the **P0.4 provider slots** (OpenAI-compatible/Ollama LLM
endpoints in both wrappers, the `MEDIAHUB_TTS_PROVIDER` seam with the `piper`
local slot, the no-unslotted-ASR guard, on-server graphics defaults), and the
**P0.3/P0.5 guard suites** that turn the dependency register's promises into
build-failing invariants (paid paths provably optional; AGPL strictly behind a
network boundary — SearXNG venv-isolated, HTTP-only). Details in the Phase 0
section below.

#### Also shipped since this plan was written — *not* in the Phase 0–5 spine

A whole stream of work landed after this roadmap was last rewritten and has **no
item here**. It was driven by a separate "**Capabilities 1–5 / Section 6**" report
(referenced in the council transcripts and in `.env.example`, but never checked in
as a doc) and by day-to-day product-quality passes. Folding it in so the roadmap is
honest:

- **Capability 1 — `ai_core` LLM client + bounded tool-loop.** A provider-agnostic
  OpenAI-compatible client and `ask_with_tools(tools, on_tool_call, max_rounds)`
  (the substrate the autonomy + research loops ride on). *Wired.*
- **Capability 2 — semantic caption memory** (`memory/`). Embeddings + a `sqlite-vec`
  store; recalls a club's prior accepted captions into the caption/voice flow.
  Off until an embed endpoint is configured. *Wired.*
- **Capability 3 — web research** (`web_research/`). DuckDuckGo by default, optional
  self-hosted SearXNG, plus a bounded deep-research ReAct loop; converged with
  PB-baseline discovery behind a type-safe gate (the model proposes URLs, the
  deterministic parser still asserts the time). *Wired, £0 default.*
- **Section 6 — the autonomy substrate.** `scheduler/` (an exactly-once, atomic-claim
  SQLite job runner — *not* Temporal; the council chose in-process Flask+threading
  over new infra), `notify/` (ntfy + webhook pings), and `autonomy/` — a **bounded,
  narrow-tool autonomy runner** that prepares + *queues for human review* and can
  never publish. All **off by default**. This is a real, if partial, down-payment on
  **Phase 2** via a different architecture than P2.1 proposed.
- **Results from a link** (`results_fetch/`). Paste a results URL → 3-tier crawl
  (static → headless Chromium → AI vision) → mirror ZIP → the existing pipeline.
  Sport-agnostic *ingestion*; production-ready. See [`RESULTS_FROM_URL.md`](RESULTS_FROM_URL.md).
  (Detector *quality* for non-swim sports still needs a registered sport — so this
  advances **P3** ingestion without yet satisfying its per-sport exit criterion.)
- **Observability** (`observability/`) — LLM-usage + uptime tracking. **Graphics /
  caption / brand-fidelity polish** — new card layouts, AI-palette-from-usage, logo
  vision colours, caption tone/jargon/locale fixes (the bulk of recent commits).

> **The two same-named autonomy enums are reconciled (P2.3, 2026-06-11):** the
> runner's pre-approval reach axis is renamed `autonomy.tools.RunnerReach`
> (`OFF`/`SUGGEST`/`DRAFT`/`PREPARE`), leaving
> `sport_profiles.autonomy.AutonomyLevel` (`draft_only`/`approval_required`/
> `fully_autonomous`) as the single enum called AutonomyLevel — the publishing
> policy axis. Different axes, now structurally impossible to conflate.

> **Test baseline (point-in-time):** the full suite is green — **2836 passed, 1
> skipped** in a fully-provisioned environment after merging `main` (the lone skip
> is the opt-in render-diff regression). Skips are environmental, never structural.

---

## Phase 0 — De-risk licensing & cost · P0 · ✅ **COMPLETE (2026-06-10)**

**Goal.** Keep the **operator's hosting cost and licensing liability low** in the
critical path — no mandatory paid API and no embedded-AGPL lock-in. (Originally framed
as guaranteeing a "truly-free self-host" promise; that promise is **retired** —
hosted-only, see [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md) — but the
cost/licensing de-risk still matters, now for the *hosted* deployment's margins.)

**Exit criterion — MET.** Zero **mandatory** paid API or dependency in the critical
path; every paid option is behind a flag/env var with a documented free default; AGPL
services are isolated behind a network boundary (never embedded). The criterion is
now **continuously enforced**, not just satisfied: three guard suites
(`tests/test_paid_deps_optional.py`, `tests/test_local_provider_slots.py`,
`tests/test_agpl_isolation.py`) fail the build on any regression. See
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).

### P0.1 — Make the Remotion reel engine optional with a free fallback · ✅ **DONE (2026-06-10)**
Remotion was the single biggest hidden-cost liability (Company License for for-profit
orgs >3 people). It is now optional behind `MEDIAHUB_REEL_ENGINE`: the **`ffmpeg`
engine** (`visual/reel_ffmpeg.py`) renders the same story-card and meet-reel MP4s
with zero licensing cost — each beat is the card's **own still graphic** (the
existing Playwright/Chromium renderer, already a hard dependency), given a
deterministic Ken Burns zoom and stitched with crossfades by FFmpeg (static binary
via the `imageio-ffmpeg` wheel; system ffmpeg / `MEDIAHUB_FFMPEG` also honoured).
Where a card has a persisted CreativeBrief, the frame renders from that exact brief
at story size, so the reel literally animates the card's approved design — brand
parity *better* than a parallel template. Reel length keeps the same data-driven
`reel_duration_for` arithmetic; cache keys are engine-separated; a missing binary
raises an honest `ReelEngineUnavailable`. Remotion remains the default for
deployments that license it; `/healthz/deps` reports both engines' availability and
gates "motion ok" on the *active* engine. The originally-sketched **Satori** path
remains P5.4 — it is a *performance* fast-path (lighter than Chromium), not the
licensing fix; this fallback closes the licensing risk without it. (Bonus fix
shipped with it: `reel_cover`'s mega headline now auto-fits long meet names via the
PAR-2 autofit helper instead of overflowing the frame.)

### P0.2 — Keep cutout free-by-default · ✅ **DONE**
Already shipped: in-process `rembg` is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`);
Replicate/PhotoRoom are opt-in paid alternates. Retained here as the de-risk record.

### P0.3 — Flag every paid dependency with a free substitute · ✅ **DONE (2026-06-10)**
The register ([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) §2) is now
**provable**: `tests/test_paid_deps_optional.py` pins, per register row, that with
zero paid configuration each paid path is off (or substituted by its free default)
and honest-errors rather than spending or faking — Remotion (optional behind the
P0.1 engine flag), edge-tts (`MEDIAHUB_VOICEOVER` opt-in), Buffer (token-gated,
`BufferAuthError` when absent), Replicate/PhotoRoom (cutout defaults to in-process
`server`), hosted LLM keys (`ProviderNotConfigured`, never a heuristic caption),
Stripe (honest-503 `billing_configured()` gate), and Imagen backgrounds
(`MEDIAHUB_GEN_BG` opt-in, default off).

### P0.4 — A local-capable default for every AI call · ✅ **DONE (2026-06-10)**
Precondition for Phase 5, now in place — every AI surface *admits* a local provider
so no cloud key is required by any interface (full local implementations remain
Phase 5 work): **LLM** — both wrappers (`ai_core.llm`, `media_ai.llm`) accept an
OpenAI-compatible endpoint via `MEDIAHUB_LLM_ENDPOINTS`, keyless local servers
(Ollama / llama.cpp / vLLM) included; **TTS** — `MEDIAHUB_TTS_PROVIDER` seam on the
voiceover surface with `piper` registered as the local slot (honest error until
P5.2 implements it; surfaced in `/healthz/deps`); **ASR** — no ASR call exists yet
(arrives with P5.3), and a guard fails the build if a speech-to-text import ever
lands outside a provider seam; **graphics** — rendering is already on-server
(Playwright stills; P0.1 ffmpeg reels), cutout defaults to in-process rembg, and
the one cloud-only image call (Imagen backgrounds) is opt-in with the procedural
backdrop as the no-key default. Pinned by `tests/test_local_provider_slots.py`.

### P0.5 — Isolate any AGPL service behind a network boundary · ✅ **DONE (2026-06-10)**
The deployed AGPL service is **SearXNG**: installed stock and unmodified into an
isolated virtualenv (`$SEARXNG_VENV`), run as its own process only when
`MEDIAHUB_RUN_SEARXNG=1`, queried exclusively over HTTP
(`web_research/searxng_client.py`) — never imported in-process. That boundary is
now **enforced**: `tests/test_agpl_isolation.py` fails the build on any in-process
import of a known-AGPL module, any AGPL distribution appearing in
`requirements.txt`/`pyproject.toml` (incl. `minio` — policy prefers cloud S3), or
the Dockerfile installing SearXNG outside its venv. If/when Postiz/MinIO/MediaCMS
are ever used, the same separate-service-over-API rule applies. Policy in
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) §3.

**Building blocks (as shipped).** FFmpeg (LGPL/GPL, free — static binary via
`imageio-ffmpeg`, invoked strictly as a subprocess) + the existing Playwright still
renderer for reels; `rembg` (MIT, free) — the cutout default; OpenAI-compatible
endpoints (Ollama, MIT) as the LLM local slot; Piper (MIT) reserved as the TTS local
slot. Remotion Company License is *not* a hard requirement; no AGPL is embedded.
Satori (MPL-2.0) stays on the board for P5.4 as a render fast-path.

**Dependencies.** None upstream. **Feeds every later phase** — especially P4
(publishing) and P5 (local-AI), whose free defaults this phase guarantees.

---

## Phase 1 — Strategy brain + post-type taxonomy + sport profiles · P1 · ✅ **COMPLETE (2026-06-10)**

**Goal.** Build the planner that fuses **three-source intelligence** (own + external
+ direct signals) into a ranked content plan; realise the cross-sport **post-type
taxonomy**; and ship the **sport-profile** config. Ship swimming + one other profile.

**Exit criterion — MET (2026-06-10).** A profile-driven planner produces a ranked,
explainable content plan for **≥2 sport profiles** (swimming end-to-end; football
on profile + direct/external signals, honestly noting its missing engine), grounded
in the three sources — not just from a results file. Pinned by
`tests/test_cross_source_planner.py`; product surface `/plan`. The external-signal
spokes are deliberately thin until P3's data sources land (discovered-context +
calendar today; fixtures/news feeds arrive with the sport spokes).

### P1.1 — Sport-profile schema + loader + AutonomyLevel + 2 profiles · ✅ **DONE**
Shipped this rebuild: `mediahub.sport_profiles` (`SportProfile`/`PostTypeConfig`,
`AutonomyLevel`), `data/sport_profiles/{swimming,football}.yaml`, unit tests.
Originally inert scaffolding; **now live** — the P1.3 planner enumerates profiles
at runtime, P2.4's per-type policy uses its `AutonomyLevel` as the canonical
publishing-policy enum, and both shipped profiles carry every implemented
universal surface. See [`SPORT_PROFILES.md`](SPORT_PROFILES.md).

### P1.2 — Realise the post-type taxonomy in code · ✅ **DONE (2026-06-10)**
The Council-gated extend-vs-layer call was pressure-tested (5 advisors + peer
review, unanimous direction) and decided: **layer, on a slug-canonical spine**
([`adr/0013-post-type-taxonomy-slug-canonical.md`](adr/0013-post-type-taxonomy-slug-canonical.md)).
Shipped as `club_platform/post_types.py` — taxonomy slugs are the canonical
post-type identity (universal slugs in code, sport-specific in profile YAML);
`ContentType` is demoted to the implemented-surface badge (subset invariant
test-pinned; never grows an unimplemented member, so no "Coming soon" leakage);
the two historic mismatches were renamed under the gated 15+15-step process
(`WEEKEND_PREVIEW`→`EVENT_PREVIEW`, `SPONSOR_POST`→`SPONSOR_ACTIVATION`) with
read-tolerant legacy aliases at every persistence boundary (per-org autonomy
policy keys, saved stub packs, the type gate) so operator-set autonomy levels
survive. `tests/test_post_types.py`.

### P1.3 — Cross-source planner (the strategy brain) · ✅ **DONE (2026-06-10)**
Shipped in `content_engine`: `signals.py` gathers the three sources (own = runs +
workflow states + draft packs + posting recency; external = discovered meet
context + calendar anniversaries; direct = operator-entered upcoming events,
structured goals targeting a post type, blackout dates, sponsor-configured fact),
and `planner.py` fuses them into a ranked, explainable `ContentPlan` keyed by
sport profile — the swim newsworthiness ranker's transparent additive-scoring
pattern, generalised; deterministic (no LLM in the ranking loop), every item
carrying signal-grounded reasons including the honest negative ("no football
results ingested yet"). Per-org persistence under `DATA_DIR/content_plans/` and
an org-scoped product surface: **Plan** in the nav (`/plan`) +
`/api/plan/{generate,latest,inputs}`. See [`CONTENT_PLANNER.md`](CONTENT_PLANNER.md);
`tests/test_cross_source_planner.py`.

### P1.4 — Generative Content Engine v2 (distinctive, on-brand output) · ✅ **DONE**
The asset-quality stream: replace the enum-permutation variation mechanism with an
archetype library + design-spec director, keeping the deterministic engine. Decided
in [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md); runnable
build prompts in **Appendix A** (PAR-\* / SEQ-\*). **Complete (2026-06-10):** Tier A
(SEQ-1, PR #259) + the full Sequential Spine SEQ-0→SEQ-4 (PR #301) — tokens, the
Tier B director/pool/compliance ranking, the gated SEQ-3 cutover (old engine
removed; A/B review approved; `MEDIAHUB_GEN_V2=0` kill switch retained), and the
SEQ-4 video stage. All seven Appendix A §5 acceptance criteria met; evidence in
[`build_reports/SEQ_SPINE_2026-06-10.md`](build_reports/SEQ_SPINE_2026-06-10.md).
The **parallel bucket (PAR-1 → PAR-8) is likewise all shipped** (PR #300):
captions live end-to-end (approval seam → few-shot store → route injection,
also feeding the SEQ-0 voice block), autofit with measured Anton calibration,
saliency, the design-spec contract, variant metrics, brand bootstrap aligned to
the DesignTokens lockup vocabulary, the complete 12-archetype catalog
(`duo_athlete_split` closes it) with every archetype's authored notes briefing
the director's catalog, and the docs/ADR refresh — plus the renderer
self-hosted-font fix, regression-pinned.

### P1.5 — Local brand-DNA-from-URL · ✅ **DONE (2026-06-10)**
The Open-Pomelli-style flow now runs with **zero paid APIs**: the scrape is
local and **SSRF-hardened** (public-host gate re-validated per redirect hop on
page/CSS/image fetches); the colour science is local — `brand/palette_evidence.py`
quantizes the club's real logo/og-image **pixels** through
`material-color-utilities` (`QuantizeCelebi` → `Score`, the theming engine's own
maths) and merges them with site-wide CSS-usage frequencies into
provenance-carrying evidence; and the one judgement step (semantic role
assignment + voice) rides `media_ai.llm`, which serves keyless local
OpenAI-compatible endpoints (Ollama via `MEDIAHUB_LLM_ENDPOINTS`, P0.4) exactly
like the hosted providers. LLM palette picks are validated against the evidence
universe (an invented hex is dropped and backfilled from real evidence — the
`bootstrap_extract` anti-hallucination doctrine); with no provider at all the
palette stays evidence-grounded and the voice fields stay honestly empty
(`no_provider`). Per-slot provenance persists to `brand_palette_sources` /
`brand_palette_reasoning`. `tests/test_brand_dna_local.py`.

**Building blocks.** crewAI / LangGraph **patterns** (free frameworks — *verify
MIT-family*) paired with **Ollama** (MIT, free) for the planner;
`material-color-utilities` (Apache-2.0) — already in use; Satori for graphics
(Phase 5 overlap). All AI calls must keep the honest-error rule.

**Dependencies.** Needs **P0** (a free AI path). **Feeds P2** (autonomy needs a
plan to act on) and **P3** (new sports need profiles).

---

## Phase 2 — Autonomy toggles + orchestration backbone · P2 · ✅ **COMPLETE (2026-06-11)**

**Goal.** Put every content type on a durable workflow with an **optional
human-approval signal**; implement the guardrails + kill switch + audit trail;
expose the per-type `autonomy_level` in the workspace.

**Exit criterion — MET (2026-06-11).** A content type can be set to any
`AutonomyLevel` (P2.4 store + Settings → Autonomy); `fully_autonomous` publishes
**only** when all guardrails + the confidence gate pass (the P2.3 publish gate,
evaluated against the exact caption that would ship); the kill switch halts
publishing instantly — checked first on every gate evaluation and re-asserted
inside the Buffer call, so a mid-cycle engagement still halts; every autonomous
decision (allowed AND blocked verdicts, auto-approvals, publish attempts) lands
in the immutable per-org audit ledger. Pinned end-to-end by
`tests/test_autonomous_publishing.py::test_phase2_exit_criterion_end_to_end`.
Full model: [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md).

### P2.1 — ~~Temporal orchestration adapter~~ → in-process scheduler + bounded runner · ✅ **DONE (in-process, not Temporal)**
Superseded by a council decision: instead of a Temporal adapter, durability is the
`scheduler/` atomic-claim SQLite runner + the `autonomy/` bounded loop, both riding
`ai_core.ask_with_tools`. `workflow.store` remains the card-state precursor. Temporal
is **not** being adopted; this item is closed by the in-process substrate.
*Quality-reviewed 2026-06-11:* security strong (atomic claim, fixed tool
allow-list, structural no-publish, strict tenancy), with five hardening fixes
applied — the audit ledger no longer raises/corrupts on oversized args (it
always writes valid JSON), the ledger and the posting log resolve `DATA_DIR`
per call instead of freezing it at import, a scheduler claim hiccup no longer
aborts the tick for remaining tasks, the silent busy-timeout fallback is now
logged, and the runner's enum is renamed (see P2.3).

### P2.2 — Human-approval signal = the autonomy toggle · ✅ **DONE (2026-06-11)**
Shipped as `workflow/approval.py::apply_approval_signal` on the existing
`workflow.CardStatus` QUEUE → APPROVED → POSTED transition: gated types
**pause on the signal** (cards stay QUEUE/EDITED until a human approves);
a `fully_autonomous` type's cards run the P2.3 publish gate against the exact
caption that would ship — passing cards auto-APPROVE and, when the org has
chosen autonomous channels (Settings → Autonomy; per-org Buffer token),
publish through the same Buffer path a human click uses (workflow
schedule-state + posting log + audit identical to the human path). Failing
cards stay queued for the human with blockers recorded — autonomy degrades to
approval, never the reverse; human decisions are never revisited.
Triggers: `POST /api/autonomy/sweep` (org-scoped) and the `approval_signal`
scheduler task type. Machine-approved captions deliberately don't feed the
voice-learning store.

### P2.3 — Guardrails: provenance/trust · brand-safety · rate limit · kill switch · audit · ✅ **DONE (2026-06-11)**
The single per-type publish gate shipped: `publishing/publish_gate.py` —
kill switch → per-type policy → provenance (`recognition.schema.SafeToPost`
plus the run trust report's post/review/hold vocabulary, fail-closed on
missing/unknown) → per-type confidence threshold (default 0.85, floor 0.5,
operator-tunable per type in Settings → Autonomy) → deterministic
brand-safety (AI-tell ban-list, the org's `brand_phrases_to_avoid`, platform
length) → safeguarding (a card concerning a minor never auto-publishes,
ADR-0003) → per-org rate caps over the posting log
(`MEDIAHUB_AUTONOMOUS_HOURLY_CAP`/`MEDIAHUB_AUTONOMOUS_DAILY_CAP`). Every
verdict is explainable per check and audited. The two `AutonomyLevel` enums
are **reconciled**: the runner's reach axis is renamed
`autonomy.tools.RunnerReach` (OFF/SUGGEST/DRAFT/PREPARE), leaving
`sport_profiles.autonomy.AutonomyLevel` as the single publishing-policy enum.
`/healthz/deps` reports the gate (`publish_gate`) alongside the P2.4 policy.

### P2.4 — Per-type autonomy controls in the workspace · ✅ **DONE**
Surface the toggle; default everything gated; warn before enabling `fully_autonomous`.
Shipped + live (PR #297): Settings>Autonomy tab with per-profile per-type policy defaulting to approval_required; publish gate consults the policy behind the global kill switch; /healthz/deps exposes per_type_autonomy. Canonical enum = sport_profiles.autonomy.AutonomyLevel (the runner's separate reach axis was renamed RunnerReach in P2.3). *Extended 2026-06-11 (P2.3):* the tab also carries the per-type auto-publish confidence threshold and the org's autonomous-channel list.

**Building blocks.** **Temporal** (MIT — truly free to self-host; 3,000+ paying
customers incl. Snap/Netflix/Stripe) for the backbone + human-in-the-loop signal.
The "Agent Inbox" pattern (langchain-social-media-agent — *verify*) as reference.

**Dependencies.** Needs **P1** (a content plan) and **P0** (free path). Gates **P4**
(publishing must obey autonomy + guardrails).

---

## Phase C — Commercialise & Distribute · PC · 🔵 **sell side open — compliance build-out reopened 2026-06-12 (PC.11–PC.14)** · 🥇 TOP PRIORITY

> **Why "Phase C", not "P6".** It is lettered, not numbered, because it does not sit
> *after* Phase 5 — it sits **ahead of the expansion phases (P3/P4/P5) in priority.** The
> numbered phases are *capability*; Phase C is *commercialisation*. Added in the 2026-06
> diligence reconcile
> ([`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md));
> evidence base in
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md). It does not
> invent new work — it **promotes and reconciles** Appendix B **Step 7** (commercial
> layer), Appendix B **Step 14** (multi-club orchestration), and the cross-cutting
> **"Multi-tenancy: org → workspace"** item into one front-of-queue track.

**Goal.** Make MediaHub **sellable without the founder in the loop**: self-serve signup +
auth, Stripe billing, **true multi-tenancy** (org → workspace in one shared instance),
validated pricing with annual prepay, a resolved free-self-host position (**resolved:
hosted-only** — [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)), and a
go-to-market motion. **Update 2026-06-09:** the *build* half is now half-closed —
self-serve signup + auth (**PC.1**) and Stripe billing (**PC.2**) shipped and are live
(merged PR #267). But billing **honest-503s until the operator sets `STRIPE_*` keys**, so
there are still **zero paying customers** against ~164k LOC. The diligence's central
"build/sell imbalance" is therefore **half-closed on the build side and entirely open on
the sell side** — the remaining gates are true multi-tenancy (**PC.3**), validated
pricing (**PC.4**) and a go-to-market motion (**PC.6**).

**Update 2026-06-11 — the build side is now fully closed.** **PC.3 shipped** (org →
workspace membership binding, Council-pressure-tested, [`adr/0014`](adr/0014-org-workspace-multitenancy-schema.md)),
and the engineering halves of **PC.4** (revealed-WTP quote ledger + per-quote Stripe
Checkout + verified payment recording) and **PC.6** (warm-first pipeline tooling + the
drafted Swim England application) landed with it on the operator console
(`/operator/commercial`). Everything that remains in Phase C is selling: set the
`STRIPE_*` keys, pre-bind the pilot clubs, quote real annual prices, run the warm +
referral motion, submit the NGB application. The exit gates are unchanged and unmet —
**zero paying clubs** today; code can no longer be the excuse.

**Update 2026-06-12 — the build side is reopened: the compliance surface was never
built.** A compliance-readiness audit (maintainer-instructed) found that "sell now"
was being pushed with **no Terms of Service, no Privacy Notice (the existing
`/privacy` route is a data-inventory/delete tool, not a policy), no club DPA, no
ICO registration, no terms acceptance at signup, no account deletion, no data
export, no password reset (no transactional email at all), and no backup/restore
story** — while the product processes **minors'** names, ages, performance data and
photos for UK clubs and publishes them on a public wall. Root cause and decision in
[`adr/0015-compliance-readiness-sell-gate.md`](adr/0015-compliance-readiness-sell-gate.md):
Phase C was composed from a *revenue* diligence, so "lawful to operate" was never an
exit criterion. **PC.11–PC.14** close the gap and a third exit gate below makes it
structural. The selling motion can be *prepared* in parallel (warm conversations,
the NGB application, the demo), but **no club pays before gate 3 holds.**

**Exit criteria (all three are hard gates; 1–2 gate later phases, 3 gates the first paid contract).**
1. **Commercial-readiness gate:** *a club can sign up, pay, and publish with zero founder
   involvement.* No scaling work (P3/P4/P5) starts until this holds.
2. **Traction gate:** *≥10 clubs paying annually* before any new sport (P3). If the wedge
   stalls below ~50 clubs over time, that is a retention/PMF problem to fix — **not** a
   signal to add sports.
3. **Compliance-readiness ("lawful-to-sell") gate — added 2026-06-12:** *no paid
   contract before* versioned Terms + Privacy Notice are live and accepted at signup,
   the club DPA exists, ICO registration is done, the minors' consent gate (PC.12)
   enforces at generation/wall/publish, deletion + export (PC.13) work end-to-end,
   and password reset / breach notice / verified backups (PC.14) are in place.
   PC.4's pricing ledger and PC.6's funnel keep moving, but a quote may not convert
   to payment until this gate holds ([ADR-0015](adr/0015-compliance-readiness-sell-gate.md)).

### PC.1 — Self-serve signup + auth · ✅ **DONE**
The signup/login/session half of Appendix B **Step 7** (email+password, hashed; signed
session cookie), promoted from "alongside Phase 1" to the front of the queue. Self-hosted
deployments without billing env vars keep working (auth optional). *Ref: Appendix B Step 7.*
Shipped in PR #267 (signup/login/logout, bcrypt, signed session cookie, users.jsonl ledger); live-verified 2026-06-09. Auth stays optional when no accounts/billing are configured.

### PC.2 — Stripe billing + subscription lifecycle · ✅ **DONE (code-complete; awaits operator STRIPE_* keys)**
The billing half of Appendix B **Step 7**: Stripe Checkout, the Customer Portal, and a
signed webhook that drives plan state. Annual prepay is the default (see PC.4). Billing
routes honest-error (`503 "billing not configured"`) when `STRIPE_*` is unset, so the
free/self-host path is unaffected. *Ref: Appendix B Step 7.*
Shipped in PR #267 (Checkout, Customer Portal, signed webhook driving plan state). Routes honest-503 when STRIPE_* is unset so there is zero added running cost until the operator sets keys; live-verified 2026-06-09.

### PC.3 — True multi-tenancy: org → workspace · ✅ **DONE (2026-06-11)**
**The #1 architectural fix — shipped.** Single-instance-per-club rises linearly in
ops/support against fixed founder hours and collapses around 15–40 clubs; MediaHub now
runs **org → workspace isolation in one shared instance.** The 2026-06-09 escalation was
resolved exactly as governance required: the schema was **Council-pressure-tested**
(five advisors + anonymous peer review + chairman) and **operator-signed-off** (the
operator's direct instruction to complete Phase C), with the verdict recorded in
[`adr/0014-org-workspace-multitenancy-schema.md`](adr/0014-org-workspace-multitenancy-schema.md).
What shipped:

- **Per-org membership binding** (`web/tenancy.py` + `DATA_DIR/memberships.jsonl`,
  mirroring the `users.jsonl` ledger): an org with ≥1 ACTIVE membership is **bound** —
  members-only at every choke point (the `_active_profile_id()` resolver, set-active,
  the `/sign-in` picker, `/organisation` edits, deletion, run stamping) — while an org
  with no members behaves exactly as before (Step 14's standalone default), so pilot
  deployments and the existing anonymous fixtures are untouched.
- **Zero-founder-involvement first claim:** orgs created by a signed-in user are born
  bound to their creator; existing pilot orgs are pre-bound by a one-time operator
  invite (`invited` rows deliberately do not lock the org) that **auto-activates at
  signup**. Owners manage members at `/organisation/members` (pending invites by
  email — no email-sending infrastructure pretended).
- **ADR-0003 strengthened, never weakened:** `_can_access_run` is untouched for owned
  runs; the ownerless-legacy-run branch now refuses signed-in *foreign* accounts (the
  shared-instance blast-radius fix the Council made a precondition), while anonymous
  pilot and operator behaviour is preserved.
- **Pinned by a second invariant suite** — `tests/test_workspace_membership_invariant.py`
  sweeps the pinning surfaces the ADR-0003 test never covered (plus an ownerless-run
  route sweep under account mode), alongside `tests/test_tenancy.py` unit coverage.

*Ref: cross-cutting "Multi-tenancy: org → workspace"; Appendix B Step 14 (Step 14's
federation dashboards / template-push surfaces remain later-stage work — NOT pulled
forward).*

### PC.4 — Repricing & packaging (validate, don't assume) · 🔵 **IN PROGRESS (build complete 2026-06-11; evidence gate open)**
**Build side fully shipped; the gate is now a selling exercise.** Completion pass
2026-06-11: `/pricing` now actually **reads the PC.4 gate** instead of merely defaulting
to TBC — `commercial/wtp.py:public_list_price` returns a committed price only once ≥5
distinct clubs have paid annual, and the figure is *derived from the paid ledger* (the
highest tested price that cleared), never typed in. Until then the page shows "Pricing
TBC" even when Stripe price ids are configured. The revealed-WTP machinery
landed with PC.3 (same PR, [`adr/0014`](adr/0014-org-workspace-multitenancy-schema.md) §7):
a quote ledger (`commercial/wtp.py`, `DATA_DIR/commercial/wtp_quotes.jsonl`) records every
real annual price quoted per club; **per-quote Stripe Checkout** charges exactly the
quoted annual figure (`billing.create_quote_checkout_session`, ad-hoc `price_data`,
quote-id metadata); and the signed webhook records the payment **idempotently and
amount-verified** — a figure that doesn't match the quote is stored as a mismatch and
never counts. Both gates render live on the operator console (`/operator/commercial`):
the **≥5 clubs paid annual** pricing gate and the **≥10 paying clubs** traction gate.
`/pricing` still honestly shows "Pricing TBC" and stays that way until the pricing gate
is met. What remains is not code: quote real prices to real clubs and record what clears.
The original evidence-gate design (unchanged, still the rule):

- **Candidate hypothesis (to test, not to publish):** Club **£49–£99/mo billed
  annually**, Federation **£250+/mo**. Annual prepay is non-negotiable — SMB/volunteer
  churn runs 3–7%/mo and annual billing cuts it ~30–40% ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)).
- **Validation method:** treat the first ~10 hand-sold clubs (**PC.6**) as live price
  discovery. Quote a *real* annual price, vary it across clubs, and record accept/decline
  plus the price each club will actually pay — i.e. **revealed** WTP from real payments,
  not survey-stated WTP.
- **Gate (the >95%-confidence-correct step):** keep `/pricing` at the honest
  *"Pricing TBC"* it already shows until **≥5 clubs have paid an annual prepay at a tested
  price**; only then commit a public list price, set at the highest tested point that
  still cleared. Below that signal, any fixed list price is a guess.
- **Why this sequencing:** under-pricing is hard to reverse (re-pricing existing annual
  contracts upward churns volunteer buyers), and over-pricing with no buyers teaches
  nothing. Revealed WTP from real annual payments is the only evidence that de-risks the
  tier — and it costs nothing extra because the first ~10 sales happen anyway under PC.6.

**Sourced price comparators (anchor the hypothesis; every figure dated):**

| Comparator | Segment | Current price | What it anchors |
|---|---|---|---|
| **Gipper** (closest analog) | US K-12/college athletic depts | **$625 / $1,500 / $3,000 per year, annual-only** *(gipper.com/pricing, verified 2026-06-09)* | The institutional ceiling a results-graphics tool can reach *with a sales motion*. |
| **Predis.ai** (horizontal AI) | Any SMB / creator | **$19 / $40 / $212 per month** *(predis.ai/pricing, verified 2026-06-09)* | The buyer's mental price ceiling for "AI makes my posts." |
| **SwimTopia** (swim incumbent that touches money) | Swim clubs | ~$150–$699/yr annual *([`SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))* | What a club *will* pay when software is mission-critical (registration/billing) — MediaHub is not, yet. |
| **Canva Free** | Volunteer creator | **£0** | The free substitute every volunteer already has. |
| **Swim Wales affiliation** | Whole NGB relationship | £150/yr *([`SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))* | The volunteer treasurer's anchor for "what anything costs." |

Read together: the commodity floor (£0 Canva / ~$19/mo Predis) and the £150/yr NGB anchor
pull the Club tier **down**, while Gipper proves the institutional ceiling is far higher
($625–$3,000/yr) **but only for a schools/federation buyer with a budget, not a volunteer
club.** That gap is exactly why Route B (US schools) and PC.6 governing-body endorsement
carry the revenue weight, and why the Club tier must be set by revealed WTP rather than
assumed.

*Confidence: the **step** — gate the public price on ≥5 revealed annual payments before
publishing a list price — is >95%-confidence-correct; it is what a hard-nosed operator
would insist on. The **price levels themselves remain an unvalidated hypothesis** and are
flagged as such, not stated as fact. Ref: Appendix B Step 7 tiers (⚠️ unvalidated there);
[`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md).*

### PC.5 — Free-self-host tension · ✅ **RESOLVED (2026-06-09): hosted-only**
"Truly free, no hidden fees" self-host, as framed, hands power users a permanent
zero-revenue escape hatch. **Resolved 2026-06-09 (maintainer decision): hosted-SaaS
only — no customer self-host tier, free or capped.** Both earlier options — a capped
lead-gen tier (the default recommendation) and keeping true-free self-host — were
rejected in favour of hosted-only, the simplest principle that removes the zero-revenue
escape hatch entirely rather than half-closing it. The standing **no-hidden-fees /
truly-free self-host** product principle is retired; [`CLAUDE.md`](../CLAUDE.md) is the
authoritative statement. Recorded in
[adr/0011](adr/0011-commercial-reconcile-revenue-reality.md).

### PC.6 — Go-to-market / distribution · 🔵 **IN PROGRESS (tooling + NGB application drafted 2026-06-11; the selling is founder work)**
Distribution kills solo ventures, not product gaps. **Instrumented 2026-06-11:** the
warm-first funnel now has an operational home on the operator console
(`/operator/commercial`, backed by `commercial/pipeline.py`): a lead ledger by source
(warm_local / referral / meet_presence / cold), a **cold-share readout** that flags when
cold stops being the capped supplement, and a **referral-debt readout** listing every won
club still owing its **2 named intros** (the 5 → 10 compounding mechanism). The Swim
England approved-systems application is **drafted and submission-ready** at
[`commercial/SWIM_ENGLAND_API_APPLICATION.md`](commercial/SWIM_ENGLAND_API_APPLICATION.md)
(safeguarding/isolation evidence included), with its status tracked on the console
(PC.6(a) — the founder must actually submit it). The clubs themselves cannot be built in
code: the funnel below is the founder's motion, unchanged. The sub-track:
- **Governing-body channel — split into two mechanisms with very different evidence (reality-checked 2026-06-09):**
  - **(a) Official data-API access — REAL, dated, the concrete first NGB action.** Swim England launched a secure **approved-systems API** (announced 1 Oct 2025) letting approved platforms read official swim times/PBs directly from its databases; initial partners are the club-admin platforms Swim Club Manager and Swim Manager, and it explicitly invites *“commercial organisations interested in benefiting from the Swim England API”* to apply, with *“more to follow in 2026”* toward a “connected digital eco-system.” Applying for approved access is high-confidence-available and strengthens the deterministic data moat + credibility — but it grants **data, not promotion.** *(>95% this step is correct/available; sourced in [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md).)*
  - **(b) Promotional NGB endorsement to hundreds of clubs — DOWN-WEIGHTED to speculative.** No evidence any NGB promotes a third-party *content* tool to its member clubs. Swim England’s partner slots are **category-exclusive and already held** (SportsEngine = “preferred technology supplier” for swim schools; GoCardless = “Official Payments Partner”); the corporate-partner tier (Speedo, Sport England, SportsHotels) is sponsorship-based and slow. So “one deal reaches hundreds of clubs” is a *possibility, not the assumed highest-leverage channel.* **Threshold: if no NGB/region will pilot or promote after ~6 months, treat it as speculative and lean on direct + word-of-mouth.** This re-weighting reinforces **Route C** — the incumbents who already hold the endorsement *and* the official data integration are the realistic distribution partners. *([adr/0012](adr/0012-ngb-distribution-channel-reality-check.md).)*
- **Hand-sell the first ~10 clubs yourself — the traction gate, designed as a warm-first sequence (expanded + evidence-banded 2026-06-09).** This is *the* Phase C exit gate, not a growth tactic, and it is now the **de-facto primary channel** after the promotional-endorsement down-weight (PC.6(b) / ADR-0012). The base rates say the gate is reached by **manufactured warmth + referral chains, not cold broadcast**:
  - **(i) Local-warm base first (Swansea / South-East Wales).** The founder is locally embedded; Swim Wales has ~80–90 affiliated clubs (~11,000 members) — a tight regional network. Warm / in-person founder-led sales convert at **~30–50%** vs **~2–5%** for cold. *Win the first ~3–5 paying clubs here, high-touch, in person.* `[Founder-led sales benchmark — ESTIMATE; warm 30–50% vs cold 2–5%.]`
  - **(ii) Referral engine on every signed club.** Coaches and volunteers know each other across county squads and meets. In SaaS, **20–50% of new customers come from referral / word-of-mouth** (≈65% of B2B new business; referred customers ~37% higher retention) — *amplified* in a community this tight. Ask each signed club for **2 named intros** to peer clubs; warm-intro close stays in the 30–50% band. *This is the mechanism that compounds 5 → 10.* `[SaaS referral benchmark — ESTIMATE.]`
  - **(iii) Meet / event presence as warmth-manufacture.** County and regional meets are where the community physically gathers; producing real branded output for host / visiting clubs turns strangers into warm leads — it is not cold outreach.
  - **(iv) Cold outreach = a capped supplement, never the path to the gate.** The public Swim England (~1,200+ clubs) and Swim Wales club directories make contacts reachable, but the honest funnel for a brand-new, unproven tool sold to a no-budget volunteer buyer is brutal: cold reply **~2–5%** × reply→meeting **~30–50%** × meeting→paid **~15–30%** ≈ **~0.3–1.0% cold-to-paid.** Reaching 10 clubs cold would need **~1,000–3,000 quality contacts** — not achievable solo at quality. *Use cold only to book a handful of discovery calls; do not plan the gate around it.* `[Blended from cold-email + founder-led benchmarks — ESTIMATE.]`
  - **Honest funnel to the gate:** ~5 local-warm + ~5 referral; cold supplements top-of-funnel only. **Realistic timeline ~3–6+ months** to 10 paying clubs given seasonal calendars, volunteer decision-making and no standing budget line (founder-led SaaS cycles run 4–8 weeks for *budgeted* buyers; volunteer clubs are slower). `[ESTIMATE — flagged, not a commitment.]`
  - **Confidence split (the >95% discipline):** the *design* — warm + referral over cold broadcast — is **>95%-confidence-correct** on the cited base rates; the *outcome* (10 paying clubs in N months at price X) is **unproven and IS the validation** (it also closes the PC.4 willingness-to-pay gap). Do not conflate the two. Sourced in [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) (Evidence refresh cycle 4).
- **Rebalance build vs. sell** — stop adding capability surface; manufacture pipeline.

### PC.7 — Instant try-before-signup demo · ✅ **DONE (2026-06-11)**
**The sales motion's sharpest tool — shipped as specced.** PC.6's warm-first
hand-sell needs a shareable magic moment, and the June 2026 competitive pass verified
nobody can copy this demo — no competitor ingests a results file at all. *(Ideas
research #1 — [`research/PRODUCT_IDEAS_2026-06.md`](research/PRODUCT_IDEAS_2026-06.md).)*
What shipped:
- **Public `/try` flow** (no account, org-gate-exempt): upload a results file — or one
  click on the bundled `samples/MISM-2024-Results.pdf` — answer one question ("which
  club is yours?", parsed from the file), and the normal pipeline runs into a
  watermarked top-≤3-card preview with deterministic brand captions and the same
  "why this card" explainer the product shows (honest error text when no AI provider).
- **Demo restrictions:** runs are stamped to the sandboxed, unbound `demo-try` org
  (`web/demo_try.py:ensure_demo_profile`); `pb_discovery` web-verification is forced
  off (`fetch_pbs=False` — no third-party calls on unauthenticated traffic); every
  card renders through the new `watermark_text` overlay layer in
  `graphic_renderer/render.py` (a repeated diagonal stamp injected above every layout
  family).
- **Caps + isolation + self-cleaning:** per-IP and global daily caps
  (`MEDIAHUB_TRY_IP_DAILY_CAP` / `MEDIAHUB_TRY_GLOBAL_DAILY_CAP`, fail-closed),
  per-browser-session run visibility (one visitor can never open another's demo run,
  and demo routes 404 for any non-demo-org run), and a daily `demo_sweep` scheduler
  task deleting demo runs older than 24h. `MEDIAHUB_TRY_DEMO=0` switches the whole
  surface off.
- **Conversion carry:** the signup CTA rides the preview, and a signed-in club can
  claim the run (`POST /try/<run_id>/claim`) — it re-stamps to their org, leaves the
  sandbox and the sweep's reach, and opens in their review queue.
Pinned by `tests/test_try_demo.py` (caps, sandbox isolation, demo restrictions,
claim, sweep).

### PC.8 — Sponsor manager + sponsor exposure reports · ✅ **DONE (2026-06-11)**
**Makes the subscription revenue-positive for the club — direct PC.4 leverage.**
*(Idea #3.)* What shipped:
- **Sponsor registry** on `web/club_profile.py` (`ClubProfile.sponsors`: name, logo
  as a media-library asset reference, tier, active window, website) with a `/sponsors`
  workspace page to add/remove sponsors and pick the logo from the org's media
  library. The legacy single `sponsor_name` field stays a fallback — pre-PC.8
  profiles render exactly as before (sponsor only on the dedicated Sponsor Variant).
- **Deterministic rotation** (`club_platform/sponsors.py:sponsor_for_card`): the
  (run, card) identity seeds which active sponsor's slot a card carries — sha256
  rotation in the `auto_variation_seed_for` mould, so stills, motion, and re-renders
  agree. Wired into the standard create-graphic path (single render + Tier B
  candidate pool) and the sponsor-variant surface; the sponsor's logo rides the
  renderer's sponsor strip (`render_brief(sponsor_logo_path=…)`).
- **Exposure ledger + monthly report:** every sponsor-stamped render appends
  idempotently to `DATA_DIR/sponsors/<org>__exposure.jsonl`; `/sponsors/report`
  joins it with `workflow` approval states and `publishing/posting_log.py` into a
  branded, downloadable per-sponsor monthly report (cards carried / approved /
  posted / publish attempts, per run). Reach lands later with W.14 phase 2; email
  delivery with P4.5.
Pinned by `tests/test_sponsors.py` (registry, windows, rotation determinism, legacy
fallback, ledger idempotency, report arithmetic, route flows, and the
no-behaviour-change guarantee for legacy profiles).

### PC.9 — In-product referral engine · ❌ **NOT STARTED**
**Runs PC.6's compounding mechanism (2 named intros per signed club) inside the
product instead of operator ledgers.** *(Idea #4.)* **Build:** referral codes per
org; signup accepts a code and records the lead in `commercial/pipeline.py` with
source=referral; the reward (a free month as a Stripe coupon via `web/billing.py`)
auto-grants when the referred club's first annual payment lands amount-verified in
`commercial/wtp.py` (the idempotent webhook hook already exists); the
referral-debt readout on `/operator/commercial` switches from manual entries to
live code-tracked state. **Exit:** a signed club has a shareable code; a paid
referral auto-grants the reward and updates the funnel ledger with zero operator
typing.

### PC.10 — Public club achievements page + website embed · ✅ **DONE (2026-06-11)**
**A zero-gating distribution surface and a standing referral advert.** *(Idea #2.)*
What shipped:
- **Public read-only surfaces** (`web/public_wall.py` + routes): `/wall/<token>`
  (hosted celebration page), `/wall/<token>/embed` (iframe-ready), per-club
  `/wall/<token>/feed.rss` + `/feed.json`, and the card-image route — all keyed by
  an unguessable per-org token, all with cache headers, all carrying the
  "powered by MediaHub" badge into the signup funnel. First-party Flask; no
  platform review anywhere.
- **Approved-only, side-effect-free:** pages read `workflow.CardStatus` APPROVED
  (and POSTED — an approved card that has since published) and serve only
  already-rendered PNGs with result-grounded alt text; QUEUE/EDITED/REJECTED never
  appear, and the public reader never mutates anything (no caption-memory capture).
- **Opt-in + structural revocation:** the `/public-wall` workspace page switches the
  wall on (token minted) and off (**token cleared** — the old URL 404s, not an "off"
  page).
- **Safeguarding-conservative until W.2:** initials-only display toggle (default ON)
  applied to all wall text and alt text, plus per-card hide/show
  (`public_wall_excluded_cards`).
- **ADR-0003 holds:** the token scopes exactly one org — wall queries are pinned to
  the org's own runs, the run JSON's owner is re-checked, and a cross-tenant card
  fetch 404s.
Pinned by `tests/test_public_wall.py` (token resolution, approved-only, initials,
exclusions, revocation, feeds, and cross-tenant isolation).

### PC.11 — Legal & privacy pack · ❌ **NOT STARTED** · *(sell gate — ADR-0015)*
**The contractual minimum to take a club's money.** MediaHub is a **processor**
for clubs (the controllers) over personal data that is largely **children's** —
names, ages, race performance, photos — and today there is no Terms of Service,
no Privacy Notice, no DPA, and signup records no acceptance of anything.
**Build:**
- Public **Terms of Service** + **Privacy Notice** routes (e.g. `/legal/terms`,
  `/legal/privacy` — the existing `/privacy` data-inventory tool keeps its URL),
  versioned documents stored in-repo; signup requires an explicit acceptance
  checkbox and records `{terms_version, accepted_at}` in the `users.jsonl`
  ledger; material changes force re-acceptance at next login.
- A club-facing **Data Processing Agreement** (UK GDPR Art. 28 processor terms,
  minors' data explicitly in scope) presented to the org owner at org creation /
  first paid quote, acceptance recorded per org.
- A published **subprocessor register** with transfer mechanisms, kept truthful
  against the dependency register: Render (hosting + disk), Stripe (payments),
  Google Gemini + Anthropic (LLM — athlete names/results ride in prompts),
  Buffer (when scheduled), Replicate/PhotoRoom (opt-in cutouts), the TTS
  provider when voiceover is on. A guard test pins the register against the
  env-flag surface so a new provider can't ship undisclosed.
- **Founder (non-code) checklist, tracked on `/operator/commercial`:** ICO
  registration (data-protection fee), and a professional review of the three
  documents before the first paid contract — drafts can be assembled in-repo,
  but sign-off is a human act.
**Exit:** an account cannot be created without recorded acceptance of a
versioned ToS + Privacy Notice; an org owner has a recorded DPA acceptance;
the subprocessor page renders and its guard test is green; ICO registration is
logged on the operator console.

### PC.12 — Minors' consent & safeguarding gate · ❌ **NOT STARTED** · *(sell gate — W.2 promoted 2026-06-12)*
**W.2 stops being optional the day money changes hands.** The product's core
output is *publishing children's achievements*; Swim England's Social Media
Good Club Guide expects photo-consent handling, the drafted NGB application
already cites safeguarding evidence, and the public wall (PC.10) currently
leans on an initials-only default rather than recorded consent. **Build:** ship
**W.2** (per-athlete consent registry — photo OK / full name OK / initials-only /
do-not-feature; most-restrictive default; CSV import; enforced deterministically
at generation, in `media_library/selector.py` photo scoring, on the public wall,
and as a publish-gate check; welfare-officer export; audited changes). A
name-keyed minimal ledger is acceptable for this gate if W.1's full athlete
registry hasn't landed; it migrates onto the W.1 spine when that ships. Plus a
documented **Children's-Code (Age Appropriate Design) pass** over the public
surfaces (`/wall`, embed, RSS/JSON feeds, `/try`). **Exit:** a card for a
no-consent athlete cannot render a name/photo and cannot pass the gate or
appear on the wall; the review UI explains why; the Children's-Code pass is
recorded; the NGB application's safeguarding claims are all true in code.

### PC.13 — Data lifecycle & rights · ❌ **NOT STARTED** · *(sell gate — ADR-0015)*
**Deletion, export, retention — the data-subject-rights plumbing a controller
club will ask its processor for.** Today `/privacy` deletes individual runs,
demo runs sweep at 24h — and that's the whole story: no account deletion, no
org deletion, no export, no retention schedule. **Build:**
- **Self-serve account deletion** (user row + memberships) and **org deletion**
  cascading runs, media assets, content packs, wall token, sponsor/exposure
  ledgers, consent registry — with the Stripe customer handled per the DPA
  (financial records have their own statutory retention).
- **Org-level data export** (takeout ZIP: runs JSON, media, captions, consent
  state, audit log) — serves SARs and portability in one mechanism.
- A documented **retention schedule** (runs, uploads, media, logs, audit
  trails, demo runs, deleted-org grace window) published in the Privacy Notice
  and enforced by scheduler jobs where automatic.
**Exit:** a club owner can delete their org or export everything it holds
without founder involvement; deletion verifiably removes the data from
`DATA_DIR` (pinned by tests under the ADR-0003/0014 isolation invariants);
the retention schedule in the Privacy Notice matches what the code does.

### PC.14 — Operational trust pack · ❌ **NOT STARTED** · *(sell gate — ADR-0015)*
**The boring things a paying customer silently assumes.** Found missing in the
2026-06-12 audit: there is **no transactional email at all** (so no password
reset — a locked-out volunteer is locked out forever; PC.3's member invites
never send; a breach could not be notified), **no backup story** beyond the
single 1 GB Render disk that holds `users.jsonl`, the payment/WTP ledgers and
every run, and no support or incident path. **Build:**
- **Transactional-email seam** (Resend-style HTTP API behind an env key,
  honest-503 unconfigured — pulls P4.5's seam forward without the digest
  product): password reset (signed expiring token), email verification,
  member-invite delivery, and an operator "notify all users" path for breach
  notification (the ICO's 72-hour clock needs a working channel, not a plan to
  build one).
- **Backups + restore drill:** confirm Render disk-snapshot coverage, add a
  scheduled off-site `DATA_DIR` backup (ledgers + `data.db` + runs) with the
  key material handled per the DPA, and a *documented, rehearsed* restore —
  an unrestored backup is a hypothesis.
- **Support + incident runbook:** a real support contact surfaced in-product
  and in the ToS; a short incident/breach runbook (detect → contain → assess →
  notify ICO/clubs) checked into `docs/`; `/healthz` uptime already exists —
  surface it honestly to customers.
- **Billing hygiene:** decide VAT handling (Stripe Tax vs below-threshold
  statement), and ensure Checkout emits an invoice/receipt a volunteer
  treasurer can put through club accounts.
**Exit:** a user can reset their password unaided; an invite email actually
arrives; a restore from backup has been performed and documented; the support
contact and runbook exist; a test payment produces an expensable invoice.

**Building blocks.** Stripe (Checkout + Customer Portal + webhooks); the existing
`DATA_DIR` persistence (a `users.jsonl`-style ledger per Step 7 — no SQLAlchemy); the
shipped cross-tenant isolation invariant (ADR-0003) as the multi-tenancy seed; Postiz /
Mixpost org→workspace schemas as *reference only* over a network boundary (never embed
AGPL — [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).

**Dependencies.** Upstream of **P3 / P4 / P5** — those are gated behind PC's exit
criteria. Independent of P0–P2 capability work, which may continue *to the bar needed to
make the swim wedge sellable* (see P1.4 and "Immediate next moves") but **not ahead of
billing**.

### Strategy notes — the three credible £1M+ routes (context, *not* build items)

These are **not roadmap work** — they are the only routes the diligence considers
arithmetically credible for £1M+, recorded so the expansion phases are sequenced with
revenue in mind. Each carries the report's confidence band. **All figures are estimates.**

- **Route A — Multi-sport UK grassroots** (broadest TAM, weakest moat). ~151,000 UK
  sports clubs; even a fraction at £49–£99/mo annual reaches £1M. *Risk: per-sport data
  integrations are non-transferable engineering, head-on vs Canva/Predis. Confidence of
  £1M: ~15–20%.* → sequences **P3**.
- **Route B — US schools/colleges** (highest WTP, proven by Gipper/FanWord). Reposition
  as results-driven achievement graphics at $625–$3,000/yr. *Needs US sales presence;
  strongest math plus a wedge incumbents lack. Confidence of £1M solo: <15%; higher with
  a US partner/hire.*
- **Route C — Content/integration layer for swim-data incumbents** (de-risks
  distribution). License/sell the content engine to SwimTopia/TeamUnify rather than fight
  them. *Trades upside for survival probability; possibly the most realistic high-value
  exit. Confidence it beats going direct: ~50/50.*

**Highest-leverage combination:** governing-body **data-API access + incumbent integration (Route C)** (PC.6) for *distribution* +
US-schools repositioning (Route B) for *revenue*.

---

## Phase W — Deepen the swimming wedge · W · ❌ **NOT STARTED (selectable backlog, added 2026-06-11)**

**Goal.** Make the swim wedge easier to sell, safer to run, and richer in content
moments — without waiting for, or blocking, the P3/P4/P5 gates. Every item is
deterministic-engine or workflow work on existing seams; none adds a mandatory paid
dependency; AI-judgement surfaces ride `media_ai.llm`/`ai_core.llm` with honest
errors, per the standing rules.

**Provenance.** The June 2026 ideas research pass —
[`research/PRODUCT_IDEAS_2026-06.md`](research/PRODUCT_IDEAS_2026-06.md) (22
researched candidates with competitive, data-ecosystem and platform-feasibility
sourcing). The sell-side four became **PC.7–PC.10**; the distribution slice became
**P4.5/P4.6** plus build detail folded into **P4.1/P4.2/P4.4**; the remaining
fourteen live here. Each item cites its idea number in that doc.

**Gating position (read carefully).** Phase W sits **outside** the Phase C exit
gates — these are wedge-sellability items in exactly the class PC.6's dependency
note already permits ("capability work … *to the bar needed to make the swim wedge
sellable*, but **not ahead of billing**"). The discipline: pick an item **only when
it unblocks a sale, a pilot, the NGB application, or a known churn risk** — never
as polish for its own sake, and never as a reason to defer the selling motion. No
fixed phase exit; every item carries its own. Recommended first picks: **W.1 → W.2**
(the consent story committees ask about — and W.2 is no longer merely recommended:
it was **promoted into the PC.12 sell gate on 2026-06-12**), **W.4** (cheap,
parent-delighting), and **W.10** (demo-day ingestion robustness).

### W.1 — Athlete registry + milestone detectors · ❌ **NOT STARTED**
**The data spine for W.2/W.3/W.8 — and per-athlete celebration at scale, which the
competitive pass verified nobody automates.** Today there is no athlete identity
across runs: names are per-run strings (`media_library` linking included), so
milestones, records, consent and season totals have nothing durable to hang on, and
the KNOWN_ISSUES twins/siblings cross-match has no fix surface. *(Idea #9.)*
**Build:** a workspace-scoped athlete table in `data.db` (canonical name +
variants, optional ASA number, birth year, active flag), back-filled from
`runs_v4` snapshots; a review-time "same swimmer?" merge UI whose decisions
persist; deterministic milestone detectors joining
`recognition_swim/achievements/` — first-ever event, Nth race (25/50/100), first
gala, PB-in-every-event, comeback (extending the existing `ReturnToFormDetector`
seam). **No LLM anywhere in identity or milestone logic.** Multi-tenant: rows are
org-scoped under the ADR-0003/ADR-0014 invariants. **Exit:** the same swimmer is
one entity across ≥2 runs; a 50th-race card generates with a provenance trail;
merge decisions persist and are auditable.

### W.2 — Consent & safeguarding manager · ❌ **NOT STARTED** *(depends on W.1; **promoted 2026-06-12 — load-bearing for the PC.12 sell gate**, no longer optional: see Phase C / ADR-0015. PC.12 permits a name-keyed minimal ledger ahead of W.1, migrating onto the registry when it lands)*
**The committee objection-killer and the strongest §4 evidence for the Swim England
application.** Swim England's own Social Media Good Club Guide expects photo-consent
handling; the competitive pass found **no content tool encodes minors' rules**; the
code today has only `media_assets.safe_for_minors` — no consent ledger. *(Idea #16.)*
**Build:** a per-athlete consent registry on the W.1 spine — photo OK / name OK /
initials-only / do-not-feature; CSV import from the club's existing records; default
**most-restrictive when unknown**. Enforced twice, deterministically: at generation
(initials-only rendering; photo suppression in `media_library/selector.py` scoring)
and as a new publish-gate check beside the existing safeguarding rule in
`publishing/publish_gate.py`. Review UI shows "blocked: no consent on file"; a
welfare-officer export lists consent state; every consent change is audited.
**Exit:** a card for a no-consent athlete cannot render a name/photo and cannot
pass the gate; the review page explains why; pinned by tests alongside the
ADR-0003 invariant suites.

### W.3 — Club records engine + "NEW CLUB RECORD" cards · ❌ **NOT STARTED**
**The highest-emotion moment a club posts, and no detector exists for it**
([`DETECTOR_INVENTORY.md`](DETECTOR_INVENTORY.md)); admin incumbents *display*
records but never generate content from them. *(Idea #10.)* **Build:** a
per-workspace records store (event × course × age-group × gender) seeded by CSV
import of the club's records sheet — a strong onboarding hook — and updated from
ingested meets **on approval only**; a deterministic `ClubRecordDetector` in
`recognition_swim/achievements/club_record.py` ranked **above** PB; "approaching
the record" as a planner signal; a records-wall block on the PC.10 public page.
**Exit:** importing a records sheet then uploading a record-breaking meet yields a
ranked NEW CLUB RECORD card carrying old mark, new mark and provenance; the table
updates only when the card is approved.

### W.4 — Season-current qualifying-time packs · ❌ **NOT STARTED**
**"Qualified for Counties!" is a parent-shareable trigger plain PB detection
misses — and the detector already exists** (V5 `QualifyingTimeDetector`;
`ClubProfile.important_standards` is already a field). What's missing is **data**:
county/regional/national QTs are published as public seasonal PDFs; times are
facts (low licensing risk, cite the source PDF); third-party aggregators prove
demand. *(Idea #11.)* **Build:** versioned curated datasets under
`data/standards/<season>/` with per-table provenance (source PDF URL + curation
date) and a documented seasonal refresh runbook; club picks its county/region in
settings; wire the detector + a dedicated card archetype; later add USA Swimming
motivational times (official free PDFs, fixed 4-year cycle) for US expansion.
**Exit:** a club selects its standards and a qualifying swim yields a "qualified"
card naming the standard and its source.

### W.5 — LENEX (.lef/.lxf) ingestion · ❌ **NOT STARTED**
**The highest-value UK ingestion add** (June 2026 data-ecosystem pass): LENEX 3.0
is the openly licensed XML interchange format ("free of charge and without
restriction"), it is what SportSystems exports, and Swim England's results
uploader accepts exactly Hy-Tek + LENEX — so HY3 + LENEX covers the licensed-meet
pipeline upstream of the NGB, and unlocks European clubs later. *(Idea #13.)*
**Build:** `interpreter/lenex_parser.py` for the results + entries elements per
the Lenex 3.0 spec; `.lxf` (zipped `.lef`) through the existing bomb-safe unzip
(`interpreter/_zip_safety.py`); register in `interpreter/ingest.py` format
detection; normalise to the same canonical shape as HY3/SDIF; fixtures = the four
official spec example files. Deterministic throughout. **Exit:** a SportSystems
`.lxf` export runs the full pipeline with output parity to the HY3 path on the
same meet.

### W.6 — Data-driven meet previews from entry files · ❌ **NOT STARTED**
**Doubles content per meet (before + after) from files clubs already hold.** The
`event_preview` type exists but is form-based — a human types everything; the
P1.3 planner already wants upcoming-event signals. *(Idea #12.)* **Build:**
entry-shaped ingestion — Hy-Tek entry files, LENEX `entries` (free with W.5), PDF
psych sheets through the existing extractor with needs-review flagging — mapped to
a preview pack (who's entered, events, sessions, squad-size stat) that feeds
`club_platform` event_preview generation instead of the form, plus a planner
signal for the meet date. Ambiguous rows flagged, never guessed. **Exit:**
uploading an entry file yields an approvable "good luck this weekend" pack with
zero typing.

### W.7 — Live meet mode (watch a results URL mid-gala) · ❌ **NOT STARTED**
**Clubs are told to post PBs on event day; nobody can without a volunteer glued to
a laptop — and it is the most theatrical hand-sell demo available.** Ingestion
today is single-shot. The ToS-clean path is verified: Hy-Tek "Real-Time Results"
static HTML on the **host club's own site** (with consent) and
results.swimming.org meet pages; **Meet Mobile and rankings scraping stay
prohibited** (the PC.6/ADR-0012 posture is unchanged). *(Idea #14.)* **Build:** a
watch = stored URL + polite poll interval as a `scheduler/` task type
(`results_fetch` tier-A fetch; the robots-respecting crawl exists); diff per poll
with per-swim dedupe keys so a swim cards exactly once; new results → recognition
→ cards **queued for approval** through the autonomy queue (which structurally
cannot publish); ntfy push ("3 new PBs in session 2") via `notify/channels.py`
click-URL straight into review (pairs with W.9); watches auto-expire at meet end.
**Exit:** a watched live meet produces incremental queued cards within one poll
interval, with zero duplicates and zero auto-publishing, and the watch stops
itself.

### W.8 — Season wraps / monthly recap packs · ❌ **NOT STARTED**
**Retention work that lands exactly when annual renewal (PC.4's model) comes due**
— accumulated history becomes switching cost, Wrapped-style. The v7.3
weekend-in-numbers pattern exists per-run; this generalises it across the season.
*(Idea #15.)* **Build:** deterministic aggregation across a workspace's history
(`runs_v4` snapshots + `data.db`): total PBs, medals, records (W.3), debuts and
milestones (W.1), biggest improver, busiest swimmer; a recap pack type + reel
sequence on the existing still/motion engines; the scheduler drafts it monthly
through the autonomy queue for approval; a configurable season-end wrap. **Exit:**
one click (or the monthly draft) yields an approvable "month in numbers" pack
consistent with stored history.

### W.9 — Magic-link mobile approvals · ❌ **NOT STARTED**
**The approval bottleneck is the head coach's Sunday evening, not the software** —
and a volunteer-shaped approval loop is unclaimed by competitors (enterprise tools
or generic design suites only). Also closes the KNOWN_ISSUES unsigned-run-id
defence-in-depth gap. *(Idea #17.)* **Build:** HMAC-signed, expiring, run-scoped
tokens (`itsdangerous`, keyed off `MEDIAHUB_SECRET_KEY`) minted when a pack is
ready; delivered by ntfy/webhook (click-URL support already in
`notify/channels.py`; email joins via P4.5); a mobile-first lite review surface —
approve / edit caption / reject only — driving the same `workflow.CardStatus`
transitions with full audit (who approved, via which token); tokens revocable per
run; org-bound, no account needed. **Exit:** an approver on a phone clears a pack
end-to-end from the link; expiry/revocation enforced; audit parity with logged-in
approval.

### W.10 — OCR fallback for scanned PDFs · ❌ **NOT STARTED**
**A failed first upload during a hand-sell demo is a lost club.** KNOWN_ISSUES:
low-DPI scans parse to gibberish; the interpreter already marks image uploads
"needs OCR" but no OCR exists — and committee secretaries *will* upload phone
photos of printouts. *(Idea #18.)* **Build:** an OCR step (Tesseract in the Docker
image, or the RapidOCR wheel) behind the interpreter's existing low-confidence
path for image-only PDFs and photos; per-row confidence carried through to the
existing flag-for-review surface — uncertain rows are flagged, never silently
guessed; `interpreting`-phase logs record OCR engagement. Deterministic.
**Exit:** a phone photo of a printed results sheet produces parsed rows with
uncertainty flags instead of gibberish or a dead end.

### W.11 — Result-grounded alt-text on every export · ❌ **NOT STARTED**
**KNOWN_ISSUES: exports carry no alt text.** Cards are data-dense graphics, so the
alt text must restate the result ("Maya Patel, 50m freestyle, 31.24 — a 0.8s PB at
the Swansea Spring Open"), under ~125 chars, human-reviewable — which the approval
gate already provides. *(Idea #19.)* **Build:** extend the caption-generation
contract with an `alt_text` field produced in the **same** `media_ai.llm` call
(zero added latency/cost; honest-error when no provider — no heuristic fallback);
thread through the pack ZIP, the newsletter HTML, the PC.10 page/embed (`alt=`
attributes) and every publish payload; editable in review beside the caption.
**Exit:** every exported or published card carries result-grounded alt text the
approver saw.

### W.12 — PB certificates + A4 noticeboard posters · ❌ **NOT STARTED**
**Parents currently DIY this with generic certificate templates — the competitive
pass surfaced printable certificates as the existing "solution" to per-child
celebration.** A branded certificate carrying the verified time is the artifact
families print and frame; zero platform dependency. *(Idea #20.)* **Build:** A4
print layouts in `graphic_renderer/layouts/` (Playwright prints PDF natively;
`reportlab` stays optional); a per-swimmer certificate batch export on the pack
(ZIP of PDFs) + an A4/A3 weekend-recap poster for the leisure-centre noticeboard;
BrandKit tokens reused so print matches cards; W.2 consent honoured in batch
exports. **Exit:** one click exports print-ready branded certificates for every
approved achievement in a run.

### W.13 — Bilingual captions (Welsh first) · ❌ **NOT STARTED**
**The first ten clubs are being hand-sold in Swansea / South-East Wales (PC.6) —
bilingual posting is locally resonant and no US competitor will ever bother.**
Marginal cost ≈ 0 on the existing Gemini call (tone-preserving in-pipeline
translation; dedicated MT APIs only matter at scale). *(Idea #21.)* **Build:** a
per-workspace language setting on `ClubProfile` (en / cy / bilingual); caption
prompt extension producing both variants with swim terminology correct; review UI
shows and edits both; publish-gate platform-length checks account for the doubled
text; the same seam serves any future locale. Honest-error when no provider — no
machine-translation heuristics. **Exit:** a bilingual club approves Cymraeg +
English captions in one pass and the gate's length checks hold.

### W.14 — Engagement feedback loop · ❌ **NOT STARTED** *(phase 2 needs P4.2)*
**The compounding intelligence-layer moat: every approval teaches the next plan —
template tools cannot replicate it.** *(Idea #22.)* **Build, phase 1 (no external
APIs):** record per-club which tone variant / archetype is approved, edited or
rejected at the existing approval seam; feed the caption few-shot store and
`memory/`; surface "this club prefers…" in the planner's explainable reasons;
`observability/` counters. **Phase 2 (after P4.2 connectors):** a scheduled
per-post metrics pull — IG `views`/`reach`/`saved`/`shares` under the
**post-Apr-2025 metric names** (`impressions` is deprecated; Page-insights
deprecations continue through 2026) — into a per-club format ranking ("carousels
earn saves here; reels earn reach"), feeding plan ranking **deterministically**
(the LLM never ranks). **Exit (phase 1):** the planner's reasons cite the club's
own approval history. **Exit (phase 2):** per-post metrics inform format choice
with provenance.

**Building blocks.** Existing seams only: `recognition_swim/achievements/` + the
detector bus, `interpreter/` + `_zip_safety`, `results_fetch/` + `scheduler/` +
`notify/`, `workflow/` + the P2.3 publish gate, `graphic_renderer/`,
`media_ai.llm`/`ai_core.llm`, `memory/`, `observability/`. New paid dependencies:
none (Tesseract/RapidOCR are open-source; everything else is already in-tree).

**Dependencies.** Independent of the P3/P4/P5 gates. W.2 and W.8 lean on W.1; W.6
is cheaper after W.5; W.12 and PC.10 should honour W.2 once it exists; W.14
phase 2 waits for P4.2. Feeds **PC.4/PC.6** (sellability, the NGB application's
safeguarding evidence) and **P3** (W.5/W.10 broaden ingestion patterns the
multi-sport spokes will reuse).

---

## Phase 3 — Broaden ingestion spokes · P3 · ❌ **NOT STARTED**

**Goal.** Ingest beyond swimming and normalise every spoke to the canonical schema,
so a second sport produces real content end-to-end.

**Exit criterion.** **≥1 non-swimming sport** produces real content end-to-end from a
real data source (football via openfootball, or basketball via nba_api), with a
registered `recognition_<sport>` adapter and its sport profile wired in.

### P3.1 — Second-sport engine adapter · ❌ **NOT STARTED**
`recognition_football` or `recognition_basketball` + `register_sport(...)` (the seam
exists — [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)). Bind `engine_sport` in the profile.

### P3.2 — Sports-data API spokes · ❌ **NOT STARTED**
`nba_api`, `openfootball`, fixture generators; each normalised to `canonical.*`.

### P3.3 — Running/athletics parsers · ❌ **NOT STARTED**
Chip-timing CSV + client-side Garmin `FIT` parsing (the swim-data-analyser pattern).
This sport needs custom parsers — open-source coverage is sparse.

### P3.4 — Normalise all spokes to the canonical schema · ❌ **NOT STARTED**
Separate raw extraction from cleaned canonical data; flag ambiguous rows for review.

**Building blocks.** `swar/nba_api` (open, keyless — *verify*), `openfootball`
(**public domain**), `ndPPPhz/Fixture-Generator` (MIT). ⚠️ `statsbomb/open-data` is a
**non-OSS data agreement** (attribution / responsible use) — code-vs-data licence
split; use openfootball as the free default. ([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md))

**Dependencies.** Needs **P1** (sport profiles + taxonomy). Pairs with **P4** (new
sports → new audiences → more publishing targets).

---

## Phase 4 — Direct-to-platform publishing · P4 · ❌ **NOT STARTED**

**Goal.** Replace the paid Buffer dependency with direct platform adapters,
prioritising the genuinely-free targets.

**Exit criterion.** Posts publish via **direct APIs to ≥2 platforms including a
genuinely-free one** (Bluesky and/or Mastodon), with Buffer demoted to optional.

### P4.1 — Bluesky (AT Protocol) + Mastodon adapters · ❌ **NOT STARTED**
The free/open posting targets — build these first. **Build detail (June 2026
feasibility pass; ideas research #7):** `publishing/bluesky.py` (AT Protocol;
app-password or OAuth — **no app review or business verification exists at
all**) and `publishing/mastodon.py` (per-instance REST; apps register
programmatically), both beside `buffer.py`, both gated by the P2.3 publish gate
and writing `publishing/posting_log.py`; per-workspace account binding in
Settings; image + W.11 alt-text first, video where the instance allows. Each
adapter is days, not weeks — they also rehearse the connector pattern (connect →
gate → post → log → audit) before the Meta review lands, and they make the
autonomy story demonstrable end-to-end on a zero-risk network.

### P4.2 — Instagram Graph / Facebook / TikTok / YouTube adapters · ❌ **NOT STARTED**
Least-privilege per integration; human connects each account (no auto-connect).
**Platform API policy gates auto-posting (verified June 2026 — [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) cycle 5):** Instagram content-publishing needs a Business/Creator account + a connected Facebook Page + Meta **App Review** (~2–4 weeks/permission) + **Business Verification**; TikTok's *unaudited* Content-Posting client can post only **private (SELF_ONLY), ≤5 users/24h** until it passes an audit. This is *why* **P4.1 (Bluesky + Mastodon) ships first**, and these stay behind human approval and the audit timeline.
**Start the paperwork before the code (June 2026 pass; ideas research #8):** the
Meta Business Verification + App Review (`instagram_content_publish`,
`pages_manage_posts`, Threads scopes) costs $0 but burns **weeks of calendar
time** — the application can begin while this item stays unbuilt, so the clock
runs in parallel with Phase C instead of after it. What the code side needs when
it opens: a Pillow **JPEG export** path in `graphic_renderer` (the IG API is
JPEG-only), publicly URL-reachable media (already true), a "Connect Instagram"
flow, and `publishing/meta.py` behind an operator flag + the publish gate. Current
IG limits are workable: **100 API-published posts/24h per account, including
Reels, Stories and carousels** — and carousels (one card per swimmer per meet) are
the engagement/saves format in the 2025 35M-post benchmarks, so the adapter
should group packs as carousels by default. One Meta review covers Facebook Pages
+ Instagram (+ Threads scoped separately); **TikTok and YouTube stay deferred
until clubs demand them** (TikTok unaudited = private-only; YouTube's default
10k-unit quota ≈ 6 uploads/day across *all* tenants until audited).

### P4.3 — X adapter (budget pay-per-use) · ❌ **NOT STARTED**
X moved to pay-per-use (6 Feb 2026); treat as a paid, optional target.

### P4.4 — Demote Buffer to optional · ❌ **NOT STARTED**
Keep the Buffer path for those who want it; remove it from the critical path.
**Urgency re-graded (June 2026 research):** Buffer's classic developer API has
been **closed to new developers since 2019**, remaining third-party integrations
were **cut off on 1 Mar 2025**, and the 2026 beta API **lacks third-party OAuth**
— so the current connector (`publishing/buffer.py`, classic
`/1/updates/create.json`) runs on borrowed time and cannot onboard new clubs'
accounts under Buffer's new regime. "Demote Buffer" is therefore **resilience
work, not preference**: P4.1/P4.5/P4.6 are the replacement paths; keep the Buffer
path only while the legacy token still functions, and surface an honest error
the day it stops.

### P4.5 — Email digest delivery (the newsletter actually sends) · ❌ **NOT STARTED**
**The v7.3 grouped newsletter already builds (`/api/runs/<run_id>/newsletter`,
`content_pack/builder.py`) — nothing can send it.** Email needs no platform
review, clubs already run parent lists, and Gipper sells newsletters as a paid
tier; costs are trivial (Resend: free to 3k emails/mo, ~$20/mo for 50k ≈ 50 clubs
× 200 members weekly). *(Ideas research #5.)* **Build:** `publishing/email.py`
behind a provider seam (Resend first; honest-error unkeyed, per the P0.3/P0.4
doctrine — no silent paid dependency); a per-workspace member list (CSV import
with consent capture, one-click unsubscribe route + suppression list — GDPR:
unsubscribes honoured before any send); a weekly `scheduler/` job assembling
approved-card digests; the PC.8 sponsor slot and W.11 alt text in the template;
W.9 approval links ride the same channel. **Pull-forward candidate during
Phase C** at the maintainer's discretion — it is review-free and directly
sell-supporting; it sits in P4 for thematic fit, not because it needs the gate's
platform machinery. **Exit:** a club imports members and receives a weekly
digest of approved content; unsubscribes stick; unkeyed deployments honest-error.

### P4.6 — Telegram channel publishing (+ WhatsApp share stopgap) · ❌ **NOT STARTED**
**The best effort-to-value publish target found in the June 2026 feasibility
pass:** the Telegram Bot API is free with generous broadcast limits, needs no
review, and sends **PNG and MP4 natively** — note reels currently have **no
scheduled outlet anywhere** (the Buffer path takes a single image URL). WhatsApp
has **no official Channels API** and the Business Platform bills per template
message with verification friction, so the legitimate WhatsApp answer today is a
share affordance, not an API. *(Ideas research #6.)* **Build:**
`publishing/telegram.py` (per-workspace bot token + channel binding;
`sendPhoto`/`sendVideo` with caption + W.11 alt text) behind the publish gate +
posting log; a review-UI "share to WhatsApp" button (copy caption, download
media, open `wa.me`) as the stopgap for WhatsApp-centric UK clubs. Like P4.5, a
**pull-forward candidate during Phase C** — zero platform risk, and it proves
the full gate→post loop (including for autonomy demos) on a real channel.
**Exit:** an approved card *and* a reel both land in a connected Telegram channel
through the gate with full audit; the WhatsApp button works on mobile.

**Building blocks.** **Bluesky / Mastodon** (free/open) first; the **Telegram Bot
API** and a **Resend-seamed email channel** join the genuinely-free tier
(P4.5/P4.6); direct platform APIs.
**Postiz** adapters as a *reference implementation only* (**AGPL** — call over its
API or read the patterns; never embed — [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).

**Dependencies.** Needs **P2** (autonomy + guardrails govern what may auto-publish)
and **P0** (Buffer is a flagged, optional paid path).

---

## Phase 5 — Local-AI substitution everywhere · P5 · ❌ **NOT STARTED**

**Goal.** Give every AI call a zero-cost local path, completing the no-hidden-fees
guarantee.

**Exit criterion.** With **no cloud keys configured**, the full pipeline (caption,
cutout, voice, graphics, reels) runs **locally end-to-end** — honest-erroring only
where a local model is genuinely unavailable.

### P5.1 — Ollama LLM provider · ❌ **NOT STARTED**
A local backend behind the existing `ai_core.llm` interface — the zero-key default.
*Head start from P0.4:* both LLM wrappers already accept a keyless
OpenAI-compatible endpoint (`MEDIAHUB_LLM_ENDPOINTS=http://localhost:11434/v1`
reaches a running Ollama today); what remains is shipping/operating the model
runtime itself, model selection defaults, and the operator workflow.

### P5.2 — Piper TTS replaces edge-tts · ❌ **NOT STARTED**
Local neural TTS; drops the undocumented Edge cloud-endpoint dependency. The
provider slot is already registered (P0.4: `MEDIAHUB_TTS_PROVIDER=piper`
honest-errors until this lands) — P5.2 fills the slot with the real backend.

### P5.3 — whisper.cpp / faster-whisper ASR · ❌ **NOT STARTED**
Local transcription for reel captions / word-level burn-in. Must land behind a
provider seam — the P0.4 guard fails the build on any unslotted ASR import.

### P5.4 — Satori graphics fast-path · ❌ **NOT STARTED**
Lighter card rendering (~100× lighter than headless Chromium). A *performance*
play, not a licensing one — P0.1's shipped ffmpeg engine already removed the
Remotion requirement; this slots into the same `MEDIAHUB_REEL_ENGINE` seam
(the `satori` engine name is registered and honest-errors until it ships).

### P5.5 — rembg / MODNet cutout · ✅ **DONE**
Already the shipped default (rembg). MODNet is an optional higher-quality matting
alternative.

**Building blocks.** All **ADOPT-NOW**: Ollama (MIT), Piper (MIT), whisper.cpp /
faster-whisper (MIT), Satori (MPL-2.0), rembg (MIT), MODNet (Apache-2.0). ⚠️ Avoid
Coqui **XTTS** weights commercially (CPML, non-commercial) — Piper instead.

**Dependencies.** Set up by **P0 ✅** (the local-capable interfaces all exist —
P0.4). This phase **completes the no-hidden-fees promise** the whole roadmap is
built around.

---

## Phase 6 — Creative-suite breadth (our own versions, MediaHub-shaped) · P6 · ❌ **NOT STARTED (gated)**

**Goal.** Build **MediaHub's own first-party version of every content-creation
capability Canva and Adobe Express ship** — re-expressed through this product's
thesis (data in → meaningful, branded, approval-gated content out), never by
integrating their tools or becoming a blank-template shop. The evidence base is
two exhaustive competitor inventories checked in at
[`research/CANVA_FEATURE_INVENTORY_2026.md`](research/CANVA_FEATURE_INVENTORY_2026.md)
and
[`research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md`](research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md);
**every bullet in both** is mapped — feature by feature, with a completeness
index proving none is missed — in the long-form companion
[`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md) (added 2026-06-11,
maintainer instruction). The phase essay below is the summary; the companion
doc is the build depth.

**Gating & order.** Phase 6 sits behind the same two Phase C gates as P3/P4/P5
(zero-founder onboarding; ≥10 clubs paying annually). Within the phase, order
is **pull-driven** — build what paying clubs ask for first; the numbering is a
default sequence, not a promise. Standing rules hold everywhere: hosted-only
(ADR-0011), approval-first publishing + the P2.3 gate, the deterministic-engine
boundary, Gemini→Anthropic honest-error AI, self-hosted fonts, and the GWS /
9router exclusions. External services appear only as optional flag-gated
provider slots behind our own interfaces where first-party is impossible
(model hosting, platform APIs, print fulfilment, music rights).

**Exit criterion.** A club can run its **entire content life inside MediaHub**
— social, print, email, microsite, video, documents — without reaching for
Canva/Express; measured per-item (each P6 item carries its own exit in the
companion doc) and in aggregate by wedge clubs actually cancelling their Canva
habit.

### P6.1 — Smart format catalogue & format transformer · ❌
Every design type both products offer becomes a data-driven club `FormatSpec`
(certificates, posters, meet programmes, yearbooks, athlete one-pagers, season
calendars, carousels, memes, per-channel sizes…) on the existing
archetype/brief/renderer spine; `turn_into` v2 re-targets any approved design
to any format/size by re-layout, not scaling. *(Companion §P6.1.)*

### P6.2 — Conversational creative assistant & agentic editing · ❌
The club content copilot: create/edit/explain by chat (and voice), executed as
validated **design-spec patches** through `ai_core.ask_with_tools` — the agent
never paints pixels, every step auditable; Magic-Write-class text tools; org
assistant memory with inspect/delete. *(Companion §P6.2.)*

### P6.3 — Generative imagery & image-AI services · ❌
One `media_ai` image-provider seam (Gemini-first, honest errors) for generate /
edit / fill / expand / remove / subject-lift / text-lift / upscale /
style-match / mockups — scenery and fix-ups only, never fabricated results
data; provenance-stamped (P6.22). *(Companion §P6.3.)*

### P6.4 — Photo editor (deterministic recipes) · ❌
Non-destructive `EditRecipe`s on media-library assets: filters, adjustments,
crop/perspective/flip, crop-to-shape, frames/collages, blur brush (also the
safeguarding tool), pool-light auto-enhance, HEIC ingest; pure pixel maths,
selection maths untouched. *(Companion §P6.4.)*

### P6.5 — Video suite (footage path) · ❌
Phone clips → branded reels: EDL timeline over the shipped Remotion/FFmpeg
engines, ASR captions (P5.3 seam), **Clip-Maker-for-sport** (moment detection,
saliency reframe, caption burn-in), beat sync, browser screen/webcam recorders,
per-clip recipes; avatars only as a disclosed, explicitly-requested opt-in.
*(Companion §P6.5.)*

### P6.6 — Audio engine · ❌
Own licence-clean music/SFX pools with mood tags + a rights ledger
(fingerprint checks; chart-music rights only via a flag-gated slot), the TTS
seam grown into a voice layer (catalogue, params, athlete-name pronunciation
lexicon), denoise/levelling, ducking; voice cloning consent-gated and audited.
*(Companion §P6.6.)*

### P6.7 — Typography system & text effects · ❌
Curated **self-hosted** font catalogue + per-org uploads (licence-attested),
AI pairing with reasons, deterministic text-effect tokens (shadow/lift/hollow/
splice/echo/glitch/neon/curve/extrude/warp) policed by APCA, formatting depth,
data-bound dynamic text. *(Companion §P6.7.)*

### P6.8 — Elements, stock & drawing · ❌
Sport-editorial element packs (SVG with brand-token slots — every element
auto-on-brand), our own open-collection-seeded stock pools, embedding search +
context-aware suggestions, telestration/annotate layer, club mascot/emoji
packs. *(Companion §P6.8.)*

### P6.9 — Charts, infographics & data storytelling · ❌
The data advantage made visible: deterministic brand-styled stat graphics from
canonical results + `history/` (progressions, PB drops, medal tables, record
boards), AI chart recommendation and **grounded** insight takeaways (numbers
computed first, LLM phrases), diagram formats, scroll-stories. *(Companion §P6.9.)*

### P6.10 — Animation & motion system · ❌
A tokenised brand motion vocabulary (in/loop/out presets, photo motion, motion
paths, shared-element "match & move", page transitions, physics-flavoured
curves) compiled once to Remotion + FFmpeg + CSS; click/step order for decks;
reduce-motion variants everywhere. *(Companion §P6.10.)*

### P6.11 — Brand platform depth · ❌
Multi-kit (sponsor co-branding with pairing rules, event/section kits),
deterministic brand check (ΔE/APCA/clear-space) + AI auto-fix patches, token
locks, brand home page, kit-edit → re-render sweep across persisted briefs,
palette-file import. *(Companion §P6.11.)*

### P6.12 — Documents, decks & the PDF suite · ❌
One paged document engine for the three club documents (meet programme, season
report, sponsor proposal) + AGM decks: data-grounded outline→draft, presenter
surface (notes, timer, phone remote, autoplay/kiosk), PPTX/DOCX round-trip,
deck→MP4, honest bounded PDF utilities. *(Companion §P6.12.)*

### P6.13 — Club microsites, link-in-bio, forms & widgets · ❌
Data-generated pages (meet microsite, link-in-bio, event RSVP) on platform
subdomains/BYO domains, forms feeding the data hub (ADR-0003 applies hard),
vetted sandboxed widget catalogue (countdown, medal tally, polls), SEO layer,
brand-safe QR generator. *(Companion §P6.13.)*

### P6.14 — Email & newsletter design · ❌
The `turn_into` newsletter made visual and portable: email-safe branded HTML
auto-assembled from the period's approved content with an editorial AI pass;
export/hosted-view first, direct-send adapter later behind the publish gate.
*(Companion §P6.14.)*

### P6.15 — Data hub, bulk generation & personalisation · ❌
Canonical tables made user-facing (provenance per cell, CSV/XLSX round-trip,
deterministic derived columns), club-relevant connectors (Swim England API per
PC.6a) on `scheduler/` refresh, and review-queued **bulk generation** —
"certificates for all 47 PB swimmers" in one click; bulk never bypasses
approval. *(Companion §P6.15.)*

### P6.16 — Planner calendar, board & performance analytics · ❌
The P1.3 planner gets a calendar/board body (drag-reschedule re-evaluates the
gate), club-aware key dates, per-channel previews with safe zones, and a
first-party post-P4 metrics loop (per-type/archetype attribution feeding the
planner's ranking); sponsor A/B creative sets — prepare, never spend.
*(Companion §P6.16.)*

### P6.17 — Collaboration & review · ❌
Committee-shaped review on the workflow spine: anchored comment threads,
mentions, blocking tasks, version diff/restore, element locks, roles +
group-approver rules, expiring share tokens for outside reviewers, the
assistant taggable in threads. *(Companion §P6.17.)*

### P6.18 — Export, conversion & delivery engine · ❌
One export engine for every surface (adds SVG/GIF/PPTX/DOCX/WAV/print-PDF,
quality/transparency options, bulk jobs) + the quick-action toolbox on the
media library (image/video/PDF/GIF utilities) — all deterministic code we own.
*(Companion §P6.18.)*

### P6.19 — Print & merch pipeline · ❌
Print-readiness as engineering: physical `FormatSpec`s, CMYK PDF/X with
bleed/marks, **deterministic preflight with explanations**, merch formats +
mockups; fulfilment only ever as an optional flag-gated slot — the default
deliverable is a file any printer accepts. *(Companion §P6.19.)*

### P6.20 — Platform surface: public API, webhooks & MCP · ❌
A versioned org-scoped API over what the product already does, signed
webhooks, published iPaaS recipes (their runtimes stay theirs), an **MCP
server** so agents (Claude/ChatGPT/Gemini-class) drive MediaHub itself,
first-party file interop (SVG/PSD/palettes), read-only embeds; marketplace
explicitly long-term; GWS stays excluded. *(Companion §P6.20.)*

### P6.21 — Mobile, PWA & access surfaces · ❌
Hosted-only stands: an installable PWA with share-target capture to the media
library (the poolside killer feature), offline-tolerant approval queue,
mobile-first review/caption/crop; guest views via share tokens; native-store
apps only if the PWA proves insufficient. *(Companion §P6.21.)*

### P6.22 — AI governance, quotas & provenance · ❌
The Shield analogue we mostly have, completed: per-org/per-feature quota
ledger on `observability/` with a live usage panel (tier numbers belong to
PC.4), moderation on generative surfaces, provenance manifests on AI media
(C2PA-style where tooling allows), role-based feature permissions.
*(Companion §P6.22.)*

### P6.23 — Localisation & translation · ❌
Welsh-first bilingual content (a real Swansea-wedge need): glossary-protected
translation with layout-aware re-render and autofit absorption, side-by-side
bilingual approval, bulk per-language variants, AI-dub pipeline (labelled),
own UI string catalogue. *(Companion §P6.23.)*

### P6.24 — Pro editor & round-trip (the Affinity answer) · ❌
A fine-control editor as validated spec patches (layers, align/distribute,
rulers/guides, page management, vector node/boolean ops, curves/levels) — and
**round-trip, not suite-cloning**: layered SVG/PSD export/import so power
users finish in their own pro tool; RAW/HDR/DTP explicitly non-goals.
*(Companion §P6.24.)*

**Building blocks.** Almost entirely seams that already ship: the design-spec
director + archetypes (P1.4), `graphic_renderer` + autofit + saliency, both
reel engines (P0.1), the cutout layer, the TTS/ASR/LLM provider slots (P0.4),
`media_library`, `workflow` + publish gate, `scheduler/`, `notify/`,
`observability/`, PC.3 tenancy. New heavy deps stay licence-vetted per
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) (e.g. `pillow-heif`,
`pypdf`, `python-pptx`/`docx`, a PSD reader/writer, C2PA tooling — all behind
our own modules).

**Dependencies.** Gated behind **Phase C** (both exit gates) like P3/P4/P5.
P6.16's analytics loop and P6.14's send adapter additionally need **P4**
adapters; P6.2 voice input and P6.5 captions need the **P5.3** ASR seam
filled (or a cloud provider on the same seam). Feeds back into **PC.4**
packaging (quotas/tiers) and strengthens the wedge against the
"volunteer-already-has-Canva" commodity pressure named in the diligence.

---

## Cross-cutting investments (all phases)

| Investment | Status | Notes |
|---|---|---|
| No-hidden-fees discipline | ✅ enforced | The [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) register is now pinned by the Phase-0 guard suites (P0.3/P0.4/P0.5, 2026-06-10): every paid path stays optional with a free default, every AI surface admits a local provider, and no AGPL code can enter the process. |
| Multi-tenancy: org → workspace | ✅ shipped (2026-06-11) | **PC.3 done:** per-org membership binding in one shared instance (`web/tenancy.py`, `memberships.jsonl`, ADR-0014) on top of the ADR-0003 invariant; pinned by `tests/test_workspace_membership_invariant.py`. Postiz/Mixpost stayed reference-only — nothing embedded. |
| Go-to-market / distribution | 🔵 instrumented; selling open | The build/sell imbalance is the #1 risk (PC.6): warm-first pipeline + referral-debt + cold-cap readouts and the drafted Swim England application now live on `/operator/commercial`; the founder's selling motion (and the ≥10-club gate) remains open. See [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md). |
| Safeguarding / minors' data | ✅ locked | Isolation invariant per [`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md); applies with extra force to autonomous post types. |
| Explainability & audit trail | ✅ | Every step explainable; autonomous-publish decisions (gate verdicts, auto-approvals, publish attempts) land in the immutable per-org ledger (P2.3, 2026-06-11). |
| Product design / UI polish | ❌ | Targets: Home, Add Input, Content Pack, the autonomy controls. Flask + Jinja stay. |
| Test-suite stability | ✅ | Full suite green (2836 passed / 1 skipped after merging main). Keep green. |
| Operator deployment template | ✅ | `render.yaml` + `.env.example` canonical; one-click Render deploy works. |

---

## Immediate next moves

A recommended ordered backlog — each with its own exit criterion. (Full backlog in the
rebuild's `CHANGES`/PR.)

**Re-sequenced (2026-06 commercial reconcile).** The prior reconcile rightly put
**product quality on the swim wedge** ahead of the grand expansions. The scaling
diligence ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))
adds the missing half: **the binding constraint is monetisation/distribution, not
capability.** So the **commercial gate (Phase C) is now #1** — ahead of *everything*,
including more graphics polish — and P3/P4/P5 are explicitly deferred behind it **and** a
*≥10 clubs paying annually* gate.

1. **Phase C — Commercialise & Distribute (🥇 top priority).** Self-serve signup + auth
   (PC.1), Stripe billing (PC.2), **true multi-tenancy** (PC.3), validated pricing with
   annual prepay (PC.4), the free-self-host call (PC.5, **resolved: hosted-only**), and GTM/distribution (PC.6).
   *Exit:* a club can sign up, pay, and publish with **zero founder involvement.**
   **Nothing below ships ahead of this.** (Update 2026-06-11: the engineering is done —
   PC.1 + PC.2 live, **PC.3 shipped** (Council-tested schema, ADR-0014), PC.4/PC.6
   instrumented on `/operator/commercial`. What's left of Phase C is the founder's
   selling motion: set `STRIPE_*`, pre-bind pilots, quote real prices, submit the Swim
   England application, win the first 10 annual clubs.)
2. **Phase W — the wedge-depth backlog (selectable, ungated; added 2026-06-11).**
   Fourteen researched items (athlete registry, consent manager, club records,
   qualifying times, LENEX, meet previews, live meet mode, season wraps,
   magic-link approvals, OCR, alt-text, certificates, Welsh captions, engagement
   telemetry) absorbed from
   [`research/PRODUCT_IDEAS_2026-06.md`](research/PRODUCT_IDEAS_2026-06.md); the
   sell-side four became **PC.7–PC.10** and the distribution slice **P4.5/P4.6**.
   Pick an item **only when it unblocks a sale, a pilot, the NGB application, or
   a churn risk** — never ahead of the selling motion. Recommended first picks:
   W.1→W.2 (consent), W.4 (qualifying times), W.10 (demo-day OCR robustness),
   PC.7 (the instant demo). *Exit:* per item.
3. **P1.4 graphics — ✅ done (2026-06-10).** The full spine shipped (PR #301: Tier B
   director/pool/compliance, the gated SEQ-3 cutover with the A/B review approved, and
   the SEQ-4 video stage), all §5 acceptance criteria met — so the "sellable wedge" bar
   is cleared. **Per the standing rule: stop polishing and sell.** Anything further on
   graphics (the 12th archetype, the floor's no-photo bias, the logo-chip polish) is
   strictly behind Phase C sell-side work.
4. **P0 — ✅ done (2026-06-10).** The whole de-risk phase closed in one pass:
   the P0.1 free reel engine (still-graphics + FFmpeg behind
   `MEDIAHUB_REEL_ENGINE=ffmpeg` — a zero-license deployment renders reels),
   plus the three Phase-0 guard suites making paid-dep optionality (P0.3),
   local provider slots (P0.4) and AGPL isolation (P0.5) continuously enforced.
5. **P1.3 — Cross-source planner. ✅ done (2026-06-10)** — with P1.2's
   slug-canonical taxonomy and P1.5's local brand-DNA flow, closing Phase 1.
   *Exit met:* a ranked, explainable plan for ≥2 profiles at `/plan`.
6. **P2 — ✅ done (2026-06-11).** The approval signal (P2.2), the single
   publish gate with all guardrails (P2.3) and the enum reconciliation shipped
   on the in-process substrate. *Exit met:* `fully_autonomous` publishes only
   when every guardrail + the confidence gate pass; kill switch halts
   instantly; every decision audited.

**Deferred behind the commercial gate AND "≥10 clubs paying annually":**

7. **P3 — Second sport end-to-end.** `recognition_football`/`_basketball` + a real data
   spoke. (`results_fetch/` already does sport-agnostic *ingestion*; this adds the
   per-sport *detector*.) *Gated:* no new sport until ≥10 clubs pay annually. *Exit:* one
   non-swimming sport produces content end-to-end.
8. **P4 — Free direct publishing.** Bluesky + Mastodon adapters (P4.1), email
   digests (P4.5) and Telegram channels (P4.6) as the review-free tier; start the
   Meta verification paperwork early (P4.2 note); demote the now-deprecated Buffer
   path (P4.4 — its classic API shut to new developers in 2019; integrations cut
   off 2025-03-01). *Exit:* publish to ≥2 platforms incl. one free.
9. **P5 — Local AI.** Ollama + Piper + whisper.cpp. *Exit:* full pipeline runs with no
   cloud keys.
9. **P6 — Creative-suite breadth.** Our own first-party versions of the full
   Canva / Adobe Express capability map, MediaHub-shaped (24 work packages,
   P6.1–P6.24; feature-by-feature mapping + completeness index in
   [`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md)). Pull-driven order
   once the gates open. *Exit:* a club runs its entire content life inside
   MediaHub without reaching for Canva/Express.

Run a **pilot** in parallel (one real club, the themed product) to surface UX holes the
audits can't — see [`PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md). The pilot now doubles as the
first hand-sell toward the Phase C traction gate.

---

## Appendices — status & how they map to Phase 0–5

The previous roadmap revision carried three appendices of runnable build/verification
prompts. They are **retained** below as execution detail (they preserve live
`PAR-*` / `SEQ-*` / `Step N` trailer IDs and link real shipped/in-flight code), with
this lineage note:

- **Appendix A — Generative Content Engine v2.** Current. The build breakdown for
  **P1.4** above (decided in [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md)).
  Its local `§0–§5` / `PAR-*` / `SEQ-*` numbering is self-contained.
- **Appendix B — Growth & Expansion (Steps 8–17).** ⚠️ **Legacy sequence,
  superseded.** Written against the older *Parity → Distinction → Leadership* spine.
  Its still-relevant steps are absorbed by the new phases (commercial/enterprise →
  **Phase C** — Step 7 → PC.1/PC.2/PC.4, Step 14's org→club hierarchy → PC.3; sport
  expansion → **P3**; publishing → **P4**; agentic/autonomy → **P2**).
  Where it conflicts with the new strategy, **the Phase C + 0–5 spine wins.** Retained for
  step-level execution detail only.
- **Appendix C — Adaptive Theming Engine verification.** Current. Verifies the
  **shipped** theming engine summarised under "Where we are today" (see
  [`THEMING.md`](THEMING.md)).

> **Lineage in one line:** the new **Phase 0–5** spine supersedes the old **Phase 1
> Parity → Phase 2 Distinction → Phase 3 Leadership** spine; the appendices below are
> the older revision's execution detail, kept and re-mapped, not deleted.

---

## Appendix A — Generative Content Engine v2: Build Prompts

> *Section numbers in this appendix (§0–§5) and item IDs (PAR-\*, SEQ-\*) are local to the appendix. This was previously a standalone doc; it is merged into the roadmap so there is a single reference. It is the build breakdown for §1.7 above.*

**What this is.** An execution roadmap that turns the recommendations in
`docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md` into ordered,
runnable build stages — *taking the advice in those documents as fact* — with an
implementation prompt and a verification prompt for every stage, and a separate
**parallel bucket** of work that can be run right now, simultaneously, in
different Claude sessions and merged to `main` in any order without conflicts.

**Date:** May 2026 · **Built against:** `main` after PR #137 (the trimmed
CLAUDE.md with the *gated removal process*) and PR #136 (the research docs).

**The problem being solved (from the thesis).** "Click generate" selects a tuple
from a bounded, hand-authored option space dominated by ~6 layout skeletons, with
an LLM constrained to *menu-pick* from fixed enums (`creative_brief/ai_director.py`)
and a renderer that repaints one DOM (`graphic_renderer/render.py`). The fix is to
replace the variation mechanism with: a **brand-token contract** → an **archetype
library + layout intelligence** (Tier A) → an **LLM design-spec director** (Tier B)
→ **generate-a-pool, rank, and compliance-check**, while keeping the deterministic
engine, the captions, Remotion, and the renderer substrate.

---

### 0. How to use this document

There are **two tracks**:

- **The Parallel Bucket (§2)** — additive, file-disjoint work that does **not**
  affect the build because each item ships *new, inert files* (or owns one
  isolated surface). These can be run **now**, each in its own Claude session,
  each on its own branch → PR to `main`. They are wired into the live pipeline
  later by the spine. **Run these first / concurrently.**
- **The Sequential Spine (§3)** — build-order-dependent work that modifies the
  shared files (`generator.py`, `ai_director.py`, `render.py`,
  `content_pack_visual/integration.py`, the `web.py` route) and *wires in* the
  parallel modules. These must be done in order, behind the `MEDIAHUB_GEN_V2`
  flag, and the removal stage follows CLAUDE.md's gated-removal process.

Each stage has a **Context** (what/why + files + thesis ref), an **Implementation
prompt** (paste into a fresh session), and a **Verification prompt** (paste into a
*separate* session to confirm it was done properly).

#### Relationship to the in-flight Adaptive Theming Engine (ROADMAP 1.6)

Do **not** rebuild the brand-token system. ROADMAP §1.6 already delivers the
DTCG-format `derived_palette`, ~25 MD3 role tokens, and a single-source-of-truth
JSON consumed by web/motion/email/graphic (Stage G). The thesis's "Layer 1 — brand
token contract" is **mostly that work, extended** with three generation-specific
additions (logo lockups by theme/form, type pairing, a structured voice profile,
and *semantic role descriptions an LLM can read*). SEQ-0 below extends the theming
token object; it does not duplicate it. If 1.6 Stage G is not yet merged, SEQ-0
coordinates with it rather than forking it.

---

### 1. The shared prompt preamble (every prompt inherits this)

To keep each prompt short, every Implementation and Verification prompt below
**assumes this preamble**. Paste it at the top of the session if the model hasn't
read the repo yet:

> **Preamble — read before doing anything.** You are working in the MediaHub repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md` in full, plus
> `docs/research/mediahub-generative-ai-thesis.md` (the plan) and the file(s) named
> in the task. Hard rules you must follow:
> - **Deterministic engine is off-limits to AI:** never Gemini-ify parsers
>   (`interpreter/`, `pb_discovery/`), detectors (`recognition*/`), the ranker
>   (`legacy/swim_content_v5/ranker_v3.py`), or colour-science (`theming/`,
>   CIEDE2000/APCA). You may *read* their outputs.
> - **Honest error, never a fake fallback:** if an AI provider is unavailable,
>   surface `ProviderNotConfigured`/`ClaudeUnavailableError` or fall back to a
>   *real deterministic* path — never a fabricated caption/graphic.
> - **Judgement goes through `media_ai.llm` / `ai_core.llm`** — never new hardcoded
>   heuristics for "which layout / which copy / which tone."
> - **Removing or replacing a route or data structure** requires CLAUDE.md's
>   *15-step breakage check before* + *15-step verification after* + a *dead-code
>   sweep*. Do not skip it.
> - **Tests:** run `python -m pytest tests/ -q` and add tests for new code; there
>   must be **no new failures** vs `main`, and you must not delete/skip/weaken a
>   test to go green.
> - **Branch & ship:** create a feature branch `claude/<short-name>`, commit with a
>   clear message, push, and **open a PR** (do not merge to `main` without the
>   user's approval — the user merges).
> - **Scope discipline:** touch only the files this task names. If you find you need
>   to modify a file the task says not to touch, stop and report instead.

---

### 2. The Parallel Bucket — run these now, concurrently, one session each

**Why these are safe to run simultaneously and merge in any order:** every item
below either creates **only new files** (inert — nothing imports them yet, so the
build is unaffected) or owns a **single isolated surface** that no other item and
no spine stage touches. The "Files you may touch" / "Files you must NOT touch"
lists guarantee no two parallel PRs edit the same file. Merge them to `main` in any
order; the spine (§3) wires them in afterward.

> **Conflict-safety contract (applies to every PAR item):** You may create/modify
> **only** the files listed under "Owns." You must **NOT** touch `web/web.py`,
> `creative_brief/generator.py`, `creative_brief/ai_director.py`,
> `graphic_renderer/render.py`, or `content_pack_visual/integration.py` (those are
> spine files). Your change must leave the existing build and tests green on its own.

#### PAR-1 · Caption quality pack
**Owns:** `src/mediahub/web/ai_caption.py` (the only item that touches it) + new
`src/mediahub/web/caption_examples.py` + `tests/test_caption_quality.py`.
**Context:** Captions are already strong (thesis §5.6); this adds the verified
brand-voice recipe. Independent of the graphic surgery.

**Implementation prompt:**
> [Preamble.] Extend MediaHub's caption generation (`web/ai_caption.py`) with the
> brand-voice recipe from thesis §5.6, all inside the existing Gemini→Anthropic
> path. Add: (1) **few-shot injection** — accept up to 5 of the club's own past
> captions and inject them verbatim as examples in the system prompt (store/read
> them via a new `web/caption_examples.py` keyed by `profile_id`, persisted under
> `DATA_DIR`); (2) **generate-many-then-dedupe** — generate 4–6 candidates and
> return them ranked, dropping any whose n-gram/embedding similarity to a recent
> caption or to each other is above a threshold; (3) **per-platform variants** —
> given one approved caption, produce feed / story / X / LinkedIn variants with
> per-platform length+tone constraints; (4) an explicit **AI-tell ban-list**
> ("delve", "elevate", "in the world of", reflexive "!"); (5) an **approval-loop**
> hook: a function that appends an edited+approved caption to the club's
> few-shot example store. Keep the existing function signatures working
> (additive params with defaults). Add `tests/test_caption_quality.py` covering
> dedupe, ban-list filtering, and few-shot injection (mock the LLM). Do NOT touch
> any spine file. Branch `claude/gen-par-1-captions`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-1 (caption quality pack) was done properly. Confirm:
> only `web/ai_caption.py`, `web/caption_examples.py`, and the new test were
> changed (no spine files); the existing caption route still works with the new
> defaults; few-shot examples are injected and capped at 5; dedupe actually drops
> near-duplicates; the ban-list filters the listed phrases; the approval-loop
> appends to the store; captions still raise an honest error (no fabricated
> fallback) when no provider is configured. Run the full suite — no new failures.
> Report a pass/fail checklist.

#### PAR-2 · Auto-fit text helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/autofit.py` + `tests/test_autofit.py`.
**Context:** Bannerbear's verified core feature (eval §6.1). A pure function that
computes the font-size (px) that fits a string into a given box at a given
font/weight, so long names/events never break a layout. Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/autofit.py`: a pure, deterministic helper
> `fit_font_px(text, box_w, box_h, *, font_family, weight, min_px, max_px,
> line_height) -> int` that returns the largest integer px size at which `text`
> fits within `box_w × box_h` (binary search; approximate advance-width via a
> char-width table or Pillow `ImageFont.getbbox` if a font file is available, else
> a metric heuristic — but keep it deterministic and documented). Add helpers for
> multi-line wrapping. No network, no LLM (this is layout maths, not judgement).
> Add `tests/test_autofit.py` with golden cases (short vs very long swimmer names,
> narrow vs wide boxes). Create ONLY these two files. Branch
> `claude/gen-par-2-autofit`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-2: only `graphic_renderer/autofit.py` and its test were
> added; `fit_font_px` is deterministic (same inputs → same output), monotonic
> (a longer string never returns a larger size for the same box), respects
> min/max bounds, and has no LLM/network calls. Run the suite — no new failures.

#### PAR-3 · Saliency-aware crop helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/saliency.py` + `tests/test_saliency.py`.
**Context:** Subject-aware crops (eval §6.1, thesis §5.3.1) so one archetype looks
correct and different with every photo. Deterministic maths (consistent with the
colour-science rule). Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/saliency.py`: deterministic helpers that,
> given an image path, return candidate crop rectangles for a set of target aspect
> ratios (e.g. `9:16`, `1:1`, `4:5`) using a saliency/energy heuristic (e.g.
> gradient-magnitude / edge density via Pillow+numpy, or reuse the existing cutout
> alpha if present to bias toward the subject). Expose
> `crops_for(image_path, ratios) -> dict[ratio, (x,y,w,h)]` and a
> `best_crop(image_path, ratio)`. No LLM, no network. Add `tests/test_saliency.py`
> with a couple of synthetic images (subject in different corners) asserting the
> crop tracks the subject and stays within bounds. Create ONLY these two files.
> Branch `claude/gen-par-3-saliency`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-3: only the saliency module + test were added; crops are
> deterministic, stay within image bounds, match the requested aspect ratios, and
> track the subject on the synthetic fixtures; no LLM/network. Suite green.

#### PAR-4 · Design-spec schema + validator (the Tier B contract, inert)
**Owns:** new `src/mediahub/creative_brief/design_spec.py` + `tests/test_design_spec.py`.
**Context:** The structured JSON contract the LLM art-director will emit (thesis
§5.4). Defining it as a standalone schema + normaliser now lets SEQ-2 just call it.
Inert until the director uses it.

**Implementation prompt:**
> [Preamble.] Create `creative_brief/design_spec.py` defining the `DesignSpec`
> dataclass and a strict `normalise(raw: dict, *, archetypes: list[str],
> token_roles: list[str]) -> DesignSpec` that coerces a (possibly hallucinated)
> LLM JSON object into a valid spec — every field constrained to a known enum or a
> token *role* name, with safe defaults on any out-of-vocabulary value (so a bad
> LLM response can never produce an illegal/illegible card). Fields per thesis
> §5.4: `archetype`, `colour_roles` (ground/surface/headline/accent → role names),
> `focal_element`, `crop_intent`, `hero_stat`, `secondary_stats`, `headline_hook`,
> `accent_treatment`, `logo_lockup`, `mood`, `motion_intent`, `rationale`. Provide
> the JSON-schema dict for schema-constrained decoding. No live LLM call here — this
> is the contract + validator only. Add `tests/test_design_spec.py` (valid spec
> round-trips; hallucinated/garbage values normalise to defaults; enums enforced).
> Create ONLY these two files. Branch `claude/gen-par-4-design-spec`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-4: only the design_spec module + test were added; an
> out-of-vocabulary value for every field normalises to a safe default; the schema
> dict matches the dataclass; no card-illegal spec can be produced. Suite green.

#### PAR-5 · Variant metrics module (success-metric instrumentation, inert)
**Owns:** new `src/mediahub/quality/variant_metrics.py` + `tests/test_variant_metrics.py`.
**Context:** Thesis §8C success metrics — archetype diversity and perceptual
distance across a candidate pool. Standalone scoring lib; inert until SEQ-2 wires it.

**Implementation prompt:**
> [Preamble.] Create a new `quality/` package with `variant_metrics.py`:
> deterministic functions `archetype_diversity(specs) -> float` (distinct
> archetypes / candidates) and `perceptual_spread(png_paths) -> float` (mean
> pairwise distance using a cheap perceptual hash or downscaled-LAB histogram
> distance — no heavy ML). Add `caption_repetition(captions) -> float` (max n-gram
> overlap). These power the §8C targets. No LLM/network. Add
> `tests/test_variant_metrics.py`. Create ONLY the new package files + test.
> Branch `claude/gen-par-5-metrics`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-5: only the new `quality/` module + test were added;
> metrics are deterministic and bounded; diversity rises with distinct archetypes;
> spread rises with visually different PNGs. Suite green.

#### PAR-6 · Brand bootstrap extractor (draft from a URL, inert)
**Owns:** new `src/mediahub/brand/bootstrap_extract.py` + `tests/test_bootstrap_extract.py`.
**Context:** "Paste your club URL → draft brand kit" onboarding (thesis §5.3),
modelled on Brandfetch's schema. A pure extractor that returns a **draft**
DesignTokens dict (for human confirmation — never auto-trusted). It may *read* the
existing `brand/link_handlers/` but must not modify them or add a route (wiring is
SEQ work). Inert until onboarding calls it.

**Implementation prompt:**
> [Preamble.] Create `brand/bootstrap_extract.py`: `extract_brand_draft(url) ->
> dict` returning a *draft* token set (palette candidates with semantic guesses,
> logo URLs by inferred form, font guesses) shaped like the DesignTokens contract,
> reusing existing `brand/link_handlers/` for fetching where possible (read-only
> import). Mark every field `"confirmed": false`. No route, no web.py edit, no
> auto-apply. Honest about uncertainty (small-club extraction is unreliable — return
> confidence flags, never silently guess). Add `tests/test_bootstrap_extract.py`
> (mock the fetch; assert draft shape + all `confirmed:false`). Create ONLY these
> two files. Branch `claude/gen-par-6-brand-bootstrap`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-6: only the extractor + test were added; no route/web.py
> change; output is a draft (all `confirmed:false`), shaped like DesignTokens; the
> existing `link_handlers` were imported, not modified. Suite green.

#### PAR-7 · Archetype templates (the fan-out item — one session per archetype)
**Owns (per session):** ONE new file `src/mediahub/graphic_renderer/layouts/v2/<name>.html`
(+ optional `<name>.notes.md`). Run this prompt N times in N sessions, once per
archetype name — each writes a *different* file, so they never conflict.
**Context:** The structural variety the 6 families lack (thesis §5.3.1). Author
each against the **slot convention** below so SEQ-1 can wire them uniformly.

**Slot convention (author against this exactly):** use `{{PLACEHOLDER}}` string
substitution (not Jinja), and reference brand colours **only** via CSS custom
properties (`var(--mh-primary)`, `var(--mh-on-primary)`, `var(--mh-surface)`,
`var(--mh-on-surface)`, `var(--mh-accent)`, `var(--mh-outline)`) — never hardcode a
hex. Available text placeholders: `{{ATHLETE_FULL_NAME}}`, `{{ATHLETE_FIRST_NAME}}`,
`{{ATHLETE_SURNAME_DISPLAY}}`, `{{EVENT_NAME}}`, `{{RESULT_VALUE}}`,
`{{ACHIEVEMENT_LABEL}}`, `{{MEET_NAME}}`, `{{CLUB_FULL}}`, `{{HERO_STAT}}`,
`{{LOGO_BLOCK}}`, `{{ATHLETE_IMG_BLOCK}}`, `{{ACCENT_DECORATION}}`,
`{{SPONSOR_BLOCK}}`. Canvas is `{{WIDTH}}×{{HEIGHT}}`. Include `{{BASE_CSS}}` at the
top. The archetype must read *structurally distinct* from `individual_hero` /
`big_number_hero` at a glance.

**Suggested archetype names (assign one per session):** `split_diagonal_hero`,
`full_bleed_photo_lower_third`, `editorial_numbers_grid`, `centered_medal_spotlight`,
`magazine_cover`, `ticker_strip`, `stat_stack_sidebar`, `triptych_progression`,
`quote_led_recap`, `big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`.

**Progress (PAR-7 catalog):** ✅ **12 of 12 archetypes live — catalog complete** (`duo_athlete_split` added 2026-06-09: a matchday duel poster — the canvas bisected into two equal vertical halves by a hard accent seam, photo bay vs brand data bay, crossed by the one full-width name band that bridges the seam). Representative seeds-0..9 pack archetype-diversity saturated at **1.00**; new archetype nearest-neighbour dHash **0.355** sits above the contemporaneously re-measured pre-existing library floor (**0.285**) so the floor is unchanged (genuine new structure, not a reskin). Every archetype now ships a `.notes.md` director catalog entry (test-enforced). The verification pass also fixed two renderer-wide typography defects (self-hosted fonts never loaded — `set_content` blocked `file://` woff2 fetches; Anton autofit under-measurement clipping long surnames) — see `docs/build_reports/GEN_QUALITY_BASELINE.md`.

**Implementation prompt (template — fill in `<NAME>`):**
> [Preamble.] Author ONE new graphic archetype `graphic_renderer/layouts/v2/<NAME>.html`
> following the slot convention in `docs/ROADMAP.md` (Appendix A → PAR-7)
> exactly (CSS-variable colours only, the listed `{{PLACEHOLDERS}}`, `{{BASE_CSS}}`
> at top). It must be a *structurally distinct* portrait layout (1080×1350 and
> 1080×1920 must both read well) — a genuinely different composition from the
> existing families, not a reskin. Self-contained HTML/CSS; no JS, no network, no
> hex literals. Add a one-paragraph `<NAME>.notes.md` describing the composition and
> when the director should pick it. Create ONLY those file(s) under `layouts/v2/`.
> Do not touch `render.py` or any other file. Branch `claude/gen-par-7-<NAME>`,
> commit, open a PR. (You cannot fully render-test it until SEQ-1 wires `layouts/v2`;
> instead, validate the HTML is well-formed and every placeholder/variable matches
> the convention.)

**Verification prompt:**
> [Preamble.] Verify a PAR-7 archetype: exactly one new `layouts/v2/<NAME>.html`
> (+ notes) was added; it uses ONLY CSS-variable colours (grep for `#` hex literals
> → none in colour positions); every placeholder is on the §PAR-7 allow-list;
> `{{BASE_CSS}}` is present; the layout is structurally distinct from the existing
> families; no other file changed. Suite green (these files are inert, so the suite
> is unaffected — confirm that too).

#### PAR-8 · Documentation + ADR (pure docs, inert)
**Owns:** new `docs/GENERATION.md` + `docs/adr/0001-generation-engine-v2.md`.
**Context:** Single canonical doc for the new engine + an architecture-decision
record. Pure docs; conflicts with nothing.

**Implementation prompt:**
> [Preamble.] Author `docs/GENERATION.md` documenting the v2 generation
> architecture from thesis §5 (the token contract, archetype library, design-spec
> director, pool/rank/compliance, captions, video), the `layouts/v2` slot
> convention (copy it from this roadmap §PAR-7), and the `MEDIAHUB_GEN_V2` flag.
> Also author `docs/adr/0001-generation-engine-v2.md` recording the decision to
> replace the enum-permutation/menu-picker engine with the design-spec director
> (context, decision, alternatives rejected per thesis §4A, consequences). Docs
> only. Branch `claude/gen-par-8-docs`, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-8: only the two docs were added; `GENERATION.md` matches
> thesis §5 and the §PAR-7 slot convention; the ADR records context/decision/
> alternatives/consequences. No code changed.

---

### 3. The Sequential Spine — build in order, behind `MEDIAHUB_GEN_V2`

These stages modify the shared spine files and wire in the parallel modules. They
**cannot** run concurrently with each other (they touch the same files); run them
in order, each as its own PR, after the parallel bucket is merged. Everything that
changes live behaviour is gated by the `MEDIAHUB_GEN_V2` feature flag until SEQ-3's
cutover, so production never regresses.

#### SEQ-0 · DesignTokens contract + feature-flag scaffolding · ✅ **DONE**
**Depends on:** ROADMAP §1.6 Stage G (DTCG `derived_palette` JSON) if merged; else
coordinate. **Touches:** `brand/kit.py`, a new `config`/flag read, `theming/` (read).
**Thesis ref:** §5.3.

**Implementation prompt:**
> [Preamble.] Extend the brand token object (`brand/kit.py` / the theming
> `derived_palette`) into the generation **DesignTokens contract** from thesis §5.3,
> *additively* — keep the existing flat `primary_colour`/`secondary_colour`/
> `accent_colour` as derived aliases so nothing breaks. Add: semantic colour
> **roles** with `brightness` + `when_to_use` text (reuse the existing APCA/ΔE2000
> numbers from `theming/`), **logo lockups** typed by `form`
> (icon/horizontal/stacked/mono) and `theme` (light/dark) — extend
> `theming/logo_chip.py` to *select* the lockup for a given background — a typed
> `type` pairing, and a structured `voice` profile (examples, banned phrases, emoji
> policy) that the caption store (PAR-1) can populate. Add a `MEDIAHUB_GEN_V2`
> feature flag read (env, default off) and a single helper
> `resolve_design_tokens(profile_id) -> dict` that returns the full contract with
> the semantic role descriptions an LLM can consume. No behaviour change yet (flag
> off). This is additive — the gated-removal process is NOT needed here. Add tests
> for `resolve_design_tokens`. Branch `claude/gen-seq-0-tokens`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-0: the old flat BrandKit fields still resolve (back-compat
> alias); `resolve_design_tokens` returns roles with `brightness`+`when_to_use`,
> logo lockups by form/theme, type pairing, and a voice profile; `logo_chip` selects
> a lockup per background; the `MEDIAHUB_GEN_V2` flag exists and defaults off; old
> persisted profiles still load. Suite green (no new failures); the change is purely
> additive (no removals).

#### SEQ-1 · Tier A — archetype library + layout intelligence (the immediate fix) · ✅ **DONE**
**Depends on:** SEQ-0, PAR-2 (autofit), PAR-3 (saliency), PAR-7 (archetypes),
optionally PAR-6. **Touches:** `graphic_renderer/render.py`,
`creative_brief/generator.py`, `legacy/swim_content_v5/ranker_v3.py` (read-only
addition). **Thesis ref:** §5.3.1. **This stage alone is expected to fix "samey."**

**Implementation prompt:**
> [Preamble.] Implement Tier A (thesis §5.3.1), gated behind `MEDIAHUB_GEN_V2`.
> (1) Teach `graphic_renderer/render.py` to load archetypes from
> `graphic_renderer/layouts/v2/*.html` (the PAR-7 files) using the documented slot
> convention, resolving colours from the DesignTokens roles (SEQ-0) as CSS
> variables. (2) Wire in `autofit.fit_font_px` (PAR-2) for headline/name/event
> slots so long strings never overflow. (3) Wire in `saliency.best_crop` (PAR-3) so
> the athlete photo is cropped per the archetype's `crop_intent`. (4) In
> `creative_brief/generator.py`, add a **deterministic archetype-picker** (seeded by
> the existing `auto_variation_seed_for`, stable per card, different across cards)
> that selects among the v2 archetypes — this is the no-AI fallback floor. (5)
> Expose, *read-only*, the ranker's ranked **emphasis angles** (lead with time / PB
> delta / placing / relay split) so the brief can vary the hero stat — do NOT change
> the ranker's scoring. With the flag ON, a content pack should use ≥6 distinct
> archetypes. Add tests asserting archetype diversity across a pack and that autofit
> prevents overflow. Branch `claude/gen-seq-1-tier-a`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-1: with `MEDIAHUB_GEN_V2=1`, rendering a pack uses ≥6
> distinct v2 archetypes; with the flag OFF, behaviour is unchanged (old engine).
> Long swimmer names/events no longer overflow (autofit); photo crops track the
> subject (saliency); the ranker's *scoring is byte-identical* to before (only a
> read-only emphasis-angle accessor was added — confirm no PB/ranking regression per
> CLAUDE.md engine rule). Walk upload→process→review with the flag on; cards render,
> captions/confidence intact. Suite green. Report the archetype-diversity number.

#### SEQ-2 · Tier B — design-spec director + pool, rank, compliance · ✅ **DONE**
**Depends on:** SEQ-1, PAR-4 (design_spec), PAR-5 (variant_metrics). **Touches:**
`creative_brief/ai_director.py`, `content_pack_visual/integration.py`,
`web/web.py` (the create-graphic route response). **Thesis ref:** §5.4–5.5.

**Implementation prompt:**
> [Preamble.] Implement Tier B (thesis §5.4–5.5), gated behind `MEDIAHUB_GEN_V2`.
> (1) Rewrite `ai_director.ai_creative_direction` to emit a **DesignSpec** (use
> `creative_brief/design_spec.py` from PAR-4) under JSON-schema-constrained decoding
> via `ai_core` — the LLM now chooses archetype, colour-role assignment, focal
> element, hero stat (from the ranker's emphasis list), generated hook, crop intent,
> accent, logo lockup, mood, and a `rationale` (which feeds the existing "why this
> design" explainability). Keep the SEQ-1 deterministic archetype-picker as the
> fallback floor when no provider is configured (honest error / real floor — never a
> fabricated card). (2) In `content_pack_visual/integration.py`, emit **N candidate
> specs** (default 5), render the pool (cheap — Playwright), run a **deterministic
> brand-compliance check** (APCA/ΔE2000 contrast, correct logo lockup for the
> background, sponsor-safe zones) that attaches an explainable score to each, score
> diversity with `quality/variant_metrics.py` (PAR-5), rank with the existing ranker,
> and return a **ranked shortlist**. (3) Extend the create-graphic route response in
> `web/web.py` to return the shortlist + per-candidate compliance score (additive
> JSON; keep the old single-visual fields populated from the top candidate so
> existing callers keep working). This stage *replaces* the menu-picker prompt — but
> the old `random_variation_profile`/enum path stays in place as the flag-off route
> until SEQ-3, so this is still additive at the route level. Add tests for spec
> emission (mock LLM), normalisation of a bad LLM response to a legal card, and the
> compliance score. Branch `claude/gen-seq-2-tier-b`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-2: with the flag on, the director emits a schema-valid
> DesignSpec; a deliberately malformed LLM response still yields a legal, legible
> card (PAR-4 normalisation); the pipeline returns a ranked shortlist of ≥4
> structurally distinct candidates each with a compliance score; the top candidate
> populates the legacy single-visual response fields (old callers unaffected); with
> no provider configured it falls back to the deterministic archetype floor (no
> fabricated output). Flag OFF = old behaviour. Suite green. Confirm no spine file
> outside the three named was touched.

#### SEQ-3 · Cutover + gated removal of the dead engine (the "full removal") · ✅ **DONE**
**Depends on:** SEQ-2 proven (A/B beats the old engine in review + suite green).
**Touches (removals):** `creative_brief/generator.py`,
`creative_brief/ai_director.py`. **Thesis ref:** §5.1, §7 cutover. **This is a
route/data-structure-adjacent removal — follow CLAUDE.md's gated process exactly.**

**Implementation prompt:**
> [Preamble.] Cut over to v2 and remove the dead variation engine — this is a
> deliberate replacement, so you MUST run CLAUDE.md's **15-step breakage check
> (Section A) before** touching anything, write the breakage list, then remove and
> run the **15-step verification (Section B) after**, then the **dead-code sweep
> (Section C)**. Steps: (1) flip `MEDIAHUB_GEN_V2` default to ON. (2) Remove the
> now-dead enum-permutation path: `random_variation_profile`, `_legacy_axes_from_seed`,
> `_PHRASE_TABLES`/`_phrase_for_seed`, and the closed-vocabulary menu-picker
> `_system_prompt` in `ai_director.py`; demote `BACKGROUND_STYLES`/`ACCENT_STYLES`/
> `TYPOGRAPHY_PAIRS`/`COMPOSITIONS`/`PHOTO_TREATMENTS` to renderer-internal building
> blocks only if still needed, else remove. (3) Keep the deterministic archetype
> floor. (4) Migrate or tolerate old persisted briefs/`variation_signature` fields
> (decide explicitly per breakage step 13). Do NOT remove the route or the
> `CreativeBrief` dataclass (extend, don't delete — production depends on them).
> Provide the completed A-list, B-list, and dead-code sweep in the PR description.
> Branch `claude/gen-seq-3-cutover`, run the full suite (no new failures, no
> weakened tests), PR.

**Verification prompt:**
> [Preamble.] Independently re-run CLAUDE.md Section B (15-step safe-removal
> verification) against SEQ-3: zero stray refs to the removed symbols (whole-repo
> grep); imports resolve; full suite green with no deleted/skipped/weakened tests;
> the create-graphic route + templates still work; old persisted runs still load (or
> are migrated); engine accuracy (PB detection, ranking) byte-identical; no new
> debug/IDOR exposure, no `ANTHROPIC_API_KEY` leak; diff contains only intended
> edits; dead-code sweep actually happened (no orphaned helpers, `_unused` vars, or
> "removed" placeholder comments). Report the checklist with pass/fail per step.

#### SEQ-4 · Video — data-driven scene structure (+ optional Tier C) · ✅ **DONE**
**Depends on:** SEQ-1/2 (the richer brief). **Touches:** `visual/motion.py`,
`remotion/src/compositions/`, optionally `visual/ai_background.py`. **Thesis ref:**
§5.7.

**Implementation prompt:**
> [Preamble.] Enrich video (thesis §5.7). (1) The richer brief (archetype, hero
> stat, tokens) already flows into `visual/motion.py` props — extend the Remotion
> compositions in `remotion/src/compositions/` to honour the archetype/emphasis so
> the reel's *look* matches the still. (2) Add **data-driven scene structure**: a
> multi-PB weekend produces a structurally different reel (variable
> `durationInFrames`/scene count derived from the number of ranked moments) than a
> single medal — the thing template tools can't do and Remotion can. (3) **Optional,
> behind its own flag** (`MEDIAHUB_GEN_BG`, default off): activate the dormant
> `visual/ai_background.py` hook (already imported at `render.py`) via a
> commercial-safe API (Bria/Recraft) for **backgrounds only**, composited under the
> deterministic text, with the existing contrast guardrails — never the data layer.
> Keep cache-by-content-hash behaviour. Add tests for variable scene count. Branch
> `claude/gen-seq-4-video`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-4: reel scene count varies with the number of ranked
> moments; the reel look matches the still archetype; cache-by-hash still works;
> the optional generative-background path is OFF by default and, when on, only
> affects the background (data text stays deterministic and legible). Suite green.

---

### 4. Dependency graph & sequencing

```
RUN NOW, CONCURRENTLY (each its own session → PR to main, any merge order):
  PAR-1 captions      PAR-2 autofit     PAR-3 saliency    PAR-4 design-spec
  PAR-5 metrics       PAR-6 bootstrap   PAR-7 archetypes×N PAR-8 docs
        (all additive/inert or single-surface — no shared-file conflicts)
                              │
                              ▼
THEN, IN ORDER (each its own PR; gated by MEDIAHUB_GEN_V2):
  SEQ-0 tokens ─▶ SEQ-1 Tier A ─▶ SEQ-2 Tier B ─▶ SEQ-3 cutover+removal ─▶ SEQ-4 video
  (SEQ-0 also coordinates with ROADMAP §1.6 Stage G if not yet merged)
```

**Wiring map (which spine stage consumes which parallel module):**

| Parallel module | Wired in by | Until then it is |
|---|---|---|
| PAR-2 autofit, PAR-3 saliency, PAR-7 archetypes | SEQ-1 | inert new files |
| PAR-4 design-spec, PAR-5 metrics | SEQ-2 | inert new files |
| PAR-6 brand bootstrap | SEQ-0 onboarding (or later) | inert new file |
| PAR-1 captions | already live (own surface) | shipped independently |
| PAR-8 docs | n/a | docs |

**The fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (in parallel now) →
SEQ-0 → SEQ-1. That delivers Tier A — deterministic, brand-safe, ~$0 marginal cost
— which the thesis expects to resolve the complaint on its own, before any
LLM-director work (SEQ-2).

---

### 5. Acceptance criteria (from thesis §8C)

The overhaul is "done" when, with `MEDIAHUB_GEN_V2` on:

1. **Structural distinctiveness:** a 10-card pack uses ≥6 distinct archetypes; a
   5-candidate pool for one card spans ≥4 archetypes (today ~1–2). Measured by
   `quality/variant_metrics.py` (PAR-5).
2. **On-brand fidelity:** the deterministic compliance check passes ≥99% of shipped
   candidates; off-brand candidates are caught before a human sees them.
3. **Caption non-repetition:** consecutive captions for a card are below the overlap
   threshold; zero ban-list phrases ship.
4. **Human-acceptance rate** (approved without manual redesign) rises vs the old
   engine in the review-UI A/B.
5. **Cost & latency:** marginal API cost/pack < ~$0.50 (Tier A+B); cold render
   within today's 30–90s; cache-hit behaviour preserved.
6. **No moat regression:** rendered data accuracy stays 100% (deterministic), and
   every card keeps its "why this card / why this design" explanation.
7. **Suite green** throughout (no new failures, no weakened tests), and SEQ-3's
   gated-removal checklists are completed and recorded.

---

*Derived from `docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md`, against `main` after
PR #137. Run the Parallel Bucket (§2) now in separate sessions; then walk the
Sequential Spine (§3) in order.*



---

## Appendix B — Growth & Expansion: Build Prompts (not yet done)

> *Runnable implementation + verification prompts for the Phase 2/3 growth work (commercial, sport expansion, athlete surfaces, integrations, enterprise, agentic editing, marketplace, sponsor-side). The earlier steps (brand DNA, voice imitation, visible intelligence, output expansion, turn-into, publishing) are already shipped and are intentionally omitted. Step/Phase numbers below are local to this appendix.*

#### Step 7: Commercial Layer — Stripe, Tiers, Self-Serve Signup

##### Context
MediaHub has no commercial layer today. The plan is to ship public pricing, self-serve signup, and a free tier alongside Phase 1's product improvements so commercial pressure surfaces during iteration.

> ⚠️ **Promoted & repriced (2026-06 reconcile).** This step is no longer "alongside
> Phase 1" — it is the front-of-queue **Phase C** (signup → **PC.1**, Stripe → **PC.2**,
> tiers/pricing → **PC.4**). The scaling diligence
> ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)) makes
> it the **top priority**, ahead of expansion. **The `Free / Club £30/mo / Federation
> £250/mo` figures in the prompt below are ⚠️ unvalidated and too low** — candidate
> repricing: **Club £49–£99/mo billed annually, Federation £250+/mo**, with **annual
> prepay** (SMB/volunteer churn is 3–7%/mo; annual billing cuts it ~30–40%). Treat the
> code-block prompt below as legacy execution detail; Phase C and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md)
> are the current source of truth.

##### Implementation Prompt

```
Add a commercial layer: signup, Stripe billing, three tiers.

GOAL: a new user can land on /, click "Get started", create an account
with email + password, choose a plan (Free / Club £30/mo / Federation
£250/mo), pay via Stripe Checkout, and start using MediaHub on the
hosted service.

FILES TO MODIFY:
- NEW src/mediahub/web/auth.py: minimal email+password auth (use
  passlib bcrypt; sessions via Flask's session cookie with a
  signed secret).
- NEW src/mediahub/web/billing.py: Stripe Checkout session creation,
  webhook handler for subscription events.
- src/mediahub/web/web.py:
  - new GET/POST /signup, /login, /logout
  - new GET /pricing (3-tier table)
  - new GET /billing (current plan, manage subscription via Stripe
    Customer Portal)
  - new POST /webhooks/stripe (verify signature, update subscription
    status)
  - guard premium features (multi-club, enterprise tools — to be
    added in Phase 3) behind a plan check; existing features remain
    open on Free.
- DB: extend the existing DATA_DIR storage with a users.jsonl ledger
  (email, hashed_password, plan, stripe_customer_id, created_at).
  Do not introduce SQLAlchemy.
- environment: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION.
- Free tier limits: 3 runs/month, single brand profile, no Buffer
  scheduling. Soft limit (a banner) — never lock the user out
  permanently on free.

ACCEPTANCE CRITERIA:
- /signup creates a user, hashes the password, logs them in.
- /pricing shows the three tiers with feature lists.
- "Upgrade" buttons start a Stripe Checkout flow (use Stripe test
  mode keys for dev).
- A successful Stripe Checkout webhook updates the user's plan.
- /billing lets the user manage their subscription via Stripe Customer
  Portal.
- Self-hosted deployments (no STRIPE_SECRET_KEY env) continue to
  work — auth is optional, billing routes return 503 with a clear
  "billing is not configured for this deployment" message.

DON'T BREAK:
- Any existing route that was open is still open if no STRIPE_*
  env vars are configured.
- pytest at 253+.
- The Stop hook git push flow continues to work.

TESTS:
- tests/test_auth.py: signup, login, logout, password hashing.
- tests/test_billing.py (mocked Stripe): webhook verification,
  subscription update flow.

```

##### Verification Prompt

```
Verify Step 7 (Commercial layer) end-to-end.

1. Tests: full pytest + tests/test_auth.py + tests/test_billing.py -v.

2. Self-hosted-without-billing path:
   - With STRIPE_SECRET_KEY unset, boot the app.
   - GET /, /add-input, /upload, /organisation, /settings — all 200.
   - GET /pricing and /billing — 200 (show "billing not configured").
   - All caption / motion / Turn-Into routes work as before.

3. Signup / login flow:
   - POST /signup with a fresh email + 12-char password. Confirm
     redirect to /add-input + a session cookie.
   - Log out. Log back in. Confirm session restored.
   - Submit a wrong password. Confirm a clear error, not a 500.
   - Confirm passwords in users.jsonl are bcrypt hashes (not plain).

4. Stripe-mode (test keys):
   - Set STRIPE_SECRET_KEY, STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION
     to Stripe test values.
   - Hit /pricing. Click "Upgrade to Club".
   - Confirm a Stripe Checkout session URL is returned and the test
     mode page renders (open in browser, fill 4242 4242 4242 4242).
   - Complete checkout. Confirm the webhook handler updates the
     user's plan in users.jsonl to "club".

5. Free tier soft limit:
   - On a Free account, create 3 runs. Create a 4th. Confirm a banner
     appears (NOT a hard lock).

6. Buffer scheduling guarded:
   - On Free, the Schedule button must show "Upgrade to schedule
     posts" instead of opening the modal.

7. Security checks:
   - Try to access /billing without a session. Confirm redirect to
     /login.
   - Inspect the session cookie — must be HttpOnly + Secure (when
     served via HTTPS) and signed.
   - Grep the codebase for STRIPE_SECRET_KEY — must only appear in
     billing.py and never logged.

8. Regression sweep: all features from Steps 1-6 still work.

OUTPUT: single report.
```

---

### Phase 2 — Distinction (Steps 8-12, target months 3-9)

#### Step 8: Sport Expansion — Athletics (Track and Field)

##### Context
MediaHub today is swimming-only. Athletics is the natural second sport — overlapping audience (school athletic programmes, multi-sport clubs), similar result-file structure (event, time/distance, place), but a different event vocabulary and a different PB taxonomy.

##### Implementation Prompt

```
Add athletics (track and field) as MediaHub's second sport.

GOAL: a user can upload an athletics result file (CSV or Hytek-format
.txt) on /upload, MediaHub recognises athletes, computes PBs, ranks
achievements, and produces a content pack with athletics-appropriate
language.

FILES TO MODIFY:
- NEW src/mediahub/sports/: refactor the sport-specific bits of the
  existing pipeline out of swimming-implicit code paths. Each sport
  should have:
    sports/<sport>/events.py — canonical event vocabulary
    sports/<sport>/parser.py — result-file parsers
    sports/<sport>/pb_logic.py — PB and record detection
    sports/<sport>/templates.py — celebratory phrase patterns
- src/mediahub/sports/__init__.py: register a SPORTS dict and a
  pick_sport(file_bytes, hint) -> SportModule selector.
- src/mediahub/sports/swimming/: move existing swimming code here
  (preserve all behaviour and tests).
- src/mediahub/sports/athletics/: new athletics implementation.
  Event vocabulary: 100m, 200m, 400m, 800m, 1500m, 3000m, 5000m,
  10000m, hurdles (60m/100m/110m/400m), steeplechase, all field
  events (LJ, TJ, HJ, PV, SP, DT, HT, JT), relays. Distinguish
  TRACK (time-based) from FIELD (distance/height-based) for PB
  comparison logic.
- src/mediahub/web/web.py /upload: detect sport from filename and
  content; allow user to override via a sport dropdown.
- ClubProfile: add primary_sport field; default to "swimming" for
  backward compatibility.

ACCEPTANCE CRITERIA:
- Uploading an athletics result file produces an athletics-specific
  content pack with phrases like "smashed a PB" appropriate to track
  ("ran a personal best") and field ("threw a personal best").
- A field PB is correctly detected (higher = better) vs track PB
  (lower = better).
- All swimming tests still pass — no regression.
- Adding a third sport in future is a matter of creating a new
  sports/<sport>/ subpackage, no refactoring of the platform code.

DON'T BREAK:
- Every existing swimming test (interpreter, recognition, corpus,
  visual, caption) still passes.
- pytest at 253+ (new athletics tests added).
- All Phase 1 features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion, Buffer publishing) work for athletics output.

TESTS:
- tests/test_athletics_parser.py: parse a sample athletics CSV,
  verify event detection.
- tests/test_athletics_pb_logic.py: field PB (higher = better) and
  track PB (lower = better) are correctly classified.
- tests/test_sports_registry.py: pick_sport routes correctly.

```

##### Verification Prompt

```
Verify Step 8 (Athletics support) end-to-end with no swimming regression.

1. Tests:
   - python -m pytest tests/ -q. Must be 253+ plus the new athletics
     tests (target 260+).
   - python -m pytest tests/test_athletics_*.py
     tests/test_sports_registry.py -v.

2. Swimming regression:
   - Upload an existing swimming sample file. Confirm the content pack
     is identical in structure to pre-Step-8 behaviour.
   - All four caption tones generate; visible intelligence shows PB
     reasoning; Turn-Into produces 6-7 artefacts; motion renders.
   - tests/test_interpreter_smoke.py, tests/test_pb_discovery.py,
     tests/test_corpus_recovery.py — all pass.

3. Athletics happy path:
   - Upload a sample athletics CSV. Confirm sport detection routes
     to athletics.
   - Confirm event names include 100m, 800m, LJ, TJ, etc.
   - Confirm PB logic: a long jump of 6.45m beats a previous 6.30m
     (higher = better); a 100m time of 11.40 beats 11.50 (lower = better).
   - Confirm captions use athletics-appropriate language ("ran a
     PB in the 800m" not "swam a PB").

4. Sport switching:
   - Manually override sport from swimming → athletics on the /upload
     page. Confirm the override takes effect.

5. Module structure:
   - ls src/mediahub/sports/ — confirms swimming/ and athletics/
     subpackages.
   - python -c "from mediahub.sports import SPORTS, pick_sport;
     print(list(SPORTS.keys()))"
     — confirms both sports registered.

6. Regression sweep on Phase 1:
   - All 7 Phase 1 steps' features still work (sample one feature
     from each).

OUTPUT: single report.
```

---

#### Step 9: Athlete-Facing Micro-Surfaces

##### Context
Greenfly routes content from a league to athletes for personal sharing. For MediaHub the parallel is letting a swimmer/athlete receive their own personal share-ready cards via a private link, which they post to their own channels. This expands distribution beyond the club account.

##### Implementation Prompt

```
Add athlete-facing micro-surfaces for personal sharing.

GOAL: each swimmer/athlete in a run can be given a personal,
unlisted link to a page that shows their cards for that meet plus
their season-to-date highlights, with a "Share to Instagram" / "Save
to camera roll" affordance per card. No login required for the
swimmer.

FILES TO MODIFY:
- src/mediahub/athlete_pages/: new module.
- Token: per-athlete unlisted token = HMAC(server_secret, run_id +
  athlete_id), 24 chars base32. Stored in run JSON.
- src/mediahub/web/web.py:
  - new GET /a/<token> — renders the athlete page. No auth required.
  - new GET /a/<token>/card/<card_id>/share — returns the card as a
    direct-download image for the athlete to save and post.
  - new POST /api/runs/<run_id>/athlete-tokens — admin route on the
    review page: generate or revoke tokens for athletes in the run.
- Review page: "Send to athlete" button on each card; clicking copies
  the personal share link (or opens a QR code modal for in-person
  hand-off).
- Privacy: the athlete page MUST NOT show any other swimmer's data,
  the original results file, or any club admin surface.

ACCEPTANCE CRITERIA:
- An athlete with a token can see only their own cards.
- The link is unguessable (HMAC + secret rotation).
- An admin can revoke a token; revoked tokens render a "this link has
  been revoked" page.
- Share affordances work on mobile: tapping "Save to camera roll" on
  iOS Safari triggers a long-press save flow; on Android, a direct
  download.
- Page renders correctly on screens 320px wide (smallest common mobile).

DON'T BREAK:
- All earlier features still work.
- Privacy: no PII leakage from athlete page to the rest of the
  system. Specifically: an athlete cannot enumerate other tokens.

TESTS:
- tests/test_athlete_pages.py: token generation determinism, HMAC
  verification, revoked-token handling, isolation between athletes.

```

##### Verification Prompt

```
Verify Step 9 (Athlete pages) end-to-end.

1. Tests: full pytest + tests/test_athlete_pages.py -v.

2. Happy path:
   - On an existing run, generate a token for athlete A and athlete B.
   - GET /a/<token_A> — confirm 200, shows only A's cards.
   - GET /a/<token_B> — confirm 200, shows only B's cards.
   - Try GET /a/<token_A> with one character changed — confirm 404,
     NOT a leak of the original page.

3. Isolation:
   - On A's page, the response body must NOT contain B's swimmer_name.
   - The page must NOT contain the path to the results file.

4. Revocation:
   - Revoke A's token. Re-fetch /a/<token_A> — confirm a clear
     "revoked" page, status 410 or 200 with a message.

5. Mobile rendering:
   - Open /a/<token_A> in a 360x800 viewport. Screenshot.
   - Confirm cards fit, text is readable, the share buttons are
     thumb-sized (≥44px).

6. Share affordance:
   - GET /a/<token>/card/<card_id>/share — must return an image with
     Content-Disposition: attachment.

7. Regression sweep: all Phase 1 + Step 8 features still work.

OUTPUT: single report.
```

---

#### Step 10: Sponsor-Aware Generation

##### Context
Sponsors are a primary revenue driver for clubs and the buyer's biggest stakeholder. A sponsor-aware product variant of every output type — caption with sponsor mention, graphic with sponsor logo, newsletter section with sponsor block — turns MediaHub into a sponsorship-value-realisation tool.

##### Implementation Prompt

```
Make every output type sponsor-aware.

GOAL: when ClubProfile has sponsor_name + sponsor_guidelines set,
every generated caption, graphic, motion, reel, and Turn-Into
artefact has an opt-in sponsor variant. The sponsor variant must
respect the guidelines (e.g. "always include #BrandNameSwim";
"never combine our logo with a competitor's").

FILES TO MODIFY:
- ClubProfile: extend with sponsor_logo_path,
  sponsor_brand_colour (hex), sponsor_required_hashtags (list),
  sponsor_forbidden_phrases (list), sponsor_activation_rate
  (e.g. "every 3rd post"), sponsor_position_preference
  (top|bottom|watermark).
- src/mediahub/sponsor/: new module:
    apply_sponsor_to_caption(caption: str, profile: ClubProfile,
                              activation: bool) -> str
    apply_sponsor_to_graphic(graphic_brief: dict,
                              profile: ClubProfile) -> dict
- Generators (caption, graphic, motion, Turn-Into) call the sponsor
  apply functions when activation=True. Activation is determined by
  the sponsor_activation_rate or explicit user toggle per card.
- review page: a "Sponsor mode" toggle on each card; the entire
  content pack also has a global toggle.
- Compliance: a "Sponsor compliance check" panel lists each generated
  artefact and confirms it satisfies all guidelines or flags
  violations.

ACCEPTANCE CRITERIA:
- With sponsor configured, the sponsor toggle on a card produces a
  sponsor variant that:
  - Includes any required hashtags.
  - Avoids any forbidden phrases.
  - Displays the sponsor logo in the configured position.
  - Uses the sponsor brand colour as a tasteful accent (without
    overriding the club's primary palette).
- The compliance panel surfaces any violation clearly.
- Without a sponsor configured, the toggle is hidden, not greyed out.

DON'T BREAK:
- All earlier features still work.
- pytest at 260+ (athletics tests added in Step 8).

TESTS:
- tests/test_sponsor_pipeline.py: required-hashtag enforcement,
  forbidden-phrase blocking, logo positioning.

output expansion).
```

##### Verification Prompt

```
Verify Step 10 (Sponsor mode) end-to-end.

1. Tests: full pytest + tests/test_sponsor_pipeline.py -v.

2. Configuration round-trip:
   - Set sponsor_name + sponsor_required_hashtags ["#TestSponsor"]
     + sponsor_forbidden_phrases ["beat the competition"].
   - Save, reload /organisation. Confirm the fields persist.

3. Sponsor caption check:
   - Toggle "Sponsor mode" on one card.
   - Confirm the caption now contains "#TestSponsor".
   - Force the LLM (or heuristic) to produce text containing "beat the
     competition" via a test fixture, run the apply function, and
     confirm the phrase is removed or rewritten.

4. Sponsor graphic check:
   - Toggle sponsor mode, regenerate the graphic.
   - Open the image; confirm the sponsor logo appears in the
     configured position.
   - Confirm the sponsor colour appears as an accent (not as
     the primary background).

5. Compliance panel:
   - Configure a deliberate violation (a required hashtag NOT present
     in the caption). Confirm the compliance panel flags it visibly.

6. Sponsor absent:
   - Clear sponsor_name. Confirm the sponsor toggle is hidden, not
     present in the DOM.

7. Regression sweep: all Phase 1 and Steps 8-9 features still work.

OUTPUT: single report.
```

---

#### Step 11: Multi-Sport Architecture Cleanup + Football/Rugby

##### Context
With athletics shipped in Step 8 the sports/ package exists. Adding football and rugby validates that the architecture genuinely scales and unlocks the largest UK market segment (school and university football/rugby).

##### Implementation Prompt

```
Add football and rugby as sports 3 and 4; clean up the sports/
architecture as needed.

GOAL: a user can upload a football match report (CSV / structured
text / one-pager PDF) and get a content pack appropriate to football
(goal scorers, clean sheets, man-of-the-match, league position,
fixture preview). Same for rugby (tries, conversions, line-out
stats, set-piece dominance, man-of-the-match).

FILES TO MODIFY:
- src/mediahub/sports/football/: events.py (match events: goals,
  assists, yellow/red cards, subs), parser.py (parse common
  match-report formats including OPTA-style CSV if available),
  achievement_logic.py (goal-of-the-match, hat-trick detection,
  clean-sheet recognition), templates.py.
- src/mediahub/sports/rugby/: similar structure for rugby union
  (tries, conversions, penalties, man-of-the-match, line-out wins).
- Generalise the existing pb_logic.py — for team sports it's
  achievement_logic.py with different primitives. Refactor the
  swimming/athletics modules to use a common interface
  (sports/<sport>/achievement_logic.py) where appropriate.
- /upload: detect sport from file content + filename.
- /organisation: add a "Sports" multi-select so a club can declare
  it covers multiple sports.

ACCEPTANCE CRITERIA:
- A hat-trick is correctly detected and surfaced as the headline
  achievement in football.
- A clean sheet is correctly attributed to the goalkeeper.
- Rugby man-of-the-match selection prefers tries > conversions >
  metres made if not explicitly named in the input.
- A clean league position (1st in the table) is detected as a
  high-priority achievement.
- All previous sports tests (swimming + athletics) still pass.

DON'T BREAK:
- pytest at the new baseline (target 280+).
- Phase 1 features remain functional on football/rugby output.

TESTS:
- tests/test_football_*.py and tests/test_rugby_*.py covering parsing,
  achievement detection, and caption generation.

```

##### Verification Prompt

```
Verify Step 11 (Football + Rugby) end-to-end.

1. Tests: full pytest. Target 280+ passed.
   - python -m pytest tests/test_football_*.py tests/test_rugby_*.py -v.

2. Hat-trick detection:
   - Upload a football match where player X scored 3 goals.
   - Confirm the top-ranked card mentions a hat-trick.
   - Confirm the visible-intelligence reasoning includes goal count.

3. Clean sheet attribution:
   - Upload a 2-0 win match. Confirm the goalkeeper's card mentions
     "clean sheet".

4. Rugby try detection:
   - Upload a rugby match with 4 tries by player Y. Confirm Y is the
     headline and the caption uses rugby-appropriate language.

5. Multi-sport club:
   - Set a club's sports to ["swimming","football"]. Upload swimming.
     Confirm swimming pipeline. Upload football. Confirm football
     pipeline.

6. Cross-sport caption consistency:
   - Same voice_profile applied to a football caption and a swimming
     caption — the stylistic signature (sentence length, hashtag
     count) should match across both.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 12: Native Publishing APIs (Replace Buffer Dependency)

##### Context
Step 6 shipped Buffer integration to close the publishing gap fast. This step builds direct integrations to Instagram Graph API, Facebook Pages, X (v2), LinkedIn Marketing, and TikTok Business so MediaHub no longer depends on Buffer for the core publishing path.

##### Implementation Prompt

```
Replace Buffer dependency with native publishing APIs.

GOAL: a user can connect Instagram Business, Facebook Pages, X,
LinkedIn (Company Page), and TikTok Business directly. Scheduling
no longer requires a Buffer account.

FILES TO MODIFY:
- src/mediahub/publishing/instagram.py: Graph API; OAuth via
  Facebook Login. Single-image + reels upload + caption.
- src/mediahub/publishing/facebook.py: Pages API; OAuth via
  Facebook Login.
- src/mediahub/publishing/x_twitter.py: v2 API; OAuth 2.0 with PKCE.
- src/mediahub/publishing/linkedin.py: Marketing Developer Platform;
  OAuth 2.0.
- src/mediahub/publishing/tiktok.py: TikTok Business API; OAuth 2.0.
- src/mediahub/publishing/scheduler.py: a unified Scheduler interface
  (queue, schedule_at, dispatch_now) so the UI calls one API
  regardless of platform.
- A background worker (lightweight — Flask-APScheduler or a simple
  cron-style polling thread) that dispatches scheduled posts at
  their scheduled_at time.
- /settings: native "Connect Instagram", "Connect Facebook" etc.
  buttons (in addition to the existing Buffer field, which remains
  as a fallback).

ACCEPTANCE CRITERIA:
- A user can complete the OAuth flow for each platform and the
  resulting access tokens are stored encrypted (Fernet) in
  DATA_DIR / "secrets" / <user_id>.json.
- Scheduling a post via the UI dispatches to the right platform at
  the right time.
- Token refresh is handled before each dispatch.
- Buffer remains available as a fallback channel; users can choose
  per-card whether to dispatch direct or via Buffer.

DON'T BREAK:
- pytest at the new baseline (target 290+ with publishing tests).
- All earlier features still work.

TESTS:
- tests/test_native_publishing.py: mocked OAuth + dispatch, token
  refresh, dispatcher worker.

landscape closing), §6 Workstream 3.x.
```

##### Verification Prompt

```
Verify Step 12 (Native publishing) end-to-end.

1. Tests: full pytest + tests/test_native_publishing.py -v.

2. OAuth flows (mocked):
   - For each of the 5 platforms, simulate the OAuth callback with a
     fixed test token. Confirm the token is stored encrypted (not
     plaintext) in the per-user secrets file.

3. Dispatch (mocked):
   - Schedule a post with scheduled_at = now + 30s.
   - Wait 45s. Confirm the post was dispatched via the mocked API.
   - Confirm the workflow state shows schedule_status=published.

4. Token refresh:
   - Set an expired-token scenario. Confirm the dispatcher refreshes
     the token before dispatching, or surfaces a clear "re-connect"
     error if refresh fails.

5. Buffer fallback:
   - Confirm Buffer is still selectable per-card and the Buffer
     dispatch path still works.

6. Security:
   - grep the codebase for any access_token logging — must be zero.
   - Confirm the encrypted secrets file mode is 0600.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Phase 3 — Leadership (Steps 13-17, target months 9-18)

#### Step 13: Integration Moat — Hy-Tek, TeamUnify, ClubBuzz Importers

##### Context
The single most defensible distribution moat against horizontal entrants is direct integration with the software clubs already use. Hy-Tek MeetManager (results), TeamUnify (club management), ClubBuzz (UK clubs), SwimManager — each integration is one to three engineering weeks and creates a switching cost.

##### Implementation Prompt

```
Build first-class importers for the most-used club software.

GOAL: a user with a TeamUnify or ClubBuzz account can connect MediaHub
once, and every new meet result automatically flows into MediaHub
without a manual upload.

FILES TO MODIFY:
- src/mediahub/integrations/teamunify.py: OAuth or API key auth,
  poll for new meet results, ingest as a new run, run the full
  pipeline.
- src/mediahub/integrations/clubbuzz.py: same pattern.
- src/mediahub/integrations/hytek_meetmanager.py: file-format
  importer for the .hy3 format with deeper coverage than the existing
  parser (handle all common event codes, age groups, time conversions).
- src/mediahub/integrations/splash_meet_manager.py: file-format
  importer for Splash's export format.
- /settings: new "Integrations" section with one-click connect
  buttons.
- A background polling worker for the API-based integrations.

ACCEPTANCE CRITERIA:
- A connected TeamUnify account auto-ingests new meets within 1 hour
  of them appearing in TeamUnify.
- Hytek and Splash file imports produce identical content packs to
  manual uploads.
- A revoked integration cleanly stops polling and surfaces in the UI.

DON'T BREAK:
- Manual file upload still works.
- pytest at the new baseline (target 300+).

TESTS:
- tests/test_integrations_*.py: mocked API responses, end-to-end
  ingestion.

```

##### Verification Prompt

```
Verify Step 13 (Integrations) end-to-end.

1. Tests: full pytest + tests/test_integrations_*.py -v.

2. TeamUnify mocked happy path:
   - Connect with a test API key.
   - Push a fake new-meet event via the mock server.
   - Confirm a new run appears in MediaHub within the polling interval.
   - Confirm the run produces a valid content pack.

3. Hytek parity:
   - Take an existing .hy3 file that worked with the manual uploader.
   - Run it through the new importer. Confirm the resulting content
     pack is identical (same number of achievements, same ranking).

4. Splash importer:
   - Process a sample Splash file. Confirm event detection + PB
     attribution.

5. Disconnection:
   - Revoke the test API key. Confirm polling stops within 1 polling
     cycle and the /settings page shows "Disconnected".

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 14: Enterprise Tier — Multi-Club Orchestration

##### Context
The financial backbone of the strategy. Governing bodies, leagues, federations, and large university athletic departments need multi-club orchestration: branded league templates, federation-wide engagement analytics, sponsorship reporting across clubs.

> ⚠️ **Partly promoted (2026-06 reconcile).** The **Organisation → Club → Run hierarchy /
> multi-tenancy** half of this step is no longer a far-future "leadership" item — it is
> pulled forward to **Phase C · PC.3** as a **blocking prerequisite**, because
> single-instance-per-club can't scale (ops/support rise linearly vs. fixed founder
> hours). The *federation analytics / template-push / sponsorship-report* surfaces remain
> later-stage. See
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md).

##### Implementation Prompt

```
Ship the enterprise tier: multi-club orchestration.

GOAL: a Federation user (Stripe enterprise plan from Step 7) can
manage up to 50 clubs from one account, push league-branded templates
to all clubs, view aggregated engagement analytics, and produce
sponsorship reports.

FILES TO MODIFY:
- Data model: introduce Organisation (governing body / league) →
  Club → Run hierarchy. Backward-compatible: a club without an
  organisation is treated as a standalone (today's default).
- src/mediahub/enterprise/: new module:
    OrganisationProfile dataclass
    league_templates.py — manage and distribute templates
    aggregated_analytics.py — engagement metrics across child clubs
    sponsorship_report.py — sponsor-exposure metrics with citations
- new pages:
  /federation — dashboard
  /federation/clubs — manage child clubs
  /federation/templates — push templates
  /federation/analytics — aggregated metrics
  /federation/sponsorship — sponsor reports
- billing: Stripe plan "federation" unlocks these pages.

ACCEPTANCE CRITERIA:
- A federation user can add a child club and the child club's owner
  receives an invite link to accept the relationship.
- Pushing a template to all child clubs makes the template available
  in each club's Turn-Into picker.
- Aggregated analytics correctly sum engagement across all child
  clubs and never double-count.
- A sponsorship report can be exported as a branded PDF.

DON'T BREAK:
- Standalone clubs (no parent organisation) work exactly as before.
- pytest at the new baseline (target 310+).

TESTS:
- tests/test_enterprise_*.py covering hierarchy, template push,
  analytics aggregation, sponsorship report generation.

scale).
```

##### Verification Prompt

```
Verify Step 14 (Enterprise tier) end-to-end.

1. Tests: full pytest + tests/test_enterprise_*.py -v.

2. Hierarchy:
   - Create a federation account and three child clubs.
   - Confirm the federation dashboard shows all three.
   - Sign in as one child club — confirm it can see only its own runs.

3. Template push:
   - Federation pushes a "Meet Recap League Template".
   - Each child club's Turn-Into picker now includes it.

4. Analytics:
   - Federation analytics page sums engagement across the three clubs.
   - Manually verify the sum equals the per-club totals.

5. Sponsorship report:
   - Generate a sponsorship PDF for the federation's headline sponsor.
   - Confirm the PDF includes per-club sponsor activations with
     citations (which post, which date, which platform).

6. Plan guard:
   - On a non-federation plan, the federation pages return a clear
     upgrade prompt, not a 404.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 15: Conversational / Agentic Caption Editing

##### Context
Lately's Kately and Holo's chat-editor demonstrate the next interaction primitive: a conversational layer over the existing content pack. "Make this caption more energetic", "Add a thank-you to the parents", "Generate a TikTok script from this meet" — the user issues natural-language instructions and the agent operates over the existing assets.

##### Implementation Prompt

```
Add a conversational editing surface to the content pack.

GOAL: every card on the review page has a chat panel where the user
can issue natural-language edit commands ("shorter", "more energetic",
"in Spanish", "add a sponsor mention", "generate a TikTok variant").
The agent uses the existing tools (generate_caption_for_tone,
sponsor.apply, motion.render_story_card) rather than free-form
generation.

FILES TO MODIFY:
- src/mediahub/agent/__init__.py
- src/mediahub/agent/tools.py: register the tools the agent can call
  (regenerate_caption, change_tone, translate_caption, add_sponsor,
  generate_motion, generate_reel_variant).
- src/mediahub/agent/runner.py: a small tool-use loop using the
  existing LLM (Gemini or Anthropic) with structured tool calling.
- /review page: a chat panel toggle next to each card.
- Every agent action writes an audit entry (who, when, what tool,
  what arguments, what result) to DATA_DIR/agent_audit/<run_id>.jsonl.

ACCEPTANCE CRITERIA:
- "Make this shorter" produces a caption ≤80% of the original length.
- "Make this in Spanish" produces Spanish output.
- "Add a sponsor mention" calls the sponsor.apply tool and produces
  a sponsor variant.
- The agent NEVER publishes — every change is staged and requires
  the user's Save click.

DON'T BREAK:
- pytest at the new baseline (target 320+).
- All earlier features still work.

TESTS:
- tests/test_agent_*.py: tool invocation, no-publish guarantee,
  audit log integrity.

§6 Workstream 3.3.
```

##### Verification Prompt

```
Verify Step 15 (Agentic editing) end-to-end.

1. Tests: full pytest + tests/test_agent_*.py -v.

2. Edit commands:
   - "shorter" → length reduction confirmed.
   - "more energetic" → tone shift confirmed (compare against baseline).
   - "in Spanish" → output is Spanish (langdetect).
   - "add a sponsor mention" → sponsor hashtag present.

3. No-publish guarantee:
   - Issue 10 agent commands. Confirm NONE of them dispatched a
     publish action. The audit log should show zero publishing tool
     calls.

4. Audit:
   - For each agent action, confirm DATA_DIR/agent_audit/<run_id>.jsonl
     has a corresponding entry with full arguments and result.

5. Tool safety:
   - Try to inject "delete this run" via the chat input. Confirm the
     agent does not call any destructive tool (no such tool exists in
     the registry).

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 16: Template Marketplace

##### Context
Community templates raise switching cost. Once a club has invested in templates that exist only on MediaHub — branded recap layouts, voice profiles, season-narrative arcs — leaving the platform costs them their accumulated content infrastructure.

##### Implementation Prompt

```
Ship a community template marketplace.

GOAL: clubs and federations can publish templates (visual layouts,
voice profiles, Turn-Into recipes, sponsor activation patterns) for
other clubs to fork. Templates are versioned and reviewable.

FILES TO MODIFY:
- src/mediahub/marketplace/: new module.
- Template types: visual_layout (graphic + motion templates),
  voice_profile_template (anonymised voice patterns),
  turn_into_recipe (which 7 artefacts a Turn-Into produces and how),
  sponsor_activation (predefined sponsor variants for common partners).
- /marketplace page: browse, preview, fork.
- /marketplace/submit: submit a template (with review queue).
- /marketplace/admin: review/approve/reject submissions (federation
  + MediaHub admin role).

ACCEPTANCE CRITERIA:
- A submitted template enters a review queue.
- Forking a template clones it into the user's own club profile —
  edits to the fork do not affect the source.
- Templates are versioned; the user can upgrade their fork to a newer
  source version.
- Marketplace search by sport, audience size, language.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_marketplace_*.py covering submission, fork, version
  upgrade, isolation between fork and source.

```

##### Verification Prompt

```
Verify Step 16 (Template marketplace) end-to-end.

1. Tests: full pytest + tests/test_marketplace_*.py -v.

2. Submit + approve:
   - As a club user, submit a visual_layout template.
   - As an admin, approve it.
   - The template now shows in /marketplace.

3. Fork:
   - As another club, fork the template. Confirm the fork lives in
     the new club's profile.
   - Edit the fork. Confirm the source is unchanged.

4. Version upgrade:
   - As the source owner, publish version 2.
   - The fork shows an "upgrade available" badge. Confirm the upgrade
     applies cleanly.

5. Search:
   - Search by sport=athletics. Confirm only athletics templates
     appear.

6. Privacy:
   - Confirm voice_profile_template templates are anonymised (no
     PII / no club name leaked) before they enter the public
     marketplace.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 17: Sponsor-Side Analytics Product

##### Context
The final defensible primitive: a sponsor-facing product that proves to the sponsor the value of their brand exposure across a club's content. Nota and FanWord do not do this at small-club scale; this is a category MediaHub can own.

##### Implementation Prompt

```
Build a sponsor-side product surface.

GOAL: a sponsor (the brand paying the club) can log in and see a
dashboard of all the times their brand appeared in content produced
by clubs they sponsor, with engagement metrics and an estimated
brand-exposure value.

FILES TO MODIFY:
- New user role: sponsor. Sponsor accounts are linked to specific
  club profiles via an invitation flow.
- src/mediahub/sponsor_dashboard/: new module.
- /sponsor — sponsor dashboard.
- /sponsor/exposure — list of every post where this sponsor's brand
  appeared, with date, platform, engagement, and a thumbnail of
  the asset.
- /sponsor/value — estimated brand-exposure value (impressions ×
  CPM-equivalent based on the platform).
- /sponsor/export — branded PDF report.

ACCEPTANCE CRITERIA:
- A sponsor can only see content produced by clubs they sponsor.
- Engagement metrics are pulled from the publishing layer's
  post-success records (Step 12).
- The brand-exposure value calculation is documented and auditable
  (open the value calculation in a tooltip).
- The PDF export is reproducible and includes citations to every
  source post.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_sponsor_dashboard_*.py: scoping (sponsor sees only their
  clubs), metric calculation determinism, PDF export shape.

```

##### Verification Prompt

```
Verify Step 17 (Sponsor-side product) end-to-end.

1. Tests: full pytest + tests/test_sponsor_dashboard_*.py -v.

2. Scoping:
   - Sponsor A is linked to Club 1 and Club 2 (not Club 3).
   - Sponsor A's exposure page shows posts from Club 1 and 2 only.
   - Confirm Club 3's posts do NOT appear in any sponsor query.

3. Metric calculation:
   - For a post with known engagement, manually compute the value
     using the documented formula. Confirm the dashboard matches.

4. PDF export:
   - Export a sponsor report. Confirm it opens, contains citations,
     and is reproducible (re-export, byte-equality of the content
     section).

5. Sponsor cannot leak admin:
   - As a sponsor, attempt to access /federation, /admin,
     /api/runs/<id>/turn-into. All must return 403.

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Final Audit — After Step 17 (or any time after Step 7)

##### Context
At any milestone the full product should be audited end-to-end. This audit is the prompt to run after a major release.

##### Audit Prompt

```
Conduct a full MediaHub product audit.

OBJECTIVE: confirm that every feature shipped to date — every step
in the roadmap that has been completed — still works end-to-end with
no regressions, and that the product as a whole holds up against the
quality bar set by the competitors documented in
docs/research/generation-engine-competitor-evaluation.md.

PHASE A — Automated tests:
1. python -m pytest tests/ -q. Report pass/skip/fail counts.
2. python -c "from mediahub.web.web import create_app; create_app()".
3. Boot the app: python -m mediahub.web.web (background).
4. Confirm 0 ERROR-level log lines on a clean boot.

PHASE B — Route sweep:
For each of these routes, confirm a 200 (or correct 30x/40x):
- GET /, /add-input, /upload, /organisation, /settings, /privacy
- GET /pricing, /signup, /login (if Step 7 shipped)
- GET /free-text, /weekend-preview, /sponsor-post, /session-update
- GET /spotlight (if implemented)
- GET /federation, /federation/clubs (if Step 14 shipped)
- GET /marketplace (if Step 16 shipped)
- GET /sponsor (if Step 17 shipped)

PHASE C — Critical user journeys, for each completed step:
- Brand DNA capture: paste a URL, confirm preview, save. Should work.
- Voice imitation: paste 5 examples, save, confirm voice_profile.
- Visible intelligence: open any run, confirm "Why this card?" works.
- Motion: render a story card; render a reel.
- Turn-Into: produce 6-7 artefacts from a meet.
- Buffer or native publishing: schedule a mocked post.
- Commercial: signup, login, upgrade (Stripe test mode).
- Athletics: upload athletics sample, confirm pipeline.
- Athlete page: generate a token, fetch /a/<token>.
- Sponsor mode: toggle on a card, confirm variant.
- Football/Rugby: upload sample, confirm hat-trick / clean sheet.
- Native publishing OAuth: complete one platform's mock flow.
- Integrations: TeamUnify mocked auto-ingest.
- Enterprise: multi-club orchestration.
- Agent: 5 edit commands all hit tools correctly.
- Marketplace: submit + approve + fork.
- Sponsor dashboard: scope correctness + PDF export.

PHASE D — Cross-cutting quality:
- Visual polish: open / and the review page in a browser; screenshot.
  Compare against tryholo.ai's homepage. List any obvious gaps.
- Performance: time a fresh upload-to-content-pack run end-to-end.
  Target < 90s for a 200-swim meet.
- Security: grep the codebase for hardcoded API keys, exposed
  secrets in logs, Path("data/...") relative paths. Report any.
- Test isolation: confirm tests do not write to the real
  data/secrets.json or club_profiles/*.json.
- Accessibility: run a quick a11y scan on the review page. Report
  contrast and keyboard-nav issues.

PHASE E — Strategic position:
For each of the competitors in `docs/research/generation-engine-competitor-evaluation.md`, evaluate where
MediaHub now stands on a 5-point Leading / Competitive / Adequate /
Underdeveloped / Absent scale across the 6 dimensions:
1. Input modality
2. Intelligence layer
3. Output surface
4. Brand context capture
5. Distribution
6. Commercial model

Cross-reference with the competitor analysis in `docs/research/`. Has MediaHub moved up
the matrix on the dimensions Phase 1 targeted? Are there new gaps
that have opened?

OUTPUT FORMAT:
Return a structured audit report:
- Phase A: automated tests results
- Phase B: route table with status codes
- Phase C: per-step pass/fail table
- Phase D: a quality scorecard (1-5) per cross-cutting area
- Phase E: an updated competitive matrix
- Top 5 regression risks (ordered by severity)
- Top 5 next-step recommendations
- A single "release readiness" verdict: Ship / Hold / Block.
```

---

#### Notes on running this roadmap

**Branching.** Every step is a feature branch off `dev`; never merge to `main` without approval. Use names like `step-01-brand-dna-capture`, `step-06-buffer-publishing`. The verification prompt is run before opening the merge request.

**Sequencing.** Steps 1-7 (Phase 1) should be done strictly in order — each builds on the previous. Steps 8-12 (Phase 2) can be partially parallelised once Step 8 (sports architecture) is in. Steps 13-17 (Phase 3) are highest value when done in the order shown but Step 14 (enterprise tier) is the highest financial priority; consider promoting it earlier if revenue is the limiting factor.

**Test budget.** Maintain ≥ 253 passed at every step. Each step adds 5-15 tests, so by Step 17 expect 350+ passing.

**When verification fails.** Paste the failing report back into the implementation session of the same step. Do not move forward until a clean verification report is produced.

**When you stop following the prompts.** Each step is designed to be readable on its own. If during implementation Claude needs context that the prompt didn't provide, the prompt is at fault — improve the prompt and re-run rather than letting Claude guess.

**Source of truth.** This roadmap and the analyses in `docs/research/` (the competitor evaluation + the generative-AI thesis) are the paired references.

---

## Appendix C — Adaptive Theming Engine (1.6): Verification Prompts

> *Stage IDs in this appendix (A–J) map 1:1 to the §1.6 Stage table above. §1.6 is **shipped** — all ten stages are in `main`, live by default, and green. Unlike Appendix A (which builds an as-yet-unbuilt engine), this appendix is **verification-only**: paste-into-a-session acceptance audits that independently confirm each shipped stage still meets its part of the §1.6 acceptance criteria. There are no implementation prompts here — the code already exists.*

**What this is.** A per-stage acceptance-audit harness for the now-shipped
Adaptive Theming Engine. Each stage below has a **Context** (what shipped +
the real files) and a **Verification prompt** (paste into a fresh session).
The prompts are read-only audits plus the test suite; none should need to
modify the engine. A final **full-engine acceptance audit** ties the
per-stage checks back to the five numbered acceptance criteria in §1.6.

**Date:** May 2026 · **Built against:** `main` with Stages A–J merged (the
`theming/` package, the five `static/theme/*.css` layers, `theme_store.py`,
and `docs/THEMING.md`).

**Why verify a shipped feature.** The engine touches every rendered page and
four output media (web, motion, email, static graphic). It is exactly the
kind of cross-cutting surface where a later refactor can silently regress
contrast, drift one medium's palette from the others, or break the cascade.
These prompts are the regression harness that proves it still holds.

---

### 1. The shared verification preamble (every prompt inherits this)

> **Preamble — read before doing anything.** You are auditing MediaHub's
> **shipped** Adaptive Theming Engine (ROADMAP §1.6) in the repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md`,
> `docs/THEMING.md`, and the file(s) named in the task. This is a
> **verification** task — read code, run tests, exercise routes, and report a
> pass/fail checklist. Hard rules:
> - **The colour-science engine is deterministic and off-limits to AI.**
>   `theming/` (palette, roles, contrast, cvd, quality, repair, seed_extract,
>   harmony, logo_chip) and the CIEDE2000 / APCA / Machado maths must stay
>   deterministic. If a check fails, **report it** — do **not** "fix" it by
>   routing a judgement through Gemini/Anthropic, and do not add a hand-tuned
>   per-seed override (the point of §1.6 is intelligence in the algorithm,
>   not a lookup table).
> - **No test cheating.** If you run the suite, do not delete, skip, or weaken
>   a test to make it pass. A red test is a finding, not an obstacle.
> - **Determinism is a property under test.** Same seed → byte-identical
>   palette, every time. If you find non-determinism, that is a failure.
> - **Read-only by default.** These prompts should not need to modify the
>   engine. If you find a genuine gap, report it with a minimal repro; only
>   fix it in a **separate, clearly-scoped** branch + PR with the user's
>   go-ahead — never fold an engine change into a verification pass.
> - **Run the tests named in the task plus the full suite**
>   (`python -m pytest tests/ -q`); confirm no new failures vs `main`.
> - **Report format:** a pass/fail checklist, one line per claim, citing the
>   `file:line` or test name that proves each.

---

### 2. Per-stage verification prompts

#### Stage A — Token foundation
**Shipped:** ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`,
`--mh-primary`, …) defined in `static/theme/theme-base.css` and surfaced via
`web/theme_tokens.py`; every animatable seed/colour registered with
`@property { syntax: "<color>"; inherits: true }`. Tests:
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage A (token foundation). Confirm: the ~25 documented
> role tokens all exist in `theme-base.css`; each animatable colour variable
> (the `--mh-*-seed` set and the role tokens that transition) is registered
> via `@property` with `syntax: "<color>"` (grep the `@property` blocks); no
> transitioned colour relies on an untyped custom property; and migrating to
> tokens introduced no visual change for the default brand (the token values
> resolve to the pre-token palette). Run `tests/test_theme_tokens.py` + the
> full suite. Report any token that is missing or unregistered.

#### Stage B — Colour-science library
**Shipped:** the `src/mediahub/theming/` package — `seed_extract.py`,
`palette.py`, `roles.py`, `contrast.py` (APCA Lc + WCAG2), `cvd.py` (Machado
2009), `quality.py` (`PaletteQualityReport`), `repair.py`, `harmony.py`
(Cohen-Or). Deps `materialyoucolor` + `coloraide` in `pyproject.toml` /
`requirements.txt`. Entry point `theming.derive_theme(seed)`. Tests:
`tests/theming/test_palette.py`, `test_contrast.py`, `test_cvd.py`,
`test_quality.py`, `test_repair.py`, `test_seed_extract.py`,
`test_harmony.py`.

**Verification prompt:**
> [Preamble.] Verify Stage B (colour-science package). Confirm: `derive_theme`
> is deterministic (call it twice on one seed → byte-identical `to_json()`);
> the pipeline is seed → HCT → 5×13 tonal palettes → MD3 roles → APCA/ΔE/CVD
> gates → bounded repair loop (`repair_max_iters` honoured, never infinite);
> `contrast.py` APCA Lc and `cvd.py` Machado matrices match their known
> fixtures; no module makes a network/LLM call (grep `theming/` for
> `requests`, `httpx`, `media_ai`, `ai_core` — none); and an empty/garbage
> seed returns the fallback theme rather than raising. Run all
> `tests/theming/test_*` + the full suite. State the determinism result
> explicitly.

#### Stage C — CSS architecture
**Shipped:** the inline `<style>` block is extracted into `static/theme/`
across `theme-base.css`, `theme-derive.css` (the `color-mix(in oklch, …)` +
relative-colour derivation graph), `theme-components.css`, `theme-cascade.css`,
and `theme-fallback.css` (the `@supports not (color: oklch(from red l c h))`
precomputed ramp). `light-dark()` drives surface/ink pairs off
`prefers-color-scheme`. Tests: `tests/test_theme_static_files.py`,
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage C (CSS architecture). Confirm: the bulk of the
> chrome's colours are *derived* in CSS (grep `theme-derive.css` for
> `color-mix(in oklch` and `oklch(from var(--mh-brand-seed)` — the derivation
> graph is present, not a hardcoded ramp); `light-dark()` is used for
> surface/ink pairs and `prefers-color-scheme` is honoured; the Safari
> long-tail fallback lives inside an `@supports not (...)` block in
> `theme-fallback.css` with no JS polyfill; and the CSS is served as static
> files with a cache-busting URL (not re-inlined per request). Run
> `tests/test_theme_static_files.py` + the full suite. Report the count of
> hardcoded brand-colour hex literals found in colour-derivation positions in
> the CSS layers (expected: ~0).

#### Stage D — Theme delivery (Flask)
**Shipped:** a `before_request` hook + `_theme_seed_style_block()` emit an
inline `<style id="mh-theme-seed">` carrying the active org's brand-seed
override into `<head>` *before* the external stylesheet (zero FOUC).
Resolution is three-tier (flag-off → pinned-org palette → generic-default).

**Verification prompt:**
> [Preamble.] Verify Stage D (theme delivery). Boot the app and request a
> page; confirm the inline `<style id="mh-theme-seed">` block appears in
> `<head>` **before** the external `theme-base.css` link (so there is no flash
> of un-themed content) and carries the active organisation's seed. Confirm
> the three-tier resolution in `_theme_seed_style_block()`:
> `MEDIAHUB_ADAPTIVE_THEME=0` emits nothing (falls through to the static
> cascade), a pinned org uses its `derived_palette`, and no-org uses the
> generic-default theme. Confirm the payload is small (hundreds of bytes, not
> the full palette). Report the head ordering and the three-tier behaviour.

#### Stage E — "Looks right" cascade
**Shipped:** the organisation-finalise handler derives + persists the palette
(`ensure_derived_palette(force=True)`) and navigates via
`document.startViewTransition`; `theme-cascade.css` carries
`@view-transition { navigation: auto }`, the `:root` seed `transition`, and
the `prefers-reduced-motion: reduce` instant-swap override. Tests:
`tests/test_theme_cascade.py`, `tests/test_browser_cascade.py`.

**Verification prompt:**
> [Preamble.] Verify Stage E (the cascade). Confirm: the "Looks right — start
> creating" finalise path saves the brand kit, derives + persists
> `derived_palette`, and wraps the navigation in `document.startViewTransition`
> (degrading to a normal nav where unsupported); `theme-cascade.css` contains
> the `@view-transition` rule, the `:root` colour `transition`, and a
> `@media (prefers-reduced-motion: reduce)` block that disables both; and
> because every derived var is a `color-mix`/`oklch(from …)` of the seed,
> changing the seed alone interpolates the whole palette in lockstep. Run
> `tests/test_theme_cascade.py`; run `tests/test_browser_cascade.py` with
> `MEDIAHUB_RUN_BROWSER_TESTS=1` if a browser is available (else note it's
> gated). Report each contract check.

#### Stage F — Logo intelligence
**Shipped:** `theming/logo_chip.py` defaults to a neutral chip behind an
uploaded logo and computes a "safe to drop chip" decision (dominant
non-neutral colour vs active surface in OKLCH; ΔE2000 + APCA Lc gates in both
polarities); MediaHub's own marks use `fill="currentColor"`; uploaded SVG
marks are never recoloured. Tests: `tests/test_logo_chip.py`,
`tests/test_mediahub_mark_theming.py`.

**Verification prompt:**
> [Preamble.] Verify Stage F (logo intelligence). Confirm: `logo_chip.py`
> defaults to a neutral chip and exposes a deterministic "safe to drop chip"
> test driven by ΔE2000 + APCA Lc in both light and dark polarities;
> MediaHub's *own* SVG marks use `fill="currentColor"` so the chrome adapts to
> ink colour; and the path for *uploaded* logos never recolours or injects
> `currentColor` into an unknown mark (it only adds/removes a chip behind it).
> Run `tests/test_logo_chip.py` + `tests/test_mediahub_mark_theming.py` + the
> full suite. Report the chip-decision logic and confirm the "never recolour
> uploaded marks" guarantee holds.

#### Stage G — Single source of truth (motion + email + static graphic)
**Shipped:** `theming/theme_store.py` writes the DTCG palette JSON to
`DATA_DIR/themes/<profile_id>.json`; `visual/motion.py` passes it as
`inputProps` to `render.js`; `brand/newsletter_renderer.py` Premailer-inlines
the resolved hexes; `graphic_renderer/render.py` reads the same JSON instead
of `BrandKit.primary_colour`. Tests: `tests/test_theme_store.py`,
`test_motion_theme_store.py`, `test_newsletter_theme_store.py`,
`test_graphic_renderer_theme_store.py`.

**Verification prompt:**
> [Preamble.] Verify Stage G (single source of truth). Confirm there is
> exactly **one** palette source — the `theme_store.py` JSON at
> `DATA_DIR/themes/<profile_id>.json` — and that all four consumers read it:
> `visual/motion.py` (→ Remotion `inputProps`), `brand/newsletter_renderer.py`
> (Premailer-inlined hexes, since email clients don't support custom
> properties), `graphic_renderer/render.py`, and the web cascade. Pick one
> seed, derive its theme, and assert the **same** role hex appears in the
> motion props, the inlined email HTML, the static graphic, and the CSS seed
> block — **zero drift across media**. Run the four `*_theme_store.py` tests +
> the full suite. Report the cross-media hex comparison.

#### Stage H — Explainability + QA
**Shipped:** `PaletteQualityReport` (`quality.py` `to_summary()` +
`to_detail()`) logs APCA Lc per role pair, the CIEDE2000 matrix for brand ×
{neutral, success, warning, danger}, Machado-CVD ΔE under
deutan/protan/tritan, the Cohen-Or harmonic-fit energy, and a decision trace;
a "Why does my theme look like this?" panel on `/organisation/setup` shows the
decisions + lets a committee member override a role (logged, with a
cultural-clash warning if it lowers a status colour's ΔE); a non-blocking
callout fires when the hostile-seed repair loop ran. Tests:
`tests/test_quality_detail.py`, `test_repair_callout.py`,
`test_org_palette_confirm.py`.

**Verification prompt:**
> [Preamble.] Verify Stage H (explainability + QA). Confirm: every derivation
> produces a `PaletteQualityReport` with APCA Lc per text-on-surface pair, the
> brand×status CIEDE2000 matrix, Machado-CVD ΔE under all three CVD types, the
> Cohen-Or harmonic-fit energy, and a human-readable decision trace; the "Why
> does my theme look like this?" panel renders these on `/organisation/setup`;
> a manual role override is persisted *and* logged, and lowering a status
> colour's ΔE raises a cultural-clash warning; and when the repair loop fires
> on a hostile seed, a non-blocking callout explains *which status colour* was
> nudged and why (never silently rewriting the brand colour). Run
> `tests/test_quality_detail.py` + `test_repair_callout.py` +
> `test_org_palette_confirm.py` + the full suite. Report each explainability
> surface.

#### Stage I — Test coverage
**Shipped:** `tests/theming/` with golden-master snapshots for ~30
representative seeds (incl. fluorescent `#DFFF00`, muddy `#2A3A1A`, near-white
`#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, +
real club colours) in `seeds_catalogue.py` / `snapshots/`, plus
APCA/CVD/quality/repair unit tests; `tests/test_browser_cascade.py` is the
Playwright/browser-use end-to-end (gated on `MEDIAHUB_RUN_BROWSER_TESTS=1`).

**Verification prompt:**
> [Preamble.] Verify Stage I (test coverage). Confirm: the golden-snapshot set
> in `tests/theming/` covers the hostile seeds
> (neon/muddy/near-white/near-black/pure-primary) **and** real club colours;
> the gate tests actually assert the §1.6 thresholds (APCA Lc ≥ 75 for
> text-on-surface; CIEDE2000 ≥ 5 between adjacent tonal stops; ≥ 15 between
> brand and each status colour; Machado-deuteranopia ΔE2000 ≥ 10 for the same
> triples; Cohen-Or fit below threshold); the snapshots regenerate
> deterministically (no flakiness); and `tests/test_browser_cascade.py` exists
> and is correctly gated. Run `python -m pytest tests/theming/ -q` and report
> the count + whether any threshold is asserted more weakly than §1.6 states.

#### Stage J — Cutover + polish
**Shipped:** `_adaptive_theme_enabled()` reads `MEDIAHUB_ADAPTIVE_THEME`
(default **on**; `0/false/off/no` rolls back to the static cascade) — J1;
`_default_theme_json()` runs the generic-default BrandKit (`#0E2A47` /
`#C9A227`) through the pipeline for unconfigured first-run — J2;
`docs/THEMING.md` documents the architecture, role-token table,
operator-overridable variables, and academic citations — J3. Tests:
`tests/test_adaptive_theme_flag.py`, `test_default_theme.py`,
`test_theming_md.py`.

**Verification prompt:**
> [Preamble.] Verify Stage J (cutover + polish). Confirm: `MEDIAHUB_ADAPTIVE_THEME`
> defaults **on**, and setting it to `0`/`false`/`off`/`no` cleanly reverts
> every page to the static Stage-A cascade with no errors (the on-disk JSON,
> audit panel, and repair callout keep working regardless); the generic-default
> brand kit is themed through the same pipeline (unconfigured deployments get
> the upgrade, no regression); and `docs/THEMING.md` documents the
> architecture, the role-token table, the variables an operator may safely
> override, and the inline academic citations. Run
> `tests/test_adaptive_theme_flag.py` + `test_default_theme.py` +
> `test_theming_md.py` + the full suite. Report the flag round-trip and the
> default-theme behaviour.

---

### 3. Full-engine acceptance audit (maps to the §1.6 acceptance criteria)

**Verification prompt:**
> [Preamble.] Run the §1.6 "definition of done" end-to-end and report a single
> scorecard against the five acceptance criteria:
> 1. **Hostile-seed gate.** Drive ~30 representative seeds (incl.
>    neon/muddy/near-greyscale/pure-primary) through `derive_theme`; assert
>    APCA Lc ≥ 75 for every text-on-surface role pair, CIEDE2000 ≥ 5 between
>    adjacent tonal stops, ≥ 15 between brand and each of
>    success/warning/danger, Machado-deuteranopia ΔE2000 ≥ 10 for those
>    triples, and Cohen-Or fit below threshold. Report any seed that fails any
>    gate.
> 2. **Live cascade.** Confirm the cascade works in Chromium (run
>    `tests/test_browser_cascade.py` with `MEDIAHUB_RUN_BROWSER_TESTS=1` if
>    available) and degrades to instant nav where View Transitions is
>    unsupported; reduced-motion users get an instant swap.
> 3. **No stray hardcoded brand colour.** Grep the whole repo for
>    brand-colour hex literals outside `theming/repair.py`'s curated-neighbour
>    fallback table; report any found in template/CSS/Python colour positions.
> 4. **Zero cross-media drift.** For one seed, assert the same role hexes
>    appear in web (CSS seed block), motion (`inputProps`), email (inlined
>    HTML), and static graphic.
> 5. **Suite green.** `python -m pytest tests/ -q` — no new failures vs
>    `main`, no weakened/skipped tests masking a structural break.
> Output: a five-row pass/fail table with the proof (test name / `file:line`)
> for each, plus any regression risk you spotted.

---

### 4. If a verification fails

A failure here is a real regression in shipped code, not a build step.
Capture a minimal repro (the seed, the role pair, the failing assertion),
report it against the stage above, and fix it in a **separate** branch + PR
scoped to that regression — keeping the colour-science deterministic and never
substituting an AI judgement or a hand-tuned per-seed override for the
algorithm. Re-run the full-engine audit (§3) before closing.

---

*End of roadmap.*
