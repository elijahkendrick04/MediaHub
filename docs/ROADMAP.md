# MediaHub Roadmap

The plan, as two lists: what's **to do** and what's **completed**. Each line is
one item with a stable ID. The full long-form plan this replaces — phase
essays, commercial analysis, and the Appendix A/B/C build prompts — is
preserved verbatim in
[`ROADMAP_ARCHIVE_2026-06.md`](ROADMAP_ARCHIVE_2026-06.md); the strategy
itself lives in the ADRs and companion docs linked under
[Standing context](#standing-context) below.

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
**Last updated:** 2026-06-10 · `ea36bf142` · Merge pull request #306 from elijahkendrick04/bot/roadmap-autoupdate
<!-- /ROADMAP:LAST_UPDATED -->

**Recent activity**

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-06-10 | `ce77df9f3` | feat(gen-v2): complete the PAR bucket against the shipped SEQ-0-4 spine |
| 2026-06-10 | `cc928922d` | fix(roadmap): merge directly when the bot PR is already clean |
| 2026-06-10 | `f141579f6` | fix(roadmap): land auto-updates via auto-merge PR + catch up the missed range |
| 2026-06-10 | `f3bc87b3a` | docs(build): SEQ-3 gate A/B review — v2 beats the old engine; cutover approved |
| 2026-06-10 | `c1e540f32` | style: apply pre-commit hygiene to PR-touched files (ruff-format 0.8.4, EOF fixer) |
| 2026-06-10 | `3a03b9889` | docs(build): final suite result — 3628 passed, 1 skipped after the full spine |
| 2026-06-10 | `4a8623c1f` | docs(build): SEQ-4 verification evidence + suite table in the spine report |
| 2026-06-10 | `52470c085` | feat(gen-v2): SEQ-4 — data-driven reel scene structure + archetype-matched motion + opt-in gen backg |
| 2026-06-10 | `e64f604cd` | fix(gen-v2): explicit seed 0 must be an exact archetype pick, not 'no seed' |
| 2026-06-10 | `968d37d2d` | style: ruff-format touched files (pinned hook v0.8.4) |
| 2026-06-10 | `97ed87e94` | refactor(gen-v2)!: SEQ-3 cutover — remove the dead enum-permutation variation engine |
| 2026-06-10 | `db6b1fbc1` | test(renderer): regression pins for the font-loading and Anton-fit defects |
<!-- /ROADMAP:ACTIVITY -->

## To do

Ordered by priority: **Phase C (commercialise) outranks everything**; P3/P4/P5
are gated behind Phase C's exit criteria (see Standing context).

<!-- ROADMAP:TODO -->
- **PC.3** · Phase C 🥇 — True multi-tenancy: org → workspace in one shared instance (the #1 scaling fix; single-instance-per-club collapses at ~15–40 clubs). Schema needs operator/Council sign-off — it touches the locked ADR-0003 isolation invariant · ⚠️ **BLOCKED**
- **PC.4** · Phase C 🥇 — Pricing & packaging by revealed willingness-to-pay: quote real annual prices to the first hand-sold clubs; keep `/pricing` at "TBC" until ≥5 clubs have paid annual at a tested price · ❌ **NOT STARTED**
- **PC.6** · Phase C 🥇 — Go-to-market: warm-first hand-sell of the first ~10 clubs (local Swansea/South-Wales base + referrals; cold capped) and apply for Swim England's approved-systems data API · ❌ **NOT STARTED**
- **P0.1** · Phase 0 — Free reel fallback (Satori + FFmpeg) behind a flag so Remotion is optional · ❌ **NOT STARTED**
- **P0.3** · Phase 0 — Every paid dependency provably optional behind a flag with a free default wired · 🔵 **IN PROGRESS**
- **P0.4** · Phase 0 — A local-capable provider slot for every AI call (LLM/TTS/ASR/graphics) — precondition for P5 · ❌ **NOT STARTED**
- **P0.5** · Phase 0 — Any AGPL service isolated behind a network boundary (never embedded) · ❌ **NOT STARTED**
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
- **P5.4** · Phase 5 (gated) — Satori graphics fast-path (~100× lighter than headless Chromium; overlaps P0.1) · ❌ **NOT STARTED**
<!-- /ROADMAP:TODO -->

## Completed

<!-- ROADMAP:DONE -->
- ✅ **P0.2** · Phase 0 — Cutout free-by-default: in-process rembg is the default (`MEDIAHUB_CUTOUT_PROVIDER=server`); Replicate/PhotoRoom opt-in *(completed pre-2026-06 — see archive)*
- ✅ **P5.5** · Phase 5 — rembg cutout shipped as the default (MODNet noted as optional upgrade) *(completed pre-2026-06 — see archive)*
- ✅ **P1.1** · Phase 1 — Sport-profile schema + loader + `AutonomyLevel` + swimming/football YAML profiles (inert scaffolding) *(completed pre-2026-06 — see archive)*
- ✅ **P2.1** · Phase 2 — Orchestration backbone the in-process way: `scheduler/` exactly-once SQLite runner + `autonomy/` bounded narrow-tool runner (Temporal rejected by Council) *(completed pre-2026-06 — see archive)*
- ✅ **PC.1** · Phase C — Self-serve signup + auth: `/signup` `/login` `/logout`, bcrypt, signed session cookie, `users.jsonl` ledger *(completed 2026-06-09, PR #267)*
- ✅ **PC.2** · Phase C — Stripe billing + subscription lifecycle: Checkout, Customer Portal, signed webhook; honest-503 until the operator sets `STRIPE_*` keys *(completed 2026-06-09, PR #267)*
- ✅ **PC.5** · Phase C — Free-self-host tension resolved: **hosted-only**, no customer self-host tier (maintainer decision; ADR-0011) *(completed 2026-06-09)*
- ✅ **P2.4** · Phase 2 — Per-type autonomy controls in the workspace: Settings → Autonomy tab, per-profile per-type policy defaulting to approval_required, publish gate + global kill switch *(completed 2026-06-09, PR #297)*
- ✅ **P1.4** · Phase 1 — Generative Content Engine v2, complete: Appendix A spine SEQ-0→4 (tokens, Tier B director/pool/APCA compliance ranking, gated SEQ-3 cutover with the A/B review approved, data-driven video) + the full PAR-1→8 bucket (12/12 archetype catalog); v2 is the default engine, `MEDIAHUB_GEN_V2=0` is the kill switch; evidence in `build_reports/SEQ_SPINE_2026-06-10.md` and `build_reports/GEN_QUALITY_BASELINE.md` *(completed 2026-06-10, PRs #259/#300/#301)*
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

**Archive:** the pre-2026-06-10 long-form roadmap (phase essays, revenue
tables, Appendix A/B/C build & verification prompts) is frozen in
[`ROADMAP_ARCHIVE_2026-06.md`](ROADMAP_ARCHIVE_2026-06.md).
