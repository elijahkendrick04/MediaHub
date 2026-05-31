"""
brand/voice_imitation.py — Analyse past social posts → structured voice profile.
brand/voice_imitation.py — derive a structured voice profile from a club's
past social captions.

Dissertation reference: §4.5 (Lately), §4.6 (Jasper), §6 Workstream 2.4.

Goal
----
A user pastes 5-20 recent Instagram/Facebook/X captions. We compute a
deterministic numeric "voice fingerprint" (sentence length, emoji rate,
hashtag count, etc.) and then ask the LLM for the qualitative side
(characteristic openers, closers, phrases to avoid). The resulting
voice_profile dict is consumed by ai_caption.generate_caption_for_tone()
so that live captions sound like the club's own past posts.

Privacy
-------
Pasted captions can contain real swimmer names. We strip obvious names
(Title-cased word pairs and bare first-name@token shapes) before
running the LLM analysis and before persisting voice_examples back to
the club profile JSON.

Public API
----------
analyse_examples(examples: list[str]) -> dict
    Compute deterministic stats (sentence length, emoji/hashtag counts) plus
    LLM-extracted qualitative patterns (openers, closers, forbidden phrases).
    Returns a dict suitable for ClubProfile.voice_profile.

_redact_pii(texts: list[str]) -> list[str]
    Strip obvious name-like tokens (Title Case pairs) before any storage.

Voice profile dict schema
-------------------------
{
    "sentence_length_avg": float,
    "sentence_length_p90": float,
    "emoji_rate_per_caption": float,
    "hashtag_count_avg": float,
    "characteristic_openers": list[str],     # first-line openers
    "characteristic_closers": list[str],     # last-line closers
    "forbidden_phrases": list[str],          # via LLM or empty
    "preferred_swimmer_address": str,        # first_name|last_name|surname_only|nickname
    "capitalisation_style": str,             # sentence|title|all_caps_emphasis
    "common_hashtags": list[str],
}
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII redaction — strip Title Case word pairs that look like personal names.
# This runs on the raw examples BEFORE any analysis so names don't leak into
# the saved voice_profile dict.
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")


def _redact_pii(texts: list[str]) -> list[str]:
    """Replace 'First Last' name-like patterns with '[NAME]'."""
    return [_NAME_RE.sub("[NAME]", t) for t in texts]


# ---------------------------------------------------------------------------
# Deterministic stat helpers — no LLM required.
# ---------------------------------------------------------------------------


def _capitalisation_style(texts: list[str]) -> str:
    all_caps = 0
    title_caps = 0
    total = 0
    for t in texts:
        for w in t.split():
            clean = re.sub(r"[^A-Za-z]", "", w)
            if not clean:
                continue
            total += 1
            if clean.isupper() and len(clean) > 1:
                all_caps += 1
            elif clean[0].isupper() and not clean.isupper():
                title_caps += 1
    if total == 0:
        return "sentence"
    if all_caps / total > 0.08:
        return "all_caps_emphasis"
    if title_caps / total > 0.35:
        return "title"
    return "sentence"


# Unicode emoji ranges (BMP + supplementary). Covers the common social emoji
# set without needing the optional `emoji` package.
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f6ff"  # symbols & pictographs, transport, misc symbols
    "\U0001f900-\U0001faff"  # supplemental symbols, faces, hands, food
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "☀-➿"  # misc symbols + dingbats (☀ ✨ ✅ etc.)
    "]",
    flags=re.UNICODE,
)

_HASHTAG_RE = re.compile(r"(?<!\w)#[A-Za-z0-9_]+")

# Capitalised-name shape used for PII redaction. Matches Title-cased word
# pairs (Emma Davies, James O'Brien) and bare first-name @handle patterns
# (@emma_davies). Single capitalised words are not redacted because that
# would strip event names, venues, and place names too aggressively.
_NAME_PAIR_RE = re.compile(r"\b[A-Z][a-z'’]+(?:[- ][A-Z][a-z'’]+)+\b")
_HANDLE_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_\.]{2,}")

# Common non-name Title-cased phrases that should NOT be redacted as people.
# Lower-cased for membership checks.
_NAME_ALLOWLIST: frozenset[str] = frozenset(
    {
        "city of manchester aquatics",
        "city aquatics club",
        "swim england",
        "north east",
        "south west",
        "west midlands",
        "east midlands",
        "north west",
        "national age",
        "british champs",
        "winter championships",
        "summer championships",
        "national finals",
        "open meet",
        "personal best",
        "long course",
        "short course",
        "freestyle relay",
        "medley relay",
        "great britain",
        "new pb",
    }
)

# Address-style preferences understood downstream by generate_caption_for_tone.
ADDRESS_OPTIONS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "surname_only",
        "nickname",
    }
)


# ---------------------------------------------------------------------------
# Deterministic stats
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitter — splits on . ! ? while keeping non-empty pieces.

    Newlines also act as sentence boundaries because social captions
    routinely use bare line breaks instead of punctuation.
    """
    if not text:
        return []
    # Treat one-or-more newlines as a sentence boundary too.
    parts = re.split(r"[.!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _word_count(sentence: str) -> int:
    return len([w for w in re.split(r"\s+", sentence.strip()) if w])


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    # Linear interpolation between closest ranks.
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return float(s[lo] + (s[hi] - s[lo]) * frac)


def _compute_stats(examples: list[str]) -> dict:
    """Compute the deterministic numeric portion of the voice profile."""
    sentence_lengths: list[float] = []
    total_emoji = 0
    total_hashtag = 0
    n = len(examples)

    for cap in examples:
        for s in _split_sentences(cap):
            sentence_lengths.append(float(_word_count(s)))
        total_emoji += len(_EMOJI_RE.findall(cap))
        total_hashtag += len(_HASHTAG_RE.findall(cap))

    avg_sentence = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0.0
    p90_sentence = _percentile(sentence_lengths, 0.9)
    emoji_rate = total_emoji / n if n else 0.0
    hashtag_avg = total_hashtag / n if n else 0.0

    return {
        "sentence_length_avg": round(avg_sentence, 2),
        "sentence_length_p90": round(p90_sentence, 2),
        "emoji_rate_per_caption": round(emoji_rate, 2),
        "hashtag_count_avg": round(hashtag_avg, 2),
    }


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------


def redact_pii(caption: str) -> str:
    """Strip obvious personal names and social handles from a caption.

    Designed to be cheap and conservative — we err on the side of
    over-redacting individual swimmer names rather than letting a real
    name slip into the persisted voice profile. Allowlisted multi-word
    phrases (e.g. "City of Manchester Aquatics") are preserved by
    detecting their spans first and skipping any name-pair match that
    falls inside one.
    """
    if not caption:
        return caption

    lower = caption.lower()
    allow_spans: list[tuple[int, int]] = []
    for phrase in _NAME_ALLOWLIST:
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            allow_spans.append((idx, idx + len(phrase)))
            start = idx + len(phrase)

    def _in_allowlist(span_start: int, span_end: int) -> bool:
        for a, b in allow_spans:
            if span_start >= a and span_end <= b:
                return True
        return False

    def _name_pair_sub(m: re.Match) -> str:
        if _in_allowlist(m.start(), m.end()):
            return m.group(0)
        return "[NAME]"

    out = _NAME_PAIR_RE.sub(_name_pair_sub, caption)
    out = _HANDLE_RE.sub("[NAME]", out)
    return out


def _redact_examples(examples: Iterable[str]) -> list[str]:
    return [redact_pii(c) for c in examples if c and c.strip()]


# ---------------------------------------------------------------------------
# Qualitative analysis (LLM-backed, with safe fallback)
# ---------------------------------------------------------------------------

_QUAL_SYSTEM_PROMPT = (
    "You are analysing a sports club's social-media voice from sample "
    "captions. Personal names have been replaced with [NAME]. Identify "
    "patterns that make these captions sound distinctive: how they open, "
    "how they close, words/phrases the club seems to avoid, and how the "
    "club refers to its athletes (first name only, surname only, etc.)."
)

_QUAL_USER_TEMPLATE = (
    "Sample captions (one per line):\n"
    "{captions}\n\n"
    "Return ONLY a JSON object with keys:\n"
    "  characteristic_openers: list of up to 5 short opener phrases "
    "(2-5 words each) that recur or feel typical.\n"
    "  characteristic_closers: list of up to 5 short closer phrases.\n"
    "  forbidden_phrases: list of up to 5 phrases this club clearly "
    "would NOT use (cliched filler, generic hype, off-tone words). "
    "If unclear, return an empty list.\n"
    "  preferred_swimmer_address: one of "
    '"first_name", "last_name", "surname_only", "nickname". '
    "Pick the closest match based on how athletes are addressed.\n"
    "No prose. JSON only."
)


def _normalise_qual(raw: dict) -> dict:
    """Clamp the LLM output to the documented schema."""

    def _str_list(key: str, cap: int = 5) -> list[str]:
        vals = raw.get(key)
        if not isinstance(vals, list):
            return []
        out: list[str] = []
        for v in vals:
            if isinstance(v, str):
                s = v.strip()
                if s:
                    out.append(s[:80])
            if len(out) >= cap:
                break
        return out

    addr = raw.get("preferred_swimmer_address")
    if isinstance(addr, str) and addr.strip() in ADDRESS_OPTIONS:
        address = addr.strip()
    else:
        address = "first_name"

    return {
        "characteristic_openers": _str_list("characteristic_openers"),
        "characteristic_closers": _str_list("characteristic_closers"),
        "forbidden_phrases": _str_list("forbidden_phrases"),
        "preferred_swimmer_address": address,
    }


def _qualitative_via_llm(redacted: list[str]) -> dict:
    """Ask the LLM for openers / closers / forbidden phrases / address style.

    Returns a dict with the four qualitative keys, always. On any LLM
    failure we fall back to empty lists and "first_name" — the numeric
    portion of the profile is still useful on its own.
    """
    fallback = {
        "characteristic_openers": [],
        "characteristic_closers": [],
        "forbidden_phrases": [],
        "preferred_swimmer_address": "first_name",
    }
    if not redacted:
        return fallback
    try:
        from mediahub.media_ai.llm import generate_json
    except Exception as e:  # pragma: no cover — import guard
        log.debug("voice_imitation: generate_json import failed: %s", e)
        return fallback

    user_msg = _QUAL_USER_TEMPLATE.format(captions="\n".join(f"- {c}" for c in redacted))
    try:
        raw = generate_json(
            user_msg,
            system=_QUAL_SYSTEM_PROMPT,
            max_tokens=600,
            fallback=fallback,
        )
    except Exception as e:
        log.debug("voice_imitation: generate_json call failed: %s", e)
        return fallback
    if not isinstance(raw, dict) or not raw:
        return fallback
    return _normalise_qual(raw)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyse_examples(
    examples: list[str],
    *,
    use_llm: Optional[bool] = None,
) -> dict:
    """Build a voice_profile dict from raw caption strings.

    Args:
        examples: 5-20 raw captions pasted by the user. Empty strings are
            filtered out automatically. PII is stripped before any LLM
            call and before the resulting profile is returned.
        use_llm: True forces the LLM call, False forces the deterministic
            path only. Default (None) means "call the LLM if available".

    Returns {} when no usable examples are provided.
    """
    cleaned = [c.strip() for c in (examples or []) if c and c.strip()]
    if not cleaned:
        return {}
    redacted = _redact_examples(cleaned)

    stats = _compute_stats(redacted)
    cap_style = _capitalisation_style(redacted)

    if use_llm is False:
        qual = {
            "characteristic_openers": [],
            "characteristic_closers": [],
            "forbidden_phrases": [],
            "preferred_swimmer_address": "first_name",
        }
    else:
        qual = _qualitative_via_llm(redacted)

    return {**stats, "capitalisation_style": cap_style, **qual}


__all__ = [
    "analyse_examples",
    "redact_pii",
    "ADDRESS_OPTIONS",
]
