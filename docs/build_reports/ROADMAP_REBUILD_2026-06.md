# CHANGES — Roadmap rebuild (multi-sport, autonomy-first)

Session summary for the rebuild that reorganises MediaHub's roadmap around the
multi-sport, autonomy-first strategy. Scope was **docs + non-breaking scaffolding
only** — zero behaviour change to the shipped swimming product. Feature work is
deferred to later sessions (see the backlog below).

Decision record: [`../adr/0004-roadmap-rebuild-multisport-autonomy.md`](../adr/0004-roadmap-rebuild-multisport-autonomy.md).
Evidence base: [`../research/ROADMAP_RESEARCH_2026.md`](../research/ROADMAP_RESEARCH_2026.md).

---

## 1. What changed

**Rebuilt**
- `docs/ROADMAP.md` — reorganised around **Phase 0–5**. Preserves the badge legend,
  plain-English intro, the `roadmap: <ID> <status>` trailer convention, and the
  auto-generated marker blocks (`LAST_UPDATED` / `ACTIVITY`, untouched). Current
  state re-verified against the code and badged. Appendices A/B/C retained with a
  lineage/bridging note; the old Parity → Distinction → Leadership spine is
  superseded.

**New docs**
- `docs/POST_TYPE_TAXONOMY.md`, `docs/AUTONOMY_MODEL.md`, `docs/SPORT_PROFILES.md`,
  `docs/ARCHITECTURE_TARGET.md`, `docs/DEPENDENCY_LICENSING.md`.
- `docs/adr/0004-roadmap-rebuild-multisport-autonomy.md` (decision record).
- `GLOSSARY.md` — added strategy terms (strategy brain, hub-and-spoke, spoke, sport
  profile, post type, autonomy level, guardrail, three-source intelligence, kill switch).

**New scaffolding (inert — not wired into runtime)**
- `src/mediahub/sport_profiles/` — `AutonomyLevel` enum (`autonomy.py`),
  `SportProfile`/`PostTypeConfig` dataclasses (`schema.py`), YAML loader
  (`loader.py`), `__init__.py`, `README.md`.
- `data/sport_profiles/{swimming,football}.yaml` + `README.md`.
- `tests/test_sport_profiles.py` (23 tests; includes a "gated by default" safety
  invariant — no shipped profile may default to `fully_autonomous`).
- `PyYAML>=6.0` declared in `requirements.txt` + `pyproject.toml` (MIT, free; the
  loader's only new dep).

**Housekeeping**
- Renamed the research report from its auto-generated `compass_artifact_*` export
  name to the canonical `docs/research/ROADMAP_RESEARCH_2026.md` (nothing referenced
  the old name).

**Verification**
- Full suite green: **2826 passed / 1 skipped** baseline at rebuild; **2836 passed /
  1 skipped** after merging `main` (PR214), including the 23 new sport-profile tests.
- All seven pre-commit hooks pass on the changed files (trailing-whitespace, EOF,
  large-files, check-yaml, merge-conflict, ruff, ruff-format).
- The new roadmap IDs (`P0`–`P5`, `P0.1`…) and the legacy IDs (`PAR-*`, `SEQ-*`,
  `1.6`) all resolve against `scripts/roadmap_autoupdate.py`; its unit tests pass.

## 2. New doc map

```
docs/
  ROADMAP.md ................ the Phase 0–5 plan (rebuilt)
  POST_TYPE_TAXONOMY.md ..... universal vs sport-specific post types; tables for
                              swimming, football, basketball, running
  AUTONOMY_MODEL.md ......... AutonomyLevel states, what the toggle controls,
                              human-in-the-loop checkpoints, guardrails
  SPORT_PROFILES.md ......... the sport-profile concept, schema, "add a new sport"
  ARCHITECTURE_TARGET.md .... hub-and-spoke target mapped onto existing modules
  DEPENDENCY_LICENSING.md ... ADOPT/CAUTION/AUDIT/AVOID register + current-dep
                              hidden-fee flags + free substitutes
  adr/0004-...md ............ the decision record (PR links this)
  research/ROADMAP_RESEARCH_2026.md ... the evidence base (renamed)
GLOSSARY.md ................. + strategy terms
src/mediahub/sport_profiles/  typed loader + AutonomyLevel (inert)
data/sport_profiles/*.yaml .. swimming + football profiles
```

All five new docs cross-link each other, the research report, and `ROADMAP.md`.

## 3. New roadmap IDs

Verified compatible with the `roadmap: <ID> <status>` auto-updater.

| Phase | ID | Items |
|---|---|---|
| 0 — De-risk licensing & cost | `P0` | `P0.1`–`P0.5` |
| 1 — Strategy brain + taxonomy + sport profiles | `P1` | `P1.1`–`P1.5` |
| 2 — Autonomy toggles + orchestration | `P2` | `P2.1`–`P2.4` |
| 3 — Broaden ingestion spokes | `P3` | `P3.1`–`P3.4` |
| 4 — Direct-to-platform publishing | `P4` | `P4.1`–`P4.4` |
| 5 — Local-AI substitution everywhere | `P5` | `P5.1`–`P5.5` |

Already-done items badged ✅ from verified current state: `P0.2` (rembg default),
`P1.1` (scaffolding), `P5.5` (rembg/MODNet cutout). In progress 🔵: `P0.3`, `P1.4`
(Gen Content Engine v2 — ADR-0001 / Appendix A). Legacy IDs (`PAR-*`, `SEQ-*`,
`Step N`, `1.6`) remain valid in the appendices.

## 4. Recommended ordered backlog (next sessions — one per phase)

Each is a focused session with its own exit criterion. Order respects the
cross-phase dependencies in `ROADMAP.md`.

1. **P0.1 — Remotion free fallback.** Add a Satori+FFmpeg reel path behind a flag;
   keep Remotion optional. *Exit:* a zero-license deployment renders reels. *(Biggest
   hidden-cost win; do first.)*
2. **P1.3 — Cross-source strategy brain.** Extend `content_engine`/`context_engine`
   into a three-source planner over sport profiles. *Exit:* a ranked, explainable
   content plan for ≥2 sport profiles (swimming + football/basketball).
3. **P1.4 — Generative Content Engine v2.** Run Appendix A (PAR-2/PAR-3/PAR-7 →
   SEQ-0 → SEQ-1). *Exit:* ≥6 structural archetypes; a ranked pool, not one card.
4. **P2 — Autonomy on Temporal.** Per-type toggle + guardrails + kill switch + audit
   trail. *Exit:* `fully_autonomous` publishes only when all guardrails + the
   confidence gate pass; the kill switch halts instantly.
5. **P3 — Second sport end-to-end.** `recognition_football`/`_basketball` adapter +
   a real data spoke (openfootball / nba_api). *Exit:* one non-swimming sport
   produces content end-to-end with its profile wired in.
6. **P4 — Free direct publishing.** Bluesky (AT Protocol) + Mastodon adapters;
   demote Buffer to optional. *Exit:* publish to ≥2 platforms incl. one genuinely
   free.
7. **P5 — Local AI everywhere.** Ollama (LLM) + Piper (TTS) + whisper.cpp (ASR).
   *Exit:* the full pipeline runs with no cloud keys configured.

Run a **pilot** (one real club, themed product) in parallel — see
[`../PILOT_PLAYBOOK.md`](../PILOT_PLAYBOOK.md).

> Each of P2–P5 (and any new sport) is Council-gated per
> [`../COUNCIL_GOVERNANCE.md`](../COUNCIL_GOVERNANCE.md): convene before the build
> and link the decision record from the PR.
