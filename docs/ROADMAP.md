# MediaHub Roadmap

> **Reading this:** the structure follows the dissertation
> [`docs/competitor_dissertation_2026.md`](competitor_dissertation_2026.md)
> — *Phase 1: Parity → Phase 2: Distinction → Phase 3: Leadership*.
> Each phase tracks **shipped / in flight / not started** against
> dissertation workstreams. The old version-numbered roadmap (V8.x /
> V9 / V10) is preserved at the bottom as an engineering history.

The strategic thesis is unchanged from the dissertation:

> Preserve the moat (sport-grounded intelligence layer), close the
> polish gap to the horizontal players (Holo, Blaze, Jasper),
> operationalise the niche so thoroughly that no generalist platform
> can credibly serve a club, society or team without going through
> MediaHub.

---

## Where we are today (May 2026)

Two structural shifts beyond the original dissertation thesis:

1. **The intelligence layer is meaningfully ahead** of where the
   dissertation assumed at this point. Four full workstreams have
   shipped — brand DNA, brand guidelines ingestion, voice imitation,
   and the AI-derived operating profile that replaces every
   hardcoded judgment constant. No generalist player can replicate
   that without paying the same vertical data-pipeline cost.

2. **The product is operator-managed and turnkey for users.** All
   configuration (LLM keys, Buffer access token, cutout providers)
   is set once via env vars at deploy time. There is no user-facing
   settings UI; the end user lands on the home page, sets up their
   organisation, and creates content. They never see a knob.

The operational layers below the intelligence (publishing,
reliability, athlete-facing surfaces, sport coverage) remain the
diagnosed gap. Commercial layer is deliberately deferred until the
product is genuinely ready for paying customers.

### The deployment model (the bit the dissertation didn't anticipate)

MediaHub is now a **single-org-per-deployment** turnkey product:

