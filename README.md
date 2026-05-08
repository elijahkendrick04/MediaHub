# MediaHub

> Sport content automation. Upload meet results → get social-ready captions, content cards, and rendered graphics.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-287%20passing-brightgreen.svg)](docs/AUDIT_REPORTS.md)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

MediaHub ingests raw competition data — Hy-Tek HY3 ZIPs, SDIF/CL2 files, exported PDFs, scraped HTML result pages — and produces a curated stream of athlete-spotlight, weekend-recap, and meet-preview posts ready for Instagram / Facebook / TikTok. It runs as a single Flask service that you can self-host on Render, Fly, Docker, or a plain VPS.

---

## Quick start (local)

```bash
git clone <this-repo>
cd mediahub-export
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # add your API keys (all optional)
make run               # starts http://localhost:5000
```

Open `http://localhost:5000`, click **Upload**, drop in a results PDF, and watch the pipeline run.

## Quick start (Docker)

```bash
docker compose up --build
```

## What it does

1. **Upload** any results file — HY3, SDIF, PDF, HTML, ZIP.
2. **Interpret** — the [interpreter](docs/SYSTEM_FLOW.md#interpreter) auto-detects the format and induces a typed schema.
3. **Recognise** — the [detector bus](docs/DETECTOR_BUS.md) flags PBs, qualifying times, medal finals, and other achievements.
4. **Verify** — the [PB engine](docs/PB_VERIFICATION.md) cross-checks against swimmingresults.org with a trust ledger.
5. **Render** — [graphic_renderer](docs/UPLOAD_TO_CARDS.md) generates Instagram-ready PNGs from HTML/CSS templates.
6. **Caption** — Claude (or a deterministic fallback) writes a club-voice caption for each card.
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

```bash
make test            # full suite, 287 tests
make test-collect    # collection only
```

## Licence

Proprietary; see [LICENSE](LICENSE).
