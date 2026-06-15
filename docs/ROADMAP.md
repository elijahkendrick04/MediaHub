# MediaHub Roadmap

The forward plan — **one document, in priority order.** It reads top-to-bottom
the way you should work it: the two live to-do lists (**things to build**, then
**things only you can do**), then the in-depth plan for each phase in priority
order, then the rules every change respects, then the changelog. **The record
of everything already shipped lives in its own file —
[`ROADMAP_BUILT.md`](ROADMAP_BUILT.md)** (the Completed list, what's live today,
the finished phases, and the retained build/verification prompts). Nothing on
*this* page is work that is already done.

## In plain words (start here)

MediaHub turns a swim meet's results file into ready-to-post club content:
upload the results, the app works out what matters (PBs, medals, club
records), designs branded cards and reels, writes the captions, and a human
approves everything before it goes anywhere.

**Where we are right now (June 2026):** the product is built and live — signup,
billing code, multi-tenancy, the generative design engine, fourteen
swimming-depth features and a UK legal-compliance baseline have all shipped
(the full record is in [`ROADMAP_BUILT.md`](ROADMAP_BUILT.md)). The decision now
(founder directive, **2026-06-13**) is to **make the product as good as it can
possibly be — genuinely something clubs *want* to use — before we
commercialise.** So the plan is reordered: every piece of work that improves the
product's usability is pulled forward, and the **last three things, in this
order, are (1) rebrand, (2) add a second sport, (3) go to market.** Everything
those three depend on is sequenced with them, last.

**Two hard rules were added on 2026-06-13.** First, **everything is built
in-house:** every capability is MediaHub's own first-party code, and every AI
call has a zero-cost local path (Phase 4). An outside service is used only as an
optional, swappable adapter for the one *unavoidable* final hop to someone
else's network — posting to a social platform a club already uses, taking a card
payment, or sending to a physical printer — never for the intelligence, the
content, the data, or the branding (rule 11). Second, **the second sport
(Phase 6) and going to market (Phase 7) do not start until every phase above
them is finished** — Phases 1–5: product polish, direct publishing, the creative
suite, zero-cost local AI, and the rebrand (rule 12). Those two phases are marked
🔒 throughout.

**The phases, in priority order:**

- **Phase 1 — Product polish & usability** · make the core flow excellent (Home,
  Add Input, the content-pack review, the autonomy controls; every
  empty/loading/error/success state; explainability + confidence).
- **Phase 2 — Direct publishing** · close the loop so a club can actually post —
  free targets first (Bluesky/Mastodon, email digests, Telegram), then
  Instagram/Facebook.
- **Phase 3 — Creative-suite breadth** · MediaHub's own first-party version of
  the content types clubs reach for (charts, documents, photo/video editing,
  templates, planner, collaboration, microsites…).
- **Phase 4 — Zero-cost local AI** · give every AI call a free local path
  (operator-margin work, invisible to clubs — so it sits behind the user-facing
  phases).
- **Phase 5 — Rebrand & identity** · pick the real company name, register it,
  buy the domain, and sweep the new brand through every surface.
- **Phase 6 — Second sport** · 🔒 *gated on Phases 1–5* · prove the engine
  beyond swimming end-to-end.
- **Phase 7 — Go to market** · 🔒 *gated on Phases 1–5* · pricing discovery, the
  first paying clubs, and the lawful-to-sell / payments / hosting groundwork —
  deliberately the **last** thing we do.

Phases are renumbered into this priority order. **Item IDs are kept stable as
identifiers** (`U.*` the new polish work; `P4.*` publishing, `P6.*` creative
suite, `P5.*` local-AI, `P3.*` second sport, `PC.*`/`F.*` the commercial +
founder work) so cross-references, the auto-update directives, and the shipped
record all stay valid — only the *order* and the phase numbers changed.

Every task carries a badge: 🔵 in progress · ⚠️ stuck · ❌ not started. (✅
"done" never appears here — finished work moves to
[`ROADMAP_BUILT.md`](ROADMAP_BUILT.md).)

> New here? Read **[START_HERE.md](../START_HERE.md)** first, then come back.
> Odd word? See the **[GLOSSARY](../GLOSSARY.md)**.

## Status (auto-updated)

<!-- ROADMAP:LAST_UPDATED -->
**Last updated:** 2026-06-15 · `d6f6e71a6` · Merge pull request #623: 1,000+ unique templates via a deterministic style-pack catalog
<!-- /ROADMAP:LAST_UPDATED -->

The stamp above, the activity table in the Changelog, the Production-findings
list, and the items inside the two to-do lists refresh on every push to `main`
via [`.github/workflows/roadmap-autoupdate.yml`](../.github/workflows/roadmap-autoupdate.yml).
**Completed work is not kept on this page** — when an item is marked done it is
moved out of its to-do list into the Completed list in
[`ROADMAP_BUILT.md`](ROADMAP_BUILT.md) (the bot maintains that file too). To move
an item, put a directive line in any commit message:

> `roadmap: <ID> <status>` — `<ID>` is an item ID from the lists below (`U.2`,
> `P4.1`, `P6.3` …); `<status>` is `done` · `wip` · `blocked` · `todo`. `done`
> **moves the item to the Completed list in `ROADMAP_BUILT.md`** (date-stamped);
> any other status sets the badge in place (`F.*` ids live on the founder list,
> everything else on the build list).

No directive is needed for an item already *marked* done: on every push the bot
also runs a **completed-item sweep** — any to-do item whose badge is ✅ (however
it got marked) is moved to `ROADMAP_BUILT.md`, dated from its badge, so a
finished item can never squat on this page.

## Production findings (from the live log sentinel)

Open problems the in-app log sentinel spotted in production logs and filed as
GitHub issues (label `sentinel`) — each is a real, evidenced fault waiting for
a code fix, so treat this list as roadmap to-do items sourced from production
rather than from planning. The block refreshes with the rest of this Status
section; **closing the issue clears it from here**. How the bot works:
[`LOG_SENTINEL.md`](LOG_SENTINEL.md).

<!-- ROADMAP:SENTINEL -->
_No open production findings — the log sentinel has nothing filed._
<!-- /ROADMAP:SENTINEL -->

## To do — things to build (priority order)

Ask in any session ("build P4.1"). In priority order: **Phase 1** product polish
(U.*) makes what exists feel finished; **Phase 2** publishing (P4.*) lets clubs
actually post; **Phase 3** creative-suite breadth (P6.*) makes MediaHub do far
more; **Phase 4** local-AI (P5.*) is operator-margin work. Then the
deliberately-last trio: **Phase 5** rebrand (PC.15), **Phase 6** second sport
(P3.*), **Phase 7** go-to-market ops (PC.16). Every item is first-party/in-house
— an external service only ever sits behind a swappable seam for the unavoidable
final hop (rule 11). **Phase 6 and Phase 7 are hard-gated** (🔒): they don't
begin until Phases 1–5 are complete (rule 12).

**UI2 — design-system-uplift follow-on surfaces (current no.1 priority).** The UI
motion/effect kit ([`ui-uplift/README.md`](ui-uplift/README.md)) is built and wired into
nine screens in PR #473. These items build the *purpose-built surfaces* the remaining
adopt-listed kit effects still need — rather than force-fitting them — and sit at the very
top of this list. Each reuses the already-built kit classes and is a discrete, dispatchable
build. **Parallelism:** 🟢 = independent surface, safe to build/merge in a **separate
parallel session**; 🟡 = touches a shared file (the `.btn` system or a list filter), so
sequence it or merge with care.

