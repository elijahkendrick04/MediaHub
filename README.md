# MediaHub

> A content-strategy brain for sports teams — it works out what a team should post, drafts it, brands it, and (where allowed) publishes it. Swimming results → content is the shipped wedge; multi-sport and autonomy-first are the direction (see the [roadmap](docs/ROADMAP.md)).

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-3815%20passing-brightgreen.svg)](tests/)
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

**The direction.** MediaHub is becoming a multi-sport, multi-tenant content-strategy brain: it fuses a team's own signals (past posts, brand voice), external signals (fixtures, results, news), and direct input (goals, blackout dates) into a ranked content plan, gated by a **per-content-type autonomy toggle**, on a stack with **no mandatory paid dependencies**. The plan is in [`docs/ROADMAP.md`](docs/ROADMAP.md) (phases in priority order — build-first: rebrand → second sport → go-to-market are deliberately last; everything already shipped is recorded in [`docs/ROADMAP_BUILT.md`](docs/ROADMAP_BUILT.md)); the strategy docs are linked below. Results ingestion is one spoke among many — not the product's identity.

**What ships today (the swimming wedge).** MediaHub ingests raw competition data — Hy-Tek HY3 ZIPs, SDIF/CL2 files, exported PDFs, scraped HTML result pages — and produces a curated stream of athlete-spotlight, weekend-recap, and meet-preview posts ready for Instagram / Facebook / TikTok. It is a cloud-hosted SaaS that customers access via a web browser; the engine runs on the operator's managed deployment, with AI captioning and image processing handled through cloud APIs. Human approval is required before anything is published.

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

```
src/mediahub/        live, supported package
  web/               Flask UI + helpers (formerly swim_content_v4)
  pipeline/          orchestration (formerly bridge files)
  interpreter/       format-agnostic ingestion + ontology
  recognition*/      detector bus + sport adapters
  pb_discovery/      web-verified PB engine
  graphic_renderer/  HTML/CSS → PNG via Playwright
  voice/             learned caption styles
  sport_profiles/    sport config + autonomy levels (roadmap scaffolding, inert)
  …
legacy/              read-only historical packages (V1–V5 + early V6)
data/                ontology, voices, brand kits, sport profiles, discovered cache
tests/               pytest suite (2837 collected)
docs/                long-form documentation
samples/             tiny representative meet corpus
scripts/             build + maintenance scripts
```

## Tests

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the contributor test workflow.

## Licence

Proprietary; see [LICENSE](LICENSE).
