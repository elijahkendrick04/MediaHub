# MediaHub — Claude Code Project Guide

## What is MediaHub?

MediaHub is a scalable club/team/society content automation engine. The current wedge is swimming results-to-content automation, but the broader vision is a sport-agnostic, org-agnostic intelligence layer:

**Structured input → meaningful moments detected → ranked → branded → ready-to-post content**

Target users: sports clubs, university societies, sports teams, businesses, committee members, coaches, social media volunteers.

The system should not become a manual agency or a Canva template shop. The defensible layer is intelligence:
- Ingest structured or semi-structured data (results files, PDFs, free text)
- Understand what matters (PBs, medals, trends, first-times)
- Detect achievements and moments
- Rank content-worthiness with confidence scores
- Select appropriate formats (feed, stories, reels, spotlights)
- Apply club branding (colours, logos, tone)
- Generate human-sounding captions
- Preserve explainability and source-grounding
- Keep human approval before publishing

## Project Structure

```
src/mediahub/          — Main Python package
  web/web.py           — Flask monolith (~5000 lines), all routes
  web/club_profile.py  — ClubProfile dataclass + persistence
  media_ai/llm.py      — Cloud LLM wrapper (Gemini/Claude with provider failover)
  club_platform/       — Content types, stubs, athlete spotlight
  brand/               — BrandKit, tone system
  workflow/            — CardStatus, WorkflowStore, content pack
  media_library/       — Media asset store
tests/                 — pytest suite
data/                  — Runtime data (DB, runs, cache)
```

## Key Architecture Conventions

- **Cloud-hosted SaaS** — MediaHub runs on the operator's managed deployment (Render is the reference target). Customers access via browser; there is no customer-facing local install path.
- **Flask monolith** — all routes in `web.py` via f-string Jinja2 templates
- **DATA_DIR env var** — all storage paths derived from `DATA_DIR`; never hardcode `Path("data/...")`
- **url_for() always** — never hardcode URL paths; use `url_for()` for all internal links
- **Fonts are self-hosted on every surface, never the Google Fonts CDN** — the brand typefaces are served first-party across all three public surfaces: the web UI (`web/static/theme/fonts.css` → `web/static/fonts/*.woff2`), the still-graphic renderer (`graphic_renderer/layouts/_shared.css` → `layouts/fonts/*.woff2`, rewritten to `file://` at render time), and the Remotion reels (`remotion/src/fonts.ts` via `staticFile()` from `remotion/public/fonts/`, held by `delayRender`/`continueRender` until `document.fonts.ready`). This is reliability + EU/UK GDPR (the Munich ruling on CDN-served Google Fonts). Do NOT reintroduce a `fonts.googleapis.com`/`gstatic` `<link>`, `@import`, or webfont loader. Refresh via `scripts/fetch_fonts.py` + `scripts/regen_fonts_css.py` (web) and `scripts/fetch_renderer_fonts.py` (renderer, which also feeds the reel); `tests/test_self_hosted_fonts.py` guards against the CDN creeping back on any surface.
- **Gemini-first, AI required, never heuristic-substituted** — Gemini is the embedded AI for every AI-driven surface (captioning, brand interpretation, palette resolution, creative direction, operating-profile derivation, media description tagging). Anthropic is the secondary failover provider via `ai_core/llm.py`. When no provider is configured, surface `ClaudeUnavailableError` / `ProviderNotConfigured` so the operator sees an honest error. Do NOT reintroduce regex/template heuristic fallbacks — a fake caption, stub profile, or made-up palette is worse than a clear error. Any new judgement-based surface (which photo to pick, which tone, which copy) MUST go through `media_ai.llm` / `ai_core.llm`, never through hardcoded rules.
- **Critical engine stays deterministic** — parsers (`interpreter/`, `pb_discovery/parse_pbs.py`), detectors (`recognition/`, `recognition_swim/achievements/`), the ranker (`legacy/swim_content_v5/ranker_v3.py`), and pixel/colour-science maths (`theming/logo_chip.py`, mechanical contrast / CIEDE2000) are deliberately NOT AI-replaced. Accuracy of "is this a PB?" / "which card outranks which?" matters more than flexibility; LLMs are too non-deterministic for these. Do NOT propose Gemini-ifying parsers, detectors, ranker, or colour-science modules without explicit user approval.
- **Mathematical scoring stays deterministic** — e.g. `media_library/selector.py:score_asset` uses fixed weights to pick the best photo for a card. This is fast, reproducible, and well-tuned; replacing with an LLM call per asset would add seconds per content pack with no quality win.
- **Provider failover is online, not local** — `ai_core/llm.py` walks Gemini → Anthropic on transient errors. This is multi-provider redundancy, not a local fallback.
- **Server-side rendering, not customer-side** — Remotion (video) and Playwright/Chromium (HTML → PNG) run inside the deployed container on the operator's server. They are not "local" in the customer-machine sense — the customer accesses a hosted URL. Gemini cannot replace these (Imagen and Veo are generative, not structured-data renderers).
- **Cutout provider naming** — `MEDIAHUB_CUTOUT_PROVIDER=server` runs in-process rembg on the deployed server (default); `replicate` / `photoroom` are cloud-API alternatives. The legacy values `local` and `rembg` are accepted aliases for `server`. Never use the word "local" to describe the on-server backend in user-facing copy or docs; it's a deployment-side cutout backend.
- **Feature flags** — `_club_platform_ok`, `_v73_ok`, `_v8_ok` guard optional features
- **Removing routes or data structures is allowed, but gated** — you may remove or replace an existing route or data structure when an update genuinely needs it; don't just pile on additively. When you do, follow the process in *"Changing the engine: removing or replacing routes & data structures"* below — a 15-step breakage check **before** removal, a 15-step verification **after** removal and replacement, and a dead-code sweep at the end of every engine change.