<!-- ROADMAP:TODO -->
- **UI2.5** · UI2 (top priority) — **CTA motion**: a purpose-built primary-CTA variant that actually shows Moving-Border (`.mh-moving-border`) + Stateful-Button (`.btn[data-mh-state]`, loading→success) — needs a borderless/transparent host so the animated border isn't hidden behind the button's own border · 🟡 coordinate (edits the shared `.btn` system) · ❌ **NOT STARTED**
- **UI 1.10** · Phase 1 (Product polish) — Visual template/archetype gallery (from Chronicle): browse the 12 content archetypes with preview thumbnails + category filters before creating a pack; renders existing archetype data, no new API · ❌ **NOT STARTED** · ANY ORDER (independent — not tied to the existing to-do sequence)
- **UI 1.20** · Phase 1 (Product polish) — Polished pricing page (from Resend): tier cards with check/cross feature lists + recommended-plan highlight + a billing-period toggle + a feature comparison table; server-rendered, matches existing CSS variables · ❌ **NOT STARTED** · ANY ORDER (independent — not tied to the existing to-do sequence)
- **UI 1.24** · Phase 1 (Product polish) — Moment-type marquee/ticker (from SavoirFaire/SuperHi): a continuous horizontal scrolling ticker of moment types (PBs · medals · comebacks · finals · club records) or club names as a section divider on the landing; pure CSS animation · ❌ **NOT STARTED** · ANY ORDER (independent — not tied to the existing to-do sequence)
- **P4.1** · Phase 2 (Direct publishing) — Bluesky (AT Protocol) + Mastodon adapters — the free/open posting targets first · ❌ **NOT STARTED**
- **P4.5** · Phase 2 (Direct publishing) — Email digest delivery: the existing newsletter actually sends (member lists, unsubscribe) behind an in-house SMTP relay by default; a managed relay (Resend) is an optional deliverability upgrade on the same seam · ❌ **NOT STARTED**
- **P4.6** · Phase 2 (Direct publishing) — Telegram channel publishing (free Bot API; native PNG+MP4) + a WhatsApp share stopgap · ❌ **NOT STARTED**
- **P4.2** · Phase 2 (Direct publishing) — Instagram Graph / Facebook / TikTok / YouTube adapters, least-privilege, human-connected · ❌ **NOT STARTED**
- **P4.3** · Phase 2 (Direct publishing) — X adapter as a paid, optional target (pay-per-use API) · ❌ **NOT STARTED**
- **P4.4** · Phase 2 (Direct publishing) — Demote Buffer to optional; remove it from the critical path · ❌ **NOT STARTED**
- **P6.1** · Phase 3 (Creative suite) — Smart format catalogue + format transformer: every Canva/Adobe-class design type as a data-driven club `FormatSpec` (certificates, posters, programmes, yearbooks, per-channel sizes); `turn_into` v2 re-targets any approved design · ❌ **NOT STARTED**
- **P6.2** · Phase 3 (Creative suite) — Conversational creative assistant: agentic spec-patch editing on `ai_core.ask_with_tools`, Magic-Write-class text tools, org assistant memory, voice input via the ASR seam · ❌ **NOT STARTED**
- **P6.3** · Phase 3 (Creative suite) — Generative imagery suite behind our own `media_ai` provider seam, with an **in-house local-model backend the default** (a licence-clean self-hosted diffusion model — the P5.6 path; cloud generators optional on the same seam): generate / edit / fill / expand / remove / subject-lift / upscale / style-match / mockups, provenance-stamped · ❌ **NOT STARTED**
- **P6.4** · Phase 3 (Creative suite) — Photo editor: deterministic non-destructive edit recipes (filters, adjustments, crop/perspective, collages, blur brush, HEIC) on `media_library` assets · ❌ **NOT STARTED**
- **P6.5** · Phase 3 (Creative suite) — Video suite: footage path + EDL timeline over the shipped reel engines, ASR captions, Clip-Maker-for-sport, saliency reframe, browser recorders, opt-in disclosed avatars · ❌ **NOT STARTED**
- **P6.6** · Phase 3 (Creative suite) — Audio engine: own licence-clean music/SFX pools + rights ledger, voice layer on the TTS seam (catalogue, params, name-pronunciation lexicon), denoise/levelling, consent-gated voice features · ❌ **NOT STARTED**
- **P6.7** · Phase 3 (Creative suite) — Typography system: curated self-hosted font catalogue + per-org uploads, AI pairing, deterministic text-effect tokens (shadow/neon/curve/extrude/warp), formatting depth · ❌ **NOT STARTED**
- **P6.8** · Phase 3 (Creative suite) — Element & stock libraries: brand-token-recolourable sport-editorial packs, own open-collection-seeded stock pools, embedding search, annotate/draw layer · ❌ **NOT STARTED**
- **P6.9** · Phase 3 (Creative suite) — Charts & insights: deterministic brand-styled stat graphics from canonical results/history + grounded AI takeaways and chart recommendations; diagram formats · ❌ **NOT STARTED**
- **P6.10** · Phase 3 (Creative suite) — Motion vocabulary: tokenised animation presets/transitions compiled to Remotion + FFmpeg + CSS, shared-element transitions, motion paths, reduce-motion variants · ❌ **NOT STARTED**
- **P6.11** · Phase 3 (Creative suite) — Brand platform depth: multi-kit (sponsor/event/section co-branding), deterministic brand check + AI auto-fix, token locks, brand home, kit-edit re-render sweep · ❌ **NOT STARTED**
- **P6.12** · Phase 3 (Creative suite) — Document engine: meet programmes / season reports / sponsor proposals / AGM decks, presenter surface (notes, remote, autoplay), PPTX/DOCX round-trip, PDF utilities · ❌ **NOT STARTED**
- **P6.13** · Phase 3 (Creative suite) — Club microsites + link-in-bio + forms + QR + vetted interactive widgets (countdowns, medal tally, polls), data-generated and publish-gated · ❌ **NOT STARTED**
- **P6.14** · Phase 3 (Creative suite) — Email & newsletter composer: email-safe branded HTML auto-assembled from the period's approved content; export-first, send-adapter later · ❌ **NOT STARTED**
- **P6.15** · Phase 3 (Creative suite) — Data hub + bulk personalisation: user-facing canonical tables with provenance, CSV/XLSX round-trip, deterministic derived columns, review-queued bulk generation ("certificates for all 47 PB swimmers") · ❌ **NOT STARTED**
- **P6.16** · Phase 3 (Creative suite) — Planner calendar/board: drag-reschedule through the publish gate, club-aware key dates, per-channel previews + safe zones, first-party performance-analytics loop feeding the planner · ❌ **NOT STARTED**
- **P6.17** · Phase 3 (Creative suite) — Collaboration & review: anchored comments/mentions/tasks, version diff + restore, element locks, roles, group approvers, expiring share tokens · ❌ **NOT STARTED**
- **P6.18** · Phase 3 (Creative suite) — Export & conversion engine: SVG/GIF/PPTX/DOCX/WAV/print-PDF additions, quality/transparency options, bulk export jobs, media-library quick-action utilities · ❌ **NOT STARTED**
- **P6.19** · Phase 3 (Creative suite) — Print & merch pipeline: physical-dimension FormatSpecs, CMYK PDF/X export, deterministic preflight with explanations, mockups; optional flag-gated fulfilment slot later · ❌ **NOT STARTED**
- **P6.20** · Phase 3 (Creative suite) — MediaHub platform surface: versioned public API + signed webhooks + a **first-party MCP server MediaHub *exposes*** so external agents (Claude/ChatGPT/Gemini-class) can optionally drive it — MediaHub itself depends on no external MCP — plus first-party file interop (SVG/PSD/palettes); GWS stays excluded · ❌ **NOT STARTED**
- **P6.21** · Phase 3 (Creative suite) — Mobile PWA: installable share-target capture to media library, offline-tolerant approval queue, mobile-first review/caption/crop; hosted-only stands · ❌ **NOT STARTED**
- **P6.22** · Phase 3 (Creative suite) — AI governance: per-org/per-feature quota ledger on `observability/`, generative moderation, provenance manifests on AI media, role-based feature permissions · ❌ **NOT STARTED**
- **P6.23** · Phase 3 (Creative suite) — Localisation: glossary-protected translation with layout-aware re-render, bilingual approval pairs (Welsh-first), bulk per-language variants, AI-dub pipeline, UI i18n · ❌ **NOT STARTED**
- **P6.24** · Phase 3 (Creative suite) — Pro editor & round-trip: layers/align/guides/page management as validated spec patches, vector node/boolean ops, curves/levels recipes, layered SVG/PSD export-import; deep darkroom/DTP stays a round-trip non-goal · ❌ **NOT STARTED**
- **P5.1** · Phase 4 (Local AI) — Ollama local LLM provider behind the existing `ai_core.llm` interface · ❌ **NOT STARTED**
- **P5.2** · Phase 4 (Local AI) — Piper local TTS replaces edge-tts · ❌ **NOT STARTED**
- **P5.3** · Phase 4 (Local AI) — whisper.cpp / faster-whisper local ASR for reel captions · ❌ **NOT STARTED**
- **P5.4** · Phase 4 (Local AI) — Satori graphics fast-path (~100× lighter than headless Chromium; rides the reel-engine seam P0.1 shipped) · ❌ **NOT STARTED**
- **P5.6** · Phase 4 (Local AI) — Local generative-image backend behind the `media_ai` seam (a licence-clean self-hosted diffusion model, e.g. FLUX.1-schnell, Apache-2.0): gives P6.3's imagery suite a zero-cost in-house path so generate/edit/fill/expand run with no cloud key; cloud generators stay optional on the same seam · ❌ **NOT STARTED**
- **PC.15** · Phase 5 (Rebrand) — Rebrand sweep, waits on F.9's name: one product-name source of truth threaded through every customer-facing surface (UI chrome, legal pages, wall badge + embeds, email from-name, `/try`, README) plus the F.11 canonical-host redirect; `mediahub` package/env names stay internal · ❌ **NOT STARTED**
- **P3.1** · Phase 6 (Second sport · 🔒 gated: Phases 1–5 first) — Second-sport engine adapter: `recognition_football`/`_basketball` + `register_sport(...)` · ❌ **NOT STARTED**
- **P3.2** · Phase 6 (Second sport · 🔒 gated: Phases 1–5 first) — Sports-data spokes, in-house first: vendor the public-domain/open datasets (openfootball, MIT fixture generators) into the repo as curated, versioned, provenance-stamped data like the qualifying-time packs; a live external sports API (`nba_api`) is an optional flag-gated spoke behind a seam, never required; all normalised to `canonical.*` · ❌ **NOT STARTED**
- **P3.3** · Phase 6 (Second sport · 🔒 gated: Phases 1–5 first) — Running/athletics parsers (chip-timing CSV, client-side FIT) — first-party, no external API · ❌ **NOT STARTED**
- **P3.4** · Phase 6 (Second sport · 🔒 gated: Phases 1–5 first) — Normalise all spokes to the canonical schema; flag ambiguous rows for review · ❌ **NOT STARTED**
- **PC.16** · Phase 7 (Go to market · 🔒 gated: Phases 1–5 first) — Hosting-cutover code half, waits on F.12's go decision: VPS deploy template (compose + reverse-proxy TLS on the same Dockerfile), off-site backup-target preflight, log-sentinel log-source seam (Render-API-free), staged subprocessor-register + privacy-notice hosting/region update, written cutover runbook · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO -->

## To do — things only you can do (the rebrand + go-to-market motion — last)

Fable 5 cannot register a business, sign a contract, spend your money, or sit in
front of a swim-club committee. These are **the rebrand + go-to-market motion —
deliberately the last things we do**, after the product is excellent (Phases
1–4) and proven on a second sport (Phase 6). Each item has a **step-by-step
guide** below. Order: settle the **identity first** (F.9 real name → F.10
company → F.11 domain), since every later filing embeds it; then the
lawful-to-sell / payments / ops groundwork (F.1–F.8, F.13, F.12); then the
selling motion itself (PC.4 pricing, PC.6 the first ~10 clubs).

<!-- ROADMAP:TODO_FOUNDER -->
- **F.9** · Choose the real company name (MediaHub is a filler): run the four-register name diligence — Companies House, UK trade marks, domain, social handles — and make the call · ❌ **NOT STARTED**
- **F.10** · Register the company at Companies House: verify your identity, file online (£100), then the post-registration basics — Corporation Tax, business bank account, statutory diary · ❌ **NOT STARTED**
- **F.11** · Buy the .co.uk domain in the company's name and point it at the live app (custom domain + TLS on Render today; Stripe webhook and base URL move with it) · ❌ **NOT STARTED**
- **F.1** · Turn payments on: create the Stripe account, set the four `STRIPE_*` keys on Render, switch on renewal reminders, decide VAT · ❌ **NOT STARTED**
- **F.2** · Register with the ICO and fill in the business identity (company name, address, contact email, ICO number) · ❌ **NOT STARTED**
- **F.3** · Get the five legal drafts solicitor-reviewed and signed off (Terms, Privacy, Cookies, DPA, DPIA) · ❌ **NOT STARTED**
- **F.4** · Accept each vendor's data-processing terms and pin the hosting region · ❌ **NOT STARTED**
- **F.5** · Adapt and submit the drafted Swim England API application · ❌ **NOT STARTED**
- **F.6** · Production ops decisions: retention period, breach owner named in the runbook, insurance, Remotion licence (or the free ffmpeg engine), Render snapshots + off-site backup target · ❌ **NOT STARTED**
- **F.7** · Each season: refresh the qualifying-time tables (recurring; runbook in `data/standards/README.md`) · ❌ **NOT STARTED**
- **F.8** · When direct Instagram/Facebook posting nears (P4.2): start the Meta Business Verification + App Review paperwork early · ❌ **NOT STARTED**
- **F.13** · Take the GitHub repo private again (public today; the children's-data fixtures' lawful-basis note assumes a private repo): pre-flight sweep, CI-minutes plan, the Settings flip, integration re-checks — at the latest before the first club pays · ❌ **NOT STARTED**
- **F.12** · 🔒 Gated (Phases 1–5 first) — Decide and execute the cheaper-hosting move off Render (≈£20/mo → ≈£4–8/mo VPS) via the rehearsed backup-restore cutover — after F.11, never ahead of selling · ❌ **NOT STARTED**
- **PC.4** · Phase 7 (Go to market · 🔒 gated: Phases 1–5 first) — Quote real annual prices to the first clubs and record what clears; the public price unlocks itself once ≥5 clubs have paid annual at a tested price (build side shipped — this is selling; warm groundwork may continue, but the gate holds full GTM until Phases 1–5 land) · 🔵 **IN PROGRESS**
- **PC.6** · Phase 7 (Go to market · 🔒 gated: Phases 1–5 first) — Win the first ~10 paying clubs: warm-first hand-sell from the Swansea/South-Wales base + referrals, cold capped (tooling shipped — this is selling; warm groundwork may continue, but the gate holds full GTM until Phases 1–5 land) · 🔵 **IN PROGRESS**
<!-- /ROADMAP:TODO_FOUNDER -->

### Step-by-step guides (one per item above)

#### F.9 — Choose the real company name (the naming diligence)

"MediaHub" was always a working title: it is generic, shared by other
companies, and could never be defended as a brand or trade mark. The real
name comes **first** — before Companies House, Stripe, the ICO, the
solicitor's letters and the domain — because every one of those filings
embeds it, and renaming later means re-doing (and re-paying) the lot.

**What "due diligence" means here, in plain words:** before you commit to a
name, check that nobody else already owns it — as a registered company, as a
trade mark, as the domain, or as the obvious social handles — so that no one
can force you to rebrand (or sue you) later, and so you are never pushed into
a worse spelling of your own name. It is an afternoon of free searches, done
in the order below.

