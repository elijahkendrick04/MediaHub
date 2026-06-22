# Dependency Licensing & Hidden-Fee Register

> **In plain words.** MediaHub must keep the **operator's hosting cost and
> licensing liability low** — no building block may force a hidden fee or a
> legal obligation into the critical path. (This register originally guarded a
> "truly-free self-host" promise; that promise was retired in favour of
> **hosted-only SaaS** —
> [`adr/0011`](adr/0011-commercial-reconcile-revenue-reality.md) — but the
> de-risk still matters, now for the *hosted* deployment's margins.) The traps
> are easy to fall into by accident: some popular building blocks are free for
> a hobbyist but charge a company, or are "open source" in a way that legally
> forces you to publish your own code, or quietly route every AI call through
> a paid API. This page is the safety register: which outside tools are safe
> to adopt now, which need care, which need a licence check first, and which
> to avoid — plus where MediaHub's *current* dependencies hide a cost and what
> the free replacement is. New here? See [`../GLOSSARY.md`](../GLOSSARY.md).
>
> **Enforcement (Phase 0, shipped 2026-06-10):** these rules are pinned by
> three guard suites — `tests/test_paid_deps_optional.py` (every paid path
> off/flagged by default, P0.3), `tests/test_local_provider_slots.py` (every
> AI surface admits a local provider, P0.4), and `tests/test_agpl_isolation.py`
> (no AGPL code in-process, P0.5).

Evidence base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md)
Parts C & D. Related: [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md),
[`ROADMAP_BUILT.md`](ROADMAP_BUILT.md) (Phase 0 de-risk — shipped) and
[`ROADMAP.md`](ROADMAP.md) (Phase 4 — zero-cost local AI).

> **Two rules before wiring anything in.**
> 1. **Verify the licence yourself** from the actual `LICENSE` file at the version
>    you adopt. Items below marked *(verify)* were **not** confirmed from source in
>    the research pass. This document is a register, not a legal sign-off.
> 2. **Separate code licence from data/model licence.** A repo's code can be MIT
>    while its *data* (StatsBomb) or *model weights* (Coqui XTTS) carry
>    non-commercial or custom terms. Both must clear.

---

## 1. The register

### ✅ ADOPT NOW — permissive, truly free to self-host

