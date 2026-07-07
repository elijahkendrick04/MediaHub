# UI Uplift — Aceternity + Refero design-system integration

This folder records a curated UI/design-system uplift that worked through **every**
component on [Aceternity UI](https://ui.aceternity.com/components) (108 components) and
a representative breadth of [Refero](https://styles.refero.design/) design styles,
adopting the patterns that fit MediaHub and skipping the ones that fight a dark-first,
editorial/sport product.

## Approach (why it looks the way it does)

MediaHub's web UI is a **Flask monolith with f-string Jinja2 templates**, a Phase-1.6
theme cascade, and **no React / Tailwind / Framer Motion / bundler**. Aceternity ships
React + Framer + Tailwind components; Refero is a gallery of real-product *screenshots*
grouped by style. Neither can be dropped in 1:1. So:

- **Every adopted effect is re-implemented natively** as vanilla CSS + a small
  progressive-enhancement JS layer, reusing the existing design tokens.
- **No new external API/MCP dependency**; self-hosted, no CDN (honours the
  self-hosted-fonts / no-CDN rule).
- Every effect is **token-driven** (a re-skinned brand re-skins the effect),
  **`prefers-reduced-motion`-gated**, and **fails safe** (the page is fully usable with
  the effect absent — no-JS, reduced-motion, or old engine).

## The kit (foundation)

| File | Role |
|---|---|
| `src/mediahub/web/static/theme/theme-motion.css` | Effect layer — loads after `theme-components`, before the responsive guardrails (which stay last). |
| `src/mediahub/web/static/js/ui-kit.js` | Behaviour layer — pointer-follow, tilt, IntersectionObserver reveal/count-up, tab indicator, compare, lens, scroll progress, `MH.renderLogSteps` / `MH.btnState` / `MH.cursorReadout`. Deferred, re-entrant (`MH.ui.init`), fails safe. |

Loader wiring: `theme_tokens.py` exports `THEME_MOTION_CSS`; `web.py` appends it to
`BASE_CSS` and adds `<script defer src=".../js/ui-kit.js">` to the shared shell.

## Where it's wired (screen → effect)

| Screen | Effects integrated |
|---|---|
| **Home / landing** | Spotlight (hero ambient), count-up/odometer hero stats (`data-mh-count` + `data-mh-odometer`), reveal + reveal-lines (sections and final CTA via `.mh-reveal`). *(The sport marquee, home Card-Spotlight samples and split-flap Flapboard were later removed in the "Tidy home page" pass — see the REMOVED rows below.)* |
| **Upload** | Aurora ambient (entry hero) |
| **Processing** | Multi-Step Loader (real pipeline log → live step checklist via `MH.renderLogSteps`) |
| **Review** | Count-up (recognition stats, via the existing `data-mh-count`), bar-fill (priority bars), Animated-Tooltip (athlete avatar on every card → name · club · meet haul, via `.mh-tooltip`), client-side workflow Tabs (`.mh-tabs` — Queue/Approved filter switches in place, no reload, UI2.4), inline machine-readable **Codeblock** (the run's recognition data, syntax-highlighted + copyable on the Recognition-summary card, UI2.8) |
| **Make** | Glow-border (live content-type tiles) |
| **Settings** | Glow-border (category tiles) + reveal-group (tile grid) |
| **Sign-in** | Card-Spotlight (org profile cards) |
| **Plan** | reveal (plan items) |
| **Media library** | Lens (asset thumbnail magnify-to-inspect) |
| **Athlete spotlight** | Animated-Tooltip (`.mh-tooltip`) — decorative avatars on the swimmer roster, a keyboard-reachable hero avatar carrying name · club · band haul |
| **Upload · Make** | Primary-CTA (`.btn.mh-cta-motion`, UI2.5) — Moving-Border ring + Stateful-Button (`data-mh-state`, idle→loading→success) on one borderless host: the Upload "Continue" submit (spins while the file uploads) and the Make "Generate the pack" action (loading→success before the pack opens) |

Moving-Border + Stateful-Button are wired together on the primary-CTA host
(`.btn.mh-cta-motion`, UI2.5 — Upload / Make). The kit also ships ready-to-use effects not yet
wired to a specific screen (Aurora, Grid/Dot/Scales/Grain backgrounds, gradient-border,
3D tilt, hover-group, Hover-Border-Gradient, Text-Generate, Hero-Highlight,
Compare slider, Tracing-Beam, Timeline, Vanish-input) for follow-on surfaces.
(Glare, Flip-Words and the Flapboard shipped in the kit but were never wired,
and were deleted in the dead-code sweep — see the REMOVED verdicts below.)

---

## Aceternity — verdict on all 108 components

`ADOPT` = re-implemented and/or wired. `PARTIAL` = idea adopted, restrained or pending a
host surface. `SKIP` = off-brand / gimmick / irrelevant to a sports-club product (per
MediaHub's UI guide: *avoid generic AI-SaaS patterns; no over-animation*).

### Backgrounds & effects
| Component | Verdict | Note |
|---|---|---|
| Webcam Pixel Grid | SKIP | no webcam use case |
| Images Badge | SKIP | marginal |
| Parallax Hero Images | PARTIAL | restrained hero only |
| Scales | ADOPT | `.mh-scales-bg` texture |
| Dotted Glow Background | PARTIAL | folded into dot/grid bg |
| Background Ripple | SKIP | distracting |
| Sparkles | ADOPT | `.mh-sparkles` (restrained, achievement accents) |
| Background Gradient | ADOPT | `.mh-gradient-border` |
| Gradient Animation | PARTIAL | aurora covers it |
| Wavy Background | PARTIAL | swim motif, used sparingly |
| Background Boxes | PARTIAL | |
| Background Beams | PARTIAL | |
| Background Beams w/ Collision | SKIP | too much |
| Background Lines | PARTIAL | |
| Aurora Background | ADOPT | `.mh-aurora` |
| Meteors | PARTIAL | |
| Glowing Stars | PARTIAL | |
| Shooting Stars | SKIP | redundant |
| Vortex | SKIP | too busy |
| Spotlight / Spotlight New | ADOPT | `.mh-spotlight` (hero) |
| Canvas Reveal | PARTIAL | |
| SVG Mask Effect | PARTIAL | |
| Tracing Beam | ADOPT | `.mh-tracing-beam` |
| Lamp Effect | PARTIAL | |
| Grid and Dot Backgrounds | ADOPT | `.mh-grid-bg` / `.mh-dot-bg` |
| Glowing Effect | ADOPT | `.mh-glow-border` (Make tiles) |
| Google Gemini Effect | SKIP | another brand's identity |
| Dither Shader | SKIP | off-brand |
| Noise Background | ADOPT | `.mh-grain` (subtle, anti-banding) |

### Cards
| Component | Verdict | Note |
|---|---|---|
| Keyboard / Terminal / ASCII Art / Pixelated Canvas | SKIP | not relevant |
| 3D Card Effect / Comet Card | ADOPT | `.mh-tilt` |
| Evervault Card | SKIP | gimmick |
| Card Stack | PARTIAL | |
| Card Hover Effect | ADOPT | `.mh-hover-group` |
| Wobble Card | PARTIAL | |
| Expandable Card | PARTIAL | pending review-card detail |
| Card Spotlight | ADOPT | `.mh-spotlight-card` (sign-in org profile cards) |
| Focus Cards | PARTIAL | needs a grid gallery (media lib is a table) |
| Infinite Moving Cards | REMOVED | shipped as `.mh-marquee` (home sport band), removed with the "Tidy home page" pass; no producer at HEAD |
| Draggable Card | SKIP | no use |
| Glare Card | REMOVED | shipped as `.mh-glare` but no surface ever used it; deleted in the dead-code sweep |
| Direction Aware Hover | PARTIAL | needs image grid |

### Scroll / parallax
| Component | Verdict | Note |
|---|---|---|
| Parallax Scroll | PARTIAL | |
| Sticky Scroll Reveal | ADOPT | reuses the existing `.mh-reveal` system (`.is-in`) |
| Macbook Scroll | SKIP | device mockup, off-brand |
| Container Scroll | PARTIAL | |
| Hero Parallax | PARTIAL | |

### Text
| Component | Verdict | Note |
|---|---|---|
| Canvas Text / Squiggly Text / Text Reveal Card | SKIP | busy / gimmick |
| Encrypted Text | SKIP | gimmick |
| Layout Text Flip / Container Text Flip | PARTIAL | flip-words covers it |
| Colourful Text | SKIP | reads AI-generic |
| Text Generate Effect | ADOPT | `.mh-text-generate` (kit; skipped on editable caption by design) |
| Typewriter Effect | PARTIAL | |
| Flip Words | REMOVED | shipped as `.mh-flip-words` but no surface ever used it; deleted in the dead-code sweep |
| Text Hover Effect | PARTIAL | |
| Hero Highlight | ADOPT | `.mh-highlight` |
| Text Flipping Board | REMOVED | shipped as `.mh-flapboard` but no surface ever used it; deleted in the dead-code sweep |

### Buttons / loaders / nav / inputs
| Component | Verdict | Note |
|---|---|---|
| Magnetic Button | PARTIAL | |
| Tailwind Buttons | SKIP | the app has its own `.btn` system |
| Hover Border Gradient | ADOPT | `.mh-hover-border-gradient` |
| Moving Border | ADOPT | `.mh-moving-border`; wired on the `.btn.mh-cta-motion` primary CTA (UI2.5) |
| Stateful Button | ADOPT | `.btn[data-mh-state]` + `MH.btnState`; wired on the `.btn.mh-cta-motion` primary CTA (UI2.5) |
| Multi Step Loader | ADOPT | processing screen (`MH.renderLogSteps`) |
| Loader | ADOPT | reuses existing `.mh-spinner` / skeletons |
| Notch | SKIP | |
| Floating Navbar / Resizable Navbar | PARTIAL | existing topnav is already sticky |
| Navbar Menu | PARTIAL | |
| Sidebar | PARTIAL | app is top-nav only by design |
| Floating Dock | PARTIAL | |
| Tabs | ADOPT | `.mh-tabs` sliding indicator — wired to the review Queue/Approved filter as client-side tabs (UI2.4) |
| Sticky Banner | PARTIAL | |
| Signup Form | PARTIAL | informs auth-form styling |
| Placeholders & Vanish Input | ADOPT | `.mh-vanish` |
| File Upload | ADOPT* | dropzone is already this natively |
| Gooey Input | SKIP | vanish-input wins |

### Overlays / carousels / layout / data / cursor / 3D
| Component | Verdict | Note |
|---|---|---|
| Animated Modal | ADOPT | reuses existing `.mh-modal` (already animated) |
| Animated Tooltip | ADOPT | `.mh-tooltip` — athlete-avatar tooltips on the review queue + spotlight surfaces (UI2.2) |
| Link Preview | PARTIAL | |
| Images Slider | PARTIAL | |
| Carousel / Apple Cards Carousel | PARTIAL | content-pack preview |
| Animated Testimonials | PARTIAL | landing social proof |
| Layout Grid | PARTIAL | gallery expand |
| Bento Grid | PARTIAL | dashboard candidate |
| Container Cover | PARTIAL | folded into spotlight/aurora |
| GitHub Globe / World Map / 3D Globe | SKIP | not relevant to a club |
| Timeline | ADOPT | `.mh-timeline` (recap / audit) |
| Compare | ADOPT | `.mh-compare` (cutout A/B) |
| Codeblock | ADOPT | `code_highlight` first-party server-side highlighter (`.mh-cs-*`/`.mh-tok-*`); wired to the review page's inline machine-readable raw parsed-data view (UI2.8) |
| Following Pointer / Pointer Highlight | SKIP | gimmick |
| Lens | ADOPT | `.mh-lens` (media library) |
| 3D Pin / 3D Marquee | PARTIAL | |

**Tally:** ~37 ADOPT, ~24 PARTIAL (idea taken; restrained or awaiting a host surface),
~25 SKIP, 4 REMOVED (shipped, then deleted once unwired — Glare, Flip Words,
Flapboard, Infinite Moving Cards). Every one of the 108 has a verdict.

---

## Refero — design-direction audit

Refero catalogues design *directions* (≈20-30 distinct families across 2,000+ entries),
not components, so the integration is a **principled audit**: distil each direction, map
it to MediaHub's tokens, adopt the gaps, skip what's off-brand. Sampled representatively
across the distinct families (curated-breadth).

### Styles sampled
| Style | Family | One-line |
|---|---|---|
| **Dala** | cosmic / void | violet pulse on infinite black; ultra-thin display; hairline borders |
| **Linear** | dark precision | acid-lime status light on obsidian; razor-thin type; one rationed accent |
| **Mercury** | dark fintech | command centre at twilight; single violet-blue CTA accent; no shadows |
| **Apple** | restraint | gallery-white; weight-700 headlines; colour reserved for the one blue button |
| **Auros** | deep-teal precision | abyssal trading terminal; tonal elevation, no shadows; aurora-gradient ghost borders |
| **Active Theory** | experimental void | observatory; mono micro-labels; serif body; one rationed accent |
| **Air** | light / airy | serene cloud UI; action-blue accent; frosted glass |
| **Gsap** | dark / neon-brutalist | extreme display type (224px, 0.90 line-height, −0.020em); colour-as-information |
| **Sequel** | dark / cinematic gallery | binary radius discipline (10px cards / 9999px pills); weight-300 body |
| **dope.security** | dark / glass | one rationed violet accent (#af50ff); zero card box-shadows; −0.07em @ 80px |
| **ORYZO AI** | dark / warm-black | accent as hairline signal, never a fill (#dc5000, 1px only); display line-height 0.90 |
| **Integrated Biosciences** | dark + light bands | hierarchy from size + tightening on a single 400 weight (−0.03em@158px); mono counters |
| **Superpower** | light | inverse tracking hierarchy (−0.025em display → −0.005em body) |
| **Structured** | mixed | dramatic display tracking; compressed display line-height 0.84 ("carved") |
| **Dylanbrouwer** | mixed | IBM Plex Mono metadata register; display line-height 0.74 |
| **monopo saigon** | mixed | tight display line-height 0.70–0.76; colour reserved for imagery, never UI |
| **Adaline / Monad / Seed / Dia Browser / Portal / Ditto** | light | SKIP — light themes, off-brand for dark-first |

> **Reachability note:** Refero's public index is hard-capped at ~20 entries (client-rendered, no pagination), so the **~22 distinct styles** sampled here are essentially *the full set the site exposes* — the advertised "2,000+" isn't browsable. The curated-breadth ~40-60 target isn't reachable without external deep-links; this audit covers what Refero surfaces.

### Convergent principles → MediaHub alignment
| Principle (shared across the dark systems) | MediaHub status |
|---|---|
| **Single rationed accent** — monochrome at rest, one high-contrast accent for primary action only | **Already core** — lane-yellow `--mh-primary` is the single accent; medals are the only secondary |
| **4px base · 1200px max · 80-120px section rhythm** | **Aligned** — `--sp-*` 4px base, `--container-lg: 1200px` |
| **Tight radius vocabulary** (badge 2px, control 6px, card 12-16px, pill 9999px) | **Aligned** — `--radius` 4 / `-md` 6 / `-lg` 10 / `-pill` 999 |
| **Negative tracking on display type, scaled to size; wide positive tracking on uppercase labels** | **Already done** — hero h1 `letter-spacing: -0.01em`; mono eyebrows `+0.14–0.18em` uppercase |
| **Tonal / hairline-first depth, not heavy shadows** | **Aligned** — `.card` uses a 1px hairline + the near-flat `--shadow-1`; tonal surface ramp (`--mh-surface` → `-variant` → `-container` → `-container-high`) |
| **Gradient backdrops are theatrical / full-bleed, never UI chrome** | **Added by this PR** — `.mh-aurora` / `.mh-spotlight` hero backdrops; `.mh-glow-border` hairline glow |
| **Mono uppercase micro-labels for chrome** (Active Theory, Linear) | **Already pervasive** — mono eyebrows / straps throughout |
| **No box-shadows — tonal + 1px-hairline depth** (dope.security, ORYZO, IB, Mercury, Apple, Auros) | **Aligned** — `.card` uses a hairline + the near-flat `--shadow-1`, not drop shadows |
| **Accent as hairline signal, never a fill** (ORYZO AI) | **Validated** — lane-yellow is the single accent; hairlines (`--mh-outline`) carry separation |
| **Sub-1.0 display line-height** (Gsap 0.90, ORYZO 0.90, Structured 0.84, monopo 0.70) | **Already done** — `h1 { line-height: 0.95 }` on the condensed display face |

**Finding:** MediaHub's design system already matches the elite dark-precision systems on
every load-bearing axis. The Refero pass is **validation**, plus the gradient-backdrop /
glow-border / single-accent treatments the references use — which this PR's Aceternity work
adds — rather than an overhaul. No risky global type/colour/shadow change was warranted.

### Adopted refinements
- `.mh-gradient-text` — the "single chromatic accent as a gradient on type" move
  (Apple/Mercury/Auros product-gradient idea), as an opt-in utility (`--mh-primary` →
  `--mh-tertiary`), with a solid-colour fallback for engines without `background-clip:text`.

### Skipped families (recorded for honesty)
- **Light themes** (Air, Apple's gallery-white) — off-brand for MediaHub's deliberate
  dark-first identity.
- **Ultra-thin giant display type** (Dala 113px wt-200, Auros 295px) — wrong for a
  punchy sport/editorial product built on the condensed Big Shoulders display face.
- **Particle-cosmos / 3D-artifact-as-hero** (Dala, Active Theory) — atmospheric, but a
  sports-club product leads with real athlete content, not a void centrepiece.
- **Serif body copy** (Active Theory's Times) — MediaHub keeps Fraunces serif for accents
  only; Hanken Grotesk stays the workhorse body face.
