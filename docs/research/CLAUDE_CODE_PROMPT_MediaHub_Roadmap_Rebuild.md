# Claude Code Task — Rebuild the MediaHub Roadmap Around the New Multi-Sport, Autonomy-First Strategy

## 0. Mission & scope
You are working in the existing **MediaHub** codebase (Python/Flask sport-content-automation, currently swimming-focused). The product is being redirected. Your job **this session** is NOT to rebuild the whole product. It is to:

1. **Rebuild `docs/ROADMAP.md`** around the new strategy, grounded in the actual current state of the code.
2. **Author the strategy/architecture documentation** the rebuild depends on.
3. **Lay down non-breaking scaffolding** (config + typed stubs + tests) that later sessions will build against — with **zero behaviour change** to the shipped swimming product.

Do exactly this scope. Feature implementation happens in later sessions, driven by the roadmap you produce.

---

## 1. Ground yourself first (before editing anything)
- Read `CLAUDE.md`, `README.md`, `START_HERE.md`, `GLOSSARY.md`.
- Read `docs/ROADMAP.md` **and everything it references** (`ARCHITECTURE.md`, `EXTENSION_GUIDE.md`, `CHANGELOG.md`, `FEATURE_INVENTORY.md`, the appendices), plus `.github/workflows/roadmap-autoupdate.yml` and `scripts/roadmap_autoupdate.py` so you understand the auto-update machinery and the `roadmap: <ID> <status>` commit-trailer convention.
- Read the research report I have placed at **`docs/research/ROADMAP_RESEARCH_2026.md`** — this is your evidence base (strategy in Part A, architecture in Part B, the ~55-repo catalogue in Part C, synthesis/phases/licensing verdicts in Part D).
- Survey `src/mediahub/` to learn the **real** module layout. Note especially the existing `recognition/` vs `recognition_swim/` split, and modules like `context_engine/`, `content_engine/`, `workflow/`, `brand/`, `theming/`, `graphic_renderer/`, `remotion/`, `voice/` — the new concepts must map onto these where they already exist, not spawn a parallel structure.
- **Produce a short written plan before editing.** Verify against the actual code; do not assume.

---

## 2. The strategic reframe (the "why")
- **The hub is a content-strategy brain**, not a results parser. It assesses what a given sports team should post, drafts it, and readies it for a human to review and then export/download for manual posting.
- **Results ingestion is one spoke among many** — demote it from the product's identity.
- **Multi-sport and multi-tenant.** Different sports need different post sets (swimming ≠ basketball) with meaningful crossover. One workspace per team.
- **Human-approval-gated by default, with a per-content-type toggle** that sets any single post type's review disposition (draft-only vs requires human approval before content is exported).
- **Three-source intelligence:** the team's own signals (past posts, engagement, brand voice) + external signals (fixtures, results, news, peer clubs, trends) + direct input (onboarding answers, goals, blackout dates).
- **No hidden fees / truly-free self-host is a hard product constraint**, not a nice-to-have. Keep it visible in every phase.

---

## 3. Primary deliverable — rebuilt `docs/ROADMAP.md`
Rewrite it so that:
- It is organised around the report's **Phase 0–5** (0: de-risk licensing/cost · 1: strategy brain + post-type taxonomy + sport profiles · 2: autonomy toggles + orchestration backbone · 3: broaden ingestion beyond swimming · 5: local-AI substitution). These **supersede** the old Parity → Distinction → Leadership spine; keep one line noting that lineage.
- It reflects **actual current state**, not the report's aspirations. As a *starting hypothesis to verify against the code*: shipped = brand-DNA/guidelines ingestion, voice imitation, the AI operating profile, the adaptive theming engine (§1.6), swim recognition, `graphic_renderer` (Playwright→PNG), Remotion reels, `edge-tts` voiceover, content packs. Not yet shipped = the content-strategy brain as hub, multi-sport beyond swimming, per-content-type review-disposition toggles (draft-only vs requires human approval before export), the local-AI substitution layer. Confirm each against the code and mark items with the existing badges (✅ done · 🔵 in progress · ⚠️ stuck · ❌ not started).
- **Each phase** carries: goal, **exit criterion**, the features to build, the open-source building blocks to use (each with its **license + free/paid verdict**), and cross-phase dependencies.
- **Preserve all existing mechanics:** the badge legend, the plain-English "in plain words" intro, and the `roadmap: <ID> <status>` trailer convention. Assign new **stable IDs** to new phases/items. **Do NOT edit content inside the auto-generated blocks** `<!-- ROADMAP:LAST_UPDATED -->…<!-- /ROADMAP:LAST_UPDATED -->` and `<!-- ROADMAP:ACTIVITY -->…<!-- /ROADMAP:ACTIVITY -->`; the GitHub Action owns those.

---

## 4. Secondary deliverables — supporting docs + non-breaking scaffolding

