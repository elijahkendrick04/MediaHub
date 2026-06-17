"""visual/narration.py — deterministic, fact-only narration for motion renders.

The narration spoken over a story card or meet reel is built here, and the
rule is the same one the renderer itself lives by: **zero invention**. The
script is a fixed template over the *same verified card facts the video
already displays* — athlete name, event, result, achievement label, meet
name, and the honest cover stats derived from the labels. There is no LLM
in this module and no judgement call: showing a fact on screen and speaking
that same fact are one approval surface.

Times get a deterministic *spoken-form* transform so the TTS engine reads
them like a poolside announcer rather than a phone number:

    "1:02.45"  →  "1 minute 2.45 seconds"
    "54.32"    →  "54.32 seconds"
    "DQ"       →  "DQ"            (non-times pass through verbatim)

**Script-style templates.** The same facts can be spoken in different
*registers*. Five are offered (``STYLES`` / ``STYLE_DESCRIPTIONS``):

    standard   balanced poolside-announcer phrasing (the default; byte-
               identical to the pre-style behaviour, so existing caches and
               cache keys are unchanged)
    compact    tightest phrasing — clipped facts, abbreviated stats, a bare
               club sign-off; fits the most card lines into a budget
    verbose    fuller sentences with result-agnostic connective scaffolding
    poetic     flowing em-dash cadence; the rhythm is the only flourish —
               never an invented adjective or emotion
    technical  field-labelled, data-forward register (Event: / Result: /
               Totals:)

Crucially, a style changes **only the phrasing** — never which facts are
spoken, nor their values. Every register is a fixed template; none is more
or less honest than another, and all stay result-agnostic (a "DQ", a place,
or a points total is never re-spoken as a time). The active style is chosen
per render via the ``style`` argument, or — when that is ``None`` — from the
``MEDIAHUB_NARRATION_STYLE`` environment variable (default ``standard``).
Because the assembled script text is what the audio mux folds into its cache
key, switching styles can never serve a stale mix.

Scripts are length-budgeted: a reel only narrates as many card lines as fit
the video's duration (estimated at a fixed words-per-second rate), dropping
from the bottom of the ranking — never speeding up, never summarising.
Pronunciation overrides (``visual/pronunciation.py``) are applied later by
``voiceover.synthesize``, not here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

# Conservative speaking-rate estimate for the default edge-tts voices.
# Used only to budget how many card lines fit a reel — the audio mux still
# hard-trims to the video length as the final guarantee.
WORDS_PER_SECOND = 2.4

_TIME_MIN_SEC = re.compile(r"^(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?$")
_TIME_SECONDS = re.compile(r"^(\d{1,3})\.(\d{1,2})$")

# Operator-selectable narration register (default 'standard').
_ENV_VAR = "MEDIAHUB_NARRATION_STYLE"


def spoken_time(value: str) -> str:
    """Deterministic spoken form of a result value; non-times pass through.

    Only two shapes are transformed — ``m:ss(.cc)`` and ``ss.cc`` — because
    those are unambiguous swim times. Anything else (places, "DQ", points,
    empty) is returned verbatim so we never mis-speak a value we did not
    understand.
    """
    v = (value or "").strip()
    m = _TIME_MIN_SEC.match(v)
    if m:
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        frac = m.group(3) or ""
        sec_str = f"{seconds}.{frac}" if frac else str(seconds)
        min_word = "minute" if minutes == 1 else "minutes"
        sec_word = "second" if sec_str == "1" else "seconds"
        return f"{minutes} {min_word} {sec_str} {sec_word}"
    m = _TIME_SECONDS.match(v)
    if m:
        return f"{v} seconds"
    return v


def estimate_seconds(text: str) -> float:
    """Estimated spoken duration of ``text`` at the fixed narration rate."""
    words = len((text or "").split())
    return words / WORDS_PER_SECOND


# ---------------------------------------------------------------------------
# Fact extraction (shared by every style — the one place props are read)
# ---------------------------------------------------------------------------


def _present(*parts: str) -> list[str]:
    """The non-empty, stripped parts in order — the omit-what-isn't-there join."""
    return [p for p in (str(s).strip() for s in parts) if p]


