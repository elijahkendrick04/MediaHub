# Self-hosted renderer poster fonts

These `.woff2` files are the **poster typefaces** used by the static graphic
renderer (Playwright HTML→PNG) for the cards/reels MediaHub actually posts —
Bebas Neue, Anton, Bowlby One, Space Grotesk, Inter, JetBrains Mono. They are
served **first-party** (no Google Fonts CDN).

The Council added this on 2026-05-31 (audit round of the typography change): the
web UI had already moved off the CDN, but the *rendered graphic* — the product's
public output — still pulled these poster fonts from `fonts.gstatic.com`. That
left the same EU/UK GDPR exposure on the surface that ships publicly, made each
render depend on a network round-trip, and the version-pinned CDN URLs had
themselves gone stale (most 404ed), so the renderer was silently falling back to
non-brand fonts.

The `@font-face` declarations are in `../_shared.css` with relative
`url(fonts/<name>.woff2)`. The render page is a throwaway `file://`, so
`render.py` rewrites those to absolute `file://` URLs before inlining the CSS.
Same families as before, so `autofit.py` text-fit metrics are unchanged.

## Variable fonts (G1.9)

The three text/data families ship a genuine **variable** `woff2` — one file that
holds every weight continuously, declared in `../_shared.css` over an axis range
(`font-weight: <lo> <hi>`):

| File | Axes |
| --- | --- |
| `inter.woff2` | `wght` 100–900 + `opsz` 14–32 (optical size) |
| `space-grotesk.woff2` | `wght` 300–700 |
| `jetbrains-mono.woff2` | `wght` 100–800 |

This lets the renderer instance any weight continuously (the autofit axis
optimiser, `graphic_renderer.autofit.optimise_axes`, can ask for `'wght' 612`)
rather than snapping to a pinned cut, and Inter's optical axis is tracked to the
rendered size by `font-optical-sizing: auto`. The three display faces (`anton`,
`bebas-neue`, `bowlby-one`) have no variable cut on Google Fonts, so they stay
single static instances. `tests/test_variable_font_axes.py` verifies each
shipped file's real `fvar` axes against the CSS declarations.

## Regenerate

```bash
python scripts/fetch_renderer_fonts.py
```

Resolves each family's current latin `.woff2` from the Google Fonts CSS API **by
name** (not the stale pinned URLs), downloads it here, and rewrites `../_shared.css`
to local URLs. Network needed only to refresh; the committed files are what ship.