| Building block | Role | Licence |
|---|---|---|
| `temporalio/temporal` (+ Python/TS/PHP SDKs) | Orchestration backbone / human-approval workflow | MIT |
| `ollama/ollama`, `ggerganov/llama.cpp` | Local LLM (zero-cost brain/captions) | MIT |
| `vercel/satori` | HTML/CSS→SVG→PNG graphics (~100× lighter than Chromium) | MPL-2.0 |
| `OHF-Voice/piper1-gpl` (pip `piper-tts`) | Local neural TTS engine — the **default** voiceover backend (roadmap 1.7, replacing edge-tts) | **GPL-3.0-or-later** — used server-side in the hosted-only deployment and **never conveyed** to customers, so no source-offer obligation triggers (the same hosted-only basis the repo already relies on for AGPL SearXNG). The original `rhasspy/piper` engine was MIT; the maintained package is GPL. |
| Piper voice **model** `en_GB-alba-medium` | The licence-clean default voice shipped in the deployed image (1.7) | **CC BY 4.0** — commercial use permitted **with attribution** (trained on the Edinburgh `datashare.ed.ac.uk/handle/10283/3270` corpus). Attribution recorded here + shipped beside the model. *(Per rule 2: the model licence is separate from the engine's — both clear.)* |
| MediaHub `audio/` engine bundled pool (roadmap 1.8) | First-party music/SFX/idents shipped in `src/mediahub/audio/assets` as the no-key default audio library | **CC0-1.0** — synthesised first-party by `scripts/make_audio_assets.py` (no third-party sample), dedicated to the public domain. Adds **no new pip dependency**: `ops.py`/`clean.py` reuse the existing FFmpeg seam (`imageio-ffmpeg`, BSD-2 + stock FFmpeg subprocess); upload fingerprinting optionally uses an operator-supplied **Chromaprint `fpcalc`** binary and denoise an operator-supplied **RNNoise** model — neither is bundled, and both honest-disable when absent. |
| `danielgatis/rembg` | Background removal / cutout | MIT |
| `heuer/segno` (pip `segno`) | Microsite QR generator (roadmap 1.16, `mediahub.sites.qr`) — supplies the raw QR matrix; the brand-colour/contrast-guard/logo/PNG-SVG-PDF layer is MediaHub's own. Pure-Python, **no deps**, no external service, no per-call cost; honest-errors (`QRUnavailable`) if absent. | MIT |
| `ZHKKKe/MODNet` | Portrait matting (code + models) | Apache-2.0 (PPM dataset CC BY-NC-SA) |
| `black-forest-labs/FLUX.1-schnell` (weights) | Local generative-image backend — text→image + inpaint/outpaint for the imagine seam (roadmap 1.1). Self-hosted by the operator behind `MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`; MediaHub ships **no weights** and adds **no new dependency** (HTTP client only). | **Apache-2.0** (avoid the OpenRAIL/non-commercial FLUX.1-dev weights) |
| `openai/whisper`, `whisper.cpp`, `faster-whisper` | ASR / captioning | MIT |
| `material-color-utilities`, `jxnblk/palx` | Theming / palette | Apache-2.0 / MIT |
| `SwimComm/hytek-parser` | Swimming HY3/HYV ingest | MIT |
| `tdsmith/sdif` | SDIF/SD3 ingest | Apache-2.0 |
| `gpilgrim2670/SwimmeR` | Swimming PDF/HTML/HY3 (R) | MIT |
| `swar/nba_api` | Basketball data (keyless) | open (verify) |
| `openfootball/football.json` | Football fixtures/results | Public domain |
| `ndPPPhz/Fixture-Generator` | Round-robin fixtures (npm) | MIT |
| `mutonby/openshorts` | Clip + publish shorts | MIT |

### ⚠️ ADOPT WITH CAUTION — usable if the caveat is respected

| Building block | Caveat | Safe use |
|---|---|---|
| `gitroomhq/postiz-app` | **AGPL-3.0** (network-copyleft) | Run as a **separate self-hosted service, called over its API** — never fork/embed its source into MediaHub's own distributed code. |
| `mediacms-io/mediacms`, `minio/minio` | **AGPL-3.0** | Same network-boundary rule. **Prefer cloud S3 over MinIO** to avoid AGPL entirely; MinIO community edition is also in maintenance flux. |
| `crewAIInc/crewAI`, `langchain-ai/social-media-agent` | Free framework, but LLM calls cost unless local | Pair with Ollama so calls are zero-cost. Licences *(verify MIT-family)*. |
| `Agamnentzar/ag-psd`, `ajamous1/nba-gameday-generator` | PSD-binding / data→poster pattern | Excellent reference; confirm `ag-psd` MIT before depending. |
| `idiap/coqui-ai-TTS` | Toolkit MPL-2.0, but **XTTS-v2 model is CPML (non-commercial)** and no commercial licensor exists post-shutdown | Use VITS/Tacotron backends commercially; **avoid XTTS weights** commercially. (We prefer Piper anyway.) |
| `statsbomb/open-data` | Free data under a **custom non-OSS agreement** (attribution / responsible use), distinct from code | Football spotlight/leader stats only with attribution; prefer public-domain openfootball as the default. |

### 🔍 AUDIT BEFORE USE — licence unconfirmed or partial

`AkhilNam/Sports-Highlight-Detector`, `matija2209/sports-highlights-generator`, the
swimming scrapers (`Swimrankings`, `SwimScraper`, `swimset`, `swimulator`), the
reels tools (`GabrielLaxy`, `steinathan`, `gyoridavid`, `IgorShadurin`,
`vvinniev34`), `clawnify/open-design`, `WhisperX`, `pybaseball`, `TheSportsDB`
(free-tier rate/abuse limits), `JimmyRowland/team_sporty`. Confirm the `LICENSE`
file and any paid-API dependency before adopting.

### ⛔ AVOID — do not reuse as the production engine

| Item | Why |
|---|---|
| `jgolliher/hyparse`, `EdwinWalela/fixture-generator` | **NO LICENSE** (all rights reserved — not legally reusable). |
| `remotion-dev/remotion` *as the for-profit engine* | Source-available, **not free for for-profit orgs >3 people**; Company License $100+/mo. The single biggest hidden-cost item. Keep behind a flag with a free fallback (below). |
| `n8n` *as the embedded engine of a product you sell* | Sustainable Use Licence forbids it (internal use OK). |
| `Mixpost Pro` *to build a SaaS* | Pro licence explicitly forbids SaaS; Enterprise required. |
| `lidojs/canva-clone` | Export feature paywalled; custom "use at your own risk" licence. |
| Paid-API defaults: `Open-Pomelli` / `AI-Youtube-Shorts` *api mode* (MuAPI), `iut62elec/Soccer-Highlight-Generator` (AWS Bedrock) | Switch to local substitutes (Ollama/Piper/rembg/Satori). |
| `ANAS727189/MediaHub` | **Explicitly excluded** — unrelated, same-named project. Never reference, cite, or research it. |

## 2. MediaHub's current dependencies — hidden-fee flags & free substitutes

The product's current AI/media path and its honest cost story. **Default config is
already low/zero marginal cost** — most substitutions are *de-risking*, not fixing a
live bill.

| Current dependency | Hidden-fee flag | Status today | Free substitute (roadmap) |
|---|---|---|---|
| **Remotion** (reels, `remotion/` + `visual/motion.py`) | ⚠️ **Company License** for for-profit >3 people ($25/seat/mo Creators; $0.01/render, $100/mo min Automators; $500/mo min Enterprise). v5.0 mandates telemetry `licenseKey` for the render tier. | **Optional behind a flag** — ✅ substituted (P0.1, 2026-06-10): `MEDIAHUB_REEL_ENGINE=ffmpeg` renders story cards + reels from the card's own still graphics via FFmpeg (`visual/reel_ffmpeg.py`), no Node/Remotion needed. Remotion stays the default for those who license it. | **Shipped**: still-graphic + FFmpeg engine. Satori remains the P5.4 *fast-path* (performance, not licensing). |
| **`edge-tts`** (voiceover, `visual/voiceover.py`) | ⚠️ Free but depends on an undocumented **Microsoft Edge cloud endpoint** — not a stable contract, and caption text leaves the box. | **No longer the default — opt-in only** (roadmap 1.7): selected with `MEDIAHUB_TTS_PROVIDER=edge`; demoted from a required dependency to the `voiceover-edge` extra. | **Piper is now the DEFAULT** (`piper-tts`, GPL-3.0, local CPU) — ✅ **replaced edge-tts (1.7)**: zero-cost, fully offline, the caption text never leaves the box. The deployed image ships a CC BY 4.0 `en_GB-alba-medium` voice (auto-discovered) so it works with no config; honest-errors if the package/model is absent. |
| **`replicate`** (cutout, `media_ai/providers`) | ⚠️ **Paid** per-call cutout API. | **Optional** — default is already in-process **rembg** (`MEDIAHUB_CUTOUT_PROVIDER=server`) | **Already substituted**: rembg (MIT, local) is the default; Replicate/PhotoRoom are opt-in. ✅ |
| **Hosted Anthropic / Gemini keys** (`media_ai.llm`, `ai_core.llm`) | ⚠️ Hosted LLM **API keys** (Gemini free tier today; Anthropic paid). | Shipped; Gemini-first, Anthropic failover | **Ollama** local provider behind the same `ai_core.llm` interface for a zero-key path (Phase 5). |

Notes:
- **No new *mandatory* paid dependency** may be added. Anything paid (Remotion
  Company License, Replicate, hosted keys) must stay **optional, behind a
  flag/env var, with a documented free default** ([`ROADMAP.md`](ROADMAP.md)
  Phase 0 exit criterion).
- The cutout substitution is **already done** — `rembg` is the shipped default.
- The remaining `requirements.txt` deps (Flask, Pillow, pdfplumber, lxml,
  materialyoucolor, coloraide, numpy, PyYAML, …) are permissive and free.
- **`pillow-heif`** (1.3 photo-editor HEIC ingest) is BSD-3; its manylinux
  wheels bundle **libheif** (LGPL-2.1+, dynamically linked) for decode. We use
  it **decode-only at upload time** to convert iPhone HEIC/HEIF to JPEG, never
  to encode/distribute HEVC, and the code (`media_library.heic`) honest-errors
  if the package is ever absent — so it stays an optional, free ingest helper.

## 3. AGPL handling rule (restated)

Do **not** fork or embed AGPL code (SearXNG, Postiz, MinIO, MediaCMS) into this
repo. Reference them only as **external services across a network boundary**, and
say so explicitly wherever they appear. AGPL implications depend on whether you
distribute/network-serve modified code; consult counsel before forking. Prefer the
"separate service called over its API" pattern, and cloud S3 over MinIO.

**The shipped example — SearXNG.** The one AGPL service actually deployed today
is SearXNG (web research, Capability 3): the Dockerfile installs it **stock and
unmodified into an isolated virtualenv** (`$SEARXNG_VENV`), it runs as its own
process only when `MEDIAHUB_RUN_SEARXNG=1`, and MediaHub talks to it exclusively
over HTTP (`web_research/searxng_client.py`, `MEDIAHUB_SEARCH_ENDPOINT`). Its
code is never imported into MediaHub's process.

**Enforced (P0.5, 2026-06-10):** `tests/test_agpl_isolation.py` fails the build
if (a) any known-AGPL module is imported in-process anywhere under
`src/mediahub`, (b) an AGPL distribution appears in `requirements.txt` /
`pyproject.toml`, or (c) the Dockerfile installs SearXNG outside its isolated
virtualenv.
