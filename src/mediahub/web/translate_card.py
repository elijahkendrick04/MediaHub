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

__all__ = ["translate_card_slots", "ClaudeUnavailableError", "CARD_SLOT_BUDGETS"]

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
