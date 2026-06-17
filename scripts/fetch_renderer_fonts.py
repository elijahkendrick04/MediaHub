#!/usr/bin/env python3
"""Self-host the graphic renderer's poster fonts (Council audit 2026-05-31).

The Playwright HTML->PNG renderer (and the card/reel it produces) pulled its
poster families from the Google Fonts CDN — both via the @font-face URLs in
layouts/_shared.css and via an @import in render.py. That left the same EU/UK
GDPR exposure (Munich ruling) on the product's public output, made each render
depend on a network round-trip, AND the version-pinned gstatic URLs hardcoded in
_shared.css had already gone stale (most 404 now) — so the renderer was silently
falling back to non-brand fonts.

This resolves each family's CURRENT latin woff2 from the Google Fonts CSS API by
NAME (not the stale pinned URLs), downloads it into layouts/fonts/, and rewrites
_shared.css so every @font-face uses a local url(fonts/<slug>.woff2). render.py
is edited separately to drop the @import and resolve the relative urls to file://.

Usage (from repo root):
    python scripts/fetch_renderer_fonts.py
"""
from __future__ import annotations
import re, ssl, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts"
SHARED = LAYOUTS / "_shared.css"
FONTS = LAYOUTS / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE

# family name (as written in _shared.css) -> (css2 query, local slug)
#
# G1.9 — the three text/data families that have a genuine variable cut on Google
# Fonts are queried with an axis RANGE (`@<lo>..<hi>`), which makes the CSS2 API
# return the VARIABLE woff2 (one file, all weights + Inter's optical axis)
# instead of a pinned static instance. _shared.css declares them as range faces
# (`font-weight: <lo> <hi>`); tests/test_variable_font_axes.py verifies the
# downloaded files actually carry these axes. The three display faces (Bebas
# Neue, Anton, Bowlby One) have no variable cut, so they stay static.
FAMILIES = {
    "Bebas Neue":    ("Bebas+Neue", "bebas-neue"),
    "Anton":         ("Anton", "anton"),
    "Bowlby One":    ("Bowlby+One", "bowlby-one"),
    "Space Grotesk": ("Space+Grotesk:wght@300..700", "space-grotesk"),
    "Inter":         ("Inter:opsz,wght@14..32,100..900", "inter"),
    "JetBrains Mono": ("JetBrains+Mono:wght@100..800", "jetbrains-mono"),
}
_LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
          "U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
          "U+FEFF, U+FFFD")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=_ctx) as r:
        return r.read()


def _latin_woff2_url(query: str) -> str:
    """Resolve the latin-subset woff2 URL for a css2 family query.

    Google emits one @font-face block per subset, in a stable order; the LAST
    one (no preceding unicode-range comment for cyrillic/greek/vietnamese) is
    `latin`. We pick the block whose preceding comment is `/* latin */`.
    """
    css = _get(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode("utf-8")
    blocks = re.split(r"/\*\s*([\w-]+)\s*\*/", css)
    # blocks = ['', subset1, css1, subset2, css2, ...]
    for i in range(1, len(blocks) - 1, 2):
        if blocks[i] == "latin":
            m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", blocks[i + 1])
            if m:
                return m.group(1)
    # fallback: first woff2 in the whole sheet
    m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css)
    if not m:
        raise SystemExit(f"no woff2 found for query {query!r}")
    return m.group(1)


def main() -> None:
    css = SHARED.read_text(encoding="utf-8")

    # Download each family's current latin woff2 by name.
    for family, (query, slug) in FAMILIES.items():
        url = _latin_woff2_url(query)
        (FONTS / f"{slug}.woff2").write_bytes(_get(url))
        print(f"  {family:14} -> fonts/{slug}.woff2")

    # Rewrite every @font-face block: swap its gstatic src for the local file,
    # keyed by family name (robust to the stale pinned URLs).
    def _rewrite(match: re.Match) -> str:
        block = match.group(0)
        fam = re.search(r"font-family:\s*'([^']+)'", block)
        if not fam or fam.group(1) not in FAMILIES:
            return block
        slug = FAMILIES[fam.group(1)][1]
        return re.sub(
            r"src:\s*url\(https://fonts\.gstatic\.com/[^)]+\.woff2\)\s*format\('woff2'\)",
            f"src: url(fonts/{slug}.woff2) format('woff2')",
            block,
        )

    new_css = re.sub(r"@font-face\s*\{[^}]*\}", _rewrite, css)

    # JetBrains Mono: the layouts reference it but only render.py's old @import
    # provided it. Append self-hosted faces (500 + 700) so dropping the @import
    # is regression-free.
    if "'JetBrains Mono'" not in new_css:
        new_css = new_css.rstrip() + "\n\n" + "\n".join(
            "@font-face {\n"
            "  font-family: 'JetBrains Mono';\n"
            "  font-style: normal;\n"
            f"  font-weight: {w};\n"
            "  font-display: swap;\n"
            "  src: url(fonts/jetbrains-mono.woff2) format('woff2');\n"
            f"  unicode-range: {_LATIN};\n"
            "}"
            for w in ("500", "700")
        ) + "\n"

    SHARED.write_text(new_css, encoding="utf-8")
    assert "gstatic" not in new_css, "gstatic URL still present in _shared.css"
    print(f"\nRewrote _shared.css; {len(list(FONTS.glob('*.woff2')))} local woff2 in {FONTS}")


if __name__ == "__main__":
    main()
