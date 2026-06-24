"""Provider-backed translation engine — glossary-constrained, length-budgeted,
honest-erroring.

Translation is judgement, so it goes through the configured LLM provider
(``media_ai`` → Gemini-first, Anthropic failover) exactly like captioning. The
standing AI rule holds: when no provider is configured we raise
``ClaudeUnavailableError`` rather than return a fake or word-for-word
translation. There is no heuristic fallback.

What this engine adds on top of a raw provider call:

* **glossary constraints** — the sport's protected vocabulary (``glossary``)
  is injected into the prompt and verified afterwards, so "PB" stays "PB" and
  "freestyle" becomes the right word.
* **generic protection** — athlete/club/meet names, recorded times, hashtags,
  @handles and URLs are kept exactly as given, with numbers in Western digits.
* **length budgets** — a per-slot character budget is passed to the model and
  checked afterwards; the renderer's autofit absorbs overflow, but a slot that
  blew its budget is flagged so a human can see it.
* **regional variants** — en-GB ↔ en-US (and other same-language region pairs)
  are handled as a spelling/idiom pass, not a full translation.
* **provenance + warnings** — the result records which provider answered and any
  protected-term or length warnings, for the review UI and audit log.

Multi-slot translation (``translate_slots``) does the whole card in ONE provider
call — headline, sub-head, caption and alt-text together — so a translated card
costs one round-trip, not one per field.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Imported into this module's namespace so tests can patch
# ``mediahub.localize.translate.generate_json`` the same way they patch
# ``ai_caption.call_claude``.
from mediahub.media_ai.llm import (
    ClaudeUnavailableError,
    active_provider,
    generate_json,
    is_available,
)

from .glossary import check_protected, glossary_prompt
from .scripts import base_code, is_rtl, script_name

__all__ = [
    "TranslationResult",
    "ClaudeUnavailableError",
    "available",
    "translate_slots",
    "translate_text",
    "parse_locale",
]


@dataclass
class TranslationResult:
    """The outcome of translating one or more text slots into a target language."""

    target_language: str  # the requested code, e.g. "cy" or "en-US"
    source_language: str
    sport: str
    slots: dict[str, str]  # slot key → translated text
    source_slots: dict[str, str]  # slot key → original text
    provider: str = ""  # which LLM provider answered ("gemini-api" …)
    rtl: bool = False  # does the target language lay out right-to-left
    script: str = "latin"  # target writing system
    regional_only: bool = False  # spelling/idiom pass, not a full translation
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serialisable form (for persistence on the workflow sidecar)."""
        return asdict(self)


def available() -> bool:
    """True when a provider is configured and translation can run."""
    return is_available()


def parse_locale(code: str | None) -> tuple[str, str]:
    """Split a language code into (base, region): ``en-GB`` → ``("en", "GB")``.

    Region is upper-cased; ``""`` when absent. Tolerates ``_`` and whitespace.
    """
    if not code:
        return "", ""
    raw = str(code).strip().replace("_", "-")
    head, _, tail = raw.partition("-")
    return head.lower(), tail.upper()


# Generic, sport-independent protection rules — the same on every call.
_GENERIC_RULES = (
    "Keep these EXACTLY as given — never translate, transliterate, re-spell or "
    "reformat them: people's names, club names, team names, meet/competition "
    "names, recorded times (e.g. 1:02.34), dates, hashtags (#…), @handles and "
    "URLs. Keep all numbers and times in Western digits."
)


def _language_label(code: str) -> tuple[str, str]:
    """(English name, native name) for a base code, via the caption registry.

    Lazy import: ``web.languages`` pulls in the Flask package, so we only reach
    for it at call time and fall back to the bare code if it is unavailable or
    doesn't know the language.
    """
    base = base_code(code)
    try:  # pragma: no cover - exercised in integration, trivial fallback
        from mediahub.web.languages import get_language

        lang = get_language(base)
        if lang is not None:
            return lang.name, lang.native_name
    except Exception:
        pass
    return base or code or "", base or code or ""


