"""UI string catalogue — MediaHub's own interface internationalisation (1.24).

The customer-facing chrome (nav, primary actions, status words) ships in English
and, where verified, in other languages. This is a CURATED catalogue, not
machine translation: an interface word must read the same way every time, so each
non-English string is a human-verified term — Welsh first, the honest flagship
for the Welsh-club wedge. Anything not in a locale's catalogue falls back to
English, so a partially-translated locale is always coherent, never broken.

This is the *interface* layer. Generated CONTENT (captions, cards) is translated
by the AI engine in :mod:`mediahub.localize.translate`; the two are deliberately
separate — you want "Approve" to be one fixed word, but a caption freshly
written each time.

``t(key, locale)`` is the single lookup. Add a key to the English catalogue and
it exists everywhere (falling back to English); add it to ``cy`` to ship the
verified Welsh. Grown by demand — only chrome that has been needed *and* verified
lives here.
"""

from __future__ import annotations

DEFAULT_UI_LOCALE = "en"

# key -> English source string (the base; also the fallback for every locale).
_EN: dict[str, str] = {
    "nav.home": "Home",
    "nav.create": "Create",
    "nav.review": "Review",
    "nav.settings": "Settings",
    "nav.sign_in": "Sign in",
    "nav.sign_out": "Sign out",
    "nav.switch_org": "Switch organisation",
    "nav.notifications": "Notifications",
    "action.approve": "Approve",
    "action.reject": "Reject",
    "action.export": "Export",
    "action.download": "Download",
    "action.save": "Save",
    "action.cancel": "Cancel",
}

# Verified Welsh (cy) — the flagship locale. Only terms confident enough to ship;
# these follow established Welsh software/UI conventions (e.g. gov.wales).
_CY: dict[str, str] = {
    "nav.home": "Hafan",
    "nav.create": "Creu",
    "nav.review": "Adolygu",
    "nav.settings": "Gosodiadau",
    "nav.sign_in": "Mewngofnodi",
    "nav.sign_out": "Allgofnodi",
    "nav.switch_org": "Newid sefydliad",
    "nav.notifications": "Hysbysiadau",
    "action.approve": "Cymeradwyo",
    "action.reject": "Gwrthod",
    "action.export": "Allforio",
    "action.download": "Lawrlwytho",
    "action.save": "Cadw",
    "action.cancel": "Canslo",
}

UI_STRINGS: dict[str, dict[str, str]] = {
    "en": _EN,
    "cy": _CY,
}


def available_ui_locales() -> tuple[str, ...]:
    """Locales with at least a partial catalogue (English always first)."""
    return tuple(["en"] + sorted(k for k in UI_STRINGS if k != "en"))


def has_ui_locale(locale: str | None) -> bool:
    """True if a (base) locale has a UI catalogue."""
    base = (locale or "").strip().lower().split("-", 1)[0]
    return base in UI_STRINGS


def t(key: str, locale: str | None = None) -> str:
    """Look up a UI string by key for a locale.

    Resolution: the locale's catalogue → English → the key itself (so a missing
    key is visible in dev rather than crashing). ``locale`` may be a full code
    (``cy``, ``en-GB``); only the base subtag is used.
    """
    base = (locale or DEFAULT_UI_LOCALE).strip().lower().split("-", 1)[0]
    cat = UI_STRINGS.get(base) or {}
    if key in cat:
        return cat[key]
    if key in _EN:
        return _EN[key]
    return key


__all__ = [
    "UI_STRINGS",
    "DEFAULT_UI_LOCALE",
    "t",
    "available_ui_locales",
    "has_ui_locale",
]
