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

## Non-Latin script fonts (1.24 localisation)

When a card is translated into a non-Latin language, the six Latin brand
families above have no glyphs for the script. These self-hosted **Noto** faces
(SIL Open Font Licence — first-party, never the Google Fonts CDN) cover the
scripts the localisation registry needs:

| File | Script | Languages |
| --- | --- | --- |
| `noto-sans-cyrillic.woff2` | Cyrillic | Russian |
| `noto-sans-arabic.woff2` | Arabic | Arabic, Urdu |
| `noto-sans-devanagari.woff2` | Devanagari | Hindi |
| `noto-sans-bengali.woff2` | Bengali | Bengali |

`../_shared.css` declares each as a standalone family (`'Noto Sans Arabic'`…)
**and** registers it as a per-glyph fallback under every brand family via
`unicode-range`, so an Arabic event name inside an Anton headline renders in
Noto with no template change — and English cards never fetch these files (the
`unicode-range` gate means the browser only downloads a face when a glyph in its
range is actually used). The renderer flips text direction for right-to-left
languages (`render_brief(..., language="ar")`).

**CJK (Han) is not shipped:** a usable Han subset is ~10 MB, over the repo's
1.5 MB-per-file hygiene gate, so `zh` falls back to a generic family until an
operator installs a Han face (see `localize/scripts.py`).

## Regenerate

```bash
python scripts/fetch_renderer_fonts.py    # the six Latin brand families
python scripts/fetch_script_fonts.py      # the non-Latin Noto faces (1.24)
```

Each resolves the current `.woff2` from the Google Fonts CSS API **by name**,
downloads it here, and rewrites `../_shared.css` to local URLs. Network needed
only to refresh; the committed files are what ship.
