"""
voice/learned/feature_extract.py — Text → VoiceFeatures heuristics.

Pure Python; no AI dependencies.  All measurements are descriptive
statistics over the supplied exemplar texts.

Public API
----------
extract_features(texts: list[str]) -> VoiceFeatures
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Sequence

from .models import VoiceFeatures

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Match emoji characters (broad Unicode blocks)
_EMOJI_RE = re.compile(
    r"["
    r"\U0001F300-\U0001FAFF"
    r"\U00002702-\U000027B0"
    r"\U000024C2-\U0001F251"
    r"\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF"
    r"\U00002500-\U00002BEF"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FAFF"
    r"]",
    flags=re.UNICODE,
)

_HASHTAG_RE = re.compile(r"#\w+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SECOND_PERSON_RE = re.compile(r"\b(you|your|you're|you've|you'll|you'd)\b", re.IGNORECASE)
_EXCLAMATION_RE = re.compile(r"!")
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?:\.\d{1,2})?)\b")

# Words that often introduce achievements — used to detect starting phrases
_SENTENCE_STARTER_WORDS = re.compile(
    r"^([A-Z\U0001F300-\U0001FAFF][^\n.!?]{3,60}[.!?]?)",
    re.MULTILINE,
)

# Positive / celebratory lexicon words we want to harvest
_ACHIEV_WORD_RE = re.compile(
    r"\b(stunning|incredible|amazing|brilliant|superb|fantastic|great|"
    r"outstanding|excellent|epic|massive|huge|big|best|top|first|gold|"
    r"record|pb|personal best|gold|silver|bronze|podium|winner|"
    r"champion|title|smash|smashed|crushed|flies|flying|"
    r"goes|powered|stormed|powered|blasted|nailed|nails)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Individual feature functions
# ---------------------------------------------------------------------------


def _avg_sentence_len(texts: List[str]) -> float:
    lengths = []
    for t in texts:
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(t) if s.strip()]
        if not sentences:
            sentences = [t]
        for s in sentences:
            words = s.split()
            if words:
                lengths.append(len(words))
    return round(sum(lengths) / len(lengths), 2) if lengths else 0.0


def _capitalisation_style(texts: List[str]) -> str:
    """
    Classify the dominant capitalisation pattern:
    - 'title'              — Most sentence-starting words use Title Case beyond first word
    - 'all_caps_emphasis'  — Multiple ALL-CAPS words scattered throughout
    - 'sentence'           — Standard sentence capitalisation
    """
    all_caps_count = 0
    title_caps_count = 0
    total_words = 0

    for t in texts:
        words = t.split()
        total_words += len(words)
        for w in words:
            clean = re.sub(r"[^A-Za-z]", "", w)
            if not clean:
                continue
            if clean.isupper() and len(clean) > 1:
                all_caps_count += 1
            elif clean[0].isupper() and not clean.isupper():
                title_caps_count += 1

    if total_words == 0:
        return "sentence"

    all_caps_ratio = all_caps_count / total_words
    title_ratio = title_caps_count / total_words

    if all_caps_ratio > 0.08:
        return "all_caps_emphasis"
    if title_ratio > 0.35:
        return "title"
    return "sentence"


def _emoji_density(texts: List[str]) -> float:
    """Emojis per 100 characters."""
    total_emojis = sum(len(_EMOJI_RE.findall(t)) for t in texts)
    total_chars = sum(len(t) for t in texts)
    if total_chars == 0:
        return 0.0
    return round(total_emojis / total_chars * 100, 4)


def _emoji_palette(texts: List[str], top_n: int = 10) -> List[str]:
    """Most-used emojis."""
    counter: Counter = Counter()
    for t in texts:
        counter.update(_EMOJI_RE.findall(t))
    return [emoji for emoji, _ in counter.most_common(top_n)]


def _hashtag_density(texts: List[str]) -> float:
    """Hashtags per 100 characters."""
    total_tags = sum(len(_HASHTAG_RE.findall(t)) for t in texts)
    total_chars = sum(len(t) for t in texts)
    if total_chars == 0:
        return 0.0
    return round(total_tags / total_chars * 100, 4)


def _common_hashtags(texts: List[str], top_n: int = 10) -> List[str]:
    counter: Counter = Counter()
    for t in texts:
        counter.update(tag.lower() for tag in _HASHTAG_RE.findall(t))
    return [tag for tag, _ in counter.most_common(top_n)]


def _starting_phrases(texts: List[str], top_n: int = 6) -> List[str]:
    """
    Collect the opening phrase (first 6 words) of each exemplar.
    Returns the most common distinct openers.
    """
    openers = []
    for t in texts:
        stripped = t.strip()
        if not stripped:
            continue
        # Take first non-empty line
        first_line = stripped.split("\n")[0].strip()
        words = first_line.split()
        if words:
            opener = " ".join(words[:6])
            # Strip trailing punctuation for cleaner template
            opener = re.sub(r"[.!?,;]+$", "", opener).strip()
            if opener:
                openers.append(opener)
    counter: Counter = Counter(openers)
    # Deduplicate by keeping most common; if all unique, return all
    results = [phrase for phrase, _ in counter.most_common(top_n)]
    # Also deduplicate near-duplicates (same first 3 words)
    seen_prefixes: set = set()
    unique = []
    for phrase in results:
        prefix = " ".join(phrase.split()[:3]).lower()
        if prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            unique.append(phrase)
    return unique[:top_n]


def _sign_offs(texts: List[str], top_n: int = 4) -> List[str]:
    """
    Collect last non-hashtag, non-empty lines as sign-offs.
    """
    candidates = []
    for t in texts:
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        # Walk backwards past hashtag-only lines
        for line in reversed(lines):
            if not _HASHTAG_RE.fullmatch(line) and not re.fullmatch(r"#\w+(\s+#\w+)*", line):
                # Likely a sign-off if it's short and doesn't look like prose
                if len(line.split()) <= 10 and not line.endswith("."):
                    candidates.append(line)
                break
    counter: Counter = Counter(candidates)
    return [so for so, _ in counter.most_common(top_n)]


def _name_format(texts: List[str]) -> str:
    """
    Heuristic: count how names appear — we look for patterns like
    'First Last', 'First', or 'F. Last'.
    Default to 'first_only' as most social posts use first names.
    """
    full_name_pattern = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")
    initial_pattern = re.compile(r"\b[A-Z]\. [A-Z][a-z]+\b")

    full_count = sum(len(full_name_pattern.findall(t)) for t in texts)
    initial_count = sum(len(initial_pattern.findall(t)) for t in texts)

    if initial_count > full_count and initial_count > 1:
        return "first_initial"
    if full_count > 3:
        return "full"
    return "first_only"


def _time_format(texts: List[str]) -> str:
    """
    Detect whether times use 'X:XX.XX', 'X:XX', or prose like '1 minute 23 seconds'.
    """
    centisecond_re = re.compile(r"\b\d{1,2}:\d{2}\.\d{1,2}\b")
    minute_re = re.compile(r"\b\d{1,2}:\d{2}\b")
    prose_re = re.compile(r"\b\d+ (minute|second|min|sec)\b", re.IGNORECASE)

    cs_count = sum(len(centisecond_re.findall(t)) for t in texts)
    min_count = sum(len(minute_re.findall(t)) for t in texts)
    prose_count = sum(len(prose_re.findall(t)) for t in texts)

    # centisecond is subset of minute, adjust
    min_only_count = min_count - cs_count

    if prose_count >= max(cs_count, min_only_count):
        return "prose"
    if cs_count >= min_only_count:
        return "m:ss.cc"
    return "m:ss"


def _achievement_words(texts: List[str], top_n: int = 15) -> List[str]:
    counter: Counter = Counter()
    for t in texts:
        for match in _ACHIEV_WORD_RE.finditer(t):
            counter[match.group(0).lower()] += 1
    return [w for w, _ in counter.most_common(top_n)]


def _exclamation_density(texts: List[str]) -> float:
    """Exclamation marks per sentence."""
    total_exc = sum(len(_EXCLAMATION_RE.findall(t)) for t in texts)
    # Count sentences
    total_sents = 0
    for t in texts:
        sents = [s for s in _SENTENCE_SPLIT_RE.split(t) if s.strip()]
        total_sents += max(len(sents), 1)
    return round(total_exc / total_sents, 4) if total_sents else 0.0


def _second_person_density(texts: List[str]) -> float:
    """Second-person pronouns per 100 words."""
    total_sp = sum(len(_SECOND_PERSON_RE.findall(t)) for t in texts)
    total_words = sum(len(t.split()) for t in texts)
    if total_words == 0:
        return 0.0
    return round(total_sp / total_words * 100, 4)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_features(texts: Sequence[str]) -> VoiceFeatures:
    """
    Given a list of exemplar post texts, compute and return a VoiceFeatures.

    Parameters
    ----------
    texts : sequence of str
        Raw social-media post texts (3+ recommended, but works with any count).

    Returns
    -------
    VoiceFeatures
        A fully-populated VoiceFeatures dataclass.
    """
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return VoiceFeatures()

    return VoiceFeatures(
        avg_sentence_len=_avg_sentence_len(texts),
        capitalisation_style=_capitalisation_style(texts),
        emoji_density=_emoji_density(texts),
        emoji_palette=_emoji_palette(texts),
        hashtag_density=_hashtag_density(texts),
        common_hashtags=_common_hashtags(texts),
        starting_phrases=_starting_phrases(texts),
        sign_offs=_sign_offs(texts),
        name_format=_name_format(texts),
        time_format=_time_format(texts),
        achievement_words=_achievement_words(texts),
        exclamation_density=_exclamation_density(texts),
        second_person_density=_second_person_density(texts),
    )


__all__ = ["extract_features"]
