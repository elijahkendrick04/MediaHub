# Static graphics and brand fidelity

## The result card is rendered exactly, not generated

Static graphics (result cards, spotlights, story graphics) are rendered
deterministically: HTML/CSS templates → PNG via headless Chromium (Playwright)
in `graphic_renderer/render.py`. The card must be **factually exact** (the time
is the time), **brand-exact** (the real hex, the real logo), and **true** (real
athlete imagery; **no synthetic AI-generated people** unless explicitly
requested). Generative image models approximate and hallucinate text / numbers —
never use them to render the card itself.

## Text must be measured to fit

Long names / events / captions overflow fixed layouts (a live issue: the
1080×1920 story format truncates long captions because layout isn't yet
caption-length-aware). Measure text and fit it to its box (deterministic
auto-fit) rather than assuming a fixed size.

## Brand is a single source of truth

The resolved palette lives as DTCG-format JSON (`theme_store`) and on
`ClubProfile.brand_kit.derived_palette` (`brand/kit.py`). The web UI, motion
(Remotion), email, and the static graphic renderer all consume the **same**
palette — never re-hardcode a hex in one surface. Colour maths
(contrast / ΔE2000 / CVD) is computed in `theming/`, not hand-tuned per club.

## Generative imagery: background only, under the text

`visual/ai_background.py` already implements the only sanctioned
generative-image use: an **abstract, non-figurative, brand-coloured background**
(explicitly *no people, no faces, no text, no logos*; central negative space for
the text overlay), cached by hash, **degrading to a procedural pattern** when
unavailable. Generated images are a billed feature and carry a provider
watermark — keep them optional and behind the existing key/cost gate. Do not
extend generative imagery to the foreground, stats, or logo.

## Mathematical asset selection stays deterministic

`media_library/selector.py::score_asset` picks the best photo per card with
fixed weights. Keep it deterministic — see `rules/deterministic-engine.md`.
