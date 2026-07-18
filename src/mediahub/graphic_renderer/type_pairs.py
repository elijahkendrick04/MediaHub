"""Curated typography pairings for the v2 archetypes (D5, Canva gap analysis).

Canva-grade output applies curated font *sets* — a display voice, a kicker
voice, a body voice and a data voice chosen together — where MediaHub's old
``typography_pair`` list was half-cosmetic: three of six pairs resolved to the
Anton default and only the display face ever changed. This module replaces
that list with a small **curated table of real quadruples**. Each pairing is
an atomic ``(display, kicker, body, data)`` set emitted by the renderer as
``--mh-font-display`` / ``--mh-font-kicker`` / ``--mh-font-body`` custom
properties; the v2 layouts consume the vars with their current stacks as
``var()`` fallbacks, so a pairing that keeps a register on its default emits
nothing for it and the layout renders byte-identically.

Hard rules inherited from the graphic-craft skill:

* **Self-hosted faces only.** Every family named here ships as first-party
  woff2 via the fonts workflow (``scripts/fetch_renderer_fonts.py`` →
  ``layouts/fonts/`` + ``remotion/public/fonts/``). Never a CDN family.
* **Data speaks mono.** The data register is JetBrains Mono in every pairing
  (``data=""`` = the layouts' hard-coded JetBrains stacks stand) so tabular
  alignment and the ``tnum`` numerics never vary by pairing.
* **Still ↔ motion parity.** The display stack per pairing mirrors
  ``fontStackFor`` in ``remotion/src/compositions/StoryCard.tsx`` — the parity
  contract the old ``render._PAIR_DISPLAY_FONT`` dict carried, now sourced
  from this table on the Python side (``tests/test_typography_pairings.py``
  pins both directions).
* **Deterministic selection.** ``pick_pair_for_card`` is a seeded, mood-keyed
  subset pick (sha256 of the card key — the same derivation family as the
  style-pack picker), so the same card always gets the same pairing and a
  content pack spreads across the table. No randomness, no LLM.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

__all__ = [
    "TypePairing",
    "PAIRINGS",
    "PAIR_IDS",
    "DEFAULT_PAIR_ID",
    "MOOD_PAIR_SUBSETS",
    "pairing_for",
    "pick_pair",
    "pick_pair_for_card",
    "font_vars_for_pair",
]


@dataclass(frozen=True)
class TypePairing:
    """One curated (display, kicker, body, data) quadruple.

    Register fields hold the CSS ``font-family`` stack to bind, or ``""`` for
    "keep the layouts' default register" (Anton display / Space Grotesk kicker
    / Inter body / JetBrains Mono data) — an empty field emits **no** var, so
    the default pairing is byte-identical to the pre-D5 renderer.
    """

    id: str
    display: str = ""  # → --mh-font-display   (default: Anton)
    kicker: str = ""  # → --mh-font-kicker    (default: Space Grotesk)
    body: str = ""  # → --mh-font-body      (default: Inter)
    data: str = ""  # data register is LOCKED to JetBrains Mono (never emitted)
    note: str = ""

    @property
    def is_default(self) -> bool:
        return not (self.display or self.kicker or self.body)


# The concrete stacks. Display stacks MUST mirror StoryCard.tsx fontStackFor
# (still↔motion parity); kicker/body stacks lead with the self-hosted family
# and keep a same-register safety net behind it.
_DISPLAY_BEBAS = "'Bebas Neue','Oswald','Impact','Arial Narrow',sans-serif"
_DISPLAY_BOWLBY = "'Bowlby One','Anton','Impact',sans-serif"
_DISPLAY_GROTESK = "'Space Grotesk','Archivo','Inter','Helvetica Neue',Arial,sans-serif"
_DISPLAY_PLAYFAIR = "'Playfair Display',Georgia,'Times New Roman',serif"
_KICKER_INTER = "'Inter','Space Grotesk',sans-serif"
_KICKER_MONO = "'JetBrains Mono','Space Grotesk',monospace"
_BODY_GROTESK = "'Space Grotesk','Inter',sans-serif"

DEFAULT_PAIR_ID = "anton-inter"

# The curated table: seven real quadruples plus the two legacy aliases
# (druk-inter / oswald-inter resolved to the Anton default before D5 and keep
# doing so — those persisted briefs must stay byte-identical).
PAIRINGS: dict[str, TypePairing] = {
    p.id: p
    for p in (
        TypePairing(
            id="anton-inter",
            note="The house default: Anton display, Space Grotesk kickers, Inter body.",
        ),
        TypePairing(
            id="druk-inter",
            note="Legacy alias of the Anton default (kept for persisted briefs).",
        ),
        TypePairing(
            id="oswald-inter",
            note="Legacy alias of the Anton default (kept for persisted briefs).",
        ),
        TypePairing(
            id="bebas-grotesk",
            display=_DISPLAY_BEBAS,
            note="Condensed scoreboard display over the technical grotesk kickers.",
        ),
        TypePairing(
            id="bowlby-inter",
            display=_DISPLAY_BOWLBY,
            kicker=_KICKER_INTER,
            note="Rounded poster display; Inter kickers so only one voice performs.",
        ),
        TypePairing(
            id="archivo-inter",
            display=_DISPLAY_GROTESK,
            kicker=_KICKER_INTER,
            note="Space Grotesk AS display; kickers move to Inter to avoid near-alike pairing.",
        ),
        TypePairing(
            id="playfair-editorial",
            display=_DISPLAY_PLAYFAIR,
            note="The serif register: editorial Playfair display over grotesk kickers.",
        ),
        TypePairing(
            id="playfair-mono",
            display=_DISPLAY_PLAYFAIR,
            kicker=_KICKER_MONO,
            note="Serif display with instrumented mono kickers — quiet data-forward editorial.",
        ),
        TypePairing(
            id="grotesk-mono",
            display=_DISPLAY_GROTESK,
            kicker=_KICKER_MONO,
            body=_BODY_GROTESK,
            note="All-technical: grotesk display+body with mono kickers.",
        ),
    )
}

PAIR_IDS: tuple[str, ...] = tuple(PAIRINGS)

# Mood-keyed subsets (keys ⊆ design_spec.MOODS plus "" for the neutral floor).
# Each subset orders its most characteristic pairing first so a card with no
# usable seed still lands on the register that fits the feeling.
MOOD_PAIR_SUBSETS: dict[str, tuple[str, ...]] = {
    "": ("anton-inter", "bebas-grotesk", "archivo-inter", "grotesk-mono"),
    "neutral": ("anton-inter", "bebas-grotesk", "archivo-inter", "grotesk-mono"),
    "explosive": ("anton-inter", "bebas-grotesk", "bowlby-inter"),
    "electric": ("bebas-grotesk", "grotesk-mono", "anton-inter"),
    "calm": ("playfair-editorial", "grotesk-mono", "anton-inter"),
    "fierce": ("anton-inter", "bebas-grotesk"),
    "celebratory": ("bowlby-inter", "anton-inter", "bebas-grotesk"),
    "stoic": ("playfair-editorial", "anton-inter", "grotesk-mono"),
    "precise": ("grotesk-mono", "archivo-inter", "playfair-mono"),
    "warm": ("bowlby-inter", "playfair-editorial", "anton-inter"),
    "bold": ("anton-inter", "bowlby-inter", "bebas-grotesk"),
    "triumphant": ("anton-inter", "playfair-editorial", "bebas-grotesk"),
    "minimal": ("archivo-inter", "grotesk-mono", "anton-inter"),
}


def pairing_for(pair_id: str) -> TypePairing:
    """The curated pairing for a ``typography_pair`` id (unknown → default)."""
    return PAIRINGS.get((pair_id or "").strip().lower(), PAIRINGS[DEFAULT_PAIR_ID])


def font_vars_for_pair(pair_id: str) -> dict[str, str]:
    """The ``--mh-font-*`` custom properties this pairing binds (may be empty).

    Only non-default registers appear, so the Anton default (and both legacy
    aliases) return ``{}`` and the card's HTML is byte-identical to pre-D5.
    """
    p = pairing_for(pair_id)
    out: dict[str, str] = {}
    if p.display:
        out["--mh-font-display"] = p.display
    if p.kicker:
        out["--mh-font-kicker"] = p.kicker
    if p.body:
        out["--mh-font-body"] = p.body
    return out


def _mood_subset(mood: str) -> tuple[str, ...]:
    """The pairing subset for a mood ("", multi-word and unknown → neutral).

    The brief's mood channel is free-ish text ("electric, precise"); the first
    recognised mood word wins, mirroring how the style-pack presets read it.
    """
    for word in (mood or "").replace(",", " ").split():
        sub = MOOD_PAIR_SUBSETS.get(word.strip().lower())
        if sub:
            return sub
    return MOOD_PAIR_SUBSETS[""]


def pick_pair(mood: str, seed: int) -> TypePairing:
    """Deterministic seeded pick from the mood's subset (same seed → same pair)."""
    subset = _mood_subset(mood)
    return PAIRINGS[subset[int(seed) % len(subset)]]


def pick_pair_for_card(mood: str, card_key: str | None) -> TypePairing:
    """The stable per-card pairing: sha256 of the card key over the mood subset.

    Salted with ``"pair"`` so this axis varies independently of the style-pack
    and archetype walks that hash the same card key. ``None``/empty key →
    the subset's characteristic first entry (still deterministic).
    """
    subset = _mood_subset(mood)
    key = (card_key or "").strip()
    if not key:
        return PAIRINGS[subset[0]]
    digest = hashlib.sha256(f"{key}|pair".encode("utf-8")).digest()
    return PAIRINGS[subset[int.from_bytes(digest[:4], "big") % len(subset)]]