1. Longlist 5–10 candidate names. The criteria that actually matter for this
   product: **distinctive** (a coined/invented word beats a descriptive one —
   descriptive names can't be defended and are already taken), **short and
   unambiguous said aloud** (poolside, over the phone, on a committee call),
   **comfortable in Wales** (check the Welsh reading/meaning — the first
   market is Welsh clubs and the product ships Welsh-first captions, W.13),
   and **bigger than swimming** (the vision is sport-agnostic — avoid "swim"
   in the name unless that's a deliberate choice).
2. **Companies House check.** Search the free register at
   find-and-update.company-information.service.gov.uk and run GOV.UK's
   "Check if a company name is available" service. The rules: the registered
   name ends "Ltd"/"Limited" (you can trade without the suffix), it can't be
   the "same as" an existing name, and "sensitive words" (Royal, British,
   Institute, …) need permission. An existing dormant or different-sector
   company with a similar name isn't automatically fatal — but prefer a clear
   field.
3. **Trade mark check — the one that can actually force a rebrand.** Search
   UK trade marks (GOV.UK "Search for a trade mark") in **class 9**
   (software), **class 42** (software-as-a-service) and **class 41**
   (sport/education services). A live mark on a confusingly similar name in
   those classes = drop the candidate. Registering a company name gives you
   **no** trade-mark rights — they are separate systems.
4. **Domain check.** Is the exact-match `.co.uk` free at any registrar
   (≈£5–15/yr)? Don't buy yet — that's F.11, after F.10 locks the name. If
   the `.com` is parked at a four-figure aftermarket price, let it go; the
   `.co.uk` is the brand at home and a sane `.com` variant can come later.
5. **Handles check.** Instagram, Facebook, X, TikTok, Bluesky, YouTube,
   GitHub. The product's whole job is social content — clubs *will* search
   the name. Exact or near-exact handles should be free.
6. **The passing-off sniff test.** Plain web search for the name plus
   "swim", "sport", "club", "software". Anyone already trading under it in an
   adjacent space — even without a registered trade mark — can claim
   "passing off" in the UK. Avoid names with active neighbours.
7. Pick the winner and sleep on it once. Say it in the three sentences it
   must live in: "___ has signed up to ___", "Powered by ___", "___ Ltd".
8. *(Optional, cheap insurance once revenue starts:)* file your own UK trade
   mark — £205 online for one class, +£60 per extra class (fees rose
   1 Apr 2026); classes 9 + 42 first. This can wait for the first paying
   clubs.
9. **Verify:** the name passes all four registers (Companies House, trade
   marks, domain, handles), with screenshots/notes kept in one folder — then
   tell Fable 5 the chosen name so the rebrand sweep (PC.15) can be built and
   F.2's legal placeholders get the real value.

#### F.10 — Register the company at Companies House

About 30 minutes online once F.9 has settled the name. The company is the
legal identity everything else hangs off — Stripe onboarding (F.1), ICO
registration (F.2), the solicitor's sign-off (F.3), the Swim England
application (F.5), insurance (F.6) and the domain registration (F.11). This
supersedes the old "sole trader is fine to start" note in F.2: decided
2026-06-12 — name first, company second, everything files once under it.

1. **Verify your identity first** (mandatory for new directors since
   18 Nov 2025): create a GOV.UK One Login and complete Companies House
   identity verification — you receive a personal code that the
   incorporation filing now requires.
2. Decide the basics — the answers are mostly "you": sole director = you;
   shareholder = you (1 or 100 ordinary £1 shares — either is fine; 100
   makes a future split easier); Person with Significant Control = you.
3. Choose the **registered office address** — it is public, forever. Your
   home address works but is published; a registered-office service
   (≈£20–50/yr, often bundled by accountants) keeps your home address off
   the register. You also need a registered email address (not published).
4. Pick the **SIC code** (what the company does): 62012 "business and
   domestic software development" fits; add 63120 (web portals) if you like —
   up to four, all changeable later.
5. **File online**: GOV.UK "Set up a private limited company" → register the
   company. £100 digital fee (it rose from £50 on 1 Feb 2026), model
   articles of association are fine, and registration usually completes
   within 24 hours. You get the certificate of incorporation + company
   number.
6. **Within 3 months of starting to trade** (the first sale is the trigger):
   register for Corporation Tax — HMRC posts the company's UTR to the
   registered office.
7. **Open a business bank account in the company's name** (Starling, Tide,
   Monzo Business — free tiers are fine). Company money and your money never
   mix; Stripe payouts (F.1) land here.
8. Set up the books and **diary the annual duties** so they never surprise
   you: the confirmation statement each year (£50 online — also where
   directors' ID verification is enforced), annual accounts (micro-entity
   accounts are tiny), and the Corporation Tax return. Simplest: a fixed-fee
   accountant for a micro company (≈£300–700/yr `[ESTIMATE]`); or
   FreeAgent/Xero solo.
9. VAT: nothing to do below the registration threshold — F.1 step 7 already
   covers the decision; just keep records.
10. Feed the new identity into everything queued behind it: Stripe (F.1) as
    the Ltd, ICO (F.2) in the company's name — and give Fable 5 the five
    identity values so the legal placeholders fill — the solicitor (F.3),
    Swim England (F.5), insurance (F.6).
11. **Verify:** the company appears on the public register; the certificate,
    personal code, UTR letter and bank details live in the records folder;
    after F.2 step 4, `/terms` and `/privacy` show the real company name and
    number.

#### F.11 — Own domain: buy the .co.uk and point it at the live app

Today the public URL is the borrowed `mediahub-gzwc.onrender.com`. Your own
domain is the **portable** identity: once every printed QR code, embedded
wall, bookmark and Stripe webhook points at your own `.co.uk`, the hosting
underneath (F.12) can change with a DNS flip and nobody notices. That is why
the domain comes before the host move — and after F.10, so the company owns
it.

1. Register `<name>.co.uk` at any Nominet-accredited registrar (Namecheap,
   Porkbun, Gandi, Ionos/123-reg, Krystal, … ≈£5–15/yr `[ESTIMATE]`).
   Register it **in the company's name** with the company's contact email —
   not as a personal possession; clean ownership matters if you ever sell or
   raise. Take the bare `.uk` too if it's pennies; skip aftermarket-priced
   `.com` offers.
2. Decide the canonical host once: `www.<name>.co.uk` (recommended —
   CNAME-friendly everywhere) with the apex redirecting to it.
3. *(Recommended)* put the DNS on a provider you won't outgrow — Cloudflare's
   free tier works with a domain bought anywhere (add the site, switch the
   two nameservers at the registrar). Registrar DNS also works; pick one.
4. Wire it to Render **now** — don't wait for F.12: Render dashboard → the
   service → Settings → Custom Domains → add `www.<name>.co.uk` (+ apex);
   create the CNAME/A records it shows; TLS certificates are automatic.
5. Update what knows the URL: the `MEDIAHUB_PUBLIC_BASE_URL` env var on
   Render; the Stripe webhook endpoint (F.1 step 4) to
   `https://www.<name>.co.uk/webhooks/stripe`; and when transactional email
   goes live, send as `no-reply@<name>.co.uk` with the SPF + DKIM DNS
   records your email provider gives you (`MEDIAHUB_EMAIL_FROM` — mail from
   your own domain lands in inboxes; mail from borrowed domains lands in
   spam).
6. Ask Fable 5 for the small code half (rides with PC.15): a canonical-host
   redirect so the old `*.onrender.com` URLs 301 to the new domain — every
   old link keeps working forever.
7. **Verify:** `https://www.<name>.co.uk` serves the app with a padlock and
   the apex redirects; `/try`, a `/wall/<token>` page and a Stripe **test**
   webhook all work on the new URL; the old onrender.com URL redirects.

#### F.12 — Move hosting off Render to a cheaper host

The honest numbers first: Render's standard instance — the 2 GB the
Chromium/Remotion renders need — is **$25/mo ≈ £20/mo** plus the disk. A
capable EU VPS runs **€3.79–€7.59/mo** (Hetzner CX22 4 GB → CX32 8 GB,
verified June 2026), so the move saves roughly **£150–200/yr** `[ESTIMATE]`.
Real money, but small against one paying club (~£588–1,188/yr) — which is
why F.12 is queued **behind** the identity work and must never displace a
selling week. The trade: a VPS hands you the ops the platform did (OS
updates, monitoring, disk space). The app is deliberately a single-box shape
— one container, SQLite under `DATA_DIR` — so a single VPS fits it exactly,
and the backup/restore drill (PC.14) already rehearses the actual move.

1. **Decide between three honest options.**
   **(a) EU/UK VPS + Docker** — the recommended target: Hetzner (Germany/
   Finland, EU) at €3.79–7.59/mo, or a UK-soil VPS (≈£5–15/mo `[ESTIMATE]`)
   if "your data stays in the UK" plays better with clubs. Either improves
   on today's hosting, which stores Club Data in the **US** (see the DPA's
   subprocessor register) — the move shrinks F.4's transfer homework.
   **(b) A cheaper managed platform** (Fly.io London, Railway, …) — less ops,
   smaller savings once a persistent volume + 2 GB RAM are priced; check
   their current calculators.
   **(c) Stay on Render and revisit at traction** — £0 effort, a legitimate
   choice while selling time is the binding constraint. If (c): stop here
   and diary it for after the first ~3 paying clubs.
2. If (a) or (b): ask Fable 5 to build **PC.16** (the code half) — the
   compose + reverse-proxy TLS template, the off-site backup-target
   preflight, the log-sentinel log-source seam (it currently reads logs via
   the Render API and must honest-disable or grow a journald/file source off
   Render), the staged subprocessor-register + privacy-notice hosting/region
   update, and the written cutover runbook.
3. Provision the box; deploy the **same Dockerfile** with the same `.env`;
   point a temporary subdomain (e.g. `next.<name>.co.uk`) at it.
4. **Rehearse the move with the shipped drill:** take the latest production
   backup ZIP, `python -m mediahub.backup restore` onto the new box, then
   smoke-test the primary flow (upload → pack → review → approve → export),
   one reel render, `/healthz`, and a Stripe **test** webhook against the
   temporary subdomain.
5. Cut over: lower the DNS TTL the day before; pause uploads briefly (tell
   any live pilot club); final backup → restore → flip the `www` record to
   the new box; watch `/healthz` and the uptime readout.
6. Keep Render alive for ~1 week as the instant rollback (flip DNS back),
   then download a final disk snapshot, delete the service, detach the card.
   Point the off-site backup target somewhere that is **not** the new box —
   a backup living on the machine it protects isn't one.
7. **Verify:** a full green week on the new host (uptime, scheduler runs,
   off-site backups arriving, one real run end-to-end); the DPA's
   subprocessor register and the Privacy Notice name the new host and
   region (PC.16); and the bill actually dropped.

#### F.1 — Turn payments on

The billing code shipped in PR #267 and deliberately refuses to run (an
honest "billing not configured" message) until you give it real Stripe keys.

1. Create an account at stripe.com and complete Stripe's business onboarding
   (it asks for the legal identity you create in F.10 — onboard as the
   limited company from the start, so its KYC never has to be re-done after
   a switch from a personal account).
2. In the Stripe dashboard, create two Products with recurring annual Prices:
   **Club** and **Federation**. Copy each Price id (`price_…`).
3. Developers → API keys: copy the Secret key. Use the `sk_test_…` key first
   if you want to rehearse the whole flow with the card number
   `4242 4242 4242 4242`, then swap to `sk_live_…`.
4. Developers → Webhooks → Add endpoint:
   `https://<your-app-domain>/webhooks/stripe` (the F.11 domain once it's
   live — update the endpoint here if you wire Stripe first), subscribed to
   the checkout/subscription events; copy the Signing secret (`whsec_…`).
5. Render dashboard → your service → Environment: set `STRIPE_SECRET_KEY`,
   `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_CLUB`, `STRIPE_PRICE_FEDERATION`.
   Redeploy.
6. In Stripe → Settings → Billing: switch **on** renewal-reminder emails for
   annual subscriptions (the Terms and `/billing/confirm` promise a reminder
   before renewal — make it true), and confirm the customer-portal
   cancellation flow is enabled (cancelling must stay as easy as signing up).
7. Decide VAT: below the registration threshold, do nothing but keep records;
   otherwise enable Stripe Tax. Confirm Checkout emits an invoice/receipt a
   volunteer treasurer can put through club accounts.
8. **Verify:** `/billing` on the live site no longer shows "billing not
   configured", and a test-mode payment runs end-to-end.

#### F.2 — Register with the ICO + fill in the business identity

You process personal data (largely children's), so UK law requires
registering with the Information Commissioner's Office and paying the small
annual data-protection fee.

1. The business identity is the F.10 limited company (decided 2026-06-12:
   name first, company second, everything else files once under it) — do
   F.9/F.10 before this, so the ICO entry never needs re-registering under
   a rename.
2. Register as a data controller at **ico.org.uk/registration** and pay the
   fee (tier 1 covers a small business; it renews annually).
3. Note the ICO registration number you receive.
4. Give Fable 5 the five values — trading/company name, company number (or
   "sole trader"), business address, contact email, ICO number — and ask it
   to fill the placeholders in `web/legal.py` (one edit fixes every legal
   page and the footer; the canonical list is `legal.PLACEHOLDERS`).
5. **Verify:** open `/terms` and `/privacy` on the live site — no
   `[COMPANY_NAME]`-style brackets remain anywhere.

#### F.3 — Solicitor sign-off on the legal drafts

The five documents are drafted and live, but headed "DRAFT — requires
solicitor review". A human professional must sign them off before the first
paid contract.

1. Find a solicitor with data-protection/commercial experience (the Law
   Society finder, or a fixed-fee online firm; budget a few hundred pounds).
2. Send them the four live pages (`/terms`, `/privacy`, `/cookies`, `/dpa`),
   the DPIA draft (`docs/compliance/DPIA.md`), and the specific open
   questions listed in [`COMPLIANCE_AUDIT.md`](COMPLIANCE_AUDIT.md) §4(d).
3. Feed their edits back through Fable 5 — it updates `web/legal.py` and
   bumps the document version, which automatically routes every signed-in
   account through re-acceptance. That's the mechanism, not a promise.
4. When they sign off, ask Fable 5 to remove the DRAFT banners and record the
   sign-off date.
5. **Verify:** the four pages render without DRAFT banners and carry dated
   versions.

#### F.4 — Vendor data-processing terms + hosting region

MediaHub sends data to a handful of providers; each needs its processing
terms accepted and a lawful UK→US transfer mechanism confirmed.

1. Work down the live-provider list: Google (Gemini API), Anthropic, Stripe,
   Render — plus any you have switched on (Buffer, Photoroom, Replicate,
   ntfy).
2. For each: accept/execute their data-processing terms (usually a dashboard
   checkbox or a published DPA) and keep a dated copy in one folder.
3. For US vendors, confirm UK–US Data Bridge certification, or execute their
   IDTA/UK Addendum.
4. Where a "don't train on my data" toggle exists (Google AI, Anthropic),
   switch it off and screenshot it.
5. In Render: pin the region, confirm disk encryption, confirm TLS/HSTS at
   the edge.
6. **Verify:** every subprocessor named in the Privacy Notice §7 has a
   recorded agreement in your folder — and tell Fable 5 about any provider
   you add or drop so the notice stays true.

#### F.5 — Submit the Swim England API application

Swim England's approved-systems API grants official swim-times data (not
promotion — see [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)).
The application is already drafted and submission-ready.

