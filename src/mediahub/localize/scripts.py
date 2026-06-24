"""Writing-system metadata per language — the *rendering* side of localisation.

When MediaHub translates a card into another language, the renderer needs to
know three things the caption-writing registry (``web/languages.py``) doesn't
carry: which **script** (writing system) the language uses, whether it lays
out **right-to-left**, and which self-hosted **font family** covers its
glyphs. That's this table.

It is deliberately standalone — pure data, no imports — so the graphic
renderer and the translation engine can pull script/RTL/font facts without
dragging in the Flask app (importing ``web.languages`` pulls in the whole
``web`` package, which loads the monolith). The two tables are kept in lock-step
by ``tests/test_localize_scripts.py``: every caption language must have a script
entry here, and the RTL flags must agree.

Font families:

* Latin scripts reuse the brand display faces already shipped for cards
  (Inter / Anton / Bebas Neue …) — ``font_family`` is left blank, meaning
  "use the layout's own font stack".
* Non-Latin scripts name a self-hosted **Noto** family (SIL Open Font
  Licence — licence-clean, no Google Fonts CDN). The woff2 files and the
  ``@font-face`` wiring are shipped by the renderer build (1.24 Build 3);
  whether a script's font is actually on disk is derived from the filesystem
  there, not flagged here, so this table never goes stale.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptInfo:
    """Script, direction and font-coverage facts for one language."""

    code: str  # ISO 639-1 base code, lowercase ("cy", "ar", "zh")
    script: str  # writing system: latin | cyrillic | arabic | devanagari | bengali | han
    rtl: bool  # right-to-left layout (Arabic, Urdu)
    # CSS font family the renderer should prefer for this script. "" means
    # "use the layout's own (Latin) font stack". A Noto family name means the
    # renderer must have that self-hosted face available, else fall back
    # honestly (see graphic_renderer).
    font_family: str = ""


# One entry per caption language in web/languages.py. base code → ScriptInfo.
# (kept in sync by tests/test_localize_scripts.py)
_SCRIPTS: tuple[ScriptInfo, ...] = (
    ScriptInfo("en", "latin", False, ""),
    ScriptInfo("cy", "latin", False, ""),
    ScriptInfo("ga", "latin", False, ""),
    ScriptInfo("es", "latin", False, ""),
    ScriptInfo("fr", "latin", False, ""),
    ScriptInfo("pt", "latin", False, ""),
    ScriptInfo("ru", "cyrillic", False, "Noto Sans"),
    ScriptInfo("zh", "han", False, "Noto Sans SC"),
    ScriptInfo("hi", "devanagari", False, "Noto Sans Devanagari"),
    ScriptInfo("bn", "bengali", False, "Noto Sans Bengali"),
    ScriptInfo("ar", "arabic", True, "Noto Sans Arabic"),
    ScriptInfo("ur", "arabic", True, "Noto Nastaliq Urdu"),
)

SCRIPTS_BY_CODE: dict[str, ScriptInfo] = {s.code: s for s in _SCRIPTS}

# Latin is the renderer's native script — everything else needs a self-hosted
# non-Latin face to render without system-font fallback.
NON_LATIN_SCRIPTS: frozenset[str] = frozenset(s.script for s in _SCRIPTS if s.script != "latin")


def base_code(code: str | None) -> str:
    """Strip any region/script subtag and lowercase: ``en-GB`` → ``en``.

    Tolerates the common separators (``-`` and ``_``) and stray whitespace.
    Returns ``""`` for empty/None input.
    """
    if not code:
        return ""
    head = str(code).strip().lower().replace("_", "-").split("-", 1)[0]
    return head


def script_for(code: str | None) -> ScriptInfo | None:
    """ScriptInfo for a language code (region subtags ignored). None if unknown."""
    return SCRIPTS_BY_CODE.get(base_code(code))


def is_rtl(code: str | None) -> bool:
    """True if the language lays out right-to-left (Arabic, Urdu)."""
    info = script_for(code)
    return bool(info and info.rtl)


def script_name(code: str | None) -> str:
    """Writing-system name for a code (``"latin"``, ``"arabic"`` …); ``""`` if unknown."""
    info = script_for(code)
    return info.script if info else ""


def font_family_for(code: str | None) -> str:
    """Preferred self-hosted font family for the language's script.

    ``""`` means "use the layout's own (Latin) font stack" — the brand
    display faces already shipped. A non-empty value names a self-hosted Noto
    family the renderer must have available.
    """
    info = script_for(code)
    return info.font_family if info else ""


def is_non_latin(code: str | None) -> bool:
    """True if the language needs a non-Latin font face to render cleanly."""
    info = script_for(code)
    return bool(info and info.script != "latin")


def all_scripts() -> tuple[ScriptInfo, ...]:
    """Every script entry, in registry order."""
    return _SCRIPTS


__all__ = [
    "ScriptInfo",
    "SCRIPTS_BY_CODE",
    "NON_LATIN_SCRIPTS",
    "base_code",
    "script_for",
    "is_rtl",
    "script_name",
    "font_family_for",
    "is_non_latin",
    "all_scripts",
]