## Decision governance — the Council decides

Non-trivial decisions in this repo are made by **the Council**, not by a single
voice (human or AI) acting on a hunch. The Council is Karpathy's LLM Council
methodology, wired into Claude Code as the invocable **`/llm-council`** skill
(`.claude/skills/llm-council` → `autotest/skills/llm-council/SKILL.md`; embedded
in-process as `autotest/council.py`): five advisors argue from clashing angles,
peer-review each other anonymously, and a chairman writes a binding verdict. **The
verdict — not your first instinct — is what you build.** Convene it with `/llm-council`
or a trigger phrase ("council this", "pressure-test this"). Full policy:
**`docs/COUNCIL_GOVERNANCE.md`**.

- **Convene the Council BEFORE acting** on any council-gated decision: architecture or
  data-model changes; removing/replacing a route or data structure (the council runs
  *before* the 15-step breakage check below); roadmap priority/sequencing ("what to
  build next"); a choice between ≥2 credible approaches where the wrong pick costs more
  than an afternoon; new AI judgement surfaces or anything touching the
  deterministic-engine boundary; and anything outward-facing or hard to reverse.
- **Don't council trivial work** — typo/format/mechanical-refactor fixes, single-
  obvious-fix bugs, or implementing a step the Council *already* decided (cite that
  decision instead). Counciling trivia dulls the mechanism for the decisions that matter.
- **Record the decision.** Every council-gated change writes a transcript +
  HTML report under `autotest/reports/council/`, and the **PR body links that decision
  record**. If hands-on work invalidates a premise the Council assumed, write the
  deviation and its reason *into the verdict* — never deviate silently.
- The Council **cannot approve** Gemini-ifying the deterministic engine (parsers,
  detectors, ranker, colour-science) — that still requires explicit user sign-off — but
  it must be consulted on the framing.

## Changing the engine: removing or replacing routes & data structures

Removing or replacing existing routes and data structures is allowed when an update genuinely needs it — prefer a clean replacement over piling on additively. But because `web/web.py` is a large monolith with f-string templates, persisted `DATA_DIR` state, and feature-flagged surfaces, every removal/replacement MUST be gated by both checklists below. Do not skip steps to save time.

### A. 15-step breakage check — run BEFORE removing or replacing

1. **Pin the target.** Write down the exact route path / symbol / data structure (name, module path, signature, fields) being removed or replaced.
2. **Define the replacement.** State what replaces it and its new shape/signature — or justify dropping it outright.
3. **Whole-repo grep.** Search the entire repo for the name: imports, calls, attribute access, dict keys, string literals.
4. **Routes & links.** Search `web/web.py` for the route and every `url_for()` that targets it.
5. **Templates.** Search the f-string Jinja2 templates for the route, field names, and variables tied to the structure.
6. **Frontend/JS callers.** Find `fetch`/XHR/form posts to the route, including the motion/reel API endpoints.
7. **Persistence.** Check whether data stored under `DATA_DIR` (runs, DB rows, cached JSON, content packs) carries the field/shape.
8. **Feature flags.** Check whether the target is guarded by, or guards, `_club_platform_ok` / `_v73_ok` / `_v8_ok`.
9. **AI surfaces.** Check whether any `media_ai.llm` / `ai_core.llm` prompt or response parser produces or consumes the field/shape.
10. **Deterministic engine.** Check parsers (`interpreter/`, `pb_discovery/`), detectors (`recognition/`, `recognition_swim/`), the ranker, and colour-science for dependencies.
11. **Dynamic references.** Search for indirect access a literal grep misses: `getattr`, `**kwargs`, config keys, serialized status/enum strings.
12. **Tests.** Find every test in `tests/` that imports, mocks, patches, or asserts on the target.
13. **Back-compat data.** Identify old persisted runs/profiles still carrying the old shape; decide migrate-vs-tolerate.
14. **Coverage map.** Map each caller found above to its replacement (1:1), or record explicitly why a caller is dropped.
15. **Breakage list.** Write the explicit list of what would fail (import / route / template / parse / test) if the target were removed without the replacement in place.

### B. 15-step safe-removal verification — run AFTER removing and replacing

1. **Zero stray refs.** Re-grep the whole repo for the old name — confirm no leftover references remain.
2. **No dangling links.** Confirm no `url_for()`, template link, or JS call still points at a removed route.
3. **Callers migrated.** Confirm every caller from the breakage map now uses the replacement.
4. **Imports resolve.** Import the app and affected modules — no `ImportError` / `NameError` / `AttributeError`.
5. **Full test suite.** Run `python -m pytest tests/ -q` — expect ~253 passed / ~34 skipped, with no *new* failures.
6. **No test cheating.** Confirm no test was deleted, skipped, or weakened just to go green.
7. **Route works.** Exercise each affected route end-to-end (request → expected response/status).
8. **Templates render.** Confirm affected pages render with no undefined-variable / missing-field errors.
9. **Persistence loads.** Confirm old persisted runs/profiles still load (or are migrated) without error.
10. **Flags still gate.** Confirm `_club_platform_ok` / `_v73_ok` / `_v8_ok` behaviour is unchanged with the code gone.
11. **AI surfaces aligned.** Confirm prompts and parsers still produce/consume valid output for the new shape.
12. **Engine accuracy held.** Confirm parsers/detectors/ranker give identical output for the same input — no regression in "is this a PB?" or ranking.
13. **Primary flow.** Walk the core flow: upload → configure → process → review (cards, captions, confidence) → approve → export.
14. **No new exposure.** Confirm the change exposed no debug/admin route, secret, or IDOR, and didn't leak `ANTHROPIC_API_KEY`.
15. **Documented & clean diff.** Record the route/data-structure change and confirm the diff contains only intended edits.

### C. Dead-code sweep — at the end of every engine change

After any change to the engine (not only removals), remove the clutter and dead code it introduced or orphaned: unused imports, unreachable branches, orphaned helpers, commented-out blocks, now-unused data fields, and stale tests for behaviour that no longer exists. Do not leave back-compat shims, renamed `_unused` vars, or "removed"/"deleted" placeholder comments.

## Explicitly Excluded

- **Google Workspace / GWS** — Do NOT install or use `@googleworkspace/cli`, Gmail, Drive, Calendar, Sheets, Docs, Slides, Chat, or Admin automation. This exclusion is permanent unless the user explicitly requests it.
- **9router / gray-market LLM proxies** — Do NOT add [9router](https://github.com/decolua/9router) (or any similar AI-coding-tool proxy that routes through unofficial/"free" provider tiers) as a skill, a vendored dependency, a documented dev workflow, or a product component. MediaHub's AI path stays on official env-keyed providers via `ai_core/llm.py` / `media_ai/llm.py`, and customer LLM traffic is never routed through a third-party proxy. Rationale recorded in [`docs/adr/0002-reject-9router-integration.md`](docs/adr/0002-reject-9router-integration.md). This exclusion is permanent unless the user explicitly requests it.

---

## UI / Frontend work

MediaHub UI expectations:
- Avoid generic AI-looking SaaS patterns (grey cards, blue-300 buttons, Tailwind defaults)
- Build credible product UI for sports clubs, coaches, committee members, university societies — editorial/sport feel, not a toy demo
- Prioritise clear workflows: upload → configure → process → review → approve → export
- Support club branding, sponsor branding, result cards, athlete spotlights, meet recaps, story graphics
- Dark-first colour palette consistent with existing CSS variables (`--bg`, `--accent`, `--ink`, `--panel`)
- Strong hierarchy; obvious primary actions; polished empty/loading/error/success states
- Clear recognition explanations and confidence displays; unambiguous approval/rejection/export states
- No over-animation — motion only for feedback and hierarchy
- Mobile-aware but desktop-primary layout

The primary user flow to keep coherent: open app → upload meet results file → select club / brand kit / logo → run pipeline → review content pack (cards, captions, confidence scores) → edit caption, approve/reject → export/download.

## Code review focus

When reviewing your own changes before presenting them, check for: duplicated logic, functions doing too much, unused imports, missing error handling, fragile parsing logic, UI state bugs, inconsistent naming, security issues (XSS, injection, IDOR), and inefficient queries.

For MediaHub specifically, pay attention to:
- Result parsing logic (interpreter, adapters)
- PB detection and achievement ranking
- Confidence scoring
- Content generation pipeline
- Club profile / brand kit handling
- Export and approval state workflows
- "Why was/wasn't this card generated?" explainability logic

## Document & results processing

Relevant inputs: swim meet result PDFs, spreadsheets (XLS/XLSX/CSV), exported result files (HY3, SDIF, SportSystems), qualifying time documents, entry lists, heat sheets, historical performance files, brand guidelines, club profile documents.

Processing requirements:
- Extract tables accurately; preserve source provenance
- Validate parsed fields; detect uncertain or ambiguous rows
- Normalise swimmer names, event names, and times; preserve age group/category where available
- Separate raw extraction from cleaned canonical data
- Flag ambiguous results for human review — never silently guess; make uncertainty explicit
- Output machine-readable JSON for the recognition engine

Pipeline: raw file → parsed structured data → validated canonical data → achievement detections → ranked content opportunities → content pack.

## Security focus areas

- File upload validation (HY3, ZIP, PDF — prevent zip bombs, path traversal)
- Multi-tenant data isolation (run data must not leak between profiles)
- IDOR risks (run IDs, card IDs accessible without auth)
- XSS in generated captions (HTML-escaped output via `_h()`)
- Injection risks in filename handling and query params
- Exposed debug/admin endpoints
- Secrets leakage in UI or logs (`ANTHROPIC_API_KEY` must never appear in user-visible text)

Never run a live security test against the production Render deployment (mediahub-gzwc.onrender.com) or any customer environment without explicit written permission. Document findings; do not exploit beyond proof-of-concept.

## Database / data model direction

- Schema changes are deliberate and reviewable
- Queries must be index-aware; avoid `SELECT *`
- Design for multi-tenant SaaS (organisations as tenants)
- Store raw data, parsed data, recognition decisions, and final content separately
- Preserve audit trails for all generated outputs

The future data model should handle: organisations / clubs / societies / teams; users and roles; athletes / members; meets / events / competitions; raw result files; parsed results; historical personal bests; achievement detections with confidence scores; content recommendations and rankings; generated captions (with tone, voice, edit history); brand kits and media assets; approval states per card; export history; audit logs.

## External integrations

- Human approval must remain required before any external publishing — never auto-publish or auto-post
- Use least privilege for every integration; never connect external accounts without explicit approval
- Keep credentials out of source control — `.env` only

## Environment Variables

See `.env.example` for the full list.

**RULE — API keys are env/`.env` only, NEVER hard-coded.** Provider keys
(`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, …) must be read from the process
environment (loaded from the gitignored `.env`), never written as a literal in
any source file, test, comment, commit, log line, or pushed artifact. The
operator rotates the key by editing `.env` alone — no code change. This holds
for the autonomous tester/fixer too: they load `.env` via `autotest/_env.py`.
A key committed to the repo is a leak even if later removed.

## Running Tests

All test files pass. Run the full suite with no ignores:

```bash
# Full suite (current expectation: ~253 passed, ~34 skipped).
python -m pytest tests/ -q
```

Skips are all legitimate data-only gaps (missing corpus ZIPs, missing sample PDFs,
optional `reportlab` dependency) — no test file is structurally broken.

Previously-fixed files (now part of the passing suite):
- `tests/test_pb_discovery.py` — all mock.patch targets updated to canonical `mediahub.*` paths; real ledger pollution cleared
- `tests/test_corpus_recovery.py` — swim-count gate now scales with corpus size (`min(30_000, max(1_000, captured * 600))`) instead of a flat 30k

## Contributor / engineering setup

Engineering iteration and the Node + Remotion motion stack are documented in
`docs/DEVELOPMENT.md`. That file is contributor-only — it is not part of the
customer-facing product surface and must not be referenced as a "how to run
MediaHub" path.

## Motion-graphic / video output (Remotion)

MediaHub generates branded MP4 outputs via Remotion 4.x on the deployed
server:
- **Story cards** — 1080×1920, 6 seconds, one card per swimmer/achievement
- **Meet reels** — 1080×1920, 15 seconds, top-3 cards stitched with crossfades

The Node + Remotion stack lives at `src/mediahub/remotion/`. It is invoked
from Python via `src/mediahub/visual/motion.py`, which shells out to
`render.js` and caches outputs under `DATA_DIR/motion_cache/<hash>.mp4`.

Outputs are programmatic and data-driven (never static templates), club-branded
from the `BrandKit`, and use real athlete/team imagery where provided — no
synthetic AI-generated people unless explicitly requested.

### Routes

- `POST /api/runs/<run_id>/card/<card_id>/motion` — render a single story card MP4
- `POST /api/runs/<run_id>/reel` — render the meet reel from the top-N cards
  (default 3, capped at 5; pass `?n=4` to override)

Both endpoints serve the rendered MP4 directly with `Content-Type: video/mp4`.
Cache hits return the existing file (< 30s wall-clock); cold renders take
30–90s on the deployment's worker.

### Brand consistency

Motion compositions read the same `BrandKit` palette as the static graphic
renderer and honour the per-card `variation_seed` from
`src/mediahub/creative_brief/generator.py` (`auto_variation_seed_for`), so
the motion render of a given card visually aligns with its still graphic.

## Deployment

Deployed on Render via `render.yaml`. Docker-compatible via `Dockerfile`.
Branch model: feature branches from `dev`. Merges to `main` may happen
autonomously without human approval, gated only on green CI — `main` is a
trunk that auto-deploys to Render production, so a red build must never be
merged. (This replaces the former human-approval-before-`main` rule.)
The product is delivered to customers as a hosted web application — there is
no customer-facing self-host or local-install path.

---

## MediaHub Product Principles (Standing Rules)

Manual work is acceptable only as a learning-stage concierge MVP. The long-term goal is a
repeatable content automation engine. Before building anything, ask:

- What is the repeatable system behind this?
- What can be automated without losing quality or trust?
- Would someone actually pay for this as a standalone feature?
- Does this strengthen or weaken the scalable business?
- Is this intelligence-layer work or manual agency work?

The intelligence layer is the moat:
- Ingest → detect → rank → brand → generate → approve → export
- Every step should be explainable and auditable
- Human approval before external publishing — always