- The operator (you, or a club's IT person) deploys MediaHub on
  Render (or any Docker host) and sets two env vars: `GEMINI_API_KEY`
  (free) and `BUFFER_ACCESS_TOKEN`. Optionally `ANTHROPIC_API_KEY`
  with `MEDIAHUB_LLM_PROVIDER=anthropic` for paid Claude quality.
- The end users (the club's social-media volunteers, coaches,
  parents) reach the deployment URL, set up their organisation,
  and use the product. They never see a configuration screen.
- Cost to the operator at default config: ~$10–25/month total
  (Render Starter + Buffer Essentials + Gemini free tier). The
  free-tier LLM covers the small-club business model end-to-end.

Multi-tenant SaaS (multiple clubs sharing one MediaHub instance) is
Phase 3 work — both architecturally and commercially.

---

## Phase 1 — Parity (target: complete by Aug 2026)

**Goal:** any visiting club can land on the deployment URL, set up
their organisation, generate content, schedule it through Buffer,
and trust the uptime — *all in under twenty minutes from a cold
start.* This is the Holo / Blaze parity benchmark, adapted to the
operator-managed deployment model.

### 1.1 Brand DNA capture · ✅ **SHIPPED + extended**

| Sub-item | Status |
|---|---|
| Capture brand from a club website URL | ✅ `brand/dna_capture.py` |
| Capture from up to 5 social profiles | ✅ `brand/social_dna.py` |
| Voice imitation from past captions (5–20 exemplars) | ✅ `brand/voice_imitation.py` |
| Optional brand-guidelines doc upload (PDF/DOCX/ZIP/TXT/HTML/RTF) | ✅ `brand/guidelines.py` |
| Unified `brand_context_for_llm()` consumed by every tool | ✅ `brand/context.py` |
| AI-derived operating profile (tone prose, priority weights, type phrases, artefact intents) — derived once at save-time, cached on the profile | ✅ `brand/derived.py` |
| Org-first gate (no content production before AI knows the org) | ✅ `_gate_until_org_ready` in `web.py` |
| Session pinning + multi-tenant `/activity` scoping | ✅ |
| First-run `/organisation/setup` flow | ✅ |

**Beyond the dissertation:** the operating-profile cache means an
org's tone, ranking weights, and per-artefact creative intents are
AI-derived from *their specific* brand context and persist
deterministically. The dissertation's §6 was conceptual; this is
implemented and tested (472 tests passing).

### 1.2 Output surface expansion · ✅ **SHIPPED**

| Sub-item | Status |
|---|---|
| Static result-card graphics (Playwright + branded layouts) | ✅ `graphic_renderer/` |
| Animated reel / story-format graphics (Remotion) | ✅ `remotion/`, `/api/runs/<id>/card/<id>/motion`, `/api/runs/<id>/reel`; surfaced in pack UI as per-card "Motion video" button + meet-level "Generate reel" |
| Captions across 4 tones (warm-club / hype / data-led / AI) | ✅ now AI-derived per org |
| Turn-Into (9 derivative artefact types from one meet) | ✅ `turn_into/` — profile-aware via derived intents; `_artefact_intent` + `_artefact_key` now actually reach the LLM (previously a latent no-op) |
| Newsletter format (HTML/Markdown email digest) | ✅ `brand/newsletter_renderer.py` + `GET /api/runs/<id>/newsletter?format=html|text|zip`; sender-safe HTML email with inline styles + table scaffold; ZIP packages both formats + README; surfaced in pack UI as 4 download buttons |
| Sponsor-templated content variants | ✅ `brand/sponsor.py::generate_sponsor_caption` + `/runs/<id>/card/<cid>/sponsor-variant` page; visual via existing `sponsor_branded` layout family, caption through the regular pipeline with sponsor requirement layered as an extra instruction; per-card "Sponsor variant" button in grouped pack |
| Per-platform output adaptation (IG / X / LinkedIn / TikTok / Facebook / email) | ✅ `brand/derived.PLATFORM_FORMATS` + `platform_format_for(artefact_key)`; format constraints are mechanical/code-controlled (separated from AI-derived voice) and threaded into every caption that carries an `_artefact_key` |

### 1.3 Publishing layer · ✅ **SHIPPED** (multi-tenant-safe Buffer + Buffer-free download path)

| Sub-item | Status |
|---|---|
| Buffer channel listing | ✅ `/api/buffer/channels` — resolves token per-profile first |
| Per-card scheduling | ✅ `/api/runs/<id>/card/<id>/schedule` calls real Buffer, persists per-channel results, marks workflow store as SCHEDULED/FAILED |
| **Per-profile access-token storage** (multi-tenant safe) | ✅ Each `ClubProfile` carries its own `buffer_access_token`. Connection is inline inside the schedule modal via `/api/organisation/connect-buffer` — never via a settings page. Validates against Buffer before persisting. Single-tenant self-hosted deployments may set `BUFFER_ACCESS_TOKEN` env var as a fallback (operator IS the user in that model). |
| **Buffer-free download path** | ✅ `/api/runs/<run>/card/<card>/download` ships a ZIP with the caption text + visual PNG for clubs that don't use Buffer at all. The "Copy + Download" affordance is always available inside the schedule modal, even for clubs that haven't connected Buffer. Zero TOS surface for non-Buffer users. |
| Scheduled-post status surface in `/activity` | ✅ Per-run schedule summary column ("3 scheduled · 1 failed") pulled from workflow store; "Recent posting activity" panel listing the last 20 attempts with status badges + error messages |
| Failure observability | ✅ `publishing/posting_log.py` SQLite log of every attempt (success + failure) with profile/run/card/channel/status/error_kind/error_message/update_id/caption_excerpt fields; bounded retention (5000-row sweep to 4500); `/api/posting/log` endpoint for SPA/JS consumers, gated by active org |
| Rate-limit handling | ✅ `BufferRateLimitError` on 429 with `Retry-After` parsing; loop short-circuits early since rate-limit is per-account |
| Media URL hardening | ✅ Defence-in-depth scheme + netloc validation rejects `file://` / `javascript:` / `data:` / bare paths before they reach Buffer |
| Native publish (IG Graph, FB Pages, X v2, TikTok Business, LinkedIn Marketing) | ❌ **Phase 3 stretch** — only needed if Buffer's developer terms ever close or rate-limits bite. The per-profile model means we're a legitimate Buffer API consumer, not a re-distributor. |
| Buffer OAuth flow (one-click vs paste-token) | ❌ **Phase 3 nice-to-have** — token paste is friction but happens once per club, inline in the publishing flow, never gates first-run. |

**The multi-tenant-safety invariant.** Each club connects their OWN
Buffer account; content from Club A NEVER flows through Club B's
Buffer (pinned by `tests/test_buffer_per_profile.py`). Clubs that
have no Buffer at all use the download path. This is the TOS-safe
launch-ready model.

### 1.4 Visible intelligence · ✅ **SHIPPED**

| Sub-item | Status |
|---|---|
| `explain_achievement()` produces `{headline, bullets, source_lines}` | ✅ `recognition/explainer.py` (profile-aware via derived type phrases) |
| "Why this card?" UI default-visible on every card | ✅ `<details open>` in `_render_why_this_card`; reasoning is the first thing the user sees on every card across review / workflow / content-pack / grouped-pack |
| One-click insert "why this matters" into the caption | ✅ "Use in next caption" button inside the explainer block POSTs to `/api/runs/<id>/swim/<id>/caption?include_why=1` which injects the explainer headline + bullets as `_extra_instructions` on top of the existing brand-context system prompt. Result lands in an inline panel below the explainer with a copy button. Fallback explainer text ("AI unavailable" / "Generated for: ranked top-N") is filtered out so the LLM never gets told to "include error text" |
| Confidence-band visualisation in pack list | ✅ Promoted to a sortable column on the grouped pack: per-card `data-band-rank` + `data-priority` attributes + per-section "Sort: Confidence / Priority" buttons that reorder in place via `mhSortPackSection` JS, toggling desc→asc on repeat clicks |

Promoted from Phase 2 to Phase 1 — surfacing the intelligence layer
is the single biggest *marketing* lever the product has and no
horizontal player can copy it.

### 1.5 Reliability + observability · ✅ **SHIPPED**

| Sub-item | Status |
|---|---|
| `/healthz` + `/healthz/deps` | ✅ |
| `/api/settings/llm-status` (live AI status, kept post-rewrite) | ✅ |
| Per-card schedule status pills on `/activity` | ✅ |
| "Recent posting activity" panel on `/activity` (posting_log) | ✅ |
| Public status page with uptime number | ✅ `/status` reads from `observability/uptime.py` SQLite heartbeat log; renders 24h / 7d / 30d uptime + last incident + JSON twin at `/api/status` |
| Per-run pipeline error logging surfaced to user | ✅ `/activity` now renders a "Why did this run fail?" collapsible block under each errored row, plus a header callout counting failures in the last 100 runs |
| Operator-facing usage dashboard (Gemini quota consumed today, est. monthly cost) | ✅ `/healthz/usage` reads from `observability/llm_usage.py` and shows today + 7d + 30d LLM call counts, per-provider cost estimates, Gemini free-tier headroom bar, and the most recent provider error |

Dissertation §4.4's reliability positioning asset is now real:
`/status` is a public, no-auth page that shows the deployment's real
uptime number derived from heartbeat density. Each `/healthz` and
`/health` hit logs one row; the page is honest when there's no data
yet (shows em-dashes, not a fake 100%).

**Phase 1 is complete.** All 5 work-streams shipped.

---

## Phase 2 — Distinction (target: Aug 2026 → Feb 2027)

**Goal:** convert MediaHub's vertical advantages into visible,
marketable product surfaces. Win one geography + one governing body.

### 2.1 Commercial layer · ❌ **DEFERRED to pre-launch**

The deployment model has shifted: MediaHub is now a turnkey
single-org-per-deployment product. That changes how this work-stream
looks. Two viable commercial paths:

**Path A (preferred, self-serve hosted SaaS):** stand up a managed
"club.mediahub.example" service. Each club gets their own subdomain
+ isolated instance. Operator (us) pays for hosting + Buffer +
optional Anthropic; charges the club £30–50/mo. Single-org per
instance means no multi-tenant gymnastics in the app code.

**Path B (open-source distribution):** keep the codebase MIT-
licensed; provide a one-click Render deploy template. Operators
self-host and pay their own costs. We earn from support contracts
+ optional hosted SaaS for those who don't want to self-host.

In either path, the commercial layer needs to ship near launch:

| Sub-item | Status | Next step |
|---|---|---|
| Public `/pricing` page (on a marketing site, NOT in the product) | ❌ | Static page on the project landing site; no in-product pricing UI |
| Tenant provisioning (Path A) | ❌ | One-click "deploy a new club instance" admin tool |
| Stripe billing for hosted SaaS | ❌ | Stripe subscription per provisioned instance |
| Free-tier quota enforcement (LLM-call-count) | ❌ | Count Gemini calls per `profile_id`; soft-throttle at quota |
| Support / SLA tier for governing-body customers | ❌ | Manual onboarding for the first 10 enterprise customers |

**Deliberately deferred.** Payment options only go in once the app
is genuinely ready for paying customers. Shipping a paywall before
the product is finished does more brand damage than running a few
months without revenue. Schedule: completes Phase 2 right before
public launch. The operator-managed deployment model means we can
run pilot clubs at $0 marginal cost while iterating on the product.

### 2.2 Sport expansion · ❌ **NOT STARTED**

| Sub-item | Status | Next step |
|---|---|---|
| Architecture supports a second sport | ✅ canonical event vocab is configurable | — |
| Athletics (track & field) — second sport | ❌ | Quarter-long project: FinishLynx + HyTek MeetPro parsers; canonical event taxonomy; PB / record / qualifier logic; copy templates |
| Football / rugby — third sport | ❌ | Quarter after athletics |
| University society generic / non-results inputs | ⚠️ free-text input exists | Promote: weekly digest, committee announcement, training-session highlight |

Publish the sport-expansion roadmap externally on `/sports` so
buyers see the trajectory (dissertation §4.9 lesson from FanWord).

### 2.3 Turn-Into for sports · ✅ **SHIPPED**

Already implemented in `turn_into/templates.py`. Profile-aware via
the AI-derived `artefact_voice` map. Nine artefact types: meet
recap, swimmer spotlight, data thread, LinkedIn long, Instagram
long, parent newsletter, sponsor thank-you, coach quote, next-meet
preview.

### 2.4 Voice imitation · ✅ **SHIPPED**

`brand/voice_imitation.py` + the unified `brand_context_for_llm()`.

### 2.5 Athlete-facing surfaces · ❌ **NOT STARTED**

| Sub-item | Status | Next step |
|---|---|---|
| Per-athlete personal share link | ❌ | `/athlete/<slug>` showing their season's cards |
| Story-ready card download from athlete view | ❌ | Re-use Remotion 1080×1920 motion variant |
| Notification when an athlete has new content waiting | ❌ | Email or one-time-link flow; defer push for later |

This is the Greenfly-pattern adapted for small-club scale (§4.10).
Don't build a mobile app — a personal web link + email is enough.

---

## Phase 3 — Leadership (target: Feb 2027 → Nov 2027)

**Goal:** be the default content platform for at least one governing
body in one sport in one geography.

### 3.1 Integration moat · ⚠️ **PARTIAL**

| Sub-item | Status | Next step |
|---|---|---|
| HY3 parser | ✅ `interpreter/` | — |
| PDF result-sheet parser | ✅ | — |
| SportSystems adapter | ✅ | — |
| HyTek MeetManager direct import | ❌ | One quarter |
| Splash Meet Manager direct import | ❌ | One quarter |
| TeamUnify / SwimClub Manager / ClubBuzz import | ❌ | One quarter each |
| Live results-feed ingestion during a meet | ❌ | Phase 3.5 stretch |

Each integration is small in isolation but cumulative — the
defensibility comes from being the easiest place to plug into the
software clubs already use.

### 3.2 Enterprise tier · ❌ **NOT STARTED**

Multi-club orchestration, league-wide content distribution,
federation engagement analytics, sponsorship reporting, athlete
tagging at scale. Pricing £250–£500/mo. Two design-partner accounts
should be secured before public launch.

### 3.3 Agentic execution · ❌ **NOT STARTED**

Conversational caption editing ("make this more energetic", "add
a thank-you to the parents"). The agent operates over the existing
content pack and respects the brand profile. Defer until human-in-
the-loop product is mature; the audience is reputationally cautious
about unattended publishing.

### 3.4 Marketplace / community templates · ❌ **NOT STARTED**

Clubs share branded layouts, voice profiles, and content patterns.
Switching cost moat — once a club invests in templates that exist
only here, leaving is expensive.

### 3.5 Sponsor-side product · ❌ **NOT STARTED**

Convert the sponsor-tagging + engagement-analytics primitives into
a sponsor-facing dashboard that proves brand-exposure value. Nota
and FanWord don't address this at small-club scale.

---

## Cross-cutting investments (all phases)

These cut across every phase and don't fit cleanly into one
work-stream.

| Investment | Status | Notes |
|---|---|---|
| Product design / UI polish quarter | ❌ | Designer-engineer pairing for one quarter. Targets: Home, Add Input, Content Pack. (Settings no longer exists.) Doesn't require a stack rewrite — Flask + Jinja stay. |
| End-to-end pipeline observability | ⚠️ partial | Every meet upload produces a structured log of which inputs succeeded, which generations failed, why — surfaced to user and to internal admin |
| Content marketing programme | ❌ | One piece per fortnight + case studies. Yields the inbound demand for the commercial layer |
| Test suite stability | ✅ **678 passed / 0 failed at HEAD**; 43 skipped (Playwright browser, sample-corpus, reportlab, MEDIAHUB_RUN_MOTION_TESTS gates — every skip is environmental, none mask a structural failure) | Keep green |
| Operator deployment template | ✅ `render.yaml` audited + complete; `.env.example` is the canonical reference | One-click Render deploy works |

---

## Immediate next moves

**Phase 1 status:** 1.1, 1.2, 1.3, 1.4, 1.5 all SHIPPED. **Phase 1
is complete.**

1. **Pilot deployment.** Stand up one production Render instance,
   set the env vars, invite one real club to use it for a month.
   This is the first real-world load test of the operator-managed
   model and will surface every UX hole the audits couldn't find.
   Operator runbook in [`docs/PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md).

2. **Sport expansion (2.2 athletics).** Unlocks the next tranche
   of buyers (track-and-field clubs). One quarter of work:
   canonical event taxonomy + result-file parser + PB/record/
   qualifier logic + copy templates.

3. **Athlete-facing surfaces (2.5).** Per-athlete personal share
   link (`/athlete/<slug>`) showing their season's cards +
   story-ready downloads. Long-tail distribution moat.

Commercial layer (2.1) is deliberately scheduled last — only when
the product is ready for paying customers.

---

## Engineering history (historical record)

Preserved from the previous roadmap structure — these are the
contracts shipped between V8 and the current state.

### V8.x

- ✅ Brand kit upload (V8.1)
- ✅ Two-step upload UI
- ✅ Cutout providers: rembg / Replicate / PhotoRoom
- ✅ Vision-aware creative briefs
- ✅ Variation seed for deterministic regeneration
- ✅ Live AI captions
- ✅ Voice induction from exemplars
- ✅ V8.2 polish: render upgrades, venue search hardening

### V9.x (current)

- ✅ Zero hardcoded AI fallbacks — errors surface honestly (PR #49)
- ✅ Production URL-prefix fix; dead Free Text card retired (PR #49)
- ✅ Brand DNA layer — website + 5 socials + guidelines doc + voice
  imitation + unified context helper (PRs #52, #54)
- ✅ Org-first gate + multi-tenant `/activity` scoping (PRs #52, #53)
- ✅ Home page slimmed; runs scoped per organisation (PR #53)
- ✅ AI-derived operating profile replacing hardcoded judgment in
  tone descriptors, ranking weights, type phrases, and artefact
  intents (PR #55)
- ✅ Phase 1.2 output surface: newsletter export, motion-as-export,
  sponsor variants, per-platform format awareness, latent
  `_artefact_intent` plumbing fix
- ✅ Phase 1.3 publishing via Buffer: end-to-end schedule loop,
  rate-limit + media-URL hardening, SQLite posting log,
  per-run schedule summary + posting-activity panel on /activity
- ✅ Phase 1.4 visible intelligence: explainer default-visible
  across every card surface; "Use in next caption" button that
  reinjects reasoning into the LLM; sortable confidence/priority
  columns on the grouped pack
- ✅ **Operator-config rewrite**: settings page deleted entirely;
  LLM chain slimmed to Gemini-first + optional Anthropic; OpenAI
  + Claude CLI + pplx-bridge removed; Buffer access token moved
  to operator-managed env var; secrets store reduced to a thin
  env-first facade. Two audit fleets ran in parallel after the
  rewrite, each finding ran an 8-step resolve subagent; all
  findings closed. 605 tests passing.
- ✅ **Phase 1.5 reliability + observability**: new
  `mediahub.observability` package with SQLite-backed `uptime` log
  (heartbeats on every /healthz + /health hit) and `llm_usage` log
  (every Gemini / Anthropic call). Three new routes: public
  `/status` page + `/api/status` JSON twin (no auth, no org gate —
  trust-signal positioning), and operator-only `/healthz/usage`
  showing today / 7d / 30d LLM call counts, per-provider cost
  estimates from public list pricing, Gemini free-tier headroom
  bar, posting-log 7-day summary, and the most recent LLM provider
  error. `/activity` gained a "Why did this run fail?" collapsible
  panel under each errored row plus a header callout. The
  `test_v8_brand_kit_upload::test_extract_palette_from_synthetic_logo`
  pre-existing failure was fixed by replacing the missing
  `colorthief` dependency with a Pillow-based palette extractor
  (Pillow was already a hard dep). Operator pilot playbook in
  `docs/PILOT_PLAYBOOK.md`. **678 tests passing, zero failed,
  zero known-issue carve-outs.**

### Future (V10+ vision, retained from previous roadmap)

- Real-time meet feed (live captioning while a session is on)
- Native iOS / Android share-sheet integration
- A learnable ranker that takes `like_rate` feedback from posted
  content
- Move from JSON ledgers to Postgres
- WebSocket pipeline status (replace `/api/runs/<id>/status` polling)
