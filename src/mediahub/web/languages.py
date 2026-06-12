"""Caption language registry — the single source of truth for every
language MediaHub can write captions in.

Grew out of W.13 (bilingual Welsh captions). The registry now carries the
top-10 world languages by total speakers (Ethnologue: English, Mandarin
Chinese, Hindi, Spanish, French, Arabic, Bengali, Portuguese, Russian,
Urdu) plus the two Celtic community languages the wedge market asked for
(Welsh, Irish). Every surface that touches caption language — the
/organisation settings picker, ``ClubProfile.language`` validation, the
caption-prompt instructions in ``ai_caption``, and the review-UI display
labels — derives from ``SUPPORTED_LANGUAGES``. Adding a ``Language``
entry here is the ONLY change needed to offer a new language end-to-end;
every current and future caption surface picks it up through the helpers
below.

``ClubProfile.language`` setting values:

  "en", "cy", "ga", "zh", …   write captions in that one language
  "en+cy", "en+zh", …          bilingual — English caption plus a
                               side-by-side translation in the second
                               language, both from the same provider call
  "bilingual" (legacy W.13)    pre-registry spelling of "en+cy"; it is
                               normalised on every read and rewritten on
                               the next save

Translation itself is always done by the configured LLM provider
(Gemini-first via ai_core) per the standing AI rule — the registry holds
per-language prompt guidance only, never canned translations, and a
missing provider stays an honest ``ClaudeUnavailableError``.

Kept as Python data (like ``web/_countries.py``) so the data travels
with the source and imports have zero I/O cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1 code, lowercase ("cy", "ga", "zh", …)
    name: str  # English name shown to operators ("Welsh")
    native_name: str  # endonym shown to readers ("Cymraeg")
    rtl: bool = False  # right-to-left script (Arabic, Urdu)
    # Curated, language-specific prompt guidance appended to the generic
    # instruction — e.g. verified Welsh swimming terminology. Leave ""
    # unless the terms are verified: a wrong term baked into the prompt
    # is worse than letting the model pick the natural one.
    prompt_notes: str = ""


SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", "English"),
    Language(
        "cy",
        "Welsh",
        "Cymraeg",
        prompt_notes=(
            "Swimming terminology correct (e.g. dull rhydd = freestyle, "
            "dull cefn = backstroke, dull broga = breaststroke, dull "
            "pili-pala = butterfly, record personol = personal best)."
        ),
    ),
    Language("ga", "Irish", "Gaeilge"),
    Language("zh", "Mandarin Chinese", "中文"),
    Language("hi", "Hindi", "हिन्दी"),
    Language("es", "Spanish", "Español"),
    Language("fr", "French", "Français"),
    Language("ar", "Arabic", "العربية", rtl=True),
    Language("bn", "Bengali", "বাংলা"),
    Language("pt", "Portuguese", "Português"),
    Language("ru", "Russian", "Русский"),
    Language("ur", "Urdu", "اردو", rtl=True),
)

LANGUAGES_BY_CODE: dict[str, Language] = {lang.code: lang for lang in SUPPORTED_LANGUAGES}

DEFAULT_LANGUAGE = "en"

# Legacy W.13 value — the only pre-registry spelling that ever shipped.
_LEGACY_ALIASES = {"bilingual": "en+cy"}


def get_language(code: Optional[str]) -> Optional[Language]:
    """Look up one language by ISO code. None for unknown/empty codes."""
    return LANGUAGES_BY_CODE.get((code or "").strip().lower())


def normalise_language_setting(value: Optional[str]) -> str:
    """Collapse any stored or submitted language setting to canonical form.

    Unknown or empty values fall back to "en" (the same fail-safe the
    original W.13 validator had), legacy "bilingual" becomes "en+cy", and
    a pair whose halves match ("en+en") collapses to the single language.
    """
    v = (value or "").strip().lower()
    if not v:
        return DEFAULT_LANGUAGE
    v = _LEGACY_ALIASES.get(v, v)
    if "+" in v:
        primary, _, secondary = v.partition("+")
        primary, secondary = primary.strip(), secondary.strip()
        if get_language(primary) is None or get_language(secondary) is None:
            return DEFAULT_LANGUAGE
        if primary == secondary:
            return primary
        return f"{primary}+{secondary}"
    return v if get_language(v) else DEFAULT_LANGUAGE


def split_language_setting(value: Optional[str]) -> tuple[str, Optional[str]]:
    """Return (primary_code, secondary_code | None) for any setting value."""
    setting = normalise_language_setting(value)
    if "+" in setting:
        primary, _, secondary = setting.partition("+")
        return primary, secondary
    return setting, None


def _profile_language(profile) -> str:
    """Raw language setting from a ClubProfile-like object or dict."""
    if profile is None:
        return DEFAULT_LANGUAGE
    if isinstance(profile, dict):
        return profile.get("language") or DEFAULT_LANGUAGE
    return getattr(profile, "language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE


def language_setting_for(profile) -> str:
    """Normalised ``ClubProfile.language`` setting for an object/dict."""
    return normalise_language_setting(_profile_language(profile))


def primary_language_for(profile) -> str:
    """Primary caption language code for a ClubProfile-like object/dict."""
    return split_language_setting(_profile_language(profile))[0]


def secondary_language_for(profile) -> Optional[str]:
    """Side-by-side translation language code, or None when monolingual."""
    return split_language_setting(_profile_language(profile))[1]


def caption_language_instruction(code: str) -> str:
    """System-prompt line that makes the model write its output in this
    language. Returns "" for English (prompts are already English-first)
    and for unknown codes, so callers can append unconditionally."""
    lang = get_language(code)
    if lang is None or lang.code == DEFAULT_LANGUAGE:
        return ""
    parts = [
        f"Write everything you produce — the caption, and the alt text "
        f"when asked for one — in natural {lang.name} ({lang.native_name}): "
        "native-speaker fluency in the language's own sporting register, "
        "never a word-for-word translation from English. Keep athlete "
        "names, club names, meet names, recorded times and hashtags "
        "exactly as given — never translate, transliterate or re-spell "
        "them — and keep times and numbers in Western digits (e.g. "
        "1:02.34)."
    ]
    if lang.prompt_notes:
        parts.append(lang.prompt_notes)
    return " ".join(parts)


def secondary_caption_rules(code: str) -> str:
    """Bundle-contract rule for the side-by-side translated caption
    (the ``caption_secondary`` JSON key in the caption bundle)."""
    lang = get_language(code)
    if lang is None or lang.code == DEFAULT_LANGUAGE:
        return ""
    parts = [
        f"caption_secondary: the same caption written in natural "
        f"{lang.name} ({lang.native_name}) — a tone-preserving "
        "translation, not word-for-word, in the language's own sporting "
        "register; keep athlete names, club names, recorded times and "
        "hashtags exactly as given, with times and numbers in Western "
        "digits."
    ]
    if lang.prompt_notes:
        parts.append(lang.prompt_notes)
    return " ".join(parts)


def language_label(code: str) -> str:
    """Operator-facing label for one language: "Cymraeg (Welsh)"."""
    lang = get_language(code)
    if lang is None:
        return code or ""
    if lang.native_name == lang.name:
        return lang.name
    return f"{lang.native_name} ({lang.name})"


def single_language_options() -> tuple[tuple[str, str], ...]:
    """(value, label) pairs for the monolingual picker options."""
    return tuple((lang.code, language_label(lang.code)) for lang in SUPPORTED_LANGUAGES)


def bilingual_language_options() -> tuple[tuple[str, str], ...]:
    """(value, label) pairs for the English-led bilingual picker options."""
    return tuple(
        (f"{DEFAULT_LANGUAGE}+{lang.code}", f"English + {language_label(lang.code)}")
        for lang in SUPPORTED_LANGUAGES
        if lang.code != DEFAULT_LANGUAGE
    )


__all__ = [
    "Language",
    "SUPPORTED_LANGUAGES",
    "LANGUAGES_BY_CODE",
    "DEFAULT_LANGUAGE",
    "get_language",
    "normalise_language_setting",
    "split_language_setting",
    "language_setting_for",
    "primary_language_for",
    "secondary_language_for",
    "caption_language_instruction",
    "secondary_caption_rules",
    "language_label",
    "single_language_options",
    "bilingual_language_options",
]
