# Third-party licenses

MediaHub is delivered as a hosted web application. This file records the
license notices for any third-party source code **vendored into this
repository** (i.e. copied in, as opposed to installed from PyPI/npm at build
time). Dependencies pulled from package registries carry their own licenses via
their distributions and are not duplicated here.

## Provider-agnostic LLM layer (`ai_core/llm_client.py`, `media_ai/model_select.py`, `media_ai/llm_providers.py`)

The OpenAI-compatible LLM transport speaks the OpenAI `/v1/chat/completions`
wire format so MediaHub can target any compatible endpoint (Groq, OpenRouter,
Together, Fireworks, a self-hosted vLLM / Ollama / llama.cpp server, …). It
**vendors no third-party source code** — it is original MediaHub code built on
the existing `requests` dependency (Apache-2.0), which is installed from PyPI
via `requests` already declared in `requirements.txt`.

No additional third-party notices are required for this layer.

## Semantic memory — sqlite-vec (Capability 2)

The semantic caption memory (`mediahub.memory.store`) stores embedding vectors
in a `vec0` virtual table inside MediaHub's existing SQLite database, via the
**sqlite-vec** loadable extension. It is a **registry dependency** (installed
from PyPI, pinned in `requirements.txt`), not vendored source — its upstream
notice is retained here:

- **sqlite-vec** — © Alex Garcia, with support from Mozilla Builders — dual
  **MIT / Apache-2.0** (https://github.com/asg017/sqlite-vec). Loaded as an
  optional native extension; if it cannot load, semantic recall degrades to
  unavailable rather than failing a run. (Embeddings themselves are computed via
  a cloud OpenAI-compatible endpoint, so no `fastembed`/ChromaDB code is vendored
  or required.)

## In-container SearXNG metasearch (optional, Capability 3)

When `MEDIAHUB_RUN_SEARXNG=1`, the deployment installs and runs **SearXNG**
(https://github.com/searxng/searxng), a metasearch engine, as a **stock,
unmodified** process inside the container, queried only over localhost HTTP.
MediaHub does not modify, fork, or link against SearXNG — it only sends it
search queries.

- **SearXNG** — © SearXNG contributors — **AGPL-3.0-or-later**. Run unmodified
  at the pinned `SEARXNG_REF`; per AGPL-3.0 the corresponding source is the
  upstream repository (https://github.com/searxng/searxng) at that ref. Its
  transitive dependencies carry their own licenses via their distributions.

## Scheduler — croniter (Capability: scheduling)

The in-process scheduler (`mediahub.scheduler`, `mediahub.workflow.schedule`)
uses **croniter** to compute cron / daily / weekly / monthly fire-times. It is a
**registry dependency** (installed from PyPI via `requirements.txt`), not
vendored source — its upstream notice is retained here for completeness:

- **croniter** — © the croniter authors, maintained under **Pallets-Eco** —
  **MIT License** (https://github.com/pallets-eco/croniter). Transitive
  dependencies (`python-dateutil`, `pytz`) carry their own licenses via their
  distributions.

## Notifications — ntfy (`mediahub.notify`)

The notifier sends "pack ready for review" pings via **ntfy**
(https://ntfy.sh) and/or a generic webhook. MediaHub **vendors no ntfy source**
— it only POSTs messages to the ntfy HTTP API (the public server or a
self-hosted one), so the network-copyleft does not reach MediaHub. The HTTP
client is original MediaHub code on the existing `requests` dependency.

- **ntfy** — © Philipp C. Heckel and ntfy contributors — dual
  **Apache-2.0 / GPL-2.0** (https://github.com/binwiederhier/ntfy). Used
  unmodified over its HTTP API; no ntfy code is bundled or linked.

## Bounded autonomy runner (`mediahub.autonomy`)

The autonomy runner is original MediaHub code built on MediaHub's **own**
bounded tool-loop (`ai_core.ask_with_tools`, Capability 1) and a fixed,
narrow tool registry. It **vendors no third-party agent / loop source** — no
external agent framework is copied or linked — so no upstream notice is
required for it.

## Bundled fonts (self-hosted `.woff2`)

All bundled typefaces were obtained from Google Fonts and are licensed under
the **SIL Open Font License 1.1** (OFL), which permits bundling and
commercial use. Self-hosted first-party on every surface (Council decision
2026-05-31; see `src/mediahub/web/static/fonts/README.md`).

| Family | Copyright | Surfaces |
|---|---|---|
| Big Shoulders Display | © The Big Shoulders Project Authors | web UI |
| Fraunces | © The Fraunces Project Authors | web UI |
| Hanken Grotesk | © The Hanken Grotesk Project Authors | web UI |
| JetBrains Mono | © 2020 JetBrains (OFL) | web UI, renderer, reels |
| Anton | © The Anton Project Authors | renderer, reels |
| Bebas Neue | © The Bebas Neue Project Authors | renderer, reels |
| Bowlby One | © The Bowlby One Project Authors | renderer, reels |
| Inter | © The Inter Project Authors | renderer, reels |
| Space Grotesk | © The Space Grotesk Project Authors | renderer, reels |

OFL text: https://openfontlicense.org. Refresh via `scripts/fetch_fonts.py`
(web) and `scripts/fetch_renderer_fonts.py` (renderer + reels).

## `vendor/` reference material — licence status

The `vendor/` directory holds **reference material** (skills, examples) that
is not imported by the MediaHub runtime. Attribution status, audited
2026-06-12 (docs/COMPLIANCE_AUDIT.md finding 7.2):

| Directory | Licence found | Status |
|---|---|---|
| `skills-main/` | Apache-2.0 | OK — notices intact |
| `claude-marketplace-main/` | MIT | OK |
| `matt-pocock-skills/` | MIT | OK |
| `taste-skill-main/` | MIT | OK |
| `ui-ux-pro-max-skill-main/` | MIT | OK |

**Resolved 2026-06-12 (PC.11):** `agent-skills-main/` and
`bencium-marketplace-main/` carried no upstream licence file, so MediaHub had
no verifiable right to redistribute them. Both directories were **removed**
from the repository (nothing in `src/`, `tests/`, `scripts/` or `.claude/`
referenced them). `tests/test_vendor_licences.py` now fails the build if a
vendored directory ever lands without a licence or third-party notice file.

## Scraper conduct (results fetching & PB verification)

MediaHub's fetchers identify themselves and behave politely by design:

- Identified User-Agents — `SwimPBDiscovery/7.5` (`pb_discovery/fetch_profile.py`)
  and `MediaHubResults/1.0` (`results_fetch/fetch.py`); never browser-spoofed.
- `robots.txt` fetched and respected by default (`results_fetch/crawl.py`).
- 0.3 s politeness delay between requests; hard budgets per crawl
  (400 pages / 50 MiB / 180 s / depth 3).
- Caching to avoid re-fetching: per-run PB cache plus a 7-day warm cache per
  swimmer; 30-day search cache.
- PB verification reads **already-public** results pages only, and the
  try-it demo surface never triggers third-party lookups.

---

_When a future change vendors third-party source (as opposed to a registry
dependency), add its upstream name, version, license, and copyright notice
under a new section here._
