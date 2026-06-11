"""
voice/learned/render.py — Heuristic caption renderer.

Given a swim achievement dict and a VoiceProfile loaded from disk, renders
one or more caption variants.  Works with any VoiceProfile — nothing about
specific named voices is special in code.

Public API
----------
render_caption(
    achievement: dict,
    profile: VoiceProfile,
    n_variants: int = 1,
) -> list[str]
"""

from __future__ import annotations

import random
import re
from typing import List, Optional

from .models import VoiceProfile

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Fallback starter phrases used when the profile has none
_DEFAULT_STARTERS = [
    "What a swim",
    "Brilliant performance",
    "Great result",
    "Fantastic effort",
    "Well done",
    "Outstanding swim",
]

# Fallback achievement words
_DEFAULT_ACHIEV_WORDS = ["brilliant", "great", "fantastic", "impressive", "strong"]

# Regex: strip excess whitespace
_WS_RE = re.compile(r" {2,}")


def _apply_capitalisation(text: str, style: str) -> str:
    """Apply the profile's capitalisation style to a text string."""
    if style == "title":
        # Title-case every word except minor words
        minor = {
            "a",
            "an",
            "the",
            "and",
            "but",
            "or",
            "for",
            "nor",
            "on",
            "at",
            "to",
            "by",
            "in",
            "of",
            "up",
        }
        words = text.split()
        result = []
        for i, w in enumerate(words):
            if i == 0 or w.lower() not in minor:
                result.append(w.capitalize())
            else:
                result.append(w.lower())
        return " ".join(result)

    if style == "all_caps_emphasis":
        # Keep existing text; caller already inserts ALL-CAPS words as needed
        return text

    # Default: sentence case — first letter capitalised, rest preserved
    if text:
        return text[0].upper() + text[1:]
    return text


