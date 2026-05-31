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

## Regenerate

```bash
python scripts/fetch_renderer_fonts.py
```

Resolves each family's current latin `.woff2` from the Google Fonts CSS API **by
name** (not the stale pinned URLs), downloads it here, and rewrites `../_shared.css`
to local URLs. Network needed only to refresh; the committed files are what ship.
