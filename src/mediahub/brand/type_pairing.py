"""AI font pairing (roadmap 1.9).

"Which typeface fits *this* club" is a judgement call, so — per CLAUDE.md — it
goes through the cloud LLM (`media_ai.llm`), Gemini-first with an honest
``ClaudeUnavailableError`` when no provider is configured (never a regex/heuristic
fake). But the *options* are bounded by the deterministic
:mod:`mediahub.typography.catalog`: the model is shown only the self-hosted faces
MediaHub actually ships and must answer with their slugs, so it can never pick a
face the renderer cannot run. Anything it returns is re-validated against the
catalogue (and re-picked deterministically from the pairing-affinity graph if the
model fumbled a slug), so a :class:`Pairing` is always renderable and on-brand.

The deterministic, seed-driven ``typography_pair`` that predates this stays the
default treatment — this module is the *opt-in* upgrade a club gets when a
provider is configured. :meth:`Pairing.typography_pair` maps the result back onto
that existing renderer key, so a chosen pairing flows through the render path
already in place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from mediahub.typography import catalog as cat

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairingContext:
    """What the model is told about the club when proposing a pairing."""

    club_name: str = ""
    sport: str = "swimming"
    mood: str = ""  # a feeling word, e.g. "bold", "elegant", "technical"
    tone: str = ""  # the club's voice, e.g. "hype", "data_led", "warm_club"
    notes: str = ""  # any extra brief ("we're a masters club", "junior squad")


@dataclass(frozen=True)
class Pairing:
    """A validated, catalogue-bound three-face pairing with a reason."""

    headline: str  # catalogue slug
    body: str  # catalogue slug
    numeral: str  # catalogue slug
    reason: str
    corrected: bool = False  # the model named an invalid slug → we re-picked

    def families(self) -> dict[str, str]:
        """The CSS family names, in the shape ``brand.design_tokens`` uses."""
        return {
            "headline_family": _family(self.headline),
            "body_family": _family(self.body),
            "numeral_family": _family(self.numeral),
        }

    def typography_pair(self) -> str:
        """Map onto the renderer's existing ``typography_pair`` override key.

        Lets an AI-chosen pairing ride the render path that already exists
        (``brief.typography_pair`` → ``_TYPOGRAPHY_OVERRIDES``) instead of needing
        a new rendering seam.
        """
        head = self.headline
        if head == "bebas-neue":
            return "bebas-grotesk"
        if head == "bowlby-one":
            return "bowlby-inter"
        return "anton-inter"

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "body": self.body,
            "numeral": self.numeral,
            "reason": self.reason,
            "corrected": self.corrected,
            "typography_pair": self.typography_pair(),
            "families": self.families(),
        }


def _family(slug: str) -> str:
    f = cat.get(slug)
    return f.family if f else slug


# --------------------------------------------------------------------------- #
# Role validity against the catalogue
# --------------------------------------------------------------------------- #
def _is_headline(slug: str) -> bool:
    f = cat.get(slug)
    return bool(f and (f.klass == "display" or "headline" in f.role_affinity))


def _is_body(slug: str) -> bool:
    f = cat.get(slug)
    return bool(f and f.klass in ("sans", "serif") and "body" in f.role_affinity)


def _is_numeral(slug: str) -> bool:
    f = cat.get(slug)
    return bool(f and f.numeral)


def _first(pred, prefer: tuple[str, ...] = ()) -> str:
    """First catalogue slug matching ``pred`` (preferring ``prefer`` order)."""
    fonts = cat.load_catalog()
    by_slug = {f.slug: f for f in fonts}
    for slug in prefer:
        if slug in by_slug and pred(slug):
            return slug
    for f in fonts:
        if pred(f.slug):
            return f.slug
    return fonts[0].slug


def _coerce_role(slug: Optional[str], pred, prefer: tuple[str, ...]) -> tuple[str, bool]:
    """Return (valid_slug, corrected). Keeps the model's pick if valid."""
    s = (slug or "").strip().lower()
    if s.startswith("upload:"):  # uploads are never proposed by the model
        s = ""
    if s and pred(s):
        return s, False
    return _first(pred, prefer), True


# --------------------------------------------------------------------------- #
# The proposal
# --------------------------------------------------------------------------- #
def _catalogue_brief() -> str:
    """A compact, model-readable listing of the self-hosted faces."""
    lines = []
    for f in cat.load_catalog():
        roles = "/".join(f.role_affinity) or "-"
        moods = ", ".join(f.mood_tags)
        num = " [good for numbers]" if f.numeral else ""
        lines.append(f"- {f.slug}: {f.klass}, roles {roles}; moods: {moods}{num}")
    return "\n".join(lines)


_SYSTEM = (
    "You are a typographer choosing fonts for a sports club's branded graphics. "
    "Pick a three-face pairing — a HEADLINE face (display/condensed, the big "
    "names and numbers), a BODY face (clean sans/serif, captions and meta), and a "
    "NUMERAL face (for result times/scores). Choose ONLY from the catalogue you "
    "are given, answering with each face's exact slug. Aim for clear contrast "
    "between headline and body, and a club-appropriate feel. Return STRICT JSON."
)


def suggest_pairing(context: PairingContext) -> Pairing:
    """Propose a catalogue-bound pairing for ``context`` via the cloud LLM.

    Raises ``mediahub.media_ai.llm.ClaudeUnavailableError`` when no AI provider is
    configured — the honest error the operator must see; callers keep the
    deterministic default pairing in that case. A provider that answers with an
    invalid slug is silently corrected to a valid catalogue face (``corrected``),
    so the returned pairing is always renderable.
    """
    from mediahub.media_ai.llm import generate_json

    user = (
        f"Club: {context.club_name or 'a sports club'}\n"
        f"Sport: {context.sport or 'swimming'}\n"
        f"Desired feel: {context.mood or 'confident, sporty'}\n"
        f"Voice/tone: {context.tone or 'club-proud'}\n"
        f"Notes: {context.notes or '(none)'}\n\n"
        f"Catalogue (choose slugs from here only):\n{_catalogue_brief()}\n\n"
        'Return JSON: {"headline": slug, "body": slug, "numeral": slug, '
        '"reason": one sentence}'
    )
    raw = generate_json(user, system=_SYSTEM, max_tokens=400)
    return _pairing_from_raw(raw)


def _pairing_from_raw(raw: dict) -> Pairing:
    """Validate a model response into a renderable :class:`Pairing`."""
    raw = raw if isinstance(raw, dict) else {}
    headline, c1 = _coerce_role(
        raw.get("headline"), _is_headline, prefer=("anton", "bebas-neue", "bowlby-one")
    )
    body, c2 = _coerce_role(
        raw.get("body"), _is_body, prefer=("inter", "space-grotesk", "hanken-grotesk")
    )
    numeral, c3 = _coerce_role(
        raw.get("numeral"), _is_numeral, prefer=("jetbrains-mono", "anton")
    )
    reason = str(raw.get("reason") or "").strip()[:240]
    if not reason:
        reason = f"{_family(headline)} headlines over {_family(body)} body, {_family(numeral)} for times."
    return Pairing(
        headline=headline,
        body=body,
        numeral=numeral,
        reason=reason,
        corrected=bool(c1 or c2 or c3),
    )


__all__ = ["PairingContext", "Pairing", "suggest_pairing"]
