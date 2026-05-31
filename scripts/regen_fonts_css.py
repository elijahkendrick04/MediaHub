#!/usr/bin/env python3
"""Regenerate static/theme/fonts.css deterministically from the woff2 files in
static/fonts/ (so the @font-face set is deduplicated and stable).

Council verdict (2026-05-31): the typography problem was DELIVERY, not choice —
the Google Fonts CDN intermittently fell back to Impact/Oswald and is an EU/UK
GDPR liability (Munich ruling). Keep the families; serve them first-party.

Run from the repo root after scripts/fetch_fonts.py:
    python scripts/regen_fonts_css.py

fontTools is used only to compute the metric-tuned fallback overrides; if it is
not installed the script falls back to the precomputed constants below (the same
values fontTools produces for Hanken Grotesk v12), so regeneration never depends
on a non-runtime build dependency.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "mediahub" / "web" / "static"
FONTS = STATIC / "fonts"

PREFIX_FAMILY = {
    "bigshoulders": "Big Shoulders Display",
    "hanken": "Hanken Grotesk",
    "jetbrains": "JetBrains Mono",
    "fraunces": "Fraunces",
}
# Canonical Google Fonts subset unicode-ranges (latin / latin-ext).
URANGE = {
    "latin": ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
              "U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,"
              "U+2212,U+2215,U+FEFF,U+FFFD"),
    "latin-ext": ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,"
                  "U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,"
                  "U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"),
}

# Precomputed Hanken-vs-Arial fallback overrides (fontTools output, Hanken v12:
# unitsPerEm 1000, x-height 500, typo ascender 1000, descender -300, line-gap 0;
# Arial x-height ratio 1062/2048). Used when fontTools/brotli is unavailable so
# regeneration never depends on a non-runtime build dependency.
FALLBACK = {"size_adjust": 95.07, "ascent": 105.18, "descent": 31.87, "gap": 0.00}


def parse(fn: str):
    """<prefix>-<subset>-<style>-<weight>.woff2 -> (prefix, subset, style, weight)."""
    stem = fn[:-len(".woff2")]
    prefix = stem.split("-", 1)[0]
    rest = stem[len(prefix) + 1:]
    subset = "latin-ext" if rest.startswith("latin-ext-") else "latin"
    rest2 = rest[len(subset) + 1:]
    style, weight = rest2.split("-", 1)
    return prefix, subset, style, weight.replace("-", " ")  # "400-900" -> "400 900"


def fallback_overrides():
    """Compute Hanken-vs-Arial metric overrides; precomputed if no fontTools."""
    # fontTools needs the brotli extension to read woff2; either being absent
    # falls back to the precomputed constants, so this build step never adds a
    # runtime dependency. The whole computation is guarded (not just the import).
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(str(FONTS / "hanken-latin-normal-400.woff2"))
        upm = f["head"].unitsPerEm
        os2 = f["OS/2"]
        arial_xh_ratio = 1062 / 2048
        size_adj = (os2.sxHeight / upm) / arial_xh_ratio
        return {
            "size_adjust": round(size_adj * 100, 2),
            "ascent": round(os2.sTypoAscender / upm / size_adj * 100, 2),
            "descent": round(abs(os2.sTypoDescender) / upm / size_adj * 100, 2),
            "gap": round(os2.sTypoLineGap / upm / size_adj * 100, 2),
        }
    except Exception:
        return FALLBACK


def main() -> None:
    order = {"bigshoulders": 0, "fraunces": 1, "hanken": 2, "jetbrains": 3}
    faces = []
    for p in sorted(FONTS.glob("*.woff2")):
        prefix, subset, style, weight = parse(p.name)
        faces.append((order.get(prefix, 9), 0 if subset == "latin" else 1,
                      style, weight, prefix, subset, p.name))
    faces.sort()

    out = [
        "/* =====================================================================",
        "   FONTS — self-hosted (Council verdict 2026-05-31)",
        "   First-party woff2; NO Google Fonts CDN (reliability + EU/UK GDPR: the",
        "   Munich ruling makes CDN-served Google Fonts a data-transfer liability,",
        "   and a blocked/slow CDN dropped users onto the Impact/Oswald fallback).",
        "   Same families as before — Big Shoulders Display, Fraunces (VARIABLE,",
        "   opsz 9-144, so optical sizing survives), Hanken Grotesk, JetBrains Mono",
        "   — latin + latin-ext subsets, used weights only.",
        "   Regenerate: python scripts/regen_fonts_css.py",
        "   ===================================================================== */",
        "",
    ]
    for _o, _s, style, weight, prefix, subset, fname in faces:
        out += [
            "@font-face {",
            f"  font-family: '{PREFIX_FAMILY[prefix]}';",
            f"  font-style: {style};",
            f"  font-weight: {weight};",
            "  font-display: swap;",
            f"  src: url(../fonts/{fname}) format('woff2');",
            f"  unicode-range: {URANGE[subset]};",
            "}",
            "",
        ]

    fb = fallback_overrides()
    out += [
        "/* Metric-tuned fallback: Arial scaled to Hanken's box so the load swap",
        "   produces no layout shift (the real fix for \"the fonts look changed\").",
        "   Used as the next stack entry after Hanken in --font-body. */",
        "@font-face {",
        "  font-family: 'Hanken Grotesk Fallback';",
        "  src: local('Arial');",
        f"  size-adjust: {fb['size_adjust']:.2f}%;",
        f"  ascent-override: {fb['ascent']:.2f}%;",
        f"  descent-override: {fb['descent']:.2f}%;",
        f"  line-gap-override: {fb['gap']:.2f}%;",
        "}",
        "",
    ]

    (STATIC / "theme" / "fonts.css").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote fonts.css: {len(faces)} @font-face faces + 1 fallback; "
          f"{len(list(FONTS.glob('*.woff2')))} woff2 on disk")


if __name__ == "__main__":
    main()
