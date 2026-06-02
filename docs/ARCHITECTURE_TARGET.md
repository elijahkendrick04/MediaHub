# Target Architecture (hub-and-spoke)

> **In plain words.** Today MediaHub is shaped like a pipeline: a results file
> goes in one end and posts come out the other. The new shape is a **hub with
> spokes**. In the middle sits a "strategy brain" that decides what a team should
> post. Around it are *spokes*: things that bring information in (results, fixtures,
> news), things that make the posts look good (graphics, reels, voice), and things
> that send them out (Instagram, etc.). The brain is the valuable part; results
> ingestion becomes just one spoke. Crucially, **most of this already exists** —
> this page maps the new picture onto the folders we already have, so we extend
> rather than rebuild. New here? Read [`ARCHITECTURE.md`](ARCHITECTURE.md) (today's
> shape) first.

Evidence base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md)
Part B. Related: [`SPORT_PROFILES.md`](SPORT_PROFILES.md),
[`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md), [`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md),
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md), [`ROADMAP.md`](ROADMAP.md).

---

## 1. The target picture

```
            THREE SOURCES OF SIGNAL                       SPOKES
   ┌──────────────────────────────────┐
   │ own signals (past posts,          │   ┌─▶ ingestion spokes ──┐
   │   engagement, brand DNA)          │   │   results · fixtures  │
   │ external signals (fixtures,       │   │   news · peer clubs   │
   │   results, news, peers, trends)   │   │                       ▼
   │ direct input (onboarding, goals,  │   │              ┌──────────────────┐
   │   blackout dates)                 │───┼─────────────▶│  STRATEGY BRAIN  │
   └──────────────────────────────────┘   │              │  (the hub):      │
                                           │              │  fuse → rank →   │
   ┌──────────────────────────────────┐   │              │  plan → draft    │
   │  ORCHESTRATION BACKBONE           │◀──┘              └────────┬─────────┘
   │  one workflow per content type,   │                          │
   │  optional human-approval signal   │   ┌──────────────────────┼───────────────┐
   │  (= the autonomy toggle)          │   ▼                      ▼               ▼
   └──────────────────────────────────┘  asset-generation   publishing layer   multi-tenant
                                          engines (graphics,  (direct APIs /     workspace
                                          reels, voice,       Buffer today)      isolation
                                          theming, cutout)
                              ▲
                   LOCAL-AI SUBSTITUTION LAYER (LLM, TTS, ASR, cutout, graphics)
                   guarantees zero per-call cost under everything above
```

The **deterministic engine stays inside the spokes**, untouched: parsers, PB
detectors, the ranker, and colour-science remain non-AI (CLAUDE.md). The brain
*orchestrates and drafts*; it never overrides "is this a PB?" or "which card
outranks which?".

## 2. Component → existing module map (verified)

Almost every target component already has a home. The job is to **generalise and
connect**, not to spawn a parallel structure.

