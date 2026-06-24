"""Translate a review card's text into another language (roadmap 1.24).

Thin web-facing adapter over :mod:`mediahub.localize`. It takes the text slots
the approver is looking at (caption, alt text, headline …), translates them in
one provider call through the glossary-constrained engine, and shapes the result
into a variant dict that:

* the ``/translate`` route returns to the review UI (to show the bilingual pair),
* the workflow store persists on the card (so the pair rides into approval/export).

Honest-erroring: when no provider is configured the underlying engine raises
``ClaudeUnavailableError`` and we let it propagate — the route turns it into an
honest 503, never a fake translation.
"""

from __future__ import annotations

from typing import Optional

from mediahub.localize import base_code, translate_slots
from mediahub.localize.translate import ClaudeUnavailableError

__all__ = [
    "translate_card_slots",
    "translate_card_labels",
    "CARD_LABEL_SLOTS",
    "ClaudeUnavailableError",
    "CARD_SLOT_BUDGETS",
]

# The painted-card text layers that carry DESCRIPTIVE labels — these are
# translated when re-rendering a card graphic in another language. Everything
# else a card paints (athlete names, recorded times, result digits, place) is
# kept verbatim, so it is deliberately NOT listed here.
CARD_LABEL_SLOTS = ("event_name", "achievement_label")

# Soft per-slot character budgets for the slots a card carries. The renderer's
# autofit absorbs overflow; these just nudge the model and flag a slot that blew
# past (e.g. a caption that won't fit a story panel). Unknown slots are
# unbudgeted.
CARD_SLOT_BUDGETS: dict[str, int] = {
    "caption": 2200,  # Instagram hard limit; most clubs sit well under
    "alt_text": 200,  # matches the alt-text input maxlength in review
    "headline": 60,
    "subhead": 90,
}


def _language_label(code: str) -> str:
    """Reader-facing label for a language: the native name where we know it."""
    try:
        from mediahub.web.languages import get_language

        lang = get_language(base_code(code))
        if lang is not None:
            return lang.native_name
    except Exception:
        pass
    return code or ""


def translate_card_slots(
    slots: dict[str, str],
    target_language: str,
    *,
    sport: str = "swimming",
    source_language: str = "en",
    length_budgets: Optional[dict[str, int]] = None,
) -> dict:
    """Translate the given card slots into ``target_language``.

    Returns a JSON-serialisable variant dict::

        {
          "language": "cy", "language_base": "cy", "language_label": "Cymraeg",
          "rtl": False, "script": "latin", "regional_only": False,
          "slots": {"caption": "...", "alt_text": "..."},
          "provider": "gemini-api", "warnings": [...],
        }

    Raises ``ClaudeUnavailableError`` when no provider is configured.
    """
    budgets = dict(CARD_SLOT_BUDGETS)
    if length_budgets:
        budgets.update(length_budgets)
    # Only budget slots we were actually given.
    budgets = {k: v for k, v in budgets.items() if k in (slots or {})}

    res = translate_slots(
        slots,
        target_language,
        sport=sport,
        source_language=source_language,
        length_budgets=budgets or None,
    )
    return {
        "language": res.target_language,
        "language_base": base_code(res.target_language),
        "language_label": _language_label(res.target_language),
        "rtl": res.rtl,
        "script": res.script,
        "regional_only": res.regional_only,
        "slots": res.slots,
        "provider": res.provider,
        "warnings": res.warnings,
    }


def translate_card_labels(
    text_layers: dict,
    target_language: str,
    *,
    sport: str = "swimming",
    source_language: str = "en",
) -> dict:
    """Translate a brief's painted *labels* for a layout-aware re-render (1.24).

    Returns a copy of ``text_layers`` with the descriptive label slots
    (``event_name``, ``achievement_label``) translated; names, recorded times,
    result digits and place are preserved verbatim. The caller renders the
    resulting brief with ``render_brief(..., language=target_language)`` so the
    re-rendered card carries RTL/script handling and autofit absorbs the
    translated text's length. No-op (no provider call) when there are no
    translatable labels. Raises ``ClaudeUnavailableError`` when no provider is
    configured.
    """
    layers = dict(text_layers or {})
    to_translate = {
        k: layers[k]
        for k in CARD_LABEL_SLOTS
        if isinstance(layers.get(k), str) and layers[k].strip()
    }
    if not to_translate:
        return layers
    res = translate_slots(
        to_translate,
        target_language,
        sport=sport,
        source_language=source_language,
    )
    layers.update(res.slots)
    return layers
