# Dependency Licensing & Hidden-Fee Register

> **In plain words.** A core promise of MediaHub is **no hidden fees and a truly
> free way to self-host.** That promise is easy to break by accident — some
> popular building blocks are free for a hobbyist but charge a company, or are
> "open source" in a way that legally forces you to publish your own code, or quietly
> route every AI call through a paid API. This page is the safety register: which
> outside tools are safe to adopt now, which need care, which need a licence check
> first, and which to avoid — plus where MediaHub's *current* dependencies hide a
> cost and what the free replacement is. New here? See
> [`../GLOSSARY.md`](../GLOSSARY.md).

Evidence base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md)
Parts C & D. Related: [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md),
[`ROADMAP.md`](ROADMAP.md) (Phase 0 de-risk, Phase 5 local-AI).

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
| `temporalio/temporal` (+ Python/TS/PHP SDKs) | Orchestration backbone / autonomy toggle | MIT |
| `ollama/ollama`, `ggerganov/llama.cpp` | Local LLM (zero-cost brain/captions) | MIT |
| `vercel/satori` | HTML/CSS→SVG→PNG graphics (~100× lighter than Chromium) | MPL-2.0 |
| `rhasspy/piper` | Local neural TTS (voiceover) | MIT |
| `danielgatis/rembg` | Background removal / cutout | MIT |
| `ZHKKKe/MODNet` | Portrait matting (code + models) | Apache-2.0 (PPM dataset CC BY-NC-SA) |
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
| **Remotion** (reels, `remotion/` + `visual/motion.py`) | ⚠️ **Company License** for for-profit >3 people ($25/seat/mo Creators; $0.01/render, $100/mo min Automators; $500/mo min Enterprise). v5.0 mandates telemetry `licenseKey` for the render tier. | Shipped engine — **top cost liability** | **Satori + FFmpeg** fallback behind a flag (Phase 0/5); keep Remotion optional for those who license it. |
| **`edge-tts`** (voiceover, `visual/voiceover.py`) | ⚠️ Free but depends on an undocumented **Microsoft Edge cloud endpoint** — not a stable contract. Already operator-gated (`MEDIAHUB_VOICEOVER=1`) and honest-errors when absent. | Optional, off by default | **Piper** (MIT, local, CPU) (Phase 5). |
| **Buffer** (publishing, `publishing/buffer.py`) | ⚠️ **Paid** scheduling SaaS; an external account + token (`BUFFER_ACCESS_TOKEN`). | Shipped publishing path | **Direct platform APIs**; prioritise genuinely-free **Bluesky (AT Protocol)** + **Mastodon**; budget for X's pay-per-use (Phase 4). |
| **`replicate`** (cutout, `media_ai/providers`) | ⚠️ **Paid** per-call cutout API. | **Optional** — default is already in-process **rembg** (`MEDIAHUB_CUTOUT_PROVIDER=server`) | **Already substituted**: rembg (MIT, local) is the default; Replicate/PhotoRoom are opt-in. ✅ |
| **Hosted Anthropic / Gemini keys** (`media_ai.llm`, `ai_core.llm`) | ⚠️ Hosted LLM **API keys** (Gemini free tier today; Anthropic paid). | Shipped; Gemini-first, Anthropic failover | **Ollama** local provider behind the same `ai_core.llm` interface for a zero-key path (Phase 5). |

Notes:
- **No new *mandatory* paid dependency** may be added. Anything paid (Remotion
  Company License, Replicate, hosted keys, Buffer, X API) must stay **optional,
  behind a flag/env var, with a documented free default** ([`ROADMAP.md`](ROADMAP.md)
  Phase 0 exit criterion).
- The cutout substitution is **already done** — `rembg` is the shipped default.
- The remaining `requirements.txt` deps (Flask, Pillow, pdfplumber, lxml,
  materialyoucolor, coloraide, numpy, PyYAML, …) are permissive and free.

## 3. AGPL handling rule (restated)

Do **not** fork or embed AGPL code (Postiz, MinIO, MediaCMS) into this repo.
Reference them only as **external services across a network boundary**, and say so
explicitly wherever they appear. AGPL implications depend on whether you
distribute/network-serve modified code; consult counsel before forking. Prefer the
"separate service called over its API" pattern, and cloud S3 over MinIO.
