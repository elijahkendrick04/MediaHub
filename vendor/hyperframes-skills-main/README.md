# HyperFrames skills (vendored reference)

Reference copy of the core craft skill from HeyGen's
[HyperFrames](https://github.com/heygen-com/hyperframes) — an open-source
"write HTML, render video" framework whose Claude skills encode strong motion
design knowledge: beat direction, motion principles, scene transitions,
typography for video, data-in-motion, captions, and quality checks.

- **Source:** https://github.com/heygen-com/hyperframes
- **Commit:** `d0a7f7d839dd1d93dcd2a04226d3111928e213a5` (2026-06-12)
- **License:** Apache-2.0 (see `LICENSE` in this folder; `CREDITS.md` kept from upstream)
- **Vendored subset:** `skills/hyperframes/` only — the craft core. The rest of
  the upstream repo (CLI, runtime packages, registry, GSAP/Lottie/Three/shader
  skills, SFX assets) is specific to the HyperFrames runtime and was not taken.

## Why this is here — and what it is NOT

This folder is **reference material only**, kept per the house rule that
downloaded skill collections live under `vendor/`. It is **not** a MediaHub
product dependency:

- MediaHub video stays on **Remotion** (`src/mediahub/remotion/`), invoked via
  `src/mediahub/visual/motion.py`. HyperFrames the runtime is not installed,
  not shelled out to, and must not become a render path.
- HyperFrames' implementation idiom (GSAP timelines, `data-*` clip attributes,
  CSS/WAAPI animation, WebGL shader packages) does **not** transfer: MediaHub
  compositions must stay a pure function of the frame (no CSS animation —
  see `.claude/skills/mediahub-engineering/rules/motion-and-audio.md`).
- Its palette presets and Google-Fonts discovery script do **not** transfer:
  MediaHub colour comes from the club's resolved BrandKit palette and fonts are
  fixed, self-hosted brand typefaces.

The craft knowledge was adapted ("made our own") into two MediaHub-native
skills, rewritten for the Remotion + Playwright deterministic stack:

- `.claude/skills/motion-craft/` — beat direction, choreography, transitions,
  on-video text for story cards and meet reels.
- `.claude/skills/graphic-craft/` — composition, typography, data presentation
  and anti-samey variety for still result cards and spotlights.

Per Apache-2.0 §4: those adapted files are modified derivative works; the
upstream license and notices are retained here.

Do not edit files under this folder (house rule for `vendor/`).