def _build_system_prompt(
    *,
    target_code: str,
    source_code: str,
    sport: str,
    slot_budgets: dict[str, int] | None,
    regional_only: bool,
) -> str:
    name, native = _language_label(target_code)
    parts: list[str] = []
    if regional_only:
        _, region = parse_locale(target_code)
        parts.append(
            "You are a copy editor localising sports-club social content. "
            f"Rewrite each field in {name} as written in region {region or 'the target locale'} "
            "— convert spelling and idiom only (e.g. colour/color, metres/meters, "
            "favourite/favorite). Keep the meaning, structure, facts, names and "
            "times identical; do not paraphrase."
        )
    else:
        parts.append(
            "You are a professional translator for a sports club's social media. "
            f"Translate each field into natural {name} ({native}) — native-speaker "
            "fluency in the sport's own register, never a word-for-word rendering."
        )
    parts.append(_GENERIC_RULES)
    gloss = glossary_prompt(sport, target_code)
    if gloss:
        parts.append(gloss)
    if slot_budgets:
        budget_lines = "; ".join(
            f'"{slot}" ≤ {n} characters' for slot, n in slot_budgets.items() if n and n > 0
        )
        if budget_lines:
            parts.append(
                "Length budgets — keep each field within its character budget "
                f"where the language allows it: {budget_lines}. Never pad to reach a budget."
            )
    parts.append(
        "Return ONLY a JSON object whose keys are EXACTLY the keys given in the "
        "input and whose values are the localised strings. Add no other keys, no "
        "commentary, no markdown."
    )
    return "\n\n".join(parts)


def translate_slots(
    slots: dict[str, str],
    target_language: str,
    *,
    sport: str = "swimming",
    source_language: str = "en",
    length_budgets: dict[str, int] | None = None,
) -> TranslationResult:
    """Translate a dict of named text slots into ``target_language`` in one call.

    ``slots`` maps a slot name (e.g. ``"headline"``, ``"caption"``) to its
    source text. Returns a :class:`TranslationResult` with the translated slots,
    the provider that answered, and any protected-term / length warnings.

    Raises ``ClaudeUnavailableError`` when no provider is configured (honest
    error — never a fake translation). Empty/blank slots are passed through
    untouched and never sent to the model.
    """
    src = {str(k): ("" if v is None else str(v)) for k, v in (slots or {}).items()}
    tgt_base, tgt_region = parse_locale(target_language)
    src_base, src_region = parse_locale(source_language)
    regional_only = bool(tgt_base) and tgt_base == src_base and tgt_region != src_region

    result = TranslationResult(
        target_language=target_language,
        source_language=source_language,
        sport=sport,
        slots=dict(src),
        source_slots=dict(src),
        rtl=is_rtl(target_language),
        script=script_name(target_language) or "latin",
        regional_only=regional_only,
    )

    # Same language and same region → nothing to do. (A genuine no-op, so we
    # never spend a provider call or require one to be configured.)
    if tgt_base == src_base and not regional_only:
        return result

    # Only translate the slots that actually have text.
    payload = {k: v for k, v in src.items() if v.strip()}
    if not payload:
        return result

    budgets = {k: v for k, v in (length_budgets or {}).items() if k in payload}
    system = _build_system_prompt(
        target_code=target_language,
        source_code=source_language,
        sport=sport,
        slot_budgets=budgets or None,
        regional_only=regional_only,
    )
    import json as _json

    user = _json.dumps(payload, ensure_ascii=False)

    # generate_json raises ClaudeUnavailableError when no provider answers —
    # let it propagate. Budget scales with the amount of text.
    max_tokens = min(4096, 512 + 6 * sum(len(v) for v in payload.values()))
    raw = generate_json(user, system=system, max_tokens=max_tokens)

    out = dict(src)
    for key, source_val in payload.items():
        val = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
        else:
            result.warnings.append(f'slot "{key}" was not returned; kept the source text')
        # Protected-term survival check (per slot, against this slot's source).
        for w in check_protected(sport, source_val, out[key]):
            result.warnings.append(f'in "{key}": {w}')
        # Length-budget check (soft — autofit absorbs overflow, but flag it).
        budget = budgets.get(key)
        if budget and len(out[key]) > budget:
            result.warnings.append(
                f'slot "{key}" is {len(out[key])} chars, over its {budget}-char budget'
            )

    result.slots = out
    result.provider = active_provider()
    return result


def translate_text(
    text: str,
    target_language: str,
    *,
    sport: str = "swimming",
    source_language: str = "en",
    max_chars: int | None = None,
) -> str:
    """Translate a single string. Convenience wrapper over :func:`translate_slots`.

    Raises ``ClaudeUnavailableError`` when no provider is configured.
    """
    budgets = {"text": max_chars} if max_chars else None
    res = translate_slots(
        {"text": text},
        target_language,
        sport=sport,
        source_language=source_language,
        length_budgets=budgets,
    )
    return res.slots.get("text", text or "")
