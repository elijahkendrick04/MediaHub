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

Scripts are length-budgeted: a reel only narrates as many card lines as fit
the video's duration (estimated at a fixed words-per-second rate), dropping
from the bottom of the ranking — never speeding up, never summarising.
Pronunciation overrides (``visual/pronunciation.py``) are applied later by
``voiceover.synthesize``, not here.
"""

from __future__ import annotations

import re

# Conservative speaking-rate estimate for the default edge-tts voices.
# Used only to budget how many card lines fit a reel — the audio mux still
# hard-trims to the video length as the final guarantee.
WORDS_PER_SECOND = 2.4

_TIME_MIN_SEC = re.compile(r"^(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?$")
_TIME_SECONDS = re.compile(r"^(\d{1,3})\.(\d{1,2})$")


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


def _card_line(card_props: dict) -> str:
    """One spoken sentence for a card — its on-screen facts, nothing else."""
    p = card_props or {}
    label = str(p.get("achievementLabel") or "").strip()
    name = str(p.get("athleteFullName") or "").strip()
    event = str(p.get("eventName") or "").strip()
    result = spoken_time(str(p.get("resultValue") or ""))
    facts = ", ".join(s for s in (name, event, result) if s)
    if not facts:
        return ""
    return f"{label}: {facts}." if label else f"{facts}."


def story_script(card_props: dict, brand: dict) -> str:
    """Narration for a single story card: the card line, then the club."""
    line = _card_line(card_props)
    if not line:
        return ""
    club = str((brand or {}).get("displayName") or (brand or {}).get("shortName") or "").strip()
    return f"{line} {club}." if club else line


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
) -> str:
    """Narration for a meet reel, budgeted to ``max_seconds``.

    Priority order mirrors what matters: the meet-name opener, then one
    line per card in rank order (the content), then the honest stats
    sentence, then the club sign-off. When the budget is tight the
    lowest-priority pieces are dropped whole — card lines from the bottom
    of the ranking up, never the top moments, and never by summarising.
    """
    cards = list(cards_props or [])
    club = str((brand or {}).get("displayName") or (brand or {}).get("shortName") or "").strip()
    meet = (meet_name or "").strip()

    opener = f"{meet}." if meet else "Meet recap."

    pbs, medals = _label_stats(cards)
    stat_parts: list[str] = []
    if pbs:
        stat_parts.append(f"{pbs} personal best{'s' if pbs != 1 else ''}")
    if medals:
        stat_parts.append(f"{medals} medal{'s' if medals != 1 else ''}")
    stats_sentence = (" and ".join(stat_parts) + ".") if stat_parts else ""

    closer = f"Follow {club} for more." if club else ""

    # ~1s of slack for the audio fade-out.
    budget = max(0.0, float(max_seconds) - 1.0)
    pieces: list[str] = [opener]

    def _fits(extra: str) -> bool:
        return estimate_seconds(" ".join([*pieces, extra])) <= budget

    for line in (_card_line(c) for c in cards):
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
]