**New docs** (each with a plain-English intro then a technical body, matching the `START_HERE`/`GLOSSARY` house style):
- `docs/POST_TYPE_TAXONOMY.md` — universal post types vs sport-specific ones; how a sport profile parameterises (enabled / data inputs / template set / default autonomy). Give concrete tables for **swimming, football/soccer, basketball, running/athletics**.
- `docs/SPORT_PROFILES.md` — the sport-profile concept, its schema, and a step-by-step "how to add a new sport."
- `docs/ARCHITECTURE_TARGET.md` — the hub-and-spoke target architecture; **map each component onto existing `src/mediahub/` modules** (e.g. strategy brain ≈ `context_engine` + `content_engine` + `workflow`; sport adapters generalise `recognition_swim`), and identify the **minimal** new modules needed. Name the orchestration backbone (Temporal, MIT) and the local-AI substitution layer (Ollama / Piper / whisper.cpp / rembg / Satori).
- `docs/DEPENDENCY_LICENSING.md` — the **ADOPT NOW / ADOPT WITH CAUTION / AUDIT BEFORE USE / AVOID** register from the report's Part D, plus the repo's current dependencies with their hidden-fee flags and **free substitutes**: Remotion (Company License → Satori+FFmpeg fallback), `edge-tts` (cloud endpoint → Piper), `replicate` (paid → `rembg` local), hosted Anthropic/Gemini keys (→ Ollama local).

**Scaffolding (additive only; no runtime behaviour change; must not break tests):**
- `data/sport_profiles/swimming.yaml` plus one second example (`basketball.yaml` or `football.yaml`) capturing post types, data inputs, template namespace, and default autonomy level per type. (Mirror how `data/` already holds ontology/voices/brand kits.)
- `src/mediahub/sport_profiles/` — a typed loader + schema (dataclasses/pydantic, consistent with the repo's style) and the `AutonomyLevel` enum, with **unit tests**. Do **not** wire it into runtime behaviour yet unless the wiring is trivial and provably safe.
- Describe (in docs, not by refactoring working code) how the `recognition`/`recognition_swim` split generalises into a **sport-adapter pattern**.

---

## 5. Hard constraints / guardrails
- **Do not delete, rewrite, or break working swimming functionality.** Run the test suite; keep it green.
- **No new mandatory paid dependency.** Anything paid (Remotion Company License, Replicate, hosted LLM keys) must be **optional**, behind a flag/env var, with a documented **free default**.
- **Do not fork or embed AGPL code** (Postiz, MinIO, MediaCMS) into this repo. Reference them only as external services across a network boundary, and say so explicitly in the docs.
- **Never reference, cite, or research `ANAS727189/MediaHub`** — it is an unrelated same-named project; any claim derived from it is wrong.
- **Trust the research report as a starting point, but verify any license yourself before wiring a dependency in** (the report marks many as "verify"). Separate **code license** from **data/model license** (e.g. StatsBomb data terms, Coqui XTTS non-commercial model).
- **Preserve plain-English accessibility** — non-coders read this project.
- **Honor everything in `CLAUDE.md`.**

---

## 6. Working method
- Work on a branch: `claude/roadmap-rebuild`.
- Plan first, then make **small, reviewable commits** with clear messages; use the `roadmap: <ID> <status>` trailer where it applies.
- Add every new term (sport profile, strategy brain, spoke, autonomy level, guardrail, three-source intelligence) to `GLOSSARY.md`.
- Run the full test suite **and** the pre-commit / lint hooks (`ruff`, `stylelint`, etc.); fix anything you touch.
- Finish with a `CHANGES` summary covering: what changed, the new doc map, the new roadmap IDs, and a **recommended ordered backlog of the next Claude Code sessions** — roughly one per roadmap phase, each with its own exit criterion.

---

## 7. Acceptance criteria (self-check before finishing)
- [ ] `docs/ROADMAP.md` is reorganised around Phase 0–5, badges reflect **verified** current state, mechanics + auto-generated blocks + trailer convention are intact, and every phase has a goal, exit criterion, building blocks (with license/free-paid verdicts), and dependencies.
- [ ] All four new docs exist, match house style, and cross-link each other and the research report.
- [ ] `docs/POST_TYPE_TAXONOMY.md` has concrete tables for swimming, football, basketball, and running.
- [ ] `data/sport_profiles/` has ≥2 profiles; `src/mediahub/sport_profiles/` has a typed loader + `AutonomyLevel` enum + passing unit tests; nothing is wired into runtime behaviour.
- [ ] `docs/DEPENDENCY_LICENSING.md` reproduces the ADOPT/CAUTION/AUDIT/AVOID register and flags Remotion, edge-tts, Replicate, and hosted LLM keys with free substitutes.
- [ ] No new mandatory paid dependency; no AGPL code embedded; no reference to the misidentified repo.
- [ ] Full test suite and lint hooks pass; `GLOSSARY.md` updated; `CHANGES` summary + next-session backlog written.
