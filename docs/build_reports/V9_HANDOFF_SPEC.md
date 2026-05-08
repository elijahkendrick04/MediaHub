# V9 — Master Handoff Package Spec

Source: `/home/user/workspace/swim-content/` (live MediaHub project, runs at https://mediahub.pplx.app)
Target: `/home/user/workspace/mediahub-export/` (clean repo to be ZIPped)

## NON-NEGOTIABLE RULES

1. **Preserve everything.** Do NOT simplify, rebuild, redesign, or remove any module. Move + rewire only.
2. **The live workspace stays untouched.** Work entirely in `mediahub-export/`. Never modify files in `swim-content/`.
3. **Every legacy package preserved verbatim.** `swim_content/`, `swim_content_pb/`, `swim_content_v5/`, `engine_v4/`, `legacy_scripts/`, `app_v3.py`, `templates/home_v2.html`, etc. all go into `legacy/` directory unchanged.
4. **Deployment configs include Docker.** The user wants this transferable outside Perplexity, including via Docker.
5. **Five real audits.** Each is a 10-step concrete checklist comparing the export to the live source. PASS/FAIL per item with evidence.

## Repo structure

```
mediahub-export/
  README.md
  LICENSE
  pyproject.toml
  requirements.txt
  Procfile
  Dockerfile
  docker-compose.yml
  render.yaml
  fly.toml
  vercel.json
  Makefile
  .env.example
  .gitignore
  .dockerignore
  .editorconfig
  src/mediahub/
    __init__.py
    web/                  ← was swim_content_v4/
    pipeline/             ← was swim_content_v4/pipeline_v4.py + bridges (move FILES, not the package)
    interpreter/
    recognition/
    recognition_swim/
    canonical/
    content_pack/
    content_pack_visual/
    voice/
    brand/
    workflow/
    club_platform/
    pb_discovery/
    context_engine/
    media_ai/
    media_library/
    media_requirements/
    venue_search/
    inspiration/
    creative_brief/
    graphic_renderer/
    web_research/
    history/
  data/
    ontology/
    voices/seed/
    patterns.jsonl
    brand_kits/.gitkeep
    discovered/.gitkeep
    secrets.json.example
  scripts/
  tests/
  samples/
    learning_corpus/INDEX.csv (keep), MISM-2024-Results.pdf (keep), 3-5 representative ZIP/PDF only
  dist/public/             ← static landing page
  legacy/
    swim_content/
    swim_content_pb/
    swim_content_v5/
    engine_v4/
    legacy_scripts/
    app_v3.py
    templates_v4/
    templates/             ← old home_v2.html / upload_v3.html
    sample_data_v4/
    smoke5.py, smoke_test5.py, run_with_demo.py.disabled if exists
  docs/
    ARCHITECTURE.md
    SYSTEM_FLOW.md
    DETECTOR_BUS.md
    RANKING.md
    PB_VERIFICATION.md
    UPLOAD_TO_CARDS.md
    EXTENSION_GUIDE.md
    DEPLOYMENT.md
    ROADMAP.md
    KNOWN_ISSUES.md
    TECHNICAL_DEBT.md
    INVENTORY.md
    AUDIT_REPORTS.md
    ASSUMPTIONS.md
    FEATURE_INVENTORY.md
    ROUTE_INVENTORY.md
    API_INVENTORY.md
    ENV_INVENTORY.md
    DETECTOR_INVENTORY.md
    PROMPT_INVENTORY.md
    SYSTEM_MAP.md
    DEPENDENCY_MAP.md
    CHANGELOG.md          ← V1 → V8.2 changelog from existing build reports
```

## Phase-by-phase plan

### Phase A — Inventory + copy (mechanical)
1. Write a script `scripts/build_export.py` that: walks the source workspace, classifies every file, and copies into `mediahub-export/` per the structure above.
2. Skip these from the export (caches/runtime/secrets):
   - `__pycache__/`, `.pytest_cache/`
   - `.cache/` (PB lookup runtime)
   - `runs_v4/*.json` (runtime), `runs_v4/*/visuals/*` (rendered PNGs)
   - `uploads_v4/*` (uploaded blobs)
   - `data/discovered/clubs/*.json` (engine-discovered runtime data; keep dir + .gitkeep)
   - `data/discovered/swimmers/*`, `data/discovered/meets/*`, `data/discovered/pbs/*`
   - `data/discovered_sources.jsonl` (regenerated)
   - `data/secrets.json` (NEVER include — write `.example`)
   - `smoke_v8_output/` (runtime artefacts)
   - `node_modules/` if any
   - `.git/` if any (start fresh)
   - `static/`-ephemeral things — but KEEP `dist/public/`
   - Everything in `samples/learning_corpus/` EXCEPT INDEX.csv + 5 representative samples (1 PDF, 1 ZIP, 1 HTML, 1 DOCX, 1 image) covering format diversity
3. KEEP everything else, including: all V*_BUILD_SPEC.md, V*_FIX_REPORT.md, V*_INTEGRATION_REPORT.md (move to docs/build_reports/)

### Phase B — Restructure live source into src/mediahub/
1. Each top-level package becomes `src/mediahub/<package>/`:
   - `swim_content_v4/` → split into:
     - `src/mediahub/web/` (web.py + ai_caption.py + secrets_store.py + brand_kit_upload.py + club_discovery.py)
     - `src/mediahub/pipeline/` (pipeline_v4.py, interpreter_bridge.py, pb_bridge.py)
     - `src/mediahub/web/__main__.py` containing `from .web import app; if __name__ == "__main__": app.run()` for `python -m mediahub.web`
   - All other live packages move directly: `recognition/`, `recognition_swim/`, `canonical/`, `interpreter/`, `voice/`, `brand/`, `workflow/`, `club_platform/`, `pb_discovery/`, `context_engine/`, `media_ai/`, `media_library/`, `media_requirements/`, `venue_search/`, `inspiration/`, `creative_brief/`, `graphic_renderer/`, `content_pack/`, `content_pack_visual/`, `web_research/`, `history/`, `research/`
2. Top-level `src/mediahub/__init__.py` adds re-export shims so absolute imports keep working: e.g. `import recognition` should still resolve in legacy code paths via `sys.modules["recognition"] = mediahub.recognition`.

### Phase C — Rewire imports
1. Walk every `.py` in `src/mediahub/` and rewrite absolute imports of the package names above to `from mediahub.X import ...`.
2. Inside `legacy/`, do NOT rewrite — preserve verbatim.
3. Update test imports in `tests/` to use `mediahub.*`.

### Phase D — Deployment configs
- `Procfile`: `web: gunicorn mediahub.web.app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 300`
- `Dockerfile`: Python 3.12-slim base, install playwright + chromium for graphic rendering, copy src + data, expose 5000, gunicorn entrypoint
- `docker-compose.yml`: single web service + bind-mount `data/` for persistence
- `render.yaml`: Render.com one-click deploy spec
- `fly.toml`: Fly.io spec
- `vercel.json`: static-only frontend (`dist/public/`) with note that backend deploys elsewhere
- `Makefile`: `install`, `test`, `run`, `build`, `clean`, `deploy-render`, `deploy-fly`
- `.env.example`: every env var the code references — `ANTHROPIC_API_KEY`, `REPLICATE_API_TOKEN`, `PHOTOROOM_API_KEY`, `MEDIAHUB_CUTOUT_PROVIDER`, `PORT`, `FLASK_ENV`, etc.
- `pyproject.toml`: standard PEP 621 metadata + `mediahub` package + console_script `mediahub-web = mediahub.web.__main__:main`
- `.gitignore`: standard Python + `data/discovered/`, `data/secrets.json`, `runs_v4/`, `uploads_v4/`, `.cache/`, `__pycache__/`, `*.pyc`, `node_modules/`, `dist/`, `.env`

### Phase E — Documentation (all in docs/)
- **README.md** at repo root: ~3-page intro, quick start, badges, screenshot, link to docs/
- **ARCHITECTURE.md**: high-level diagram + spine: Upload → Interpreter → Pipeline → Recognition → Content Pack → Visual + Caption + Pack ZIP. Module responsibility table.
- **SYSTEM_FLOW.md**: step-by-step flow with code references.
- **DETECTOR_BUS.md**: how detectors register, how rank scores combine, how to add a new detector for a new sport.
- **RANKING.md**: ranker formula + meet-level scoring + tunable knobs in `data/ontology/`.
- **PB_VERIFICATION.md**: pb_discovery flow, trust ledger, cache layout, how confidence-aware language picks "NEW PB" vs "LIKELY PB".
- **UPLOAD_TO_CARDS.md**: trace a single upload from `/upload` POST to a card on `/review/<run_id>`.
- **EXTENSION_GUIDE.md**: how to add a new sport / new layout / new voice / new cutout provider safely.
- **DEPLOYMENT.md**: Docker, Render, Fly, self-hosted VPS, env-var setup, persistent volumes, scaling.
- **ROADMAP.md**: planned features by version (V8.3 open-water, V9 native AI image gen, V10 multi-sport, etc).
- **KNOWN_ISSUES.md** + **TECHNICAL_DEBT.md** + **ASSUMPTIONS.md**: explicit lists.
- **CHANGELOG.md**: concatenate the V*_FIX_REPORT.md / V*_BUILD_SPEC.md highlights into a single chronological CHANGELOG.

### Phase F — Inventories (auto-generated by script)
- `INVENTORY.md`: every file with size + 1-line purpose
- `ROUTE_INVENTORY.md`: dump Flask URL map programmatically
- `API_INVENTORY.md`: every `/api/*` endpoint with request/response schema
- `ENV_INVENTORY.md`: grep for `os.environ.get` and `os.getenv` and document each
- `DETECTOR_INVENTORY.md`: every file in `recognition_swim/achievements/` with its trigger condition
- `PROMPT_INVENTORY.md`: every Claude prompt template with its purpose
- `SYSTEM_MAP.md`: ASCII or mermaid diagram of module relationships
- `DEPENDENCY_MAP.md`: pip-deptree output + per-package dependents
- `FEATURE_INVENTORY.md`: every user-visible feature checked against the live app

### Phase G — 5 × 10-step audits
For each audit, write a 10-row checklist to `docs/AUDIT_REPORTS.md` with PASS/FAIL/NOTE columns + evidence. Real diffs, not rubber stamps.

1. **Architecture completeness audit** — 10 modules in source vs 10 modules in export
2. **Frontend / page / component audit** — 10 routes/pages live vs export
3. **Backend / API / data-flow audit** — 10 API endpoints + the upload→pack flow
4. **Detector / PB / ranking logic audit** — 10 detectors + PB rules + ranker constants
5. **Deployment / env / setup audit** — 10 commands run cleanly (`python -c "import mediahub"`, `pytest`, `docker build`, `make install`, `gunicorn` startup, etc.)

For audits 1-4: compare file lists / line counts / function presence between source and export.
For audit 5: actually `python -c "from mediahub.web.app import app"` and `python -m pytest tests/ -x -q --co` (collection only).

If any audit fails, FIX before finalising.

## Deliverables
1. `mediahub-export/` directory fully populated
2. `mediahub-export/docs/AUDIT_REPORTS.md` showing all 5 audits PASS
3. Run `pytest -x -q --co` from inside `mediahub-export/` and confirm tests collect (≥340 tests)
4. Write `V9_HANDOFF_REPORT.md` to `/home/user/workspace/swim-content/` with summary + top-level inventory + audit summary

DO NOT zip — the parent agent will handle zipping + sharing.

## Anti-shortcut rules
- Do not skip moving any package. Every package in the source must appear in the export under either `src/mediahub/` or `legacy/`.
- Do not invent files. If something doesn't exist in source, document it as missing rather than fabricating.
- Do not redact build reports — move them all to `docs/build_reports/`.
- For audits, evidence MUST be concrete (e.g. "source has 23 files in recognition_swim/achievements/, export has 23 — PASS").
