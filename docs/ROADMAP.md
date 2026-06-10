# MediaHub Roadmap

The plan — **one document, in depth**. It opens with the two live lists (what’s
**to do** and what’s **completed**; one line per item, each with a stable ID),
and the rest of the document is the full long-form plan those lists index: the
plain-words overview, the commercial reality check, the phase essays with
per-item detail, the cross-cutting investments, and **Appendices A/B/C** (the
PAR-*/SEQ-*/Step-N build & verification prompts). The decided strategy lives in
the ADRs and companion docs linked under [Standing context](#standing-context).

## Status (auto-updated)

Refreshes on every push to `main` via
[`.github/workflows/roadmap-autoupdate.yml`](../.github/workflows/roadmap-autoupdate.yml)
(landed through an auto-merge PR — `main` requires PRs). Put a directive line
in any commit message to move an item:

> `roadmap: <ID> <status>` — `<ID>` is an item ID from the lists below
> (`PC.3`, `P1.2`, …); `<status>` is `done` · `wip` · `blocked` · `todo`.
> `done` **moves the item to Completed** (date-stamped); any other status
> moves it back to To do with the matching badge.

<!-- ROADMAP:LAST_UPDATED -->
**Last updated:** 2026-06-10 · `d1dbdd16a` · Merge pull request #310 from elijahkendrick04/claude/exciting-johnson-drqqc3
<!-- /ROADMAP:LAST_UPDATED -->

**Recent activity**

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-06-10 | `5e758bced` | docs: regenerate ENV_INVENTORY for MEDIAHUB_FFMPEG + MEDIAHUB_TTS_PROVIDER |
| 2026-06-10 | `cc255f513` | docs(roadmap): fold the archive back in — one in-depth document |
| 2026-06-10 | `e3b227c51` | feat(p0): complete Phase 0 — free reel engine, paid-dep guards, provider slots, AGPL isolation |
| 2026-06-10 | `52e212ef9` | docs(roadmap): restructure into To-do / Completed lists; auto-updater now moves items |
| 2026-06-10 | `ce77df9f3` | feat(gen-v2): complete the PAR bucket against the shipped SEQ-0-4 spine |
| 2026-06-10 | `cc928922d` | fix(roadmap): merge directly when the bot PR is already clean |
| 2026-06-10 | `f141579f6` | fix(roadmap): land auto-updates via auto-merge PR + catch up the missed range |
| 2026-06-10 | `f3bc87b3a` | docs(build): SEQ-3 gate A/B review — v2 beats the old engine; cutover approved |
| 2026-06-10 | `c1e540f32` | style: apply pre-commit hygiene to PR-touched files (ruff-format 0.8.4, EOF fixer) |
| 2026-06-10 | `3a03b9889` | docs(build): final suite result — 3628 passed, 1 skipped after the full spine |
| 2026-06-10 | `4a8623c1f` | docs(build): SEQ-4 verification evidence + suite table in the spine report |
| 2026-06-10 | `52470c085` | feat(gen-v2): SEQ-4 — data-driven reel scene structure + archetype-matched motion + opt-in gen backg |
<!-- /ROADMAP:ACTIVITY -->

## To do

Ordered by priority: **Phase C (commercialise) outranks everything**; P3/P4/P5
are gated behind Phase C's exit criteria (see Standing context).

<!-- ROADMAP:TODO -->
- **PC.3** · Phase C 🥇 — True multi-tenancy: org → workspace in one shared instance (the #1 scaling fix; single-instance-per-club collapses at ~15–40 clubs). Schema needs operator/Council sign-off — it touches the locked ADR-0003 isolation invariant · ⚠️ **BLOCKED**
- **PC.4** · Phase C 🥇 — Pricing & packaging by revealed willingness-to-pay: quote real annual prices to the first hand-sold clubs; keep `/pricing` at "TBC" until ≥5 clubs have paid annual at a tested price · ❌ **NOT STARTED**
- **PC.6** · Phase C 🥇 — Go-to-market: warm-first hand-sell of the first ~10 clubs (local Swansea/South-Wales base + referrals; cold capped) and apply for Swim England's approved-systems data API · ❌ **NOT STARTED**
- **P1.2** · Phase 1 — Realise the post-type taxonomy in code (extend vs layer on `club_platform.content_types` — Council-gated data-model call) · ❌ **NOT STARTED**
- **P1.3** · Phase 1 — Cross-source planner (the strategy brain): fuse own/external/direct signals into a ranked plan keyed by sport profile · ❌ **NOT STARTED**
- **P1.5** · Phase 1 — Brand-DNA-from-URL with no paid API (local scrape + local model + material-color-utilities) · ❌ **NOT STARTED**
- **P2.2** · Phase 2 — Human-approval signal = the autonomy toggle (gated types pause on `workflow.CardStatus` QUEUE → APPROVED → POSTED) · ❌ **NOT STARTED**
- **P2.3** · Phase 2 — Single per-type publish gate: provenance/trust + brand-safety + rate limit + global kill switch on `SafeToPost`; reconcile the two `AutonomyLevel` enums · 🔵 **IN PROGRESS**
- **P3.1** · Phase 3 (gated) — Second-sport engine adapter: `recognition_football`/`_basketball` + `register_sport(...)` · ❌ **NOT STARTED**
- **P3.2** · Phase 3 (gated) — Sports-data API spokes (`nba_api`, openfootball, fixture generators) normalised to `canonical.*` · ❌ **NOT STARTED**
- **P3.3** · Phase 3 (gated) — Running/athletics parsers (chip-timing CSV, client-side FIT) · ❌ **NOT STARTED**
- **P3.4** · Phase 3 (gated) — Normalise all spokes to the canonical schema; flag ambiguous rows for review · ❌ **NOT STARTED**
- **P4.1** · Phase 4 (gated) — Bluesky (AT Protocol) + Mastodon adapters — the free/open posting targets first · ❌ **NOT STARTED**
- **P4.2** · Phase 4 (gated) — Instagram Graph / Facebook / TikTok / YouTube adapters, least-privilege, human-connected · ❌ **NOT STARTED**
- **P4.3** · Phase 4 (gated) — X adapter as a paid, optional target (pay-per-use API) · ❌ **NOT STARTED**
- **P4.4** · Phase 4 (gated) — Demote Buffer to optional; remove it from the critical path · ❌ **NOT STARTED**
- **P5.1** · Phase 5 (gated) — Ollama local LLM provider behind the existing `ai_core.llm` interface · ❌ **NOT STARTED**
- **P5.2** · Phase 5 (gated) — Piper local TTS replaces edge-tts · ❌ **NOT STARTED**
- **P5.3** · Phase 5 (gated) — whisper.cpp / faster-whisper local ASR for reel captions · ❌ **NOT STARTED**
- **P5.4** · Phase 5 (gated) — Satori graphics fast-path (~100× lighter than headless Chromium; rides the reel-engine seam P0.1 shipped) · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO -->

## Completed

<!-- ROADMAP:DONE -->
- ✅ **P0.2** · Phase 0 — Cutout free-by-default: in-process rembg is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`); Replicate/PhotoRoom opt-in *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P5.5** · Phase 5 — rembg cutout shipped as the default (MODNet noted as optional upgrade) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P1.1** · Phase 1 — Sport-profile schema + loader + `AutonomyLevel` + swimming/football YAML profiles (inert scaffolding) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **P2.1** · Phase 2 — Orchestration backbone the in-process way: `scheduler/` exactly-once SQLite runner + `autonomy/` bounded narrow-tool runner (Temporal rejected by Council) *(completed pre-2026-06 — detail in the phase sections below)*
- ✅ **PC.1** · Phase C — Self-serve signup + auth: `/signup` `/login` `/logout`, bcrypt, signed session cookie, `users.jsonl` ledger *(completed 2026-06-09, PR #267)*
- ✅ **PC.2** · Phase C — Stripe billing + subscription lifecycle: Checkout, Customer Portal, signed webhook; honest-503 until the operator sets `STRIPE_*` keys *(completed 2026-06-09, PR #267)*
- ✅ **PC.5** · Phase C — Free-self-host tension resolved: **hosted-only**, no customer self-host tier (maintainer decision; ADR-0011) *(completed 2026-06-09)*
- ✅ **P2.4** · Phase 2 — Per-type autonomy controls in the workspace: Settings → Autonomy tab, per-profile per-type policy defaulting to approval_required, publish gate + global kill switch *(completed 2026-06-09, PR #297)*
- ✅ **P1.4** · Phase 1 — Generative Content Engine v2, complete: Appendix A spine SEQ-0→4 (tokens, Tier B director/pool/APCA compliance ranking, gated SEQ-3 cutover with the A/B review approved, data-driven video) + the full PAR-1→8 bucket (12/12 archetype catalog); v2 is the default engine, `MEDIAHUB_GEN_V2=0` is the kill switch; evidence in `build_reports/SEQ_SPINE_2026-06-10.md` and `build_reports/GEN_QUALITY_BASELINE.md` *(completed 2026-06-10, PRs #259/#300/#301)*
- ✅ **P0.1** · Phase 0 — Free reel fallback shipped: `MEDIAHUB_REEL_ENGINE=ffmpeg` renders story cards + meet reels from the cards’ own still graphics via FFmpeg (`visual/reel_ffmpeg.py`) — no Node, no Remotion license *(completed 2026-06-10)*
- ✅ **P0.3** · Phase 0 — Every paid dependency provably optional behind a flag with a free default wired — pinned by `tests/test_paid_deps_optional.py` against the DEPENDENCY_LICENSING §2 register *(completed 2026-06-10)*
- ✅ **P0.4** · Phase 0 — Local-capable provider slot on every AI surface: LLM (OpenAI-compatible endpoints incl. Ollama, both wrappers), TTS (`MEDIAHUB_TTS_PROVIDER` with the `piper` slot), ASR (guarded — none may land unslotted), graphics (server-side stills + ffmpeg reel engine + cutout `server` default) — pinned by `tests/test_local_provider_slots.py` *(completed 2026-06-10)*
- ✅ **P0.5** · Phase 0 — AGPL isolation enforced: SearXNG stays a stock, venv-isolated, HTTP-only sidecar; `tests/test_agpl_isolation.py` fails the build on any in-process AGPL import, manifest entry, or Dockerfile drift *(completed 2026-06-10)*
<!-- /ROADMAP:DONE -->

## Standing context

The short list of decided, load-bearing principles — full reasoning in the
linked ADRs and research docs:

- **Hosted-only SaaS.** No customer self-host or local-install path, free or
  paid — a decided commercial principle
  ([ADR-0011](adr/0011-commercial-reconcile-revenue-reality.md)).
- **Commercialise before generalise.** Phase C outranks all capability work.
  Two hard gates before P3/P4/P5 start: *(1)* a club can sign up, pay, and
  publish with zero founder involvement; *(2)* **≥10 clubs paying annually**
  ([SCALING_DILIGENCE_2026](research/SCALING_DILIGENCE_2026.md)).
- **Stop polishing and sell.** P1.4 cleared the "sellable wedge" bar; further
  graphics work sits strictly behind Phase C sell-side progress.
- **The deterministic engine is the moat.** Parsers, detectors, the ranker,
  and colour-science stay AI-free; AI judgement goes through
  `media_ai.llm`/`ai_core.llm` with honest errors, never heuristic fakes
  (see [`../CLAUDE.md`](../CLAUDE.md)).
- **Human approval before anything publishes externally. Always.**
- **PC.3 is Council-gated.** The org → workspace schema touches the locked
  cross-tenant isolation invariant
  ([ADR-0003](adr/0003-pilot-safety-invariant-lock.md)) and needs
  operator/Council sign-off before implementation.
- **NGB channel, reality-checked.** Swim England **data-API access is real —
  apply**; promotional NGB endorsement is down-weighted to speculative
  ([ADR-0012](adr/0012-ngb-distribution-channel-reality-check.md)).

**Companion docs:** [POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md) ·
[AUTONOMY_MODEL](AUTONOMY_MODEL.md) · [SPORT_PROFILES](SPORT_PROFILES.md) ·
[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md) ·
[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md) · [THEMING](THEMING.md) ·
[GENERATION](GENERATION.md) · research base in
[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md) ·
new-starter path: [START_HERE](../START_HERE.md) + [GLOSSARY](../GLOSSARY.md).

The long-form plan follows — same document, full depth.

---


## In plain words (start here)

A **roadmap** is our plan for what to build next, and *why*. MediaHub is being
**redirected**: from "swimming results → social posts" into a **content-strategy
brain** for sports teams — software that works out *what a team should post*,
drafts it, and (where a team allows it) publishes it largely on its own. Swimming
becomes the **first example** of a general pattern, not the whole product.

The plan now has **six stages, Phase 0 to Phase 5**:

- **Phase 0 — De-risk:** make sure nothing in the core forces a hidden fee.
  *(✅ done — 2026-06-10.)*
- **Phase 1 — Strategy brain:** the "what should we post?" thinking, the list of
  post types, and a settings sheet per sport.
- **Phase 2 — Autonomy:** per-post-type controls for how much MediaHub may post on
  its own, with strong safety guardrails.
- **Phase 3 — More sports & inputs:** football, basketball, running, and more.
- **Phase 4 — Post directly:** publish straight to the platforms (and stop needing
  the paid Buffer service).
- **Phase 5 — Free AI everywhere:** run the AI locally so there are no per-use fees.

> These six stages **supersede** the previous three-stage plan (*Parity →
> Distinction → Leadership*). That older plan's detailed build prompts are kept in
> the appendices for reference.

> **Ahead of all six in priority (added 2026-06)** sits a new
> **Phase C — Commercialise & Distribute**: self-serve signup, billing, true
> multi-tenancy, sane pricing, and a real way to reach clubs. The numbered phases
> describe *capability*; **Phase C is about getting paid for it** — and a hard-nosed
> scaling diligence
> ([research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md))
> concludes that **comes first.** So the order is now *commercialise, then generalise*:
> the expansions (Phases 3–5) wait until clubs can sign up and pay on their own. The
> reasoning sits under **"A commercial reality check"** below and is recorded in
> **[adr/0011-commercial-reconcile-revenue-reality.md](adr/0011-commercial-reconcile-revenue-reality.md)**.

Each task carries a little badge so you can see how it's going:
✅ done · 🔵 in progress · ⚠️ stuck · ❌ not started yet.

The **"Last updated"** line and the **"Recent activity"** table further down update
themselves automatically whenever we ship something — you don't edit those by hand.

> New to the team? Read **[../START_HERE.md](../START_HERE.md)** first, then come
> back here. Tricky word? See **[../GLOSSARY.md](../GLOSSARY.md)**. The strategy
> behind this rebuild lives in five companion docs —
> **[POST_TYPE_TAXONOMY](POST_TYPE_TAXONOMY.md)** ·
> **[AUTONOMY_MODEL](AUTONOMY_MODEL.md)** ·
> **[SPORT_PROFILES](SPORT_PROFILES.md)** ·
> **[ARCHITECTURE_TARGET](ARCHITECTURE_TARGET.md)** ·
> **[DEPENDENCY_LICENSING](DEPENDENCY_LICENSING.md)** — with the evidence base in
> **[research/ROADMAP_RESEARCH_2026.md](research/ROADMAP_RESEARCH_2026.md)** and the
> decision recorded in
> **[adr/0004-roadmap-rebuild-multisport-autonomy.md](adr/0004-roadmap-rebuild-multisport-autonomy.md)**.

---

> **Reading this:** the single forward-looking roadmap for MediaHub, organised as
> **Phase 0–5**. Only *not-yet-done* work is tracked in detail; shipped work is
> summarised under **"Where we are today."** The previous spine's build and
> verification prompts live in the appendices: **Appendix A** (Generative Content
> Engine v2), **Appendix B** (growth & expansion — *legacy sequence, superseded*),
> and **Appendix C** (Adaptive Theming Engine verification).

**Strategic thesis:** MediaHub is a **content-strategy brain, not a results
parser.** The moat is the intelligence layer — ingest → detect → rank → brand →
generate → approve → export — now **generalised across sports** and made **largely
autonomous**, delivered as a **hosted SaaS** (hosted-only — no customer self-host
tier; a decided principle, see [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)).
Results ingestion is one spoke among many.

**A commercial reality check (2026-06) — *commercialise before generalising*.** The
thesis above is a **capability** thesis. A 2026 scaling diligence
([research/SCALING_DILIGENCE_2026.md](research/SCALING_DILIGENCE_2026.md)) weighed it
against market data and concluded the **binding constraint is distribution and
monetisation, not more capability** — and that this roadmap, being 100% an engineering
plan with no commercial track, was missing its most important phase. The load-bearing
conclusions, now encoded below:

> ⚠️ **All revenue figures here are hypotheses/estimates, not facts** — see the
> diligence report and its caveats. No pre-launch solo venture can have high confidence
> of any specific revenue number; the confidence attaches to the *decisions*, not the
> outcome.

- **Swimming-only is mathematically capped at ≈ £150k–£400k ARR** (~1,300 UK&I
  affiliated clubs; ~2,740 USA Swimming clubs). £1M ARR at £30/mo would need ~2,778
  paying clubs — more than *every* UK affiliated club. **£1M+ requires multi-sport
  breadth *and* institutional buyers (schools / governing bodies) *and* almost certainly
  a second person.**
- **"£1M/month" (~£12M ARR) is dropped as a stated goal** — not realistic for a
  solo→small team on any evidence reviewed. The most likely *good* outcome is a
  £150k–£400k sustainable swimming business, with a low-double-digit-% shot at £1M+ only
  via sport/segment expansion plus a second person.
- **Single-instance-per-club can't scale**, and **"truly free, no hidden fees"
  self-host — as framed — cannibalises revenue.** True multi-tenancy is delivered by
  **Phase C**. The self-host tension is now **resolved (2026-06-09): hosted-only, no
  customer self-host tier** — the "no-hidden-fees / truly-free self-host" product
  principle is retired in favour of hosted SaaS (maintainer decision, see
  [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)).
- **The incumbent-bolts-on-content threat is currently LOW but is a *time advantage,
  not a moat*;** the horizontal commodity (Canva / Predis / Gipper's auto-achievement
  graphics) is the real pressure on price and narrative.

**Consequence for the plan:** a new **Phase C — Commercialise & Distribute** becomes the
**top priority**, ahead of the expansion phases. P3 (multi-sport), P4 (direct publishing)
and P5 (local-AI) are **deferred — not deleted** — behind two gates: *a club can sign up,
pay, and publish with zero founder involvement*, and *≥10 clubs paying annually*. Recorded
in [adr/0011-commercial-reconcile-revenue-reality.md](adr/0011-commercial-reconcile-revenue-reality.md).

**Realistic revenue by horizon (estimates — outcome odds, not guarantees).** The
≈ £150k–£400k swimming-only ceiling above is a *saturation* figure; the table below
decomposes it into horizons tied to the **PC.6 warm-first funnel's** club-count trajectory
and the candidate **Club £49–£99/mo billed annually** price (≈ £588–£1,188 per club per
year — **PC.4, unvalidated**). The *club-count↔ARR arithmetic and the sequencing are
>95%-confidence-correct*; the *probability bands are honest estimates of the outcome*,
flagged `[ESTIMATE]`, not commitments — they decline across horizons because each is
conditional on the one before (compounding execution risk).

| Horizon | Paying clubs | ARR @ £588–£1,188/club | Outcome probability `[ESTIMATE]` | Binding constraint |
|---|---|---|---|---|
| **H1 — Validation** (≤ ~12 mo) | ~10 (the traction gate) | ≈ £6k–£12k | **~40–55%**, *conditional on the founder actually running the warm + referral motion* — the dominant failure mode is the motion not being run, not the close rate | Founder selling-time; first revealed WTP (PC.4) |
| **H2 — Early scale** (~1–2 yr) | ~30–60 | ≈ £18k–£71k | **~25–40%** — conditional on H1 + referral compounding + retention holding (annual prepay essential) | **PC.3 multi-tenancy** — single-instance ops collapse ~15–40 clubs |
| **H3 — Swimming ceiling** (~2–4+ yr) | ~125–680 (price-dependent) | **≈ £150k–£400k** | **~10–20%** — needs sustained multi-year execution, meaningful UK *and* US penetration, and almost certainly a second person | Market size (~1,300 UK&I + ~2,740 USA clubs) + support capacity |
| **H4 — £1M+ ARR** | (out of wedge) | **≥ £1M** | **low-double-digit-%** — only via multi-sport breadth (Route A) *and* institutional buyers (Route B) *and* a second person | Out-of-wedge expansion; not swimming-only |
| **£1M/month (~£12M ARR)** | — | ~£12M | **not realistic** on any evidence reviewed | Directional north star only |

> **Sequencing caveat (load-bearing):** every horizon past **~15–40 clubs is gated on PC.3
> (true multi-tenancy)**, which is currently ⚠️ BLOCKING / escalated. Without it, per-club
> ops cost rises linearly against fixed founder hours and caps revenue *below* the H3
> market math regardless of demand — so the £150k–£400k ceiling is only reachable *if PC.3
> ships*. Club-count↔ARR arithmetic and the ~£150k–£400k anchor derive from the sourced
> market sizes and candidate price above (see
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)); the
> per-horizon probability bands are flagged estimates, consistent with the diligence's
> low-double-digit-% confidence on £1M+.

---

---

## Where we are today (June 2026)

Three facts shape the work ahead.

1. **The intelligence layer is the moat and is already ahead — for swimming.**
   Brand-DNA + guidelines ingestion, voice imitation, the AI-derived operating
   profile, the Adaptive Theming Engine, swim recognition, and the
   render/caption/pack pipeline all ship and are live. The reframe does not throw
   any of this away — it **generalises** it.

2. **The product is operator-managed and turnkey.** Configuration (LLM keys, Buffer
   token, cutout provider) is set once via env vars at deploy time; the end user
   never sees a settings screen.

3. **Most of the new architecture already has a home in the code.** The new
   concepts map onto existing seams — `recognition.registry.register_sport`,
   `club_platform.content_types`, `workflow.CardStatus`, `ClubProfile.org_type` —
   so this is generalisation, not a rewrite. See
   [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md).

**Verified shipped (✅)** — confirmed against the code this rebuild:

- Brand-DNA / guidelines ingestion (`brand/dna_capture.py`, `guidelines.py`),
  voice imitation (`brand/voice_imitation.py`, `voice/learned/`), and the AI
  operating profile (`brand/derived.py`).
- Adaptive Theming Engine (`theming/`, the former §1.6 — see [`THEMING.md`](THEMING.md)
  and Appendix C); single DTCG palette consumed by web + motion + email + graphic.
- Swim recognition (`recognition_swim/` on the sport-agnostic `recognition` bus),
  PB verification (`pb_discovery/`), ranker (deterministic).
- `graphic_renderer` (Playwright → PNG) and Remotion reels (`remotion/` +
  `visual/motion.py`).
- `edge-tts` voiceover (optional, `MEDIAHUB_VOICEOVER=1`, honest-errors when absent).
- Buffer publishing path (`publishing/buffer.py`; human clicks Schedule — no autopost).
- Content packs (`content_pack/`, `workflow/pack.py`).
- **Free cutout by default** — in-process `rembg` (`MEDIAHUB_CUTOUT_PROVIDER=server`);
  Replicate/PhotoRoom are optional paid alternates. *(This is Phase-5 substitution
  already done.)*
- Cross-tenant run isolation invariant (`_can_access_run`,
  `tests/test_run_route_isolation_invariant.py`) — see
  [`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md).
- Gemini→Anthropic provider failover (`media_ai/llm.py`, `ai_core/llm.py`).
- **Self-serve signup + auth + Stripe billing** (`web/auth.py`, `web/billing.py`): routes
  `/signup` `/login` `/logout`, bcrypt + a signed session cookie, a `users.jsonl` ledger,
  plus Stripe Checkout + Customer Portal + a signed webhook. Merged **PR #267**
  (2026-06-09); billing **honest-503s until `STRIPE_*` keys are set**. This is
  **PC.1 + PC.2** — see Phase C.

**Not yet shipped (❌)** — the reframe's new surface:

- The content-strategy brain **as the hub** (today's planner is swim-result-centric).
- Multi-sport beyond swimming (the `register_sport` seam exists; only swimming is
  registered; `football.yaml` is config-only).
- Per-content-type **autonomy toggles in the UI** (the *runner* now exists — see
  below — but the per-post-type toggle and workspace control do not, and the
  `sport_profiles.AutonomyLevel` enum that was meant to drive them is still inert).
- **Direct-to-platform** publishing (only Buffer today).
- The **local-AI substitution layer** (Ollama / Piper / whisper.cpp / Satori absent;
  rembg present).
- **The rest of the commercial layer** — signup + billing themselves now ship (see
  above), but **true multi-tenancy** (org → workspace in one shared instance; **PC.3**,
  blocking), **validated pricing** (**PC.4**) and a **go-to-market motion** (**PC.6**) are
  still missing, and because billing is unconfigured there are **zero paying customers**.
  This "build/sell imbalance" is the binding constraint per the 2026 scaling diligence;
  closing it is **Phase C**, the top priority (see below) — now **half-closed on the build
  side, fully open on the sell side**.

**Shipped (✅ 2026-06-10):** the Generative Content Engine v2 — the full
Appendix A **Sequential Spine** (SEQ-0 → SEQ-4) merged in **PR #301** on top of
Tier A (PR #259): the DesignTokens contract (`brand/design_tokens.py` +
lockup selection), the Tier B design-spec director with the candidate
pool / APCA compliance ranking / additive `?candidates=N` route, the **SEQ-3
cutover** (the old enum-permutation engine removed under the gated 15+15-step
process; `MEDIAHUB_GEN_V2=0` remains the kill switch; the "A/B beats the old
engine" gate was reviewed and approved — 6/6 vs ≤1/6 approvable), and the
SEQ-4 video stage (data-driven reel scene structure, archetype-matched
motion, opt-in `MEDIAHUB_GEN_BG`). v2 is the **default engine**; the
archetype library stands at 11/12 (PAR-7's `duo_athlete_split` outstanding,
picked up automatically when it lands). Evidence:
[`build_reports/SEQ_SPINE_2026-06-10.md`](build_reports/SEQ_SPINE_2026-06-10.md);
suite 3628 passed / 1 skipped. The sport-profile scaffolding remains inert.

**Shipped (✅ 2026-06-10): Phase 0 complete.** The de-risk phase closed in one
pass: the **P0.1 free reel engine** (`MEDIAHUB_REEL_ENGINE=ffmpeg` — story cards
and meet reels rendered from the cards' own still graphics by FFmpeg, no
Node/Remotion), the **P0.4 provider slots** (OpenAI-compatible/Ollama LLM
endpoints in both wrappers, the `MEDIAHUB_TTS_PROVIDER` seam with the `piper`
local slot, the no-unslotted-ASR guard, on-server graphics defaults), and the
**P0.3/P0.5 guard suites** that turn the dependency register's promises into
build-failing invariants (paid paths provably optional; AGPL strictly behind a
network boundary — SearXNG venv-isolated, HTTP-only). Details in the Phase 0
section below.

#### Also shipped since this plan was written — *not* in the Phase 0–5 spine

A whole stream of work landed after this roadmap was last rewritten and has **no
item here**. It was driven by a separate "**Capabilities 1–5 / Section 6**" report
(referenced in the council transcripts and in `.env.example`, but never checked in
as a doc) and by day-to-day product-quality passes. Folding it in so the roadmap is
honest:

- **Capability 1 — `ai_core` LLM client + bounded tool-loop.** A provider-agnostic
  OpenAI-compatible client and `ask_with_tools(tools, on_tool_call, max_rounds)`
  (the substrate the autonomy + research loops ride on). *Wired.*
- **Capability 2 — semantic caption memory** (`memory/`). Embeddings + a `sqlite-vec`
  store; recalls a club's prior accepted captions into the caption/voice flow.
  Off until an embed endpoint is configured. *Wired.*
- **Capability 3 — web research** (`web_research/`). DuckDuckGo by default, optional
  self-hosted SearXNG, plus a bounded deep-research ReAct loop; converged with
  PB-baseline discovery behind a type-safe gate (the model proposes URLs, the
  deterministic parser still asserts the time). *Wired, £0 default.*
- **Section 6 — the autonomy substrate.** `scheduler/` (an exactly-once, atomic-claim
  SQLite job runner — *not* Temporal; the council chose in-process Flask+threading
  over new infra), `notify/` (ntfy + webhook pings), and `autonomy/` — a **bounded,
  narrow-tool autonomy runner** that prepares + *queues for human review* and can
  never publish. All **off by default**. This is a real, if partial, down-payment on
  **Phase 2** via a different architecture than P2.1 proposed.
- **Results from a link** (`results_fetch/`). Paste a results URL → 3-tier crawl
  (static → headless Chromium → AI vision) → mirror ZIP → the existing pipeline.
  Sport-agnostic *ingestion*; production-ready. See [`RESULTS_FROM_URL.md`](RESULTS_FROM_URL.md).
  (Detector *quality* for non-swim sports still needs a registered sport — so this
  advances **P3** ingestion without yet satisfying its per-sport exit criterion.)
- **Observability** (`observability/`) — LLM-usage + uptime tracking. **Graphics /
  caption / brand-fidelity polish** — new card layouts, AI-palette-from-usage, logo
  vision colours, caption tone/jargon/locale fixes (the bulk of recent commits).

> **Two `AutonomyLevel` enums now exist** and must be reconciled when Phase 2 is
> built properly: `sport_profiles/autonomy.py` (`draft_only`/`approval_required`/
> `fully_autonomous` — the *publishing*-autonomy policy, inert) vs `autonomy/tools.py`
> (`OFF`/`SUGGEST`/`DRAFT`/`PREPARE` — the *runner*'s pre-approval reach, live). They
> describe different axes; don't collapse them blindly.

> **Test baseline (point-in-time):** the full suite is green — **2836 passed, 1
> skipped** in a fully-provisioned environment after merging `main` (the lone skip
> is the opt-in render-diff regression). Skips are environmental, never structural.

---

## Phase 0 — De-risk licensing & cost · P0 · ✅ **COMPLETE (2026-06-10)**

**Goal.** Keep the **operator's hosting cost and licensing liability low** in the
critical path — no mandatory paid API and no embedded-AGPL lock-in. (Originally framed
as guaranteeing a "truly-free self-host" promise; that promise is **retired** —
hosted-only, see [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md) — but the
cost/licensing de-risk still matters, now for the *hosted* deployment's margins.)

**Exit criterion — MET.** Zero **mandatory** paid API or dependency in the critical
path; every paid option is behind a flag/env var with a documented free default; AGPL
services are isolated behind a network boundary (never embedded). The criterion is
now **continuously enforced**, not just satisfied: three guard suites
(`tests/test_paid_deps_optional.py`, `tests/test_local_provider_slots.py`,
`tests/test_agpl_isolation.py`) fail the build on any regression. See
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).

### P0.1 — Make the Remotion reel engine optional with a free fallback · ✅ **DONE (2026-06-10)**
Remotion was the single biggest hidden-cost liability (Company License for for-profit
orgs >3 people). It is now optional behind `MEDIAHUB_REEL_ENGINE`: the **`ffmpeg`
engine** (`visual/reel_ffmpeg.py`) renders the same story-card and meet-reel MP4s
with zero licensing cost — each beat is the card's **own still graphic** (the
existing Playwright/Chromium renderer, already a hard dependency), given a
deterministic Ken Burns zoom and stitched with crossfades by FFmpeg (static binary
via the `imageio-ffmpeg` wheel; system ffmpeg / `MEDIAHUB_FFMPEG` also honoured).
Where a card has a persisted CreativeBrief, the frame renders from that exact brief
at story size, so the reel literally animates the card's approved design — brand
parity *better* than a parallel template. Reel length keeps the same data-driven
`reel_duration_for` arithmetic; cache keys are engine-separated; a missing binary
raises an honest `ReelEngineUnavailable`. Remotion remains the default for
deployments that license it; `/healthz/deps` reports both engines' availability and
gates "motion ok" on the *active* engine. The originally-sketched **Satori** path
remains P5.4 — it is a *performance* fast-path (lighter than Chromium), not the
licensing fix; this fallback closes the licensing risk without it. (Bonus fix
shipped with it: `reel_cover`'s mega headline now auto-fits long meet names via the
PAR-2 autofit helper instead of overflowing the frame.)

### P0.2 — Keep cutout free-by-default · ✅ **DONE**
Already shipped: in-process `rembg` is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`);
Replicate/PhotoRoom are opt-in paid alternates. Retained here as the de-risk record.

### P0.3 — Flag every paid dependency with a free substitute · ✅ **DONE (2026-06-10)**
The register ([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) §2) is now
**provable**: `tests/test_paid_deps_optional.py` pins, per register row, that with
zero paid configuration each paid path is off (or substituted by its free default)
and honest-errors rather than spending or faking — Remotion (optional behind the
P0.1 engine flag), edge-tts (`MEDIAHUB_VOICEOVER` opt-in), Buffer (token-gated,
`BufferAuthError` when absent), Replicate/PhotoRoom (cutout defaults to in-process
`server`), hosted LLM keys (`ProviderNotConfigured`, never a heuristic caption),
Stripe (honest-503 `billing_configured()` gate), and Imagen backgrounds
(`MEDIAHUB_GEN_BG` opt-in, default off).

### P0.4 — A local-capable default for every AI call · ✅ **DONE (2026-06-10)**
Precondition for Phase 5, now in place — every AI surface *admits* a local provider
so no cloud key is required by any interface (full local implementations remain
Phase 5 work): **LLM** — both wrappers (`ai_core.llm`, `media_ai.llm`) accept an
OpenAI-compatible endpoint via `MEDIAHUB_LLM_ENDPOINTS`, keyless local servers
(Ollama / llama.cpp / vLLM) included; **TTS** — `MEDIAHUB_TTS_PROVIDER` seam on the
voiceover surface with `piper` registered as the local slot (honest error until
P5.2 implements it; surfaced in `/healthz/deps`); **ASR** — no ASR call exists yet
(arrives with P5.3), and a guard fails the build if a speech-to-text import ever
lands outside a provider seam; **graphics** — rendering is already on-server
(Playwright stills; P0.1 ffmpeg reels), cutout defaults to in-process rembg, and
the one cloud-only image call (Imagen backgrounds) is opt-in with the procedural
backdrop as the no-key default. Pinned by `tests/test_local_provider_slots.py`.

### P0.5 — Isolate any AGPL service behind a network boundary · ✅ **DONE (2026-06-10)**
The deployed AGPL service is **SearXNG**: installed stock and unmodified into an
isolated virtualenv (`$SEARXNG_VENV`), run as its own process only when
`MEDIAHUB_RUN_SEARXNG=1`, queried exclusively over HTTP
(`web_research/searxng_client.py`) — never imported in-process. That boundary is
now **enforced**: `tests/test_agpl_isolation.py` fails the build on any in-process
import of a known-AGPL module, any AGPL distribution appearing in
`requirements.txt`/`pyproject.toml` (incl. `minio` — policy prefers cloud S3), or
the Dockerfile installing SearXNG outside its venv. If/when Postiz/MinIO/MediaCMS
are ever used, the same separate-service-over-API rule applies. Policy in
[`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) §3.

**Building blocks (as shipped).** FFmpeg (LGPL/GPL, free — static binary via
`imageio-ffmpeg`, invoked strictly as a subprocess) + the existing Playwright still
renderer for reels; `rembg` (MIT, free) — the cutout default; OpenAI-compatible
endpoints (Ollama, MIT) as the LLM local slot; Piper (MIT) reserved as the TTS local
slot. Remotion Company License is *not* a hard requirement; no AGPL is embedded.
Satori (MPL-2.0) stays on the board for P5.4 as a render fast-path.

**Dependencies.** None upstream. **Feeds every later phase** — especially P4
(publishing) and P5 (local-AI), whose free defaults this phase guarantees.

---

## Phase 1 — Strategy brain + post-type taxonomy + sport profiles · P1 · 🔵 **IN PROGRESS**

**Goal.** Build the planner that fuses **three-source intelligence** (own + external
+ direct signals) into a ranked content plan; realise the cross-sport **post-type
taxonomy**; and ship the **sport-profile** config. Ship swimming + one other profile.

**Exit criterion.** A profile-driven planner produces a ranked, explainable content
plan for **≥2 sport profiles** (swimming + football or basketball), grounded in the
three sources — not just from a results file.

### P1.1 — Sport-profile schema + loader + AutonomyLevel + 2 profiles · ✅ **DONE**
Shipped this rebuild as **inert scaffolding**: `mediahub.sport_profiles`
(`SportProfile`/`PostTypeConfig`, `AutonomyLevel`), `data/sport_profiles/{swimming,
football}.yaml`, unit tests. Not wired into runtime yet. See
[`SPORT_PROFILES.md`](SPORT_PROFILES.md).

### P1.2 — Realise the post-type taxonomy in code · ❌ **NOT STARTED**
Reconcile the taxonomy ([`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md)) with the
existing `club_platform.content_types.ContentType` registry (extend vs. layer —
Council-gated data-model call).

### P1.3 — Cross-source planner (the strategy brain) · ❌ **NOT STARTED**
Extend `content_engine` (planner) + `context_engine` to fuse own/external/direct
signals into a ranked plan keyed by sport profile. The swim newsworthiness ranker
generalises into the cross-source prioritiser.

### P1.4 — Generative Content Engine v2 (distinctive, on-brand output) · ✅ **DONE**
The asset-quality stream: replace the enum-permutation variation mechanism with an
archetype library + design-spec director, keeping the deterministic engine. Decided
in [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md); runnable
build prompts in **Appendix A** (PAR-\* / SEQ-\*). **Complete (2026-06-10):** Tier A
(SEQ-1, PR #259) + the full Sequential Spine SEQ-0→SEQ-4 (PR #301) — tokens, the
Tier B director/pool/compliance ranking, the gated SEQ-3 cutover (old engine
removed; A/B review approved; `MEDIAHUB_GEN_V2=0` kill switch retained), and the
SEQ-4 video stage. All seven Appendix A §5 acceptance criteria met; evidence in
[`build_reports/SEQ_SPINE_2026-06-10.md`](build_reports/SEQ_SPINE_2026-06-10.md).
The **parallel bucket (PAR-1 → PAR-8) is likewise all shipped** (PR #300):
captions live end-to-end (approval seam → few-shot store → route injection,
also feeding the SEQ-0 voice block), autofit with measured Anton calibration,
saliency, the design-spec contract, variant metrics, brand bootstrap aligned to
the DesignTokens lockup vocabulary, the complete 12-archetype catalog
(`duo_athlete_split` closes it) with every archetype's authored notes briefing
the director's catalog, and the docs/ADR refresh — plus the renderer
self-hosted-font fix, regression-pinned.

### P1.5 — Local brand-DNA-from-URL · ❌ **NOT STARTED**
Re-implement the Open-Pomelli brand-DNA flow with local scrape + Ollama +
`material-color-utilities` (no paid MuAPI). Brand-DNA capture partly exists in
`brand/`; this generalises and de-paid-API-s it.

**Building blocks.** crewAI / LangGraph **patterns** (free frameworks — *verify
MIT-family*) paired with **Ollama** (MIT, free) for the planner;
`material-color-utilities` (Apache-2.0) — already in use; Satori for graphics
(Phase 5 overlap). All AI calls must keep the honest-error rule.

**Dependencies.** Needs **P0** (a free AI path). **Feeds P2** (autonomy needs a
plan to act on) and **P3** (new sports need profiles).

---

## Phase 2 — Autonomy toggles + orchestration backbone · P2 · 🔵 **IN PROGRESS — substrate + per-type policy shipped; P2.2 partially subsumed; P2.3 partial**

**Goal.** Put every content type on a durable workflow with an **optional
human-approval signal**; implement the guardrails + kill switch + audit trail;
expose the per-type `autonomy_level` in the workspace.

**Exit criterion.** A content type can be set to any `AutonomyLevel`;
`fully_autonomous` publishes **only** when all guardrails + the confidence gate pass;
the kill switch halts publishing instantly; every autonomous decision is recorded in
an immutable audit trail. Full model: [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md).

> **Reality check (2026-06 reconcile).** A meaningful slice of this phase already
> shipped under the "Section 6" stream — but via a **different architecture than P2.1
> proposed**. The council rejected Temporal in favour of an **in-process** design
> (Flask + `threading` + SQLite, no Celery/Redis/new infra): `scheduler/` fires due
> tasks exactly-once via an atomic SQLite claim, `autonomy/` is a bounded narrow-tool
> runner that only ever *queues for human review*, and `workflow/autonomy.py` keeps an
> audit log. All **off by default**. What's left is the **product surface**, not the
> backbone: the per-type policy (P2.2/P2.4) and the remaining guardrails (P2.3).

### P2.1 — ~~Temporal orchestration adapter~~ → in-process scheduler + bounded runner · ✅ **DONE (in-process, not Temporal)**
Superseded by a council decision: instead of a Temporal adapter, durability is the
`scheduler/` atomic-claim SQLite runner + the `autonomy/` bounded loop, both riding
`ai_core.ask_with_tools`. `workflow.store` remains the card-state precursor. Temporal
is **not** being adopted; this item is closed by the in-process substrate.

### P2.2 — Human-approval signal = the autonomy toggle · ❌ **NOT STARTED**
Gated types pause on the signal; autonomous types skip it. Maps onto the existing
`workflow.CardStatus` QUEUE → APPROVED → POSTED transition.

### P2.3 — Guardrails: provenance/trust · brand-safety · rate limit · kill switch · audit · 🔵 **PARTIAL**
Foundations exist: `workflow/autonomy.py` keeps an immutable audit log; the runner's
tools are a fixed allow-list (no shell/file/web) and structurally cannot publish;
`publishing.posting_log` records posting events; `context_engine.trust` scores
provenance. **Remaining:** wire these into a single per-type *publish gate* with a
brand-safety check and a global kill switch, on `recognition.schema.SafeToPost`. The
safeguarding posture from ADR-0003 applies to minors' data.

### P2.4 — Per-type autonomy controls in the workspace · ✅ **DONE**
Surface the toggle; default everything gated; warn before enabling `fully_autonomous`.
Shipped + live (PR #297): Settings>Autonomy tab with per-profile per-type policy defaulting to approval_required; publish gate consults the policy behind the global kill switch; /healthz/deps exposes per_type_autonomy. Canonical enum = sport_profiles.autonomy.AutonomyLevel; the second AutonomyLevel enum still needs reconciliation.

**Building blocks.** **Temporal** (MIT — truly free to self-host; 3,000+ paying
customers incl. Snap/Netflix/Stripe) for the backbone + human-in-the-loop signal.
The "Agent Inbox" pattern (langchain-social-media-agent — *verify*) as reference.

**Dependencies.** Needs **P1** (a content plan) and **P0** (free path). Gates **P4**
(publishing must obey autonomy + guardrails).

---

## Phase C — Commercialise & Distribute · PC · 🔵 **IN PROGRESS (PC.1/PC.2 shipped)** · 🥇 TOP PRIORITY

> **Why "Phase C", not "P6".** It is lettered, not numbered, because it does not sit
> *after* Phase 5 — it sits **ahead of the expansion phases (P3/P4/P5) in priority.** The
> numbered phases are *capability*; Phase C is *commercialisation*. Added in the 2026-06
> diligence reconcile
> ([`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md));
> evidence base in
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md). It does not
> invent new work — it **promotes and reconciles** Appendix B **Step 7** (commercial
> layer), Appendix B **Step 14** (multi-club orchestration), and the cross-cutting
> **"Multi-tenancy: org → workspace"** item into one front-of-queue track.

**Goal.** Make MediaHub **sellable without the founder in the loop**: self-serve signup +
auth, Stripe billing, **true multi-tenancy** (org → workspace in one shared instance),
validated pricing with annual prepay, a resolved free-self-host position (**resolved:
hosted-only** — [adr/0011](adr/0011-commercial-reconcile-revenue-reality.md)), and a
go-to-market motion. **Update 2026-06-09:** the *build* half is now half-closed —
self-serve signup + auth (**PC.1**) and Stripe billing (**PC.2**) shipped and are live
(merged PR #267). But billing **honest-503s until the operator sets `STRIPE_*` keys**, so
there are still **zero paying customers** against ~164k LOC. The diligence's central
"build/sell imbalance" is therefore **half-closed on the build side and entirely open on
the sell side** — the remaining gates are true multi-tenancy (**PC.3**), validated
pricing (**PC.4**) and a go-to-market motion (**PC.6**).

**Exit criteria (both are hard gates on later phases).**
1. **Commercial-readiness gate:** *a club can sign up, pay, and publish with zero founder
   involvement.* No scaling work (P3/P4/P5) starts until this holds.
2. **Traction gate:** *≥10 clubs paying annually* before any new sport (P3). If the wedge
   stalls below ~50 clubs over time, that is a retention/PMF problem to fix — **not** a
   signal to add sports.

### PC.1 — Self-serve signup + auth · ✅ **DONE**
The signup/login/session half of Appendix B **Step 7** (email+password, hashed; signed
session cookie), promoted from "alongside Phase 1" to the front of the queue. Self-hosted
deployments without billing env vars keep working (auth optional). *Ref: Appendix B Step 7.*
Shipped in PR #267 (signup/login/logout, bcrypt, signed session cookie, users.jsonl ledger); live-verified 2026-06-09. Auth stays optional when no accounts/billing are configured.

### PC.2 — Stripe billing + subscription lifecycle · ✅ **DONE (code-complete; awaits operator STRIPE_* keys)**
The billing half of Appendix B **Step 7**: Stripe Checkout, the Customer Portal, and a
signed webhook that drives plan state. Annual prepay is the default (see PC.4). Billing
routes honest-error (`503 "billing not configured"`) when `STRIPE_*` is unset, so the
free/self-host path is unaffected. *Ref: Appendix B Step 7.*
Shipped in PR #267 (Checkout, Customer Portal, signed webhook driving plan state). Routes honest-503 when STRIPE_* is unset so there is zero added running cost until the operator sets keys; live-verified 2026-06-09.

### PC.3 — True multi-tenancy: org → workspace · ⚠️ **PARTIAL (foundation only) — BLOCKING**
**The #1 architectural fix.** Single-instance-per-club rises linearly in ops/support
against fixed founder hours and collapses around 15–40 clubs. Generalise to **org →
workspace isolation in one shared instance.** The cross-tenant **isolation invariant
already shipped** (`_can_access_run`, [`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md))
— that is the foundation, not the finish line. This is the **Organisation → Club → Run
hierarchy** of Appendix B **Step 14**, pulled forward from "enterprise leadership" to a
**blocking prerequisite**. *Ref: cross-cutting "Multi-tenancy: org → workspace"; Appendix B
Step 14.*

Escalation (2026-06-09, autobuild): the remaining work binds user-account identity to org membership and generalises cross-org isolation in one shared instance, which directly touches the locked cross-tenant isolation invariant (ADR-0003). Per CLAUDE.md governance this is a high-stakes, hard-to-reverse architecture fork that must be Council-pressure-tested and operator-signed-off before the org to workspace schema is committed; the autonomous build loop must NOT rearchitect it unattended. NEEDS OPERATOR/COUNCIL sign-off on the schema before implementation.

### PC.4 — Repricing & packaging (validate, don't assume) · ❌ **NOT STARTED**
The £30/£250 tiers in the code are **unvalidated and too low**, and the £30 anchor must
die. But the corrective is **not** to swap in a new fixed price — it is to **discover the
price from revealed willingness-to-pay before locking any public list price.** WTP at the
candidate tiers is the single most load-bearing *unproven* assumption on the whole revenue
path, so PC.4 is structured as an evidence gate, not a one-off reprice:

- **Candidate hypothesis (to test, not to publish):** Club **£49–£99/mo billed
  annually**, Federation **£250+/mo**. Annual prepay is non-negotiable — SMB/volunteer
  churn runs 3–7%/mo and annual billing cuts it ~30–40% ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)).
- **Validation method:** treat the first ~10 hand-sold clubs (**PC.6**) as live price
  discovery. Quote a *real* annual price, vary it across clubs, and record accept/decline
  plus the price each club will actually pay — i.e. **revealed** WTP from real payments,
  not survey-stated WTP.
- **Gate (the >95%-confidence-correct step):** keep `/pricing` at the honest
  *"Pricing TBC"* it already shows until **≥5 clubs have paid an annual prepay at a tested
  price**; only then commit a public list price, set at the highest tested point that
  still cleared. Below that signal, any fixed list price is a guess.
- **Why this sequencing:** under-pricing is hard to reverse (re-pricing existing annual
  contracts upward churns volunteer buyers), and over-pricing with no buyers teaches
  nothing. Revealed WTP from real annual payments is the only evidence that de-risks the
  tier — and it costs nothing extra because the first ~10 sales happen anyway under PC.6.

**Sourced price comparators (anchor the hypothesis; every figure dated):**

| Comparator | Segment | Current price | What it anchors |
|---|---|---|---|
| **Gipper** (closest analog) | US K-12/college athletic depts | **$625 / $1,500 / $3,000 per year, annual-only** *(gipper.com/pricing, verified 2026-06-09)* | The institutional ceiling a results-graphics tool can reach *with a sales motion*. |
| **Predis.ai** (horizontal AI) | Any SMB / creator | **$19 / $40 / $212 per month** *(predis.ai/pricing, verified 2026-06-09)* | The buyer's mental price ceiling for "AI makes my posts." |
| **SwimTopia** (swim incumbent that touches money) | Swim clubs | ~$150–$699/yr annual *([`SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))* | What a club *will* pay when software is mission-critical (registration/billing) — MediaHub is not, yet. |
| **Canva Free** | Volunteer creator | **£0** | The free substitute every volunteer already has. |
| **Swim Wales affiliation** | Whole NGB relationship | £150/yr *([`SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))* | The volunteer treasurer's anchor for "what anything costs." |

Read together: the commodity floor (£0 Canva / ~$19/mo Predis) and the £150/yr NGB anchor
pull the Club tier **down**, while Gipper proves the institutional ceiling is far higher
($625–$3,000/yr) **but only for a schools/federation buyer with a budget, not a volunteer
club.** That gap is exactly why Route B (US schools) and PC.6 governing-body endorsement
carry the revenue weight, and why the Club tier must be set by revealed WTP rather than
assumed.

*Confidence: the **step** — gate the public price on ≥5 revealed annual payments before
publishing a list price — is >95%-confidence-correct; it is what a hard-nosed operator
would insist on. The **price levels themselves remain an unvalidated hypothesis** and are
flagged as such, not stated as fact. Ref: Appendix B Step 7 tiers (⚠️ unvalidated there);
[`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md).*

### PC.5 — Free-self-host tension · ✅ **RESOLVED (2026-06-09): hosted-only**
"Truly free, no hidden fees" self-host, as framed, hands power users a permanent
zero-revenue escape hatch. **Resolved 2026-06-09 (maintainer decision): hosted-SaaS
only — no customer self-host tier, free or capped.** Both earlier options — a capped
lead-gen tier (the default recommendation) and keeping true-free self-host — were
rejected in favour of hosted-only, the simplest principle that removes the zero-revenue
escape hatch entirely rather than half-closing it. The standing **no-hidden-fees /
truly-free self-host** product principle is retired; [`CLAUDE.md`](../CLAUDE.md) is the
authoritative statement. Recorded in
[adr/0011](adr/0011-commercial-reconcile-revenue-reality.md).

### PC.6 — Go-to-market / distribution · ❌ **NOT STARTED**
Distribution kills solo ventures, not product gaps. The sub-track:
- **Governing-body channel — split into two mechanisms with very different evidence (reality-checked 2026-06-09):**
  - **(a) Official data-API access — REAL, dated, the concrete first NGB action.** Swim England launched a secure **approved-systems API** (announced 1 Oct 2025) letting approved platforms read official swim times/PBs directly from its databases; initial partners are the club-admin platforms Swim Club Manager and Swim Manager, and it explicitly invites *“commercial organisations interested in benefiting from the Swim England API”* to apply, with *“more to follow in 2026”* toward a “connected digital eco-system.” Applying for approved access is high-confidence-available and strengthens the deterministic data moat + credibility — but it grants **data, not promotion.** *(>95% this step is correct/available; sourced in [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md).)*
  - **(b) Promotional NGB endorsement to hundreds of clubs — DOWN-WEIGHTED to speculative.** No evidence any NGB promotes a third-party *content* tool to its member clubs. Swim England’s partner slots are **category-exclusive and already held** (SportsEngine = “preferred technology supplier” for swim schools; GoCardless = “Official Payments Partner”); the corporate-partner tier (Speedo, Sport England, SportsHotels) is sponsorship-based and slow. So “one deal reaches hundreds of clubs” is a *possibility, not the assumed highest-leverage channel.* **Threshold: if no NGB/region will pilot or promote after ~6 months, treat it as speculative and lean on direct + word-of-mouth.** This re-weighting reinforces **Route C** — the incumbents who already hold the endorsement *and* the official data integration are the realistic distribution partners. *([adr/0012](adr/0012-ngb-distribution-channel-reality-check.md).)*
- **Hand-sell the first ~10 clubs yourself — the traction gate, designed as a warm-first sequence (expanded + evidence-banded 2026-06-09).** This is *the* Phase C exit gate, not a growth tactic, and it is now the **de-facto primary channel** after the promotional-endorsement down-weight (PC.6(b) / ADR-0012). The base rates say the gate is reached by **manufactured warmth + referral chains, not cold broadcast**:
  - **(i) Local-warm base first (Swansea / South-East Wales).** The founder is locally embedded; Swim Wales has ~80–90 affiliated clubs (~11,000 members) — a tight regional network. Warm / in-person founder-led sales convert at **~30–50%** vs **~2–5%** for cold. *Win the first ~3–5 paying clubs here, high-touch, in person.* `[Founder-led sales benchmark — ESTIMATE; warm 30–50% vs cold 2–5%.]`
  - **(ii) Referral engine on every signed club.** Coaches and volunteers know each other across county squads and meets. In SaaS, **20–50% of new customers come from referral / word-of-mouth** (≈65% of B2B new business; referred customers ~37% higher retention) — *amplified* in a community this tight. Ask each signed club for **2 named intros** to peer clubs; warm-intro close stays in the 30–50% band. *This is the mechanism that compounds 5 → 10.* `[SaaS referral benchmark — ESTIMATE.]`
  - **(iii) Meet / event presence as warmth-manufacture.** County and regional meets are where the community physically gathers; producing real branded output for host / visiting clubs turns strangers into warm leads — it is not cold outreach.
  - **(iv) Cold outreach = a capped supplement, never the path to the gate.** The public Swim England (~1,200+ clubs) and Swim Wales club directories make contacts reachable, but the honest funnel for a brand-new, unproven tool sold to a no-budget volunteer buyer is brutal: cold reply **~2–5%** × reply→meeting **~30–50%** × meeting→paid **~15–30%** ≈ **~0.3–1.0% cold-to-paid.** Reaching 10 clubs cold would need **~1,000–3,000 quality contacts** — not achievable solo at quality. *Use cold only to book a handful of discovery calls; do not plan the gate around it.* `[Blended from cold-email + founder-led benchmarks — ESTIMATE.]`
  - **Honest funnel to the gate:** ~5 local-warm + ~5 referral; cold supplements top-of-funnel only. **Realistic timeline ~3–6+ months** to 10 paying clubs given seasonal calendars, volunteer decision-making and no standing budget line (founder-led SaaS cycles run 4–8 weeks for *budgeted* buyers; volunteer clubs are slower). `[ESTIMATE — flagged, not a commitment.]`
  - **Confidence split (the >95% discipline):** the *design* — warm + referral over cold broadcast — is **>95%-confidence-correct** on the cited base rates; the *outcome* (10 paying clubs in N months at price X) is **unproven and IS the validation** (it also closes the PC.4 willingness-to-pay gap). Do not conflate the two. Sourced in [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) (Evidence refresh cycle 4).
- **Rebalance build vs. sell** — stop adding capability surface; manufacture pipeline.

**Building blocks.** Stripe (Checkout + Customer Portal + webhooks); the existing
`DATA_DIR` persistence (a `users.jsonl`-style ledger per Step 7 — no SQLAlchemy); the
shipped cross-tenant isolation invariant (ADR-0003) as the multi-tenancy seed; Postiz /
Mixpost org→workspace schemas as *reference only* over a network boundary (never embed
AGPL — [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).

**Dependencies.** Upstream of **P3 / P4 / P5** — those are gated behind PC's exit
criteria. Independent of P0–P2 capability work, which may continue *to the bar needed to
make the swim wedge sellable* (see P1.4 and "Immediate next moves") but **not ahead of
billing**.

### Strategy notes — the three credible £1M+ routes (context, *not* build items)

These are **not roadmap work** — they are the only routes the diligence considers
arithmetically credible for £1M+, recorded so the expansion phases are sequenced with
revenue in mind. Each carries the report's confidence band. **All figures are estimates.**

- **Route A — Multi-sport UK grassroots** (broadest TAM, weakest moat). ~151,000 UK
  sports clubs; even a fraction at £49–£99/mo annual reaches £1M. *Risk: per-sport data
  integrations are non-transferable engineering, head-on vs Canva/Predis. Confidence of
  £1M: ~15–20%.* → sequences **P3**.
- **Route B — US schools/colleges** (highest WTP, proven by Gipper/FanWord). Reposition
  as results-driven achievement graphics at $625–$3,000/yr. *Needs US sales presence;
  strongest math plus a wedge incumbents lack. Confidence of £1M solo: <15%; higher with
  a US partner/hire.*
- **Route C — Content/integration layer for swim-data incumbents** (de-risks
  distribution). License/sell the content engine to SwimTopia/TeamUnify rather than fight
  them. *Trades upside for survival probability; possibly the most realistic high-value
  exit. Confidence it beats going direct: ~50/50.*

**Highest-leverage combination:** governing-body **data-API access + incumbent integration (Route C)** (PC.6) for *distribution* +
US-schools repositioning (Route B) for *revenue*.

---

## Phase 3 — Broaden ingestion spokes · P3 · ❌ **NOT STARTED**

**Goal.** Ingest beyond swimming and normalise every spoke to the canonical schema,
so a second sport produces real content end-to-end.

**Exit criterion.** **≥1 non-swimming sport** produces real content end-to-end from a
real data source (football via openfootball, or basketball via nba_api), with a
registered `recognition_<sport>` adapter and its sport profile wired in.

### P3.1 — Second-sport engine adapter · ❌ **NOT STARTED**
`recognition_football` or `recognition_basketball` + `register_sport(...)` (the seam
exists — [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)). Bind `engine_sport` in the profile.

### P3.2 — Sports-data API spokes · ❌ **NOT STARTED**
`nba_api`, `openfootball`, fixture generators; each normalised to `canonical.*`.

### P3.3 — Running/athletics parsers · ❌ **NOT STARTED**
Chip-timing CSV + client-side Garmin `FIT` parsing (the swim-data-analyser pattern).
This sport needs custom parsers — open-source coverage is sparse.

### P3.4 — Normalise all spokes to the canonical schema · ❌ **NOT STARTED**
Separate raw extraction from cleaned canonical data; flag ambiguous rows for review.

**Building blocks.** `swar/nba_api` (open, keyless — *verify*), `openfootball`
(**public domain**), `ndPPPhz/Fixture-Generator` (MIT). ⚠️ `statsbomb/open-data` is a
**non-OSS data agreement** (attribution / responsible use) — code-vs-data licence
split; use openfootball as the free default. ([`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md))

**Dependencies.** Needs **P1** (sport profiles + taxonomy). Pairs with **P4** (new
sports → new audiences → more publishing targets).

---

## Phase 4 — Direct-to-platform publishing · P4 · ❌ **NOT STARTED**

**Goal.** Replace the paid Buffer dependency with direct platform adapters,
prioritising the genuinely-free targets.

**Exit criterion.** Posts publish via **direct APIs to ≥2 platforms including a
genuinely-free one** (Bluesky and/or Mastodon), with Buffer demoted to optional.

### P4.1 — Bluesky (AT Protocol) + Mastodon adapters · ❌ **NOT STARTED**
The free/open posting targets — build these first.

### P4.2 — Instagram Graph / Facebook / TikTok / YouTube adapters · ❌ **NOT STARTED**
Least-privilege per integration; human connects each account (no auto-connect).

### P4.3 — X adapter (budget pay-per-use) · ❌ **NOT STARTED**
X moved to pay-per-use (6 Feb 2026); treat as a paid, optional target.

### P4.4 — Demote Buffer to optional · ❌ **NOT STARTED**
Keep the Buffer path for those who want it; remove it from the critical path.

**Building blocks.** **Bluesky / Mastodon** (free/open) first; direct platform APIs.
**Postiz** adapters as a *reference implementation only* (**AGPL** — call over its
API or read the patterns; never embed — [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)).

**Dependencies.** Needs **P2** (autonomy + guardrails govern what may auto-publish)
and **P0** (Buffer is a flagged, optional paid path).

---

## Phase 5 — Local-AI substitution everywhere · P5 · ❌ **NOT STARTED**

**Goal.** Give every AI call a zero-cost local path, completing the no-hidden-fees
guarantee.

**Exit criterion.** With **no cloud keys configured**, the full pipeline (caption,
cutout, voice, graphics, reels) runs **locally end-to-end** — honest-erroring only
where a local model is genuinely unavailable.

### P5.1 — Ollama LLM provider · ❌ **NOT STARTED**
A local backend behind the existing `ai_core.llm` interface — the zero-key default.
*Head start from P0.4:* both LLM wrappers already accept a keyless
OpenAI-compatible endpoint (`MEDIAHUB_LLM_ENDPOINTS=http://localhost:11434/v1`
reaches a running Ollama today); what remains is shipping/operating the model
runtime itself, model selection defaults, and the operator workflow.

### P5.2 — Piper TTS replaces edge-tts · ❌ **NOT STARTED**
Local neural TTS; drops the undocumented Edge cloud-endpoint dependency. The
provider slot is already registered (P0.4: `MEDIAHUB_TTS_PROVIDER=piper`
honest-errors until this lands) — P5.2 fills the slot with the real backend.

### P5.3 — whisper.cpp / faster-whisper ASR · ❌ **NOT STARTED**
Local transcription for reel captions / word-level burn-in. Must land behind a
provider seam — the P0.4 guard fails the build on any unslotted ASR import.

### P5.4 — Satori graphics fast-path · ❌ **NOT STARTED**
Lighter card rendering (~100× lighter than headless Chromium). A *performance*
play, not a licensing one — P0.1's shipped ffmpeg engine already removed the
Remotion requirement; this slots into the same `MEDIAHUB_REEL_ENGINE` seam
(the `satori` engine name is registered and honest-errors until it ships).

### P5.5 — rembg / MODNet cutout · ✅ **DONE**
Already the shipped default (rembg). MODNet is an optional higher-quality matting
alternative.

**Building blocks.** All **ADOPT-NOW**: Ollama (MIT), Piper (MIT), whisper.cpp /
faster-whisper (MIT), Satori (MPL-2.0), rembg (MIT), MODNet (Apache-2.0). ⚠️ Avoid
Coqui **XTTS** weights commercially (CPML, non-commercial) — Piper instead.

**Dependencies.** Set up by **P0 ✅** (the local-capable interfaces all exist —
P0.4). This phase **completes the no-hidden-fees promise** the whole roadmap is
built around.

---

## Cross-cutting investments (all phases)

| Investment | Status | Notes |
|---|---|---|
| No-hidden-fees discipline | ✅ enforced | The [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md) register is now pinned by the Phase-0 guard suites (P0.3/P0.4/P0.5, 2026-06-10): every paid path stays optional with a free default, every AI surface admits a local provider, and no AGPL code can enter the process. |
| Multi-tenancy: org → workspace | ❌ **blocking** | **Prerequisite for commercial scale (PC.3), not a nice-to-have** — single-instance-per-club can't scale. Cross-tenant isolation invariant shipped (the foundation only); generalise org → per-team workspace in one shared instance. Reference Postiz/Mixpost schemas over a network boundary (never embed AGPL). |
| Go-to-market / distribution | ❌ not started | The build/sell imbalance is the #1 risk (PC.6): governing-body endorsement (Swim Wales / Swim England), annual prepay, and a deliberate build/sell rebalance. See [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md). |
| Safeguarding / minors' data | ✅ locked | Isolation invariant per [`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md); applies with extra force to autonomous post types. |
| Explainability & audit trail | 🔵 partial | Every step explainable; extend the run audit trail to autonomous-publish decisions (P2.3). |
| Product design / UI polish | ❌ | Targets: Home, Add Input, Content Pack, the autonomy controls. Flask + Jinja stay. |
| Test-suite stability | ✅ | Full suite green (2836 passed / 1 skipped after merging main). Keep green. |
| Operator deployment template | ✅ | `render.yaml` + `.env.example` canonical; one-click Render deploy works. |

---

## Immediate next moves

A recommended ordered backlog — each with its own exit criterion. (Full backlog in the
rebuild's `CHANGES`/PR.)

**Re-sequenced (2026-06 commercial reconcile).** The prior reconcile rightly put
**product quality on the swim wedge** ahead of the grand expansions. The scaling
diligence ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md))
adds the missing half: **the binding constraint is monetisation/distribution, not
capability.** So the **commercial gate (Phase C) is now #1** — ahead of *everything*,
including more graphics polish — and P3/P4/P5 are explicitly deferred behind it **and** a
*≥10 clubs paying annually* gate.

1. **Phase C — Commercialise & Distribute (🥇 top priority).** Self-serve signup + auth
   (PC.1), Stripe billing (PC.2), **true multi-tenancy** (PC.3), validated pricing with
   annual prepay (PC.4), the free-self-host call (PC.5, **resolved: hosted-only**), and GTM/distribution (PC.6).
   *Exit:* a club can sign up, pay, and publish with **zero founder involvement.**
   **Nothing below ships ahead of this.** (Update 2026-06-09: PC.1 + PC.2 shipped and live; PC.3 is the remaining engineering item but its org->workspace schema needs operator/Council sign-off — see PC.3.)
2. **P1.4 graphics — ✅ done (2026-06-10).** The full spine shipped (PR #301: Tier B
   director/pool/compliance, the gated SEQ-3 cutover with the A/B review approved, and
   the SEQ-4 video stage), all §5 acceptance criteria met — so the "sellable wedge" bar
   is cleared. **Per the standing rule: stop polishing and sell.** Anything further on
   graphics (the 12th archetype, the floor's no-photo bias, the logo-chip polish) is
   strictly behind Phase C sell-side work.
3. **P0 — ✅ done (2026-06-10).** The whole de-risk phase closed in one pass:
   the P0.1 free reel engine (still-graphics + FFmpeg behind
   `MEDIAHUB_REEL_ENGINE=ffmpeg` — a zero-license deployment renders reels),
   plus the three Phase-0 guard suites making paid-dep optionality (P0.3),
   local provider slots (P0.4) and AGPL isolation (P0.5) continuously enforced.
4. **P1.3 — Cross-source planner.** Extend `content_engine` into the three-source
   strategy brain over sport profiles. *Exit:* a ranked plan for ≥2 profiles.
5. **P2 — finish autonomy (UI + gate).** The substrate shipped in-process; what's left is
   the per-type toggle (P2.2/P2.4) + the publish gate/kill-switch (P2.3) + resolving the
   two `AutonomyLevel` enums. *Exit:* `fully_autonomous` publishes only when guardrails
   pass.

**Deferred behind the commercial gate AND "≥10 clubs paying annually":**

6. **P3 — Second sport end-to-end.** `recognition_football`/`_basketball` + a real data
   spoke. (`results_fetch/` already does sport-agnostic *ingestion*; this adds the
   per-sport *detector*.) *Gated:* no new sport until ≥10 clubs pay annually. *Exit:* one
   non-swimming sport produces content end-to-end.
7. **P4 — Free direct publishing.** Bluesky + Mastodon adapters; demote Buffer. *Exit:*
   publish to ≥2 platforms incl. one free.
8. **P5 — Local AI.** Ollama + Piper + whisper.cpp. *Exit:* full pipeline runs with no
   cloud keys.

Run a **pilot** in parallel (one real club, the themed product) to surface UX holes the
audits can't — see [`PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md). The pilot now doubles as the
first hand-sell toward the Phase C traction gate.

---

## Appendices — status & how they map to Phase 0–5

The previous roadmap revision carried three appendices of runnable build/verification
prompts. They are **retained** below as execution detail (they preserve live
`PAR-*` / `SEQ-*` / `Step N` trailer IDs and link real shipped/in-flight code), with
this lineage note:

- **Appendix A — Generative Content Engine v2.** Current. The build breakdown for
  **P1.4** above (decided in [`adr/0001-generation-engine-v2.md`](adr/0001-generation-engine-v2.md)).
  Its local `§0–§5` / `PAR-*` / `SEQ-*` numbering is self-contained.
- **Appendix B — Growth & Expansion (Steps 8–17).** ⚠️ **Legacy sequence,
  superseded.** Written against the older *Parity → Distinction → Leadership* spine.
  Its still-relevant steps are absorbed by the new phases (commercial/enterprise →
  **Phase C** — Step 7 → PC.1/PC.2/PC.4, Step 14's org→club hierarchy → PC.3; sport
  expansion → **P3**; publishing → **P4**; agentic/autonomy → **P2**).
  Where it conflicts with the new strategy, **the Phase C + 0–5 spine wins.** Retained for
  step-level execution detail only.
- **Appendix C — Adaptive Theming Engine verification.** Current. Verifies the
  **shipped** theming engine summarised under "Where we are today" (see
  [`THEMING.md`](THEMING.md)).

> **Lineage in one line:** the new **Phase 0–5** spine supersedes the old **Phase 1
> Parity → Phase 2 Distinction → Phase 3 Leadership** spine; the appendices below are
> the older revision's execution detail, kept and re-mapped, not deleted.

---

## Appendix A — Generative Content Engine v2: Build Prompts

> *Section numbers in this appendix (§0–§5) and item IDs (PAR-\*, SEQ-\*) are local to the appendix. This was previously a standalone doc; it is merged into the roadmap so there is a single reference. It is the build breakdown for §1.7 above.*

**What this is.** An execution roadmap that turns the recommendations in
`docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md` into ordered,
runnable build stages — *taking the advice in those documents as fact* — with an
implementation prompt and a verification prompt for every stage, and a separate
**parallel bucket** of work that can be run right now, simultaneously, in
different Claude sessions and merged to `main` in any order without conflicts.

**Date:** May 2026 · **Built against:** `main` after PR #137 (the trimmed
CLAUDE.md with the *gated removal process*) and PR #136 (the research docs).

**The problem being solved (from the thesis).** "Click generate" selects a tuple
from a bounded, hand-authored option space dominated by ~6 layout skeletons, with
an LLM constrained to *menu-pick* from fixed enums (`creative_brief/ai_director.py`)
and a renderer that repaints one DOM (`graphic_renderer/render.py`). The fix is to
replace the variation mechanism with: a **brand-token contract** → an **archetype
library + layout intelligence** (Tier A) → an **LLM design-spec director** (Tier B)
→ **generate-a-pool, rank, and compliance-check**, while keeping the deterministic
engine, the captions, Remotion, and the renderer substrate.

---

### 0. How to use this document

There are **two tracks**:

- **The Parallel Bucket (§2)** — additive, file-disjoint work that does **not**
  affect the build because each item ships *new, inert files* (or owns one
  isolated surface). These can be run **now**, each in its own Claude session,
  each on its own branch → PR to `main`. They are wired into the live pipeline
  later by the spine. **Run these first / concurrently.**
- **The Sequential Spine (§3)** — build-order-dependent work that modifies the
  shared files (`generator.py`, `ai_director.py`, `render.py`,
  `content_pack_visual/integration.py`, the `web.py` route) and *wires in* the
  parallel modules. These must be done in order, behind the `MEDIAHUB_GEN_V2`
  flag, and the removal stage follows CLAUDE.md's gated-removal process.

Each stage has a **Context** (what/why + files + thesis ref), an **Implementation
prompt** (paste into a fresh session), and a **Verification prompt** (paste into a
*separate* session to confirm it was done properly).

#### Relationship to the in-flight Adaptive Theming Engine (ROADMAP 1.6)

Do **not** rebuild the brand-token system. ROADMAP §1.6 already delivers the
DTCG-format `derived_palette`, ~25 MD3 role tokens, and a single-source-of-truth
JSON consumed by web/motion/email/graphic (Stage G). The thesis's "Layer 1 — brand
token contract" is **mostly that work, extended** with three generation-specific
additions (logo lockups by theme/form, type pairing, a structured voice profile,
and *semantic role descriptions an LLM can read*). SEQ-0 below extends the theming
token object; it does not duplicate it. If 1.6 Stage G is not yet merged, SEQ-0
coordinates with it rather than forking it.

---

### 1. The shared prompt preamble (every prompt inherits this)

To keep each prompt short, every Implementation and Verification prompt below
**assumes this preamble**. Paste it at the top of the session if the model hasn't
read the repo yet:

> **Preamble — read before doing anything.** You are working in the MediaHub repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md` in full, plus
> `docs/research/mediahub-generative-ai-thesis.md` (the plan) and the file(s) named
> in the task. Hard rules you must follow:
> - **Deterministic engine is off-limits to AI:** never Gemini-ify parsers
>   (`interpreter/`, `pb_discovery/`), detectors (`recognition*/`), the ranker
>   (`legacy/swim_content_v5/ranker_v3.py`), or colour-science (`theming/`,
>   CIEDE2000/APCA). You may *read* their outputs.
> - **Honest error, never a fake fallback:** if an AI provider is unavailable,
>   surface `ProviderNotConfigured`/`ClaudeUnavailableError` or fall back to a
>   *real deterministic* path — never a fabricated caption/graphic.
> - **Judgement goes through `media_ai.llm` / `ai_core.llm`** — never new hardcoded
>   heuristics for "which layout / which copy / which tone."
> - **Removing or replacing a route or data structure** requires CLAUDE.md's
>   *15-step breakage check before* + *15-step verification after* + a *dead-code
>   sweep*. Do not skip it.
> - **Tests:** run `python -m pytest tests/ -q` and add tests for new code; there
>   must be **no new failures** vs `main`, and you must not delete/skip/weaken a
>   test to go green.
> - **Branch & ship:** create a feature branch `claude/<short-name>`, commit with a
>   clear message, push, and **open a PR** (do not merge to `main` without the
>   user's approval — the user merges).
> - **Scope discipline:** touch only the files this task names. If you find you need
>   to modify a file the task says not to touch, stop and report instead.

---

### 2. The Parallel Bucket — run these now, concurrently, one session each

**Why these are safe to run simultaneously and merge in any order:** every item
below either creates **only new files** (inert — nothing imports them yet, so the
build is unaffected) or owns a **single isolated surface** that no other item and
no spine stage touches. The "Files you may touch" / "Files you must NOT touch"
lists guarantee no two parallel PRs edit the same file. Merge them to `main` in any
order; the spine (§3) wires them in afterward.

> **Conflict-safety contract (applies to every PAR item):** You may create/modify
> **only** the files listed under "Owns." You must **NOT** touch `web/web.py`,
> `creative_brief/generator.py`, `creative_brief/ai_director.py`,
> `graphic_renderer/render.py`, or `content_pack_visual/integration.py` (those are
> spine files). Your change must leave the existing build and tests green on its own.

#### PAR-1 · Caption quality pack
**Owns:** `src/mediahub/web/ai_caption.py` (the only item that touches it) + new
`src/mediahub/web/caption_examples.py` + `tests/test_caption_quality.py`.
**Context:** Captions are already strong (thesis §5.6); this adds the verified
brand-voice recipe. Independent of the graphic surgery.

**Implementation prompt:**
> [Preamble.] Extend MediaHub's caption generation (`web/ai_caption.py`) with the
> brand-voice recipe from thesis §5.6, all inside the existing Gemini→Anthropic
> path. Add: (1) **few-shot injection** — accept up to 5 of the club's own past
> captions and inject them verbatim as examples in the system prompt (store/read
> them via a new `web/caption_examples.py` keyed by `profile_id`, persisted under
> `DATA_DIR`); (2) **generate-many-then-dedupe** — generate 4–6 candidates and
> return them ranked, dropping any whose n-gram/embedding similarity to a recent
> caption or to each other is above a threshold; (3) **per-platform variants** —
> given one approved caption, produce feed / story / X / LinkedIn variants with
> per-platform length+tone constraints; (4) an explicit **AI-tell ban-list**
> ("delve", "elevate", "in the world of", reflexive "!"); (5) an **approval-loop**
> hook: a function that appends an edited+approved caption to the club's
> few-shot example store. Keep the existing function signatures working
> (additive params with defaults). Add `tests/test_caption_quality.py` covering
> dedupe, ban-list filtering, and few-shot injection (mock the LLM). Do NOT touch
> any spine file. Branch `claude/gen-par-1-captions`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-1 (caption quality pack) was done properly. Confirm:
> only `web/ai_caption.py`, `web/caption_examples.py`, and the new test were
> changed (no spine files); the existing caption route still works with the new
> defaults; few-shot examples are injected and capped at 5; dedupe actually drops
> near-duplicates; the ban-list filters the listed phrases; the approval-loop
> appends to the store; captions still raise an honest error (no fabricated
> fallback) when no provider is configured. Run the full suite — no new failures.
> Report a pass/fail checklist.

#### PAR-2 · Auto-fit text helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/autofit.py` + `tests/test_autofit.py`.
**Context:** Bannerbear's verified core feature (eval §6.1). A pure function that
computes the font-size (px) that fits a string into a given box at a given
font/weight, so long names/events never break a layout. Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/autofit.py`: a pure, deterministic helper
> `fit_font_px(text, box_w, box_h, *, font_family, weight, min_px, max_px,
> line_height) -> int` that returns the largest integer px size at which `text`
> fits within `box_w × box_h` (binary search; approximate advance-width via a
> char-width table or Pillow `ImageFont.getbbox` if a font file is available, else
> a metric heuristic — but keep it deterministic and documented). Add helpers for
> multi-line wrapping. No network, no LLM (this is layout maths, not judgement).
> Add `tests/test_autofit.py` with golden cases (short vs very long swimmer names,
> narrow vs wide boxes). Create ONLY these two files. Branch
> `claude/gen-par-2-autofit`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-2: only `graphic_renderer/autofit.py` and its test were
> added; `fit_font_px` is deterministic (same inputs → same output), monotonic
> (a longer string never returns a larger size for the same box), respects
> min/max bounds, and has no LLM/network calls. Run the suite — no new failures.

#### PAR-3 · Saliency-aware crop helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/saliency.py` + `tests/test_saliency.py`.
**Context:** Subject-aware crops (eval §6.1, thesis §5.3.1) so one archetype looks
correct and different with every photo. Deterministic maths (consistent with the
colour-science rule). Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/saliency.py`: deterministic helpers that,
> given an image path, return candidate crop rectangles for a set of target aspect
> ratios (e.g. `9:16`, `1:1`, `4:5`) using a saliency/energy heuristic (e.g.
> gradient-magnitude / edge density via Pillow+numpy, or reuse the existing cutout
> alpha if present to bias toward the subject). Expose
> `crops_for(image_path, ratios) -> dict[ratio, (x,y,w,h)]` and a
> `best_crop(image_path, ratio)`. No LLM, no network. Add `tests/test_saliency.py`
> with a couple of synthetic images (subject in different corners) asserting the
> crop tracks the subject and stays within bounds. Create ONLY these two files.
> Branch `claude/gen-par-3-saliency`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-3: only the saliency module + test were added; crops are
> deterministic, stay within image bounds, match the requested aspect ratios, and
> track the subject on the synthetic fixtures; no LLM/network. Suite green.

#### PAR-4 · Design-spec schema + validator (the Tier B contract, inert)
**Owns:** new `src/mediahub/creative_brief/design_spec.py` + `tests/test_design_spec.py`.
**Context:** The structured JSON contract the LLM art-director will emit (thesis
§5.4). Defining it as a standalone schema + normaliser now lets SEQ-2 just call it.
Inert until the director uses it.

**Implementation prompt:**
> [Preamble.] Create `creative_brief/design_spec.py` defining the `DesignSpec`
> dataclass and a strict `normalise(raw: dict, *, archetypes: list[str],
> token_roles: list[str]) -> DesignSpec` that coerces a (possibly hallucinated)
> LLM JSON object into a valid spec — every field constrained to a known enum or a
> token *role* name, with safe defaults on any out-of-vocabulary value (so a bad
> LLM response can never produce an illegal/illegible card). Fields per thesis
> §5.4: `archetype`, `colour_roles` (ground/surface/headline/accent → role names),
> `focal_element`, `crop_intent`, `hero_stat`, `secondary_stats`, `headline_hook`,
> `accent_treatment`, `logo_lockup`, `mood`, `motion_intent`, `rationale`. Provide
> the JSON-schema dict for schema-constrained decoding. No live LLM call here — this
> is the contract + validator only. Add `tests/test_design_spec.py` (valid spec
> round-trips; hallucinated/garbage values normalise to defaults; enums enforced).
> Create ONLY these two files. Branch `claude/gen-par-4-design-spec`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-4: only the design_spec module + test were added; an
> out-of-vocabulary value for every field normalises to a safe default; the schema
> dict matches the dataclass; no card-illegal spec can be produced. Suite green.

#### PAR-5 · Variant metrics module (success-metric instrumentation, inert)
**Owns:** new `src/mediahub/quality/variant_metrics.py` + `tests/test_variant_metrics.py`.
**Context:** Thesis §8C success metrics — archetype diversity and perceptual
distance across a candidate pool. Standalone scoring lib; inert until SEQ-2 wires it.

**Implementation prompt:**
> [Preamble.] Create a new `quality/` package with `variant_metrics.py`:
> deterministic functions `archetype_diversity(specs) -> float` (distinct
> archetypes / candidates) and `perceptual_spread(png_paths) -> float` (mean
> pairwise distance using a cheap perceptual hash or downscaled-LAB histogram
> distance — no heavy ML). Add `caption_repetition(captions) -> float` (max n-gram
> overlap). These power the §8C targets. No LLM/network. Add
> `tests/test_variant_metrics.py`. Create ONLY the new package files + test.
> Branch `claude/gen-par-5-metrics`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-5: only the new `quality/` module + test were added;
> metrics are deterministic and bounded; diversity rises with distinct archetypes;
> spread rises with visually different PNGs. Suite green.

#### PAR-6 · Brand bootstrap extractor (draft from a URL, inert)
**Owns:** new `src/mediahub/brand/bootstrap_extract.py` + `tests/test_bootstrap_extract.py`.
**Context:** "Paste your club URL → draft brand kit" onboarding (thesis §5.3),
modelled on Brandfetch's schema. A pure extractor that returns a **draft**
DesignTokens dict (for human confirmation — never auto-trusted). It may *read* the
existing `brand/link_handlers/` but must not modify them or add a route (wiring is
SEQ work). Inert until onboarding calls it.

**Implementation prompt:**
> [Preamble.] Create `brand/bootstrap_extract.py`: `extract_brand_draft(url) ->
> dict` returning a *draft* token set (palette candidates with semantic guesses,
> logo URLs by inferred form, font guesses) shaped like the DesignTokens contract,
> reusing existing `brand/link_handlers/` for fetching where possible (read-only
> import). Mark every field `"confirmed": false`. No route, no web.py edit, no
> auto-apply. Honest about uncertainty (small-club extraction is unreliable — return
> confidence flags, never silently guess). Add `tests/test_bootstrap_extract.py`
> (mock the fetch; assert draft shape + all `confirmed:false`). Create ONLY these
> two files. Branch `claude/gen-par-6-brand-bootstrap`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-6: only the extractor + test were added; no route/web.py
> change; output is a draft (all `confirmed:false`), shaped like DesignTokens; the
> existing `link_handlers` were imported, not modified. Suite green.

#### PAR-7 · Archetype templates (the fan-out item — one session per archetype)
**Owns (per session):** ONE new file `src/mediahub/graphic_renderer/layouts/v2/<name>.html`
(+ optional `<name>.notes.md`). Run this prompt N times in N sessions, once per
archetype name — each writes a *different* file, so they never conflict.
**Context:** The structural variety the 6 families lack (thesis §5.3.1). Author
each against the **slot convention** below so SEQ-1 can wire them uniformly.

**Slot convention (author against this exactly):** use `{{PLACEHOLDER}}` string
substitution (not Jinja), and reference brand colours **only** via CSS custom
properties (`var(--mh-primary)`, `var(--mh-on-primary)`, `var(--mh-surface)`,
`var(--mh-on-surface)`, `var(--mh-accent)`, `var(--mh-outline)`) — never hardcode a
hex. Available text placeholders: `{{ATHLETE_FULL_NAME}}`, `{{ATHLETE_FIRST_NAME}}`,
`{{ATHLETE_SURNAME_DISPLAY}}`, `{{EVENT_NAME}}`, `{{RESULT_VALUE}}`,
`{{ACHIEVEMENT_LABEL}}`, `{{MEET_NAME}}`, `{{CLUB_FULL}}`, `{{HERO_STAT}}`,
`{{LOGO_BLOCK}}`, `{{ATHLETE_IMG_BLOCK}}`, `{{ACCENT_DECORATION}}`,
`{{SPONSOR_BLOCK}}`. Canvas is `{{WIDTH}}×{{HEIGHT}}`. Include `{{BASE_CSS}}` at the
top. The archetype must read *structurally distinct* from `individual_hero` /
`big_number_hero` at a glance.

**Suggested archetype names (assign one per session):** `split_diagonal_hero`,
`full_bleed_photo_lower_third`, `editorial_numbers_grid`, `centered_medal_spotlight`,
`magazine_cover`, `ticker_strip`, `stat_stack_sidebar`, `triptych_progression`,
`quote_led_recap`, `big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`.

**Progress (PAR-7 catalog):** ✅ **12 of 12 archetypes live — catalog complete** (`duo_athlete_split` added 2026-06-09: a matchday duel poster — the canvas bisected into two equal vertical halves by a hard accent seam, photo bay vs brand data bay, crossed by the one full-width name band that bridges the seam). Representative seeds-0..9 pack archetype-diversity saturated at **1.00**; new archetype nearest-neighbour dHash **0.355** sits above the contemporaneously re-measured pre-existing library floor (**0.285**) so the floor is unchanged (genuine new structure, not a reskin). Every archetype now ships a `.notes.md` director catalog entry (test-enforced). The verification pass also fixed two renderer-wide typography defects (self-hosted fonts never loaded — `set_content` blocked `file://` woff2 fetches; Anton autofit under-measurement clipping long surnames) — see `docs/build_reports/GEN_QUALITY_BASELINE.md`.

**Implementation prompt (template — fill in `<NAME>`):**
> [Preamble.] Author ONE new graphic archetype `graphic_renderer/layouts/v2/<NAME>.html`
> following the slot convention in `docs/ROADMAP.md` (Appendix A → PAR-7)
> exactly (CSS-variable colours only, the listed `{{PLACEHOLDERS}}`, `{{BASE_CSS}}`
> at top). It must be a *structurally distinct* portrait layout (1080×1350 and
> 1080×1920 must both read well) — a genuinely different composition from the
> existing families, not a reskin. Self-contained HTML/CSS; no JS, no network, no
> hex literals. Add a one-paragraph `<NAME>.notes.md` describing the composition and
> when the director should pick it. Create ONLY those file(s) under `layouts/v2/`.
> Do not touch `render.py` or any other file. Branch `claude/gen-par-7-<NAME>`,
> commit, open a PR. (You cannot fully render-test it until SEQ-1 wires `layouts/v2`;
> instead, validate the HTML is well-formed and every placeholder/variable matches
> the convention.)

**Verification prompt:**
> [Preamble.] Verify a PAR-7 archetype: exactly one new `layouts/v2/<NAME>.html`
> (+ notes) was added; it uses ONLY CSS-variable colours (grep for `#` hex literals
> → none in colour positions); every placeholder is on the §PAR-7 allow-list;
> `{{BASE_CSS}}` is present; the layout is structurally distinct from the existing
> families; no other file changed. Suite green (these files are inert, so the suite
> is unaffected — confirm that too).

#### PAR-8 · Documentation + ADR (pure docs, inert)
**Owns:** new `docs/GENERATION.md` + `docs/adr/0001-generation-engine-v2.md`.
**Context:** Single canonical doc for the new engine + an architecture-decision
record. Pure docs; conflicts with nothing.

**Implementation prompt:**
> [Preamble.] Author `docs/GENERATION.md` documenting the v2 generation
> architecture from thesis §5 (the token contract, archetype library, design-spec
> director, pool/rank/compliance, captions, video), the `layouts/v2` slot
> convention (copy it from this roadmap §PAR-7), and the `MEDIAHUB_GEN_V2` flag.
> Also author `docs/adr/0001-generation-engine-v2.md` recording the decision to
> replace the enum-permutation/menu-picker engine with the design-spec director
> (context, decision, alternatives rejected per thesis §4A, consequences). Docs
> only. Branch `claude/gen-par-8-docs`, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-8: only the two docs were added; `GENERATION.md` matches
> thesis §5 and the §PAR-7 slot convention; the ADR records context/decision/
> alternatives/consequences. No code changed.

---

### 3. The Sequential Spine — build in order, behind `MEDIAHUB_GEN_V2`

These stages modify the shared spine files and wire in the parallel modules. They
**cannot** run concurrently with each other (they touch the same files); run them
in order, each as its own PR, after the parallel bucket is merged. Everything that
changes live behaviour is gated by the `MEDIAHUB_GEN_V2` feature flag until SEQ-3's
cutover, so production never regresses.

#### SEQ-0 · DesignTokens contract + feature-flag scaffolding · ✅ **DONE**
**Depends on:** ROADMAP §1.6 Stage G (DTCG `derived_palette` JSON) if merged; else
coordinate. **Touches:** `brand/kit.py`, a new `config`/flag read, `theming/` (read).
**Thesis ref:** §5.3.

**Implementation prompt:**
> [Preamble.] Extend the brand token object (`brand/kit.py` / the theming
> `derived_palette`) into the generation **DesignTokens contract** from thesis §5.3,
> *additively* — keep the existing flat `primary_colour`/`secondary_colour`/
> `accent_colour` as derived aliases so nothing breaks. Add: semantic colour
> **roles** with `brightness` + `when_to_use` text (reuse the existing APCA/ΔE2000
> numbers from `theming/`), **logo lockups** typed by `form`
> (icon/horizontal/stacked/mono) and `theme` (light/dark) — extend
> `theming/logo_chip.py` to *select* the lockup for a given background — a typed
> `type` pairing, and a structured `voice` profile (examples, banned phrases, emoji
> policy) that the caption store (PAR-1) can populate. Add a `MEDIAHUB_GEN_V2`
> feature flag read (env, default off) and a single helper
> `resolve_design_tokens(profile_id) -> dict` that returns the full contract with
> the semantic role descriptions an LLM can consume. No behaviour change yet (flag
> off). This is additive — the gated-removal process is NOT needed here. Add tests
> for `resolve_design_tokens`. Branch `claude/gen-seq-0-tokens`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-0: the old flat BrandKit fields still resolve (back-compat
> alias); `resolve_design_tokens` returns roles with `brightness`+`when_to_use`,
> logo lockups by form/theme, type pairing, and a voice profile; `logo_chip` selects
> a lockup per background; the `MEDIAHUB_GEN_V2` flag exists and defaults off; old
> persisted profiles still load. Suite green (no new failures); the change is purely
> additive (no removals).

#### SEQ-1 · Tier A — archetype library + layout intelligence (the immediate fix) · ✅ **DONE**
**Depends on:** SEQ-0, PAR-2 (autofit), PAR-3 (saliency), PAR-7 (archetypes),
optionally PAR-6. **Touches:** `graphic_renderer/render.py`,
`creative_brief/generator.py`, `legacy/swim_content_v5/ranker_v3.py` (read-only
addition). **Thesis ref:** §5.3.1. **This stage alone is expected to fix "samey."**

**Implementation prompt:**
> [Preamble.] Implement Tier A (thesis §5.3.1), gated behind `MEDIAHUB_GEN_V2`.
> (1) Teach `graphic_renderer/render.py` to load archetypes from
> `graphic_renderer/layouts/v2/*.html` (the PAR-7 files) using the documented slot
> convention, resolving colours from the DesignTokens roles (SEQ-0) as CSS
> variables. (2) Wire in `autofit.fit_font_px` (PAR-2) for headline/name/event
> slots so long strings never overflow. (3) Wire in `saliency.best_crop` (PAR-3) so
> the athlete photo is cropped per the archetype's `crop_intent`. (4) In
> `creative_brief/generator.py`, add a **deterministic archetype-picker** (seeded by
> the existing `auto_variation_seed_for`, stable per card, different across cards)
> that selects among the v2 archetypes — this is the no-AI fallback floor. (5)
> Expose, *read-only*, the ranker's ranked **emphasis angles** (lead with time / PB
> delta / placing / relay split) so the brief can vary the hero stat — do NOT change
> the ranker's scoring. With the flag ON, a content pack should use ≥6 distinct
> archetypes. Add tests asserting archetype diversity across a pack and that autofit
> prevents overflow. Branch `claude/gen-seq-1-tier-a`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-1: with `MEDIAHUB_GEN_V2=1`, rendering a pack uses ≥6
> distinct v2 archetypes; with the flag OFF, behaviour is unchanged (old engine).
> Long swimmer names/events no longer overflow (autofit); photo crops track the
> subject (saliency); the ranker's *scoring is byte-identical* to before (only a
> read-only emphasis-angle accessor was added — confirm no PB/ranking regression per
> CLAUDE.md engine rule). Walk upload→process→review with the flag on; cards render,
> captions/confidence intact. Suite green. Report the archetype-diversity number.

#### SEQ-2 · Tier B — design-spec director + pool, rank, compliance · ✅ **DONE**
**Depends on:** SEQ-1, PAR-4 (design_spec), PAR-5 (variant_metrics). **Touches:**
`creative_brief/ai_director.py`, `content_pack_visual/integration.py`,
`web/web.py` (the create-graphic route response). **Thesis ref:** §5.4–5.5.

**Implementation prompt:**
> [Preamble.] Implement Tier B (thesis §5.4–5.5), gated behind `MEDIAHUB_GEN_V2`.
> (1) Rewrite `ai_director.ai_creative_direction` to emit a **DesignSpec** (use
> `creative_brief/design_spec.py` from PAR-4) under JSON-schema-constrained decoding
> via `ai_core` — the LLM now chooses archetype, colour-role assignment, focal
> element, hero stat (from the ranker's emphasis list), generated hook, crop intent,
> accent, logo lockup, mood, and a `rationale` (which feeds the existing "why this
> design" explainability). Keep the SEQ-1 deterministic archetype-picker as the
> fallback floor when no provider is configured (honest error / real floor — never a
> fabricated card). (2) In `content_pack_visual/integration.py`, emit **N candidate
> specs** (default 5), render the pool (cheap — Playwright), run a **deterministic
> brand-compliance check** (APCA/ΔE2000 contrast, correct logo lockup for the
> background, sponsor-safe zones) that attaches an explainable score to each, score
> diversity with `quality/variant_metrics.py` (PAR-5), rank with the existing ranker,
> and return a **ranked shortlist**. (3) Extend the create-graphic route response in
> `web/web.py` to return the shortlist + per-candidate compliance score (additive
> JSON; keep the old single-visual fields populated from the top candidate so
> existing callers keep working). This stage *replaces* the menu-picker prompt — but
> the old `random_variation_profile`/enum path stays in place as the flag-off route
> until SEQ-3, so this is still additive at the route level. Add tests for spec
> emission (mock LLM), normalisation of a bad LLM response to a legal card, and the
> compliance score. Branch `claude/gen-seq-2-tier-b`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-2: with the flag on, the director emits a schema-valid
> DesignSpec; a deliberately malformed LLM response still yields a legal, legible
> card (PAR-4 normalisation); the pipeline returns a ranked shortlist of ≥4
> structurally distinct candidates each with a compliance score; the top candidate
> populates the legacy single-visual response fields (old callers unaffected); with
> no provider configured it falls back to the deterministic archetype floor (no
> fabricated output). Flag OFF = old behaviour. Suite green. Confirm no spine file
> outside the three named was touched.

#### SEQ-3 · Cutover + gated removal of the dead engine (the "full removal") · ✅ **DONE**
**Depends on:** SEQ-2 proven (A/B beats the old engine in review + suite green).
**Touches (removals):** `creative_brief/generator.py`,
`creative_brief/ai_director.py`. **Thesis ref:** §5.1, §7 cutover. **This is a
route/data-structure-adjacent removal — follow CLAUDE.md's gated process exactly.**

**Implementation prompt:**
> [Preamble.] Cut over to v2 and remove the dead variation engine — this is a
> deliberate replacement, so you MUST run CLAUDE.md's **15-step breakage check
> (Section A) before** touching anything, write the breakage list, then remove and
> run the **15-step verification (Section B) after**, then the **dead-code sweep
> (Section C)**. Steps: (1) flip `MEDIAHUB_GEN_V2` default to ON. (2) Remove the
> now-dead enum-permutation path: `random_variation_profile`, `_legacy_axes_from_seed`,
> `_PHRASE_TABLES`/`_phrase_for_seed`, and the closed-vocabulary menu-picker
> `_system_prompt` in `ai_director.py`; demote `BACKGROUND_STYLES`/`ACCENT_STYLES`/
> `TYPOGRAPHY_PAIRS`/`COMPOSITIONS`/`PHOTO_TREATMENTS` to renderer-internal building
> blocks only if still needed, else remove. (3) Keep the deterministic archetype
> floor. (4) Migrate or tolerate old persisted briefs/`variation_signature` fields
> (decide explicitly per breakage step 13). Do NOT remove the route or the
> `CreativeBrief` dataclass (extend, don't delete — production depends on them).
> Provide the completed A-list, B-list, and dead-code sweep in the PR description.
> Branch `claude/gen-seq-3-cutover`, run the full suite (no new failures, no
> weakened tests), PR.

**Verification prompt:**
> [Preamble.] Independently re-run CLAUDE.md Section B (15-step safe-removal
> verification) against SEQ-3: zero stray refs to the removed symbols (whole-repo
> grep); imports resolve; full suite green with no deleted/skipped/weakened tests;
> the create-graphic route + templates still work; old persisted runs still load (or
> are migrated); engine accuracy (PB detection, ranking) byte-identical; no new
> debug/IDOR exposure, no `ANTHROPIC_API_KEY` leak; diff contains only intended
> edits; dead-code sweep actually happened (no orphaned helpers, `_unused` vars, or
> "removed" placeholder comments). Report the checklist with pass/fail per step.

#### SEQ-4 · Video — data-driven scene structure (+ optional Tier C) · ✅ **DONE**
**Depends on:** SEQ-1/2 (the richer brief). **Touches:** `visual/motion.py`,
`remotion/src/compositions/`, optionally `visual/ai_background.py`. **Thesis ref:**
§5.7.

**Implementation prompt:**
> [Preamble.] Enrich video (thesis §5.7). (1) The richer brief (archetype, hero
> stat, tokens) already flows into `visual/motion.py` props — extend the Remotion
> compositions in `remotion/src/compositions/` to honour the archetype/emphasis so
> the reel's *look* matches the still. (2) Add **data-driven scene structure**: a
> multi-PB weekend produces a structurally different reel (variable
> `durationInFrames`/scene count derived from the number of ranked moments) than a
> single medal — the thing template tools can't do and Remotion can. (3) **Optional,
> behind its own flag** (`MEDIAHUB_GEN_BG`, default off): activate the dormant
> `visual/ai_background.py` hook (already imported at `render.py`) via a
> commercial-safe API (Bria/Recraft) for **backgrounds only**, composited under the
> deterministic text, with the existing contrast guardrails — never the data layer.
> Keep cache-by-content-hash behaviour. Add tests for variable scene count. Branch
> `claude/gen-seq-4-video`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-4: reel scene count varies with the number of ranked
> moments; the reel look matches the still archetype; cache-by-hash still works;
> the optional generative-background path is OFF by default and, when on, only
> affects the background (data text stays deterministic and legible). Suite green.

---

### 4. Dependency graph & sequencing

```
RUN NOW, CONCURRENTLY (each its own session → PR to main, any merge order):
  PAR-1 captions      PAR-2 autofit     PAR-3 saliency    PAR-4 design-spec
  PAR-5 metrics       PAR-6 bootstrap   PAR-7 archetypes×N PAR-8 docs
        (all additive/inert or single-surface — no shared-file conflicts)
                              │
                              ▼
THEN, IN ORDER (each its own PR; gated by MEDIAHUB_GEN_V2):
  SEQ-0 tokens ─▶ SEQ-1 Tier A ─▶ SEQ-2 Tier B ─▶ SEQ-3 cutover+removal ─▶ SEQ-4 video
  (SEQ-0 also coordinates with ROADMAP §1.6 Stage G if not yet merged)
```

**Wiring map (which spine stage consumes which parallel module):**

| Parallel module | Wired in by | Until then it is |
|---|---|---|
| PAR-2 autofit, PAR-3 saliency, PAR-7 archetypes | SEQ-1 | inert new files |
| PAR-4 design-spec, PAR-5 metrics | SEQ-2 | inert new files |
| PAR-6 brand bootstrap | SEQ-0 onboarding (or later) | inert new file |
| PAR-1 captions | already live (own surface) | shipped independently |
| PAR-8 docs | n/a | docs |

**The fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (in parallel now) →
SEQ-0 → SEQ-1. That delivers Tier A — deterministic, brand-safe, ~$0 marginal cost
— which the thesis expects to resolve the complaint on its own, before any
LLM-director work (SEQ-2).

---

### 5. Acceptance criteria (from thesis §8C)

The overhaul is "done" when, with `MEDIAHUB_GEN_V2` on:

1. **Structural distinctiveness:** a 10-card pack uses ≥6 distinct archetypes; a
   5-candidate pool for one card spans ≥4 archetypes (today ~1–2). Measured by
   `quality/variant_metrics.py` (PAR-5).
2. **On-brand fidelity:** the deterministic compliance check passes ≥99% of shipped
   candidates; off-brand candidates are caught before a human sees them.
3. **Caption non-repetition:** consecutive captions for a card are below the overlap
   threshold; zero ban-list phrases ship.
4. **Human-acceptance rate** (approved without manual redesign) rises vs the old
   engine in the review-UI A/B.
5. **Cost & latency:** marginal API cost/pack < ~$0.50 (Tier A+B); cold render
   within today's 30–90s; cache-hit behaviour preserved.
6. **No moat regression:** rendered data accuracy stays 100% (deterministic), and
   every card keeps its "why this card / why this design" explanation.
7. **Suite green** throughout (no new failures, no weakened tests), and SEQ-3's
   gated-removal checklists are completed and recorded.

---

*Derived from `docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md`, against `main` after
PR #137. Run the Parallel Bucket (§2) now in separate sessions; then walk the
Sequential Spine (§3) in order.*



---

## Appendix B — Growth & Expansion: Build Prompts (not yet done)

> *Runnable implementation + verification prompts for the Phase 2/3 growth work (commercial, sport expansion, athlete surfaces, integrations, enterprise, agentic editing, marketplace, sponsor-side). The earlier steps (brand DNA, voice imitation, visible intelligence, output expansion, turn-into, publishing) are already shipped and are intentionally omitted. Step/Phase numbers below are local to this appendix.*

#### Step 7: Commercial Layer — Stripe, Tiers, Self-Serve Signup

##### Context
MediaHub has no commercial layer today. The plan is to ship public pricing, self-serve signup, and a free tier alongside Phase 1's product improvements so commercial pressure surfaces during iteration.

> ⚠️ **Promoted & repriced (2026-06 reconcile).** This step is no longer "alongside
> Phase 1" — it is the front-of-queue **Phase C** (signup → **PC.1**, Stripe → **PC.2**,
> tiers/pricing → **PC.4**). The scaling diligence
> ([`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md)) makes
> it the **top priority**, ahead of expansion. **The `Free / Club £30/mo / Federation
> £250/mo` figures in the prompt below are ⚠️ unvalidated and too low** — candidate
> repricing: **Club £49–£99/mo billed annually, Federation £250+/mo**, with **annual
> prepay** (SMB/volunteer churn is 3–7%/mo; annual billing cuts it ~30–40%). Treat the
> code-block prompt below as legacy execution detail; Phase C and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md)
> are the current source of truth.

##### Implementation Prompt

```
Add a commercial layer: signup, Stripe billing, three tiers.

GOAL: a new user can land on /, click "Get started", create an account
with email + password, choose a plan (Free / Club £30/mo / Federation
£250/mo), pay via Stripe Checkout, and start using MediaHub on the
hosted service.

FILES TO MODIFY:
- NEW src/mediahub/web/auth.py: minimal email+password auth (use
  passlib bcrypt; sessions via Flask's session cookie with a
  signed secret).
- NEW src/mediahub/web/billing.py: Stripe Checkout session creation,
  webhook handler for subscription events.
- src/mediahub/web/web.py:
  - new GET/POST /signup, /login, /logout
  - new GET /pricing (3-tier table)
  - new GET /billing (current plan, manage subscription via Stripe
    Customer Portal)
  - new POST /webhooks/stripe (verify signature, update subscription
    status)
  - guard premium features (multi-club, enterprise tools — to be
    added in Phase 3) behind a plan check; existing features remain
    open on Free.
- DB: extend the existing DATA_DIR storage with a users.jsonl ledger
  (email, hashed_password, plan, stripe_customer_id, created_at).
  Do not introduce SQLAlchemy.
- environment: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION.
- Free tier limits: 3 runs/month, single brand profile, no Buffer
  scheduling. Soft limit (a banner) — never lock the user out
  permanently on free.

ACCEPTANCE CRITERIA:
- /signup creates a user, hashes the password, logs them in.
- /pricing shows the three tiers with feature lists.
- "Upgrade" buttons start a Stripe Checkout flow (use Stripe test
  mode keys for dev).
- A successful Stripe Checkout webhook updates the user's plan.
- /billing lets the user manage their subscription via Stripe Customer
  Portal.
- Self-hosted deployments (no STRIPE_SECRET_KEY env) continue to
  work — auth is optional, billing routes return 503 with a clear
  "billing is not configured for this deployment" message.

DON'T BREAK:
- Any existing route that was open is still open if no STRIPE_*
  env vars are configured.
- pytest at 253+.
- The Stop hook git push flow continues to work.

TESTS:
- tests/test_auth.py: signup, login, logout, password hashing.
- tests/test_billing.py (mocked Stripe): webhook verification,
  subscription update flow.

```

##### Verification Prompt

```
Verify Step 7 (Commercial layer) end-to-end.

1. Tests: full pytest + tests/test_auth.py + tests/test_billing.py -v.

2. Self-hosted-without-billing path:
   - With STRIPE_SECRET_KEY unset, boot the app.
   - GET /, /add-input, /upload, /organisation, /settings — all 200.
   - GET /pricing and /billing — 200 (show "billing not configured").
   - All caption / motion / Turn-Into routes work as before.

3. Signup / login flow:
   - POST /signup with a fresh email + 12-char password. Confirm
     redirect to /add-input + a session cookie.
   - Log out. Log back in. Confirm session restored.
   - Submit a wrong password. Confirm a clear error, not a 500.
   - Confirm passwords in users.jsonl are bcrypt hashes (not plain).

4. Stripe-mode (test keys):
   - Set STRIPE_SECRET_KEY, STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION
     to Stripe test values.
   - Hit /pricing. Click "Upgrade to Club".
   - Confirm a Stripe Checkout session URL is returned and the test
     mode page renders (open in browser, fill 4242 4242 4242 4242).
   - Complete checkout. Confirm the webhook handler updates the
     user's plan in users.jsonl to "club".

5. Free tier soft limit:
   - On a Free account, create 3 runs. Create a 4th. Confirm a banner
     appears (NOT a hard lock).

6. Buffer scheduling guarded:
   - On Free, the Schedule button must show "Upgrade to schedule
     posts" instead of opening the modal.

7. Security checks:
   - Try to access /billing without a session. Confirm redirect to
     /login.
   - Inspect the session cookie — must be HttpOnly + Secure (when
     served via HTTPS) and signed.
   - Grep the codebase for STRIPE_SECRET_KEY — must only appear in
     billing.py and never logged.

8. Regression sweep: all features from Steps 1-6 still work.

OUTPUT: single report.
```

---

### Phase 2 — Distinction (Steps 8-12, target months 3-9)

#### Step 8: Sport Expansion — Athletics (Track and Field)

##### Context
MediaHub today is swimming-only. Athletics is the natural second sport — overlapping audience (school athletic programmes, multi-sport clubs), similar result-file structure (event, time/distance, place), but a different event vocabulary and a different PB taxonomy.

##### Implementation Prompt

```
Add athletics (track and field) as MediaHub's second sport.

GOAL: a user can upload an athletics result file (CSV or Hytek-format
.txt) on /upload, MediaHub recognises athletes, computes PBs, ranks
achievements, and produces a content pack with athletics-appropriate
language.

FILES TO MODIFY:
- NEW src/mediahub/sports/: refactor the sport-specific bits of the
  existing pipeline out of swimming-implicit code paths. Each sport
  should have:
    sports/<sport>/events.py — canonical event vocabulary
    sports/<sport>/parser.py — result-file parsers
    sports/<sport>/pb_logic.py — PB and record detection
    sports/<sport>/templates.py — celebratory phrase patterns
- src/mediahub/sports/__init__.py: register a SPORTS dict and a
  pick_sport(file_bytes, hint) -> SportModule selector.
- src/mediahub/sports/swimming/: move existing swimming code here
  (preserve all behaviour and tests).
- src/mediahub/sports/athletics/: new athletics implementation.
  Event vocabulary: 100m, 200m, 400m, 800m, 1500m, 3000m, 5000m,
  10000m, hurdles (60m/100m/110m/400m), steeplechase, all field
  events (LJ, TJ, HJ, PV, SP, DT, HT, JT), relays. Distinguish
  TRACK (time-based) from FIELD (distance/height-based) for PB
  comparison logic.
- src/mediahub/web/web.py /upload: detect sport from filename and
  content; allow user to override via a sport dropdown.
- ClubProfile: add primary_sport field; default to "swimming" for
  backward compatibility.

ACCEPTANCE CRITERIA:
- Uploading an athletics result file produces an athletics-specific
  content pack with phrases like "smashed a PB" appropriate to track
  ("ran a personal best") and field ("threw a personal best").
- A field PB is correctly detected (higher = better) vs track PB
  (lower = better).
- All swimming tests still pass — no regression.
- Adding a third sport in future is a matter of creating a new
  sports/<sport>/ subpackage, no refactoring of the platform code.

DON'T BREAK:
- Every existing swimming test (interpreter, recognition, corpus,
  visual, caption) still passes.
- pytest at 253+ (new athletics tests added).
- All Phase 1 features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion, Buffer publishing) work for athletics output.

TESTS:
- tests/test_athletics_parser.py: parse a sample athletics CSV,
  verify event detection.
- tests/test_athletics_pb_logic.py: field PB (higher = better) and
  track PB (lower = better) are correctly classified.
- tests/test_sports_registry.py: pick_sport routes correctly.

```

##### Verification Prompt

```
Verify Step 8 (Athletics support) end-to-end with no swimming regression.

1. Tests:
   - python -m pytest tests/ -q. Must be 253+ plus the new athletics
     tests (target 260+).
   - python -m pytest tests/test_athletics_*.py
     tests/test_sports_registry.py -v.

2. Swimming regression:
   - Upload an existing swimming sample file. Confirm the content pack
     is identical in structure to pre-Step-8 behaviour.
   - All four caption tones generate; visible intelligence shows PB
     reasoning; Turn-Into produces 6-7 artefacts; motion renders.
   - tests/test_interpreter_smoke.py, tests/test_pb_discovery.py,
     tests/test_corpus_recovery.py — all pass.

3. Athletics happy path:
   - Upload a sample athletics CSV. Confirm sport detection routes
     to athletics.
   - Confirm event names include 100m, 800m, LJ, TJ, etc.
   - Confirm PB logic: a long jump of 6.45m beats a previous 6.30m
     (higher = better); a 100m time of 11.40 beats 11.50 (lower = better).
   - Confirm captions use athletics-appropriate language ("ran a
     PB in the 800m" not "swam a PB").

4. Sport switching:
   - Manually override sport from swimming → athletics on the /upload
     page. Confirm the override takes effect.

5. Module structure:
   - ls src/mediahub/sports/ — confirms swimming/ and athletics/
     subpackages.
   - python -c "from mediahub.sports import SPORTS, pick_sport;
     print(list(SPORTS.keys()))"
     — confirms both sports registered.

6. Regression sweep on Phase 1:
   - All 7 Phase 1 steps' features still work (sample one feature
     from each).

OUTPUT: single report.
```

---

#### Step 9: Athlete-Facing Micro-Surfaces

##### Context
Greenfly routes content from a league to athletes for personal sharing. For MediaHub the parallel is letting a swimmer/athlete receive their own personal share-ready cards via a private link, which they post to their own channels. This expands distribution beyond the club account.

##### Implementation Prompt

```
Add athlete-facing micro-surfaces for personal sharing.

GOAL: each swimmer/athlete in a run can be given a personal,
unlisted link to a page that shows their cards for that meet plus
their season-to-date highlights, with a "Share to Instagram" / "Save
to camera roll" affordance per card. No login required for the
swimmer.

FILES TO MODIFY:
- src/mediahub/athlete_pages/: new module.
- Token: per-athlete unlisted token = HMAC(server_secret, run_id +
  athlete_id), 24 chars base32. Stored in run JSON.
- src/mediahub/web/web.py:
  - new GET /a/<token> — renders the athlete page. No auth required.
  - new GET /a/<token>/card/<card_id>/share — returns the card as a
    direct-download image for the athlete to save and post.
  - new POST /api/runs/<run_id>/athlete-tokens — admin route on the
    review page: generate or revoke tokens for athletes in the run.
- Review page: "Send to athlete" button on each card; clicking copies
  the personal share link (or opens a QR code modal for in-person
  hand-off).
- Privacy: the athlete page MUST NOT show any other swimmer's data,
  the original results file, or any club admin surface.

ACCEPTANCE CRITERIA:
- An athlete with a token can see only their own cards.
- The link is unguessable (HMAC + secret rotation).
- An admin can revoke a token; revoked tokens render a "this link has
  been revoked" page.
- Share affordances work on mobile: tapping "Save to camera roll" on
  iOS Safari triggers a long-press save flow; on Android, a direct
  download.
- Page renders correctly on screens 320px wide (smallest common mobile).

DON'T BREAK:
- All earlier features still work.
- Privacy: no PII leakage from athlete page to the rest of the
  system. Specifically: an athlete cannot enumerate other tokens.

TESTS:
- tests/test_athlete_pages.py: token generation determinism, HMAC
  verification, revoked-token handling, isolation between athletes.

```

##### Verification Prompt

```
Verify Step 9 (Athlete pages) end-to-end.

1. Tests: full pytest + tests/test_athlete_pages.py -v.

2. Happy path:
   - On an existing run, generate a token for athlete A and athlete B.
   - GET /a/<token_A> — confirm 200, shows only A's cards.
   - GET /a/<token_B> — confirm 200, shows only B's cards.
   - Try GET /a/<token_A> with one character changed — confirm 404,
     NOT a leak of the original page.

3. Isolation:
   - On A's page, the response body must NOT contain B's swimmer_name.
   - The page must NOT contain the path to the results file.

4. Revocation:
   - Revoke A's token. Re-fetch /a/<token_A> — confirm a clear
     "revoked" page, status 410 or 200 with a message.

5. Mobile rendering:
   - Open /a/<token_A> in a 360x800 viewport. Screenshot.
   - Confirm cards fit, text is readable, the share buttons are
     thumb-sized (≥44px).

6. Share affordance:
   - GET /a/<token>/card/<card_id>/share — must return an image with
     Content-Disposition: attachment.

7. Regression sweep: all Phase 1 + Step 8 features still work.

OUTPUT: single report.
```

---

#### Step 10: Sponsor-Aware Generation

##### Context
Sponsors are a primary revenue driver for clubs and the buyer's biggest stakeholder. A sponsor-aware product variant of every output type — caption with sponsor mention, graphic with sponsor logo, newsletter section with sponsor block — turns MediaHub into a sponsorship-value-realisation tool.

##### Implementation Prompt

```
Make every output type sponsor-aware.

GOAL: when ClubProfile has sponsor_name + sponsor_guidelines set,
every generated caption, graphic, motion, reel, and Turn-Into
artefact has an opt-in sponsor variant. The sponsor variant must
respect the guidelines (e.g. "always include #BrandNameSwim";
"never combine our logo with a competitor's").

FILES TO MODIFY:
- ClubProfile: extend with sponsor_logo_path,
  sponsor_brand_colour (hex), sponsor_required_hashtags (list),
  sponsor_forbidden_phrases (list), sponsor_activation_rate
  (e.g. "every 3rd post"), sponsor_position_preference
  (top|bottom|watermark).
- src/mediahub/sponsor/: new module:
    apply_sponsor_to_caption(caption: str, profile: ClubProfile,
                              activation: bool) -> str
    apply_sponsor_to_graphic(graphic_brief: dict,
                              profile: ClubProfile) -> dict
- Generators (caption, graphic, motion, Turn-Into) call the sponsor
  apply functions when activation=True. Activation is determined by
  the sponsor_activation_rate or explicit user toggle per card.
- review page: a "Sponsor mode" toggle on each card; the entire
  content pack also has a global toggle.
- Compliance: a "Sponsor compliance check" panel lists each generated
  artefact and confirms it satisfies all guidelines or flags
  violations.

ACCEPTANCE CRITERIA:
- With sponsor configured, the sponsor toggle on a card produces a
  sponsor variant that:
  - Includes any required hashtags.
  - Avoids any forbidden phrases.
  - Displays the sponsor logo in the configured position.
  - Uses the sponsor brand colour as a tasteful accent (without
    overriding the club's primary palette).
- The compliance panel surfaces any violation clearly.
- Without a sponsor configured, the toggle is hidden, not greyed out.

DON'T BREAK:
- All earlier features still work.
- pytest at 260+ (athletics tests added in Step 8).

TESTS:
- tests/test_sponsor_pipeline.py: required-hashtag enforcement,
  forbidden-phrase blocking, logo positioning.

output expansion).
```

##### Verification Prompt

```
Verify Step 10 (Sponsor mode) end-to-end.

1. Tests: full pytest + tests/test_sponsor_pipeline.py -v.

2. Configuration round-trip:
   - Set sponsor_name + sponsor_required_hashtags ["#TestSponsor"]
     + sponsor_forbidden_phrases ["beat the competition"].
   - Save, reload /organisation. Confirm the fields persist.

3. Sponsor caption check:
   - Toggle "Sponsor mode" on one card.
   - Confirm the caption now contains "#TestSponsor".
   - Force the LLM (or heuristic) to produce text containing "beat the
     competition" via a test fixture, run the apply function, and
     confirm the phrase is removed or rewritten.

4. Sponsor graphic check:
   - Toggle sponsor mode, regenerate the graphic.
   - Open the image; confirm the sponsor logo appears in the
     configured position.
   - Confirm the sponsor colour appears as an accent (not as
     the primary background).

5. Compliance panel:
   - Configure a deliberate violation (a required hashtag NOT present
     in the caption). Confirm the compliance panel flags it visibly.

6. Sponsor absent:
   - Clear sponsor_name. Confirm the sponsor toggle is hidden, not
     present in the DOM.

7. Regression sweep: all Phase 1 and Steps 8-9 features still work.

OUTPUT: single report.
```

---

#### Step 11: Multi-Sport Architecture Cleanup + Football/Rugby

##### Context
With athletics shipped in Step 8 the sports/ package exists. Adding football and rugby validates that the architecture genuinely scales and unlocks the largest UK market segment (school and university football/rugby).

##### Implementation Prompt

```
Add football and rugby as sports 3 and 4; clean up the sports/
architecture as needed.

GOAL: a user can upload a football match report (CSV / structured
text / one-pager PDF) and get a content pack appropriate to football
(goal scorers, clean sheets, man-of-the-match, league position,
fixture preview). Same for rugby (tries, conversions, line-out
stats, set-piece dominance, man-of-the-match).

FILES TO MODIFY:
- src/mediahub/sports/football/: events.py (match events: goals,
  assists, yellow/red cards, subs), parser.py (parse common
  match-report formats including OPTA-style CSV if available),
  achievement_logic.py (goal-of-the-match, hat-trick detection,
  clean-sheet recognition), templates.py.
- src/mediahub/sports/rugby/: similar structure for rugby union
  (tries, conversions, penalties, man-of-the-match, line-out wins).
- Generalise the existing pb_logic.py — for team sports it's
  achievement_logic.py with different primitives. Refactor the
  swimming/athletics modules to use a common interface
  (sports/<sport>/achievement_logic.py) where appropriate.
- /upload: detect sport from file content + filename.
- /organisation: add a "Sports" multi-select so a club can declare
  it covers multiple sports.

ACCEPTANCE CRITERIA:
- A hat-trick is correctly detected and surfaced as the headline
  achievement in football.
- A clean sheet is correctly attributed to the goalkeeper.
- Rugby man-of-the-match selection prefers tries > conversions >
  metres made if not explicitly named in the input.
- A clean league position (1st in the table) is detected as a
  high-priority achievement.
- All previous sports tests (swimming + athletics) still pass.

DON'T BREAK:
- pytest at the new baseline (target 280+).
- Phase 1 features remain functional on football/rugby output.

TESTS:
- tests/test_football_*.py and tests/test_rugby_*.py covering parsing,
  achievement detection, and caption generation.

```

##### Verification Prompt

```
Verify Step 11 (Football + Rugby) end-to-end.

1. Tests: full pytest. Target 280+ passed.
   - python -m pytest tests/test_football_*.py tests/test_rugby_*.py -v.

2. Hat-trick detection:
   - Upload a football match where player X scored 3 goals.
   - Confirm the top-ranked card mentions a hat-trick.
   - Confirm the visible-intelligence reasoning includes goal count.

3. Clean sheet attribution:
   - Upload a 2-0 win match. Confirm the goalkeeper's card mentions
     "clean sheet".

4. Rugby try detection:
   - Upload a rugby match with 4 tries by player Y. Confirm Y is the
     headline and the caption uses rugby-appropriate language.

5. Multi-sport club:
   - Set a club's sports to ["swimming","football"]. Upload swimming.
     Confirm swimming pipeline. Upload football. Confirm football
     pipeline.

6. Cross-sport caption consistency:
   - Same voice_profile applied to a football caption and a swimming
     caption — the stylistic signature (sentence length, hashtag
     count) should match across both.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 12: Native Publishing APIs (Replace Buffer Dependency)

##### Context
Step 6 shipped Buffer integration to close the publishing gap fast. This step builds direct integrations to Instagram Graph API, Facebook Pages, X (v2), LinkedIn Marketing, and TikTok Business so MediaHub no longer depends on Buffer for the core publishing path.

##### Implementation Prompt

```
Replace Buffer dependency with native publishing APIs.

GOAL: a user can connect Instagram Business, Facebook Pages, X,
LinkedIn (Company Page), and TikTok Business directly. Scheduling
no longer requires a Buffer account.

FILES TO MODIFY:
- src/mediahub/publishing/instagram.py: Graph API; OAuth via
  Facebook Login. Single-image + reels upload + caption.
- src/mediahub/publishing/facebook.py: Pages API; OAuth via
  Facebook Login.
- src/mediahub/publishing/x_twitter.py: v2 API; OAuth 2.0 with PKCE.
- src/mediahub/publishing/linkedin.py: Marketing Developer Platform;
  OAuth 2.0.
- src/mediahub/publishing/tiktok.py: TikTok Business API; OAuth 2.0.
- src/mediahub/publishing/scheduler.py: a unified Scheduler interface
  (queue, schedule_at, dispatch_now) so the UI calls one API
  regardless of platform.
- A background worker (lightweight — Flask-APScheduler or a simple
  cron-style polling thread) that dispatches scheduled posts at
  their scheduled_at time.
- /settings: native "Connect Instagram", "Connect Facebook" etc.
  buttons (in addition to the existing Buffer field, which remains
  as a fallback).

ACCEPTANCE CRITERIA:
- A user can complete the OAuth flow for each platform and the
  resulting access tokens are stored encrypted (Fernet) in
  DATA_DIR / "secrets" / <user_id>.json.
- Scheduling a post via the UI dispatches to the right platform at
  the right time.
- Token refresh is handled before each dispatch.
- Buffer remains available as a fallback channel; users can choose
  per-card whether to dispatch direct or via Buffer.

DON'T BREAK:
- pytest at the new baseline (target 290+ with publishing tests).
- All earlier features still work.

TESTS:
- tests/test_native_publishing.py: mocked OAuth + dispatch, token
  refresh, dispatcher worker.

landscape closing), §6 Workstream 3.x.
```

##### Verification Prompt

```
Verify Step 12 (Native publishing) end-to-end.

1. Tests: full pytest + tests/test_native_publishing.py -v.

2. OAuth flows (mocked):
   - For each of the 5 platforms, simulate the OAuth callback with a
     fixed test token. Confirm the token is stored encrypted (not
     plaintext) in the per-user secrets file.

3. Dispatch (mocked):
   - Schedule a post with scheduled_at = now + 30s.
   - Wait 45s. Confirm the post was dispatched via the mocked API.
   - Confirm the workflow state shows schedule_status=published.

4. Token refresh:
   - Set an expired-token scenario. Confirm the dispatcher refreshes
     the token before dispatching, or surfaces a clear "re-connect"
     error if refresh fails.

5. Buffer fallback:
   - Confirm Buffer is still selectable per-card and the Buffer
     dispatch path still works.

6. Security:
   - grep the codebase for any access_token logging — must be zero.
   - Confirm the encrypted secrets file mode is 0600.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Phase 3 — Leadership (Steps 13-17, target months 9-18)

#### Step 13: Integration Moat — Hy-Tek, TeamUnify, ClubBuzz Importers

##### Context
The single most defensible distribution moat against horizontal entrants is direct integration with the software clubs already use. Hy-Tek MeetManager (results), TeamUnify (club management), ClubBuzz (UK clubs), SwimManager — each integration is one to three engineering weeks and creates a switching cost.

##### Implementation Prompt

```
Build first-class importers for the most-used club software.

GOAL: a user with a TeamUnify or ClubBuzz account can connect MediaHub
once, and every new meet result automatically flows into MediaHub
without a manual upload.

FILES TO MODIFY:
- src/mediahub/integrations/teamunify.py: OAuth or API key auth,
  poll for new meet results, ingest as a new run, run the full
  pipeline.
- src/mediahub/integrations/clubbuzz.py: same pattern.
- src/mediahub/integrations/hytek_meetmanager.py: file-format
  importer for the .hy3 format with deeper coverage than the existing
  parser (handle all common event codes, age groups, time conversions).
- src/mediahub/integrations/splash_meet_manager.py: file-format
  importer for Splash's export format.
- /settings: new "Integrations" section with one-click connect
  buttons.
- A background polling worker for the API-based integrations.

ACCEPTANCE CRITERIA:
- A connected TeamUnify account auto-ingests new meets within 1 hour
  of them appearing in TeamUnify.
- Hytek and Splash file imports produce identical content packs to
  manual uploads.
- A revoked integration cleanly stops polling and surfaces in the UI.

DON'T BREAK:
- Manual file upload still works.
- pytest at the new baseline (target 300+).

TESTS:
- tests/test_integrations_*.py: mocked API responses, end-to-end
  ingestion.

```

##### Verification Prompt

```
Verify Step 13 (Integrations) end-to-end.

1. Tests: full pytest + tests/test_integrations_*.py -v.

2. TeamUnify mocked happy path:
   - Connect with a test API key.
   - Push a fake new-meet event via the mock server.
   - Confirm a new run appears in MediaHub within the polling interval.
   - Confirm the run produces a valid content pack.

3. Hytek parity:
   - Take an existing .hy3 file that worked with the manual uploader.
   - Run it through the new importer. Confirm the resulting content
     pack is identical (same number of achievements, same ranking).

4. Splash importer:
   - Process a sample Splash file. Confirm event detection + PB
     attribution.

5. Disconnection:
   - Revoke the test API key. Confirm polling stops within 1 polling
     cycle and the /settings page shows "Disconnected".

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 14: Enterprise Tier — Multi-Club Orchestration

##### Context
The financial backbone of the strategy. Governing bodies, leagues, federations, and large university athletic departments need multi-club orchestration: branded league templates, federation-wide engagement analytics, sponsorship reporting across clubs.

> ⚠️ **Partly promoted (2026-06 reconcile).** The **Organisation → Club → Run hierarchy /
> multi-tenancy** half of this step is no longer a far-future "leadership" item — it is
> pulled forward to **Phase C · PC.3** as a **blocking prerequisite**, because
> single-instance-per-club can't scale (ops/support rise linearly vs. fixed founder
> hours). The *federation analytics / template-push / sponsorship-report* surfaces remain
> later-stage. See
> [`research/SCALING_DILIGENCE_2026.md`](research/SCALING_DILIGENCE_2026.md) and
> [`adr/0011-commercial-reconcile-revenue-reality.md`](adr/0011-commercial-reconcile-revenue-reality.md).

##### Implementation Prompt

```
Ship the enterprise tier: multi-club orchestration.

GOAL: a Federation user (Stripe enterprise plan from Step 7) can
manage up to 50 clubs from one account, push league-branded templates
to all clubs, view aggregated engagement analytics, and produce
sponsorship reports.

FILES TO MODIFY:
- Data model: introduce Organisation (governing body / league) →
  Club → Run hierarchy. Backward-compatible: a club without an
  organisation is treated as a standalone (today's default).
- src/mediahub/enterprise/: new module:
    OrganisationProfile dataclass
    league_templates.py — manage and distribute templates
    aggregated_analytics.py — engagement metrics across child clubs
    sponsorship_report.py — sponsor-exposure metrics with citations
- new pages:
  /federation — dashboard
  /federation/clubs — manage child clubs
  /federation/templates — push templates
  /federation/analytics — aggregated metrics
  /federation/sponsorship — sponsor reports
- billing: Stripe plan "federation" unlocks these pages.

ACCEPTANCE CRITERIA:
- A federation user can add a child club and the child club's owner
  receives an invite link to accept the relationship.
- Pushing a template to all child clubs makes the template available
  in each club's Turn-Into picker.
- Aggregated analytics correctly sum engagement across all child
  clubs and never double-count.
- A sponsorship report can be exported as a branded PDF.

DON'T BREAK:
- Standalone clubs (no parent organisation) work exactly as before.
- pytest at the new baseline (target 310+).

TESTS:
- tests/test_enterprise_*.py covering hierarchy, template push,
  analytics aggregation, sponsorship report generation.

scale).
```

##### Verification Prompt

```
Verify Step 14 (Enterprise tier) end-to-end.

1. Tests: full pytest + tests/test_enterprise_*.py -v.

2. Hierarchy:
   - Create a federation account and three child clubs.
   - Confirm the federation dashboard shows all three.
   - Sign in as one child club — confirm it can see only its own runs.

3. Template push:
   - Federation pushes a "Meet Recap League Template".
   - Each child club's Turn-Into picker now includes it.

4. Analytics:
   - Federation analytics page sums engagement across the three clubs.
   - Manually verify the sum equals the per-club totals.

5. Sponsorship report:
   - Generate a sponsorship PDF for the federation's headline sponsor.
   - Confirm the PDF includes per-club sponsor activations with
     citations (which post, which date, which platform).

6. Plan guard:
   - On a non-federation plan, the federation pages return a clear
     upgrade prompt, not a 404.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 15: Conversational / Agentic Caption Editing

##### Context
Lately's Kately and Holo's chat-editor demonstrate the next interaction primitive: a conversational layer over the existing content pack. "Make this caption more energetic", "Add a thank-you to the parents", "Generate a TikTok script from this meet" — the user issues natural-language instructions and the agent operates over the existing assets.

##### Implementation Prompt

```
Add a conversational editing surface to the content pack.

GOAL: every card on the review page has a chat panel where the user
can issue natural-language edit commands ("shorter", "more energetic",
"in Spanish", "add a sponsor mention", "generate a TikTok variant").
The agent uses the existing tools (generate_caption_for_tone,
sponsor.apply, motion.render_story_card) rather than free-form
generation.

FILES TO MODIFY:
- src/mediahub/agent/__init__.py
- src/mediahub/agent/tools.py: register the tools the agent can call
  (regenerate_caption, change_tone, translate_caption, add_sponsor,
  generate_motion, generate_reel_variant).
- src/mediahub/agent/runner.py: a small tool-use loop using the
  existing LLM (Gemini or Anthropic) with structured tool calling.
- /review page: a chat panel toggle next to each card.
- Every agent action writes an audit entry (who, when, what tool,
  what arguments, what result) to DATA_DIR/agent_audit/<run_id>.jsonl.

ACCEPTANCE CRITERIA:
- "Make this shorter" produces a caption ≤80% of the original length.
- "Make this in Spanish" produces Spanish output.
- "Add a sponsor mention" calls the sponsor.apply tool and produces
  a sponsor variant.
- The agent NEVER publishes — every change is staged and requires
  the user's Save click.

DON'T BREAK:
- pytest at the new baseline (target 320+).
- All earlier features still work.

TESTS:
- tests/test_agent_*.py: tool invocation, no-publish guarantee,
  audit log integrity.

§6 Workstream 3.3.
```

##### Verification Prompt

```
Verify Step 15 (Agentic editing) end-to-end.

1. Tests: full pytest + tests/test_agent_*.py -v.

2. Edit commands:
   - "shorter" → length reduction confirmed.
   - "more energetic" → tone shift confirmed (compare against baseline).
   - "in Spanish" → output is Spanish (langdetect).
   - "add a sponsor mention" → sponsor hashtag present.

3. No-publish guarantee:
   - Issue 10 agent commands. Confirm NONE of them dispatched a
     publish action. The audit log should show zero publishing tool
     calls.

4. Audit:
   - For each agent action, confirm DATA_DIR/agent_audit/<run_id>.jsonl
     has a corresponding entry with full arguments and result.

5. Tool safety:
   - Try to inject "delete this run" via the chat input. Confirm the
     agent does not call any destructive tool (no such tool exists in
     the registry).

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 16: Template Marketplace

##### Context
Community templates raise switching cost. Once a club has invested in templates that exist only on MediaHub — branded recap layouts, voice profiles, season-narrative arcs — leaving the platform costs them their accumulated content infrastructure.

##### Implementation Prompt

```
Ship a community template marketplace.

GOAL: clubs and federations can publish templates (visual layouts,
voice profiles, Turn-Into recipes, sponsor activation patterns) for
other clubs to fork. Templates are versioned and reviewable.

FILES TO MODIFY:
- src/mediahub/marketplace/: new module.
- Template types: visual_layout (graphic + motion templates),
  voice_profile_template (anonymised voice patterns),
  turn_into_recipe (which 7 artefacts a Turn-Into produces and how),
  sponsor_activation (predefined sponsor variants for common partners).
- /marketplace page: browse, preview, fork.
- /marketplace/submit: submit a template (with review queue).
- /marketplace/admin: review/approve/reject submissions (federation
  + MediaHub admin role).

ACCEPTANCE CRITERIA:
- A submitted template enters a review queue.
- Forking a template clones it into the user's own club profile —
  edits to the fork do not affect the source.
- Templates are versioned; the user can upgrade their fork to a newer
  source version.
- Marketplace search by sport, audience size, language.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_marketplace_*.py covering submission, fork, version
  upgrade, isolation between fork and source.

```

##### Verification Prompt

```
Verify Step 16 (Template marketplace) end-to-end.

1. Tests: full pytest + tests/test_marketplace_*.py -v.

2. Submit + approve:
   - As a club user, submit a visual_layout template.
   - As an admin, approve it.
   - The template now shows in /marketplace.

3. Fork:
   - As another club, fork the template. Confirm the fork lives in
     the new club's profile.
   - Edit the fork. Confirm the source is unchanged.

4. Version upgrade:
   - As the source owner, publish version 2.
   - The fork shows an "upgrade available" badge. Confirm the upgrade
     applies cleanly.

5. Search:
   - Search by sport=athletics. Confirm only athletics templates
     appear.

6. Privacy:
   - Confirm voice_profile_template templates are anonymised (no
     PII / no club name leaked) before they enter the public
     marketplace.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 17: Sponsor-Side Analytics Product

##### Context
The final defensible primitive: a sponsor-facing product that proves to the sponsor the value of their brand exposure across a club's content. Nota and FanWord do not do this at small-club scale; this is a category MediaHub can own.

##### Implementation Prompt

```
Build a sponsor-side product surface.

GOAL: a sponsor (the brand paying the club) can log in and see a
dashboard of all the times their brand appeared in content produced
by clubs they sponsor, with engagement metrics and an estimated
brand-exposure value.

FILES TO MODIFY:
- New user role: sponsor. Sponsor accounts are linked to specific
  club profiles via an invitation flow.
- src/mediahub/sponsor_dashboard/: new module.
- /sponsor — sponsor dashboard.
- /sponsor/exposure — list of every post where this sponsor's brand
  appeared, with date, platform, engagement, and a thumbnail of
  the asset.
- /sponsor/value — estimated brand-exposure value (impressions ×
  CPM-equivalent based on the platform).
- /sponsor/export — branded PDF report.

ACCEPTANCE CRITERIA:
- A sponsor can only see content produced by clubs they sponsor.
- Engagement metrics are pulled from the publishing layer's
  post-success records (Step 12).
- The brand-exposure value calculation is documented and auditable
  (open the value calculation in a tooltip).
- The PDF export is reproducible and includes citations to every
  source post.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_sponsor_dashboard_*.py: scoping (sponsor sees only their
  clubs), metric calculation determinism, PDF export shape.

```

##### Verification Prompt

```
Verify Step 17 (Sponsor-side product) end-to-end.

1. Tests: full pytest + tests/test_sponsor_dashboard_*.py -v.

2. Scoping:
   - Sponsor A is linked to Club 1 and Club 2 (not Club 3).
   - Sponsor A's exposure page shows posts from Club 1 and 2 only.
   - Confirm Club 3's posts do NOT appear in any sponsor query.

3. Metric calculation:
   - For a post with known engagement, manually compute the value
     using the documented formula. Confirm the dashboard matches.

4. PDF export:
   - Export a sponsor report. Confirm it opens, contains citations,
     and is reproducible (re-export, byte-equality of the content
     section).

5. Sponsor cannot leak admin:
   - As a sponsor, attempt to access /federation, /admin,
     /api/runs/<id>/turn-into. All must return 403.

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Final Audit — After Step 17 (or any time after Step 7)

##### Context
At any milestone the full product should be audited end-to-end. This audit is the prompt to run after a major release.

##### Audit Prompt

```
Conduct a full MediaHub product audit.

OBJECTIVE: confirm that every feature shipped to date — every step
in the roadmap that has been completed — still works end-to-end with
no regressions, and that the product as a whole holds up against the
quality bar set by the competitors documented in
docs/research/generation-engine-competitor-evaluation.md.

PHASE A — Automated tests:
1. python -m pytest tests/ -q. Report pass/skip/fail counts.
2. python -c "from mediahub.web.web import create_app; create_app()".
3. Boot the app: python -m mediahub.web.web (background).
4. Confirm 0 ERROR-level log lines on a clean boot.

PHASE B — Route sweep:
For each of these routes, confirm a 200 (or correct 30x/40x):
- GET /, /add-input, /upload, /organisation, /settings, /privacy
- GET /pricing, /signup, /login (if Step 7 shipped)
- GET /free-text, /weekend-preview, /sponsor-post, /session-update
- GET /spotlight (if implemented)
- GET /federation, /federation/clubs (if Step 14 shipped)
- GET /marketplace (if Step 16 shipped)
- GET /sponsor (if Step 17 shipped)

PHASE C — Critical user journeys, for each completed step:
- Brand DNA capture: paste a URL, confirm preview, save. Should work.
- Voice imitation: paste 5 examples, save, confirm voice_profile.
- Visible intelligence: open any run, confirm "Why this card?" works.
- Motion: render a story card; render a reel.
- Turn-Into: produce 6-7 artefacts from a meet.
- Buffer or native publishing: schedule a mocked post.
- Commercial: signup, login, upgrade (Stripe test mode).
- Athletics: upload athletics sample, confirm pipeline.
- Athlete page: generate a token, fetch /a/<token>.
- Sponsor mode: toggle on a card, confirm variant.
- Football/Rugby: upload sample, confirm hat-trick / clean sheet.
- Native publishing OAuth: complete one platform's mock flow.
- Integrations: TeamUnify mocked auto-ingest.
- Enterprise: multi-club orchestration.
- Agent: 5 edit commands all hit tools correctly.
- Marketplace: submit + approve + fork.
- Sponsor dashboard: scope correctness + PDF export.

PHASE D — Cross-cutting quality:
- Visual polish: open / and the review page in a browser; screenshot.
  Compare against tryholo.ai's homepage. List any obvious gaps.
- Performance: time a fresh upload-to-content-pack run end-to-end.
  Target < 90s for a 200-swim meet.
- Security: grep the codebase for hardcoded API keys, exposed
  secrets in logs, Path("data/...") relative paths. Report any.
- Test isolation: confirm tests do not write to the real
  data/secrets.json or club_profiles/*.json.
- Accessibility: run a quick a11y scan on the review page. Report
  contrast and keyboard-nav issues.

PHASE E — Strategic position:
For each of the competitors in `docs/research/generation-engine-competitor-evaluation.md`, evaluate where
MediaHub now stands on a 5-point Leading / Competitive / Adequate /
Underdeveloped / Absent scale across the 6 dimensions:
1. Input modality
2. Intelligence layer
3. Output surface
4. Brand context capture
5. Distribution
6. Commercial model

Cross-reference with the competitor analysis in `docs/research/`. Has MediaHub moved up
the matrix on the dimensions Phase 1 targeted? Are there new gaps
that have opened?

OUTPUT FORMAT:
Return a structured audit report:
- Phase A: automated tests results
- Phase B: route table with status codes
- Phase C: per-step pass/fail table
- Phase D: a quality scorecard (1-5) per cross-cutting area
- Phase E: an updated competitive matrix
- Top 5 regression risks (ordered by severity)
- Top 5 next-step recommendations
- A single "release readiness" verdict: Ship / Hold / Block.
```

---

#### Notes on running this roadmap

**Branching.** Every step is a feature branch off `dev`; never merge to `main` without approval. Use names like `step-01-brand-dna-capture`, `step-06-buffer-publishing`. The verification prompt is run before opening the merge request.

**Sequencing.** Steps 1-7 (Phase 1) should be done strictly in order — each builds on the previous. Steps 8-12 (Phase 2) can be partially parallelised once Step 8 (sports architecture) is in. Steps 13-17 (Phase 3) are highest value when done in the order shown but Step 14 (enterprise tier) is the highest financial priority; consider promoting it earlier if revenue is the limiting factor.

**Test budget.** Maintain ≥ 253 passed at every step. Each step adds 5-15 tests, so by Step 17 expect 350+ passing.

**When verification fails.** Paste the failing report back into the implementation session of the same step. Do not move forward until a clean verification report is produced.

**When you stop following the prompts.** Each step is designed to be readable on its own. If during implementation Claude needs context that the prompt didn't provide, the prompt is at fault — improve the prompt and re-run rather than letting Claude guess.

**Source of truth.** This roadmap and the analyses in `docs/research/` (the competitor evaluation + the generative-AI thesis) are the paired references.

---

## Appendix C — Adaptive Theming Engine (1.6): Verification Prompts

> *Stage IDs in this appendix (A–J) map 1:1 to the §1.6 Stage table above. §1.6 is **shipped** — all ten stages are in `main`, live by default, and green. Unlike Appendix A (which builds an as-yet-unbuilt engine), this appendix is **verification-only**: paste-into-a-session acceptance audits that independently confirm each shipped stage still meets its part of the §1.6 acceptance criteria. There are no implementation prompts here — the code already exists.*

**What this is.** A per-stage acceptance-audit harness for the now-shipped
Adaptive Theming Engine. Each stage below has a **Context** (what shipped +
the real files) and a **Verification prompt** (paste into a fresh session).
The prompts are read-only audits plus the test suite; none should need to
modify the engine. A final **full-engine acceptance audit** ties the
per-stage checks back to the five numbered acceptance criteria in §1.6.

**Date:** May 2026 · **Built against:** `main` with Stages A–J merged (the
`theming/` package, the five `static/theme/*.css` layers, `theme_store.py`,
and `docs/THEMING.md`).

**Why verify a shipped feature.** The engine touches every rendered page and
four output media (web, motion, email, static graphic). It is exactly the
kind of cross-cutting surface where a later refactor can silently regress
contrast, drift one medium's palette from the others, or break the cascade.
These prompts are the regression harness that proves it still holds.

---

### 1. The shared verification preamble (every prompt inherits this)

> **Preamble — read before doing anything.** You are auditing MediaHub's
> **shipped** Adaptive Theming Engine (ROADMAP §1.6) in the repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md`,
> `docs/THEMING.md`, and the file(s) named in the task. This is a
> **verification** task — read code, run tests, exercise routes, and report a
> pass/fail checklist. Hard rules:
> - **The colour-science engine is deterministic and off-limits to AI.**
>   `theming/` (palette, roles, contrast, cvd, quality, repair, seed_extract,
>   harmony, logo_chip) and the CIEDE2000 / APCA / Machado maths must stay
>   deterministic. If a check fails, **report it** — do **not** "fix" it by
>   routing a judgement through Gemini/Anthropic, and do not add a hand-tuned
>   per-seed override (the point of §1.6 is intelligence in the algorithm,
>   not a lookup table).
> - **No test cheating.** If you run the suite, do not delete, skip, or weaken
>   a test to make it pass. A red test is a finding, not an obstacle.
> - **Determinism is a property under test.** Same seed → byte-identical
>   palette, every time. If you find non-determinism, that is a failure.
> - **Read-only by default.** These prompts should not need to modify the
>   engine. If you find a genuine gap, report it with a minimal repro; only
>   fix it in a **separate, clearly-scoped** branch + PR with the user's
>   go-ahead — never fold an engine change into a verification pass.
> - **Run the tests named in the task plus the full suite**
>   (`python -m pytest tests/ -q`); confirm no new failures vs `main`.
> - **Report format:** a pass/fail checklist, one line per claim, citing the
>   `file:line` or test name that proves each.

---

### 2. Per-stage verification prompts

#### Stage A — Token foundation
**Shipped:** ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`,
`--mh-primary`, …) defined in `static/theme/theme-base.css` and surfaced via
`web/theme_tokens.py`; every animatable seed/colour registered with
`@property { syntax: "<color>"; inherits: true }`. Tests:
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage A (token foundation). Confirm: the ~25 documented
> role tokens all exist in `theme-base.css`; each animatable colour variable
> (the `--mh-*-seed` set and the role tokens that transition) is registered
> via `@property` with `syntax: "<color>"` (grep the `@property` blocks); no
> transitioned colour relies on an untyped custom property; and migrating to
> tokens introduced no visual change for the default brand (the token values
> resolve to the pre-token palette). Run `tests/test_theme_tokens.py` + the
> full suite. Report any token that is missing or unregistered.

#### Stage B — Colour-science library
**Shipped:** the `src/mediahub/theming/` package — `seed_extract.py`,
`palette.py`, `roles.py`, `contrast.py` (APCA Lc + WCAG2), `cvd.py` (Machado
2009), `quality.py` (`PaletteQualityReport`), `repair.py`, `harmony.py`
(Cohen-Or). Deps `materialyoucolor` + `coloraide` in `pyproject.toml` /
`requirements.txt`. Entry point `theming.derive_theme(seed)`. Tests:
`tests/theming/test_palette.py`, `test_contrast.py`, `test_cvd.py`,
`test_quality.py`, `test_repair.py`, `test_seed_extract.py`,
`test_harmony.py`.

**Verification prompt:**
> [Preamble.] Verify Stage B (colour-science package). Confirm: `derive_theme`
> is deterministic (call it twice on one seed → byte-identical `to_json()`);
> the pipeline is seed → HCT → 5×13 tonal palettes → MD3 roles → APCA/ΔE/CVD
> gates → bounded repair loop (`repair_max_iters` honoured, never infinite);
> `contrast.py` APCA Lc and `cvd.py` Machado matrices match their known
> fixtures; no module makes a network/LLM call (grep `theming/` for
> `requests`, `httpx`, `media_ai`, `ai_core` — none); and an empty/garbage
> seed returns the fallback theme rather than raising. Run all
> `tests/theming/test_*` + the full suite. State the determinism result
> explicitly.

#### Stage C — CSS architecture
**Shipped:** the inline `<style>` block is extracted into `static/theme/`
across `theme-base.css`, `theme-derive.css` (the `color-mix(in oklch, …)` +
relative-colour derivation graph), `theme-components.css`, `theme-cascade.css`,
and `theme-fallback.css` (the `@supports not (color: oklch(from red l c h))`
precomputed ramp). `light-dark()` drives surface/ink pairs off
`prefers-color-scheme`. Tests: `tests/test_theme_static_files.py`,
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage C (CSS architecture). Confirm: the bulk of the
> chrome's colours are *derived* in CSS (grep `theme-derive.css` for
> `color-mix(in oklch` and `oklch(from var(--mh-brand-seed)` — the derivation
> graph is present, not a hardcoded ramp); `light-dark()` is used for
> surface/ink pairs and `prefers-color-scheme` is honoured; the Safari
> long-tail fallback lives inside an `@supports not (...)` block in
> `theme-fallback.css` with no JS polyfill; and the CSS is served as static
> files with a cache-busting URL (not re-inlined per request). Run
> `tests/test_theme_static_files.py` + the full suite. Report the count of
> hardcoded brand-colour hex literals found in colour-derivation positions in
> the CSS layers (expected: ~0).

#### Stage D — Theme delivery (Flask)
**Shipped:** a `before_request` hook + `_theme_seed_style_block()` emit an
inline `<style id="mh-theme-seed">` carrying the active org's brand-seed
override into `<head>` *before* the external stylesheet (zero FOUC).
Resolution is three-tier (flag-off → pinned-org palette → generic-default).

**Verification prompt:**
> [Preamble.] Verify Stage D (theme delivery). Boot the app and request a
> page; confirm the inline `<style id="mh-theme-seed">` block appears in
> `<head>` **before** the external `theme-base.css` link (so there is no flash
> of un-themed content) and carries the active organisation's seed. Confirm
> the three-tier resolution in `_theme_seed_style_block()`:
> `MEDIAHUB_ADAPTIVE_THEME=0` emits nothing (falls through to the static
> cascade), a pinned org uses its `derived_palette`, and no-org uses the
> generic-default theme. Confirm the payload is small (hundreds of bytes, not
> the full palette). Report the head ordering and the three-tier behaviour.

#### Stage E — "Looks right" cascade
**Shipped:** the organisation-finalise handler derives + persists the palette
(`ensure_derived_palette(force=True)`) and navigates via
`document.startViewTransition`; `theme-cascade.css` carries
`@view-transition { navigation: auto }`, the `:root` seed `transition`, and
the `prefers-reduced-motion: reduce` instant-swap override. Tests:
`tests/test_theme_cascade.py`, `tests/test_browser_cascade.py`.

**Verification prompt:**
> [Preamble.] Verify Stage E (the cascade). Confirm: the "Looks right — start
> creating" finalise path saves the brand kit, derives + persists
> `derived_palette`, and wraps the navigation in `document.startViewTransition`
> (degrading to a normal nav where unsupported); `theme-cascade.css` contains
> the `@view-transition` rule, the `:root` colour `transition`, and a
> `@media (prefers-reduced-motion: reduce)` block that disables both; and
> because every derived var is a `color-mix`/`oklch(from …)` of the seed,
> changing the seed alone interpolates the whole palette in lockstep. Run
> `tests/test_theme_cascade.py`; run `tests/test_browser_cascade.py` with
> `MEDIAHUB_RUN_BROWSER_TESTS=1` if a browser is available (else note it's
> gated). Report each contract check.

#### Stage F — Logo intelligence
**Shipped:** `theming/logo_chip.py` defaults to a neutral chip behind an
uploaded logo and computes a "safe to drop chip" decision (dominant
non-neutral colour vs active surface in OKLCH; ΔE2000 + APCA Lc gates in both
polarities); MediaHub's own marks use `fill="currentColor"`; uploaded SVG
marks are never recoloured. Tests: `tests/test_logo_chip.py`,
`tests/test_mediahub_mark_theming.py`.

**Verification prompt:**
> [Preamble.] Verify Stage F (logo intelligence). Confirm: `logo_chip.py`
> defaults to a neutral chip and exposes a deterministic "safe to drop chip"
> test driven by ΔE2000 + APCA Lc in both light and dark polarities;
> MediaHub's *own* SVG marks use `fill="currentColor"` so the chrome adapts to
> ink colour; and the path for *uploaded* logos never recolours or injects
> `currentColor` into an unknown mark (it only adds/removes a chip behind it).
> Run `tests/test_logo_chip.py` + `tests/test_mediahub_mark_theming.py` + the
> full suite. Report the chip-decision logic and confirm the "never recolour
> uploaded marks" guarantee holds.

#### Stage G — Single source of truth (motion + email + static graphic)
**Shipped:** `theming/theme_store.py` writes the DTCG palette JSON to
`DATA_DIR/themes/<profile_id>.json`; `visual/motion.py` passes it as
`inputProps` to `render.js`; `brand/newsletter_renderer.py` Premailer-inlines
the resolved hexes; `graphic_renderer/render.py` reads the same JSON instead
of `BrandKit.primary_colour`. Tests: `tests/test_theme_store.py`,
`test_motion_theme_store.py`, `test_newsletter_theme_store.py`,
`test_graphic_renderer_theme_store.py`.

**Verification prompt:**
> [Preamble.] Verify Stage G (single source of truth). Confirm there is
> exactly **one** palette source — the `theme_store.py` JSON at
> `DATA_DIR/themes/<profile_id>.json` — and that all four consumers read it:
> `visual/motion.py` (→ Remotion `inputProps`), `brand/newsletter_renderer.py`
> (Premailer-inlined hexes, since email clients don't support custom
> properties), `graphic_renderer/render.py`, and the web cascade. Pick one
> seed, derive its theme, and assert the **same** role hex appears in the
> motion props, the inlined email HTML, the static graphic, and the CSS seed
> block — **zero drift across media**. Run the four `*_theme_store.py` tests +
> the full suite. Report the cross-media hex comparison.

#### Stage H — Explainability + QA
**Shipped:** `PaletteQualityReport` (`quality.py` `to_summary()` +
`to_detail()`) logs APCA Lc per role pair, the CIEDE2000 matrix for brand ×
{neutral, success, warning, danger}, Machado-CVD ΔE under
deutan/protan/tritan, the Cohen-Or harmonic-fit energy, and a decision trace;
a "Why does my theme look like this?" panel on `/organisation/setup` shows the
decisions + lets a committee member override a role (logged, with a
cultural-clash warning if it lowers a status colour's ΔE); a non-blocking
callout fires when the hostile-seed repair loop ran. Tests:
`tests/test_quality_detail.py`, `test_repair_callout.py`,
`test_org_palette_confirm.py`.

**Verification prompt:**
> [Preamble.] Verify Stage H (explainability + QA). Confirm: every derivation
> produces a `PaletteQualityReport` with APCA Lc per text-on-surface pair, the
> brand×status CIEDE2000 matrix, Machado-CVD ΔE under all three CVD types, the
> Cohen-Or harmonic-fit energy, and a human-readable decision trace; the "Why
> does my theme look like this?" panel renders these on `/organisation/setup`;
> a manual role override is persisted *and* logged, and lowering a status
> colour's ΔE raises a cultural-clash warning; and when the repair loop fires
> on a hostile seed, a non-blocking callout explains *which status colour* was
> nudged and why (never silently rewriting the brand colour). Run
> `tests/test_quality_detail.py` + `test_repair_callout.py` +
> `test_org_palette_confirm.py` + the full suite. Report each explainability
> surface.

#### Stage I — Test coverage
**Shipped:** `tests/theming/` with golden-master snapshots for ~30
representative seeds (incl. fluorescent `#DFFF00`, muddy `#2A3A1A`, near-white
`#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, +
real club colours) in `seeds_catalogue.py` / `snapshots/`, plus
APCA/CVD/quality/repair unit tests; `tests/test_browser_cascade.py` is the
Playwright/browser-use end-to-end (gated on `MEDIAHUB_RUN_BROWSER_TESTS=1`).

**Verification prompt:**
> [Preamble.] Verify Stage I (test coverage). Confirm: the golden-snapshot set
> in `tests/theming/` covers the hostile seeds
> (neon/muddy/near-white/near-black/pure-primary) **and** real club colours;
> the gate tests actually assert the §1.6 thresholds (APCA Lc ≥ 75 for
> text-on-surface; CIEDE2000 ≥ 5 between adjacent tonal stops; ≥ 15 between
> brand and each status colour; Machado-deuteranopia ΔE2000 ≥ 10 for the same
> triples; Cohen-Or fit below threshold); the snapshots regenerate
> deterministically (no flakiness); and `tests/test_browser_cascade.py` exists
> and is correctly gated. Run `python -m pytest tests/theming/ -q` and report
> the count + whether any threshold is asserted more weakly than §1.6 states.

#### Stage J — Cutover + polish
**Shipped:** `_adaptive_theme_enabled()` reads `MEDIAHUB_ADAPTIVE_THEME`
(default **on**; `0/false/off/no` rolls back to the static cascade) — J1;
`_default_theme_json()` runs the generic-default BrandKit (`#0E2A47` /
`#C9A227`) through the pipeline for unconfigured first-run — J2;
`docs/THEMING.md` documents the architecture, role-token table,
operator-overridable variables, and academic citations — J3. Tests:
`tests/test_adaptive_theme_flag.py`, `test_default_theme.py`,
`test_theming_md.py`.

**Verification prompt:**
> [Preamble.] Verify Stage J (cutover + polish). Confirm: `MEDIAHUB_ADAPTIVE_THEME`
> defaults **on**, and setting it to `0`/`false`/`off`/`no` cleanly reverts
> every page to the static Stage-A cascade with no errors (the on-disk JSON,
> audit panel, and repair callout keep working regardless); the generic-default
> brand kit is themed through the same pipeline (unconfigured deployments get
> the upgrade, no regression); and `docs/THEMING.md` documents the
> architecture, the role-token table, the variables an operator may safely
> override, and the inline academic citations. Run
> `tests/test_adaptive_theme_flag.py` + `test_default_theme.py` +
> `test_theming_md.py` + the full suite. Report the flag round-trip and the
> default-theme behaviour.

---

### 3. Full-engine acceptance audit (maps to the §1.6 acceptance criteria)

**Verification prompt:**
> [Preamble.] Run the §1.6 "definition of done" end-to-end and report a single
> scorecard against the five acceptance criteria:
> 1. **Hostile-seed gate.** Drive ~30 representative seeds (incl.
>    neon/muddy/near-greyscale/pure-primary) through `derive_theme`; assert
>    APCA Lc ≥ 75 for every text-on-surface role pair, CIEDE2000 ≥ 5 between
>    adjacent tonal stops, ≥ 15 between brand and each of
>    success/warning/danger, Machado-deuteranopia ΔE2000 ≥ 10 for those
>    triples, and Cohen-Or fit below threshold. Report any seed that fails any
>    gate.
> 2. **Live cascade.** Confirm the cascade works in Chromium (run
>    `tests/test_browser_cascade.py` with `MEDIAHUB_RUN_BROWSER_TESTS=1` if
>    available) and degrades to instant nav where View Transitions is
>    unsupported; reduced-motion users get an instant swap.
> 3. **No stray hardcoded brand colour.** Grep the whole repo for
>    brand-colour hex literals outside `theming/repair.py`'s curated-neighbour
>    fallback table; report any found in template/CSS/Python colour positions.
> 4. **Zero cross-media drift.** For one seed, assert the same role hexes
>    appear in web (CSS seed block), motion (`inputProps`), email (inlined
>    HTML), and static graphic.
> 5. **Suite green.** `python -m pytest tests/ -q` — no new failures vs
>    `main`, no weakened/skipped tests masking a structural break.
> Output: a five-row pass/fail table with the proof (test name / `file:line`)
> for each, plus any regression risk you spotted.

---

### 4. If a verification fails

A failure here is a real regression in shipped code, not a build step.
Capture a minimal repro (the seed, the role pair, the failing assertion),
report it against the stage above, and fix it in a **separate** branch + PR
scoped to that regression — keeping the colour-science deterministic and never
substituting an AI judgement or a hand-tuned per-seed override for the
algorithm. Re-run the full-engine audit (§3) before closing.

---

*End of roadmap.*
