"""video/caption_fonts.py — real self-hosted fonts for libass caption burns (M28).

The ASS caption/title documents name brand families ("Inter" et al), but the
repo self-hosts its six brand typefaces as **woff2** only — a format libass
(via fontconfig/freetype) cannot load — so on a clean deployment libass would
silently substitute whatever default face fontconfig finds: a brand-exactness
violation on every burned caption.

This module makes the named family REAL for libass:

1. **Deterministic woff2 → ttf conversion at first use** via ``fontTools``
   (already a pinned dependency — ``fonttools[woff]`` in requirements.txt, so
   brotli is present). Same woff2 in → same ttf out, cached under
   ``DATA_DIR/fonts_ttf/`` so conversion happens once per deployment.
2. **A generated ``fonts.conf``** pointing fontconfig at exactly that ttf
   directory; the render passes it as ``FONTCONFIG_FILE`` so libass resolves
   "Inter" to the repo's own Inter and nothing else.

Honest by construction: when conversion is impossible (fontTools/brotli
missing, woff2 sources absent) :func:`ensure_caption_fonts` raises
:class:`CaptionFontsUnavailable` with the exact missing piece — the caller
surfaces a caption render error naming the missing font support rather than
silently burning captions in a wrong face.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class CaptionFontsUnavailable(RuntimeError):
    """Raised when the self-hosted caption fonts cannot be provisioned."""


# The six self-hosted brand families → their woff2 files (the still renderer's
# copies are the canonical bytes; remotion/public/fonts/ is byte-identical).
_FONTS_SRC_DIR = Path(__file__).resolve().parents[1] / "graphic_renderer" / "layouts" / "fonts"

SELF_HOSTED_FAMILIES: dict[str, str] = {
    "Bebas Neue": "bebas-neue.woff2",
    "Anton": "anton.woff2",
    "Bowlby One": "bowlby-one.woff2",
    "Space Grotesk": "space-grotesk.woff2",
    "Inter": "inter.woff2",
    "JetBrains Mono": "jetbrains-mono.woff2",
}

# The family every ASS style names today. One of the six — guarded by test.
DEFAULT_CAPTION_FAMILY = "Inter"


def ass_font_family(requested: str = "") -> str:
    """The ASS style family to burn with — always one of the six.

    An unknown/empty request falls back to the default rather than letting an
    arbitrary family string reach libass (which would silently substitute).
    """
    name = str(requested or "").strip()
    return name if name in SELF_HOSTED_FAMILIES else DEFAULT_CAPTION_FAMILY


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def ttf_dir() -> Path:
    d = _data_dir() / "fonts_ttf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_ttf(family: str) -> Path:
    """The cached ttf for ``family``, converting from the repo woff2 on first use.

    Deterministic: ``fontTools`` re-flavours the woff2 container to plain ttf —
    the glyph tables are byte-preserved, no rasterisation, no network. Raises
    :class:`CaptionFontsUnavailable` naming the missing piece on any gap.
    """
    src_name = SELF_HOSTED_FAMILIES.get(family)
    if not src_name:
        raise CaptionFontsUnavailable(
            f"{family!r} is not one of the six self-hosted families "
            f"({', '.join(sorted(SELF_HOSTED_FAMILIES))})."
        )
    src = _FONTS_SRC_DIR / src_name
    if not src.exists():
        raise CaptionFontsUnavailable(
            f"Self-hosted font file missing: {src} — run scripts/fetch_renderer_fonts.py."
        )
    out = ttf_dir() / (Path(src_name).stem + ".ttf")
    try:
        if out.exists() and out.stat().st_size > 0 and out.stat().st_mtime >= src.stat().st_mtime:
            return out
    except OSError:
        pass
    try:
        from fontTools.ttLib import TTFont
    except Exception as e:  # pragma: no cover - fonttools is a pinned dep
        raise CaptionFontsUnavailable(
            "Converting the self-hosted woff2 fonts for libass needs the "
            "'fonttools' package (pip install 'fonttools[woff]')."
        ) from e
    try:
        font = TTFont(str(src))
        font.flavor = None  # woff2 container → plain ttf, tables preserved
        tmp = out.with_name(out.name + ".part")
        font.save(str(tmp))
        tmp.replace(out)
    except Exception as e:
        raise CaptionFontsUnavailable(
            f"Could not convert {src.name} to ttf for libass "
            f"(is the 'brotli' woff2 codec installed?): {e}"
        ) from e
    return out


def fontconfig_file() -> Path:
    """Generate (once) the fonts.conf that scopes fontconfig to the ttf dir."""
    d = ttf_dir()
    conf = d / "fonts.conf"
    cache = d / "fc-cache"
    cache.mkdir(parents=True, exist_ok=True)
    content = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        f"  <dir>{d}</dir>\n"
        f"  <cachedir>{cache}</cachedir>\n"
        "</fontconfig>\n"
    )
    try:
        if not conf.exists() or conf.read_text(encoding="utf-8") != content:
            conf.write_text(content, encoding="utf-8")
    except OSError as e:
        raise CaptionFontsUnavailable(f"Could not write fonts.conf under DATA_DIR: {e}") from e
    return conf


def ensure_caption_fonts() -> dict[str, str]:
    """Provision every self-hosted family as ttf and return the render env.

    Returns ``{"FONTCONFIG_FILE": <path>}`` for the FFmpeg subprocess that
    burns ASS documents, guaranteeing libass resolves the six families to the
    repo's own bytes. Raises :class:`CaptionFontsUnavailable` (honest,
    actionable) when any piece is missing — never a silent wrong-font burn.
    """
    for family in SELF_HOSTED_FAMILIES:
        ensure_ttf(family)
    return {"FONTCONFIG_FILE": str(fontconfig_file())}


__all__ = [
    "CaptionFontsUnavailable",
    "SELF_HOSTED_FAMILIES",
    "DEFAULT_CAPTION_FAMILY",
    "ass_font_family",
    "ensure_ttf",
    "fontconfig_file",
    "ensure_caption_fonts",
]
