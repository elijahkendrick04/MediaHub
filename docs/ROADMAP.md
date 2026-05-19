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
| **Per-profile access-token storage** (multi-tenant safe) | ✅ Each `ClubProfile` carries its own `buffer_access_token`. Connection is inline inside the schedule modal via `/api/organisation/connect-buffer` — never via a settings page. Validates against Buffer before persisting. Operator-managed deployments may set `BUFFER_ACCESS_TOKEN` as a deployment-wide default for single-org configurations. |
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

**Phase 1.1 – 1.5 are complete.** A sixth work-stream (1.6 Adaptive
Theming Engine) was opened in May 2026 as a parity-polish lever
that re-skins the entire product to a club's brand colours when
they accept the brand-DNA capture — see below.

### 1.6 Adaptive Theming Engine · 🔵 **NEW — IN FLIGHT**

**The user-facing promise.** When a club's owner clicks
*"Looks right — start creating"* at the end of organisation setup
(`web.py:11014`), the entire website re-skins to their brand
colours in one smooth, animated cascade — backgrounds, panels,
buttons, focus rings, ink, borders, hover states, status
colours — and stays that way for every subsequent login.

**The engineering promise (the hard part).** This works for
*any* hex the club provides. Fluorescent yellow, muddy dark
green, near-white cream, pure black, two-tone red-on-red: the
generated theme remains professional, accessible (APCA Lc ≥ 75
for body text), colour-blind-safe (Machado-simulated ΔE2000 ≥ 10
between brand and status colours), and visually harmonic — with
**no hand-tuned per-seed overrides anywhere in the codebase.**
The intelligence is in the algorithm, not in a giant lookup
table.

**Why this is Phase 1 polish, not Phase 2 distinction.** Without
this, MediaHub's brand-DNA capture (1.1) and brand-kit upload
flow promise more than they deliver: the user sees their colours
on cards but the *chrome* still looks like our chrome.
Single-org-per-deployment means every operator is hosting "their
own MediaHub" — the product should feel like it from the first
page render, not just inside generated graphics. Polish, not
distinction.

**Academic foundations.** Seventeen parallel research agents
audited the relevant literature in May 2026. The architecture
below draws directly on:
- Björn Ottosson, *"A perceptual color space for image
  processing"* (2020) — [OKLab / OKLCH](https://bottosson.github.io/posts/oklab/)
- Sharma, Wu & Dalal (2005), *"The CIEDE2000 Color-Difference
  Formula"* — [perceptual distance metric](https://www2.ece.rochester.edu/~gsharma/ciede2000/)
