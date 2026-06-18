# ADR 0024 — Local diffusion image backend (roadmap 1.1)

- **Status:** Accepted (implemented)
- **Date:** 2026-06-18
- **Roadmap item:** 1.1 — Local generative-image backend behind the `media_ai`
  seam (formerly "P5.6"; see the ID map in [`../ROADMAP.md`](../ROADMAP.md))
- **Supersedes the open thread in:** [`0023-p6-3-generative-imagery-seam.md`](0023-p6-3-generative-imagery-seam.md)
  ("P5.6 lights up the full edit family by filling the `local` slot")

## Context

ADR-0023 shipped the `media_ai.imagine` seam: a provider-agnostic facade, the
Gemini/Imagen cloud provider (`generate`/`similar` only), per-org quotas,
provenance stamping, the media-library routes and the **registered-but-empty
`local` slot**. The generative *edit family* (`edit`/`fill`/`expand`/`remove`/
`upscale`/`style_match`) was defined in the seam and **honest-errored by
capability**, because the public Imagen `:predict` surface is not edit-capable.

Roadmap 1.1 fills that slot so generate / edit / fill / expand / remove run with
**no cloud key** — the in-house-first default (rule 11). The seam was designed so
this needs **no facade or route change**: only the provider.

## Decision

### Architecture — a self-hosted inference *sidecar*, reached over HTTP

A diffusion model (e.g. **FLUX.1-schnell, Apache-2.0**) is heavy and GPU-bound,
so — exactly like the Remotion video renderer and the Playwright/Chromium
graphics renderer — it runs as **the operator's own process** and MediaHub talks
to it over HTTP. The operator stands up an inference server on their own
infrastructure and points MediaHub at it with `MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`
(the env var ADR-0023 had already reserved for this).

Why a sidecar over an in-process `diffusers`/`torch` load:

- **Licence-clean and dependency-clean.** MediaHub ships **no model weights** and
  adds **no new Python dependency** — only an HTTP client built on the `requests`
  already in the tree. The Apache-2.0 weights are the operator's to run; we never
  vendor OpenRAIL/non-commercial weights (`DEPENDENCY_LICENSING.md`).
- **In-house / zero-cloud-key / zero-per-image-cost.** Nothing leaves the
  operator's network and no third party is billed — the no-hidden-fees discipline
  for the hosted deployment's margins.
- **Consistent with the codebase.** It mirrors the local-LLM path (roadmap 1.26 —
  a keyless self-hosted endpoint) and the "server-side rendering runs as a
  separate process" pattern already used for video and graphics.
- **Testable.** The one network hop is `requests.post`, so the whole backend is
  unit-testable by mocking HTTP — no GPU in CI.

### The HTTP contract (MediaHub-native JSON, tolerant on the way back)

One `POST {endpoint}/<op>` per operation, JSON body. Edit-family ops carry the
source `image` (base64) and, where relevant, a `mask` (base64 PNG whose painted
region marks where to act). The response may be **raw image bytes**
(`Content-Type: image/*`) **or** JSON carrying base64 under `images` / `data`
(OpenAI-images-compatible) / `image`; base64 may be a bare string or a `data:`
URI. This tolerance lets a range of self-hosted servers slot in behind a thin
adapter without a bespoke MediaHub fork.

### Capabilities are declared, not assumed

`capabilities()` returns the empty set with no endpoint (so the facade never
routes to an empty slot) and, once configured, a **declared** set — default
`generate,similar,edit,expand,remove,style_match` (the realistic FLUX inpaint
vocabulary). `upscale` is **opt-in** (it needs a dedicated upscaler model), and
the operator can narrow or widen the set with `MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES`
(comma list or `all`). This keeps the honest-error rule: we advertise only what
the configured server actually does.

### Honest errors, never a fake

No endpoint → the slot is unavailable and the facade honest-errors
(`ProviderNotConfigured`) — and an operator who *pins* `local` is **never**
silently switched to a billed cloud call. A configured-but-failing endpoint
(unreachable, non-2xx, empty result) → `ImagineError` with a **redacted** reason
(the optional bearer token is masked in errors and the facade's key-redactor).
Never a stubbed or substituted image.

### Parity touch-ups (clean, in the same seam)

- The curated sport-editorial **style presets moved to `imagine_providers/styles.py`**
  so both backends read the same vocabulary (re-exported from `gemini_imagine`
  for back-compat — the web layer imports `STYLE_PRESETS` from there).
- Providers gained a `default_model()` method (recorded in provenance), removing
  the Gemini special-case in the facade's `_model_of`.

## Consequences

- With a local endpoint configured and **no cloud key**, the full surface —
  generate / similar / edit / fill / expand / remove / style-match — runs through
  the in-house backend, metered per org and provenance-stamped exactly as the
  cloud path is. The mask-brush *studio UI* and the rest of the edit-family UX
  remain roadmap **1.2** (this ADR is the backend it builds on).
- No facade, route, quota, or provenance change was needed — ADR-0023's design
  held.
- This is an **AI surface** (`media_ai`), not the deterministic engine, and a
  decided roadmap direction, so no Council gate (consistent with ADR-0023).

## Non-goals (unchanged)

The 1.2 mask-brush/expand studio UI and deep card-editor integration,
text-to-video b-roll (↗ 1.6), layer extraction, 3D (deferred-last), and batch
(↗ 1.13). The deterministic engine is not AI-replaced.
