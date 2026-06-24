"""``localize`` — MediaHub's own localisation layer (roadmap 1.24).

Turn one piece of approved content into the same content in another language,
the right way for a sports club: protected sporting terms survive, names and
times are untouched, the result is length-aware so the card still lays out, and
nothing is faked when no AI provider is configured.

Three pieces:

* :mod:`~mediahub.localize.translate` — the provider-backed translation engine
  (glossary-constrained, length-budgeted, honest-erroring). ``translate_slots``
  does a whole card in one call.
* :mod:`~mediahub.localize.glossary` — the per-sport protected vocabulary and
  the deterministic post-check that the AI respected it.
* :mod:`~mediahub.localize.scripts` — writing-system / direction / font-coverage
  metadata the renderer needs to lay out non-Latin and right-to-left languages.

The caption-language registry (which languages exist, their names, the
per-language caption-prompt notes) stays in ``web/languages.py`` — this package
is the *translation + rendering* side and reuses that registry for language
names.
"""

from __future__ import annotations

from .glossary import (
    SPORT_GLOSSARIES,
    GlossaryTerm,
    check_protected,
    glossary_for,
    glossary_prompt,
    protected_terms,
)
from .scripts import (
    ScriptInfo,
    base_code,
    font_family_for,
    is_non_latin,
    is_rtl,
    script_for,
    script_name,
)
from .translate import (
    ClaudeUnavailableError,
    TranslationResult,
    available,
    parse_locale,
    translate_slots,
    translate_text,
)

__all__ = [
    # translate
    "TranslationResult",
    "ClaudeUnavailableError",
    "available",
    "translate_slots",
    "translate_text",
    "parse_locale",
    # glossary
    "GlossaryTerm",
    "SPORT_GLOSSARIES",
    "glossary_for",
    "glossary_prompt",
    "protected_terms",
    "check_protected",
    # scripts
    "ScriptInfo",
    "base_code",
    "script_for",
    "script_name",
    "is_rtl",
    "is_non_latin",
    "font_family_for",
]
