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
  media_ai/llm.py      — Claude wrapper (multi-tier fallback)
  club_platform/       — Content types, stubs, athlete spotlight
  brand/               — BrandKit, tone system
  workflow/            — CardStatus, WorkflowStore, content pack
  media_library/       — Media asset store
tests/                 — pytest suite
data/                  — Runtime data (DB, runs, cache)
```

## Key Architecture Conventions

- **Flask monolith** — all routes in `web.py` via f-string Jinja2 templates
- **DATA_DIR env var** — all storage paths derived from `DATA_DIR`; never hardcode `Path("data/...")`
- **url_for() always** — never hardcode URL paths; use `url_for()` for all internal links
- **Graceful degradation** — all LLM calls have heuristic fallbacks; never crash on missing API key
- **Feature flags** — `_club_platform_ok`, `_v73_ok`, `_v8_ok` guard optional features
- **Additive changes** — do not remove existing routes or data structures; extend safely

---

# Agent Skills Configuration

This project uses Claude/agent skills to improve UI quality, code quality, research, security validation, video generation, diagrams, and database design.

## Installed Skills

| Skill | Source | Status |
|-------|--------|--------|
| `frontend-design` | anthropics/claude-code | ✅ Installed |
| `browser-use` | browser-use/browser-use | ✅ Installed |
| `simplify` | Built-in Claude Code skill | ✅ Active |
| `code-reviewer` | Antigravity Awesome Skills | ✅ Installed |
| `remotion` + `remotion-best-practices` | Antigravity Awesome Skills | ✅ Installed |
| `valyu-best-practices` | valyuai/skills | ✅ Installed |
| Antigravity Awesome Skills | antigravity-awesome-skills | ✅ Installed (700+ skills) |
| `database-design`, `database-architect`, `postgresql-optimization` | Antigravity | ✅ Installed |
| `shannon` | unicodeveloper/shannon | ✅ Installed |
| `excalidraw-diagram` | coleam00/excalidraw-diagram-skill | ✅ Installed |

## Explicitly Excluded

- **Google Workspace / GWS** — Do NOT install or use `@googleworkspace/cli`, Gmail, Drive, Calendar, Sheets, Docs, Slides, Chat, or Admin automation. This exclusion is permanent unless the user explicitly requests it.

---

## Default Behaviours by Task Type

### UI / Frontend work

**Always apply `frontend-design` principles when building or modifying user-facing pages.**

MediaHub UI expectations:
- Avoid generic AI-looking SaaS patterns (grey cards, blue-300 buttons, Tailwind defaults)
- Build credible product UI for sports clubs, coaches, committee members, university societies
- Prioritise clear workflows: upload → configure → process → review → approve → export
- Support club branding, sponsor branding, result cards, athlete spotlights, meet recaps, story graphics
- The product should feel like a practical content operations tool, not a toy demo
- Dark-first colour palette consistent with existing CSS variables (`--bg`, `--accent`, `--ink`, `--panel`)
- Mobile-aware but desktop-primary layout

### Browser QA

**Use `browser-use` for testing deployed or local UI flows when visual/interactive verification is needed.**

Apply to:
- Upload flow (file → configure → pipeline → review)
- Content pack and approval workflows
- Export/download flows
- Checking for blank pages, 404s, broken routes
- Screenshot capture of UI issues
- Responsive layout verification

For MediaHub flows:
1. Open app / navigate to home
2. Upload meet results file
3. Select club, upload brand kit / logo
4. Run pipeline, wait for recognition
5. Review content pack (inspect cards, captions, confidence scores)
6. Edit caption, approve/reject cards
7. Export / download content pack

### After implementation: Code Review

**Always run a simplification and review pass before presenting final code.**

Use `simplify` skill or `code-reviewer` skill. The review must check:
- Duplicated logic
- Functions doing too much
- Unused imports
- Missing error handling
- Fragile parsing logic
- UI state bugs
- Inconsistent naming
- Security issues (XSS, injection, IDOR)
- Database query inefficiency

For MediaHub specifically, review:
- Result parsing logic (interpreter, adapters)
- PB detection and achievement ranking
- Confidence scoring
- Content generation pipeline
- Club profile / brand kit handling
- Export and approval state workflows
- "Why was/wasn't this card generated?" explainability logic

### Video / Reel generation

**Use `remotion` or `remotion-best-practices` when the user asks for video, reel, demo, or animated asset generation.**

MediaHub use cases:
- Animated meet recap videos
- Swimmer spotlight videos
- Weekend-in-numbers summary videos
- Sponsor-branded video assets
- Animated result cards for stories/reels
- Club announcement videos

Remotion generates programmatic video via React + `@remotion/core`. Requires Node.js.
- Do NOT build a full video system unless asked
- Do use Remotion for individual video assets on request
- Output should be MP4-ready compositions with branded colours, typography, and data

### Live research / current facts

**Use `valyu-best-practices` when the user needs current, live, or specialist data.**

Requires: `VALYU_API_KEY` environment variable.

MediaHub use cases:
- Current meet information and qualifying windows
- Venue/pool specifications
- Sports-specific context (governing bodies, records)
- Current public club/team social examples
- Industry/competitor research
- API and tooling research

**Rule:** Any factual claim from live research must preserve source links/citations in the response and in stored data where possible.

### Architecture and planning

**Use `architecture`, `brainstorming`, `debugging-strategies`, and `api-design-principles` skills for major system design work.**

Available from Antigravity Awesome Skills. Apply when:
- Planning repeatable workflows or pipeline stages
- Designing scalable multi-tenant SaaS architecture
- Debugging deployment issues
- Improving API boundaries between modules
- Writing technical documentation
- Planning new feature architecture

Use `c4-architecture-c4-architecture`, `c4-context`, `c4-container` for structured C4 diagrams.

### Database design

**Apply database design principles for all schema and query work.**

Available skills: `database-design`, `database-architect`, `database-admin`, `postgresql-optimization`, `postgres-best-practices`, `sql-optimization-patterns`.

MediaHub database principles:
- Schema changes are deliberate and reviewable
- Queries must be index-aware; avoid `SELECT *`
- Design for multi-tenant SaaS (organisations as tenants)
- Store raw data, parsed data, recognition decisions, and final content separately
- Preserve audit trails for all generated outputs

Future data model should handle:
- organisations / clubs / societies / teams
- users and roles
- athletes / members
- meets / events / competitions
- raw result files
- parsed results
- historical personal bests
- achievement detections with confidence scores
- content recommendations and rankings
- generated captions (with tone, voice, edit history)
- brand kits and media assets
- approval states per card
- export history
- audit logs

### Security validation

**Use `shannon` ONLY on authorised local or staging systems. Never against production. Never against systems you do not own.**

Shannon triggers: mention of "shannon", "pentest", "security audit", "vuln scan".

**Safety rules (non-negotiable):**
- Require explicit user confirmation before running any live security test
- Default target: `localhost` or a local Docker container
- Never test the production Render deployment (mediahub-gzwc.onrender.com) without explicit written permission
- Keep scope narrow and time-limited
- Document findings; do not exploit beyond proof-of-concept
- Use Docker isolation if the test requires network-level access

MediaHub security focus areas:
- File upload validation (HY3, ZIP, PDF — prevent zip bombs, path traversal)
- Multi-tenant data isolation (run data must not leak between profiles)
- IDOR risks (run IDs, card IDs accessible without auth)
- XSS in generated captions (HTML-escaped output via `_h()`)
- Injection risks in filename handling and query params
- Exposed debug/admin endpoints
- Secrets leakage in UI or logs (ANTHROPIC_API_KEY must never appear in user-visible text)

Also consider: `security-auditor`, `vulnerability-scanner`, `top-web-vulnerabilities`, `gha-security-review` from Antigravity.

### Diagrams

**Use `excalidraw-diagram` when planning major system changes, explaining data flows, or documenting architecture.**

Generate Excalidraw diagrams for:
- Results upload → content pack pipeline
- PB detection and achievement recognition flow
- Club brand kit → generated assets flow
- Human approval workflow
- Multi-tenant SaaS architecture
- Deployment architecture (Render, Docker)
- Image/video generation pipeline
- Data model / entity relationship diagram
- Future integrations architecture

Also available: `mermaid-expert` from Antigravity for Mermaid diagrams inline in Markdown.

---

## Environment Variables

See `.env.example` for the full list. Key additions for agent skills:

```bash
VALYU_API_KEY=vl-...          # Required for Valyu live research
```

## Running Tests

```bash
python -m pytest tests/ -q
# Exclude known pre-existing failures:
python -m pytest tests/ --ignore=tests/test_corpus_recovery.py \
  --ignore=tests/test_interpreter_smoke.py \
  --ignore=tests/test_no_hardcode_in_live_paths.py \
  --ignore=tests/test_no_hardcoded_sources.py \
  --ignore=tests/test_pb_discovery.py \
  --ignore=tests/test_v8_render_upgrades.py \
  --ignore=tests/test_v8_vision_brief.py -q
```

Expected: ~181 passed, ~39 skipped (no new failures after changes).

## Development Server

```bash
pip install -e ".[dev]"
flask --app src.mediahub.web.web:create_app run --debug
# or
python -m mediahub.web.web
```

## Deployment

Deployed on Render via `render.yaml`. Docker-compatible via `Dockerfile`.
Branch model: feature branches from `dev`; never merge to `main` without approval.