def _cap_first(text: str) -> str:
    """Uppercase only the first character (the rest is left exactly as-is).

    Used by registers that open a clause with a lower-case connective
    (``in the …``) so a missing leading fact never yields a lower-case
    sentence start. ``str.capitalize`` is wrong here — it would also
    lower-case the rest of a name.
    """
    return text[:1].upper() + text[1:] if text else text


def _card_facts(card_props: dict) -> tuple[str, str, str, str]:
    """``(label, name, event, result_spoken)`` — the *same* fields the card paints.

    Nothing else is ever spoken. The result is run through ``spoken_time`` so
    a swim time reads like an announcer; a non-time passes through verbatim.
    """
    p = card_props or {}
    label = str(p.get("achievementLabel") or "").strip()
    name = str(p.get("athleteFullName") or "").strip()
    event = str(p.get("eventName") or "").strip()
    result = spoken_time(str(p.get("resultValue") or ""))
    return label, name, event, result


# ---------------------------------------------------------------------------
# Per-style card-line builders
#
# Each takes the four already-verified facts and returns one spoken sentence
# (or "" when there is no core fact to speak). They differ only in word order,
# connectives and punctuation — never in which facts are present or their
# values, and every connective is result-agnostic so a "DQ"/place/points value
# is never phrased as if it were a time.
# ---------------------------------------------------------------------------


def _line_standard(label: str, name: str, event: str, result: str) -> str:
    facts = ", ".join(_present(name, event, result))
    if not facts:
        return ""
    return f"{label}: {facts}." if label else f"{facts}."


def _line_compact(label: str, name: str, event: str, result: str) -> str:
    facts = ", ".join(_present(name, event, result))
    if not facts:
        return ""
    return f"{facts}. {label}." if label else f"{facts}."


def _line_verbose(label: str, name: str, event: str, result: str) -> str:
    core = _present(
        name,
        f"in the {event}" if event else "",
        f"with a result of {result}" if result else "",
    )
    if not core:
        return ""
    sentence = _cap_first(", ".join(core)) + "."
    return f"{label}. {sentence}" if label else sentence


def _line_poetic(label: str, name: str, event: str, result: str) -> str:
    facts = " — ".join(_present(name, event, result))
    if not facts:
        return ""
    return f"{facts}. {label}." if label else f"{facts}."


def _line_technical(label: str, name: str, event: str, result: str) -> str:
    parts = _present(
        name,
        f"Event: {event}" if event else "",
        f"Result: {result}" if result else "",
    )
    if not parts:
        return ""
    body = ". ".join(parts)
    return f"{body}. {label}." if label else f"{body}."


# ---------------------------------------------------------------------------
# Per-style reel scaffolding (opener · stats · closer · story club tail)
# ---------------------------------------------------------------------------


def _opener_standard(meet: str) -> str:
    return f"{meet}." if meet else "Meet recap."


def _opener_compact(meet: str) -> str:
    return f"{meet}." if meet else "Recap."


def _opener_verbose(meet: str) -> str:
    return f"Results from {meet}." if meet else "Meet results."


def _stat_units(pbs: int, medals: int, *, pb_word: str, medal_word: str) -> list[str]:
    """The honest stat phrases present — pluralised, zero-counts omitted."""
    units: list[str] = []
    if pbs:
        units.append(f"{pbs} {pb_word}{'s' if pbs != 1 else ''}")
    if medals:
        units.append(f"{medals} {medal_word}{'s' if medals != 1 else ''}")
    return units


def _stats_standard(pbs: int, medals: int) -> str:
    u = _stat_units(pbs, medals, pb_word="personal best", medal_word="medal")
    return (" and ".join(u) + ".") if u else ""


def _stats_compact(pbs: int, medals: int) -> str:
    u = _stat_units(pbs, medals, pb_word="PB", medal_word="medal")
    return (", ".join(u) + ".") if u else ""


def _stats_verbose(pbs: int, medals: int) -> str:
    u = _stat_units(pbs, medals, pb_word="personal best", medal_word="medal")
    return ("That's " + " and ".join(u) + ".") if u else ""


def _stats_poetic(pbs: int, medals: int) -> str:
    u = _stat_units(pbs, medals, pb_word="personal best", medal_word="medal")
    return (" — ".join(u) + ".") if u else ""


