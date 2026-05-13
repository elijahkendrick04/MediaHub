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

---

# Claude Skills Configuration

This section documents the full set of Claude/agent skills installed for MediaHub. Skills were
sourced from the Composio top-10 list, the previous Antigravity/individual installs, and manual
git-clone installs. All installation was done without creating accounts, connecting OAuth, or
storing credentials.

## Installed Skills — Full Registry

| # | Skill | Location | Install Method | Status |
|---|-------|----------|----------------|--------|
| 1 | `composio` | `~/.claude/skills/composio` | `npx skills add composiohq/skills` | ✅ Installed |
| 1 | `skill-creator` | `~/.agents/skills/skill-creator` | (bundled with composio) | ✅ Installed |
| 2 | `remotion-best-practices` | `~/.claude/skills/remotion-best-practices` | Antigravity Awesome Skills | ✅ Installed |
| 2 | `remotion` | `~/.claude/skills/remotion` | Antigravity Awesome Skills | ✅ Installed |
| 3 | `frontend-design` | `~/.claude/skills/` + `~/.agents/skills/` | anthropics/claude-code + Antigravity | ✅ Installed |
| 3 | `frontend-dev-guidelines` | `~/.claude/skills/` | Antigravity | ✅ Installed |
| 3 | `design-taste-frontend` | `~/.claude/skills/` | Antigravity | ✅ Installed |
| 4 | `agent-browser` | `/opt/node22/bin/agent-browser` | `npm install -g agent-browser` (v0.27.0) | ✅ Binary installed |
| 4 | `browser-use` | `~/.agents/skills/browser-use` + `~/.claude/skills/` | browser-use/browser-use + Antigravity | ✅ Installed |
| 4 | `browser-automation` | `~/.claude/skills/browser-automation` | Antigravity | ✅ Installed |
| 5 | `supermemory` | `~/.claude/skills/supermemory/` | git clone supermemoryai/supermemory | ✅ Skill file installed |
| 6 | `filesystem-context` | `~/.claude/skills/filesystem-context` | Antigravity | ✅ Installed |
| 6 | `file-uploads` | `~/.claude/skills/file-uploads` | Antigravity | ✅ Installed |
| 6 | `file-organizer` | `~/.claude/skills/file-organizer` | Antigravity | ✅ Installed |
| 7 | Marketing suite (30+ skills) | `~/.agents/skills/` | `npx skills add coreyhaines31/marketingskills` | ✅ Installed |
| 7 | `marketing-ideas` | `~/.claude/skills/marketing-ideas` | Antigravity | ✅ Installed |
| 7 | `marketing-psychology` | `~/.claude/skills/marketing-psychology` | Antigravity | ✅ Installed |
| 8 | `agent-sandbox-skill` | — | **Blocked: E2B API key required** | ⚠️ Manual setup |
| 9 | `superpowers-lab` | `~/.claude/skills/superpowers-lab` | Antigravity | ✅ Installed |
| 9 | `using-superpowers` | `~/.claude/skills/using-superpowers` | Antigravity | ✅ Installed |
| 9 | Superpowers plugin | — | **Blocked: interactive /plugin command required** | ⚠️ Manual setup |
| 10 | `web-design-guidelines` | `~/.agents/skills/web-design-guidelines` + `~/.claude/skills/` | vercel-labs/agent-skills + Antigravity | ✅ Installed |

**No accounts were created. No OAuth was performed. No secrets were stored.**

---

## Manual Steps Still Required

### agent-sandbox-skill (Skill 8)
Requires an E2B API key and Python 3.12+.

```bash
# 1. Get your E2B API key from https://e2b.dev  (requires account)
# 2. Add to .env:
#    E2B_API_KEY=e2b_...
# 3. Clone and set up the skill:
git clone https://github.com/disler/agent-sandbox-skill
cd agent-sandbox-skill
uv sync
# 4. Copy skill file:
cp .claude/skills/agent-sandbox-skill.md ~/.claude/skills/
```

Do not upload private club/athlete data to external sandboxes without explicit permission.

### Superpowers Plugin (Skill 9)
Must be installed interactively inside Claude Code.

