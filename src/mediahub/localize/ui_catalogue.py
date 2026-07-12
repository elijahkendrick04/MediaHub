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
    # Organisation (workspace) vocabulary — kept deliberately distinct from the
    # account "Log in / Log out" so the two never collide (A-5). nav.sign_in is
    # the first org pick; nav.switch_org is swapping between orgs you're in;
    # nav.sign_out leaves the current org (it never ends the account session).
    "nav.sign_in": "Choose organisation",
    "nav.sign_out": "Leave organisation",
    "nav.switch_org": "Switch organisation",
    "nav.notifications": "Notifications",
    # G-10 — the rest of the chrome: top nav, mobile bottom nav, account menu.
    "nav.media_library": "Media library",
    "nav.media": "Media",  # short mobile bottom-nav label
    "nav.activity": "Activity",
    "nav.my_season": "My Season",
    "nav.research": "Research",
    "nav.help": "Help",
    "nav.pricing": "Pricing",
    "nav.billing": "Billing",
    "nav.drafts": "Drafts",
    "nav.club_data": "Club data",
    "nav.log_in": "Log in",
    "nav.log_out": "Log out",
    "nav.sign_up": "Sign up",
    "nav.save_workspace": "Save your workspace",
    "action.approve": "Approve",
    "action.approved": "Approved",  # G-10 — the strap's post-approval state
    "action.reject": "Reject",
    "action.export": "Export",
    "action.download": "Download",
    "action.save": "Save",
    "action.cancel": "Cancel",
    "action.requeue": "Re-queue",
}

# Verified Welsh (cy) — the flagship locale. Only terms confident enough to ship;
# these follow established Welsh software/UI conventions (e.g. gov.wales).
_CY: dict[str, str] = {
    "nav.home": "Hafan",
    "nav.create": "Creu",
    "nav.review": "Adolygu",
    "nav.settings": "Gosodiadau",
    "nav.sign_in": "Dewis sefydliad",
    "nav.sign_out": "Gadael sefydliad",
    "nav.switch_org": "Newid sefydliad",
    "nav.notifications": "Hysbysiadau",
    # G-10 — standard UI Welsh (gov.wales / established software conventions).
    "nav.media_library": "Llyfrgell cyfryngau",
    "nav.media": "Cyfryngau",
    "nav.activity": "Gweithgarwch",
    "nav.my_season": "Fy Nhymor",
    "nav.research": "Ymchwil",
    "nav.help": "Cymorth",
    "nav.pricing": "Prisiau",
    "nav.billing": "Bilio",
    "nav.drafts": "Drafftiau",
    "nav.club_data": "Data'r clwb",
    "nav.log_in": "Mewngofnodi",
    "nav.log_out": "Allgofnodi",
    "nav.sign_up": "Cofrestru",
    "nav.save_workspace": "Cadw eich gweithle",
    "action.approve": "Cymeradwyo",
    "action.approved": "Cymeradwywyd",
    "action.reject": "Gwrthod",
    "action.export": "Allforio",
    "action.download": "Lawrlwytho",
    "action.save": "Cadw",
    "action.cancel": "Canslo",
    "action.requeue": "Yn ôl i'r ciw",
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