def _stats_technical(pbs: int, medals: int) -> str:
    u = _stat_units(pbs, medals, pb_word="personal best", medal_word="medal")
    return ("Totals: " + ", ".join(u) + ".") if u else ""


def _closer_standard(club: str) -> str:
    return f"Follow {club} for more." if club else ""


def _closer_compact(club: str) -> str:
    return f"{club}." if club else ""


def _closer_verbose(club: str) -> str:
    return f"Follow {club} for more updates." if club else ""


def _closer_poetic(club: str) -> str:
    return f"Follow {club}." if club else ""


def _closer_technical(club: str) -> str:
    return f"Club: {club}." if club else ""


def _tail_standard(club: str) -> str:
    return f" {club}." if club else ""


def _tail_verbose(club: str) -> str:
    return f" Follow {club} for more updates." if club else ""


def _tail_technical(club: str) -> str:
    return f" Club: {club}." if club else ""


# ---------------------------------------------------------------------------
# Style registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Style:
    """A deterministic narration register.

    Every callable is a pure, AI-free, fixed template over already-verified
    facts. A style changes only the *phrasing* — never which facts are spoken
    or their values — so no register is more or less honest than another.
    """

    card_line: Callable[[str, str, str, str], str]
    opener: Callable[[str], str]
    stats: Callable[[int, int], str]
    reel_closer: Callable[[str], str]
    story_tail: Callable[[str], str]


_STYLES: dict[str, _Style] = {
    "standard": _Style(
        _line_standard, _opener_standard, _stats_standard, _closer_standard, _tail_standard
    ),
    "compact": _Style(
        # The bare-name club sign-off doubles as the story tail (" {club}.").
        _line_compact,
        _opener_compact,
        _stats_compact,
        _closer_compact,
        _tail_standard,
    ),
    "verbose": _Style(
        _line_verbose, _opener_verbose, _stats_verbose, _closer_verbose, _tail_verbose
    ),
    "poetic": _Style(
        # Poetic keeps the plain opener and the bare-name story tail; its
        # flourish is cadence in the card lines and closer, not new words.
        _line_poetic,
        _opener_standard,
        _stats_poetic,
        _closer_poetic,
        _tail_standard,
    ),
    "technical": _Style(
        _line_technical, _opener_standard, _stats_technical, _closer_technical, _tail_technical
    ),
}

#: The default register — byte-identical to the pre-style narration.
DEFAULT_STYLE = "standard"

#: Selectable style names, in display order.
STYLES: tuple[str, ...] = ("standard", "compact", "verbose", "poetic", "technical")

#: One-line human description per style (for UI dropdowns / docs).
STYLE_DESCRIPTIONS: dict[str, str] = {
    "standard": "Balanced poolside-announcer phrasing (the default).",
    "compact": "Tightest phrasing — clipped facts, abbreviated stats, bare sign-off.",
    "verbose": "Fuller sentences with result-agnostic connective scaffolding.",
    "poetic": "Flowing em-dash cadence — rhythm only, never an invented word.",
    "technical": "Field-labelled, data-forward register (Event: / Result: / Totals:).",
}


def _normalise(name: str | None) -> str:
    return (name or "").strip().lower()


def is_valid_style(name: str | None) -> bool:
    """True when ``name`` selects a registered narration style."""
    return _normalise(name) in _STYLES


def available_styles() -> tuple[str, ...]:
    """The selectable style names, in display order."""
    return STYLES


def style_from_env() -> str:
    """The operator-selected style from ``MEDIAHUB_NARRATION_STYLE``.

    Unset/blank or an unrecognised value resolves to ``DEFAULT_STYLE`` —
    the narration register is a presentation choice, so an honest fixed
    default is correct here (mirroring the fixed default TTS voice), and a
    typo can never kill a render. Callers that want to *reject* a bad value
    can gate on ``is_valid_style`` first and surface their own error.
    """
    name = _normalise(os.environ.get(_ENV_VAR))
    return name if name in _STYLES else DEFAULT_STYLE


