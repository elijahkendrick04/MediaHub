"""Per-sport translation glossary — the *protected vocabulary* a translation
must respect.

Translation in MediaHub is done by the LLM provider (it is judgement —
``media_ai``), but a free translation will happily mangle the terms a club
cares about: it will spell "PB" out longhand, "translate" an event name, or
pick the wrong word for a stroke. This glossary is the deterministic guard
rail around that judgement:

* **keep-verbatim terms** — acronyms and codes that must survive a translation
  unchanged (``PB``, ``DQ``, ``IM``, record codes, course codes). They are the
  same in every language on a result card.
* **established translations** — terms with a *verified* target-language form
  (e.g. Welsh ``freestyle`` → ``dull rhydd``). We only bake a translation when
  it is verified; an unverified guess is worse than letting the model pick the
  natural word, so most language slots are deliberately empty.

The glossary feeds two things: a prompt block that tells the model the rules
(``glossary_prompt``), and a deterministic post-check that flags any
keep-verbatim term the model altered anyway (``check_protected``). The second
is allowed under the deterministic-engine rules: it *validates* the AI's
output, it does not replace the translation.

This is sport-keyed so the second sport (Phase 4) adds its own glossary
without touching swimming. Athlete names, club names, meet names, recorded
times, hashtags and @handles are protected generically by the translation
engine itself (they are runtime values, not a fixed vocabulary), so they are
not listed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GlossaryTerm:
    """One protected term in a sport's vocabulary."""

    canonical: str  # English canonical form ("personal best")
    keep_verbatim: bool = False  # never translate — survives unchanged ("PB")
    # Verified target-language forms, keyed by ISO 639-1 base code.
    # Only ever populated with verified terms; empty means "let the model choose".
    translations: dict[str, str] = field(default_factory=dict)
    # Other English spellings that mean the same thing (matched case-insensitively).
    aliases: tuple[str, ...] = ()


# --- Swimming -------------------------------------------------------------
# Keep-verbatim acronyms/codes are how result cards label times the world over;
# they read identically in Welsh, Spanish or Arabic. The verified Welsh stroke
# terms mirror the curated set already in web/languages.py (W.13) — the single
# place those live for the *translate* path.
SWIMMING_GLOSSARY: tuple[GlossaryTerm, ...] = (
    # Result/record codes — identical in every language on a card.
    GlossaryTerm("PB", keep_verbatim=True, aliases=("personal best record",)),
    GlossaryTerm("SB", keep_verbatim=True),
    GlossaryTerm("DQ", keep_verbatim=True, aliases=("DSQ",)),
    GlossaryTerm("DNF", keep_verbatim=True),
    GlossaryTerm("DNS", keep_verbatim=True),
    GlossaryTerm("NT", keep_verbatim=True),
    GlossaryTerm("IM", keep_verbatim=True),
    GlossaryTerm("WR", keep_verbatim=True),
    GlossaryTerm("ER", keep_verbatim=True),
    GlossaryTerm("CR", keep_verbatim=True),
    GlossaryTerm("NR", keep_verbatim=True),
    GlossaryTerm("LC", keep_verbatim=True),
    GlossaryTerm("SC", keep_verbatim=True),
    GlossaryTerm("relay", keep_verbatim=False),
    # Prose terms — verified Welsh forms; other languages left to the model.
    GlossaryTerm(
        "personal best",
        keep_verbatim=False,
        translations={"cy": "record personol"},
    ),
    GlossaryTerm(
        "freestyle",
        keep_verbatim=False,
        translations={"cy": "dull rhydd"},
        aliases=("front crawl",),
    ),
    GlossaryTerm(
        "backstroke",
        keep_verbatim=False,
        translations={"cy": "dull cefn"},
    ),
    GlossaryTerm(
        "breaststroke",
        keep_verbatim=False,
        translations={"cy": "dull broga"},
    ),
    GlossaryTerm(
        "butterfly",
        keep_verbatim=False,
        translations={"cy": "dull pili-pala"},
    ),
    GlossaryTerm("individual medley", keep_verbatim=False),
)

# Sport slug → glossary. The second sport (Phase 4) registers its own here.
SPORT_GLOSSARIES: dict[str, tuple[GlossaryTerm, ...]] = {
    "swimming": SWIMMING_GLOSSARY,
}

DEFAULT_SPORT = "swimming"


def glossary_for(sport: str | None) -> tuple[GlossaryTerm, ...]:
    """Glossary for a sport slug; empty tuple for an unknown sport."""
    return SPORT_GLOSSARIES.get((sport or "").strip().lower(), ())


def protected_terms(sport: str | None) -> list[str]:
    """All keep-verbatim terms for a sport (canonical + aliases), longest first.

    Longest-first so a post-check matches "personal best record" before "PB".
    """
    out: list[str] = []
    for term in glossary_for(sport):
        if term.keep_verbatim:
            out.append(term.canonical)
            out.extend(term.aliases)
    return sorted(set(out), key=len, reverse=True)


def glossary_prompt(sport: str | None, target_code: str) -> str:
    """Instruction block telling the model how to handle the sport's vocabulary.

    Returns "" when the sport has no glossary. ``target_code`` is the base ISO
    code of the language being translated *into* — established translations for
    that language are named explicitly; others are left to the model.
    """
    terms = glossary_for(sport)
    if not terms:
        return ""
    base = (target_code or "").strip().lower().split("-", 1)[0]

    keep = [t for t in terms if t.keep_verbatim]
    known = [
        (t, t.translations[base]) for t in terms if not t.keep_verbatim and base in t.translations
    ]

    parts: list[str] = ["Sport-terminology rules:"]
    if keep:
        names = ", ".join(sorted({t.canonical for t in keep}))
        parts.append(
            f"- Keep these result/record codes EXACTLY as written, in Latin "
            f"letters, never translated or spelled out: {names}."
        )
    if known:
        pairs = "; ".join(f'"{t.canonical}" → "{form}"' for t, form in known)
        parts.append(
            f"- Use these established translations for the sport's terms where "
            f"they appear: {pairs}."
        )
    parts.append(
        "- For any other event, stroke or distance name, use the natural, "
        "correct term in the target language's own sporting register."
    )
    return "\n".join(parts)


def check_protected(sport: str | None, source: str, translated: str) -> list[str]:
    """Deterministic post-check: which keep-verbatim terms vanished in translation.

    For each protected term present in ``source``, confirm it is still present
    (case-insensitively, as a whole token) in ``translated``. Returns a list of
    human-readable warnings — one per term that was dropped or altered. Empty
    list means every protected term survived.

    This never edits the translation; it only reports, so the caller can flag
    the card for human review rather than silently shipping a mangled code.
    """
    import re

    warnings: list[str] = []
    src = source or ""
    out = translated or ""
    for term in protected_terms(sport):
        # whole-token, case-insensitive; \b doesn't bracket non-word chars so
        # we guard with lookarounds on alphanumerics only.
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(src) and not pattern.search(out):
            warnings.append(f'protected term "{term}" was dropped or altered in the translation')
    return warnings


__all__ = [
    "GlossaryTerm",
    "SWIMMING_GLOSSARY",
    "SPORT_GLOSSARIES",
    "DEFAULT_SPORT",
    "glossary_for",
    "protected_terms",
    "glossary_prompt",
    "check_protected",
]
