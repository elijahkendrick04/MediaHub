# MediaHub

> Sport content automation. Upload meet results → get social-ready captions, content cards, and rendered graphics.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-287%20passing-brightgreen.svg)](docs/AUDIT_REPORTS.md)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

> **New here and not a coder?** Start with **[START_HERE.md](START_HERE.md)** — a
> plain-English tour of the project. Confused by a word? See
> **[GLOSSARY.md](GLOSSARY.md)**.
>
> **In plain words:** MediaHub takes a file of swim results and turns it into
> ready-to-post pictures and captions for a club's social media — it spots the
> special moments (like personal bests) and writes them up for you.

MediaHub ingests raw competition data — Hy-Tek HY3 ZIPs, SDIF/CL2 files, exported PDFs, scraped HTML result pages — and produces a curated stream of athlete-spotlight, weekend-recap, and meet-preview posts ready for Instagram / Facebook / TikTok. It is a cloud-hosted SaaS that customers access via a web browser; the engine runs on the operator's managed deployment, with AI captioning and image processing handled through cloud APIs.

---

## Getting started

MediaHub is delivered as a hosted web application. Customers sign in to the deployed URL provided by their operator and use it through any modern browser — no install, no local setup.

1. Open the deployment URL in a browser.
2. Click **Upload**, drop in a results file (PDF, HY3, SDIF, ZIP, or HTML).
3. The cloud pipeline interprets, recognises, ranks, renders, and captions in the background.
4. Review the generated cards on the run's review page, edit captions, approve, and download the content pack.

The hosted service performs all AI calls (captioning, brand interpretation, creative direction) through cloud LLM providers (Gemini / Anthropic). Image background removal runs on the deployed server or through cloud cutout APIs (Photoroom / Replicate) depending on operator configuration.

> Working on the codebase? See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for contributor setup.

## What it does

1. **Upload** any results file — HY3, SDIF, PDF, HTML, ZIP.
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
| [`ROADMAP.md`](docs/ROADMAP.md) | Planned versions |
| [`KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) | Current rough edges |
| [`TECHNICAL_DEBT.md`](docs/TECHNICAL_DEBT.md) | Legacy modules + cleanup priorities |
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
  …
legacy/              read-only historical packages (V1–V5 + early V6)
data/                ontology, voices, brand kits, discovered cache
tests/               pytest suite (287 collected)
docs/                long-form documentation
samples/             tiny representative meet corpus
scripts/             build + maintenance scripts
```

## Tests

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the contributor test workflow.

## Licence

Proprietary; see [LICENSE](LICENSE).