> **Daily-scan note (2026-06-12):** Swim England has since announced (4 Mar
> 2026) a Sport:80-built membership platform (live Autumn 2026), a **Rankings
> API** for verified swim times and a swimmingresults.org integration, with a
> SportsEngine announcement expected later in 2026. Before submitting, check
> whether commercial times-data access now routes through the Rankings-API /
> Sport:80 programme rather than the 1 Oct 2025 contact, and expect slower
> replies around the Autumn 2026 migration window.
> Source: [Sport:80 announcement](https://www.swimming.org/swimengland/sport80-membership-platform/).

1. Open [`commercial/SWIM_ENGLAND_API_APPLICATION.md`](commercial/SWIM_ENGLAND_API_APPLICATION.md)
   and fill in the founder/identity details (same values as F.2).
2. Re-verify the submission contact from Swim England's 1 Oct 2025
   approved-systems announcement — it may have moved.
3. Send it, and record "applied" on the operator console
   (`/operator/commercial`).
4. Chase politely after ~4 weeks.
5. The standing threshold: if no NGB movement after ~6 months, deprioritise
   the channel and lean on direct + referrals.

#### PC.4 — Quote real prices (the pricing gate)

Don't publish a price — *discover* one. `/pricing` deliberately shows
"Pricing TBC" until **≥5 clubs have paid an annual prepay at a tested
price**; it then derives the public list price from the highest tested figure
that cleared. Everything below is already built.

1. For each interested club, pick a real annual figure inside the candidate
   band (**£49–£99/mo billed annually ≈ £588–£1,188/yr**) and vary it across
   clubs — that variation *is* the price discovery.
2. Record the quote on `/operator/commercial` (the quote ledger). It gives
   you a per-quote Stripe Checkout link that charges exactly the quoted
   figure (needs F.1 done).
3. Send the link. The signed webhook records the payment automatically,
   idempotently and amount-verified.
4. Record declines too — a "no" at £1,188 teaches as much as a "yes" at £708.
5. Annual prepay is non-negotiable: volunteer-org churn runs 3–7 %/month and
   annual billing cuts it ~30–40 %.
6. **Done when:** the console's pricing gate shows ≥5 paid annual —
   `/pricing` switches itself on at the highest cleared price.

#### PC.6 — Win the first ~10 paying clubs (the traction gate)

This is *the* Phase C exit gate. The evidence says it is reached by warmth
and referrals, never cold broadcast (warm founder-led sales close ~30–50 %;
cold-to-paid runs ~0.3–1 %, which would need 1,000–3,000 quality contacts —
not viable solo).

1. Read [`PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md). The first club doubles as
   the pilot and will surface UX holes no audit can.
2. List 10–15 warm clubs from the Swansea / South-East-Wales network — clubs
   you can reach through someone they already know (Swim Wales has ~80–90
   affiliated clubs; it is a tight community).
3. Book in-person demos. The sharpest demo: open `/try` with **their own
   latest meet results** — watermarked branded cards in front of them, no
   account needed.
4. Close warm leads with PC.4 quotes (annual prepay only). Aim for ~3–5
   paying clubs from the local base, high-touch.
5. Ask every signed club for **two named introductions** to peer clubs — the
   designed route from 5 to 10. Track who still owes intros on
   `/operator/commercial` (the referral-debt readout).
6. Manufacture warmth at county/regional meets: produce real branded output
   for host and visiting clubs at the event.
7. Use cold outreach only as a capped supplement to book a handful of
   discovery calls — the console's cold-share readout flags when it creeps
   up.
8. **Done when:** ≥10 clubs pay annually. Expect ~3–6+ months; the dominant
   failure mode is the motion not being run, not the close rate.

#### F.6 — Production ops decisions

The boring decisions a paying customer silently assumes someone has made.

1. Set `MEDIAHUB_RETENTION_DAYS` on Render to the retention period you want —
   and tell Fable 5 if you change it later, so the Privacy Notice's retention
   table keeps matching what the code does.
2. Name the breach owner (you): the person who notifies affected clubs
   without undue delay and the ICO within 72 hours. Write the name into the
   owner line of [SUPPORT_INCIDENT_RUNBOOK](SUPPORT_INCIDENT_RUNBOOK.md)
   (shipped with PC.14 — it has the slot ready).
3. Get professional-indemnity + cyber insurance quotes (small-SaaS brokers
   cover this cheaply).
4. Decide reels: buy the Remotion company licence, **or** set
   `MEDIAHUB_REEL_ENGINE=ffmpeg` (the free engine). Don't ship for-profit on
   unlicensed Remotion.
5. ~~Open the bundled demo sample and confirm it contains no real children's
   data~~ **Done (PC.12, 2026-06-12):** the public demo sample is now the
   synthetic `samples/demo-meet-results.pdf` (fictional swimmers, generated
   by `scripts/make_demo_sample.py`); the real meet PDF survives only as a
   parser-regression fixture in `sample_data/`, which no route serves. See
   [CHILDRENS_CODE_PASS](compliance/CHILDRENS_CODE_PASS.md).
6. Switch the daily backup on and point it off the Render disk. The backup
   code + rehearsed restore shipped with PC.14, but the scheduled job
   deliberately stays off until you give it a target. In the Render
   dashboard confirm disk snapshots are on, then set two environment
   variables on the service: `MEDIAHUB_BACKUP_UPLOAD_URL` — any HTTPS
   endpoint that accepts an HTTP `PUT` of a ZIP (an S3/R2 presigned URL, a
   WebDAV folder, or any small storage service that gives you one) — and,
   if that endpoint wants auth, `MEDIAHUB_BACKUP_UPLOAD_TOKEN` (sent as a
   `Bearer` token). (Setting only `MEDIAHUB_BACKUP_DIR` also switches the
   job on, but those archives sit on the same disk they protect — off-site
   is the point.) If/when F.12 moves hosting, re-confirm the equivalent
   snapshots + off-site target on the new host.
7. **Verify:** the operator console's backup line shows a recent archive
   with **off-site upload: yes**, and your name is in the runbook's owner
   line.

#### F.7 — Seasonal qualifying-times refresh (recurring)

"Qualified for Counties!" cards (W.4) depend on season-current tables that
are curated, not scraped.

1. Each season, follow the runbook in `data/standards/README.md`: download
   the new county/regional/national qualifying-time PDFs.
2. Hand them to Fable 5 to convert into the versioned dataset format under
   `data/standards/<season>/` with per-table provenance (source URL + date).
3. **Verify:** one known qualifying swim produces a "qualified" card naming
   the new standard and its source.

#### F.8 — Meta verification paperwork (parked until P4.2 nears)

Instagram/Facebook auto-posting needs Meta Business Verification + App
Review — $0 but **weeks of calendar time**, so start the clock early when P4
work approaches. Until then, P4.1 (Bluesky/Mastodon) and P4.6 (Telegram) need
no review at all.

1. Create a Meta Business Portfolio and complete Business Verification
   (company documents — F.10's certificate of incorporation is exactly
   this).
2. Create the Meta app; request `instagram_content_publish` and
   `pages_manage_posts` via App Review, with screen recordings of the
   connect-and-post flow.
3. Expect ~2–4 weeks per permission; one review covers Facebook Pages +
   Instagram (Threads is scoped separately).

#### F.13 — Take the GitHub repo private again

The repo (`github.com/elijahkendrick04/MediaHub`) is **public today** and
needs to return to private; the only open questions are *when* and *what to
check on the way*. Why it matters, in weight order: (1) **compliance** — the
parser fixtures hold real children's personal data from published meets
(`samples/MISM-2024-Results.pdf`, `samples/learning_corpus/level1/*`), and
the documented justification for keeping them
([OPEN_LEGAL_QUESTIONS Q13](compliance/OPEN_LEGAL_QUESTIONS.md),
[DATA_MAP §6](compliance/DATA_MAP.md)) rests on "access control (private
repo)" — a defence that does not hold while the repo is public;
(2) **commercial** — hosted-only
([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md)) treats the
source as the product, and a public repo is a free self-host path that also
hands competitors the pricing strategy and sales playbook committed in
`docs/`; (3) **the clock runs one way** — flipping private recalls nothing,
so everything pushed while public stays permanently clonable by anyone who
took a copy (the full-history gitleaks audit found no real secrets, so the
exposure is the fixtures + strategy, not credentials). **Latest sensible
deadline: before the first club pays** — the sell gate's compliance posture
leans on Q13's "repo stays private". Do it earlier the moment whatever
needed the repo public is finished.

1. Confirm the reason it is public has expired and nobody external still
   needs read access — anyone who does becomes a collaborator instead (repo
   Settings → Collaborators).
2. Ask Fable 5 for the **pre-flight sweep** (one session): re-check forks —
   **0 as of 2026-06-12**; a fork made while public survives the flip as an
   independent public copy, so any that appeared need a decision before
   flipping — and re-confirm nothing fetches this repo's files
   unauthenticated at runtime (none today: the README badges are static
   shields.io, and the Dockerfile's raw.githubusercontent fetch targets the
   SearXNG repo, not ours).
3. **Decide the Actions-minutes plan — the one real cost.** Public repos run
   GitHub-hosted CI free; a private repo on the Free plan gets
   **2,000 min/month**, and today's schedules (autotest every 6 h, nightly
   Lighthouse + cross-browser sweeps, the daily contract suite, the
   half-hourly dependabot-automerge sweep, plus every push/PR) would burn
   that in days. Cheapest first: have Fable 5 trim the schedules (autotest
   6 h → daily, automerge 30 min → 2–6 h, consolidate the nightlies) and
   ship the trim *before* the flip so the quota never silently stalls CI;
   GitHub Pro (~$4/mo, 3,000 min) if trimming isn't enough; heavy jobs onto
   a self-hosted runner (the F.12 box) later if both fall short.
4. Flip it: repo → Settings → General → Danger Zone → **Change visibility →
   Make private** (type the repo name to confirm). Only you can do this
   (admin). Going private permanently drops stars/watchers (currently 0) and
   turns off GitHub's free public-repo secret scanning / push protection —
   the CI security workflow's own scanners keep running.
5. Re-verify everything that reads the repo: trigger a manual Render deploy
   (the Render GitHub App keeps its access to private repos it was granted),
   open a Claude Code session on the repo, push a trivial commit and watch
   CI + the roadmap-autoupdate bot go green, and confirm Dependabot still
   files PRs.
6. Ask Fable 5 to record the public window honestly in the compliance docs
   (Q13 in `OPEN_LEGAL_QUESTIONS.md` + `DATA_MAP` §6): pin the make-public
   date from your account security log (github.com/settings/security-log,
   filter `repo.access` — 90-day retention), or state repo creation
   (2026-05-08) as the conservative start. "Repo stays private" must read
   true again, with its history accurate.
7. **Verify:** a logged-out browser gets a 404 on
   `github.com/elijahkendrick04/MediaHub`; CI is green on the next push; a
   Render deploy succeeded after the flip; Settings → Billing shows the
   month's Actions usage tracking inside budget.

## The plan in depth — phases in priority order

The long-form plan for everything still open, **in the priority order we'll work
it.** The record of completed phases (0, 1, 2, W and the shipped Phase C build
half) lives in [`ROADMAP_BUILT.md`](ROADMAP_BUILT.md).

### Phase 1 — Product polish & usability · U · ❌ **NOT STARTED**

**Goal.** Make the product clubs already touch every week feel finished and
obviously good to use — the single fastest way to make MediaHub something people
*want*. Flask + Jinja stay; this is design and interaction quality on the
existing surfaces, not a rewrite.

**Exit criterion.** A first-time committee volunteer can go upload → configure →
process → review → approve → export without confusion, on a credible
sport-editorial UI, with every state (empty / loading / error / success)
designed and every recognition decision explained.

- **U.1 — Core-flow polish.** Home, Add Input, the content-pack review, and
  Settings → Autonomy raised to a credible product standard: strong hierarchy,
  one obvious primary action per screen, the dark-first palette on the existing
  `--bg`/`--accent`/`--ink`/`--panel` CSS variables, no generic-SaaS filler.
- **U.2 — Every state designed.** Empty, loading, error and success states
  across the primary flow — including the honest AI-unavailable error and the
  parse-uncertainty / flag-for-review surfaces (never a silent guess).
- **U.3 — Explainability & confidence.** "Why this card / why not" and the
  confidence displays made clear and trustworthy in the review UI — the
  intelligence layer is the moat, so it has to *read* as intelligent.
- **U.4 — Onboarding & mobile review.** A fast, obvious first run: brand-kit
  setup and a sample-to-first-content-pack path; mobile-aware review/approve
  (desktop-primary) so a volunteer can approve from a phone.
- **U.5 — Scroll-driven progressive reveal.** Landing sections reveal
  line-by-line on scroll; dark editorial theme throughout. Pure CSS
  IntersectionObserver, no new deps. *Inspired by Opal (op.al).*
- **U.6 — Branded render/generation loading state.** Large editorial %-counter +
  minimal progress bar for real render waits; reuses the giant-numeral motif.
  Replaces the generic spinner on long card/reel renders. *Inspired by Lusion
  (lusion.co). Supports U.2.*
- **U.7 — "Focus the facts" caption/explainability highlight.** In captions and
  the why-this-card review UI, source-grounded entities (athlete / time / event /
  PB) are sharp + pill-highlighted; surrounding filler copy is de-emphasised.
  Server-side span injection — no client JS required. *Inspired by Pedro Duarte
  (ped.ro). Supports U.3.*
- **U.8 — Animated how-it-works pipeline diagram.** Glowing nodes + connecting
  traces on the landing page showing reads (club site / socials / brand kit) →
  writes (captions / graphics / reels); reuses the blueprint grid motif. SVG +
  CSS keyframes. *Inspired by AuthKit (authkit.com).*
- **U.9 — Cycling hero accent word.** The gold italic accent word in the landing
  hero cycles through content types (stories / reels / graphics / captions) with
  a CSS crossfade; optionally swaps a matching icon. *Inspired by Spring/Summer
  (springsummer.dk).*
- **U.10 — Framed in-app product demo in hero.** Short looping screen-capture or
  interactive inline preview of generate → review → approve sits inside a framed
  browser/device mockup; subtle ambient glow behind it. *Inspired by Reflect
  (reflect.app).*
- **U.11 — Outputs inside real platform frames.** Sample outputs (cards, reels)
  presented inside Instagram Story/feed/Reel phone mockups with a subtle CSS
  autoplay carousel. Pure HTML/CSS — no JS framework. *Inspired by AndAgain
  (andagain.uk).*
- **U.12 — Animated count-up stat numerals.** Organisations / total runs / cards
  generated numerals odometer-count upward on page load + on scroll-into-view.
  Vanilla JS counter. *Inspired by Max Yinger (yinger.dev).*
- **U.13 — Floating mobile action dock.** Fixed bottom-centre thumb-reachable
  capsule (Create / Library / Approve) visible on mobile viewports during
  review/approve; hidden on desktop. *Inspired by Duties (duties.xyz). Supports
  U.4.*
- **U.14 — Cursor-following hover preview.** Hovering an item in Media Library
  or the CREATE list spawns a floating cross-dissolve thumbnail that tracks the
  cursor. JS + absolute positioning; no external dep. *Inspired by Christopher
  Ireland + SuperHi.*
- **U.15 — Before/after reveal slider.** Drag-to-wipe between a raw results
  sheet (input) and the finished branded graphic (output) on the landing page.
  Single vanilla JS slider, no library. *Inspired by Lovi (lovi.care).*
- **U.16 — Subtle 3D tilt on output cards.** Premium parallax/tilt-on-hover for
  sample output cards; uses CSS perspective + JS pointer-tracking; respects
  `prefers-reduced-motion`. *Inspired by Atlas (atlascard.com).*
- **UI 1.1 — Cycling example-prompt placeholder.** In the CREATE / Free-Text
  input and any search field, the placeholder animates through curated real
  examples ('Try: Tom Davies PB 100m free', 'Try: top three at county finals'),
  guiding first-time users with zero extra UI. Pure CSS/JS, no new deps.
  *Inspired by Cosmos (cosmos.so). Supports U.4.*
- **UI 1.2 — Bento-grid feature section.** The uniform capability card rows on
  the landing are replaced by a bento grid of varied-size tiles — each carries
  its own mini-visual (a sample story card, a stat chip, brand-kit swatches, a
  'moments we detect' list, a reel preview). Dark/premium, all on existing CSS
  variables. *Inspired by Umbrel (umbrel.com).*
- **UI 1.3 — Inline media thumbnails in a display headline.** Small real output
  thumbnails are embedded inline within a large hero sentence: 'From a results
  sheet [img] to a story [img], a feed graphic [img] and a reel [img].' Images
  served from the static directory — no external fetch. *Inspired by Samara
  (samara.com).*
- **UI 1.4 — Tactile spring-physics micro-interactions.** A restrained
  spring-physics layer on primary buttons, card-selection, and toggles: subtle
  magnetic hover + bouncy press. Vanilla JS driving CSS custom-property
  animation; `prefers-reduced-motion` respected; understated to preserve the
  editorial tone. *Inspired by Family (family.co).*
- **UI 1.5 — Live local-time + system-status HUD readout.** A small mono
  header/footer strip shows live local time and a deployment/system status line,
  extending the existing ONLINE indicator in the blueprint/HUD aesthetic.
  Low-priority polish; no new backend surface. *Inspired by AndAgain
  (andagain.uk), Dul Zorigoo (dzrgo.com), Metalab (metalab.com).*
- **UI 1.6 — Animated results/data charts.** Podium/results bar charts and
  cohort/area charts that animate in on scroll — used on the landing
  sample-outputs section and inside the in-app parsed-results view. Vanilla JS
  + CSS custom properties; no charting SDK required. *Inspired by Mixpanel
  (mixpanel.com).*
- **UI 1.7 — Pinned-panel scrollytelling.** A sticky visual panel that swaps its
  content per workflow step (results → moments → drafts → approve) as the
  narrative scrolls past on the landing how-it-works section. Pure CSS
  scroll-driven; no JS library. *Inspired by Linear (linear.app).*
- **UI 1.8 — Timestamp-anchored reel review comments.** Feedback markers pinned
  to a specific moment on a generated reel in the review surface; stored per
  run/card in SQLite, displayed as overlays on the video scrubber. Flask-backed,
  no new external service. *Inspired by Frame.io.*
- **UI 1.9 — Multi-select + bulk actions.** Checkboxes, select-all, and bulk
  approve/export/delete in the Media Library and review queue. Pure HTML form
  multi-select with progressive JS enhancement; no new routes beyond extending
  existing action endpoints. *Inspired by Frame.io.*
- **UI 1.10 — Visual template/archetype gallery.** Browse all 12 content
  archetypes with preview thumbnails and category filters before creating a pack.
  Renders existing archetype data from the design-spec catalog; no new API or
  external service. *Inspired by Chronicle (chroniclehq.com).*
- **UI 1.11 — Tabbed code-example switcher.** Language tabs + syntax highlighting
  + copy button on the Developer/API docs page. Pure HTML/CSS tabs; syntax
  highlighter bundled locally (no CDN). *Inspired by Resend (resend.com).*
- **UI 1.12 — Results data table.** Sortable/filterable parsed-results view with
  inline sparklines (athlete progress over time) and coloured delta badges
  (PB/improvement). Server-side sort via existing Flask routes; vanilla JS
  sparklines drawn on `<canvas>`. *Inspired by Wope (wope.com).*
- **UI 1.13 — Annotated UI callouts.** Labelled hotspots + SVG connector lines
  on a sample card and the review UI, forming an 'anatomy of a card' diagram for
  the landing or onboarding tour. Static HTML/SVG; no new library. *Inspired by
  Liveblocks (liveblocks.io).*
- **UI 1.14 — Notifications inbox.** A bell icon + unread-count badge + dropdown
  listing render-complete, pack-ready, and error events. Backed by the existing
  scheduler/notify layer; polled via lightweight SSE or periodic fetch; no
  external push service. *Inspired by Liveblocks (liveblocks.io).*
- **UI 1.15 — Command palette / Cmd-K.** Fast keyboard navigation and quick
  actions (jump to Create / Library / Settings; trigger common actions). Vanilla
  JS; keyboard-accessible; no framework. *Inspired by GitHub.*
- **UI 1.16 — Dashboard activity feed.** Recent runs, approvals, and exports as
  cards with status badges, relative timestamps, and expandable detail.
  Server-rendered from the existing audit log; no new data source. *Inspired by
  GitHub.*
- **UI 1.17 — Content-cadence heatmap.** A calendar activity grid showing
  generation and posting consistency over the past year. Server-rendered inline
  SVG from run history; no JS library required. *Inspired by GitHub's
  contribution graph.*
- **UI 1.18 — Inspector/properties panel.** A lightweight side panel to tweak a
  generated card before approval: edit caption text, swap brand palette swatch,
  toggle elements, adjust crop. Posted back to existing Flask card-edit routes;
  no new persistence layer. *Inspired by Sketch (sketch.com).*
- **UI 1.19 — Testimonial/social-proof carousel.** Club/coach quote cards with
  avatar initials, arrow controls, and autoplay on the landing. Pure CSS/JS; no
  carousel library. *Inspired by Sketch (sketch.com).*
- **UI 1.20 — Polished pricing page.** Tier cards with check/cross feature lists,
  a recommended-plan highlight, a billing-period toggle, and a feature comparison
  table. Server-rendered; matches existing CSS variables. *Inspired by Resend
  (resend.com).*
- **UI 1.21 — Text-scramble/decode animation.** Character-by-character
  scramble-then-decode reveal for the 'engine is generating…' processing state
  and optional hero headline. Vanilla JS; respects `prefers-reduced-motion`.
  *Inspired by Locomotive (locomotive.ca).*
- **UI 1.22 — FAQ accordion.** Expandable Q&A section on the landing. Pure HTML
  `<details>`/`<summary>` with CSS transition animation; no JS library. *Inspired
  by Limitless AI and status pages.*
- **UI 1.23 — Light/dark theme toggle.** Dark-first with an optional light mode.
  CSS custom-property swap + `localStorage` persistence + `prefers-color-scheme`
  default; no new build step. *Inspired by AuthKit (authkit.com).*
- **UI 1.24 — Moment-type marquee/ticker.** A continuous horizontal scrolling
  ticker of moment types (PBs · medals · comebacks · finals · club records) or
  club names used as a section divider on the landing. Pure CSS `animation:
  marquee` loop. *Inspired by SavoirFaire and SuperHi.*
- **UI 1.25 — Emoji reactions.** Quick emoji reactions (👍 ❤️ 🔥) on generated
  cards and in the review queue. Reaction counts stored per card in the existing
  DB; tallied server-side; updated via fetch without a full page reload. *Inspired
  by Liveblocks (liveblocks.io).*
- **UI 1.26 — Cursor-anchored progress/info readout.** A small percent/status
  label that follows the cursor during long actions (render/upload). Vanilla JS
  pointer-position tracking; disappears on completion; hidden on touch devices.
  *Inspired by UNVEIL and Cosmos (cosmos.so).*
- **UI 1.27 — Horizontal drag/scroll gallery.** A mouse-draggable horizontal
  carousel for the Media Library and the landing sample-output showcase. Vanilla
  JS pointer-event drag; CSS `overflow-x: auto` with scroll-snap; no carousel
  lib. *Inspired by Fey (feyapp.com) and Sketch (sketch.com).*
- **UI 1.28 — Keyboard shortcuts overlay.** Press `?` to reveal a modal listing
  available shortcuts; quick keys to approve/reject/navigate in the review flow.
  Vanilla JS; no new dependencies. *Inspired by GitHub.*
- **UI 1.29 — Sticky chaptered scroll-spy nav.** A fixed side chapter/section nav
  that highlights the current section on long pages and the how-it-works guide.
  Pure JS IntersectionObserver + CSS sticky; no library. *Inspired by Linear
  (linear.app).*
- **UI 1.30 — AI 'weekend at a glance' summary panel.** An at-a-glance summary
  card of the meet's key story (top swims, PBs, medals) surfaced from
  MediaHub's existing summarisation pipeline — no external API, no additional LLM
  call beyond what the content pack already produced. *Inspired by Mixpanel
  (mixpanel.com) and Fey (feyapp.com).*

**Building blocks.** All shipped: the primary flow, the design-spec director +
12-archetype catalog, the Adaptive Theming Engine, magic-link mobile approvals,
the autonomy controls. This phase is craft on top of them.

**Dependencies.** None — this is the front of the queue.

---

### Phase 2 — Direct publishing · P4 · ❌ **NOT STARTED**

**Goal.** Replace the paid Buffer dependency with direct platform adapters,
prioritising the genuinely-free targets.

**Exit criterion.** Posts publish via **direct APIs to ≥2 platforms including
a genuinely-free one** (Bluesky and/or Mastodon), with Buffer demoted to
optional.

**In-house first (rule 11).** Publishing is the one place a third party's own
network is the *unavoidable* final hop — you cannot post to a platform without
its API. So the in-house-first destinations come first: MediaHub's **own
surfaces** (the shipped public wall / website embed / RSS — PC.10 — and the
planned microsites, P6.13) are fully first-party and need no external account at
all; the **open, self-hostable protocols** (Bluesky/AT Protocol,
Mastodon/ActivityPub, email over an in-house SMTP relay) come next; the
**proprietary platforms** (Meta, X, TikTok, YouTube, Telegram) are optional,
thin, swappable adapters for the final hop to a network the club already uses.
Everything upstream of that hop — the content, the intelligence, the branding,
the gate and the audit — is in-house.

#### P4.1 — Bluesky (AT Protocol) + Mastodon adapters · ❌

The free/open posting targets — build these first. **Build detail (June 2026
feasibility pass):** `publishing/bluesky.py` (AT Protocol; app-password or
OAuth — **no app review or business verification exists at all**) and
`publishing/mastodon.py` (per-instance REST; apps register programmatically),
both beside `buffer.py`, both gated by the P2.3 publish gate and writing
`publishing/posting_log.py`; per-workspace account binding in Settings; image
+ W.11 alt-text first, video where the instance allows. Each adapter is days,
not weeks — they rehearse the connector pattern (connect → gate → post → log
→ audit) before the Meta review lands, and they make the autonomy story
demonstrable end-to-end on a zero-risk network.

#### P4.2 — Instagram Graph / Facebook / TikTok / YouTube adapters · ❌

Least-privilege per integration; a human connects each account. **Platform
API policy gates auto-posting (verified June 2026):** Instagram
content-publishing needs a Business/Creator account + a connected Facebook
Page + Meta **App Review** (~2–4 weeks/permission) + **Business
Verification**; TikTok's *unaudited* Content-Posting client can post only
**private (SELF_ONLY), ≤5 users/24h** until it passes an audit. That is *why*
P4.1 ships first and why F.8 starts the Meta paperwork early — the clock runs
in parallel instead of after. Code needs when it opens: a Pillow **JPEG
export** path in `graphic_renderer` (the IG API is JPEG-only), a "Connect
Instagram" flow, and `publishing/meta.py` behind an operator flag + the
publish gate. IG limits are workable (100 API-published posts/24h incl.
Reels/Stories/carousels); group packs as **carousels** by default (the
engagement format in the 2025 benchmarks). **TikTok and YouTube stay deferred
until clubs demand them.**

#### P4.3 — X adapter · ❌

X moved to pay-per-use (6 Feb 2026); treat as a paid, optional target.

#### P4.4 — Demote Buffer to optional · ❌

**Resilience work, not preference:** Buffer's classic developer API has been
closed to new developers since 2019, remaining third-party integrations were
cut off 1 Mar 2025, and the 2026 beta API lacks third-party OAuth — so the
current connector (`publishing/buffer.py`) runs on borrowed time and cannot
onboard new clubs' accounts. P4.1/P4.5/P4.6 are the replacement paths; keep
Buffer only while the legacy token still functions, and surface an honest
error the day it stops.

#### P4.5 — Email digest delivery · ❌ *(pull-forward candidate during Phase C)*

The v7.3 grouped newsletter already builds
(`/api/runs/<run_id>/newsletter`, `content_pack/builder.py`) — nothing can
send it. Email needs no platform review, and clubs already run parent lists.
**Build:** `publishing/email.py` behind a provider seam with an **in-house SMTP
relay the default** (the operator's own mail server; the digest, list and
unsubscribe logic is all first-party) — a managed relay (Resend, free to 3k
emails/mo) is an optional deliverability upgrade on the same seam, and an unkeyed
deployment with no relay configured honest-errors rather than dropping mail
silently; deliverability is the operator's SPF/DKIM/DMARC homework either way;
a per-workspace member list (CSV import with consent capture,
one-click unsubscribe + suppression list — unsubscribes honoured before any
send); a weekly `scheduler/` job assembling approved-card digests; the PC.8
sponsor slot and W.11 alt text in the template; W.9 approval links ride the
same channel. **Exit:** a club imports members and receives a weekly digest
of approved content; unsubscribes stick; unkeyed deployments honest-error.

#### P4.6 — Telegram channel publishing (+ WhatsApp share stopgap) · ❌ *(pull-forward candidate during Phase C)*

The best effort-to-value publish target found in the June 2026 feasibility
pass: the Telegram Bot API is free, needs no review, and sends **PNG and MP4
natively** — reels currently have no scheduled outlet anywhere. WhatsApp has
no official Channels API, so the legitimate answer today is a share
affordance. **Build:** `publishing/telegram.py` (per-workspace bot token +
channel binding; `sendPhoto`/`sendVideo` with caption + W.11 alt text) behind
the publish gate + posting log; a review-UI "share to WhatsApp" button (copy
caption, download media, open `wa.me`). **Exit:** an approved card *and* a
reel both land in a connected Telegram channel through the gate with full
audit; the WhatsApp button works on mobile.

**Building blocks.** MediaHub's own wall / embed / RSS (PC.10, shipped) as the
zero-dependency in-house target; Bluesky / Mastodon (free/open protocols) next;
an **in-house SMTP relay** as the default email channel (a managed relay like
Resend optional on the same seam) and the free Telegram Bot API alongside;
Postiz adapters as *reference only* (**AGPL** — read the patterns or call over
its API; never embed).

**Dependencies.** Needs **P2** (autonomy + guardrails govern what may
auto-publish) and **P0** (Buffer is a flagged, optional paid path).


---

### Phase 3 — Creative-suite breadth (our own versions, MediaHub-shaped) · P6 · ❌ **NOT STARTED**

**Goal.** Build **MediaHub's own first-party version of every
content-creation capability Canva and Adobe Express ship** — re-expressed
through this product's thesis (data in → meaningful, branded, approval-gated
content out), never by integrating their tools or becoming a blank-template
shop. The evidence base is two exhaustive competitor inventories
([Canva](research/CANVA_FEATURE_INVENTORY_2026.md),
[Adobe Express](research/ADOBE_EXPRESS_FEATURE_INVENTORY_2026.md)); **every
bullet in both** is mapped — feature by feature, with a completeness index —
in [`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md). The 24 one-line
work packages (P6.1–P6.24) are in the Fable 5 to-do list above; the companion
doc carries each package's build depth and per-item exit criterion.

**Order within the phase.** Within the
phase, order is **pull-driven** — build what paying clubs ask for first; the
numbering is a default sequence, not a promise. Standing rules hold
everywhere: hosted-only, approval-first publishing + the P2.3 gate, the
deterministic-engine boundary, Gemini→Anthropic honest-error AI, self-hosted
fonts, and the GWS / 9router exclusions. **In-house first (rule 11):** every
capability here is MediaHub's own first-party code; an external service appears
only as an optional, flag-gated, swappable slot behind our own interface, and
only for a genuinely-unavoidable final hop — never for the intelligence or the
data. That includes generative imagery (P6.3), whose **default backend is a
licence-clean local diffusion model** filled by the Phase-4 **P5.6** path, and
the platform surface (P6.20), whose MCP server is one MediaHub *exposes*, not one
it depends on. The narrow set of unavoidable externals: model hosting (with the
in-house local path the default), platform-publish APIs, print fulfilment, and
music rights.

**Exit criterion.** A club can run its **entire content life inside
MediaHub** — social, print, email, microsite, video, documents — without
reaching for Canva/Express; measured per-item (each P6 item carries its own
exit in the companion doc) and in aggregate by wedge clubs actually
cancelling their Canva habit.

**Building blocks.** Almost entirely seams that already ship: the design-spec
director + archetypes (P1.4), `graphic_renderer` + autofit + saliency, both
reel engines (P0.1), the cutout layer, the TTS/ASR/LLM provider slots (P0.4),
`media_library`, `workflow` + publish gate, `scheduler/`, `notify/`,
`observability/`, PC.3 tenancy. New heavy deps stay licence-vetted per
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).

**Dependencies.** No longer gated behind commercialisation (reprioritised 2026-06-13). P6.16's
analytics loop and P6.14's send adapter additionally need **P4** adapters;
P6.2 voice input and P6.5 captions need the **P5.3** ASR seam filled (or a
cloud provider on the same seam). Feeds back into **PC.4** packaging
(quotas/tiers).

---

### Phase 4 — Zero-cost local AI everywhere · P5 · ❌ **NOT STARTED**

**Goal.** Give every AI call a zero-cost local path, completing the
no-hidden-fees discipline for the hosted deployment's margins.

**Exit criterion.** With **no cloud keys configured**, the full pipeline
(caption, cutout, voice, graphics, reels, **and generative imagery**) runs
**locally end-to-end** — honest-erroring only where a local model is genuinely
unavailable.

- **P5.1 — Ollama LLM provider.** Both wrappers already accept a keyless
  OpenAI-compatible endpoint (`MEDIAHUB_LLM_ENDPOINTS=http://localhost:11434/v1`
  reaches a running Ollama today — P0.4); what remains is shipping/operating
  the model runtime, model-selection defaults, and the operator workflow.
- **P5.2 — Piper TTS replaces edge-tts.** The provider slot is already
  registered (`MEDIAHUB_TTS_PROVIDER=piper` honest-errors until this lands) —
  P5.2 fills the slot with the real backend.
- **P5.3 — whisper.cpp / faster-whisper ASR.** Local transcription for reel
  captions / word-level burn-in. Must land behind a provider seam — the P0.4
  guard fails the build on any unslotted ASR import.
- **P5.4 — Satori graphics fast-path.** ~100× lighter card rendering than
  headless Chromium. A *performance* play, not a licensing one (P0.1's ffmpeg
  engine already removed the Remotion requirement); slots into the same
  `MEDIAHUB_REEL_ENGINE` seam. (The placeholder `satori` engine name was
  removed in the dormant-features audit — register it again when the engine
  actually ships.)
- **P5.6 — Local generative-image backend.** Fills the `media_ai` image seam
  P6.3 builds against with a **licence-clean self-hosted diffusion model**
  (e.g. FLUX.1-schnell, Apache-2.0), so generate / edit / fill / expand / remove
  run with **no cloud key**. Cloud generators (Imagen/etc.) stay optional on the
  same seam; provenance manifests (P6.22) stamp every output regardless of
  backend. Licence-vetted per `DEPENDENCY_LICENSING.md` — avoid OpenRAIL /
  non-commercial weights, prefer an Apache-2.0/MIT model.

**Building blocks.** All **ADOPT-NOW** licences: Ollama (MIT), Piper (MIT),
whisper.cpp / faster-whisper (MIT), Satori (MPL-2.0), and a permissively-licenced
local image model for P5.6 (FLUX.1-schnell, Apache-2.0). ⚠️ Avoid Coqui XTTS
weights commercially (CPML, non-commercial) — Piper instead; and avoid OpenRAIL /
non-commercial image weights — pick an Apache-2.0/MIT model.

**Dependencies.** Set up by **P0** (the local-capable interfaces all
exist — P0.4). Note P5.5 (cutout) shipped long ago — rembg is already the
default; see [`ROADMAP_BUILT.md`](ROADMAP_BUILT.md).


---

### Phase 5 — Rebrand & identity · F.9–F.11 + PC.15 · ❌ **NOT STARTED**

**Goal.** Retire the "MediaHub" working title for the real, defensible company
name, register it, own the domain, and sweep the new brand through every
customer-facing surface. **First of the final three** — done once the product is
genuinely wanted, before a second sport and before selling.

**Exit criterion.** The chosen name passes the four-register diligence (F.9), the
company is registered (F.10) and owns its `.co.uk` (F.11), and the rebrand sweep
(PC.15) has threaded one product-name source of truth through the UI chrome,
legal pages, wall badge + embeds, email from-name, `/try` and the README, with
the old `*.onrender.com` URLs 301-redirecting.

The founder half (F.9 name → F.10 company → F.11 domain) is on the founder list
above with full step-by-step guides; **PC.15** (the code sweep) waits on F.9's
chosen name. Why the name is upstream of every filing, and why the domain comes
before any host move:

#### F.9–F.12 — Business identity, own domain, cheaper hosting · ❌ founder work (guides above; added & prioritised 2026-06-12) + PC.15/PC.16 code halves

Why this workstream jumped to the head of the founder list:

- **The name is upstream of every filing.** Stripe's KYC (F.1), the ICO
  register entry (F.2), the solicitor-reviewed legal pack (F.3), the Swim
  England application (F.5), insurance (F.6), the Meta verification dossier
  (F.8) and the domain itself (F.11) all embed the legal identity. File them
  under a throwaway name and a later rename re-does — and re-pays — the lot.
  "MediaHub" was always a filler: generic, shared with other companies,
  indefensible as a brand or trade mark. So: **F.9 name → F.10 company →
  F.11 domain → only then the identity-bearing paperwork.**
- **"Due diligence", defined once:** the free checks that prove nobody
  already owns the name — Companies House register, UK trade marks (classes
  9/41/42), the domain, the social handles, and a passing-off web search —
  done *before* committing, so nobody can force a rebrand later. The F.9
  guide is that checklist in order; it costs an afternoon and £0.
- **Domain before host.** Every printed QR code, embedded wall, bookmark and
  webhook that points at `mediahub-gzwc.onrender.com` dies with that
  subdomain. Pointing them at our own `.co.uk` first (F.11 — Render serves
  custom domains + TLS today) makes the later host move an invisible DNS
  flip and unbreaks every link forever.
- **The hosting numbers, honestly** (verified June 2026): Render standard —
  the 2 GB the Chromium/Remotion renders need — is **$25/mo ≈ £20/mo** +
  disk; a capable EU VPS (Hetzner CX22 4 GB → CX32 8 GB) is
  **€3.79–7.59/mo**; UK-soil VPS ≈ £5–15/mo `[ESTIMATE]`. Saving ≈
  **£150–200/yr** `[ESTIMATE]` — real, but less than a fifth of one paying
  club, which is why F.12 sits *behind* the identity work, offers an
  explicit "stay and revisit at traction" option, and may never displace a
  selling week. A side benefit if taken: today's host stores Club Data in
  the **US** (per the DPA's subprocessor register); an EU/UK box simplifies
  F.4's transfer-mechanism homework.
- **The move is already cheap to execute.** The deploy is one Dockerfile
  (compose + `fly.toml` templates exist), all state lives under `DATA_DIR`,
  and PC.14 shipped daily backups with a restore drill rehearsed on every
  test run — restoring a production backup onto a new box *is* the
  migration. PC.16 packages the remainder: reverse-proxy TLS template,
  off-site backup preflight, a Render-API-free log-sentinel source, the
  staged subprocessor/privacy updates, and the cutover runbook.
- **What this is *not*:** a self-host tier. ADR-0011's hosted-only principle
  is untouched — the operator's one deployment changes data centre;
  customers still only ever get a URL.

---

### Phase 6 — Second sport (broaden ingestion spokes) · P3 · 🔒 gated on Phases 1–5 · ❌ **NOT STARTED**

**Goal.** Ingest beyond swimming and normalise every spoke to the canonical
schema, so a second sport produces real content end-to-end.

**Exit criterion.** **≥1 non-swimming sport** produces real content
end-to-end from a real data source (football via openfootball, or basketball
via nba_api), with a registered `recognition_<sport>` adapter and its sport
profile wired in.

- **P3.1 — Second-sport engine adapter.** `recognition_football` or
  `recognition_basketball` + `register_sport(...)` (the seam exists —
  [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)). Bind `engine_sport` in the
  profile.
- **P3.2 — Sports-data spokes (in-house first).** Vendor the public-domain /
  open datasets — `openfootball` (public domain), MIT fixture generators — into
  the repo as curated, versioned, provenance-stamped data, exactly like the
  qualifying-time packs (W.4) and the open-collection stock pools (P6.8). A live
  external sports API (`nba_api` → stats.nba.com) is an **optional, flag-gated
  spoke behind a seam, never required**; each spoke normalises to `canonical.*`.
- **P3.3 — Running/athletics parsers.** Chip-timing CSV + client-side Garmin
  `FIT` parsing. This sport needs custom parsers — open-source coverage is
  sparse.
- **P3.4 — Normalise all spokes to the canonical schema.** Separate raw
  extraction from cleaned canonical data; flag ambiguous rows for review.

**Building blocks.** `openfootball` (**public domain**) and
`ndPPPhz/Fixture-Generator` (MIT) — both **vendored into the repo as in-house
data/code**, the default path; `swar/nba_api` (open, keyless — *verify*) only as
the optional live external spoke. ⚠️ `statsbomb/open-data` is a **non-OSS data
agreement** — use openfootball as the free default.
([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md))

**Dependencies.** 🔒 **Hard-gated (rule 12): does not start until Phases 1–5 are
complete** — product polish, direct publishing, the creative suite, zero-cost
local AI, and the rebrand all land first (founder directive 2026-06-13). Also
needs **P1** (sport profiles + taxonomy). Pairs with **P4** (new sports → new
audiences → more publishing targets). Note: `results_fetch/` already does
sport-agnostic *ingestion* from a URL; P3 adds the per-sport *detector* quality.


---

### Phase 7 — Go to market · PC.4 / PC.6 + F.1–F.8 / F.13 / F.12 + PC.16 · 🔒 gated on Phases 1–5 · ❌ **NOT STARTED**

**Goal.** Commercialise — lawfully and without the founder in the loop — once the
product is excellent, rebranded and proven on a second sport. **The last thing we
do.**

**Why last (reprioritised 2026-06-13).** The earlier plan put commercialise first
([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md),
[ADR-0015](adr/0015-compliance-readiness-sell-gate.md),
[SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md)); the founder has
reversed the *ordering* to perfect the product first. Those records stand as the
evidence for the prior decision — and "distribution kills solo ventures, not
product gaps" remains the standing caution this phase exists to answer.
(This phase was **"Phase C"** in the prior commercialise-first plan; the
`PC.*` item IDs keep the "C", and the founder guides above still refer to it
by that name — they mean this phase.)

**Upstream of all three: the product-completion gate (rule 12).** This whole
phase is 🔒 hard-gated — it does not begin until **Phases 1–5 are complete**
(product polish, direct publishing, the creative suite, zero-cost local AI, the
rebrand) and the second sport (Phase 6) has landed. Warm groundwork (PC.4
quotes, PC.6 funnel) may keep moving, but the full go-to-market push waits. The
three gates below then define "ready to sell" within this phase (they no longer
gate the earlier build phases — those ship first regardless):

**Exit criteria (three hard gates).**

1. **Commercial-readiness gate:** a club can sign up, pay, and publish with
   **zero founder involvement**. No selling starts until this
   holds.
2. **Traction gate:** **≥10 clubs paying annually** to validate the wedge. If
   the wedge stalls below ~50 clubs over time, that is a retention/PMF
   problem to fix — **not** a signal to add sports.
3. **Compliance-readiness ("lawful-to-sell") gate** (added 2026-06-12,
   [ADR-0015](adr/0015-compliance-readiness-sell-gate.md)): **no paid
   contract** before versioned Terms + Privacy Notice are live and accepted
   at signup, the club DPA exists, ICO registration is done, the minors'
   consent gate enforces end-to-end, deletion + export work, and
   password-reset / breach-notice / verified-backup basics are in place.
   Quotes (PC.4) and the funnel (PC.6) keep moving; a quote may not convert
   to payment until this gate holds.

The founder-side selling, payments, legal sign-off, ops, repo-private and hosting
tasks are on the founder list above (F.1–F.8, F.13, F.12) with step-by-step
guides; **PC.16** is the buildable hosting-cutover half. The pricing and
distribution detail:

#### PC.4 — Pricing by revealed willingness-to-pay · 🔵 founder work (guide above)

Build shipped 2026-06-11: a quote ledger (`commercial/wtp.py`,
`DATA_DIR/commercial/wtp_quotes.jsonl`), per-quote Stripe Checkout charging
exactly the quoted figure, an idempotent amount-verified webhook, and both
gates live on `/operator/commercial`. `/pricing` reads the gate and stays at
the honest "Pricing TBC" until **≥5 clubs have paid annual at a tested
price**, then commits the highest cleared figure. The rule (the
>95 %-confidence step): under-pricing is hard to reverse and over-pricing
with no buyers teaches nothing — only revealed WTP from real annual payments
de-risks the tier. The price *levels* remain an unvalidated hypothesis:

| Comparator | Segment | Current price | What it anchors |
|---|---|---|---|
| **Gipper** (closest analog) | US K-12/college athletic depts | **$625 / $1,500 / $3,000 per year, annual-only** *(verified 2026-06-09)* | The institutional ceiling with a sales motion |
| **Predis.ai** (horizontal AI) | Any SMB / creator | **$19 / $40 / $212 per month** *(verified 2026-06-09)* | The buyer's mental ceiling for "AI makes my posts" |
| **SwimTopia** (swim incumbent) | Swim clubs | ~$150–$699/yr annual | What a club pays when software is mission-critical |
| **Canva Free** | Volunteer creator | **£0** | The free substitute every volunteer already has |
| **Swim Wales affiliation** | Whole NGB relationship | £150/yr | The volunteer treasurer's anchor for "what anything costs" |

Read together: the commodity floor and the £150/yr NGB anchor pull the Club
tier down; Gipper proves a far higher institutional ceiling — but only for a
schools/federation buyer with a budget. That gap is why Routes B/C carry the
revenue weight and why the Club tier must be set by revealed WTP, not assumed.

#### PC.6 — Go-to-market / distribution · 🔵 founder work (guide above)

Distribution kills solo ventures, not product gaps. Instrumented 2026-06-11:
lead ledger by source, cold-share readout, referral-debt readout
(`commercial/pipeline.py` on `/operator/commercial`); the Swim England
application is drafted and submission-ready (F.5). The channel evidence:

- **NGB, split in two** (reality-checked, [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)):
  **(a) data-API access is real — apply** (Swim England approved-systems API,
  announced 1 Oct 2025; grants data + credibility, not promotion);
  **(b) promotional endorsement is speculative** — partner slots are
  category-exclusive and already held; if no NGB movement after ~6 months,
  lean on direct + word-of-mouth. The down-weight reinforces **Route C**
  (incumbent integration) as the realistic distribution partner.
- **Warm-first design** (the >95 %-confidence part): warm/in-person
  founder-led sales convert ~30–50 % vs ~2–5 % cold reply; SaaS referrals
  drive 20–50 % of new B2B customers. Honest funnel to the gate: **~5
  local-warm + ~5 referral**, cold as a capped supplement
  (~0.3–1 % cold-to-paid ⇒ 1,000–3,000 contacts to do it cold — not viable
  solo). Realistic timeline **~3–6+ months**. The *outcome* is unproven and
  IS the validation — it also closes PC.4.

#### Strategy notes — the three credible £1M+ routes (context, *not* build items)

The only routes the diligence considers arithmetically credible for £1M+,
recorded so the expansion phases stay sequenced with revenue in mind. **All
figures are estimates.**

- **Route A — Multi-sport UK grassroots** (broadest TAM, weakest moat;
  confidence of £1M ~15–20 %) → sequences **P3**.
- **Route B — US schools/colleges** (highest WTP, proven by Gipper/FanWord at
  $625–$3,000/yr; needs US presence; <15 % solo, higher with a partner).
- **Route C — Content/integration layer for swim-data incumbents** (license
  the engine to SwimTopia/TeamUnify rather than fight them; trades upside for
  survival; ~50/50 it beats going direct).

**Highest-leverage combination:** NGB data-API access + incumbent integration
(Route C) for *distribution* + US-schools repositioning (Route B) for
*revenue*.

**Building blocks.** Stripe (Checkout + Customer Portal + webhooks); the
existing `DATA_DIR` ledgers (no SQLAlchemy); the shipped ADR-0003 isolation
invariant; Postiz / Mixpost org→workspace schemas as *reference only* over a
network boundary (never embed AGPL —
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).


**Dependencies.** 🔒 **Hard-gated (rule 12): does not start until Phases 1–5 are
complete** (product polish, direct publishing, the creative suite, zero-cost
local AI, the rebrand), and still sequenced **after** Phase 6 — the second sport
lands before the go-to-market push too. As with the compliance gate, warm
relationships and groundwork (PC.4 quotes, PC.6 funnel) may keep moving, but no
full GTM push and no paid conversion proceed until the product is complete. The
selling, payments, legal sign-off, ops, repo-private and hosting tasks
(F.1–F.8, F.13, F.12) and the PC.16 hosting-cutover half all sit behind this
gate.

## The rules we build by

Decisions already made — don't re-open them mid-build. Full reasoning lives
in the linked records. (An **ADR** is an Architecture Decision Record: a
short note of a decision and why, kept in [`docs/adr/`](adr/).)

1. **Hosted only.** Clubs use MediaHub in the browser on our deployment. We
   never offer a copy to run themselves, free or paid — that would hand power
   users a permanent zero-revenue escape hatch.
   ([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md))
2. **Product-complete before commercialise** *(reprioritised 2026-06-13,
   founder directive).* The usability + capability work (Phases 1–4) ships
   first; the rebrand (5), the second sport (6) and go-to-market (7) come
   last. This **reverses** the earlier "commercialise before generalise"
   ordering — that prior decision and its evidence stay on record in
   [ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md) and
   [SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md); only the build
   *order* changed, not the standing caution that distribution, not product,
   kills solo ventures.
3. **Lawful-to-sell before sold.** Gate 3: no paid contract before the legal
   pack, the minors' consent gate, deletion/export rights, and the
   password-reset/breach/backup basics hold.
   ([ADR-0015](adr/0015-compliance-readiness-sell-gate.md))
4. **Make it genuinely wanted, then sell** *(reprioritised 2026-06-13).*
   Product polish and the capability gaps that make clubs actually *want*
   MediaHub (Phases 1–4) come **before** the selling motion (Phase 7). This
   reverses the earlier "stop polishing and sell" stance — the generative
   engine cleared the "sellable wedge" bar (P1.4), but the founder has chosen
   to make the whole product excellent before commercialising.
5. **Facts are code; judgement is AI; errors are honest.** Parsers,
   detectors, the ranker and the colour-science stay deterministic — never an
   AI guess. Creative judgement goes through `media_ai.llm` / `ai_core.llm`
   (Gemini first, Anthropic failover); with no provider configured the app
   shows an honest error, never a faked caption or palette.
   (See [`../CLAUDE.md`](../CLAUDE.md).)
6. **A human approves before anything publishes. Always.** The single
   exception: a workspace may opt one post type into `fully_autonomous`, and
   even then every post must pass the full publish gate — kill switch,
   provenance, confidence, brand safety, rate caps, and **minors' content
   never auto-publishes**. ([AUTONOMY_MODEL](AUTONOMY_MODEL.md))
7. **Swim England: data yes, promotion no.** Apply for the official data API
   (real, dated — F.5); do not plan around NGB promotional endorsement (no
   evidence it exists for content tools).
   ([ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md))
8. **Do / don't (only what the evidence supports).**
   **DO:** warm-first hand-sell from the Swansea network · annual prepay ·
   a referral engine (2 named intros per signed club) · the Swim England API
   application · Bluesky + Mastodon as the first free publish targets.
   **DON'T:** paid ads · viral-growth assumptions · VC fundraising · US
   expansion before UK validation · multi-sport as a *substitute* for fixing
   wedge traction · reliance on NGB promotion · launch-day Instagram/TikTok
   auto-posting ·
   ToS-breaching scraping of results data.
9. **Honest money expectations (estimates, not promises).** Swimming-only
   saturates at ≈ £150k–£400k ARR (~1,300 UK&I + ~2,740 USA clubs). The old
   "£1M/month" goal is dropped — £1M+ ARR needs multi-sport breadth *and*
   institutional buyers *and* almost certainly a second person. The horizons:

| Horizon | Paying clubs | ARR @ £588–£1,188/club | Outcome probability `[ESTIMATE]` | Binding constraint |
|---|---|---|---|---|
| **H1 — Validation** (≤ ~12 mo) | ~10 (the traction gate) | ≈ £6k–£12k | **~40–55%**, *conditional on the founder actually running the warm + referral motion* | Founder selling-time; first revealed WTP (PC.4) |
| **H2 — Early scale** (~1–2 yr) | ~30–60 | ≈ £18k–£71k | **~25–40%** — needs H1 + referral compounding + retention (annual prepay) | Support capacity (multi-tenancy already shipped — PC.3) |
| **H3 — Swimming ceiling** (~2–4+ yr) | ~125–680 (price-dependent) | **≈ £150k–£400k** | **~10–20%** — needs UK *and* US penetration + a second person | Market size + support capacity |
| **H4 — £1M+ ARR** | (out of wedge) | **≥ £1M** | **low-double-digit-%** — multi-sport (Route A) + institutional buyers (Route B) + a second person | Out-of-wedge expansion |

10. **The head start is real but undefended.** Verified June 2026: no swim
    incumbent ingests a result file and emits branded ranked content — but
    that is a *time advantage, not a moat*. Watch item: Gipper adding
    result-file ingestion would close it.
11. **In-house first; external only for the unavoidable final hop**
    *(added 2026-06-13, founder directive).* Every roadmap capability is
    MediaHub's own first-party code, and every AI call has a zero-cost local
    path (Phase 4 — caption, cutout, voice, graphics, reels, and generative
    imagery via P5.6). An outside service is allowed **only** as an optional,
    flag-gated, swappable adapter behind a first-party seam, and **only** for a
    genuinely-unavoidable final hop to a third party's own network: posting to a
    social platform a club already uses, processing a card payment (Stripe — one
    cannot lawfully be one's own card processor), or sending to a physical
    printer. The intelligence, content, data, branding, scheduling, gating and
    audit are always in-house; data we can hold (openfootball, fixtures, stock,
    fonts, music) is **vendored**, not called. MediaHub **depends on no external
    MCP** — it may *expose* a first-party MCP server (P6.20) for outside agents
    to drive. This hardens the standing "external services only behind our own
    interfaces" convention into a rule. (See [`../CLAUDE.md`](../CLAUDE.md).)
12. **Second sport + go-to-market are hard-gated on a complete product**
    *(added 2026-06-13, founder directive).* Phase 6 (second sport, P3.*) and
    Phase 7 (go-to-market, PC.4 / PC.6 / PC.16 + F.1–F.8 / F.12 / F.13) do
    **not** begin until **Phases 1–5 are complete** — product polish, direct
    publishing, the creative suite, zero-cost local AI, and the rebrand — and
    Phase 7 still follows Phase 6. Warm groundwork may continue, but no full GTM
    push or paid conversion proceeds ahead of the gate. This formalises the
    build-first ordering of rules 2 & 4 into a hard gate on the last two phases;
    the gated items are marked 🔒 throughout.

**Companion docs:** [POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md) ·
[CONTENT_PLANNER](CONTENT_PLANNER.md) · [AUTONOMY_MODEL](AUTONOMY_MODEL.md) ·
[SPORT_PROFILES](SPORT_PROFILES.md) ·
[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md) ·
[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md) · [THEMING](THEMING.md) ·
[GENERATION](GENERATION.md) ·
[CREATIVE_SUITE_PARITY](CREATIVE_SUITE_PARITY.md) (Phase 3 — creative-suite long-form) ·
evidence base in
[research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md) and
[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md) ·
ideas backlog in
[research/PRODUCT_IDEAS_2026-06.md](research/PRODUCT_IDEAS_2026-06.md).

## Changelog

### Strategy changelog (hand-written — newest first)

One table row per strategy/roadmap change, added by hand (the daily roadmap
engine or a Fable 5 session). Engineering ships are tracked by the Completed
list and the auto table below, not here.

| Date | Change | Read more |
|---|---|---|
| 2026-06-13 | **In-house-first hardened + second-sport/GTM hard-gated (founder directive):** every roadmap idea is now explicitly first-party — an external service is allowed only as an optional swappable adapter for the unavoidable final hop (social-platform publishing, Stripe card rails, physical print), never for intelligence / content / data. Concrete closes: generative imagery (P6.3) gains an in-house local-diffusion backend (**new P5.6**, FLUX.1-schnell-class, Apache-2.0); email (P4.5) defaults to an in-house SMTP relay (managed relay optional); second-sport data (P3.2) is vendored public-domain / open data with live APIs optional; the P6.20 MCP server is clarified as one MediaHub *exposes* (it depends on no external MCP). New **rule 11** (in-house first) + **rule 12** (Phase 6 second sport & Phase 7 go-to-market 🔒 gated until Phases 1–5 complete). | Rules 11 & 12 · P5.6 · P6.3 |
| 2026-06-13 | **Roadmap reordered — build-first, market-last (founder directive):** usability + capability work pulled to the front (Phase 1 product polish · 2 direct publishing · 3 creative-suite breadth · 4 zero-cost local AI); the three deliberately-last things sequenced at the end, in order — **5 rebrand · 6 second sport · 7 go to market.** Phases renumbered into priority order (item IDs kept stable); the gating that made P3–P6 wait on paying clubs is lifted. Everything already shipped moved out of this file into [`ROADMAP_BUILT.md`](ROADMAP_BUILT.md), so no completed items / no ✅ ticks remain on the roadmap. Reverses the commercialise-first *ordering* of rules 2/4 + ADR-0011/0015 — the prior decision's evidence stands. | Rules 2 & 4 · [`ROADMAP_BUILT.md`](ROADMAP_BUILT.md) |
| 2026-06-12 | **Daily scan — Swim England platform move (material):** Swim England announced (4 Mar 2026) a Sport:80-built membership platform launching Autumn 2026, with a new **Rankings API** for verified swim times and a swimmingresults.org integration underway, and a SportsEngine integration announcement expected later in 2026. F.5’s application route should be re-verified against this programme before submitting (dated note added to the F.5 guide); the Swim England↔SportsEngine tie-up is also a fresh input to the queued Route C go/no-go. Competitor watch otherwise quiet (Gipper/SwimTopia/TeamUnify/Swimcloud: no results-ingestion or auto-graphics move); IG Graph API and TikTok Content Posting API policies stable. ⚠️ *Flagged for founder review (not adopted):* PR #418’s public passwordless operator sign-in is an owner-decided demo convenience, but it exposes every tenant’s data and the operator consoles — re-lock it at the latest alongside F.13, before the first club pays (ADR-0015 gate 3). | [Sport:80 announcement](https://www.swimming.org/swimengland/sport80-membership-platform/) · F.5 guide |
| 2026-06-12 | **Repo privacy queued as founder work (F.13):** the GitHub repo is public today and must return to private — at the latest before the first club pays, because the lawful-basis note for the real-children's-data parser fixtures (OPEN_LEGAL_QUESTIONS Q13 / DATA_MAP §6) assumes a private repo, and ADR-0011's hosted-only stance treats the source as the product. The new guide covers the one real cost (private-repo Actions minutes — trim the CI schedules or GitHub Pro), the visibility flip, integration re-verification (Render, Claude Code, CI, Dependabot), and recording the public window honestly in the compliance docs. | Founder guide F.13 · [Q13](compliance/OPEN_LEGAL_QUESTIONS.md) |
| 2026-06-12 | **Sell-gate items closed out + the roadmap now keeps itself honest:** PC.9 and PC.11–PC.14 verified fully shipped on the code side (all 55 pinning tests green) and moved to Completed; their remaining halves are founder-only and live on the founder list with updated step-by-step guides (F.6 gains the breach-owner + off-site-backup steps). The auto-update bot gained a **completed-item sweep**: any to-do item marked ✅ moves itself to Completed on the next push to `main`, and a declared human remainder is kept on — or filed into — the founder list, so finished items can no longer squat on a to-do list. | *Status* section · [`scripts/roadmap_autoupdate.py`](../scripts/roadmap_autoupdate.py) |
| 2026-06-12 | **Business identity, own domain & cheaper hosting prioritised (F.9–F.12 + PC.15/PC.16):** the real company name comes before any further filings (MediaHub is an indefensible filler), then Companies House registration (£100 digital; director ID-verification mandatory since Nov 2025), then the .co.uk domain wired to the live app — so Stripe/ICO/solicitor/Swim England paperwork files **once**, under the real name, and every printed/shared link survives any future host. The Render→VPS move (≈£20/mo → ≈£4–8/mo, prices verified June 2026) is sequenced last, as a DNS flip, and must never displace selling. | Founder guides F.9–F.12 · Phase C section |
| 2026-06-12 | **Sell-gate code remainders + referral engine shipped (PC.9, PC.11–PC.14 code halves):** subprocessor-register guard test (caught 3 undisclosed flows) + unlicensed vendor dirs removed; W.2 consent enforced on the public wall + Children's-Code pass recorded (synthetic `/try` sample replaces real minors' data); whole-org deletion + takeout ZIP; transactional-email seam (password reset / verification / invites / breach channel), daily backups + rehearsed restore, incident runbook; in-product referral engine with auto-granted Stripe rewards. Remaining on the sell gate is founder-only (F.1–F.8). | Phase C section · [CHILDRENS_CODE_PASS](compliance/CHILDRENS_CODE_PASS.md) · [SUPPORT_INCIDENT_RUNBOOK](SUPPORT_INCIDENT_RUNBOOK.md) |
| 2026-06-12 | **UK legal compliance baseline shipped (PR #352):** in-product Terms / accurate Privacy Notice / Cookie Policy / Art. 28 DPA with versioned, recorded acceptance; erasure cascades, account deletion + export; correction/takedown workflow; retention sweep; CCR/DMCCA pre-contract checkout; auth rate-limiting + security headers; DPIA draft. PC.11/PC.13 mostly delivered, PC.12/PC.14 started; the founder half became the F.* list above. | [COMPLIANCE_AUDIT](COMPLIANCE_AUDIT.md) · [COMPLIANCE_HANDOVER](COMPLIANCE_HANDOVER.md) |
| 2026-06-12 | **Compliance-readiness audit:** Phase C had been pushing "go sell" with zero legal surface — compliance had no owning channel because Phase C was composed from a revenue diligence. Fix: a third **lawful-to-sell exit gate** + four sell-gate items **PC.11–PC.14**; no paid contract before gate 3 holds. | [ADR-0015](adr/0015-compliance-readiness-sell-gate.md) |
| 2026-06-11 | **Phase C build-out:** PC.7 try-before-signup demo, PC.8 sponsor manager + exposure reports, PC.10 public achievements wall shipped; `/pricing` now enforces PC.4's revealed-WTP gate (≥5 paid annual); PC.6 audited build-complete. What remains on PC.4/PC.6 is the founder's selling motion. | Phase C section |
| 2026-06-11 | **Phase 6 added:** every content-creation feature in the two competitor inventories (Canva, Adobe Express) gets a MediaHub-shaped, first-party build plan — 24 gated work packages (P6.1–P6.24) with a coverage index. | [CREATIVE_SUITE_PARITY](CREATIVE_SUITE_PARITY.md) |
| 2026-06-11 | **Daily scan — no material change:** competitor watch (Gipper, SwimTopia, TeamUnify, Swimcloud) shows no results-ingestion move; platform policies unchanged; Swim England club-API news only reinforces the queued Route C go/no-go. | [ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md) |

### Recent code activity (auto-updated — newest first)

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-06-15 | `c9b71d894` | style: apply ruff-format to style_packs.py |
| 2026-06-15 | `61e99b623` | feat(graphics): 1,000+ unique templates via a deterministic style-pack catalog |
| 2026-06-15 | `4ddb2d302` | Make the landing-hero product demo engaging and self-explanatory |
| 2026-06-15 | `955fa4cf3` | ui: remove the command palette (Cmd-K "search or jump to") from the top nav |
| 2026-06-15 | `0fa259f69` | ui: widen content column on large screens so the layout fills the viewport |
| 2026-06-15 | `f4aa388d7` | UI2.4: client-side workflow tabs on the review queue |
| 2026-06-15 | `ebb08dc15` | Document MEDIAHUB_RESULTS_FETCH_RENDER_RECYCLE; regen env inventory |
| 2026-06-15 | `f47f4a88d` | Recycle headless browser periodically so heavy-site crawls don't wedge |
| 2026-06-15 | `71bcbca55` | Remove light/dark theme toggle and heading scramble animation |
<!-- /ROADMAP:ACTIVITY -->