def _spec(style: str | None) -> _Style:
    """Resolve a style name (or ``None`` → the env default) to its spec.

    An unknown name falls back to the standard register — see
    ``style_from_env`` for why a fixed safe default beats an exception here.
    """
    name = _normalise(style) if style is not None else style_from_env()
    return _STYLES.get(name, _STYLES[DEFAULT_STYLE])


# ---------------------------------------------------------------------------
# Script assembly
# ---------------------------------------------------------------------------


def _card_line(card_props: dict, spec: _Style) -> str:
    """One spoken sentence for a card — its on-screen facts, in ``spec``'s register."""
    label, name, event, result = _card_facts(card_props)
    return spec.card_line(label, name, event, result)


def story_script(card_props: dict, brand: dict, *, style: str | None = None) -> str:
    """Narration for a single story card: the card line, then the club.

    ``style`` selects the register (see ``STYLES`` / ``STYLE_DESCRIPTIONS``);
    ``None`` honours ``MEDIAHUB_NARRATION_STYLE`` (default ``standard``, which
    is byte-identical to the pre-style behaviour). The script stays a fixed,
    fact-only template — the style changes only the phrasing, never the facts.
    """
    spec = _spec(style)
    line = _card_line(card_props, spec)
    if not line:
        return ""
    club = str((brand or {}).get("displayName") or (brand or {}).get("shortName") or "").strip()
    return line + spec.story_tail(club)


def _label_stats(cards_props: list[dict]) -> tuple[int, int]:
    """(pbs, medals) counted ONLY from the real achievement labels.

    Mirrors ``reelStats`` in MeetReel.tsx: a medal counts only when the
    label says so. No place-number guessing, no invented numbers.
    """
    labels = [str((c or {}).get("achievementLabel") or "").upper() for c in (cards_props or [])]
    pbs = sum(1 for l in labels if "PB" in l)
    medals = sum(1 for l in labels if any(w in l for w in ("GOLD", "SILVER", "BRONZE", "MEDAL")))
    return pbs, medals


def reel_script(
    cards_props: list[dict],
    brand: dict,
    meet_name: str,
    *,
    max_seconds: float,
    style: str | None = None,
) -> str:
    """Narration for a meet reel, budgeted to ``max_seconds``.

    Priority order mirrors what matters: the meet-name opener, then one
    line per card in rank order (the content), then the honest stats
    sentence, then the club sign-off. When the budget is tight the
    lowest-priority pieces are dropped whole — card lines from the bottom
    of the ranking up, never the top moments, and never by summarising.

    ``style`` selects the register (see ``STYLES``); ``None`` honours
    ``MEDIAHUB_NARRATION_STYLE`` (default ``standard``). A wordier register
    naturally fits fewer card lines into the same budget — that is the
    drop-from-the-bottom behaviour doing its job, not a summary.
    """
    spec = _spec(style)
    cards = list(cards_props or [])
    club = str((brand or {}).get("displayName") or (brand or {}).get("shortName") or "").strip()
    meet = (meet_name or "").strip()

    opener = spec.opener(meet)
    pbs, medals = _label_stats(cards)
    stats_sentence = spec.stats(pbs, medals)
    closer = spec.reel_closer(club)

    # ~1s of slack for the audio fade-out.
    budget = max(0.0, float(max_seconds) - 1.0)
    pieces: list[str] = [opener]

    def _fits(extra: str) -> bool:
        return estimate_seconds(" ".join([*pieces, extra])) <= budget

    for line in (_card_line(c, spec) for c in cards):
        if not line:
            continue
        if not _fits(line):
            # Stop at the first overrun — narrating a lower-ranked card
            # past a dropped higher-ranked one would misrepresent the
            # ranking.
            break
        pieces.append(line)
    if stats_sentence and _fits(stats_sentence):
        pieces.append(stats_sentence)
    if closer and _fits(closer):
        pieces.append(closer)
    return " ".join(pieces).strip()


__all__ = [
    "WORDS_PER_SECOND",
    "spoken_time",
    "estimate_seconds",
    "story_script",
    "reel_script",
    "STYLES",
    "DEFAULT_STYLE",
    "STYLE_DESCRIPTIONS",
    "available_styles",
    "style_from_env",
    "is_valid_style",
]
