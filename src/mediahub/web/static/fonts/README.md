# Self-hosted web fonts

These `.woff2` files are the MediaHub web UI typefaces, served **first-party**
(not from the Google Fonts CDN). The Council decided this on 2026-05-31 because
the CDN intermittently dropped users onto the Impact/Oswald fallback (what the
page looked like when `fonts.gstatic.com` was blocked or slow) and because
CDN-served Google Fonts transmit EU/UK visitor IPs to Google — a GDPR liability
(the Munich ruling) for the clubs MediaHub serves.

Same four families as before:

- **Big Shoulders Display** — condensed athletic headlines
- **Fraunces** — editorial serif accents (the variable font, so optical sizing
  `opsz 9–144` and italics are preserved)
- **Hanken Grotesk** — body / UI
- **JetBrains Mono** — scoreboard times & numbers

`latin` + `latin-ext` subsets, used weights only. The `@font-face` rules live in
`../theme/fonts.css` (which also defines a metric-tuned `Hanken Grotesk Fallback`
so the load swap causes no layout shift). `web.py`'s `<head>` preloads the two
above-the-fold faces and links `theme/fonts.css`.

## Regenerate

```bash
python scripts/fetch_fonts.py        # download the woff2 from Google Fonts
python scripts/regen_fonts_css.py    # rebuild ../theme/fonts.css
```

`fetch_fonts.py` needs network; `regen_fonts_css.py` uses `fontTools`+`brotli`
to compute the fallback metrics if available, else bakes in the precomputed
values — so neither is a runtime dependency. The committed `.woff2` + `fonts.css`
are what ship.