Type these commands directly in the Claude Code CLI:
```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

The `superpowers-lab` and `using-superpowers` skills (from Antigravity) are already active
as a functional equivalent for multi-agent orchestration work.

### Supermemory MCP (Skill 5 — optional upgrade)
The skill file is installed. For persistent cross-session memory via MCP, run:
```bash
npx -y install-mcp@latest https://mcp.supermemory.ai/mcp --client claude --oauth=yes
```
This requires OAuth (Supermemory account). Do not run without explicit approval.
Rules: do not store private athlete/club/user data without consent.

### agent-browser Chrome (Skill 4 — local dev)
The `agent-browser` binary is installed (v0.27.0). To enable browser automation, Chrome must be
downloaded separately. In a network-accessible environment:
```bash
agent-browser install
# If that fails on Linux:
agent-browser install --with-deps
```

---

## Usage Rules by Skill

### 1. Composio Skills
Use for integration architecture and agent tool design — not for connecting real accounts.

MediaHub future integrations where Composio is appropriate:
- Instagram/Facebook publishing handoff (requires explicit approval before connecting)
- Email/newsletter export workflows
- CRM-style club/team onboarding flows
- Content scheduling integrations
- Storage integrations (S3, GCS)

**Rules:**
- Never connect external accounts without explicit approval
- Never auto-publish or auto-post
- Human approval must remain required before any external publishing
- Use least privilege for every integration
- Keep credentials out of source control — `.env` only

### 2. Remotion / Remotion Best Practices
Use whenever the user asks for:
- Reels or short-form video
- Animated result cards (stories, feed)
- Athlete spotlight videos
- Weekend-in-numbers animated summaries
- Sponsor-branded video assets
- Meet preview videos
- Demo or product videos

MediaHub Remotion direction:
- Programmatic, data-driven — never static templates
- Club-branded outputs (colours, logo, fonts from BrandKit)
- Real athlete/team imagery where provided
- Sponsor-safe layouts
- Reusable compositions per content type
- No synthetic AI-generated people unless explicitly requested
- Video outputs flow from the same achievement engine as static posts

### 3. Frontend Design / Claude Design
**MANDATORY for all website work.**

Before writing any UI code, define:
- Target user and job-to-be-done
- Primary action on this page
- Visual direction
- Hierarchy and empty/loading/error/success states
- Trust indicators
- Responsive behaviour

MediaHub design principles:
- Bold but practical — editorial/sport feel, not generic SaaS
- Dark-first colour palette (`--bg`, `--accent`, `--ink`, `--panel`)
- Strong hierarchy; obvious primary actions
- Polished empty states and upload/processing screens
- Clear recognition explanations and confidence displays
- Strong approval workflow (queue → approved → posted)
- Brand kit and sponsor controls that feel trustworthy
- No over-animation — motion only for feedback and hierarchy
- Desktop-primary, mobile-aware

After coding UI, run a design review:
- Is this distinctive?
- Does it look like a real product?
- Would a club committee member understand it immediately?
- Would a performance coach trust the confidence scores?
- Is the main workflow obvious?
- Are actions clearly labelled?
- Are approval/rejection/export states unambiguous?

### 4. Browser Automation (agent-browser / browser-use)
Use for:
- Opening local app and verifying it loads
- Testing upload flows end-to-end
- Navigating through dashboard, recognition, and content pack screens
- Checking edit/approve/reject/export interactions
- Screenshot evidence of UI problems
- Checking mobile/responsive layouts
- Validating no blank pages, 404s, or broken routes

Snapshot-first approach:
1. Open page
2. Snapshot interactive elements
3. Interact using stable refs (not fragile selectors)
4. Screenshot evidence
5. Report failures with context

### 5. Supermemory
Use for approved project memory/context — not for storing sensitive data.

Acceptable memory targets:
- Product positioning and accepted direction
- Rejected technical/design directions (avoid re-proposing)
- Accepted architecture decisions (ADRs)
- Naming conventions
- MVP boundaries and pilot constraints
- Previous deployment issues
- Target customer assumptions

Do NOT store:
- Private club data
- Individual athlete PBs, results, or personal details
- User credentials or API keys
- Any data without explicit consent

### 6. Document Processing
Use for all structured document parsing in MediaHub.

Relevant inputs:
- Swim meet result PDFs
- Spreadsheets (XLS, XLSX, CSV)
- Exported result files (HY3, SDIF, SportSystems)
- Qualifying time documents
- Entry lists and heat sheets
- Historical performance files
- Sponsor documents
- Brand guidelines
- Club profile documents

Processing requirements:
- Extract tables accurately; preserve source provenance
- Validate parsed fields; detect uncertain or ambiguous rows
- Normalise swimmer names, event names, and times
- Preserve age group/category where available
- Separate raw extraction from cleaned canonical data
- Flag ambiguous results for human review
- Never silently guess — make uncertainty explicit
- Output machine-readable JSON for the recognition engine

Pipeline: raw file → parsed structured data → validated canonical data → achievement detections → ranked content opportunities → content pack.

### 7. Marketing Skills
Use carefully. Do not turn MediaHub into generic marketing content.

Apply marketing skills for:
- Product positioning and landing page messaging
- Customer discovery questions
- Pricing experiments and framing
- Outbound scripts for club/society onboarding
- Case studies and testimonials
- Retention loops and upgrade prompts
- Content strategy for MediaHub's own marketing
- Sponsor value proposition framing
- ROI/time-saved conversion copy

MediaHub messaging principles:
- Upload the results → engine finds the moments → branded content in minutes → human approves → saves hours
- Specific, evidence-grounded claims only (no "10x your content" without evidence)
- Never imply full automation replaces human judgement
- Do not sound like a social media agency
- Do not promise instant publishing before the approval workflow is proven

Available marketing skills include: `co-marketing`, `community-marketing`, `cold-email`,
`content-strategy`, `copy-editing`, `copywriting`, `launch-strategy`, `lead-magnets`,
`marketing-ideas`, `marketing-psychology`, `onboarding-cro`, `pricing-strategy`,
`referral-program`, `sales-enablement`, `social-content`.

### 8. agent-sandbox-skill
Use only when E2B_API_KEY is configured. Apply for:
- Safe isolated experiments that should not touch production or local data
- Testing a new upload parser against sample files
- Prototyping a new content pack UI in isolation
- Validating a deployment config safely
- Building a demo flow without risk to real data

Rules:
- Do not move normal development into sandbox unnecessarily
- Do not upload private athlete, club, or user data into external sandboxes without permission
- Commit all useful outputs back to the actual repo cleanly

### 9. Superpowers / Multi-Agent Orchestration
Use `superpowers-lab` or `using-superpowers` for large multi-step development tasks.

Do NOT over-process simple tasks. Use when the task is:
- Non-trivial, architectural, or risky
- Touches multiple files or systems
- Benefits from parallel subagents

MediaHub cases for Superpowers:
- New upload/parsing pipeline
- Achievement recognition architecture redesign
- Club/tenant multi-tenancy model
- Approval workflow overhaul
- Brand kit system redesign
- Content generation pipeline changes
- Database schema redesign
- Image/video generation architecture
- Major UI redesign
- Deployment restructuring

### 10. Web Design Guidelines
Run after completing frontend changes.

Review checklist after every UI build:
- Landing page: messaging, hierarchy, trust, CTA clarity
- Dashboard: navigation, data density, state handling
- Upload flow: drag-and-drop, progress, error states
- Content pack: cards, captions, confidence scores, approval states
- Forms: labels, validation, error messages
- Tables: sortability, empty states, pagination
- Modals: focus management, keyboard accessibility
- Mobile layouts: responsive behaviour, touch targets
- Generated content preview: sponsor-safe, brand-accurate

---

## Mandatory Website Workflow

For any website, UI, or dashboard work — regardless of task size:

1. Activate `frontend-design` skill — define visual direction before coding
2. Implement the UI
3. Optionally run `agent-browser` / `browser-use` QA — verify the flow works
4. Run `web-design-guidelines` review — check design/usability quality
5. Fix major issues identified
6. Run lint/typecheck/tests
7. Summarise changes

This four-step sequence is not optional for user-facing work.

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
