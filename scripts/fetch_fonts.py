#!/usr/bin/env python3
"""Download the four MediaHub typefaces from Google Fonts for self-hosting.

Council verdict (2026-05-31): keep the families, serve them first-party (the
Google Fonts CDN intermittently fell back to Impact/Oswald and is an EU/UK GDPR
liability — the Munich ruling). This fetches only the latin + latin-ext subsets,
only the weights actually used, with Fraunces as the VARIABLE font (opsz 9-144,
so optical sizing survives), into src/mediahub/web/static/fonts/.

Usage (from repo root):
    python scripts/fetch_fonts.py        # download the woff2
    python scripts/regen_fonts_css.py    # (re)build static/theme/fonts.css

The woff2 files and fonts.css are committed; only re-run to refresh a family or
add a weight.
"""
from __future__ import annotations
import re, ssl, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "src" / "mediahub" / "web" / "static" / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE


def _get(url: str, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=_ctx) as r:
        return r.read() if binary else r.read().decode("utf-8")


KEEP_SUBSETS = {"latin", "latin-ext"}
# css2 query -> file-prefix. Fraunces requests axis RANGES → variable woff2.
SPECS = {
    "Big+Shoulders+Display:wght@600;700;800;900": "bigshoulders",
    "Hanken+Grotesk:wght@300;400;500;600;700;800": "hanken",
    "JetBrains+Mono:wght@400;500;600;700": "jetbrains",
    "Fraunces:ital,opsz,wght@0,9..144,400..900;1,9..144,400..900": "fraunces",
}
BLOCK_RE = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", re.S)


def _field(block, name):
    m = re.search(rf"{name}:\s*([^;]+);", block)
    return m.group(1).strip() if m else ""


def main() -> None:
    seen: set[str] = set()
    n = 0
    for query, prefix in SPECS.items():
        css = _get(f"https://fonts.googleapis.com/css2?family={query}&display=swap")
        for subset, block in BLOCK_RE.findall(css):
            if subset not in KEEP_SUBSETS:
                continue
            style = _field(block, "font-style") or "normal"
            weight = (_field(block, "font-weight") or "400").replace(" ", "-")
            m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", block)
            if not m:
                continue
            fname = f"{prefix}-{subset}-{style}-{weight}.woff2"
            if fname in seen:          # css2 can repeat a subset block; dedupe
                continue
            seen.add(fname)
            (FONTS / fname).write_bytes(_get(m.group(1), binary=True))
            n += 1
            print(f"  {prefix:13} {subset:9} {style:7} {weight:9} -> {fname}")
    print(f"\nDownloaded {n} woff2 into {FONTS}.\nNow run: python scripts/regen_fonts_css.py")


if __name__ == "__main__":
    main()
