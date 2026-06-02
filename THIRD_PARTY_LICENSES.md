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

---

_When a future change vendors third-party source (as opposed to a registry
dependency), add its upstream name, version, license, and copyright notice
under a new section here._