| Target component | Maps onto (shipped today) | Gap to close |
|---|---|---|
| **Strategy brain (hub)** | `content_engine` (planner `plan_content_directions` + writer `generate_content`) + `context_engine` (identity, research, trust) + `workflow` (status/queue) | A cross-source planner that fuses the three sources into a ranked, multi-sport content *plan* (today's planner is swim-result-centric). |
| **Sport adapters (spokes)** | `recognition` (sport-agnostic bus + `registry.register_sport`) + `recognition_swim` (swim impl) | Add `recognition_<sport>` packages; the seam already exists ([`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)). |
| **Sport config** | `sport_profiles` (new, inert) + `club_platform.content_types` (post-type registry) | Wire profiles into planning; reconcile profile post types with the `ContentType` enum. |
| **Ingestion spokes** | `interpreter` (HY3/SDIF/PDF/HTML), `pb_discovery` | Add sports-data APIs (`nba_api`, `openfootball`), fixture generators, FIT/CSV parsers; normalise to the canonical schema (`canonical.*`). |
| **Asset: graphics** | `graphic_renderer` (Playwright→PNG), `creative_brief` | Optional Satori fast-path (Phase 5) to cut headless-Chromium weight. |
| **Asset: video/reels** | `remotion` + `visual/motion.py` | Cost-flag Remotion; Satori+FFmpeg fallback (Phase 0/5). |
| **Asset: voice** | `voice` (learned styles), `visual/voiceover.py` (`edge-tts`) | Swap `edge-tts` cloud endpoint for Piper (Phase 5). |
| **Asset: theming** | `theming` (Adaptive Theming Engine, **shipped**) + `brand` | Already single-source-of-truth across web/motion/email/graphic. |
| **Asset: cutout** | `media_ai.providers` (**rembg server default**, Replicate/PhotoRoom optional) | Already free-by-default; keep flag. |
| **Publishing layer** | `publishing.buffer` (+ `posting_log`) | Add direct platform adapters (Bluesky/Mastodon free first), drop the Buffer dependency (Phase 4). |
| **Orchestration backbone** | `workflow.store` (lightweight, per-run) | Promote to a durable per-content-type workflow engine with a human-approval signal (Temporal) (Phase 2). |
| **Multi-tenancy** | `web` org-gate + `_can_access_run` invariant (`tests/test_run_route_isolation_invariant.py`) | Generalise org → workspace; reference Postiz/Mixpost schemas (over a network boundary, never embedded — both AGPL/open-core). |
| **LLM / AI surfaces** | `media_ai.llm` + `ai_core.llm` (Gemini→Anthropic failover) | Add an Ollama local provider as the zero-cost default (Phase 5). |
| **Local-AI substitution** | — (new layer) | Ollama (LLM), Piper (TTS), whisper.cpp (ASR), rembg/MODNet (cutout — partly done), Satori (graphics). |

## 3. The minimal new modules

Resist new packages; most work extends existing ones. The genuinely *new* surfaces:

1. **`sport_profiles`** — ✅ already added (inert). The strategy/config layer.
2. **A cross-source planner** — extend `content_engine` (not a new package) with a
   three-source fuser that emits a ranked content plan keyed by sport profile.
3. **An orchestration adapter** — a thin module wrapping the chosen backbone
   (Temporal) so each content type runs as a workflow with an optional approval
   signal; `workflow.store` becomes its persistence detail or is superseded.
4. **An autonomy enforcer** — turns `AutonomyLevel` + the §4 guardrails
   ([`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md)) into the actual publish/skip decision.
5. **Direct publishing adapters** — `publishing/<platform>.py` per platform,
   mirroring the existing `media_ai.providers` resolver pattern.
6. **A local-AI provider** — an Ollama backend behind the existing `ai_core.llm`
   interface (no new public surface; just another provider).

Everything else is *generalisation* of code that already ships.

## 4. The orchestration backbone & local-AI layer (named)

- **Orchestration backbone: Temporal** (`temporalio/temporal`, **MIT**, truly free
  to self-host; 3,000+ paying customers incl. Snap/Netflix/Stripe). Each content
  type is a durable workflow; the **human-approval signal** physically implements
  the per-type autonomy toggle (gated types pause on the signal; autonomous types
  skip it). See [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).
- **Local-AI substitution layer:** Ollama (LLM), Piper (TTS), whisper.cpp /
  faster-whisper (ASR), rembg / MODNet (cutout), Satori (graphics) — each truly
  free and permissive (MIT / Apache-2.0 / MPL-2.0). This layer guarantees the
  **no-hidden-fees** product constraint: every AI call has a zero-cost local path.

## 5. Boundaries that do not move

- **Deterministic engine** (parsers, detectors, ranker, colour-science) stays
  non-AI and authoritative. Autonomy and the brain never touch the *data layer* —
  only the *direction* and *publish* layers (cf. [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md)).
- **AI honesty rule:** no provider configured ⇒ honest error
  (`ClaudeUnavailableError` / `ProviderNotConfigured`), never a fabricated fallback.
- **Human approval before external publishing** is the default
  ([`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md)).
- **No AGPL code embedded.** Postiz / MediaCMS / MinIO are referenced only as
  separate services across a network boundary
  ([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).
