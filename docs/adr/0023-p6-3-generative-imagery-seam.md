# ADR 0023 — P6.3 generative-imagery seam (`media_ai.imagine`)

- **Status:** Accepted (Build 1 + Build 2 delivered)
- **Date:** 2026-06-18
- **Roadmap item:** P6.3 — Generative imagery & image-AI services (Phase 2, Creative suite)

## Context

P6.3 is MediaHub's first-party version of the Canva/Adobe-Express generative-image
surface: generate / edit / fill / expand / remove / subject-lift / upscale /
style-match / similar / mockups, plus text-to-video b-roll, grab-text, layer
extraction and 3D. The roadmap mandates:

- one **image-AI provider layer** mirroring the LLM wrapper's provider doctrine;
- an **in-house local diffusion model as the default backend** (the P5.6 path),
  with cloud generators optional on the same seam;
- **honest errors, never heuristic/fake substitutes** (CLAUDE.md);
- **provenance stamping** on every output (the C2PA-class "this is AI" signal);
- **per-org quotas** on the new billed surface (the P6.22 governance slice);
- the **no-synthetic-people** rule (people off by default).

The capability is large enough that building it in one pass would trade accuracy
for breadth. This ADR records the **two-build split** and the Build-1 design.

## Decision

### Two builds

- **Build 1 (this ADR): the seam, the solid services, governance, library wiring.**
  The provider-agnostic facade `media_ai/imagine.py`; providers
  (`media_ai/imagine_providers/`: `base`, `gemini_imagine`, `local_imagine`);
  the operations that are genuinely solid today (`generate`, `similar`,
  deterministic `subject_lift`); provenance stamping; the per-org quota ledger;
  media-library JSON routes + a minimal "Generate image" UI panel; and
  generalising the existing `MEDIAHUB_GEN_BG` Imagen call behind the seam.
- **Build 2 (delivered): the working surfaces that don't need P5.6.** Re-scoped
  to what genuinely works today (the generative *edit family* needs an
  edit-capable backend, which Gemini's public Imagen `:predict` is not — so a
  mask-brush UI in front of it would only honest-error). Build 2 ships:
  - **`grab_text`** (Grab Text) — vision-OCR via the existing vision LLM
    (transcribe-only, never fabricate/translate); metered; honest-errors with no
    vision provider. Route + per-asset action.
  - **Deterministic mockups** (`src/mediahub/mockups/`) — Smartmockups-class
    product previews (poster/framed-print/phone-post/flatlay) drawn from
    first-party PIL primitives. Key-free, byte-deterministic, brand-tinted, **not**
    behind the AI seam (it generates nothing) — so it is allowed to be
    deterministic under the engine rules. Feeds P6.19 print/merch previews.
  - **Generation history + provenance viewer** (`/media-library/generated`) —
    every `ai_generated` asset with its operation/model/prompt and the embedded
    C2PA-class AI tag.

  **Deferred (await a capable backend / later packages):** the generative edit
  family's working implementation + mask-brush/expand studio UI (P5.6 or a
  verified edit-capable provider), text-to-video b-roll (↗ P6.5), layer
  extraction, 3D (deferred-last), deep card-editor integration, and batch
  (↗ P6.15). The seam already exposes the edit family and honest-errors by
  capability, so filling P5.6 lights them up with no facade/route change.

### Provider doctrine (in-house first, honest fall-through)

`get_imagine_provider()` resolves: explicit `MEDIAHUB_IMAGINE_PROVIDER`
(`local`|`gemini`) → else **local default when available** → else **Gemini when a
key is present** → else `None`. An explicit choice is honoured even when not yet
available, so an operator who asks for `local` gets an honest
`ProviderNotConfigured` ("local backend not built yet — P5.6") rather than a
silent switch to a billed cloud call.

The **local slot is the intended default** but P5.6 has not landed, so
`LocalImagineProvider.is_available()` is `False` and it honest-errors — exactly
the Piper-TTS-slot pattern. The **Gemini/Imagen provider** is the working cloud
backend; it honestly claims only `{generate, similar}` (the public Imagen
`:predict` surface), and the facade `ImagineUnsupported`-errors the edit family
until the local backend fills it. We do **not** over-claim a capability and
return a stub image.

### Operations

- Provider-backed (quota-metered): `generate`, `similar`, `edit`, `expand`,
  `remove`, `upscale`, `style_match`. Build 1 ships `generate`/`similar` (Gemini);
  the rest are defined in the seam and honest-error by capability.
- Deterministic (unmetered, key-free): `subject_lift` = cutout
  (`media_ai.providers`) + saliency framing (`graphic_renderer.saliency`) —
  reusing shipped code, exposed as "lift subject".

### Provenance

The lossless metadata embedder (`graphic_renderer/metadata_embed.py`) gains the
IPTC **DigitalSourceType** controlled-vocabulary term: a wholesale
generate/similar is `trainedAlgorithmicMedia`; an edit of a real photo is
`compositeWithTrainedAlgorithmicMedia` (carrying the source's credit chain
forward). Every output also gets a `<file>.imagine.json` sidecar manifest
(operation, provider, model, **redacted** prompt, source asset, org, content
hash) mirroring the motion-render manifests.

### Quotas

`observability/imagine_usage.py` (a sibling of `llm_usage.py`) records one
org-tagged row per provider-backed op. `imagine.check_quota(org_id)` enforces a
rolling-30-day cap (`MEDIAHUB_IMAGINE_QUOTA_MONTHLY`, default 100, `-1` =
unlimited); the route returns `429` on exceed. The check fails *open* on a DB
read error (a transient hiccup never wrongly blocks a paying club).
Deterministic `subject_lift` is not metered.

### `MEDIAHUB_GEN_BG` generalisation

`visual/ai_background.py` now delegates its Imagen HTTP call to the shared
`imagen_predict` client (the one place the Imagen request shape lives). The
public API (`is_available`, `background_data_uri_for`), the cache key, and the
request payload are unchanged, so rendered backgrounds stay byte-identical
(regression-tested in `tests/test_p6_3_ai_background_parity.py`).

## Consequences

- New generative-image surfaces have one honest, swappable, provenance-and-quota-
  governed home. With no key configured, the surface honest-errors and only
  deterministic `subject_lift` is offered.
- P5.6 lights up the full edit family by filling the `local` slot — no facade or
  route changes needed.
- This is an **AI surface** (`media_ai`), not the deterministic engine (parsers /
  detectors / ranker / colour-science are untouched), so no Council gate applied;
  the architecture is a decided roadmap direction.

## Non-goals (still open after Build 2)

The edit family's working implementation + mask-brush/expand studio UI (needs
P5.6 or a verified edit-capable provider), text-to-video b-roll (↗ P6.5), layer
extraction, 3D (deferred-last), deep card-editor integration, and batch
(↗ P6.15). The deterministic engine is not AI-replaced.
