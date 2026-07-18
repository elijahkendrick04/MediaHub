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

# script slug -> per-script config. Each carries BOTH a regular (400) cut and a
# heavy DISPLAY cut (D9, Canva gap analysis): a non-Latin hero name aliased to a
# condensed display face (Anton/Bebas/Bowlby) used to fall back to Noto Sans 400,
# flattening the very weight/width contrast that defines the card. We now
# self-host the heavy cut (Black 900 where the family carries it, else Bold 700)
# and alias THAT under the display family names, keeping the 400 cut under the
# body/data families. Fields:
#   query_400     — css2 family+weight query for the regular cut
#   query_display — css2 family+weight query for the heavy display cut
#   subset        — gstatic subset name to pick out of the css2 response
#   slug_400      — regular woff2 filename stem
#   slug_display  — heavy woff2 filename stem
#   family        — the standalone family name (selectable directly)
#   urange        — the unicode-range this script covers
SCRIPTS = {
    "cyrillic": {
        "query_400": "Noto+Sans:wght@400",
        "query_display": "Noto+Sans:wght@900",
        "subset": "cyrillic",
        "slug_400": "noto-sans-cyrillic",
        "slug_display": "noto-sans-cyrillic-black",
        "family": "Noto Sans",
        "urange": "U+0400-04FF, U+0500-052F, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
    },
    "arabic": {
        "query_400": "Noto+Sans+Arabic:wght@400",
        "query_display": "Noto+Sans+Arabic:wght@700",
        "subset": "arabic",
        "slug_400": "noto-sans-arabic",
        "slug_display": "noto-sans-arabic-bold",
        "family": "Noto Sans Arabic",
        "urange": "U+0600-06FF, U+0750-077F, U+0870-088E, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF",
    },
    "devanagari": {
        "query_400": "Noto+Sans+Devanagari:wght@400",
        "query_display": "Noto+Sans+Devanagari:wght@700",
        "subset": "devanagari",
        "slug_400": "noto-sans-devanagari",
        "slug_display": "noto-sans-devanagari-bold",
        "family": "Noto Sans Devanagari",
        "urange": "U+0900-097F, U+1CD0-1CFF, U+A830-A839, U+A8E0-A8FF",
    },
    "bengali": {
        "query_400": "Noto+Sans+Bengali:wght@400",
        "query_display": "Noto+Sans+Bengali:wght@700",
        "subset": "bengali",
        "slug_400": "noto-sans-bengali",
        "slug_display": "noto-sans-bengali-bold",
        "family": "Noto Sans Bengali",
        "urange": "U+0980-09FF, U+1CD0-1CF9, U+200C-200D, U+20B9",
    },
}

# The three heavy DISPLAY brand families — a non-Latin glyph in one of these
# aliases to the heavy Noto cut so a Cyrillic/Arabic/… hero keeps its poster
# weight. The three BODY/DATA families keep the regular Noto 400 cut (their
# Latin registers are book weight, so a 400 non-Latin fallback is correct).
DISPLAY_FAMILIES = ("Bebas Neue", "Anton", "Bowlby One")
BODY_FAMILIES = ("Space Grotesk", "Inter", "JetBrains Mono")


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
    # Standalone families (Noto Sans, Noto Sans Arabic, …), selectable directly
    # by the renderer — always the regular 400 cut.
    for cfg in SCRIPTS.values():
        lines.append(_face(cfg["family"], cfg["slug_400"], cfg["urange"]))
    # Per-glyph fallback: each brand family falls back to the right Noto face for
    # every non-Latin range so translated text in a brand-styled element renders
    # with no template change. D9: the heavy DISPLAY families alias the Black/Bold
    # cut (poster weight preserved across scripts); the BODY families keep 400.
    for brand in DISPLAY_FAMILIES:
        for cfg in SCRIPTS.values():
            lines.append(_face(brand, cfg["slug_display"], cfg["urange"]))
    for brand in BODY_FAMILIES:
        for cfg in SCRIPTS.values():
            lines.append(_face(brand, cfg["slug_400"], cfg["urange"]))
    lines.append(_MARK_END)
    return "\n".join(lines)


def _fetch(query: str, subset: str, slug: str) -> None:
    """Download one subset woff2 to ``fonts/<slug>.woff2`` if not already present.

    Skip-if-exists keeps the committed regular cuts byte-stable across re-runs
    (Google may re-subset over time) while still fetching any newly-added cut.
    """
    dest = FONTS / f"{slug}.woff2"
    if dest.exists():
        print(f"  (have)  fonts/{slug}.woff2")
        return
    url = _subset_woff2_url(query, subset)
    dest.write_bytes(_get(url))
    print(f"  fetched fonts/{slug}.woff2")


def main() -> None:
    for cfg in SCRIPTS.values():
        _fetch(cfg["query_400"], cfg["subset"], cfg["slug_400"])
        _fetch(cfg["query_display"], cfg["subset"], cfg["slug_display"])

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