def _format_time(raw_time: Optional[str], fmt: str) -> str:
    """
    Normalise a swim time string according to the profile's time_format.

    raw_time examples: "1:03.45", "63.45", "1:03"
    """
    if not raw_time:
        return ""

    # Already in m:ss.cc form — just return
    if re.match(r"^\d{1,2}:\d{2}\.\d{1,2}$", raw_time):
        if fmt == "m:ss":
            return raw_time.rsplit(".", 1)[0]
        return raw_time  # m:ss.cc or prose defaults to original

    # Already m:ss — maybe add centiseconds placeholder
    if re.match(r"^\d{1,2}:\d{2}$", raw_time):
        return raw_time  # leave as-is; we don't have centiseconds to add

    # Plain seconds (e.g. "63.45")
    try:
        secs = float(raw_time)
        minutes = int(secs // 60)
        remainder = secs - minutes * 60
        if fmt == "m:ss.cc":
            return f"{minutes}:{remainder:05.2f}"
        if fmt == "m:ss":
            return f"{minutes}:{int(remainder):02d}"
        # prose
        if minutes:
            return f"{minutes} min {int(remainder)} sec"
        return f"{remainder:.2f} seconds"
    except (ValueError, TypeError):
        return raw_time


def _pick(items: List[str], rng: random.Random) -> str:
    """Pick a random item from a list, or return '' if empty."""
    return rng.choice(items) if items else ""


def _build_body(
    achievement: dict,
    profile: VoiceProfile,
    starter: str,
    rng: random.Random,
) -> str:
    """
    Assemble the body of the caption from achievement facts.

    Achievement dict keys (all optional):
        swimmer_first, swimmer_last, event, time, pb, club, meet, place
    """
    feats = profile.features

    # ---- Name ----------------------------------------------------------
    first = str(achievement.get("swimmer_first") or "")
    last = str(achievement.get("swimmer_last") or "")

    if feats.name_format == "full":
        name = f"{first} {last}".strip()
    elif feats.name_format == "first_initial" and last:
        name = f"{first[0]}. {last}".strip() if first else last
    else:
        name = first or last or "our swimmer"

    # ---- Event + time --------------------------------------------------
    event = str(achievement.get("event") or "")
    raw_time = str(achievement.get("time") or "")
    formatted_time = _format_time(raw_time, feats.time_format) if raw_time else ""

    # ---- Achievement descriptor ----------------------------------------
    achiev_words = feats.achievement_words or _DEFAULT_ACHIEV_WORDS
    descriptor = _pick(achiev_words, rng)

    # ---- PB flag -------------------------------------------------------
    is_pb = bool(achievement.get("pb"))
    pb_tag = " — a new PB!" if is_pb else ""

    # ---- Meet/place context -------------------------------------------
    meet = str(achievement.get("meet") or "")
    place = str(achievement.get("place") or "")

    # ---- Compose body lines -------------------------------------------
    # Line 1: starter + name
    if name:
        line1 = f"{starter}, {name}!"
    else:
        line1 = f"{starter}!"

    # Line 2: event + time
    parts = []
    if event:
        parts.append(event)
    if formatted_time:
        parts.append(formatted_time)
    line2 = " in ".join(parts) + pb_tag if parts else ""

    # Line 3: place / meet context
    line3_parts = []
    if place:
        line3_parts.append(place)
    if meet:
        line3_parts.append(f"at {meet}")
    line3 = " ".join(line3_parts)

    body_parts = [line1]
    if line2:
        body_parts.append(line2)
    if line3:
        body_parts.append(line3)

    body = " ".join(body_parts)
    return _WS_RE.sub(" ", body).strip()


def _build_hashtag_block(profile: VoiceProfile, rng: random.Random) -> str:
    """Return a hashtag string according to profile density/palette."""
    feats = profile.features
    if not feats.common_hashtags or feats.hashtag_density < 0.01:
        return ""
    # Rough number of hashtags based on density (cap at 8)
    n = min(max(1, round(feats.hashtag_density * 2)), min(8, len(feats.common_hashtags)))
    selected = feats.common_hashtags[:n]
    return " ".join(selected)


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------


def render_caption(
    achievement: dict,
    profile: VoiceProfile,
    n_variants: int = 1,
    seed: Optional[int] = None,
) -> List[str]:
    """
    Render N caption variants for a swim achievement using the given profile.

    Parameters
    ----------
    achievement : dict
        Keys: swimmer_first, swimmer_last, event, time, pb, club, meet, place.
        All are optional; sensible defaults are used for missing fields.
    profile : VoiceProfile
        Any VoiceProfile loaded from disk via store.load_voice().
    n_variants : int
        Number of caption strings to return (default 1).
    seed : int, optional
        Fixed RNG seed for deterministic output in tests.

    Returns
    -------
    list[str]
        N caption strings, one per variant.
    """
    rng = random.Random(seed)
    feats = profile.features

    starters = feats.starting_phrases or _DEFAULT_STARTERS
    sign_offs = feats.sign_offs

    variants: List[str] = []
    starter_pool = list(starters)

    for i in range(n_variants):
        # Rotate through starters so each variant uses a different one
        starter = starter_pool[i % len(starter_pool)]

        body = _build_body(achievement, profile, starter, rng)
        body = _apply_capitalisation(body, feats.capitalisation_style)

        # Emoji block — sample from palette, scaled by density
        emoji_block = ""
        if feats.emoji_density > 0 and feats.emoji_palette:
            n_emojis = max(1, round(feats.emoji_density * len(body) / 100))
            n_emojis = min(n_emojis, 6)
            emojis = [feats.emoji_palette[j % len(feats.emoji_palette)] for j in range(n_emojis)]
            emoji_block = " " + "".join(emojis)

        hashtag_block = _build_hashtag_block(profile, rng)
        sign_off = _pick(sign_offs, rng) if sign_offs else ""

        # Assemble full caption
        caption_parts = [body + emoji_block]
        if hashtag_block:
            caption_parts.append(hashtag_block)
        if sign_off:
            caption_parts.append(sign_off)

        caption = "\n".join(p for p in caption_parts if p.strip())
        variants.append(caption)

    return variants


__all__ = ["render_caption"]
