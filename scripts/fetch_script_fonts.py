#!/usr/bin/env python3
"""Self-host the non-Latin script fonts for localisation (roadmap 1.24).

The renderer's six brand families are Latin-only. When a card is translated into
a non-Latin language (Welsh/EU markets are Latin, but Russian, Arabic, Urdu,
Hindi and Bengali are not), those families have no glyphs for the script, so the
text would fall back to whatever the container happens to have — tofu boxes on a
clean server. This self-hosts a Noto face per script (SIL Open Font Licence —
licence-clean, NEVER the Google Fonts CDN at render time) and wires _shared.css
so:

* each script has a standalone family ('Noto Sans Arabic', …) the renderer can
  select explicitly, AND
* every brand family gains a per-glyph fallback to the right Noto face via the
  CSS ``unicode-range`` mechanism (the same trick the Latin faces already use) —
  so an Arabic event name in an Anton headline renders in Noto Sans Arabic with
  NO template change.

The woff2 are fetched from the Google Fonts CSS API by NAME at build time and
committed (each is small — Google already subsets per script). CJK (Han) is
deliberately NOT shipped: a usable Han subset is ~10 MB, over the repo's
1.5 MB-per-file hygiene gate, so zh falls back honestly to a generic family
(see localize/scripts.py) until an operator installs a Han face.

Usage (from repo root):
    python scripts/fetch_script_fonts.py
"""

from __future__ import annotations

import re
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts"
SHARED = LAYOUTS / "_shared.css"
FONTS = LAYOUTS / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

_MARK_START = "/* === non-Latin script fonts (1.24 localisation) — generated === */"
_MARK_END = "/* === end non-Latin script fonts === */"

# script slug -> (css2 family query, gstatic subset name, woff2 slug,
#                 standalone family name, unicode-range)
SCRIPTS = {
    "cyrillic": (
        "Noto+Sans:wght@400",
        "cyrillic",
        "noto-sans-cyrillic",
        "Noto Sans",
        "U+0400-04FF, U+0500-052F, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
    ),
    "arabic": (
        "Noto+Sans+Arabic:wght@400",
        "arabic",
        "noto-sans-arabic",
        "Noto Sans Arabic",
        "U+0600-06FF, U+0750-077F, U+0870-088E, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF",
    ),
    "devanagari": (
        "Noto+Sans+Devanagari:wght@400",
        "devanagari",
        "noto-sans-devanagari",
        "Noto Sans Devanagari",
        "U+0900-097F, U+1CD0-1CFF, U+A830-A839, U+A8E0-A8FF",
    ),
    "bengali": (
        "Noto+Sans+Bengali:wght@400",
        "bengali",
        "noto-sans-bengali",
        "Noto Sans Bengali",
        "U+0980-09FF, U+1CD0-1CF9, U+200C-200D, U+20B9",
    ),
}

# The six Latin brand families that should gain a per-glyph non-Latin fallback.
BRAND_FAMILIES = (
    "Bebas Neue",
    "Anton",
    "Bowlby One",
    "Space Grotesk",
    "Inter",
    "JetBrains Mono",
)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40, context=_ctx) as r:
        return r.read()


def _subset_woff2_url(query: str, subset: str) -> str:
    css = _get(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode("utf-8")
    blocks = re.split(r"/\*\s*([\w-]+)\s*\*/", css)
    for i in range(1, len(blocks) - 1, 2):
        if blocks[i] == subset:
            m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", blocks[i + 1])
            if m:
                return m.group(1)
    m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css)
    if not m:
        raise SystemExit(f"no woff2 found for query {query!r} subset {subset!r}")
    return m.group(1)


def _face(family: str, slug: str, urange: str) -> str:
    # Single `font-weight: 400` (NOT a range): the standalone families and the
    # per-glyph fallback faces follow Google Fonts' own multi-subset pattern —
    # same family, SAME single weight, different unicode-range. Mixing a weight
    # range here with the display faces' single `400` breaks Chromium's face
    # selection so even the Latin face stops loading (regression caught by
    # tests/test_renderer_fonts.py).
    return (
        "@font-face {\n"
        f"  font-family: '{family}';\n"
        "  font-style: normal;\n"
        "  font-weight: 400;\n"
        "  font-display: swap;\n"
        f"  src: url(fonts/{slug}.woff2) format('woff2');\n"
        f"  unicode-range: {urange};\n"
        "}"
    )


def build_block() -> str:
    """The full marked @font-face block (standalone families + brand fallbacks)."""
    lines = [_MARK_START]
    # Standalone families, selectable directly by the renderer.
    for _slug, (_q, _sub, woff_slug, family, urange) in SCRIPTS.items():
        lines.append(_face(family, woff_slug, urange))
    # Per-glyph fallback: every brand family falls back to the right Noto face
    # for each non-Latin range, so translated text in a brand-styled element
    # renders correctly with no template change.
    for brand in BRAND_FAMILIES:
        for _slug, (_q, _sub, woff_slug, _family, urange) in SCRIPTS.items():
            lines.append(_face(brand, woff_slug, urange))
    lines.append(_MARK_END)
    return "\n".join(lines)


def main() -> None:
    for _slug, (query, subset, woff_slug, family, _urange) in SCRIPTS.items():
        url = _subset_woff2_url(query, subset)
        (FONTS / f"{woff_slug}.woff2").write_bytes(_get(url))
        print(f"  {family:22} -> fonts/{woff_slug}.woff2")

    css = SHARED.read_text(encoding="utf-8")
    block = build_block()
    if _MARK_START in css and _MARK_END in css:
        css = re.sub(
            re.escape(_MARK_START) + r".*?" + re.escape(_MARK_END),
            block,
            css,
            flags=re.DOTALL,
        )
    else:
        css = css.rstrip() + "\n\n" + block + "\n"
    SHARED.write_text(css, encoding="utf-8")
    assert "gstatic" not in css, "gstatic URL leaked into _shared.css"
    print(f"\nWired {len(SCRIPTS)} script fonts into _shared.css")


if __name__ == "__main__":
    main()