- Andrew Somers, *SAPC-APCA* — [perceptual contrast that
  replaces WCAG 2.x's broken luminance ratio](https://github.com/Myndex/SAPC-APCA)
- Google Material Foundation, *Material 3 Dynamic Color* — the
  [HCT colour space + 5-palette × 13-tone role-token system](https://m3.material.io/styles/color/dynamic/overview)
  (`material-color-utilities`, Apache-2.0, Python port on PyPI)
- Cohen-Or et al. (SIGGRAPH 2006), *"Color Harmonization"* —
  [Matsuda harmonic templates](https://igl.ethz.ch/projects/color-harmonization/)
  as a palette-validation oracle
- O'Donovan, Agarwala & Hertzmann (SIGGRAPH 2011), *"Color
  Compatibility from Large Datasets"* — [pretrained aesthetic
  scorer](https://www.dgp.toronto.edu/~donovan/color/) usable as
  a post-hoc gate
- Machado, Oliveira & Fernandes (2009), *"A Physiologically-
  based Model for Simulation of Color Vision Deficiency"* —
  [the CVD matrices Chrome and Firefox use natively](https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html)
- Lalitha A R (arXiv 2512.05067, 2025), *"Perceptually-Minimal
  Color Optimization for Web Accessibility"* — constrained
  non-linear optimisation in OKLCH with hue frozen by default
- W3C CSS Color Module Level 4 §14 gamut mapping, Level 5
  `color-mix()` and relative-colour syntax, CSS Properties &
  Values API `@property`, View Transitions API
- Aslam (2006), Elliot & Maier (2007), Palmer & Schloss (2010),
  W3C WCAG 1.4.1 — cross-cultural status-colour semantics
  (status roles stay locked; only brand role flows from the seed)

Provenance for every claim above is preserved in the research
trail and cited inline in `docs/THEMING.md` (to be authored in
Stage J).

**Architecture in one paragraph.** A single brand-seed hex →
HCT colour space → 5 tonal palettes (primary, secondary,
tertiary, neutral, neutral-variant) × 13 tones each → ~25
Material-3-style semantic role tokens for both light and dark
schemes → CSS custom properties registered via `@property
syntax: "<color>"` so they interpolate during a View
Transitions API-driven cascade → cached on `ClubProfile.
brand_kit.derived_palette` as a DTCG-format JSON file consumed
by the Flask templates, Remotion compositions, the newsletter
renderer, and the static graphic renderer. **Python only ships
the seed and the 5 palette anchors; every derived shade, hover
state, border, and focus ring is computed at runtime in CSS via
`color-mix(in oklch, …)` and `oklch(from var(--mh-brand-seed) …)`.**
QA gates (APCA contrast, CIEDE2000 ∆E, Machado CVD simulation,
Cohen-Or harmonic template fit) run server-side at save-time
and emit a quality report into the run audit trail.

**Work breakdown.** Ten stages, deliberately additive — the
existing `BrandKit` dataclass and `brand/` package are extended,
never replaced. Each stage is its own PR and is independently
testable.

| Stage | Sub-item | Status | Notes |
|---|---|---|---|
| **A — Token foundation** | A1 Audit every hardcoded colour in `web.py` (~1,400 lines of inline CSS) and migrate to CSS variables | ❌ | Mechanical. No behaviour change. Output: one inventory of every literal `#…` or rgba() in templates |
| | A2 Adopt 3-tier token system (primitive → semantic role → component) per [W3C Design Tokens DTCG spec](https://www.designtokens.org/TR/drafts/format/); ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`, `--mh-primary`, `--mh-on-primary`, `--mh-primary-container`, `--mh-on-primary-container`, `--mh-secondary`, `--mh-tertiary`, `--mh-outline`, `--mh-outline-variant`, `--mh-error`, `--mh-success`, `--mh-warning`, `--mh-focus`, `--mh-elevation-{1,2,3}`) | ❌ | Single source of truth. Tier 3 (component tokens) deferred per Curtis's "promote on 3+ component reuse" rule |
| | A3 Register every animatable variable via `@property { syntax: "<color>"; inherits: true; }` so they interpolate smoothly through theme switches | ❌ | Without `@property`, CSS custom properties are untyped strings and `transition` silently snaps |
| **B — Colour science library** | B1 Add `materialyoucolor` + `coloraide` to `requirements.txt` (both pure-Python, Apache-2.0, no JS runtime); avoid `colorthief` (already replaced by Pillow extractor in Phase 1.5) | ❌ | One known transitive dep (numpy) already present |
| | B2 New `src/mediahub/theming/` package: `seed_extract.py` (SVG fast-path → rasterise → QuantizerCelebi → Score), `palette.py` (HCT seed → 5×13 tonal palettes), `roles.py` (palettes → MD3 role-token map for light + dark schemes), `contrast.py` (APCA `Lc` + ink-on-surface), `cvd.py` (Machado 2009 matrices for deutan/protan/tritan), `quality.py` (all QA gates → `PaletteQualityReport`), `repair.py` (constraint-satisfaction loop: clamp chroma → sweep L → relax H ±8° → curated-neighbour fallback) | ❌ | ~6 small modules, each independently unit-testable. Ports the relevant `material-color-utilities` paths via the maintained Python package |
| | B3 Persist resolved palette on `ClubProfile.brand_kit.derived_palette` — compute once on save, never per-request | ❌ | Matches existing `brand/derived.py` operating-profile cache pattern |
| **C — CSS architecture** | C1 Extract inline CSS from `web.py` (the ~1,400-line `<style>` block starting at `web.py:1363`) into `src/mediahub/web/static/theme-base.css`; content-hashed asset URL for cache-bust | ❌ | Big mechanical change; gated behind a feature flag during cutover |
| | C2 Build the derivation graph in pure CSS via `color-mix(in oklch, …)` and relative-colour syntax (`oklch(from var(--mh-brand-seed) calc(l ± n) calc(c * f) h)`) — Python ships ~6 anchor values, CSS derives the remaining ~55 shades | ❌ | Drastically reduces the "hardcode surface area" the user mandated. CSS engine is the single source of truth for the cascade |
| | C3 Add `light-dark()` for surface/ink pairs; honour `prefers-color-scheme: dark/light` so the same seed produces correct light + dark variants without a duplicate stylesheet | ❌ | Spec status: Baseline 2024 |
| | C4 Add Python-precomputed fallback ramp inside `@supports not (color: oklch(from red l c h))` for Safari ≤ 16.3 (relative-colour syntax landed Mar 2023; the gate catches the remaining ~10% long-tail) | ❌ | No JS polyfill; pure-CSS feature query |
| **D — Theme delivery (Flask)** | D1 `before_request` middleware loads the active `ClubProfile`'s `derived_palette` into `flask.g.theme` (already partially in place via the org-gate; extend it) | ❌ | Single-org-per-deploy today; one-line extension to subdomain-based multi-tenant lookup for Phase 3 |
| | D2 Jinja base template emits one inline `<style id="mh-theme-seed">:root { --mh-brand-seed: {{ g.theme.seed }}; --mh-scheme-polarity: {{ g.theme.polarity }}; … }</style>` in `<head>` *before* any external stylesheet — zero FOUC | ❌ | Tiny payload (~250 bytes) vs the cacheable static `theme-base.css` |
| | D3 Re-render cached pages (sponsor-variant page, sponsor-branded layouts) so they consume the new variables instead of hardcoded hexes | ❌ | Audit pass after C1 |
| **E — "Looks right" cascade** | E1 Wire the existing button at `web.py:11014` so its click handler: (i) saves the brand kit, (ii) calls `theming.derive_from_seed(seed)` and persists `derived_palette`, (iii) wraps navigation to `/add-input` in `document.startViewTransition(() => location.assign(…))` | ❌ | The user-visible "wow" moment — fires on the exact button the user named |
| | E2 Add `@view-transition { navigation: auto; }` to `theme-base.css` so cross-document navigation between pages crossfades atomically (Chrome 126+ / Safari 18.2+, Firefox in progress) | ❌ | Pure CSS; degrades to instant nav on older browsers |
| | E3 Add `:root { transition: --mh-brand-seed 600ms cubic-bezier(.2,.7,.2,1); }` so the colour ripples through the page even when View Transitions isn't available — because every derived var is `color-mix(in oklch, var(--mh-brand-seed) …)`, the entire palette interpolates in lockstep for free | ❌ | One line per animatable token |
| | E4 Gate animation with `@media (prefers-reduced-motion: reduce)` — instant swap for users who request it | ❌ | WCAG 2.3.3 |
| **F — Logo intelligence** | F1 Default to a neutral chip behind every uploaded logo (auto-pick white/near-white rounded chip with 12px padding, sized to logo bounding box) — never recolour unknown SVG marks | ❌ | Matches Adobe Spectrum, IBM Carbon, BBC brand-book defaults |
| | F2 "Safe to drop chip" auto-detection: compute the logo's dominant non-neutral colour vs the active surface in OKLCH; if ΔE2000 ≥ N AND APCA Lc ≥ 45 in both polarities, render bare; otherwise chip | ❌ | Honest about when it's safe to skip the chip |
| | F3 Author MediaHub's own SVG marks with `fill="currentColor"` so the product chrome auto-adapts to ink colour without recolouring; **never** auto-inject this on uploaded logos | ❌ | Per W3C SVG2 spec; the Material You "ship a monochrome layer if you want it tintable" lesson |
| **G — Single source of truth for motion + email** | G1 Convert `derived_palette` to DTCG-format JSON at `DATA_DIR/themes/<profile_id>.json` | ❌ | Aligns with the W3C Design Tokens spec; future-proofs against Style Dictionary integration |
| | G2 `visual/motion.py` reads the JSON and passes it as `inputProps` to `render.js`; Remotion compositions consume the same tokens as the web UI | ❌ | Single source of truth across MP4 + browser |
| | G3 `brand/newsletter_renderer.py` reads the JSON and Premailer-inlines the resolved hex values into outgoing HTML emails (email clients don't reliably support CSS custom properties) | ❌ | Same JSON, different rendering target |
| | G4 `graphic_renderer/render.py` reads the same JSON, replacing today's `BrandKit.primary_colour` lookups | ❌ | Closes the loop: web, motion, email, static graphic all share one palette |
| **H — Explainability + QA** | H1 Every palette derivation logs a `PaletteQualityReport` to the run audit trail: APCA `Lc` scores for every role pair, CIEDE2000 matrix for brand × {neutral-500, success, warning, danger}, Machado-CVD ∆E2000 for the same pairs under deutan/protan/tritan, Cohen-Or harmonic-template fit energy, and a decision trace ("clamped chroma 0.30 → 0.21 to fit sRGB; shifted hue +6° to keep success-green distinct under deuteranopia") | ❌ | Matches MediaHub's standing rule: "every step should be explainable and auditable" |
| | H2 Add a "Why does my theme look like this?" expandable panel to `/organisation/setup` — committee members see the decisions and contrast scores, can override an individual role colour if they really must, and the override gets logged with a cultural-clash warning if it lowers a status colour's ΔE | ❌ | Trust signal; mirrors the brand-DNA "What MediaHub learned" panel |
| | H3 Non-blocking warning surface if the hostile-seed repair loop fired: *"Your brand yellow (#DFFF00) was very close to our success-green (#1F9D55); we adjusted the success colour by +8° to keep them distinct for colour-blind viewers."* | ❌ | Never silently rewrite the brand colour; only adjust the *status* colour and tell the user why |
| **I — Test coverage** | I1 New `tests/theming/` directory: `test_seed_extract.py`, `test_palette.py` (golden-master snapshots for ~30 representative seeds including fluorescent yellow `#DFFF00`, muddy dark green `#2A3A1A`, near-white `#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, plus 10 real club colours), `test_contrast.py` (APCA Lc gates), `test_cvd.py` (Machado simulator parity vs known fixtures), `test_quality.py`, `test_repair.py` | ❌ | Snapshots make regressions obvious in PR review |
| | I2 Playwright/browser-use end-to-end test: upload a logo → land on `/add-input` → assert `getComputedStyle(document.documentElement).getPropertyValue('--mh-surface')` matches the expected derived value | ❌ | Gated on `MEDIAHUB_RUN_BROWSER_TESTS=1` like the existing motion tests |
| **J — Cutover + polish** | J1 Replace the existing hardcoded palette in `web.py:1363-1462` by reading from `theming/`; gate behind a feature flag (`MEDIAHUB_ADAPTIVE_THEME`) during the rollout window | ❌ | Cutover is reversible while the new pipeline is observed in production |
| | J2 Run the generic-default `BrandKit` (`#0E2A47` navy / `#C9A227` gold) through the new pipeline so the unconfigured first-run experience also gets the upgrade | ❌ | No regression for fresh deployments before brand DNA is captured |
| | J3 Author `docs/THEMING.md` documenting the architecture, the role-token table, the CSS variables operators may safely override in a custom `theme-override.css`, and the academic references inline | ❌ | Single canonical doc for future contributors |

**Acceptance criteria (the "definition of done" for 1.6):**

1. A test suite that takes 30 representative seed hexes
   (including deliberately hostile cases — neon, muddy, near-
   greyscale, pure primaries) and asserts: APCA `Lc` ≥ 75 for
   every text-on-surface role pair; CIEDE2000 ≥ 5 between
   adjacent tonal stops; CIEDE2000 ≥ 15 between brand and each
   of success/warning/danger; Machado-deuteranopia-simulated
   ∆E2000 ≥ 10 for the same triples; Cohen-Or template fit
   energy below threshold.
2. Live cascade animation works in Chrome, Edge, Safari, and
   Firefox; degrades gracefully on Firefox ≤ 143 (instant nav,
   no jank). Reduced-motion users see an instant swap.
3. No hardcoded brand colour anywhere in the codebase outside
   `theming/repair.py`'s curated-neighbour fallback table (which
   only fires in genuinely hostile-seed cases AND emits a user-
   visible explanation).
4. Web, motion (Remotion), email (newsletter renderer), and
   static graphic outputs all consume the same DTCG-format
   palette JSON — zero drift across media.
5. Test suite green: the existing 678 passing tests still pass,
   plus ~80 new theming tests, with zero new structural skips.

**Effort estimate:** 3–4 engineering weeks of focused work,
front-loaded on Stages A–C (the token plumbing and the colour-
science package). Stages D–J each fit in 2–3 days once the
foundation is in place. Independently testable per stage so
the work can be parallelised across two engineers if needed.

---

## Phase 2 — Distinction (target: Aug 2026 → Feb 2027)

**Goal:** convert MediaHub's vertical advantages into visible,
marketable product surfaces. Win one geography + one governing body.

### 2.1 Commercial layer · ❌ **DEFERRED to pre-launch**

The deployment model has shifted: MediaHub is now a turnkey
single-org-per-deployment product. That changes how this work-stream
looks. Commercial path:

**Managed hosted SaaS:** stand up a managed
"club.mediahub.example" service. Each club gets their own subdomain
+ isolated instance. The operator pays for hosting + Buffer +
LLM provider costs; charges the club £30–50/mo. Single-org per
instance means no multi-tenant gymnastics in the app code, and
customers access the product through their browser — they never
install or run anything locally.

The commercial layer needs to ship near launch:

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

**Phase 1 status:** 1.1, 1.2, 1.3, 1.4, 1.5 SHIPPED. **1.6 Adaptive
Theming Engine** opened May 2026 and is the immediate priority — it
makes the brand-DNA work (1.1) and the brand-kit upload flow actually
*feel* like the user's product the moment they accept the captured
brand. Until this lands, "single-org-per-deployment" is a promise
the chrome doesn't keep.

1. **Adaptive Theming Engine (1.6).** Ship Stages A–C (token
   foundation + colour-science package + CSS architecture)
   first; they're the foundation that unlocks everything else.
   Then E (the cascade animation on "Looks right – start
   creating"), which is the user-visible moment. Stages F–J
   follow naturally. Branch: `claude/club-color-scheme-switcher`.

2. **Pilot deployment.** Stand up one production Render instance,
   set the env vars, invite one real club to use it for a month.
   This is the first real-world load test of the operator-managed
   model and will surface every UX hole the audits couldn't find.
   Operator runbook in [`docs/PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md).
   *Best run after 1.6 lands, so the pilot club's first impression
   is the themed product.*

3. **Sport expansion (2.2 athletics).** Unlocks the next tranche
   of buyers (track-and-field clubs). One quarter of work:
   canonical event taxonomy + result-file parser + PB/record/
   qualifier logic + copy templates.

4. **Athlete-facing surfaces (2.5).** Per-athlete personal share
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

### V9.6 (in flight)

- 🔵 **Phase 1.6 Adaptive Theming Engine** opened. Seventeen
  parallel research agents audited the academic and industry
  literature (Ottosson OKLab 2020, Sharma CIEDE2000 2005, Somers
  APCA, Material 3 Dynamic Color, Cohen-Or harmonic templates
  2006, O'Donovan colour-compatibility 2011, Machado CVD
  simulation 2009, Lalitha A R constrained-OKLCH 2025, plus
  W3C CSS Color 4/5 + Properties & Values API + View
  Transitions). Architecture: single-seed HCT → 5 tonal palettes
  × 13 tones → ~25 MD3 role tokens → CSS custom properties
  registered via `@property` + relative-colour syntax + `color-
  mix(in oklch)` so Python ships only the seed and the 5 palette
  anchors and the browser derives the remaining ~55 shades at
  runtime. QA gates: APCA Lc, CIEDE2000 ΔE adjacency + brand-vs-
  status, Machado-CVD simulation, Cohen-Or harmonic fit. Smooth
  cascade animation via View Transitions API + `@property`
  interpolation. Single DTCG-format JSON consumed by web,
  Remotion motion, newsletter HTML, and the static graphic
  renderer. Branch: `claude/club-color-scheme-switcher`.

### Future (V10+ vision, retained from previous roadmap)

- Real-time meet feed (live captioning while a session is on)
- Native iOS / Android share-sheet integration
- A learnable ranker that takes `like_rate` feedback from posted
  content
- Move from JSON ledgers to Postgres
- WebSocket pipeline status (replace `/api/runs/<id>/status` polling)
