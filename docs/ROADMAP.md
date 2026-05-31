# MediaHub Roadmap

## In plain words (start here)

A **roadmap** is our plan for what to build next, and *why*. MediaHub's plan has
three big stages:

1. **Catch up** (we call it *Parity*) — make MediaHub as polished as the big,
   general-purpose tools everyone already knows.
2. **Stand out** (*Distinction*) — do things for sports clubs that those big,
   general tools simply can't.
3. **Lead** (*Leadership*) — become the tool every club, society and team reaches
   for first.

Below, each task carries a little badge so you can see how it's going:
✅ done · 🔵 in progress · ⚠️ stuck · ❌ not started yet.

The **"Last updated"** line and the **"Recent activity"** table further down update
themselves automatically whenever we ship something — you don't edit those by hand.

> New to the team? Read **[../START_HERE.md](../START_HERE.md)** first, then come
> back here to see what's next. Hit a tricky word? See
> **[../GLOSSARY.md](../GLOSSARY.md)**.

---

> **Reading this:** the single forward-looking roadmap for MediaHub —
> Phase 1: Parity → Phase 2: Distinction → Phase 3: Leadership. Only
> *not-yet-done* work is tracked here; shipped work has been removed to
> keep this relevant to **now** — the one exception is the just-shipped
> §1.6, retained with its acceptance audit. Runnable implementation +
> verification prompts live in the appendices: **Appendix A** (Generative
> Content Engine v2), **Appendix B** (growth & expansion), and
> **Appendix C** (Adaptive Theming Engine — acceptance-verification
> prompts for the now-shipped §1.6).

**Strategic thesis:** preserve the moat (the sport-grounded intelligence
layer), close the polish gap to the horizontal players, and
operationalise the niche so thoroughly that no generalist platform can
credibly serve a club, society or team without going through MediaHub.

---

## Roadmap status (auto-updated)

This roadmap stays current automatically. A GitHub Action
([`.github/workflows/roadmap-autoupdate.yml`](../.github/workflows/roadmap-autoupdate.yml),
backed by [`scripts/roadmap_autoupdate.py`](../scripts/roadmap_autoupdate.py))
refreshes the stamp and activity feed below on **every push to `main`**, and
flips an item's status badge when a commit message contains a directive line:

> `roadmap: <ID> <status>` — where `<ID>` is a phase (`1.6`, `2.1`, …) or an
> Appendix item (`PAR-1`, `SEQ-1`, `Step 8`), and `<status>` is one of
> `done` · `wip` · `blocked` · `todo`. Example commit trailer:
> `roadmap: SEQ-1 done`.

<!-- ROADMAP:LAST_UPDATED -->
**Last updated:** 2026-05-31 · `401479c10` · Merge pull request #197 from elijahkendrick04/claude/decontaminate-find
<!-- /ROADMAP:LAST_UPDATED -->

**Recent activity**

