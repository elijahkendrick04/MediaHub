# MediaHub

> A content-strategy brain for sports teams — it works out what a team should post, drafts it, brands it, and readies it for posting (a human approves and posts every piece; MediaHub never publishes to a social account). Swimming results → content is the shipped wedge; multi-sport and autonomy-first are the direction (see the [roadmap](docs/ROADMAP.md)).

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-13k%20passing-brightgreen.svg)](tests/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

> **New here and not a coder?** Start with **[START_HERE.md](START_HERE.md)** — a
> plain-English tour of the project. Confused by a word? See
> **[GLOSSARY.md](GLOSSARY.md)**.
>
> **In plain words:** MediaHub helps a sports team work out what to post on social
> media, writes it, and makes the pictures — then a human checks it before it goes
> out. Today it does this from swim-meet results (spotting personal bests and
> medals); more sports and more "decide-and-post-for-me" automation are on the way
> (see the [roadmap](docs/ROADMAP.md)).

**The direction.** MediaHub is becoming a multi-sport, multi-tenant content-strategy brain: it fuses a team's own signals (past posts, brand voice), external signals (fixtures, results, news), and direct input (goals, blackout dates) into a ranked content plan. Every piece is gated by a **per-content-type autonomy toggle**, and the stack carries **no mandatory paid dependencies**. The plan is in [`docs/ROADMAP.md`](docs/ROADMAP.md) (phases in priority order — build-first: rebrand → second sport → go-to-market are deliberately last; everything already shipped is recorded in [`docs/ROADMAP_BUILT.md`](docs/ROADMAP_BUILT.md)); the strategy docs are linked below. Results ingestion is one spoke among many — not the product's identity.

**What ships today (the swimming wedge).** MediaHub ingests raw competition data — Hy-Tek HY3 ZIPs, SDIF/CL2 files, exported PDFs, scraped HTML result pages — and produces a curated stream of posts ready for Instagram / Facebook / TikTok: athlete spotlights, weekend recaps, meet previews, and a one-click "turn this meet into eight assets" pack. Behind the posts sits the club-intelligence layer that keeps them accurate and on-brand. That layer includes cross-meet athlete identity, a club-records book, qualifying-time standards ("made Counties!"), month/season recaps, a club Q&A that answers questions over the club's own results, per-athlete photo/name consent (safeguarding), a UK/EU data-protection rights engine, and multi-tenant workspaces so clubs don't see each other's data. It is a cloud-hosted SaaS that customers access via a web browser; the engine runs on the operator's managed deployment, with AI captioning and image processing handled through cloud APIs. Human approval is required before anything is published.

---

## Getting started

MediaHub is delivered as a hosted web application. Customers sign in to the deployed URL provided by their operator and use it through any modern browser — no install, no local setup.

1. Open the deployment URL in a browser.
2. Click **Upload**, drop in a results file (PDF, HY3, SDIF, ZIP, or HTML) — or **paste a results-page link** and MediaHub reads the whole competition off the site (see [`docs/RESULTS_FROM_URL.md`](docs/RESULTS_FROM_URL.md)).
3. The cloud pipeline interprets, recognises, ranks, renders, and captions in the background.
4. Review the generated cards on the run's review page, edit captions, approve, and download the content pack.

The hosted service performs all AI calls (captioning, brand interpretation, creative direction) through cloud LLM providers (Gemini / Anthropic). Image background removal runs on the deployed server or through cloud cutout APIs (Photoroom / Replicate) depending on operator configuration.

> Working on the codebase? See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for contributor setup.

## What it does

1. **Upload** any results file — HY3, SDIF, PDF, HTML, ZIP — or **paste a results-page link** ([how it works](docs/RESULTS_FROM_URL.md)).
2. **Interpret** — the [interpreter](docs/SYSTEM_FLOW.md#interpreter) auto-detects the format and induces a typed schema.
3. **Recognise** — the [detector bus](docs/DETECTOR_BUS.md) flags PBs, qualifying times, medal finals, and other achievements.
4. **Verify** — the [PB engine](docs/PB_VERIFICATION.md) cross-checks against swimmingresults.org with a trust ledger.
5. **Render** — [graphic_renderer](docs/UPLOAD_TO_CARDS.md) generates Instagram-ready PNGs from HTML/CSS templates.
6. **Caption** — the configured cloud LLM (Gemini or Claude) writes a club-voice caption for each card.
7. **Pack** — every card lands on the `/review/<run_id>` page; download a ZIP of the whole weekend's content.

## Architecture overview

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram. Short version:

```
Upload  →  Interpreter  →  Pipeline  →  Recognition  →  Content Pack
                                                ↘
                                          Visual Renderer  →  Caption  →  Pack ZIP
```

## Documentation

| Doc | Purpose |
| --- | --- |
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | High-level module diagram + responsibility table |
| [`SYSTEM_FLOW.md`](docs/SYSTEM_FLOW.md) | Step-by-step trace of an upload |
| [`DETECTOR_BUS.md`](docs/DETECTOR_BUS.md) | How achievements register and rank |
| [`RANKING.md`](docs/RANKING.md) | Ranker formula + tunable knobs |
| [`PB_VERIFICATION.md`](docs/PB_VERIFICATION.md) | PB discovery + trust ledger |
| [`UPLOAD_TO_CARDS.md`](docs/UPLOAD_TO_CARDS.md) | End-to-end request walkthrough |
| [`EXTENSION_GUIDE.md`](docs/EXTENSION_GUIDE.md) | Add a new sport / layout / voice / cutout provider |
| [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Render, Fly, Docker, VPS |
| [`ROADMAP.md`](docs/ROADMAP.md) | The forward plan — phases in priority order (build-first; rebrand → second sport → go-to-market last) |
| [`ROADMAP_BUILT.md`](docs/ROADMAP_BUILT.md) | The record of everything already shipped (split out of the roadmap) |
| [`ARCHITECTURE_TARGET.md`](docs/ARCHITECTURE_TARGET.md) | Hub-and-spoke target architecture (mapped onto today's modules) |
| [`POST_TYPE_TAXONOMY.md`](docs/POST_TYPE_TAXONOMY.md) | Universal vs sport-specific post types (swimming, football, basketball, running) |
| [`SPORT_PROFILES.md`](docs/SPORT_PROFILES.md) | The sport-profile concept + how to add a new sport |
| [`DEPENDENCY_LICENSING.md`](docs/DEPENDENCY_LICENSING.md) | No-hidden-fees register + free substitutes |
| [`KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) | Current rough edges |
| [`TECHNICAL_DEBT.md`](docs/TECHNICAL_DEBT.md) | Legacy modules + cleanup priorities |
| [`compliance/`](docs/compliance/README.md) | UK/EU data-protection programme: legal framework, data map, ROPA, gap analysis, consent/DSR/retention capabilities, Children's Code, DPIA, breach playbook — legal docs are DRAFT, for solicitor review |
| [`security/`](docs/security/README.md) | Threat model (STRIDE + LLM Top 10), TLS/at-rest/backup posture, ASVS L2 report with scan results and the honest residual-risk register |
| [`CHANGELOG.md`](docs/CHANGELOG.md) | V1 → V8.2 release notes |

Inventories under `docs/`: `INVENTORY.md`, `ROUTE_INVENTORY.md`, `API_INVENTORY.md`, `ENV_INVENTORY.md`, `DETECTOR_INVENTORY.md`, `PROMPT_INVENTORY.md`, `SYSTEM_MAP.md`, `DEPENDENCY_MAP.md`, `FEATURE_INVENTORY.md`.

## Repository layout

`src/mediahub/` is the live, supported package — ~48 sub-packages, grouped here by responsibility (the `…` notes mean "see that folder's own `README.md`"):

**Ingest & understand** — the deterministic engine (not AI-replaced)
```
interpreter/        format-agnostic ingestion + induced ontology
recognition*/       detector bus + swim achievement detectors
pb_discovery/       web-verified PB engine + trust ledger
context_engine/     who/what a meet is about (club, event, back-story)
```

**Decide, brief & rank** — the intelligence layer
```
content_engine/     the strategy brain + the single caption writer
creative_brief/     per-card look & wording direction
club_platform/      catalogue of content types (recap, spotlight, preview…)
turn_into/          one meet → eight ready-to-post assets
free_text_chat/     conversational brief builder
inspiration/        content-idea + good-example library
media_requirements/ pre-flight: does this content type have the media it needs?
```

**Render & brand**
```
graphic_renderer/   HTML/CSS → PNG via Playwright
remotion/ + visual/ Remotion MP4 story cards & meet reels (Node, driven from Python)
theming/ typography/ brand/   colour science, club typefaces, brand kits
media_library/      media asset store + deterministic photo selector
content_pack*/      the assembled, downloadable content pack
voice/              learned caption styles
venue_search/       public venue / pool backdrop photos
```

**Club intelligence** — shipped swim features
```
athletes/           cross-meet athlete identity + milestones
club_records/       the club records book
standards/          qualifying-time tables ("made Counties!")
season_wrap/        month / season recap numbers
club_qa/            ask questions over the club's own results
```

**Trust, safety & compliance**
```
safeguarding/       per-athlete photo / name consent
compliance/ privacy/  UK/EU data-protection rights engine (erasure, DSR, retention)
quality/            exact, no-AI checks on generated content
```

**Platform & operations**
```
web/                Flask UI + helpers (tenancy.py = multi-tenant workspaces; auth)
pipeline/           run orchestration
ai_core/ media_ai/  provider-agnostic LLM clients (Gemini → Anthropic failover)
memory/             semantic caption recall (embeddings)
results_fetch/      "results from a link" crawler + live-meet watch
web_research/       search + bounded deep-research loop
scheduler/          in-process, exactly-once job runner
autonomy/           bounded narrow-tool runner — queues for review, never publishes
notify/             push / webhook notifications
observability/      LLM-usage + uptime tracking
log_sentinel/       production-log night guard + safe auto-fixes
backup/             disk-failure resilience
commercial/         the founder's selling notebook (leads, quotes)
sport_profiles/     sport config + per-post-type autonomy levels
```

**Outside `src/`**
```
legacy/   read-only historical packages (V1–V5 + early V6) — newer code still borrows from here
data/     ontology, voices, brand kits, sport profiles, standards, discovered-PB cache
tests/    pytest suite — ~13,100 tests (the large majority pass; the rest skip without Playwright/Chromium, Node/Remotion, or optional corpora)
docs/     long-form documentation (see the table above)
samples/ + sample_data/   tiny representative meet corpus
scripts/  build + maintenance scripts
autotest/ the in-cloud self-tester + the LLM Council skill
vendor/   downloaded reference skill-kits — NOT part of MediaHub
```

## Tests

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the contributor test workflow.

## Licence

Proprietary; see [LICENSE](LICENSE).
