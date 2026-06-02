# MediaHub Roadmap Rebuild — Strategy, Architecture & Open-Source "What to Steal" Catalogue

## TL;DR
- **Build MediaHub as a content-strategy brain, not a results parser.** No mature open-source project today combines (a) autonomous multi-sport content strategy, (b) per-content-type automation toggles, and (c) truly-free self-hosting — that gap is MediaHub's differentiation. Assemble the product from the ~55 catalogued building blocks below rather than adopting any single platform.
- **The no-hidden-fees constraint is satisfiable but requires discipline.** The truly-free permissive core is: hytek-parser / tdsmith-sdif (parsing), Satori (graphics), Piper / whisper.cpp (audio), Ollama / llama.cpp (LLM), rembg / MODNet (cutout), nba_api / openfootball (data), Temporal (orchestration). The traps to design around are Remotion (commercial Company License — Creators $25/seat/mo, Automators $0.01/render with a $100/mo minimum, Enterprise $500/mo minimum), Postiz / MediaCMS / MinIO (AGPL network-copyleft), Mixpost (open-core, Pro forbids SaaS), Coqui XTTS (non-commercial model), n8n (source-available Sustainable Use License), and every default that assumes a paid OpenAI / Gemini / MuAPI key.
- **Phase the rebuild:** Phase 0 de-risk licensing/cost; Phase 1 strategy brain + post-type taxonomy + sport profiles; Phase 2 autonomy toggles on a Temporal backbone; Phase 3 broaden ingestion beyond swimming; Phase 4 drop Buffer for direct platform APIs; Phase 5 local-AI substitution to guarantee zero hidden cost.

## Key Findings
1. **An end-to-end autonomous multi-sport social media manager does NOT exist in open source.** The closest agents (langchain-ai/social-media-agent, Social-GPT/agent, crewAI flows) are AI-content-niche, human-in-the-loop, and depend on paid APIs. The integrated product is whitespace.
2. **MediaHub's current video engine (Remotion) is the single biggest hidden-cost liability.** It is free only for individuals and for-profit companies of up to 3 people; beyond that a Company License applies (Creators $25/seat/mo; Automators $0.01/render with a $100/mo minimum; Enterprise $500/mo minimum). From Remotion 5.0, telemetry via `licenseKey` is mandatory for the Automators (render-based) tier.
3. **The best publishing reuse (Postiz) is AGPL-3.0.** Its README states the source "is available under the AGPL-3.0 license" and "the self-hosted version has no feature limitations compared to the cloud version." Fine to self-host; viral if you fork/embed its code into a distributed product.
4. **Every "brand-DNA / campaign" generator that looks ideal (Open-Pomelli) routes all AI calls through a paid API (MuAPI).** Free substitutes (Ollama, Piper, rembg, Satori) exist for each call.
5. **A clean three-source intelligence model** (own signals + external signals + direct input) maps onto a hub-and-spoke architecture orchestrated by Temporal (MIT), which is already battle-tested ("every Snap story uses Temporal"; 3,000+ paying customers including Nvidia, Netflix, Snap and Stripe).

---

## PART A — STRATEGY

### A.1 Product thesis (new direction)
MediaHub is a **content-strategy brain** for sports teams. The hub is an intelligence layer that assesses what a given team should post, drafts it, and (where permitted) publishes it autonomously. Results ingestion is **one spoke among many**, not the core. The product is **multi-sport** and **multi-tenant** (one workspace per team), **human-approval-gated by default**, with a **per-content-type toggle** that can flip any single post type to fully autonomous.

This reframes MediaHub away from "swimming results → social posts" toward "any sports team → the right posts, mostly on autopilot." Swimming becomes the first reference implementation of a generic pattern, not the product's identity.

### A.2 Cross-sport post-type taxonomy
A **"sport profile"** is a configuration object that parameterises four things per post type: (1) whether it is enabled, (2) what data inputs feed it, (3) which template set renders it, and (4) its default autonomy level.

**Universal post types (sport-agnostic, ~70% of volume):** fixture/event announcements, results/score recaps, player/athlete spotlights, birthdays, signings/recruitment, sponsor activation, ticket/merch promos, behind-the-scenes, milestone celebrations, season recaps, "this day in history."

**Sport-specific divergence:**
- **Swimming:** meet recap, PB/qualifying-time spotlight, heat/lane preview, relay splits, club-record board. Inputs: Hy-Tek HY3/HYV, SDIF/CL2/SD3, PDF/HTML results, swimmingresults.org verification.
- **Football/soccer:** matchday XI, full-time score, goal/assist leader, league-table standings, fixture run-in. Inputs: openfootball JSON, StatsBomb open-data, fixture generators.
- **Basketball:** game-day matchup, final box score, player-of-the-game, standings, highlight clip. Inputs: nba_api, ag-psd PSD templates (cf. NBA-Gameday-Generator).
- **Running/athletics:** race preview, finish-time/PB spotlight, podium recap, club championship table, training-block milestone. Inputs: chip-timing CSV, Garmin FIT files (cf. swim-data-analyser pattern).

