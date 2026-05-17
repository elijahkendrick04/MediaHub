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

The **intelligence layer** is now meaningfully ahead of where the
dissertation assumed it would be at this point. Three full
work-streams beyond Phase 1.1 have shipped that the dissertation
didn't anticipate. The product is, as the dissertation put it,
"more than a demo" — it now has a defensible org-onboarding flow
and an AI-derived operating layer that no generalist player can
replicate without paying the same data-pipeline cost.

The **operational layers** below it (publishing, commercial,
reliability, athlete-facing surfaces) remain underdeveloped — that's
the dissertation's diagnosis and it still stands. The next two
quarters need to close those gaps, not extend the intelligence layer
further.

---

## Phase 1 — Parity (target: complete by Aug 2026)

**Goal:** any visiting club can sign up, set up their org, generate
content, schedule it, pay for it, and trust the uptime — *all in
under twenty minutes from a cold start.* This is the Holo / Blaze
parity benchmark.

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

### 1.3 Publishing layer · ❌ **NOT STARTED** (scaffolding only)

| Sub-item | Status | Next step |
|---|---|---|
| Buffer channel listing | ⚠️ `/api/buffer/channels` exists | — |
| Per-card scheduling | ⚠️ `/api/runs/<id>/card/<id>/schedule` exists | Wire to a real Buffer schedule call with success/failure return |
| Buffer OAuth + access-token storage | ❌ | **Settings page panel** for Buffer connect; store token via existing `secrets_store` |
| Scheduled-post status surface in `/activity` | ❌ | Show "scheduled · sent · failed" per card |
| Native publish (Instagram Graph, Facebook Pages, X v2, TikTok Business, LinkedIn Marketing) | ❌ | **Phase 2** — start with IG Graph (highest demand) once Buffer path is mature |
| Failure observability (which post failed why) | ❌ | Single `posting_attempts` table + simple "what failed in the last 24h" admin view |

Dissertation §6.1.3 recommends Buffer integration first (faster moat,
weaker but adequate); native publish in Phase 2. Following that.

### 1.4 Visible intelligence · ⚠️ **PARTIAL**

| Sub-item | Status | Next step |
|---|---|---|
| `explain_achievement()` produces `{headline, bullets, source_lines}` | ✅ `recognition/explainer.py` (now profile-aware via derived type phrases) | — |
| "Why this card?" UI present on cards | ⚠️ `_render_why_this_card` exists, surfaced inconsistently | **Make it default-visible on every card across review, pack, content-pack-grouped** |
| One-click insert "why this matters" into the caption | ❌ | Add a "use this in caption" button in the explainer UI that re-prompts the LLM with the explanation as required content |
| Confidence-band visualisation in pack list | ⚠️ tag exists | Promote into a sortable, filterable column |

Promoted from Phase 2 to Phase 1 — surfacing the intelligence layer
is the single biggest *marketing* lever the product has and no
horizontal player can copy it. It's a higher-priority Parity item
than commercial bringup, which moves to Phase 2 (see 2.1).

### 1.5 Reliability + observability · ⚠️ **PARTIAL**

| Sub-item | Status | Next step |
|---|---|---|
| `/healthz` + `/healthz/deps` | ✅ | — |
| Public status page | ❌ | Static `/status` page reading from a small SQLite uptime log |
| Scheduled-post success metric | ❌ | Surface in Buffer integration (1.3) |
| Per-run pipeline error logging surfaced to user | ⚠️ partial | Make "Why did this run fail?" first-class in `/activity` |
| LLM provider error history | ✅ `last_provider_errors()` shown on `/settings` | — |

Dissertation §4.4 makes a marketable case for reliability: many
Ocoya / Predis customers would switch to a more reliable competitor
at the same price. An explicit uptime number is a positioning asset,
not just an SRE chore.

---

## Phase 2 — Distinction (target: Aug 2026 → Feb 2027)

**Goal:** convert MediaHub's vertical advantages into visible,
marketable product surfaces. Win one geography + one governing body.

### 2.1 Commercial layer · ❌ **DEFERRED to pre-launch**

| Sub-item | Status | Next step |
|---|---|---|
| Public `/pricing` page | ❌ | Three tiers: free (1 meet/mo), small club £30-50/mo, governing-body custom |
| Self-serve signup (email + password) | ❌ | Use existing Flask session; persist to `users.json` or new SQLite table |
| Stripe billing | ❌ | Stripe Checkout for the small-club tier; webhook to flip `ClubProfile.tier` |
| Free-tier quota enforcement | ❌ | Count runs per `profile_id` per calendar month; soft-block at quota |
| Sales-led onboarding flow for enterprise tier | ❌ | "Contact sales" CTA + intake form; manual provisioning for the first 10 customers |

**Deliberately deferred.** Payment options only go in once the app
is ready to go live to customers — that's one of the last things
shipped before launch. The dissertation's §6.1.4 argument for
shipping commercial concurrent with Phase 1 is overruled here:
shipping a paywall before the product is ready for paying customers
is a bigger UX hazard than the lack of pricing pressure during
iteration. Schedule: completes Phase 2 immediately before public
launch.

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
| Product design / UI polish quarter | ❌ | Designer-engineer pairing for one quarter. Targets: Home, Add Input, Content Pack, Settings. Doesn't require a stack rewrite — Flask + Jinja stay. |
| End-to-end pipeline observability | ⚠️ partial | Every meet upload produces a structured log of which inputs succeeded, which generations failed, why — surfaced to user and to internal admin |
| Content marketing programme | ❌ | One piece per fortnight + case studies. Yields the inbound demand for the commercial layer (1.4) |
| Test suite stability | ✅ 472 passed / 0 failed at HEAD; 43 skipped (Playwright + sample-file gates) | Keep green; pre-existing `test_v8_brand_kit_upload::test_extract_palette_from_synthetic_logo` is the one open item |

---

## Immediate next moves

Out of the remaining phase-1 gaps, these have the highest leverage
and fewest dependencies.

1. **Publishing layer end-to-end via Buffer (1.3).** Settings panel
   to connect a Buffer account → store token → list channels →
   schedule a card → track success/failure. Closes the single most
   visible functional gap with horizontal players.
2. **Visible intelligence — "Why this card?" default-visible (1.4).**
   The explainer is already in code; this is a UI consistency
   pass — replace conditional rendering with always-show across
   review, pack, pack-grouped. Biggest *marketing* win because no
   horizontal player can match it.
3. **Reliability / public status page (1.5).** The dissertation
   makes a marketable case for explicit uptime numbers; an SQLite-
   backed `/status` is bounded work.

After those, the priority is **sport expansion (2.2 athletics)**
because it unlocks the next tranche of buyers, and
**athlete-facing surfaces (2.5)** because it's a long-tail
distribution moat.

Commercial layer (now 2.1) is deliberately scheduled last — only
when the app is ready to go live to customers, not before.

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

### Future (V10+ vision, retained from previous roadmap)

- Real-time meet feed (live captioning while a session is on)
- Native iOS / Android share-sheet integration
- A learnable ranker that takes `like_rate` feedback from posted
  content
- Move from JSON ledgers to Postgres
- WebSocket pipeline status (replace `/api/runs/<id>/status` polling)
