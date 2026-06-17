# 4. Rebuild the roadmap around a multi-sport, autonomy-first strategy

- **Status:** Accepted — docs + inert scaffolding landed in this change; feature
  implementation is deferred to later roadmap phases.
- **Date:** 2026-06-01
- **Deciders:** MediaHub maintainer (explicit user directive), grounded in the 2026
  roadmap research report. Recorded as an ADR per the same precedent as
  [`0001-generation-engine-v2.md`](0001-generation-engine-v2.md) (maintainer
  decision, research-sourced).
- **Context source:** [`../research/ROADMAP_RESEARCH_2026.md`](../research/ROADMAP_RESEARCH_2026.md)
  (strategy in Part A, architecture in Part B, the ~55-repo catalogue in Part C,
  synthesis/phases/licensing in Part D) and the task brief
  [`../research/CLAUDE_CODE_PROMPT_MediaHub_Roadmap_Rebuild.md`](../research/CLAUDE_CODE_PROMPT_MediaHub_Roadmap_Rebuild.md).

## On governance (why an ADR, not a fresh Council run)

[`COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md) makes roadmap sequencing and new
data models Council-gated. The Council, however, "explicitly warns against trivial
use" and excludes "implementing a step whose design was *already decided* (cite that
decision)." The strategic reframe here was decided by the **maintainer**, who
outranks the Council (the Council cannot even override maintainer sign-off), backed
by a deep multi-angle research report that already performed the clashing-analysis
function (Parts A–D, including negative findings and licence verdicts). Re-counciling
a closed, research-backed maintainer directive would be exactly the ceremony the
governance warns dulls the mechanism. This ADR is the durable decision record the
governance requires, and the PR links it. The genuinely-open *implementation* choices
(below) were made to match existing seams and are recorded here with their
alternatives.

## Context

MediaHub ships as a swimming results→content pipeline. The maintainer is redirecting
it toward a **content-strategy brain**: a multi-sport, multi-tenant intelligence
layer that decides what a team should post, drafts it, and — per a per-content-type
toggle — readies it for a human to review and then export/download for manual
posting. Results ingestion becomes one spoke among many. A hard product constraint
is **no hidden fees / truly-free self-host**.

This change is scoped to **documentation + non-breaking scaffolding only**. No shipped
swimming behaviour changes; no feature is implemented; the scaffolding is inert.

## Decision

1. **Rebuild `docs/ROADMAP.md`** around the research report's **Phase 0–5** spine
   (0 de-risk licensing/cost · 1 strategy brain + post-type taxonomy + sport
   profiles · 2 autonomy toggles + orchestration · 3 broaden ingestion · 4
   creative-suite breadth · 5 local-AI substitution). New stable IDs
   `P0`–`P5` / `P0.1`… verified compatible with `scripts/roadmap_autoupdate.py`.
   This **supersedes** the previous Parity → Distinction → Leadership spine (lineage
   noted in the roadmap). Badge legend, plain-English intro, the `roadmap: <ID>
   <status>` trailer convention, and the auto-generated marker blocks are preserved
   untouched. Appendices A/B/C are retained as execution detail with a bridging note.
2. **Author four supporting docs:** `POST_TYPE_TAXONOMY.md`,
   `SPORT_PROFILES.md`, `ARCHITECTURE_TARGET.md`, `DEPENDENCY_LICENSING.md`.
3. **Add inert scaffolding:** `src/mediahub/sport_profiles/` (typed `SportProfile`/
   `PostTypeConfig` dataclasses, `AutonomyLevel` enum, YAML loader) + two profiles
   (`data/sport_profiles/{swimming,football}.yaml`) + unit tests. Not wired into
   runtime.

### Implementation choices (the open forks) and why

- **New `sport_profiles` package vs. extending `recognition.registry`/
  `club_platform.content_types`.** Chosen: a *separate* config-layer package, kept
  distinct from the engine-layer `SportConfig` and post-type `ContentType` registry.
  Rationale: the engine is accuracy-critical/deterministic and changes rarely; the
  profile is human-authored product config that changes often. Merging them would
  couple two very different change cadences and risk dragging config concerns into
  the deterministic boundary. `SportProfile.engine_sport` links the two. (The task
  brief also specified a `sport_profiles/` package.)
- **YAML vs. JSON for profiles.** Chosen: YAML, despite the rest of `data/` being
  JSON — profiles are human-authored/reviewed (including by non-coders), so comments
  and readability matter. Treated as read-only shipped config (like
  `data/ontology/`, `data/voices/seed/`), resolved relative to `data/`, not `DATA_DIR`.
- **`AutonomyLevel` shape.** Chosen: the two review-disposition states
  (`draft_only`/`approval_required`), `str`-backed to match `ContentType`, gated
  by default — a human approves before any content is used.
- **Supersede vs. delete the old roadmap appendices.** Chosen: supersede the spine
  but **retain** Appendices A (Generative Content Engine v2 build prompts, tied to
  in-flight code + ADR-0001), B (older growth sequence), and C (theming
  verification, tied to shipped code), under a bridging/lineage note. Deleting valid,
  code-linked execution detail would be destructive and orphan live `PAR-*`/`SEQ-*`
  trailer IDs.

## Consequences

**Positive**
- The forward plan is grounded in *verified* current state (e.g. `rembg` is already
  the free cutout default; `recognition.registry`/`club_platform.content_types`/
  `workflow.CardStatus` already provide the seams the new concepts map onto).
- The no-hidden-fees constraint is made explicit and auditable via
  `DEPENDENCY_LICENSING.md`.
- Scaffolding lets later sessions build the strategy brain / autonomy enforcement
  against a stable, tested data model without re-deciding its shape.

**Neutral / costs**
- The roadmap now carries two phase vocabularies (new Phase 0–5 spine + the legacy
  spine surviving inside the appendices), reconciled by the lineage note.
- A new free dependency (`PyYAML`, MIT) is declared for the loader.
- New `data/sport_profiles/*.yaml` is a new persisted *shape*, but read-only shipped
  config, not multi-tenant runtime state.

**Deviations from the brief (recorded, not silent)**
- **Branch.** The brief suggested `claude/roadmap-rebuild`; the session is locked to
  `claude/beautiful-brown-oAjpg` with an explicit "never push elsewhere without
  permission" rule, which takes precedence.
- **Research filename.** The brief referenced `docs/research/ROADMAP_RESEARCH_2026.md`;
  the file was present under its auto-generated `compass_artifact_*` export name and
  was renamed to the canonical name (nothing referenced the old name).
