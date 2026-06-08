"""Deterministic brand-compliance gate for generated cards (thesis §5.5, Tier B).

Tier A gives each card a set of resolved brand **colour roles** (the ``--mh-*``
tokens). Before a card is shown to a human — and, in Tier B, before the LLM
director's candidate *pool* is ranked — those role assignments must be checked
for **legibility**: the name must read on its ground, the result chip must read,
the accent must actually stand out. This module is that check.

It is deliberately **deterministic** (consistent with the colour-science rule):
it scores the text/background pairs a v2 card actually paints using the existing
**APCA** contrast maths (``theming.contrast.apca``) and reports a pass/fail plus a
0..1 score. No LLM, no guessing. The LLM only ever *proposes* a role assignment;
this gate decides whether it is legible enough to ship.

Why APCA and not WCAG 2.x: APCA models perceptual contrast far better for the
large display type these cards use, and the codebase already ships the maths.
``|Lc| ≥ 45`` is the APCA "Bronze" threshold for large/headline text — the right
bar for a 100px swimmer surname or a result chip; smaller supporting text is held
to a higher bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mediahub.theming.contrast import apca

# APCA Lc thresholds (absolute value; sign only encodes polarity).
LC_LARGE = 45.0  # large display text — names, the result numeral, the chip
LC_SUPPORT = 60.0  # smaller supporting text — labels, meta lines

# The text→background pairs a v2 archetype actually renders, keyed to the
# ``--mh-*`` roles. Each entry is (text_role, bg_role, min_lc).
_ROLE_PAIRS: tuple[tuple[str, str, str, float], ...] = (
    ("name_on_ground", "--mh-on-primary", "--mh-primary", LC_LARGE),
    ("text_on_surface", "--mh-on-surface", "--mh-surface", LC_LARGE),
    ("accent_on_ground", "--mh-accent", "--mh-primary", LC_LARGE),
    ("chip_text_on_accent", "--mh-primary", "--mh-accent", LC_LARGE),
)


@dataclass
class ComplianceReport:
    """The legibility verdict for one role assignment."""

    pairs: dict[str, float] = field(default_factory=dict)  # pair name -> APCA Lc (abs)
    failures: list[str] = field(default_factory=list)  # pairs below their threshold
    passes: bool = True
    score: float = 1.0  # 0..1, worst pair normalised against the APCA range

    def explain(self) -> str:
        """One-line human-readable summary for the 'why this design' surface."""
        if self.passes:
            return f"brand-compliant (min contrast Lc {min(self.pairs.values(), default=0):.0f})"
        worst = ", ".join(self.failures)
        return f"low contrast on: {worst}"


def _is_hex(v) -> bool:
    return isinstance(v, str) and v.strip().startswith("#") and len(v.strip()) in (4, 7)


def check_roles(roles: dict, *, pairs=_ROLE_PAIRS) -> ComplianceReport:
    """Score the text/background pairs of a ``--mh-*`` role assignment.

    ``roles`` is the dict returned by the renderer's role resolver. Non-hex roles
    (e.g. the rgba hairline ``--mh-outline``) are simply not part of any scored
    pair. Returns a :class:`ComplianceReport`; ``passes`` is True only when every
    pair clears its APCA threshold.
    """
    report = ComplianceReport()
    worst_ratio = 1.0
    for name, text_role, bg_role, min_lc in pairs:
        fg, bg = roles.get(text_role), roles.get(bg_role)
        if not (_is_hex(fg) and _is_hex(bg)):
            continue
        lc = abs(apca(fg, bg))
        report.pairs[name] = lc
        if lc < min_lc:
            report.passes = False
            report.failures.append(name)
        # normalise each pair against its own threshold, capped at 1; the report
        # score is the worst (a card is only as legible as its weakest pair)
        worst_ratio = min(worst_ratio, min(1.0, lc / min_lc))
    report.score = round(worst_ratio, 3)
    return report


def is_legible(text_hex: str, bg_hex: str, *, min_lc: float = LC_LARGE) -> bool:
    """True when ``text_hex`` clears the APCA threshold on ``bg_hex``.

    The single-pair primitive the renderer uses to decide whether a candidate
    accent actually stands out on the brand ground before falling back to a
    derived legible tint.
    """
    if not (_is_hex(text_hex) and _is_hex(bg_hex)):
        return False
    return abs(apca(text_hex, bg_hex)) >= min_lc
