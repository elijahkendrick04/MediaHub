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

---

_When a future change vendors third-party source (as opposed to a registry
dependency), add its upstream name, version, license, and copyright notice
under a new section here._