The **sport profile** model means adding a sport = authoring a config + a parser + a template set, not rewriting the engine.

### A.3 Autonomy model
- **Default = gated.** The brain produces a content plan + drafts; a human approves before publish.
- **Per-type toggle.** Each content type carries an `autonomy_level` ∈ {`draft_only`, `approval_required`, `fully_autonomous`}. A team can set "final-score posts" to fully autonomous while keeping "signings" gated.
- **What the toggle controls:** whether the publish step requires a human-approval activity, the confidence threshold required to auto-publish, and which guardrails run.
- **Guardrails for autonomous posting:** data-provenance verification (the existing trust-ledger pattern), template/profanity/brand-safety checks, rate limiting, a global "kill switch," and an immutable audit trail. Temporal's human-in-the-loop **signal** pattern is the reference implementation: a workflow pauses on a signal for gated types and skips the wait for autonomous types.

### A.4 Three-source intelligence model
- **Own signals:** past social history, engagement data, brand DNA (logos/colours/fonts/voice). Feeds tone learning + best-time-to-post (derive from the team's own history rather than a third-party dataset).
- **External signals:** fixtures, results, news, peer/rival club posts, trending formats. Feeds the "what's happening" trigger layer (the spokes).
- **Direct input:** onboarding answers, goals, blackout dates, sponsor obligations. Feeds the planning constraints.

The brain fuses all three into a ranked content plan; newsworthiness ranking (already built for swimming highlights) generalises into the cross-source prioritiser.

---

## PART B — ARCHITECTURE

### B.1 Target hub-and-spoke design
1. **Strategy brain (hub):** an LLM-agent planner (CrewAI / LangGraph pattern) that fuses the three sources into a ranked content plan. Runs on a local LLM (Ollama) to stay free.
2. **Ingestion spokes:** results parsers (swimming today), sports-data APIs (nba_api, openfootball), news/peer scrapers. Each spoke normalises to a typed schema.
3. **Asset-generation engines:** graphics (Satori → PNG), video/reels (Remotion today — flag), captions (local LLM), theming (material-color-utilities), TTS (Piper), cutout (rembg/MODNet).
4. **Publishing layer:** direct platform APIs (to replace Buffer), or self-hosted Postiz adapters.
5. **Orchestration backbone:** Temporal workflows; each content type is a workflow with an optional human-approval signal — this is what physically implements the autonomy toggle.
6. **Multi-tenancy:** workspace/org isolation (Postiz and Mixpost both demonstrate org-partitioned Postgres schemas).
7. **Local-AI substitution layer:** Ollama (LLM), Piper/whisper.cpp (speech), rembg/MODNet (cutout), Satori (graphics) — guarantees zero per-call cost.
8. **Storage/DAM:** S3-compatible object storage (MinIO — flag AGPL) or cloud S3, plus a media library.

### B.2 Component → building-block map
- Strategy brain → crewAI / langchain social-media-agent (patterns) + Ollama
- Orchestration / autonomy toggle → temporalio/temporal
- Results ingestion → hytek-parser, tdsmith/sdif, SwimmeR; nba_api, openfootball, StatsBomb
- Graphics → vercel/satori, Agamnentzar/ag-psd, Pillow/node-canvas
- Video → Remotion (flag) / openshorts / short-video-maker
- Captions / strategy text → Ollama, llama.cpp
- TTS → Piper (free) / Coqui toolkit (XTTS model non-commercial)
- ASR / captioning → whisper.cpp, faster-whisper, openai/whisper, WhisperX
- Cutout → rembg, MODNet
- Theming → material-color-utilities, palx
- Publishing → Postiz (AGPL), Mixpost (open-core), direct APIs
- Multi-tenancy → Postiz / Mixpost reference schemas
- Storage → MinIO (AGPL) / cloud S3

---

## PART C — REPO CATALOGUE (55+ repositories)

### C.1 Autonomous content-strategy / AI social-media agents
- **langchain-ai/social-media-agent** — Agent that sources, curates and schedules posts with human-in-the-loop. *Steal:* the human-in-the-loop "Agent Inbox," few-shot voice examples (`TWEET_EXAMPLES`), business-context prompt (`BUSINESS_CONTEXT`). *Differs:* TypeScript/LangGraph, AI-content-niche. *License:* MIT-family (verify). *Hidden fees:* depends on FireCrawl + Arcade (free tiers then paid) and an LLM key. *Relevance:* general tooling.
- **Social-GPT/agent** — Autonomously strategizes + executes a campaign from a brand description; generates topic lists and per-topic ideas. *Hidden fees:* requires a GPT-3/4 key (paid). *Substitute:* Ollama.
- **kevingil/social-media-agent** — Autonomous marketing agents on LangChain (hackathon-grade; reference only).
- **Prem95/socialautonomies** — MIT. X/Twitter AI agent: post/schedule/auto-reply via X API + browser cookies. *Steal:* scheduling + auto-engage loops. *Note:* ships Stripe plan scaffolding (it is a SaaS starter).
- **crewAIInc/crewAI** — Standalone multi-agent orchestration (Crews + Flows), human-in-the-loop triggers, RBAC/audit in enterprise tier. *Steal:* the planner/researcher/writer crew pattern for the strategy brain. *License:* open-source (verify MIT). *Hidden fees:* framework free; LLM calls cost unless local.
- **crewAIInc/crewAI-examples** — Content Creator Flow (multi-crew blog/LinkedIn generation), Lead Score Flow (human-in-the-loop review). *Steal:* directly adaptable content-flow templates.

### C.2 Workflow orchestration & scheduling
- **temporalio/temporal** — **MIT.** Durable execution / workflow engine; automatic retries, long-running workflows, human-in-the-loop signals. *Steal:* this is the autonomy-toggle backbone. Very mature — 3,000+ paying customers including Nvidia, Netflix, Snap and Stripe. Truly free to self-host. *Relevance:* core infra.
- **temporalio/sdk-typescript, sdk-php, sdk-python** — MIT SDKs (TS, PHP, Python all confirmed MIT).
- **n8n-io/n8n** — ⚠️ **Sustainable Use License (fair-code, NOT OSI open-source).** Free for internal self-host and personal use; commercial-product/resale use restricted; files containing `.ee.` require the n8n Enterprise License. ~108k+ stars. *Steal:* visual workflow patterns. *Flag prominently:* not safe as the embedded engine of a product you sell.
- *Fully-open alternatives for the scheduling layer:* Windmill, Apache Airflow, Prefect, Celery, BullMQ.

### C.3 Results & sports-data ingestion (multi-sport)
- **SwimComm/hytek-parser** — **MIT.** Parses Hy-Tek Meet Manager HY3 (merge), HYV (event), XLS exports; Python 3.9+; ~21 stars; "Production/Stable." Truly free; its own CI even fails the build on GPL/AGPL deps. *Relevance:* swimming.
- **tdsmith/sdif** — **Apache-2.0.** SD3/SDIF read+write. Truly free. Swimming.
- **gpilgrim2670/SwimmeR** — **MIT.** R package; reads PDF/HTML/HY3 results, course conversions, bracket drawing; on CRAN. Swimming.
- **jgolliher/hyparse** — ⚠️ **NO LICENSE (all rights reserved; not legally reusable).** HY3 → JSON/Pandas with Pydantic models. Reference only.
- Swimming scrapers: **MauroDruwel/Swimrankings**, **maflancer/SwimScraper**, **adghayes/swimset**, **alexkgrimes/swimulator** — verify licenses individually before reuse.
- **swar/nba_api** — Open-source NBA.com API client (Python); free, no key. Basketball; powers NBA-Gameday-Generator.
- **openfootball/football.json** — **Public domain** football fixtures/results JSON; no API key. Football. Doubles as a simple multi-sport schema reference (name/matches/round/date/team1/team2/score). Related: **openfootball/worldcup.json** (incl. 2026), also public domain.
- **statsbomb/open-data** — Free football event data (JSON: competitions, matches, events, lineups, 360 data). ⚠️ Not an OSS license — the **StatsBomb Public Data User Agreement** (attribution + responsible-use; non-commercial-style). Separate code-vs-data license. **statsbomb/amf-open-data** — American-football equivalent, same agreement.
- **pybaseball** — Baseball data (verify license, typically MIT). Baseball.
- **TheSportsDB** — Free crowd-sourced multi-sport API; free tier exists, premium needs a key; rate/abuse limits on the free tier (the maintainers note the unlimited free API "became too popular and was abused").
- Fixture generators: **ndPPPhz/Fixture-Generator** (**MIT**, JavaScript/npm `fixture-generator`, round-robin), **EdwinWalela/fixture-generator** (⚠️ **C++, NO LICENSE** — not reusable), **stfnwp/sports-schedule-generator**, **Michi83/League-Schedule-Manager** (verify licenses).
- **IPTC Sport Schema** (standard, not a code repo) — formal multi-sport open standard (RDF/JSON-LD; successor to SportsML) for results, statistics, schedules and rosters; closest thing to an "open team sports data standard" (there is no real repo using the acronym "OTSD").

### C.4 Highlight / moment detection
- **AkhilNam/Sports-Highlight-Detector** — Video-based highlight detection (OpenCV/YOLOv8). *Steal:* clip-worthy moment detection for reels. Verify license.
- **iut62elec/Soccer-Highlight-Generator-with-GenAI** — ⚠️ MIT code but requires **PAID AWS Bedrock.** *Substitute:* local Whisper + Ollama.
- **matija2209/sports-highlights-generator** — FFmpeg highlight concatenation + audio-transcription microservice. Verify license.
- **SamurAIGPT/AI-Youtube-Shorts-Generator** — **MIT;** ~3.3k stars. LLM virality scoring + auto vertical crop + Whisper. ⚠️ Default `--mode api` uses paid MuAPI; `--mode local` runs free (yt-dlp + faster-whisper + ffmpeg/opencv, OpenAI/Gemini only for ranking). *Steal:* virality scoring with score+hook+reason per clip.

### C.5 Social graphic / data-to-image generators
- **vercel/satori** — **MPL-2.0.** HTML/CSS (JSX) → SVG → PNG; ~100× lighter than headless Chromium; React-Native Flexbox layout engine. *Steal:* replace Playwright card rendering. Truly free. Core building block.
- **Agamnentzar/ag-psd** — JS library to read/write Photoshop PSD files. *Steal:* let teams upload PSD templates, bind data to layers, auto-render. Verify MIT. Sport-agnostic.
- **ajamous1/nba-gameday-generator** — FastAPI + React + nba_api + Playwright + Node/ag-psd; renders NBA gameday posters and one-click posts to IG/Reddit; custom-PSD upload (beta). *Steal:* the entire data→poster→publish pipeline pattern. Verify license. Basketball but generalisable. (Its README's "$200/mo X write access" note is now outdated — see C.12.)
- **chrisvxd/puppeteer-social-image** — Puppeteer HTML→social image. Verify license.
- **macleod-ee/auto-social-images** — Automated social-image generation. Verify license.

### C.6 Brand / palette / theming
- **material-foundation/material-color-utilities** — **Apache-2.0.** Material You colour extraction, OKLCH/HCT palettes. *Steal:* brand-DNA palette generation. Truly free. Sport-agnostic.
- **jxnblk/palx** — **MIT.** Automatic palette from one base colour.
- **brianmcdo/ImagePalette** — PHP palette extraction.
- **KieronQuinn/MonetCompat**, **marijnvdwerf/material-palette** — Material palette references (verify licenses).

### C.7 Programmatic video & reels
- **remotion-dev/remotion** — ⚠️ **Source-available, NOT free for larger for-profit orgs.** Free only for individuals, ≤3-employee for-profits, non-profits, and evaluation. Otherwise a Company License: **Creators $25/seat/mo (no minimum); Automators $0.01/render with a $100/mo minimum; Enterprise $500/mo minimum.** From v5.0, telemetry via `licenseKey` is mandatory for the Automators tier. MediaHub's current engine — **flag as top cost liability.**
- **mutonby/openshorts** — **MIT.** Clip + publish shorts. Truly free.
- **GabrielLaxy/TikTokAIVideoGenerator**, **steinathan/reelsmaker**, **gyoridavid/short-video-maker**, **IgorShadurin/app.yumcut.com**, **vvinniev34/RedditReels** — verify licenses + paid-API deps individually.

### C.8 TTS / voiceover
- **rhasspy/piper** — **MIT.** Fast local neural TTS (ONNX/VITS); real-time on CPU/Raspberry Pi; 30+ languages. *Steal:* free voiceover. Truly free. Core building block.
- **OHF-Voice/piper1-gpl** — ⚠️ **GPL** (newer Piper repo). Flag copyleft.
- **idiap/coqui-ai-TTS** — ⚠️ Toolkit is **MPL-2.0** (commercial OK with source-disclosure), but the **XTTS-v2 model is CPML — non-commercial only, and no commercial licensor exists post-shutdown** (Coqui closed January 2024; community confirms "you can only use XTTS under the CPML now, there is no one to sell a commercial license anymore"). Use VITS/Tacotron backends commercially; avoid XTTS weights commercially.
- **matatonic/openedai-speech** — OpenAI-speech-compatible local TTS server (verify license).
- **edge-tts** — (MediaHub current) free but relies on a Microsoft Edge endpoint; not a guaranteed-stable contract.

### C.9 ASR / transcription & captioning
- **openai/whisper** — **MIT.** Reference ASR model (code + weights MIT). ~90k stars. Truly free locally.
- **ggerganov/whisper.cpp** (now ggml-org/whisper.cpp) — **MIT.** C/C++ Whisper; fast CPU. ~30k+ stars. Truly free.
- **SYSTRAN/faster-whisper** — **MIT.** CTranslate2 Whisper; fast. ~23k stars; actively maintained (v1.2.1, Oct 2025). Truly free.
- **m-bain/WhisperX** — word-level timestamps + diarization (verify license, BSD-family). *Steal:* word-level caption burn-in for reels.

### C.10 Background removal / cutout (free, self-hosted)
- **danielgatis/rembg** — **MIT.** Background removal (U²-Net, BiRefNet, SAM, isnet-anime); CLI/library/HTTP server/Docker; ~20k+ stars. *Steal:* replace paid Photoroom/Replicate. Truly free. Sport-agnostic (cut out athletes for spotlights).
- **ZHKKKe/MODNet** — **Apache-2.0** for code/models (the PPM benchmark dataset is CC BY-NC-SA 4.0); ~4.2k stars. Portrait matting. Truly free.
- **BiRefNet / RMBG models** — high-quality matting models; check individual model licenses (RMBG-1.4 carries non-commercial terms).

### C.11 Local LLM serving (free captions/strategy brain)
- **ollama/ollama** — **MIT.** One-command local LLM runtime; OpenAI-compatible API; ~170k+ stars; runs Llama/Qwen/Gemma/DeepSeek/gpt-oss. *Steal:* the zero-cost brain backend. Truly free. Core building block.
- **ggerganov/llama.cpp** (MIT), **vLLM**, **LocalAI**, **oobabooga/text-generation-webui** — local serving alternatives. **LM Studio** is proprietary freeware — flag.

### C.12 Platform publishing libraries (replace Buffer)
- **gitroomhq/postiz-app** — ⚠️ **AGPL-3.0.** 30+ platforms, uncapped self-host with no feature limits vs cloud, multi-tenant org schema (Prisma/Postgres), Temporal-based scheduling, public REST API + Node SDK, n8n/Make/Zapier connectors. Star count is point-in-time (cited anywhere from ~20k to ~31k across directories). *Steal:* publishing adapters + multi-tenancy + scheduling. *Flag:* AGPL virality if you fork/embed; calling it over its API/network is lower-risk than forking source.
- **gitroomhq/postiz-agent** — Postiz Agents CLI for AI agents (AGPL family).
- **inovector/mixpost** — ⚠️ **Open-core.** Lite = MIT (feature-limited); Pro/Enterprise are commercial (license code required at install). **Pro license explicitly forbids building a SaaS** ("a Mixpost app Pro license cannot be used to build a SaaS platform"); Enterprise is required for per-workspace billing/SaaS. One-time pricing model. *Steal:* the workspace model. *Flag:* the SaaS prohibition.
- **socioboard/Socioboard-5.0** — **GPLv3.** Microservices, RSS curation. Flag copyleft.
- **Direct-API references to build:** Instagram Graph API, Facebook Pages, TikTok Content Posting API, YouTube Data API, X API, LinkedIn, Mastodon, Bluesky (AT Protocol — free/open). **X API pricing update:** as of 6 Feb 2026 pay-per-use is the default for new developers ($0.01 per post created; standard writes ~$0.015/request, posts containing a URL ~$0.20/request; the free tier discontinued; the legacy $200/mo Basic tier remains only for existing subscribers). Postiz's adapters are the best reference implementation; Bluesky/Mastodon are the genuinely-free posting targets.

### C.13 Social analytics / best-time-to-post
- Open, well-licensed tools are **scarce**; most best-time data is proprietary (Buffer/Later blog reports). Small reference repos exist (e.g. an `InstagramBestTimePost`) but lack clear licensing/stars. **Recommendation:** derive best-time-to-post from the team's OWN historical engagement rather than adopting a library — this is also more defensible and tenant-specific.

### C.14 Multi-tenancy / RBAC references
- **gitroomhq/postiz-app** — org/workspace partitioning, RBAC, multi-tenant Postgres schema (Prisma), state machine for posts (DRAFT/QUEUE/PUBLISHED). Strongest reference architecture.
- **inovector/mixpost** — unlimited isolated workspaces; Enterprise adds per-workspace billing/onboarding.

### C.15 DAM / media storage
- **minio/minio** — ⚠️ **AGPLv3** (community edition now source-only; commercial AIStor is a separate paid product; community edition entered maintenance/archival flux in late-2025/early-2026 per community trackers). S3-compatible object storage. *Steal:* free Cloudinary replacement for brand assets + generated content. *Flag:* AGPL + maintenance concerns; **cloud S3 is the lower-risk alternative** if you want to avoid AGPL entirely.
- **mediacms-io/mediacms** — ⚠️ **AGPL-3.0.** Django/React media CMS, local Whisper transcription, RBAC, HLS; ~2.3k+ stars; actively maintained (Python 3.13). Note as a heavyweight media-CMS reference, not sports-specific. Flag AGPL.

### C.16 Lineup / tactical generators
- **remidej/11-builder** — Visual football XI builder (React/Cheerio). Football. Verify license.
- **ashhhlynn/optimize-fantasy-football** — lp-solver.js lineup optimisation.
- **DimaKudosh/pydfs-lineup-optimizer** — Python DFS optimiser (multi-sport). **n-roth12/DFSLineupOptimizer** — similar.
- **bwiggs/dodgeball-lineup**, **sports-club-manager/leaguesort** (league-table sorting). Verify licenses. *(This category is peripheral to the content-strategy thesis; treat as optional "interactive post" generators.)*

### C.17 Sports club / league management references
- **ChanMeng666/countryside-community-swimming-club** — **Apache-2.0.** Resolves the prior-report disagreement: the repo was **rewritten** from the original Python/Flask/MySQL to **Next.js 16 / React 19 / Neon Postgres / Drizzle / Better Auth on Cloudflare Workers** (the stale GitHub "About" blurb still says Flask/MySQL; the current code is ~86% TypeScript). ~4 stars. Reference only.
- **tktintin/swim-team-management-system** — Java desktop, swimming. Reference.
- **wp-plugins/wp-swimteam** — **GPL** WordPress plugin; swim-team admin, SDIF/HY3 CSV export. Flag GPL.
- **JimmyRowland/team_sporty** — team pages, rosters, availability. Verify license.
- **Br0kenByDesign/HydroHero** — swim performance tracking, pool-course time normalisation. **PeterK-end/swim-data-analyser** — client-side Garmin FIT parsing (useful pattern for running/athletics ingestion).

### C.18 Generic CMS / design-editor references (mostly off-target)
- **wastech/content-management-system** — **MIT,** NestJS headless CMS. Generic; weak fit.
- **clawnify/open-design** — open-source Canva alternative (Fabric.js v6, AI-agent-optimised UI mode). Verify license/cost. Useful only if MediaHub adds an in-app editor.
- **lidojs/canva-clone** — ⚠️ React Canva clone, but a **custom "use at your own risk" license, and the download/export feature is NOT included in the package** (effectively a freemium source-teaser). Flag.
- **Sourav0010/videotube-backend**, **BlueprintIT/Swim** (archived generic CMS, coincidental name), **entire-media/comator** (minimal CMS) — off-target; do not prioritise.
- **SamurAIGPT/Open-Pomelli** — **MIT code,** but ⚠️ **all AI calls route through paid MuAPI** (free sandbox keys only). Brand-DNA-from-URL + campaign generation + canvas editor + image-to-video; Next.js 16 + SQLite/Prisma. *Steal:* the brand-DNA-from-URL flow and goal-based campaign concepts. *Substitute* every MuAPI call with Ollama/Satori/rembg/Piper. Related: **HazemMeqdad/Open-Pomelli-api** (API variant), **anselm94/insta-caption-generator-streamlit** (needs Gemini key), **aashish-bidap/AI-based-Social-Media-Caption-Generator** (local CNN/LSTM — truly free).

---

## PART D — SYNTHESIS & ROADMAP INPUT

### D.1 Summary table
| Repo | Category | License | Truly free self-host? | Paid dep? | Maturity | All-sports relevance |
|---|---|---|---|---|---|---|
| temporalio/temporal | Orchestration | MIT | Yes | No | Very high (3,000+ customers) | Core infra |
| ollama/ollama | Local LLM | MIT | Yes | No | Very high (~170k★) | Core infra |
| vercel/satori | Graphics | MPL-2.0 | Yes | No | High | Sport-agnostic |
| rhasspy/piper | TTS | MIT | Yes | No | High | Sport-agnostic |
| danielgatis/rembg | Cutout | MIT | Yes | No | High (~20k★) | Sport-agnostic |
| openai/whisper | ASR | MIT | Yes | No | Very high (~90k★) | Sport-agnostic |
| ggerganov/whisper.cpp | ASR | MIT | Yes | No | High (~30k★) | Sport-agnostic |
| SYSTRAN/faster-whisper | ASR | MIT | Yes | No | High (~23k★) | Sport-agnostic |
| ZHKKKe/MODNet | Cutout | Apache-2.0 (code) | Yes | No | Med (~4.2k★) | Sport-agnostic |
| material-color-utilities | Theming | Apache-2.0 | Yes | No | High | Sport-agnostic |
| SwimComm/hytek-parser | Ingestion | MIT | Yes | No | Stable (~21★) | Swimming |
| tdsmith/sdif | Ingestion | Apache-2.0 | Yes | No | Stable | Swimming |
| gpilgrim2670/SwimmeR | Ingestion | MIT | Yes | No | Stable (CRAN) | Swimming |
| jgolliher/hyparse | Ingestion | NONE ⚠️ | No (no license) | No | Active | Swimming |
| swar/nba_api | Data | Open (verify) | Yes | No | High | Basketball |
| openfootball/football.json | Data | Public domain | Yes | No | Active | Football |
| statsbomb/open-data | Data | Custom agreement ⚠️ | Attribution/non-comm | No | Active | Football |
| ndPPPhz/Fixture-Generator | Fixtures | MIT | Yes | No | Old but usable | Multi-sport |
| EdwinWalela/fixture-generator | Fixtures | NONE ⚠️ | No (no license) | No | Low | Football |
| Agamnentzar/ag-psd | Graphics | MIT (verify) | Yes | No | Active | Sport-agnostic |
| ajamous1/nba-gameday-generator | Graphics pipeline | verify | Yes | No (X API optional) | Active | Basketball→general |
| remotion-dev/remotion | Video | Source-available ⚠️ | No (for-profit >3) | Company license $100+/mo | Very high | Sport-agnostic |
| mutonby/openshorts | Video | MIT | Yes | No | Med | Sport-agnostic |
| SamurAIGPT/AI-Youtube-Shorts-Generator | Video/highlights | MIT | Yes (local mode) | MuAPI (api mode) | Active (~3.3k★) | Sport-agnostic |
| gitroomhq/postiz-app | Publishing | AGPL-3.0 ⚠️ | Yes | No (optional AI) | High (~20–31k★) | Sport-agnostic |
| inovector/mixpost | Publishing | Open-core ⚠️ | Lite only | Pro/Ent commercial | High | Sport-agnostic |
| minio/minio | Storage | AGPLv3 ⚠️ | Yes | No | High (maint. flux) | Infra |
| mediacms-io/mediacms | Media CMS | AGPL-3.0 ⚠️ | Yes | No | Med (~2.3k★) | Reference |
| crewAIInc/crewAI | Agent framework | Open (verify MIT) | Yes | LLM cost unless local | High | Strategy brain |
| langchain-ai/social-media-agent | Agent | MIT-family (verify) | Partial | FireCrawl/Arcade/LLM | Med | General |
| SamurAIGPT/Open-Pomelli | Brand/campaign | MIT ⚠️ | Code yes | MuAPI (all AI) | Active | General |
| n8n-io/n8n | Orchestration | Sustainable Use ⚠️ | Internal only | Enterprise for resale | Very high (~108k★) | Infra (caution) |
| idiap/coqui-ai-TTS | TTS | MPL-2.0 / XTTS CPML ⚠️ | Toolkit yes | XTTS non-commercial | Med | Sport-agnostic |
| ChanMeng666/countryside-community-swimming-club | Club mgmt | Apache-2.0 | Yes | No | Low (~4★) | Swimming |
| wp-plugins/wp-swimteam | Club mgmt | GPL ⚠️ | Yes | No | Mature | Swimming |
| lidojs/canva-clone | Design editor | Custom ⚠️ | No (export paywalled) | No | Active | Off-target |

### D.2 ADOPT NOW / WITH CAUTION / AUDIT / AVOID
**ADOPT NOW (permissive, truly free):** temporalio/temporal, ollama/ollama, ggerganov/llama.cpp, vercel/satori, rhasspy/piper, danielgatis/rembg, ZHKKKe/MODNet, openai/whisper + whisper.cpp + faster-whisper, material-color-utilities, jxnblk/palx, SwimComm/hytek-parser, tdsmith/sdif, gpilgrim2670/SwimmeR, swar/nba_api, openfootball/football.json, ndPPPhz/Fixture-Generator, mutonby/openshorts.

**ADOPT WITH CAUTION (license/cost caveat, usable if respected):**
- **Postiz (AGPL)** — run as a separate self-hosted service / call over its API; do NOT fork its code into MediaHub's own distributed binary unless you will comply with AGPL source-disclosure.
- **MediaCMS / MinIO (AGPL)** — same network-copyleft caution; prefer cloud S3 over MinIO to avoid AGPL entirely.
- **crewAI / langchain social-media-agent** — free frameworks, but pair with Ollama so LLM calls cost nothing.
- **ag-psd / nba-gameday-generator pattern** — excellent for autonomous graphics; confirm ag-psd's MIT.
- **Coqui toolkit** — use only VITS/Tacotron backends commercially; XTTS-v2 weights are non-commercial.

**AUDIT BEFORE USE (license unconfirmed or partial):** AkhilNam/Sports-Highlight-Detector, matija2209/sports-highlights-generator, the swimming scrapers (Swimrankings/SwimScraper/swimset/swimulator), stfnwp & Michi83 fixture tools, the reels tools (GabrielLaxy/steinathan/gyoridavid/IgorShadurin/vvinniev34), clawnify/open-design, WhisperX, pybaseball, TheSportsDB (free-tier limits), JimmyRowland/team_sporty.

**AVOID / DO NOT REUSE AS OSS:**
- **jgolliher/hyparse** and **EdwinWalela/fixture-generator** — NO LICENSE (all rights reserved).
- **remotion-dev/remotion** for the for-profit production engine — replace it unless you will pay the Company License; it is the single biggest hidden-cost item.
- **n8n** as the embedded engine of a product you sell — Sustainable Use License forbids it (internal use is fine).
- **Mixpost Pro** to build a SaaS — explicitly prohibited by its license (use Enterprise or build your own).
- **lidojs/canva-clone** — export feature paywalled; "use at your own risk" custom license.
- **iut62elec/Soccer-Highlight-Generator** + **Open-Pomelli / AI-Youtube-Shorts api mode** as defaults — paid AWS Bedrock / MuAPI; switch to local substitutes.
- **ANAS727189/MediaHub** — explicitly excluded (misidentification; unrelated React/Node video-vault project).

### D.3 Highest-value features to steal
1. **Human-in-the-loop "Agent Inbox" + per-type approval** (langchain social-media-agent + Temporal signals) → the autonomy toggle.
2. **Brand-DNA-from-URL extraction** (Open-Pomelli) re-implemented with local scrape + Ollama + material-color-utilities.
3. **Virality scoring with score+hook+reason per clip** (AI-Youtube-Shorts-Generator).
4. **PSD-template binding for auto-graphics** (ag-psd / nba-gameday-generator).
5. **Satori-based card rendering** to drop headless-Chromium weight (~100× lighter).
6. **Postiz's multi-tenant org schema + publishing adapters** as the publishing reference.
7. **Trust-ledger verification pattern** extended into autonomous-publish guardrails.

### D.4 Proposed roadmap phases
- **Phase 0 — De-risk licensing/cost:** replace the Remotion plan (or budget the Company License), isolate AGPL services (Postiz/MinIO/MediaCMS) behind network boundaries, default every AI call to a local model. *Exit criterion:* zero mandatory paid API in the critical path.
- **Phase 1 — Strategy brain + taxonomy + sport profiles:** build the planner (crewAI/LangGraph + Ollama), the cross-sport post-type taxonomy, and the sport-profile config object. Ship swimming + one other sport profile (football or basketball).
- **Phase 2 — Autonomy toggles + orchestration:** put every content type on Temporal with an optional human-approval signal; implement guardrails + kill switch + audit trail; expose `autonomy_level` per type in the workspace UI.
- **Phase 3 — Broaden ingestion spokes:** add nba_api, openfootball, fixture generators, FIT/CSV parsers; normalise to the typed schema.
- **Phase 4 — Direct-to-platform publishing:** replace Buffer with Instagram Graph / Facebook / TikTok / YouTube / Bluesky / Mastodon adapters (Postiz adapters as reference), prioritising the genuinely-free targets (Bluesky/Mastodon) and budgeting for X's new pay-per-use pricing.
- **Phase 5 — Local-AI substitution everywhere:** Ollama (LLM), Piper (TTS), whisper.cpp (ASR), rembg/MODNet (cutout), Satori (graphics) — guaranteeing zero hidden cost.

### D.5 Negative findings / whitespace
- **No open-source end-to-end autonomous multi-sport social media manager exists.** The pieces exist; the integrated product does not. That is MediaHub's core differentiation.
- **Open-source "best-time-to-post" and "content-repurposing" tooling is weak** — mostly commercial SaaS or paid-API-dependent (OpenAI/Gemini). Build best-time from the team's own engagement history; build repurposing in-house on the local-AI stack.
- **Sport-specific result ingestion outside swimming/football/basketball is sparse** — running/athletics and minor sports will need custom parsers (the swim-data-analyser FIT pattern is a useful starting point).
- **The "brand/campaign generator" space is dominated by paid-API wrappers** — the free, fully-local version is unbuilt and worth owning.

## Caveats
- Star counts and "last updated" are point-in-time and fluctuate; several are flagged approximate (Postiz in particular is cited anywhere from ~20k to ~31k across directories).
- Some licenses marked "verify" were not confirmed from the LICENSE file in this pass and must be checked before adoption (notably crewAI, ag-psd, langchain social-media-agent, the scrapers, and the reels tools).
- StatsBomb, TheSportsDB, RMBG-1.4, and Coqui XTTS carry non-OSS or non-commercial terms distinct from their code repos — always separate **code license** from **data/model license**.
- AGPL implications depend on whether you distribute/network-serve modified code; consult counsel before forking Postiz/MediaCMS/MinIO into a product, and prefer the "separate service called over its API" pattern.
- Third-party API pricing moves fast (X API moved to pay-per-use on 6 Feb 2026; Coqui's commercial XTTS licensor no longer exists) — re-verify any paid dependency at implementation time.