<!-- ROADMAP:ACTIVITY -->
| Date | Commit | Summary |
|---|---|---|
| 2026-05-31 | `d0e77590d` | decontaminate FIND/adjudicate: provenance guard, council framing, meta-filter, dedup |
| 2026-05-31 | `abd5592df` | chore(lint): clear ruff F401/F811 debt + format touched files |
| 2026-05-31 | `5c8670678` | fix(review): explain zero-card runs when no swims match the club (#196) |
| 2026-05-31 | `8be81920b` | docs(adr): council verdict — do not integrate jcode (#188) |
| 2026-05-31 | `21af4f990` | autopilot: persist builder state [skip ci] |
| 2026-05-31 | `02ac71cef` | Deterministic, approval-gated caption voiceover (council verdict on Pixelle-Video) (#195) |
| 2026-05-31 | `872230785` | feat(council): the Council as repo decision authority, wired into Claude Code (#192) |
| 2026-05-31 | `c4aa2e880` | docs: ADR 0002 — decline CloakBrowser integration (council verdict) (#189) |
| 2026-05-31 | `9d69cb486` | Vendor a curated subset of mattpocock/skills (reference only) (#190) |
| 2026-05-31 | `1e1aa8a5c` | docs: reject 9router integration (ADR 0002) after council review (#191) |
<!-- /ROADMAP:ACTIVITY -->

---

## Where we are today (May 2026)

Two structural facts shape the work ahead:

1. **The intelligence layer is the moat and is already ahead.** The
   sport-grounded pipeline — brand DNA + guidelines ingestion, voice
   imitation, and the AI-derived operating profile that replaces every
   hardcoded judgment constant — is shipped and live. No generalist
   player can replicate it without paying the same vertical
   data-pipeline cost. The forward work is closing the *polish* gap on
   top of that moat (theming, then the generative content engine).

2. **The product is operator-managed and turnkey for users.** All
   configuration (LLM keys, Buffer access token, cutout providers)
   is set once via env vars at deploy time. There is no user-facing
   settings UI; the end user lands on the home page, sets up their
   organisation, and creates content. They never see a knob.

The operational layers below the intelligence (publishing,
reliability, athlete-facing surfaces, sport coverage) remain the
diagnosed gap. Commercial layer is deliberately deferred until the
product is genuinely ready for paying customers.

### The deployment model

MediaHub is now a **single-org-per-deployment** turnkey product:

- The operator (you, or a club's IT person) deploys MediaHub on
  Render (or any Docker host) and sets two env vars: `GEMINI_API_KEY`
  (free) and `BUFFER_ACCESS_TOKEN`. Optionally `ANTHROPIC_API_KEY`
  with `MEDIAHUB_LLM_PROVIDER=anthropic` for paid Claude quality.
- The end users (the club's social-media volunteers, coaches,
  parents) reach the deployment URL, set up their organisation,
  and use the product. They never see a configuration screen.
- Cost to the operator at default config: ~$25–35/month total
  (Render Standard + Buffer Essentials + Gemini free tier). Standard
  is the floor because Remotion's Chromium render needs more than
  the 512 MB Starter tier offers; the free-tier LLM covers the
  small-club business model end-to-end.

Multi-tenant SaaS (multiple clubs sharing one MediaHub instance) is
Phase 3 work — both architecturally and commercially.

---

## Phase 1 — Parity (target: complete by Aug 2026)

**Goal:** any visiting club can land on the deployment URL, set up
their organisation, generate content, schedule it through Buffer,
and trust the uptime — *all in under twenty minutes from a cold
start.* This is the Holo / Blaze parity benchmark, adapted to the
operator-managed deployment model.

### 1.6 Adaptive Theming Engine · ✅ **DONE**

> ✅ **Shipped — May 2026.** All ten stages (A–J) have landed and are
> live by default (`MEDIAHUB_ADAPTIVE_THEME` defaults on). The
> `theming/` colour-science package (10 modules), the five-layer CSS
> cascade (`theme-base` / `theme-derive` / `theme-cascade` /
> `theme-components` / `theme-fallback`), the single-source
> `theme_store.py` JSON consumed by web + motion + email + static
> graphic, and `docs/THEMING.md` are all in `main`, with the full
> `tests/theming/` suite green. The Stage table below is retained as
> the shipped-scope record (every row ✅). **Acceptance-verification
> prompts — one per stage — live in Appendix C.** Run them to
> independently confirm the engine still meets the §1.6 acceptance
> criteria below.

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
trail and cited inline in `docs/THEMING.md` (authored in
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
| **A — Token foundation** | A1 Audit every hardcoded colour in `web.py` (~1,400 lines of inline CSS) and migrate to CSS variables | ✅ | Mechanical. No behaviour change. Output: one inventory of every literal `#…` or rgba() in templates |
| | A2 Adopt 3-tier token system (primitive → semantic role → component) per [W3C Design Tokens DTCG spec](https://www.designtokens.org/TR/drafts/format/); ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`, `--mh-primary`, `--mh-on-primary`, `--mh-primary-container`, `--mh-on-primary-container`, `--mh-secondary`, `--mh-tertiary`, `--mh-outline`, `--mh-outline-variant`, `--mh-error`, `--mh-success`, `--mh-warning`, `--mh-focus`, `--mh-elevation-{1,2,3}`) | ✅ | Single source of truth. Tier 3 (component tokens) deferred per Curtis's "promote on 3+ component reuse" rule |
| | A3 Register every animatable variable via `@property { syntax: "<color>"; inherits: true; }` so they interpolate smoothly through theme switches | ✅ | Without `@property`, CSS custom properties are untyped strings and `transition` silently snaps |
| **B — Colour science library** | B1 Add `materialyoucolor` + `coloraide` to `requirements.txt` (both pure-Python, Apache-2.0, no JS runtime); avoid `colorthief` (already replaced by Pillow extractor in Phase 1.5) | ✅ | One known transitive dep (numpy) already present |
| | B2 New `src/mediahub/theming/` package: `seed_extract.py` (SVG fast-path → rasterise → QuantizerCelebi → Score), `palette.py` (HCT seed → 5×13 tonal palettes), `roles.py` (palettes → MD3 role-token map for light + dark schemes), `contrast.py` (APCA `Lc` + ink-on-surface), `cvd.py` (Machado 2009 matrices for deutan/protan/tritan), `quality.py` (all QA gates → `PaletteQualityReport`), `repair.py` (constraint-satisfaction loop: clamp chroma → sweep L → relax H ±8° → curated-neighbour fallback) | ✅ | ~6 small modules, each independently unit-testable. Ports the relevant `material-color-utilities` paths via the maintained Python package |
| | B3 Persist resolved palette on `ClubProfile.brand_kit.derived_palette` — compute once on save, never per-request | ✅ | Matches existing `brand/derived.py` operating-profile cache pattern |
| **C — CSS architecture** | C1 Extract inline CSS from `web.py` (the ~1,400-line `<style>` block starting at `web.py:1363`) into `src/mediahub/web/static/theme-base.css`; content-hashed asset URL for cache-bust | ✅ | Big mechanical change; gated behind a feature flag during cutover |
| | C2 Build the derivation graph in pure CSS via `color-mix(in oklch, …)` and relative-colour syntax (`oklch(from var(--mh-brand-seed) calc(l ± n) calc(c * f) h)`) — Python ships ~6 anchor values, CSS derives the remaining ~55 shades | ✅ | Drastically reduces the "hardcode surface area" the user mandated. CSS engine is the single source of truth for the cascade |
| | C3 Add `light-dark()` for surface/ink pairs; honour `prefers-color-scheme: dark/light` so the same seed produces correct light + dark variants without a duplicate stylesheet | ✅ | Spec status: Baseline 2024 |
| | C4 Add Python-precomputed fallback ramp inside `@supports not (color: oklch(from red l c h))` for Safari ≤ 16.3 (relative-colour syntax landed Mar 2023; the gate catches the remaining ~10% long-tail) | ✅ | No JS polyfill; pure-CSS feature query |
| **D — Theme delivery (Flask)** | D1 `before_request` middleware loads the active `ClubProfile`'s `derived_palette` into `flask.g.theme` (already partially in place via the org-gate; extend it) | ✅ | Single-org-per-deploy today; one-line extension to subdomain-based multi-tenant lookup for Phase 3 |
| | D2 Jinja base template emits one inline `<style id="mh-theme-seed">:root { --mh-brand-seed: {{ g.theme.seed }}; --mh-scheme-polarity: {{ g.theme.polarity }}; … }</style>` in `<head>` *before* any external stylesheet — zero FOUC | ✅ | Tiny payload (~250 bytes) vs the cacheable static `theme-base.css` |
| | D3 Re-render cached pages (sponsor-variant page, sponsor-branded layouts) so they consume the new variables instead of hardcoded hexes | ✅ | Audit pass after C1 |
| **E — "Looks right" cascade** | E1 Wire the existing button at `web.py:11014` so its click handler: (i) saves the brand kit, (ii) calls `theming.derive_from_seed(seed)` and persists `derived_palette`, (iii) wraps navigation to `/add-input` in `document.startViewTransition(() => location.assign(…))` | ✅ | The user-visible "wow" moment — fires on the exact button the user named |
| | E2 Add `@view-transition { navigation: auto; }` to `theme-base.css` so cross-document navigation between pages crossfades atomically (Chrome 126+ / Safari 18.2+, Firefox in progress) | ✅ | Pure CSS; degrades to instant nav on older browsers |
| | E3 Add `:root { transition: --mh-brand-seed 600ms cubic-bezier(.2,.7,.2,1); }` so the colour ripples through the page even when View Transitions isn't available — because every derived var is `color-mix(in oklch, var(--mh-brand-seed) …)`, the entire palette interpolates in lockstep for free | ✅ | One line per animatable token |
| | E4 Gate animation with `@media (prefers-reduced-motion: reduce)` — instant swap for users who request it | ✅ | WCAG 2.3.3 |
| **F — Logo intelligence** | F1 Default to a neutral chip behind every uploaded logo (auto-pick white/near-white rounded chip with 12px padding, sized to logo bounding box) — never recolour unknown SVG marks | ✅ | Matches Adobe Spectrum, IBM Carbon, BBC brand-book defaults |
| | F2 "Safe to drop chip" auto-detection: compute the logo's dominant non-neutral colour vs the active surface in OKLCH; if ΔE2000 ≥ N AND APCA Lc ≥ 45 in both polarities, render bare; otherwise chip | ✅ | Honest about when it's safe to skip the chip |
| | F3 Author MediaHub's own SVG marks with `fill="currentColor"` so the product chrome auto-adapts to ink colour without recolouring; **never** auto-inject this on uploaded logos | ✅ | Per W3C SVG2 spec; the Material You "ship a monochrome layer if you want it tintable" lesson |
| **G — Single source of truth for motion + email** | G1 Convert `derived_palette` to DTCG-format JSON at `DATA_DIR/themes/<profile_id>.json` | ✅ | Aligns with the W3C Design Tokens spec; future-proofs against Style Dictionary integration |
| | G2 `visual/motion.py` reads the JSON and passes it as `inputProps` to `render.js`; Remotion compositions consume the same tokens as the web UI | ✅ | Single source of truth across MP4 + browser |
| | G3 `brand/newsletter_renderer.py` reads the JSON and Premailer-inlines the resolved hex values into outgoing HTML emails (email clients don't reliably support CSS custom properties) | ✅ | Same JSON, different rendering target |
| | G4 `graphic_renderer/render.py` reads the same JSON, replacing today's `BrandKit.primary_colour` lookups | ✅ | Closes the loop: web, motion, email, static graphic all share one palette |
| **H — Explainability + QA** | H1 Every palette derivation logs a `PaletteQualityReport` to the run audit trail: APCA `Lc` scores for every role pair, CIEDE2000 matrix for brand × {neutral-500, success, warning, danger}, Machado-CVD ∆E2000 for the same pairs under deutan/protan/tritan, Cohen-Or harmonic-template fit energy, and a decision trace ("clamped chroma 0.30 → 0.21 to fit sRGB; shifted hue +6° to keep success-green distinct under deuteranopia") | ✅ | Matches MediaHub's standing rule: "every step should be explainable and auditable" |
| | H2 Add a "Why does my theme look like this?" expandable panel to `/organisation/setup` — committee members see the decisions and contrast scores, can override an individual role colour if they really must, and the override gets logged with a cultural-clash warning if it lowers a status colour's ΔE | ✅ | Trust signal; mirrors the brand-DNA "What MediaHub learned" panel |
| | H3 Non-blocking warning surface if the hostile-seed repair loop fired: *"Your brand yellow (#DFFF00) was very close to our success-green (#1F9D55); we adjusted the success colour by +8° to keep them distinct for colour-blind viewers."* | ✅ | Never silently rewrite the brand colour; only adjust the *status* colour and tell the user why |
| **I — Test coverage** | I1 New `tests/theming/` directory: `test_seed_extract.py`, `test_palette.py` (golden-master snapshots for ~30 representative seeds including fluorescent yellow `#DFFF00`, muddy dark green `#2A3A1A`, near-white `#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, plus 10 real club colours), `test_contrast.py` (APCA Lc gates), `test_cvd.py` (Machado simulator parity vs known fixtures), `test_quality.py`, `test_repair.py` | ✅ | Snapshots make regressions obvious in PR review |
| | I2 Playwright/browser-use end-to-end test: upload a logo → land on `/add-input` → assert `getComputedStyle(document.documentElement).getPropertyValue('--mh-surface')` matches the expected derived value | ✅ | Gated on `MEDIAHUB_RUN_BROWSER_TESTS=1` like the existing motion tests |
| **J — Cutover + polish** | J1 Replace the existing hardcoded palette in `web.py:1363-1462` by reading from `theming/`; gate behind a feature flag (`MEDIAHUB_ADAPTIVE_THEME`) during the rollout window | ✅ | Cutover is reversible while the new pipeline is observed in production |
| | J2 Run the generic-default `BrandKit` (`#0E2A47` navy / `#C9A227` gold) through the new pipeline so the unconfigured first-run experience also gets the upgrade | ✅ | No regression for fresh deployments before brand DNA is captured |
| | J3 Author `docs/THEMING.md` documenting the architecture, the role-token table, the CSS variables operators may safely override in a custom `theme-override.css`, and the academic references inline | ✅ | Single canonical doc for future contributors |

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

### 1.7 Generative Content Engine v2 · 🔵 **NEW — PLANNED (the "worth paying for" overhaul)**

**The promise.** Make "click generate" produce content worth paying for:
distinctive (not the same card every time), unmistakably on-brand, provably true,
offered as a *ranked shortlist of options*, in every format. This is the direct
response to the standing complaint that generation produces "a standard boring
graphic every time that isn't unique."

**The diagnosis (grounded in code).** Today's generation selects a tuple from a
bounded, hand-authored option space dominated by ~6 layout skeletons
(`creative_brief/generator.py`), with an LLM constrained to *menu-pick* from fixed
enums (`creative_brief/ai_director.py`) and a renderer that repaints one DOM
(`graphic_renderer/render.py`). It is parameterised reskinning, not generative
design. Captions (`web/ai_caption.py`) are the one genuinely generative, already-good
surface. Full analysis: `docs/research/mediahub-generative-ai-thesis.md` (the plan)
and `docs/research/generation-engine-competitor-evaluation.md` (how the 2026 field
generates content — researched by 16 agents, fact-checked by 10).

**The architecture (thesis §5).** Keep the deterministic engine, captions,
Remotion, and the renderer substrate; *replace the variation mechanism* with: a
**brand-token contract** (extends §1.6's DTCG tokens with logo lockups, type
pairing, voice profile, and semantic role descriptions an LLM can read) → an
**archetype library + layout intelligence** (12–20 structurally distinct templates,
auto-fit text, saliency crops, varied data-emphasis — Tier A, deterministic, fixes
"samey" on its own) → an **LLM design-spec director** that emits a structured JSON
spec a deterministic renderer executes (Tier B, "AI judges, maths renders") →
**generate-a-pool, rank, and a deterministic brand-compliance check** → optional
**generative backgrounds** under the deterministic text (Tier C). Video inherits the
richer brief and gains data-driven scene structure. Generative *video B-roll* stays
an opt-in premium (the one expensive item).

**Relationship to §1.6.** This builds *on* the Adaptive Theming Engine, not beside
it — §1.6 delivers the token plumbing and single-source-of-truth JSON; §1.7 extends
that contract and consumes it in the generators. Sequence §1.6 Stage G before, or
alongside, §1.7 SEQ-0.

**Cost (thesis §6).** Marginal generation ≈ cents/pack (~$0.15–0.50), ~90% gross
margin; build ≈ 2–3 focused months, with Tier A shippable in the first month;
dominant cost is human (authoring archetypes), not compute.

**Build breakdown & runnable prompts:** see **Appendix A** at the end of this document — a
**parallel bucket** (8 additive/inert items runnable now in concurrent sessions →
PR to `main`) and a **sequential spine** (SEQ-0 tokens → SEQ-1 Tier A → SEQ-2 Tier B
→ SEQ-3 cutover+gated-removal → SEQ-4 video), each with an implementation and a
verification prompt. SEQ-3 follows CLAUDE.md's gated removal process (15-step
breakage check + 15-step verification + dead-code sweep).

| Track | Item | Status |
|---|---|---|
| Parallel (now) | PAR-1 caption quality pack · PAR-2 auto-fit · PAR-3 saliency crop · PAR-4 design-spec schema · PAR-5 variant metrics · PAR-6 brand bootstrap · PAR-7 archetype templates (×N) · PAR-8 docs/ADR | ❌ NOT STARTED |
| Spine | SEQ-0 DesignTokens contract + `MEDIAHUB_GEN_V2` flag | ❌ NOT STARTED |
| Spine | SEQ-1 Tier A (archetype library + layout intelligence) — *the immediate fix* | ❌ NOT STARTED |
| Spine | SEQ-2 Tier B (design-spec director + pool/rank/compliance) | ❌ NOT STARTED |
| Spine | SEQ-3 Cutover + gated removal of the enum/menu-picker engine | ❌ NOT STARTED |
| Spine | SEQ-4 Video data-driven scene structure (+ optional Tier C) | ❌ NOT STARTED |

**Fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (parallel, now) → SEQ-0 →
SEQ-1 (Tier A). No LLM-director work required to resolve the core complaint.

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
buyers see the trajectory (the FanWord lesson from the competitor analysis).

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

**The Adaptive Theming Engine (1.6) has shipped** — the brand-DNA work
and the brand-kit upload flow now actually *feel* like the user's product
the moment they accept the captured brand; "single-org-per-deployment" is
a promise the chrome finally keeps. Audit it against the acceptance
criteria with the prompts in **Appendix C**. **The immediate priority is
now the Generative Content Engine v2 (1.7)** — its runnable build prompts
already live in **Appendix A**.

1. **Generative Content Engine v2 (1.7).** Run the build prompts in
   **Appendix A**. Fastest path to fixing "samey": the parallel
   bucket (PAR-2 auto-fit + PAR-3 saliency crop + PAR-7 archetypes,
   each its own session) → then the spine SEQ-0 (tokens) → SEQ-1
   (Tier A archetype library). No LLM-director work is required to
   resolve the core complaint. (Adaptive Theming, 1.6, is done —
   verify it with Appendix C.)

2. **Pilot deployment.** Stand up one production Render instance,
   set the env vars, invite one real club to use it for a month.
   This is the first real-world load test of the operator-managed
   model and will surface every UX hole the audits couldn't find.
   Operator runbook in [`docs/PILOT_PLAYBOOK.md`](PILOT_PLAYBOOK.md).
   *1.6 has landed, so the pilot club's first impression is already
   the themed product.*

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

## Appendix A — Generative Content Engine v2: Build Prompts

> *Section numbers in this appendix (§0–§5) and item IDs (PAR-\*, SEQ-\*) are local to the appendix. This was previously a standalone doc; it is merged into the roadmap so there is a single reference. It is the build breakdown for §1.7 above.*

**What this is.** An execution roadmap that turns the recommendations in
`docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md` into ordered,
runnable build stages — *taking the advice in those documents as fact* — with an
implementation prompt and a verification prompt for every stage, and a separate
**parallel bucket** of work that can be run right now, simultaneously, in
different Claude sessions and merged to `main` in any order without conflicts.

**Date:** May 2026 · **Built against:** `main` after PR #137 (the trimmed
CLAUDE.md with the *gated removal process*) and PR #136 (the research docs).

**The problem being solved (from the thesis).** "Click generate" selects a tuple
from a bounded, hand-authored option space dominated by ~6 layout skeletons, with
an LLM constrained to *menu-pick* from fixed enums (`creative_brief/ai_director.py`)
and a renderer that repaints one DOM (`graphic_renderer/render.py`). The fix is to
replace the variation mechanism with: a **brand-token contract** → an **archetype
library + layout intelligence** (Tier A) → an **LLM design-spec director** (Tier B)
→ **generate-a-pool, rank, and compliance-check**, while keeping the deterministic
engine, the captions, Remotion, and the renderer substrate.

---

### 0. How to use this document

There are **two tracks**:

- **The Parallel Bucket (§2)** — additive, file-disjoint work that does **not**
  affect the build because each item ships *new, inert files* (or owns one
  isolated surface). These can be run **now**, each in its own Claude session,
  each on its own branch → PR to `main`. They are wired into the live pipeline
  later by the spine. **Run these first / concurrently.**
- **The Sequential Spine (§3)** — build-order-dependent work that modifies the
  shared files (`generator.py`, `ai_director.py`, `render.py`,
  `content_pack_visual/integration.py`, the `web.py` route) and *wires in* the
  parallel modules. These must be done in order, behind the `MEDIAHUB_GEN_V2`
  flag, and the removal stage follows CLAUDE.md's gated-removal process.

Each stage has a **Context** (what/why + files + thesis ref), an **Implementation
prompt** (paste into a fresh session), and a **Verification prompt** (paste into a
*separate* session to confirm it was done properly).

#### Relationship to the in-flight Adaptive Theming Engine (ROADMAP 1.6)

Do **not** rebuild the brand-token system. ROADMAP §1.6 already delivers the
DTCG-format `derived_palette`, ~25 MD3 role tokens, and a single-source-of-truth
JSON consumed by web/motion/email/graphic (Stage G). The thesis's "Layer 1 — brand
token contract" is **mostly that work, extended** with three generation-specific
additions (logo lockups by theme/form, type pairing, a structured voice profile,
and *semantic role descriptions an LLM can read*). SEQ-0 below extends the theming
token object; it does not duplicate it. If 1.6 Stage G is not yet merged, SEQ-0
coordinates with it rather than forking it.

---

### 1. The shared prompt preamble (every prompt inherits this)

To keep each prompt short, every Implementation and Verification prompt below
**assumes this preamble**. Paste it at the top of the session if the model hasn't
read the repo yet:

> **Preamble — read before doing anything.** You are working in the MediaHub repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md` in full, plus
> `docs/research/mediahub-generative-ai-thesis.md` (the plan) and the file(s) named
> in the task. Hard rules you must follow:
> - **Deterministic engine is off-limits to AI:** never Gemini-ify parsers
>   (`interpreter/`, `pb_discovery/`), detectors (`recognition*/`), the ranker
>   (`legacy/swim_content_v5/ranker_v3.py`), or colour-science (`theming/`,
>   CIEDE2000/APCA). You may *read* their outputs.
> - **Honest error, never a fake fallback:** if an AI provider is unavailable,
>   surface `ProviderNotConfigured`/`ClaudeUnavailableError` or fall back to a
>   *real deterministic* path — never a fabricated caption/graphic.
> - **Judgement goes through `media_ai.llm` / `ai_core.llm`** — never new hardcoded
>   heuristics for "which layout / which copy / which tone."
> - **Removing or replacing a route or data structure** requires CLAUDE.md's
>   *15-step breakage check before* + *15-step verification after* + a *dead-code
>   sweep*. Do not skip it.
> - **Tests:** run `python -m pytest tests/ -q` and add tests for new code; there
>   must be **no new failures** vs `main`, and you must not delete/skip/weaken a
>   test to go green.
> - **Branch & ship:** create a feature branch `claude/<short-name>`, commit with a
>   clear message, push, and **open a PR** (do not merge to `main` without the
>   user's approval — the user merges).
> - **Scope discipline:** touch only the files this task names. If you find you need
>   to modify a file the task says not to touch, stop and report instead.

---

### 2. The Parallel Bucket — run these now, concurrently, one session each

**Why these are safe to run simultaneously and merge in any order:** every item
below either creates **only new files** (inert — nothing imports them yet, so the
build is unaffected) or owns a **single isolated surface** that no other item and
no spine stage touches. The "Files you may touch" / "Files you must NOT touch"
lists guarantee no two parallel PRs edit the same file. Merge them to `main` in any
order; the spine (§3) wires them in afterward.

> **Conflict-safety contract (applies to every PAR item):** You may create/modify
> **only** the files listed under "Owns." You must **NOT** touch `web/web.py`,
> `creative_brief/generator.py`, `creative_brief/ai_director.py`,
> `graphic_renderer/render.py`, or `content_pack_visual/integration.py` (those are
> spine files). Your change must leave the existing build and tests green on its own.

#### PAR-1 · Caption quality pack
**Owns:** `src/mediahub/web/ai_caption.py` (the only item that touches it) + new
`src/mediahub/web/caption_examples.py` + `tests/test_caption_quality.py`.
**Context:** Captions are already strong (thesis §5.6); this adds the verified
brand-voice recipe. Independent of the graphic surgery.

**Implementation prompt:**
> [Preamble.] Extend MediaHub's caption generation (`web/ai_caption.py`) with the
> brand-voice recipe from thesis §5.6, all inside the existing Gemini→Anthropic
> path. Add: (1) **few-shot injection** — accept up to 5 of the club's own past
> captions and inject them verbatim as examples in the system prompt (store/read
> them via a new `web/caption_examples.py` keyed by `profile_id`, persisted under
> `DATA_DIR`); (2) **generate-many-then-dedupe** — generate 4–6 candidates and
> return them ranked, dropping any whose n-gram/embedding similarity to a recent
> caption or to each other is above a threshold; (3) **per-platform variants** —
> given one approved caption, produce feed / story / X / LinkedIn variants with
> per-platform length+tone constraints; (4) an explicit **AI-tell ban-list**
> ("delve", "elevate", "in the world of", reflexive "!"); (5) an **approval-loop**
> hook: a function that appends an edited+approved caption to the club's
> few-shot example store. Keep the existing function signatures working
> (additive params with defaults). Add `tests/test_caption_quality.py` covering
> dedupe, ban-list filtering, and few-shot injection (mock the LLM). Do NOT touch
> any spine file. Branch `claude/gen-par-1-captions`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-1 (caption quality pack) was done properly. Confirm:
> only `web/ai_caption.py`, `web/caption_examples.py`, and the new test were
> changed (no spine files); the existing caption route still works with the new
> defaults; few-shot examples are injected and capped at 5; dedupe actually drops
> near-duplicates; the ban-list filters the listed phrases; the approval-loop
> appends to the store; captions still raise an honest error (no fabricated
> fallback) when no provider is configured. Run the full suite — no new failures.
> Report a pass/fail checklist.

#### PAR-2 · Auto-fit text helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/autofit.py` + `tests/test_autofit.py`.
**Context:** Bannerbear's verified core feature (eval §6.1). A pure function that
computes the font-size (px) that fits a string into a given box at a given
font/weight, so long names/events never break a layout. Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/autofit.py`: a pure, deterministic helper
> `fit_font_px(text, box_w, box_h, *, font_family, weight, min_px, max_px,
> line_height) -> int` that returns the largest integer px size at which `text`
> fits within `box_w × box_h` (binary search; approximate advance-width via a
> char-width table or Pillow `ImageFont.getbbox` if a font file is available, else
> a metric heuristic — but keep it deterministic and documented). Add helpers for
> multi-line wrapping. No network, no LLM (this is layout maths, not judgement).
> Add `tests/test_autofit.py` with golden cases (short vs very long swimmer names,
> narrow vs wide boxes). Create ONLY these two files. Branch
> `claude/gen-par-2-autofit`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-2: only `graphic_renderer/autofit.py` and its test were
> added; `fit_font_px` is deterministic (same inputs → same output), monotonic
> (a longer string never returns a larger size for the same box), respects
> min/max bounds, and has no LLM/network calls. Run the suite — no new failures.

#### PAR-3 · Saliency-aware crop helper (standalone, inert)
**Owns:** new `src/mediahub/graphic_renderer/saliency.py` + `tests/test_saliency.py`.
**Context:** Subject-aware crops (eval §6.1, thesis §5.3.1) so one archetype looks
correct and different with every photo. Deterministic maths (consistent with the
colour-science rule). Inert until SEQ-1 calls it.

**Implementation prompt:**
> [Preamble.] Create `graphic_renderer/saliency.py`: deterministic helpers that,
> given an image path, return candidate crop rectangles for a set of target aspect
> ratios (e.g. `9:16`, `1:1`, `4:5`) using a saliency/energy heuristic (e.g.
> gradient-magnitude / edge density via Pillow+numpy, or reuse the existing cutout
> alpha if present to bias toward the subject). Expose
> `crops_for(image_path, ratios) -> dict[ratio, (x,y,w,h)]` and a
> `best_crop(image_path, ratio)`. No LLM, no network. Add `tests/test_saliency.py`
> with a couple of synthetic images (subject in different corners) asserting the
> crop tracks the subject and stays within bounds. Create ONLY these two files.
> Branch `claude/gen-par-3-saliency`, test, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-3: only the saliency module + test were added; crops are
> deterministic, stay within image bounds, match the requested aspect ratios, and
> track the subject on the synthetic fixtures; no LLM/network. Suite green.

#### PAR-4 · Design-spec schema + validator (the Tier B contract, inert)
**Owns:** new `src/mediahub/creative_brief/design_spec.py` + `tests/test_design_spec.py`.
**Context:** The structured JSON contract the LLM art-director will emit (thesis
§5.4). Defining it as a standalone schema + normaliser now lets SEQ-2 just call it.
Inert until the director uses it.

**Implementation prompt:**
> [Preamble.] Create `creative_brief/design_spec.py` defining the `DesignSpec`
> dataclass and a strict `normalise(raw: dict, *, archetypes: list[str],
> token_roles: list[str]) -> DesignSpec` that coerces a (possibly hallucinated)
> LLM JSON object into a valid spec — every field constrained to a known enum or a
> token *role* name, with safe defaults on any out-of-vocabulary value (so a bad
> LLM response can never produce an illegal/illegible card). Fields per thesis
> §5.4: `archetype`, `colour_roles` (ground/surface/headline/accent → role names),
> `focal_element`, `crop_intent`, `hero_stat`, `secondary_stats`, `headline_hook`,
> `accent_treatment`, `logo_lockup`, `mood`, `motion_intent`, `rationale`. Provide
> the JSON-schema dict for schema-constrained decoding. No live LLM call here — this
> is the contract + validator only. Add `tests/test_design_spec.py` (valid spec
> round-trips; hallucinated/garbage values normalise to defaults; enums enforced).
> Create ONLY these two files. Branch `claude/gen-par-4-design-spec`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-4: only the design_spec module + test were added; an
> out-of-vocabulary value for every field normalises to a safe default; the schema
> dict matches the dataclass; no card-illegal spec can be produced. Suite green.

#### PAR-5 · Variant metrics module (success-metric instrumentation, inert)
**Owns:** new `src/mediahub/quality/variant_metrics.py` + `tests/test_variant_metrics.py`.
**Context:** Thesis §8C success metrics — archetype diversity and perceptual
distance across a candidate pool. Standalone scoring lib; inert until SEQ-2 wires it.

**Implementation prompt:**
> [Preamble.] Create a new `quality/` package with `variant_metrics.py`:
> deterministic functions `archetype_diversity(specs) -> float` (distinct
> archetypes / candidates) and `perceptual_spread(png_paths) -> float` (mean
> pairwise distance using a cheap perceptual hash or downscaled-LAB histogram
> distance — no heavy ML). Add `caption_repetition(captions) -> float` (max n-gram
> overlap). These power the §8C targets. No LLM/network. Add
> `tests/test_variant_metrics.py`. Create ONLY the new package files + test.
> Branch `claude/gen-par-5-metrics`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-5: only the new `quality/` module + test were added;
> metrics are deterministic and bounded; diversity rises with distinct archetypes;
> spread rises with visually different PNGs. Suite green.

#### PAR-6 · Brand bootstrap extractor (draft from a URL, inert)
**Owns:** new `src/mediahub/brand/bootstrap_extract.py` + `tests/test_bootstrap_extract.py`.
**Context:** "Paste your club URL → draft brand kit" onboarding (thesis §5.3),
modelled on Brandfetch's schema. A pure extractor that returns a **draft**
DesignTokens dict (for human confirmation — never auto-trusted). It may *read* the
existing `brand/link_handlers/` but must not modify them or add a route (wiring is
SEQ work). Inert until onboarding calls it.

**Implementation prompt:**
> [Preamble.] Create `brand/bootstrap_extract.py`: `extract_brand_draft(url) ->
> dict` returning a *draft* token set (palette candidates with semantic guesses,
> logo URLs by inferred form, font guesses) shaped like the DesignTokens contract,
> reusing existing `brand/link_handlers/` for fetching where possible (read-only
> import). Mark every field `"confirmed": false`. No route, no web.py edit, no
> auto-apply. Honest about uncertainty (small-club extraction is unreliable — return
> confidence flags, never silently guess). Add `tests/test_bootstrap_extract.py`
> (mock the fetch; assert draft shape + all `confirmed:false`). Create ONLY these
> two files. Branch `claude/gen-par-6-brand-bootstrap`, test, PR.

**Verification prompt:**
> [Preamble.] Verify PAR-6: only the extractor + test were added; no route/web.py
> change; output is a draft (all `confirmed:false`), shaped like DesignTokens; the
> existing `link_handlers` were imported, not modified. Suite green.

#### PAR-7 · Archetype templates (the fan-out item — one session per archetype)
**Owns (per session):** ONE new file `src/mediahub/graphic_renderer/layouts/v2/<name>.html`
(+ optional `<name>.notes.md`). Run this prompt N times in N sessions, once per
archetype name — each writes a *different* file, so they never conflict.
**Context:** The structural variety the 6 families lack (thesis §5.3.1). Author
each against the **slot convention** below so SEQ-1 can wire them uniformly.

**Slot convention (author against this exactly):** use `{{PLACEHOLDER}}` string
substitution (not Jinja), and reference brand colours **only** via CSS custom
properties (`var(--mh-primary)`, `var(--mh-on-primary)`, `var(--mh-surface)`,
`var(--mh-on-surface)`, `var(--mh-accent)`, `var(--mh-outline)`) — never hardcode a
hex. Available text placeholders: `{{ATHLETE_FULL_NAME}}`, `{{ATHLETE_FIRST_NAME}}`,
`{{ATHLETE_SURNAME_DISPLAY}}`, `{{EVENT_NAME}}`, `{{RESULT_VALUE}}`,
`{{ACHIEVEMENT_LABEL}}`, `{{MEET_NAME}}`, `{{CLUB_FULL}}`, `{{HERO_STAT}}`,
`{{LOGO_BLOCK}}`, `{{ATHLETE_IMG_BLOCK}}`, `{{ACCENT_DECORATION}}`,
`{{SPONSOR_BLOCK}}`. Canvas is `{{WIDTH}}×{{HEIGHT}}`. Include `{{BASE_CSS}}` at the
top. The archetype must read *structurally distinct* from `individual_hero` /
`big_number_hero` at a glance.

**Suggested archetype names (assign one per session):** `split_diagonal_hero`,
`full_bleed_photo_lower_third`, `editorial_numbers_grid`, `centered_medal_spotlight`,
`magazine_cover`, `ticker_strip`, `stat_stack_sidebar`, `triptych_progression`,
`quote_led_recap`, `big_number_dominant`, `duo_athlete_split`, `minimal_type_poster`.

**Implementation prompt (template — fill in `<NAME>`):**
> [Preamble.] Author ONE new graphic archetype `graphic_renderer/layouts/v2/<NAME>.html`
> following the slot convention in `docs/ROADMAP.md` (Appendix A → PAR-7)
> exactly (CSS-variable colours only, the listed `{{PLACEHOLDERS}}`, `{{BASE_CSS}}`
> at top). It must be a *structurally distinct* portrait layout (1080×1350 and
> 1080×1920 must both read well) — a genuinely different composition from the
> existing families, not a reskin. Self-contained HTML/CSS; no JS, no network, no
> hex literals. Add a one-paragraph `<NAME>.notes.md` describing the composition and
> when the director should pick it. Create ONLY those file(s) under `layouts/v2/`.
> Do not touch `render.py` or any other file. Branch `claude/gen-par-7-<NAME>`,
> commit, open a PR. (You cannot fully render-test it until SEQ-1 wires `layouts/v2`;
> instead, validate the HTML is well-formed and every placeholder/variable matches
> the convention.)

**Verification prompt:**
> [Preamble.] Verify a PAR-7 archetype: exactly one new `layouts/v2/<NAME>.html`
> (+ notes) was added; it uses ONLY CSS-variable colours (grep for `#` hex literals
> → none in colour positions); every placeholder is on the §PAR-7 allow-list;
> `{{BASE_CSS}}` is present; the layout is structurally distinct from the existing
> families; no other file changed. Suite green (these files are inert, so the suite
> is unaffected — confirm that too).

#### PAR-8 · Documentation + ADR (pure docs, inert)
**Owns:** new `docs/GENERATION.md` + `docs/adr/0001-generation-engine-v2.md`.
**Context:** Single canonical doc for the new engine + an architecture-decision
record. Pure docs; conflicts with nothing.

**Implementation prompt:**
> [Preamble.] Author `docs/GENERATION.md` documenting the v2 generation
> architecture from thesis §5 (the token contract, archetype library, design-spec
> director, pool/rank/compliance, captions, video), the `layouts/v2` slot
> convention (copy it from this roadmap §PAR-7), and the `MEDIAHUB_GEN_V2` flag.
> Also author `docs/adr/0001-generation-engine-v2.md` recording the decision to
> replace the enum-permutation/menu-picker engine with the design-spec director
> (context, decision, alternatives rejected per thesis §4A, consequences). Docs
> only. Branch `claude/gen-par-8-docs`, open a PR.

**Verification prompt:**
> [Preamble.] Verify PAR-8: only the two docs were added; `GENERATION.md` matches
> thesis §5 and the §PAR-7 slot convention; the ADR records context/decision/
> alternatives/consequences. No code changed.

---

### 3. The Sequential Spine — build in order, behind `MEDIAHUB_GEN_V2`

These stages modify the shared spine files and wire in the parallel modules. They
**cannot** run concurrently with each other (they touch the same files); run them
in order, each as its own PR, after the parallel bucket is merged. Everything that
changes live behaviour is gated by the `MEDIAHUB_GEN_V2` feature flag until SEQ-3's
cutover, so production never regresses.

#### SEQ-0 · DesignTokens contract + feature-flag scaffolding
**Depends on:** ROADMAP §1.6 Stage G (DTCG `derived_palette` JSON) if merged; else
coordinate. **Touches:** `brand/kit.py`, a new `config`/flag read, `theming/` (read).
**Thesis ref:** §5.3.

**Implementation prompt:**
> [Preamble.] Extend the brand token object (`brand/kit.py` / the theming
> `derived_palette`) into the generation **DesignTokens contract** from thesis §5.3,
> *additively* — keep the existing flat `primary_colour`/`secondary_colour`/
> `accent_colour` as derived aliases so nothing breaks. Add: semantic colour
> **roles** with `brightness` + `when_to_use` text (reuse the existing APCA/ΔE2000
> numbers from `theming/`), **logo lockups** typed by `form`
> (icon/horizontal/stacked/mono) and `theme` (light/dark) — extend
> `theming/logo_chip.py` to *select* the lockup for a given background — a typed
> `type` pairing, and a structured `voice` profile (examples, banned phrases, emoji
> policy) that the caption store (PAR-1) can populate. Add a `MEDIAHUB_GEN_V2`
> feature flag read (env, default off) and a single helper
> `resolve_design_tokens(profile_id) -> dict` that returns the full contract with
> the semantic role descriptions an LLM can consume. No behaviour change yet (flag
> off). This is additive — the gated-removal process is NOT needed here. Add tests
> for `resolve_design_tokens`. Branch `claude/gen-seq-0-tokens`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-0: the old flat BrandKit fields still resolve (back-compat
> alias); `resolve_design_tokens` returns roles with `brightness`+`when_to_use`,
> logo lockups by form/theme, type pairing, and a voice profile; `logo_chip` selects
> a lockup per background; the `MEDIAHUB_GEN_V2` flag exists and defaults off; old
> persisted profiles still load. Suite green (no new failures); the change is purely
> additive (no removals).

#### SEQ-1 · Tier A — archetype library + layout intelligence (the immediate fix)
**Depends on:** SEQ-0, PAR-2 (autofit), PAR-3 (saliency), PAR-7 (archetypes),
optionally PAR-6. **Touches:** `graphic_renderer/render.py`,
`creative_brief/generator.py`, `legacy/swim_content_v5/ranker_v3.py` (read-only
addition). **Thesis ref:** §5.3.1. **This stage alone is expected to fix "samey."**

**Implementation prompt:**
> [Preamble.] Implement Tier A (thesis §5.3.1), gated behind `MEDIAHUB_GEN_V2`.
> (1) Teach `graphic_renderer/render.py` to load archetypes from
> `graphic_renderer/layouts/v2/*.html` (the PAR-7 files) using the documented slot
> convention, resolving colours from the DesignTokens roles (SEQ-0) as CSS
> variables. (2) Wire in `autofit.fit_font_px` (PAR-2) for headline/name/event
> slots so long strings never overflow. (3) Wire in `saliency.best_crop` (PAR-3) so
> the athlete photo is cropped per the archetype's `crop_intent`. (4) In
> `creative_brief/generator.py`, add a **deterministic archetype-picker** (seeded by
> the existing `auto_variation_seed_for`, stable per card, different across cards)
> that selects among the v2 archetypes — this is the no-AI fallback floor. (5)
> Expose, *read-only*, the ranker's ranked **emphasis angles** (lead with time / PB
> delta / placing / relay split) so the brief can vary the hero stat — do NOT change
> the ranker's scoring. With the flag ON, a content pack should use ≥6 distinct
> archetypes. Add tests asserting archetype diversity across a pack and that autofit
> prevents overflow. Branch `claude/gen-seq-1-tier-a`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-1: with `MEDIAHUB_GEN_V2=1`, rendering a pack uses ≥6
> distinct v2 archetypes; with the flag OFF, behaviour is unchanged (old engine).
> Long swimmer names/events no longer overflow (autofit); photo crops track the
> subject (saliency); the ranker's *scoring is byte-identical* to before (only a
> read-only emphasis-angle accessor was added — confirm no PB/ranking regression per
> CLAUDE.md engine rule). Walk upload→process→review with the flag on; cards render,
> captions/confidence intact. Suite green. Report the archetype-diversity number.

#### SEQ-2 · Tier B — design-spec director + pool, rank, compliance
**Depends on:** SEQ-1, PAR-4 (design_spec), PAR-5 (variant_metrics). **Touches:**
`creative_brief/ai_director.py`, `content_pack_visual/integration.py`,
`web/web.py` (the create-graphic route response). **Thesis ref:** §5.4–5.5.

**Implementation prompt:**
> [Preamble.] Implement Tier B (thesis §5.4–5.5), gated behind `MEDIAHUB_GEN_V2`.
> (1) Rewrite `ai_director.ai_creative_direction` to emit a **DesignSpec** (use
> `creative_brief/design_spec.py` from PAR-4) under JSON-schema-constrained decoding
> via `ai_core` — the LLM now chooses archetype, colour-role assignment, focal
> element, hero stat (from the ranker's emphasis list), generated hook, crop intent,
> accent, logo lockup, mood, and a `rationale` (which feeds the existing "why this
> design" explainability). Keep the SEQ-1 deterministic archetype-picker as the
> fallback floor when no provider is configured (honest error / real floor — never a
> fabricated card). (2) In `content_pack_visual/integration.py`, emit **N candidate
> specs** (default 5), render the pool (cheap — Playwright), run a **deterministic
> brand-compliance check** (APCA/ΔE2000 contrast, correct logo lockup for the
> background, sponsor-safe zones) that attaches an explainable score to each, score
> diversity with `quality/variant_metrics.py` (PAR-5), rank with the existing ranker,
> and return a **ranked shortlist**. (3) Extend the create-graphic route response in
> `web/web.py` to return the shortlist + per-candidate compliance score (additive
> JSON; keep the old single-visual fields populated from the top candidate so
> existing callers keep working). This stage *replaces* the menu-picker prompt — but
> the old `random_variation_profile`/enum path stays in place as the flag-off route
> until SEQ-3, so this is still additive at the route level. Add tests for spec
> emission (mock LLM), normalisation of a bad LLM response to a legal card, and the
> compliance score. Branch `claude/gen-seq-2-tier-b`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-2: with the flag on, the director emits a schema-valid
> DesignSpec; a deliberately malformed LLM response still yields a legal, legible
> card (PAR-4 normalisation); the pipeline returns a ranked shortlist of ≥4
> structurally distinct candidates each with a compliance score; the top candidate
> populates the legacy single-visual response fields (old callers unaffected); with
> no provider configured it falls back to the deterministic archetype floor (no
> fabricated output). Flag OFF = old behaviour. Suite green. Confirm no spine file
> outside the three named was touched.

#### SEQ-3 · Cutover + gated removal of the dead engine (the "full removal")
**Depends on:** SEQ-2 proven (A/B beats the old engine in review + suite green).
**Touches (removals):** `creative_brief/generator.py`,
`creative_brief/ai_director.py`. **Thesis ref:** §5.1, §7 cutover. **This is a
route/data-structure-adjacent removal — follow CLAUDE.md's gated process exactly.**

**Implementation prompt:**
> [Preamble.] Cut over to v2 and remove the dead variation engine — this is a
> deliberate replacement, so you MUST run CLAUDE.md's **15-step breakage check
> (Section A) before** touching anything, write the breakage list, then remove and
> run the **15-step verification (Section B) after**, then the **dead-code sweep
> (Section C)**. Steps: (1) flip `MEDIAHUB_GEN_V2` default to ON. (2) Remove the
> now-dead enum-permutation path: `random_variation_profile`, `_legacy_axes_from_seed`,
> `_PHRASE_TABLES`/`_phrase_for_seed`, and the closed-vocabulary menu-picker
> `_system_prompt` in `ai_director.py`; demote `BACKGROUND_STYLES`/`ACCENT_STYLES`/
> `TYPOGRAPHY_PAIRS`/`COMPOSITIONS`/`PHOTO_TREATMENTS` to renderer-internal building
> blocks only if still needed, else remove. (3) Keep the deterministic archetype
> floor. (4) Migrate or tolerate old persisted briefs/`variation_signature` fields
> (decide explicitly per breakage step 13). Do NOT remove the route or the
> `CreativeBrief` dataclass (extend, don't delete — production depends on them).
> Provide the completed A-list, B-list, and dead-code sweep in the PR description.
> Branch `claude/gen-seq-3-cutover`, run the full suite (no new failures, no
> weakened tests), PR.

**Verification prompt:**
> [Preamble.] Independently re-run CLAUDE.md Section B (15-step safe-removal
> verification) against SEQ-3: zero stray refs to the removed symbols (whole-repo
> grep); imports resolve; full suite green with no deleted/skipped/weakened tests;
> the create-graphic route + templates still work; old persisted runs still load (or
> are migrated); engine accuracy (PB detection, ranking) byte-identical; no new
> debug/IDOR exposure, no `ANTHROPIC_API_KEY` leak; diff contains only intended
> edits; dead-code sweep actually happened (no orphaned helpers, `_unused` vars, or
> "removed" placeholder comments). Report the checklist with pass/fail per step.

#### SEQ-4 · Video — data-driven scene structure (+ optional Tier C)
**Depends on:** SEQ-1/2 (the richer brief). **Touches:** `visual/motion.py`,
`remotion/src/compositions/`, optionally `visual/ai_background.py`. **Thesis ref:**
§5.7.

**Implementation prompt:**
> [Preamble.] Enrich video (thesis §5.7). (1) The richer brief (archetype, hero
> stat, tokens) already flows into `visual/motion.py` props — extend the Remotion
> compositions in `remotion/src/compositions/` to honour the archetype/emphasis so
> the reel's *look* matches the still. (2) Add **data-driven scene structure**: a
> multi-PB weekend produces a structurally different reel (variable
> `durationInFrames`/scene count derived from the number of ranked moments) than a
> single medal — the thing template tools can't do and Remotion can. (3) **Optional,
> behind its own flag** (`MEDIAHUB_GEN_BG`, default off): activate the dormant
> `visual/ai_background.py` hook (already imported at `render.py`) via a
> commercial-safe API (Bria/Recraft) for **backgrounds only**, composited under the
> deterministic text, with the existing contrast guardrails — never the data layer.
> Keep cache-by-content-hash behaviour. Add tests for variable scene count. Branch
> `claude/gen-seq-4-video`, test, PR.

**Verification prompt:**
> [Preamble.] Verify SEQ-4: reel scene count varies with the number of ranked
> moments; the reel look matches the still archetype; cache-by-hash still works;
> the optional generative-background path is OFF by default and, when on, only
> affects the background (data text stays deterministic and legible). Suite green.

---

### 4. Dependency graph & sequencing

```
RUN NOW, CONCURRENTLY (each its own session → PR to main, any merge order):
  PAR-1 captions      PAR-2 autofit     PAR-3 saliency    PAR-4 design-spec
  PAR-5 metrics       PAR-6 bootstrap   PAR-7 archetypes×N PAR-8 docs
        (all additive/inert or single-surface — no shared-file conflicts)
                              │
                              ▼
THEN, IN ORDER (each its own PR; gated by MEDIAHUB_GEN_V2):
  SEQ-0 tokens ─▶ SEQ-1 Tier A ─▶ SEQ-2 Tier B ─▶ SEQ-3 cutover+removal ─▶ SEQ-4 video
  (SEQ-0 also coordinates with ROADMAP §1.6 Stage G if not yet merged)
```

**Wiring map (which spine stage consumes which parallel module):**

| Parallel module | Wired in by | Until then it is |
|---|---|---|
| PAR-2 autofit, PAR-3 saliency, PAR-7 archetypes | SEQ-1 | inert new files |
| PAR-4 design-spec, PAR-5 metrics | SEQ-2 | inert new files |
| PAR-6 brand bootstrap | SEQ-0 onboarding (or later) | inert new file |
| PAR-1 captions | already live (own surface) | shipped independently |
| PAR-8 docs | n/a | docs |

**The fastest path to fixing "samey":** PAR-2 + PAR-3 + PAR-7 (in parallel now) →
SEQ-0 → SEQ-1. That delivers Tier A — deterministic, brand-safe, ~$0 marginal cost
— which the thesis expects to resolve the complaint on its own, before any
LLM-director work (SEQ-2).

---

### 5. Acceptance criteria (from thesis §8C)

The overhaul is "done" when, with `MEDIAHUB_GEN_V2` on:

1. **Structural distinctiveness:** a 10-card pack uses ≥6 distinct archetypes; a
   5-candidate pool for one card spans ≥4 archetypes (today ~1–2). Measured by
   `quality/variant_metrics.py` (PAR-5).
2. **On-brand fidelity:** the deterministic compliance check passes ≥99% of shipped
   candidates; off-brand candidates are caught before a human sees them.
3. **Caption non-repetition:** consecutive captions for a card are below the overlap
   threshold; zero ban-list phrases ship.
4. **Human-acceptance rate** (approved without manual redesign) rises vs the old
   engine in the review-UI A/B.
5. **Cost & latency:** marginal API cost/pack < ~$0.50 (Tier A+B); cold render
   within today's 30–90s; cache-hit behaviour preserved.
6. **No moat regression:** rendered data accuracy stays 100% (deterministic), and
   every card keeps its "why this card / why this design" explanation.
7. **Suite green** throughout (no new failures, no weakened tests), and SEQ-3's
   gated-removal checklists are completed and recorded.

---

*Derived from `docs/research/mediahub-generative-ai-thesis.md` and
`docs/research/generation-engine-competitor-evaluation.md`, against `main` after
PR #137. Run the Parallel Bucket (§2) now in separate sessions; then walk the
Sequential Spine (§3) in order.*



---

## Appendix B — Growth & Expansion: Build Prompts (not yet done)

> *Runnable implementation + verification prompts for the Phase 2/3 growth work (commercial, sport expansion, athlete surfaces, integrations, enterprise, agentic editing, marketplace, sponsor-side). The earlier steps (brand DNA, voice imitation, visible intelligence, output expansion, turn-into, publishing) are already shipped and are intentionally omitted. Step/Phase numbers below are local to this appendix.*

#### Step 7: Commercial Layer — Stripe, Tiers, Self-Serve Signup

##### Context
MediaHub has no commercial layer today. The plan is to ship public pricing, self-serve signup, and a free tier alongside Phase 1's product improvements so commercial pressure surfaces during iteration.

##### Implementation Prompt

```
Add a commercial layer: signup, Stripe billing, three tiers.

GOAL: a new user can land on /, click "Get started", create an account
with email + password, choose a plan (Free / Club £30/mo / Federation
£250/mo), pay via Stripe Checkout, and start using MediaHub on the
hosted service.

FILES TO MODIFY:
- NEW src/mediahub/web/auth.py: minimal email+password auth (use
  passlib bcrypt; sessions via Flask's session cookie with a
  signed secret).
- NEW src/mediahub/web/billing.py: Stripe Checkout session creation,
  webhook handler for subscription events.
- src/mediahub/web/web.py:
  - new GET/POST /signup, /login, /logout
  - new GET /pricing (3-tier table)
  - new GET /billing (current plan, manage subscription via Stripe
    Customer Portal)
  - new POST /webhooks/stripe (verify signature, update subscription
    status)
  - guard premium features (multi-club, enterprise tools — to be
    added in Phase 3) behind a plan check; existing features remain
    open on Free.
- DB: extend the existing DATA_DIR storage with a users.jsonl ledger
  (email, hashed_password, plan, stripe_customer_id, created_at).
  Do not introduce SQLAlchemy.
- environment: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION.
- Free tier limits: 3 runs/month, single brand profile, no Buffer
  scheduling. Soft limit (a banner) — never lock the user out
  permanently on free.

ACCEPTANCE CRITERIA:
- /signup creates a user, hashes the password, logs them in.
- /pricing shows the three tiers with feature lists.
- "Upgrade" buttons start a Stripe Checkout flow (use Stripe test
  mode keys for dev).
- A successful Stripe Checkout webhook updates the user's plan.
- /billing lets the user manage their subscription via Stripe Customer
  Portal.
- Self-hosted deployments (no STRIPE_SECRET_KEY env) continue to
  work — auth is optional, billing routes return 503 with a clear
  "billing is not configured for this deployment" message.

DON'T BREAK:
- Any existing route that was open is still open if no STRIPE_*
  env vars are configured.
- pytest at 253+.
- The Stop hook git push flow continues to work.

TESTS:
- tests/test_auth.py: signup, login, logout, password hashing.
- tests/test_billing.py (mocked Stripe): webhook verification,
  subscription update flow.

```

##### Verification Prompt

```
Verify Step 7 (Commercial layer) end-to-end.

1. Tests: full pytest + tests/test_auth.py + tests/test_billing.py -v.

2. Self-hosted-without-billing path:
   - With STRIPE_SECRET_KEY unset, boot the app.
   - GET /, /add-input, /upload, /organisation, /settings — all 200.
   - GET /pricing and /billing — 200 (show "billing not configured").
   - All caption / motion / Turn-Into routes work as before.

3. Signup / login flow:
   - POST /signup with a fresh email + 12-char password. Confirm
     redirect to /add-input + a session cookie.
   - Log out. Log back in. Confirm session restored.
   - Submit a wrong password. Confirm a clear error, not a 500.
   - Confirm passwords in users.jsonl are bcrypt hashes (not plain).

4. Stripe-mode (test keys):
   - Set STRIPE_SECRET_KEY, STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION
     to Stripe test values.
   - Hit /pricing. Click "Upgrade to Club".
   - Confirm a Stripe Checkout session URL is returned and the test
     mode page renders (open in browser, fill 4242 4242 4242 4242).
   - Complete checkout. Confirm the webhook handler updates the
     user's plan in users.jsonl to "club".

5. Free tier soft limit:
   - On a Free account, create 3 runs. Create a 4th. Confirm a banner
     appears (NOT a hard lock).

6. Buffer scheduling guarded:
   - On Free, the Schedule button must show "Upgrade to schedule
     posts" instead of opening the modal.

7. Security checks:
   - Try to access /billing without a session. Confirm redirect to
     /login.
   - Inspect the session cookie — must be HttpOnly + Secure (when
     served via HTTPS) and signed.
   - Grep the codebase for STRIPE_SECRET_KEY — must only appear in
     billing.py and never logged.

8. Regression sweep: all features from Steps 1-6 still work.

OUTPUT: single report.
```

---

### Phase 2 — Distinction (Steps 8-12, target months 3-9)

#### Step 8: Sport Expansion — Athletics (Track and Field)

##### Context
MediaHub today is swimming-only. Athletics is the natural second sport — overlapping audience (school athletic programmes, multi-sport clubs), similar result-file structure (event, time/distance, place), but a different event vocabulary and a different PB taxonomy.

##### Implementation Prompt

```
Add athletics (track and field) as MediaHub's second sport.

GOAL: a user can upload an athletics result file (CSV or Hytek-format
.txt) on /upload, MediaHub recognises athletes, computes PBs, ranks
achievements, and produces a content pack with athletics-appropriate
language.

FILES TO MODIFY:
- NEW src/mediahub/sports/: refactor the sport-specific bits of the
  existing pipeline out of swimming-implicit code paths. Each sport
  should have:
    sports/<sport>/events.py — canonical event vocabulary
    sports/<sport>/parser.py — result-file parsers
    sports/<sport>/pb_logic.py — PB and record detection
    sports/<sport>/templates.py — celebratory phrase patterns
- src/mediahub/sports/__init__.py: register a SPORTS dict and a
  pick_sport(file_bytes, hint) -> SportModule selector.
- src/mediahub/sports/swimming/: move existing swimming code here
  (preserve all behaviour and tests).
- src/mediahub/sports/athletics/: new athletics implementation.
  Event vocabulary: 100m, 200m, 400m, 800m, 1500m, 3000m, 5000m,
  10000m, hurdles (60m/100m/110m/400m), steeplechase, all field
  events (LJ, TJ, HJ, PV, SP, DT, HT, JT), relays. Distinguish
  TRACK (time-based) from FIELD (distance/height-based) for PB
  comparison logic.
- src/mediahub/web/web.py /upload: detect sport from filename and
  content; allow user to override via a sport dropdown.
- ClubProfile: add primary_sport field; default to "swimming" for
  backward compatibility.

ACCEPTANCE CRITERIA:
- Uploading an athletics result file produces an athletics-specific
  content pack with phrases like "smashed a PB" appropriate to track
  ("ran a personal best") and field ("threw a personal best").
- A field PB is correctly detected (higher = better) vs track PB
  (lower = better).
- All swimming tests still pass — no regression.
- Adding a third sport in future is a matter of creating a new
  sports/<sport>/ subpackage, no refactoring of the platform code.

DON'T BREAK:
- Every existing swimming test (interpreter, recognition, corpus,
  visual, caption) still passes.
- pytest at 253+ (new athletics tests added).
- All Phase 1 features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion, Buffer publishing) work for athletics output.

TESTS:
- tests/test_athletics_parser.py: parse a sample athletics CSV,
  verify event detection.
- tests/test_athletics_pb_logic.py: field PB (higher = better) and
  track PB (lower = better) are correctly classified.
- tests/test_sports_registry.py: pick_sport routes correctly.

```

##### Verification Prompt

```
Verify Step 8 (Athletics support) end-to-end with no swimming regression.

1. Tests:
   - python -m pytest tests/ -q. Must be 253+ plus the new athletics
     tests (target 260+).
   - python -m pytest tests/test_athletics_*.py
     tests/test_sports_registry.py -v.

2. Swimming regression:
   - Upload an existing swimming sample file. Confirm the content pack
     is identical in structure to pre-Step-8 behaviour.
   - All four caption tones generate; visible intelligence shows PB
     reasoning; Turn-Into produces 6-7 artefacts; motion renders.
   - tests/test_interpreter_smoke.py, tests/test_pb_discovery.py,
     tests/test_corpus_recovery.py — all pass.

3. Athletics happy path:
   - Upload a sample athletics CSV. Confirm sport detection routes
     to athletics.
   - Confirm event names include 100m, 800m, LJ, TJ, etc.
   - Confirm PB logic: a long jump of 6.45m beats a previous 6.30m
     (higher = better); a 100m time of 11.40 beats 11.50 (lower = better).
   - Confirm captions use athletics-appropriate language ("ran a
     PB in the 800m" not "swam a PB").

4. Sport switching:
   - Manually override sport from swimming → athletics on the /upload
     page. Confirm the override takes effect.

5. Module structure:
   - ls src/mediahub/sports/ — confirms swimming/ and athletics/
     subpackages.
   - python -c "from mediahub.sports import SPORTS, pick_sport;
     print(list(SPORTS.keys()))"
     — confirms both sports registered.

6. Regression sweep on Phase 1:
   - All 7 Phase 1 steps' features still work (sample one feature
     from each).

OUTPUT: single report.
```

---

#### Step 9: Athlete-Facing Micro-Surfaces

##### Context
Greenfly routes content from a league to athletes for personal sharing. For MediaHub the parallel is letting a swimmer/athlete receive their own personal share-ready cards via a private link, which they post to their own channels. This expands distribution beyond the club account.

##### Implementation Prompt

```
Add athlete-facing micro-surfaces for personal sharing.

GOAL: each swimmer/athlete in a run can be given a personal,
unlisted link to a page that shows their cards for that meet plus
their season-to-date highlights, with a "Share to Instagram" / "Save
to camera roll" affordance per card. No login required for the
swimmer.

FILES TO MODIFY:
- src/mediahub/athlete_pages/: new module.
- Token: per-athlete unlisted token = HMAC(server_secret, run_id +
  athlete_id), 24 chars base32. Stored in run JSON.
- src/mediahub/web/web.py:
  - new GET /a/<token> — renders the athlete page. No auth required.
  - new GET /a/<token>/card/<card_id>/share — returns the card as a
    direct-download image for the athlete to save and post.
  - new POST /api/runs/<run_id>/athlete-tokens — admin route on the
    review page: generate or revoke tokens for athletes in the run.
- Review page: "Send to athlete" button on each card; clicking copies
  the personal share link (or opens a QR code modal for in-person
  hand-off).
- Privacy: the athlete page MUST NOT show any other swimmer's data,
  the original results file, or any club admin surface.

ACCEPTANCE CRITERIA:
- An athlete with a token can see only their own cards.
- The link is unguessable (HMAC + secret rotation).
- An admin can revoke a token; revoked tokens render a "this link has
  been revoked" page.
- Share affordances work on mobile: tapping "Save to camera roll" on
  iOS Safari triggers a long-press save flow; on Android, a direct
  download.
- Page renders correctly on screens 320px wide (smallest common mobile).

DON'T BREAK:
- All earlier features still work.
- Privacy: no PII leakage from athlete page to the rest of the
  system. Specifically: an athlete cannot enumerate other tokens.

TESTS:
- tests/test_athlete_pages.py: token generation determinism, HMAC
  verification, revoked-token handling, isolation between athletes.

```

##### Verification Prompt

```
Verify Step 9 (Athlete pages) end-to-end.

1. Tests: full pytest + tests/test_athlete_pages.py -v.

2. Happy path:
   - On an existing run, generate a token for athlete A and athlete B.
   - GET /a/<token_A> — confirm 200, shows only A's cards.
   - GET /a/<token_B> — confirm 200, shows only B's cards.
   - Try GET /a/<token_A> with one character changed — confirm 404,
     NOT a leak of the original page.

3. Isolation:
   - On A's page, the response body must NOT contain B's swimmer_name.
   - The page must NOT contain the path to the results file.

4. Revocation:
   - Revoke A's token. Re-fetch /a/<token_A> — confirm a clear
     "revoked" page, status 410 or 200 with a message.

5. Mobile rendering:
   - Open /a/<token_A> in a 360x800 viewport. Screenshot.
   - Confirm cards fit, text is readable, the share buttons are
     thumb-sized (≥44px).

6. Share affordance:
   - GET /a/<token>/card/<card_id>/share — must return an image with
     Content-Disposition: attachment.

7. Regression sweep: all Phase 1 + Step 8 features still work.

OUTPUT: single report.
```

---

#### Step 10: Sponsor-Aware Generation

##### Context
Sponsors are a primary revenue driver for clubs and the buyer's biggest stakeholder. A sponsor-aware product variant of every output type — caption with sponsor mention, graphic with sponsor logo, newsletter section with sponsor block — turns MediaHub into a sponsorship-value-realisation tool.

##### Implementation Prompt

```
Make every output type sponsor-aware.

GOAL: when ClubProfile has sponsor_name + sponsor_guidelines set,
every generated caption, graphic, motion, reel, and Turn-Into
artefact has an opt-in sponsor variant. The sponsor variant must
respect the guidelines (e.g. "always include #BrandNameSwim";
"never combine our logo with a competitor's").

FILES TO MODIFY:
- ClubProfile: extend with sponsor_logo_path,
  sponsor_brand_colour (hex), sponsor_required_hashtags (list),
  sponsor_forbidden_phrases (list), sponsor_activation_rate
  (e.g. "every 3rd post"), sponsor_position_preference
  (top|bottom|watermark).
- src/mediahub/sponsor/: new module:
    apply_sponsor_to_caption(caption: str, profile: ClubProfile,
                              activation: bool) -> str
    apply_sponsor_to_graphic(graphic_brief: dict,
                              profile: ClubProfile) -> dict
- Generators (caption, graphic, motion, Turn-Into) call the sponsor
  apply functions when activation=True. Activation is determined by
  the sponsor_activation_rate or explicit user toggle per card.
- review page: a "Sponsor mode" toggle on each card; the entire
  content pack also has a global toggle.
- Compliance: a "Sponsor compliance check" panel lists each generated
  artefact and confirms it satisfies all guidelines or flags
  violations.

ACCEPTANCE CRITERIA:
- With sponsor configured, the sponsor toggle on a card produces a
  sponsor variant that:
  - Includes any required hashtags.
  - Avoids any forbidden phrases.
  - Displays the sponsor logo in the configured position.
  - Uses the sponsor brand colour as a tasteful accent (without
    overriding the club's primary palette).
- The compliance panel surfaces any violation clearly.
- Without a sponsor configured, the toggle is hidden, not greyed out.

DON'T BREAK:
- All earlier features still work.
- pytest at 260+ (athletics tests added in Step 8).

TESTS:
- tests/test_sponsor_pipeline.py: required-hashtag enforcement,
  forbidden-phrase blocking, logo positioning.

output expansion).
```

##### Verification Prompt

```
Verify Step 10 (Sponsor mode) end-to-end.

1. Tests: full pytest + tests/test_sponsor_pipeline.py -v.

2. Configuration round-trip:
   - Set sponsor_name + sponsor_required_hashtags ["#TestSponsor"]
     + sponsor_forbidden_phrases ["beat the competition"].
   - Save, reload /organisation. Confirm the fields persist.

3. Sponsor caption check:
   - Toggle "Sponsor mode" on one card.
   - Confirm the caption now contains "#TestSponsor".
   - Force the LLM (or heuristic) to produce text containing "beat the
     competition" via a test fixture, run the apply function, and
     confirm the phrase is removed or rewritten.

4. Sponsor graphic check:
   - Toggle sponsor mode, regenerate the graphic.
   - Open the image; confirm the sponsor logo appears in the
     configured position.
   - Confirm the sponsor colour appears as an accent (not as
     the primary background).

5. Compliance panel:
   - Configure a deliberate violation (a required hashtag NOT present
     in the caption). Confirm the compliance panel flags it visibly.

6. Sponsor absent:
   - Clear sponsor_name. Confirm the sponsor toggle is hidden, not
     present in the DOM.

7. Regression sweep: all Phase 1 and Steps 8-9 features still work.

OUTPUT: single report.
```

---

#### Step 11: Multi-Sport Architecture Cleanup + Football/Rugby

##### Context
With athletics shipped in Step 8 the sports/ package exists. Adding football and rugby validates that the architecture genuinely scales and unlocks the largest UK market segment (school and university football/rugby).

##### Implementation Prompt

```
Add football and rugby as sports 3 and 4; clean up the sports/
architecture as needed.

GOAL: a user can upload a football match report (CSV / structured
text / one-pager PDF) and get a content pack appropriate to football
(goal scorers, clean sheets, man-of-the-match, league position,
fixture preview). Same for rugby (tries, conversions, line-out
stats, set-piece dominance, man-of-the-match).

FILES TO MODIFY:
- src/mediahub/sports/football/: events.py (match events: goals,
  assists, yellow/red cards, subs), parser.py (parse common
  match-report formats including OPTA-style CSV if available),
  achievement_logic.py (goal-of-the-match, hat-trick detection,
  clean-sheet recognition), templates.py.
- src/mediahub/sports/rugby/: similar structure for rugby union
  (tries, conversions, penalties, man-of-the-match, line-out wins).
- Generalise the existing pb_logic.py — for team sports it's
  achievement_logic.py with different primitives. Refactor the
  swimming/athletics modules to use a common interface
  (sports/<sport>/achievement_logic.py) where appropriate.
- /upload: detect sport from file content + filename.
- /organisation: add a "Sports" multi-select so a club can declare
  it covers multiple sports.

ACCEPTANCE CRITERIA:
- A hat-trick is correctly detected and surfaced as the headline
  achievement in football.
- A clean sheet is correctly attributed to the goalkeeper.
- Rugby man-of-the-match selection prefers tries > conversions >
  metres made if not explicitly named in the input.
- A clean league position (1st in the table) is detected as a
  high-priority achievement.
- All previous sports tests (swimming + athletics) still pass.

DON'T BREAK:
- pytest at the new baseline (target 280+).
- Phase 1 features remain functional on football/rugby output.

TESTS:
- tests/test_football_*.py and tests/test_rugby_*.py covering parsing,
  achievement detection, and caption generation.

```

##### Verification Prompt

```
Verify Step 11 (Football + Rugby) end-to-end.

1. Tests: full pytest. Target 280+ passed.
   - python -m pytest tests/test_football_*.py tests/test_rugby_*.py -v.

2. Hat-trick detection:
   - Upload a football match where player X scored 3 goals.
   - Confirm the top-ranked card mentions a hat-trick.
   - Confirm the visible-intelligence reasoning includes goal count.

3. Clean sheet attribution:
   - Upload a 2-0 win match. Confirm the goalkeeper's card mentions
     "clean sheet".

4. Rugby try detection:
   - Upload a rugby match with 4 tries by player Y. Confirm Y is the
     headline and the caption uses rugby-appropriate language.

5. Multi-sport club:
   - Set a club's sports to ["swimming","football"]. Upload swimming.
     Confirm swimming pipeline. Upload football. Confirm football
     pipeline.

6. Cross-sport caption consistency:
   - Same voice_profile applied to a football caption and a swimming
     caption — the stylistic signature (sentence length, hashtag
     count) should match across both.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 12: Native Publishing APIs (Replace Buffer Dependency)

##### Context
Step 6 shipped Buffer integration to close the publishing gap fast. This step builds direct integrations to Instagram Graph API, Facebook Pages, X (v2), LinkedIn Marketing, and TikTok Business so MediaHub no longer depends on Buffer for the core publishing path.

##### Implementation Prompt

```
Replace Buffer dependency with native publishing APIs.

GOAL: a user can connect Instagram Business, Facebook Pages, X,
LinkedIn (Company Page), and TikTok Business directly. Scheduling
no longer requires a Buffer account.

FILES TO MODIFY:
- src/mediahub/publishing/instagram.py: Graph API; OAuth via
  Facebook Login. Single-image + reels upload + caption.
- src/mediahub/publishing/facebook.py: Pages API; OAuth via
  Facebook Login.
- src/mediahub/publishing/x_twitter.py: v2 API; OAuth 2.0 with PKCE.
- src/mediahub/publishing/linkedin.py: Marketing Developer Platform;
  OAuth 2.0.
- src/mediahub/publishing/tiktok.py: TikTok Business API; OAuth 2.0.
- src/mediahub/publishing/scheduler.py: a unified Scheduler interface
  (queue, schedule_at, dispatch_now) so the UI calls one API
  regardless of platform.
- A background worker (lightweight — Flask-APScheduler or a simple
  cron-style polling thread) that dispatches scheduled posts at
  their scheduled_at time.
- /settings: native "Connect Instagram", "Connect Facebook" etc.
  buttons (in addition to the existing Buffer field, which remains
  as a fallback).

ACCEPTANCE CRITERIA:
- A user can complete the OAuth flow for each platform and the
  resulting access tokens are stored encrypted (Fernet) in
  DATA_DIR / "secrets" / <user_id>.json.
- Scheduling a post via the UI dispatches to the right platform at
  the right time.
- Token refresh is handled before each dispatch.
- Buffer remains available as a fallback channel; users can choose
  per-card whether to dispatch direct or via Buffer.

DON'T BREAK:
- pytest at the new baseline (target 290+ with publishing tests).
- All earlier features still work.

TESTS:
- tests/test_native_publishing.py: mocked OAuth + dispatch, token
  refresh, dispatcher worker.

landscape closing), §6 Workstream 3.x.
```

##### Verification Prompt

```
Verify Step 12 (Native publishing) end-to-end.

1. Tests: full pytest + tests/test_native_publishing.py -v.

2. OAuth flows (mocked):
   - For each of the 5 platforms, simulate the OAuth callback with a
     fixed test token. Confirm the token is stored encrypted (not
     plaintext) in the per-user secrets file.

3. Dispatch (mocked):
   - Schedule a post with scheduled_at = now + 30s.
   - Wait 45s. Confirm the post was dispatched via the mocked API.
   - Confirm the workflow state shows schedule_status=published.

4. Token refresh:
   - Set an expired-token scenario. Confirm the dispatcher refreshes
     the token before dispatching, or surfaces a clear "re-connect"
     error if refresh fails.

5. Buffer fallback:
   - Confirm Buffer is still selectable per-card and the Buffer
     dispatch path still works.

6. Security:
   - grep the codebase for any access_token logging — must be zero.
   - Confirm the encrypted secrets file mode is 0600.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Phase 3 — Leadership (Steps 13-17, target months 9-18)

#### Step 13: Integration Moat — Hy-Tek, TeamUnify, ClubBuzz Importers

##### Context
The single most defensible distribution moat against horizontal entrants is direct integration with the software clubs already use. Hy-Tek MeetManager (results), TeamUnify (club management), ClubBuzz (UK clubs), SwimManager — each integration is one to three engineering weeks and creates a switching cost.

##### Implementation Prompt

```
Build first-class importers for the most-used club software.

GOAL: a user with a TeamUnify or ClubBuzz account can connect MediaHub
once, and every new meet result automatically flows into MediaHub
without a manual upload.

FILES TO MODIFY:
- src/mediahub/integrations/teamunify.py: OAuth or API key auth,
  poll for new meet results, ingest as a new run, run the full
  pipeline.
- src/mediahub/integrations/clubbuzz.py: same pattern.
- src/mediahub/integrations/hytek_meetmanager.py: file-format
  importer for the .hy3 format with deeper coverage than the existing
  parser (handle all common event codes, age groups, time conversions).
- src/mediahub/integrations/splash_meet_manager.py: file-format
  importer for Splash's export format.
- /settings: new "Integrations" section with one-click connect
  buttons.
- A background polling worker for the API-based integrations.

ACCEPTANCE CRITERIA:
- A connected TeamUnify account auto-ingests new meets within 1 hour
  of them appearing in TeamUnify.
- Hytek and Splash file imports produce identical content packs to
  manual uploads.
- A revoked integration cleanly stops polling and surfaces in the UI.

DON'T BREAK:
- Manual file upload still works.
- pytest at the new baseline (target 300+).

TESTS:
- tests/test_integrations_*.py: mocked API responses, end-to-end
  ingestion.

```

##### Verification Prompt

```
Verify Step 13 (Integrations) end-to-end.

1. Tests: full pytest + tests/test_integrations_*.py -v.

2. TeamUnify mocked happy path:
   - Connect with a test API key.
   - Push a fake new-meet event via the mock server.
   - Confirm a new run appears in MediaHub within the polling interval.
   - Confirm the run produces a valid content pack.

3. Hytek parity:
   - Take an existing .hy3 file that worked with the manual uploader.
   - Run it through the new importer. Confirm the resulting content
     pack is identical (same number of achievements, same ranking).

4. Splash importer:
   - Process a sample Splash file. Confirm event detection + PB
     attribution.

5. Disconnection:
   - Revoke the test API key. Confirm polling stops within 1 polling
     cycle and the /settings page shows "Disconnected".

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 14: Enterprise Tier — Multi-Club Orchestration

##### Context
The financial backbone of the strategy. Governing bodies, leagues, federations, and large university athletic departments need multi-club orchestration: branded league templates, federation-wide engagement analytics, sponsorship reporting across clubs.

##### Implementation Prompt

```
Ship the enterprise tier: multi-club orchestration.

GOAL: a Federation user (Stripe enterprise plan from Step 7) can
manage up to 50 clubs from one account, push league-branded templates
to all clubs, view aggregated engagement analytics, and produce
sponsorship reports.

FILES TO MODIFY:
- Data model: introduce Organisation (governing body / league) →
  Club → Run hierarchy. Backward-compatible: a club without an
  organisation is treated as a standalone (today's default).
- src/mediahub/enterprise/: new module:
    OrganisationProfile dataclass
    league_templates.py — manage and distribute templates
    aggregated_analytics.py — engagement metrics across child clubs
    sponsorship_report.py — sponsor-exposure metrics with citations
- new pages:
  /federation — dashboard
  /federation/clubs — manage child clubs
  /federation/templates — push templates
  /federation/analytics — aggregated metrics
  /federation/sponsorship — sponsor reports
- billing: Stripe plan "federation" unlocks these pages.

ACCEPTANCE CRITERIA:
- A federation user can add a child club and the child club's owner
  receives an invite link to accept the relationship.
- Pushing a template to all child clubs makes the template available
  in each club's Turn-Into picker.
- Aggregated analytics correctly sum engagement across all child
  clubs and never double-count.
- A sponsorship report can be exported as a branded PDF.

DON'T BREAK:
- Standalone clubs (no parent organisation) work exactly as before.
- pytest at the new baseline (target 310+).

TESTS:
- tests/test_enterprise_*.py covering hierarchy, template push,
  analytics aggregation, sponsorship report generation.

scale).
```

##### Verification Prompt

```
Verify Step 14 (Enterprise tier) end-to-end.

1. Tests: full pytest + tests/test_enterprise_*.py -v.

2. Hierarchy:
   - Create a federation account and three child clubs.
   - Confirm the federation dashboard shows all three.
   - Sign in as one child club — confirm it can see only its own runs.

3. Template push:
   - Federation pushes a "Meet Recap League Template".
   - Each child club's Turn-Into picker now includes it.

4. Analytics:
   - Federation analytics page sums engagement across the three clubs.
   - Manually verify the sum equals the per-club totals.

5. Sponsorship report:
   - Generate a sponsorship PDF for the federation's headline sponsor.
   - Confirm the PDF includes per-club sponsor activations with
     citations (which post, which date, which platform).

6. Plan guard:
   - On a non-federation plan, the federation pages return a clear
     upgrade prompt, not a 404.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 15: Conversational / Agentic Caption Editing

##### Context
Lately's Kately and Holo's chat-editor demonstrate the next interaction primitive: a conversational layer over the existing content pack. "Make this caption more energetic", "Add a thank-you to the parents", "Generate a TikTok script from this meet" — the user issues natural-language instructions and the agent operates over the existing assets.

##### Implementation Prompt

```
Add a conversational editing surface to the content pack.

GOAL: every card on the review page has a chat panel where the user
can issue natural-language edit commands ("shorter", "more energetic",
"in Spanish", "add a sponsor mention", "generate a TikTok variant").
The agent uses the existing tools (generate_caption_for_tone,
sponsor.apply, motion.render_story_card) rather than free-form
generation.

FILES TO MODIFY:
- src/mediahub/agent/__init__.py
- src/mediahub/agent/tools.py: register the tools the agent can call
  (regenerate_caption, change_tone, translate_caption, add_sponsor,
  generate_motion, generate_reel_variant).
- src/mediahub/agent/runner.py: a small tool-use loop using the
  existing LLM (Gemini or Anthropic) with structured tool calling.
- /review page: a chat panel toggle next to each card.
- Every agent action writes an audit entry (who, when, what tool,
  what arguments, what result) to DATA_DIR/agent_audit/<run_id>.jsonl.

ACCEPTANCE CRITERIA:
- "Make this shorter" produces a caption ≤80% of the original length.
- "Make this in Spanish" produces Spanish output.
- "Add a sponsor mention" calls the sponsor.apply tool and produces
  a sponsor variant.
- The agent NEVER publishes — every change is staged and requires
  the user's Save click.

DON'T BREAK:
- pytest at the new baseline (target 320+).
- All earlier features still work.

TESTS:
- tests/test_agent_*.py: tool invocation, no-publish guarantee,
  audit log integrity.

§6 Workstream 3.3.
```

##### Verification Prompt

```
Verify Step 15 (Agentic editing) end-to-end.

1. Tests: full pytest + tests/test_agent_*.py -v.

2. Edit commands:
   - "shorter" → length reduction confirmed.
   - "more energetic" → tone shift confirmed (compare against baseline).
   - "in Spanish" → output is Spanish (langdetect).
   - "add a sponsor mention" → sponsor hashtag present.

3. No-publish guarantee:
   - Issue 10 agent commands. Confirm NONE of them dispatched a
     publish action. The audit log should show zero publishing tool
     calls.

4. Audit:
   - For each agent action, confirm DATA_DIR/agent_audit/<run_id>.jsonl
     has a corresponding entry with full arguments and result.

5. Tool safety:
   - Try to inject "delete this run" via the chat input. Confirm the
     agent does not call any destructive tool (no such tool exists in
     the registry).

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 16: Template Marketplace

##### Context
Community templates raise switching cost. Once a club has invested in templates that exist only on MediaHub — branded recap layouts, voice profiles, season-narrative arcs — leaving the platform costs them their accumulated content infrastructure.

##### Implementation Prompt

```
Ship a community template marketplace.

GOAL: clubs and federations can publish templates (visual layouts,
voice profiles, Turn-Into recipes, sponsor activation patterns) for
other clubs to fork. Templates are versioned and reviewable.

FILES TO MODIFY:
- src/mediahub/marketplace/: new module.
- Template types: visual_layout (graphic + motion templates),
  voice_profile_template (anonymised voice patterns),
  turn_into_recipe (which 7 artefacts a Turn-Into produces and how),
  sponsor_activation (predefined sponsor variants for common partners).
- /marketplace page: browse, preview, fork.
- /marketplace/submit: submit a template (with review queue).
- /marketplace/admin: review/approve/reject submissions (federation
  + MediaHub admin role).

ACCEPTANCE CRITERIA:
- A submitted template enters a review queue.
- Forking a template clones it into the user's own club profile —
  edits to the fork do not affect the source.
- Templates are versioned; the user can upgrade their fork to a newer
  source version.
- Marketplace search by sport, audience size, language.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_marketplace_*.py covering submission, fork, version
  upgrade, isolation between fork and source.

```

##### Verification Prompt

```
Verify Step 16 (Template marketplace) end-to-end.

1. Tests: full pytest + tests/test_marketplace_*.py -v.

2. Submit + approve:
   - As a club user, submit a visual_layout template.
   - As an admin, approve it.
   - The template now shows in /marketplace.

3. Fork:
   - As another club, fork the template. Confirm the fork lives in
     the new club's profile.
   - Edit the fork. Confirm the source is unchanged.

4. Version upgrade:
   - As the source owner, publish version 2.
   - The fork shows an "upgrade available" badge. Confirm the upgrade
     applies cleanly.

5. Search:
   - Search by sport=athletics. Confirm only athletics templates
     appear.

6. Privacy:
   - Confirm voice_profile_template templates are anonymised (no
     PII / no club name leaked) before they enter the public
     marketplace.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

#### Step 17: Sponsor-Side Analytics Product

##### Context
The final defensible primitive: a sponsor-facing product that proves to the sponsor the value of their brand exposure across a club's content. Nota and FanWord do not do this at small-club scale; this is a category MediaHub can own.

##### Implementation Prompt

```
Build a sponsor-side product surface.

GOAL: a sponsor (the brand paying the club) can log in and see a
dashboard of all the times their brand appeared in content produced
by clubs they sponsor, with engagement metrics and an estimated
brand-exposure value.

FILES TO MODIFY:
- New user role: sponsor. Sponsor accounts are linked to specific
  club profiles via an invitation flow.
- src/mediahub/sponsor_dashboard/: new module.
- /sponsor — sponsor dashboard.
- /sponsor/exposure — list of every post where this sponsor's brand
  appeared, with date, platform, engagement, and a thumbnail of
  the asset.
- /sponsor/value — estimated brand-exposure value (impressions ×
  CPM-equivalent based on the platform).
- /sponsor/export — branded PDF report.

ACCEPTANCE CRITERIA:
- A sponsor can only see content produced by clubs they sponsor.
- Engagement metrics are pulled from the publishing layer's
  post-success records (Step 12).
- The brand-exposure value calculation is documented and auditable
  (open the value calculation in a tooltip).
- The PDF export is reproducible and includes citations to every
  source post.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_sponsor_dashboard_*.py: scoping (sponsor sees only their
  clubs), metric calculation determinism, PDF export shape.

```

##### Verification Prompt

```
Verify Step 17 (Sponsor-side product) end-to-end.

1. Tests: full pytest + tests/test_sponsor_dashboard_*.py -v.

2. Scoping:
   - Sponsor A is linked to Club 1 and Club 2 (not Club 3).
   - Sponsor A's exposure page shows posts from Club 1 and 2 only.
   - Confirm Club 3's posts do NOT appear in any sponsor query.

3. Metric calculation:
   - For a post with known engagement, manually compute the value
     using the documented formula. Confirm the dashboard matches.

4. PDF export:
   - Export a sponsor report. Confirm it opens, contains citations,
     and is reproducible (re-export, byte-equality of the content
     section).

5. Sponsor cannot leak admin:
   - As a sponsor, attempt to access /federation, /admin,
     /api/runs/<id>/turn-into. All must return 403.

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

### Final Audit — After Step 17 (or any time after Step 7)

##### Context
At any milestone the full product should be audited end-to-end. This audit is the prompt to run after a major release.

##### Audit Prompt

```
Conduct a full MediaHub product audit.

OBJECTIVE: confirm that every feature shipped to date — every step
in the roadmap that has been completed — still works end-to-end with
no regressions, and that the product as a whole holds up against the
quality bar set by the competitors documented in
docs/research/generation-engine-competitor-evaluation.md.

PHASE A — Automated tests:
1. python -m pytest tests/ -q. Report pass/skip/fail counts.
2. python -c "from mediahub.web.web import create_app; create_app()".
3. Boot the app: python -m mediahub.web.web (background).
4. Confirm 0 ERROR-level log lines on a clean boot.

PHASE B — Route sweep:
For each of these routes, confirm a 200 (or correct 30x/40x):
- GET /, /add-input, /upload, /organisation, /settings, /privacy
- GET /pricing, /signup, /login (if Step 7 shipped)
- GET /free-text, /weekend-preview, /sponsor-post, /session-update
- GET /spotlight (if implemented)
- GET /federation, /federation/clubs (if Step 14 shipped)
- GET /marketplace (if Step 16 shipped)
- GET /sponsor (if Step 17 shipped)

PHASE C — Critical user journeys, for each completed step:
- Brand DNA capture: paste a URL, confirm preview, save. Should work.
- Voice imitation: paste 5 examples, save, confirm voice_profile.
- Visible intelligence: open any run, confirm "Why this card?" works.
- Motion: render a story card; render a reel.
- Turn-Into: produce 6-7 artefacts from a meet.
- Buffer or native publishing: schedule a mocked post.
- Commercial: signup, login, upgrade (Stripe test mode).
- Athletics: upload athletics sample, confirm pipeline.
- Athlete page: generate a token, fetch /a/<token>.
- Sponsor mode: toggle on a card, confirm variant.
- Football/Rugby: upload sample, confirm hat-trick / clean sheet.
- Native publishing OAuth: complete one platform's mock flow.
- Integrations: TeamUnify mocked auto-ingest.
- Enterprise: multi-club orchestration.
- Agent: 5 edit commands all hit tools correctly.
- Marketplace: submit + approve + fork.
- Sponsor dashboard: scope correctness + PDF export.

PHASE D — Cross-cutting quality:
- Visual polish: open / and the review page in a browser; screenshot.
  Compare against tryholo.ai's homepage. List any obvious gaps.
- Performance: time a fresh upload-to-content-pack run end-to-end.
  Target < 90s for a 200-swim meet.
- Security: grep the codebase for hardcoded API keys, exposed
  secrets in logs, Path("data/...") relative paths. Report any.
- Test isolation: confirm tests do not write to the real
  data/secrets.json or club_profiles/*.json.
- Accessibility: run a quick a11y scan on the review page. Report
  contrast and keyboard-nav issues.

PHASE E — Strategic position:
For each of the competitors in `docs/research/generation-engine-competitor-evaluation.md`, evaluate where
MediaHub now stands on a 5-point Leading / Competitive / Adequate /
Underdeveloped / Absent scale across the 6 dimensions:
1. Input modality
2. Intelligence layer
3. Output surface
4. Brand context capture
5. Distribution
6. Commercial model

Cross-reference with the competitor analysis in `docs/research/`. Has MediaHub moved up
the matrix on the dimensions Phase 1 targeted? Are there new gaps
that have opened?

OUTPUT FORMAT:
Return a structured audit report:
- Phase A: automated tests results
- Phase B: route table with status codes
- Phase C: per-step pass/fail table
- Phase D: a quality scorecard (1-5) per cross-cutting area
- Phase E: an updated competitive matrix
- Top 5 regression risks (ordered by severity)
- Top 5 next-step recommendations
- A single "release readiness" verdict: Ship / Hold / Block.
```

---

#### Notes on running this roadmap

**Branching.** Every step is a feature branch off `dev`; never merge to `main` without approval. Use names like `step-01-brand-dna-capture`, `step-06-buffer-publishing`. The verification prompt is run before opening the merge request.

**Sequencing.** Steps 1-7 (Phase 1) should be done strictly in order — each builds on the previous. Steps 8-12 (Phase 2) can be partially parallelised once Step 8 (sports architecture) is in. Steps 13-17 (Phase 3) are highest value when done in the order shown but Step 14 (enterprise tier) is the highest financial priority; consider promoting it earlier if revenue is the limiting factor.

**Test budget.** Maintain ≥ 253 passed at every step. Each step adds 5-15 tests, so by Step 17 expect 350+ passing.

**When verification fails.** Paste the failing report back into the implementation session of the same step. Do not move forward until a clean verification report is produced.

**When you stop following the prompts.** Each step is designed to be readable on its own. If during implementation Claude needs context that the prompt didn't provide, the prompt is at fault — improve the prompt and re-run rather than letting Claude guess.

**Source of truth.** This roadmap and the analyses in `docs/research/` (the competitor evaluation + the generative-AI thesis) are the paired references.

---

## Appendix C — Adaptive Theming Engine (1.6): Verification Prompts

> *Stage IDs in this appendix (A–J) map 1:1 to the §1.6 Stage table above. §1.6 is **shipped** — all ten stages are in `main`, live by default, and green. Unlike Appendix A (which builds an as-yet-unbuilt engine), this appendix is **verification-only**: paste-into-a-session acceptance audits that independently confirm each shipped stage still meets its part of the §1.6 acceptance criteria. There are no implementation prompts here — the code already exists.*

**What this is.** A per-stage acceptance-audit harness for the now-shipped
Adaptive Theming Engine. Each stage below has a **Context** (what shipped +
the real files) and a **Verification prompt** (paste into a fresh session).
The prompts are read-only audits plus the test suite; none should need to
modify the engine. A final **full-engine acceptance audit** ties the
per-stage checks back to the five numbered acceptance criteria in §1.6.

**Date:** May 2026 · **Built against:** `main` with Stages A–J merged (the
`theming/` package, the five `static/theme/*.css` layers, `theme_store.py`,
and `docs/THEMING.md`).

**Why verify a shipped feature.** The engine touches every rendered page and
four output media (web, motion, email, static graphic). It is exactly the
kind of cross-cutting surface where a later refactor can silently regress
contrast, drift one medium's palette from the others, or break the cascade.
These prompts are the regression harness that proves it still holds.

---

### 1. The shared verification preamble (every prompt inherits this)

> **Preamble — read before doing anything.** You are auditing MediaHub's
> **shipped** Adaptive Theming Engine (ROADMAP §1.6) in the repo
> (`/home/user/MediaHub` or the session's checkout). Read `CLAUDE.md`,
> `docs/THEMING.md`, and the file(s) named in the task. This is a
> **verification** task — read code, run tests, exercise routes, and report a
> pass/fail checklist. Hard rules:
> - **The colour-science engine is deterministic and off-limits to AI.**
>   `theming/` (palette, roles, contrast, cvd, quality, repair, seed_extract,
>   harmony, logo_chip) and the CIEDE2000 / APCA / Machado maths must stay
>   deterministic. If a check fails, **report it** — do **not** "fix" it by
>   routing a judgement through Gemini/Anthropic, and do not add a hand-tuned
>   per-seed override (the point of §1.6 is intelligence in the algorithm,
>   not a lookup table).
> - **No test cheating.** If you run the suite, do not delete, skip, or weaken
>   a test to make it pass. A red test is a finding, not an obstacle.
> - **Determinism is a property under test.** Same seed → byte-identical
>   palette, every time. If you find non-determinism, that is a failure.
> - **Read-only by default.** These prompts should not need to modify the
>   engine. If you find a genuine gap, report it with a minimal repro; only
>   fix it in a **separate, clearly-scoped** branch + PR with the user's
>   go-ahead — never fold an engine change into a verification pass.
> - **Run the tests named in the task plus the full suite**
>   (`python -m pytest tests/ -q`); confirm no new failures vs `main`.
> - **Report format:** a pass/fail checklist, one line per claim, citing the
>   `file:line` or test name that proves each.

---

### 2. Per-stage verification prompts

#### Stage A — Token foundation
**Shipped:** ~25 MD3-style role tokens (`--mh-surface`, `--mh-on-surface`,
`--mh-primary`, …) defined in `static/theme/theme-base.css` and surfaced via
`web/theme_tokens.py`; every animatable seed/colour registered with
`@property { syntax: "<color>"; inherits: true }`. Tests:
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage A (token foundation). Confirm: the ~25 documented
> role tokens all exist in `theme-base.css`; each animatable colour variable
> (the `--mh-*-seed` set and the role tokens that transition) is registered
> via `@property` with `syntax: "<color>"` (grep the `@property` blocks); no
> transitioned colour relies on an untyped custom property; and migrating to
> tokens introduced no visual change for the default brand (the token values
> resolve to the pre-token palette). Run `tests/test_theme_tokens.py` + the
> full suite. Report any token that is missing or unregistered.

#### Stage B — Colour-science library
**Shipped:** the `src/mediahub/theming/` package — `seed_extract.py`,
`palette.py`, `roles.py`, `contrast.py` (APCA Lc + WCAG2), `cvd.py` (Machado
2009), `quality.py` (`PaletteQualityReport`), `repair.py`, `harmony.py`
(Cohen-Or). Deps `materialyoucolor` + `coloraide` in `pyproject.toml` /
`requirements.txt`. Entry point `theming.derive_theme(seed)`. Tests:
`tests/theming/test_palette.py`, `test_contrast.py`, `test_cvd.py`,
`test_quality.py`, `test_repair.py`, `test_seed_extract.py`,
`test_harmony.py`.

**Verification prompt:**
> [Preamble.] Verify Stage B (colour-science package). Confirm: `derive_theme`
> is deterministic (call it twice on one seed → byte-identical `to_json()`);
> the pipeline is seed → HCT → 5×13 tonal palettes → MD3 roles → APCA/ΔE/CVD
> gates → bounded repair loop (`repair_max_iters` honoured, never infinite);
> `contrast.py` APCA Lc and `cvd.py` Machado matrices match their known
> fixtures; no module makes a network/LLM call (grep `theming/` for
> `requests`, `httpx`, `media_ai`, `ai_core` — none); and an empty/garbage
> seed returns the fallback theme rather than raising. Run all
> `tests/theming/test_*` + the full suite. State the determinism result
> explicitly.

#### Stage C — CSS architecture
**Shipped:** the inline `<style>` block is extracted into `static/theme/`
across `theme-base.css`, `theme-derive.css` (the `color-mix(in oklch, …)` +
relative-colour derivation graph), `theme-components.css`, `theme-cascade.css`,
and `theme-fallback.css` (the `@supports not (color: oklch(from red l c h))`
precomputed ramp). `light-dark()` drives surface/ink pairs off
`prefers-color-scheme`. Tests: `tests/test_theme_static_files.py`,
`tests/test_theme_tokens.py`.

**Verification prompt:**
> [Preamble.] Verify Stage C (CSS architecture). Confirm: the bulk of the
> chrome's colours are *derived* in CSS (grep `theme-derive.css` for
> `color-mix(in oklch` and `oklch(from var(--mh-brand-seed)` — the derivation
> graph is present, not a hardcoded ramp); `light-dark()` is used for
> surface/ink pairs and `prefers-color-scheme` is honoured; the Safari
> long-tail fallback lives inside an `@supports not (...)` block in
> `theme-fallback.css` with no JS polyfill; and the CSS is served as static
> files with a cache-busting URL (not re-inlined per request). Run
> `tests/test_theme_static_files.py` + the full suite. Report the count of
> hardcoded brand-colour hex literals found in colour-derivation positions in
> the CSS layers (expected: ~0).

#### Stage D — Theme delivery (Flask)
**Shipped:** a `before_request` hook + `_theme_seed_style_block()` emit an
inline `<style id="mh-theme-seed">` carrying the active org's brand-seed
override into `<head>` *before* the external stylesheet (zero FOUC).
Resolution is three-tier (flag-off → pinned-org palette → generic-default).

**Verification prompt:**
> [Preamble.] Verify Stage D (theme delivery). Boot the app and request a
> page; confirm the inline `<style id="mh-theme-seed">` block appears in
> `<head>` **before** the external `theme-base.css` link (so there is no flash
> of un-themed content) and carries the active organisation's seed. Confirm
> the three-tier resolution in `_theme_seed_style_block()`:
> `MEDIAHUB_ADAPTIVE_THEME=0` emits nothing (falls through to the static
> cascade), a pinned org uses its `derived_palette`, and no-org uses the
> generic-default theme. Confirm the payload is small (hundreds of bytes, not
> the full palette). Report the head ordering and the three-tier behaviour.

#### Stage E — "Looks right" cascade
**Shipped:** the organisation-finalise handler derives + persists the palette
(`ensure_derived_palette(force=True)`) and navigates via
`document.startViewTransition`; `theme-cascade.css` carries
`@view-transition { navigation: auto }`, the `:root` seed `transition`, and
the `prefers-reduced-motion: reduce` instant-swap override. Tests:
`tests/test_theme_cascade.py`, `tests/test_browser_cascade.py`.

**Verification prompt:**
> [Preamble.] Verify Stage E (the cascade). Confirm: the "Looks right — start
> creating" finalise path saves the brand kit, derives + persists
> `derived_palette`, and wraps the navigation in `document.startViewTransition`
> (degrading to a normal nav where unsupported); `theme-cascade.css` contains
> the `@view-transition` rule, the `:root` colour `transition`, and a
> `@media (prefers-reduced-motion: reduce)` block that disables both; and
> because every derived var is a `color-mix`/`oklch(from …)` of the seed,
> changing the seed alone interpolates the whole palette in lockstep. Run
> `tests/test_theme_cascade.py`; run `tests/test_browser_cascade.py` with
> `MEDIAHUB_RUN_BROWSER_TESTS=1` if a browser is available (else note it's
> gated). Report each contract check.

#### Stage F — Logo intelligence
**Shipped:** `theming/logo_chip.py` defaults to a neutral chip behind an
uploaded logo and computes a "safe to drop chip" decision (dominant
non-neutral colour vs active surface in OKLCH; ΔE2000 + APCA Lc gates in both
polarities); MediaHub's own marks use `fill="currentColor"`; uploaded SVG
marks are never recoloured. Tests: `tests/test_logo_chip.py`,
`tests/test_mediahub_mark_theming.py`.

**Verification prompt:**
> [Preamble.] Verify Stage F (logo intelligence). Confirm: `logo_chip.py`
> defaults to a neutral chip and exposes a deterministic "safe to drop chip"
> test driven by ΔE2000 + APCA Lc in both light and dark polarities;
> MediaHub's *own* SVG marks use `fill="currentColor"` so the chrome adapts to
> ink colour; and the path for *uploaded* logos never recolours or injects
> `currentColor` into an unknown mark (it only adds/removes a chip behind it).
> Run `tests/test_logo_chip.py` + `tests/test_mediahub_mark_theming.py` + the
> full suite. Report the chip-decision logic and confirm the "never recolour
> uploaded marks" guarantee holds.

#### Stage G — Single source of truth (motion + email + static graphic)
**Shipped:** `theming/theme_store.py` writes the DTCG palette JSON to
`DATA_DIR/themes/<profile_id>.json`; `visual/motion.py` passes it as
`inputProps` to `render.js`; `brand/newsletter_renderer.py` Premailer-inlines
the resolved hexes; `graphic_renderer/render.py` reads the same JSON instead
of `BrandKit.primary_colour`. Tests: `tests/test_theme_store.py`,
`test_motion_theme_store.py`, `test_newsletter_theme_store.py`,
`test_graphic_renderer_theme_store.py`.

**Verification prompt:**
> [Preamble.] Verify Stage G (single source of truth). Confirm there is
> exactly **one** palette source — the `theme_store.py` JSON at
> `DATA_DIR/themes/<profile_id>.json` — and that all four consumers read it:
> `visual/motion.py` (→ Remotion `inputProps`), `brand/newsletter_renderer.py`
> (Premailer-inlined hexes, since email clients don't support custom
> properties), `graphic_renderer/render.py`, and the web cascade. Pick one
> seed, derive its theme, and assert the **same** role hex appears in the
> motion props, the inlined email HTML, the static graphic, and the CSS seed
> block — **zero drift across media**. Run the four `*_theme_store.py` tests +
> the full suite. Report the cross-media hex comparison.

#### Stage H — Explainability + QA
**Shipped:** `PaletteQualityReport` (`quality.py` `to_summary()` +
`to_detail()`) logs APCA Lc per role pair, the CIEDE2000 matrix for brand ×
{neutral, success, warning, danger}, Machado-CVD ΔE under
deutan/protan/tritan, the Cohen-Or harmonic-fit energy, and a decision trace;
a "Why does my theme look like this?" panel on `/organisation/setup` shows the
decisions + lets a committee member override a role (logged, with a
cultural-clash warning if it lowers a status colour's ΔE); a non-blocking
callout fires when the hostile-seed repair loop ran. Tests:
`tests/test_quality_detail.py`, `test_repair_callout.py`,
`test_org_palette_confirm.py`.

**Verification prompt:**
> [Preamble.] Verify Stage H (explainability + QA). Confirm: every derivation
> produces a `PaletteQualityReport` with APCA Lc per text-on-surface pair, the
> brand×status CIEDE2000 matrix, Machado-CVD ΔE under all three CVD types, the
> Cohen-Or harmonic-fit energy, and a human-readable decision trace; the "Why
> does my theme look like this?" panel renders these on `/organisation/setup`;
> a manual role override is persisted *and* logged, and lowering a status
> colour's ΔE raises a cultural-clash warning; and when the repair loop fires
> on a hostile seed, a non-blocking callout explains *which status colour* was
> nudged and why (never silently rewriting the brand colour). Run
> `tests/test_quality_detail.py` + `test_repair_callout.py` +
> `test_org_palette_confirm.py` + the full suite. Report each explainability
> surface.

#### Stage I — Test coverage
**Shipped:** `tests/theming/` with golden-master snapshots for ~30
representative seeds (incl. fluorescent `#DFFF00`, muddy `#2A3A1A`, near-white
`#FAFAF7`, near-black `#0C0C0C`, brand red `#A30D2D`, brand navy `#0E2A47`, +
real club colours) in `seeds_catalogue.py` / `snapshots/`, plus
APCA/CVD/quality/repair unit tests; `tests/test_browser_cascade.py` is the
Playwright/browser-use end-to-end (gated on `MEDIAHUB_RUN_BROWSER_TESTS=1`).

**Verification prompt:**
> [Preamble.] Verify Stage I (test coverage). Confirm: the golden-snapshot set
> in `tests/theming/` covers the hostile seeds
> (neon/muddy/near-white/near-black/pure-primary) **and** real club colours;
> the gate tests actually assert the §1.6 thresholds (APCA Lc ≥ 75 for
> text-on-surface; CIEDE2000 ≥ 5 between adjacent tonal stops; ≥ 15 between
> brand and each status colour; Machado-deuteranopia ΔE2000 ≥ 10 for the same
> triples; Cohen-Or fit below threshold); the snapshots regenerate
> deterministically (no flakiness); and `tests/test_browser_cascade.py` exists
> and is correctly gated. Run `python -m pytest tests/theming/ -q` and report
> the count + whether any threshold is asserted more weakly than §1.6 states.

#### Stage J — Cutover + polish
**Shipped:** `_adaptive_theme_enabled()` reads `MEDIAHUB_ADAPTIVE_THEME`
(default **on**; `0/false/off/no` rolls back to the static cascade) — J1;
`_default_theme_json()` runs the generic-default BrandKit (`#0E2A47` /
`#C9A227`) through the pipeline for unconfigured first-run — J2;
`docs/THEMING.md` documents the architecture, role-token table,
operator-overridable variables, and academic citations — J3. Tests:
`tests/test_adaptive_theme_flag.py`, `test_default_theme.py`,
`test_theming_md.py`.

**Verification prompt:**
> [Preamble.] Verify Stage J (cutover + polish). Confirm: `MEDIAHUB_ADAPTIVE_THEME`
> defaults **on**, and setting it to `0`/`false`/`off`/`no` cleanly reverts
> every page to the static Stage-A cascade with no errors (the on-disk JSON,
> audit panel, and repair callout keep working regardless); the generic-default
> brand kit is themed through the same pipeline (unconfigured deployments get
> the upgrade, no regression); and `docs/THEMING.md` documents the
> architecture, the role-token table, the variables an operator may safely
> override, and the inline academic citations. Run
> `tests/test_adaptive_theme_flag.py` + `test_default_theme.py` +
> `test_theming_md.py` + the full suite. Report the flag round-trip and the
> default-theme behaviour.

---

### 3. Full-engine acceptance audit (maps to the §1.6 acceptance criteria)

**Verification prompt:**
> [Preamble.] Run the §1.6 "definition of done" end-to-end and report a single
> scorecard against the five acceptance criteria:
> 1. **Hostile-seed gate.** Drive ~30 representative seeds (incl.
>    neon/muddy/near-greyscale/pure-primary) through `derive_theme`; assert
>    APCA Lc ≥ 75 for every text-on-surface role pair, CIEDE2000 ≥ 5 between
>    adjacent tonal stops, ≥ 15 between brand and each of
>    success/warning/danger, Machado-deuteranopia ΔE2000 ≥ 10 for those
>    triples, and Cohen-Or fit below threshold. Report any seed that fails any
>    gate.
> 2. **Live cascade.** Confirm the cascade works in Chromium (run
>    `tests/test_browser_cascade.py` with `MEDIAHUB_RUN_BROWSER_TESTS=1` if
>    available) and degrades to instant nav where View Transitions is
>    unsupported; reduced-motion users get an instant swap.
> 3. **No stray hardcoded brand colour.** Grep the whole repo for
>    brand-colour hex literals outside `theming/repair.py`'s curated-neighbour
>    fallback table; report any found in template/CSS/Python colour positions.
> 4. **Zero cross-media drift.** For one seed, assert the same role hexes
>    appear in web (CSS seed block), motion (`inputProps`), email (inlined
>    HTML), and static graphic.
> 5. **Suite green.** `python -m pytest tests/ -q` — no new failures vs
>    `main`, no weakened/skipped tests masking a structural break.
> Output: a five-row pass/fail table with the proof (test name / `file:line`)
> for each, plus any regression risk you spotted.

---

### 4. If a verification fails

A failure here is a real regression in shipped code, not a build step.
Capture a minimal repro (the seed, the role pair, the failing assertion),
report it against the stage above, and fix it in a **separate** branch + PR
scoped to that regression — keeping the colour-science deterministic and never
substituting an AI judgement or a hand-tuned per-seed override for the
algorithm. Re-run the full-engine audit (§3) before closing.

---

*End of roadmap.*
