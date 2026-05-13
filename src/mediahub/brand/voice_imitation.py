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

import re
import statistics
from typing import Optional

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


def _sentence_lengths(text: str) -> list[int]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        sentences = [text]
    return [len(s.split()) for s in sentences if s.split()]


def _compute_stats(texts: list[str]) -> dict:
    all_lengths: list[int] = []
    emoji_counts: list[int] = []
    hashtag_counts: list[int] = []
    openers: list[str] = []
    closers: list[str] = []

    for t in texts:
        # Sentence lengths
        all_lengths.extend(_sentence_lengths(t))

        # Emoji and hashtag counts per caption
        emoji_counts.append(len(_EMOJI_RE.findall(t)))
        hashtag_counts.append(len(_HASHTAG_RE.findall(t)))

        # Openers: first non-empty line, first 6 words
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        if lines:
            words = lines[0].split()
            opener = " ".join(words[:6]).rstrip(".!?,;")
            if opener:
                openers.append(opener)

        # Closers: last non-hashtag, non-empty line
        for line in reversed(lines):
            if not re.fullmatch(r"#\w+(\s+#\w+)*", line):
                if len(line.split()) <= 12:
                    closers.append(line)
                break

    avg_len = round(statistics.mean(all_lengths), 2) if all_lengths else 0.0
    p90_len = round(
        sorted(all_lengths)[int(len(all_lengths) * 0.9)] if all_lengths else 0.0, 2
    )
    emoji_rate = round(statistics.mean(emoji_counts), 2) if emoji_counts else 0.0
    hashtag_avg = round(statistics.mean(hashtag_counts), 2) if hashtag_counts else 0.0

    # Deduplicate openers/closers — keep up to 6 distinct ones
    def _dedup(items: list[str], n: int) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.lower()[:40]
            if key not in seen:
                seen.add(key)
                out.append(item)
                if len(out) >= n:
                    break
        return out

    return {
        "sentence_length_avg": avg_len,
        "sentence_length_p90": p90_len,
        "emoji_rate_per_caption": emoji_rate,
        "hashtag_count_avg": hashtag_avg,
        "characteristic_openers": _dedup(openers, 6),
        "characteristic_closers": _dedup(closers, 4),
    }


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


def _common_hashtags(texts: list[str], top_n: int = 8) -> list[str]:
    from collections import Counter
    counter: Counter = Counter()
    for t in texts:
        for tag in _HASHTAG_RE.findall(t):
            counter[tag.lower()] += 1
    return [tag for tag, _ in counter.most_common(top_n)]


def _preferred_swimmer_address(texts: list[str]) -> str:
    """Heuristic: infer preferred name style from name-pattern frequency."""
    full_name_re = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")
    initial_re = re.compile(r"\b[A-Z]\. [A-Z][a-z]+\b")
    full_count = sum(len(full_name_re.findall(t)) for t in texts)
    initial_count = sum(len(initial_re.findall(t)) for t in texts)
    if initial_count > full_count and initial_count > 0:
        return "last_name"
    if full_count > 2:
        return "first_name"
    return "first_name"


# ---------------------------------------------------------------------------
# LLM enrichment (qualitative patterns) — optional; safe to skip.
# ---------------------------------------------------------------------------

def _llm_enrich(texts: list[str]) -> dict:
    """Ask the LLM for forbidden_phrases and opening phrase archetypes."""
    try:
        from mediahub.media_ai.llm import generate_json
    except ImportError:
        return {}

    sample = "\n---\n".join(texts[:12])
    prompt = (
        "You are analysing social media captions to extract style patterns.\n\n"
        "Here are example captions:\n\n"
        f"{sample}\n\n"
        "Return a JSON object with exactly these keys:\n"
        '- "forbidden_phrases": list of 3-6 phrases or patterns this brand NEVER uses '
        "(based on what is conspicuously absent or tonally wrong — be specific).\n"
        '- "opening_archetypes": list of 3-5 short templates that capture how these captions '
        'typically open (e.g. "Huge congratulations to [NAME]", "What a weekend for [TEAM]").\n\n'
        "Respond with only the JSON object."
    )
    try:
        result = generate_json(prompt, max_tokens=400)
        if not isinstance(result, dict):
            return {}
        return {
            "forbidden_phrases": [str(p) for p in result.get("forbidden_phrases", [])[:6]],
            "opening_archetypes": [str(p) for p in result.get("opening_archetypes", [])[:5]],
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_examples(examples: list[str]) -> dict:
    """
    Analyse 5-20 past social-media captions and produce a structured voice profile.

    Always returns a non-empty dict (graceful degradation if LLM unavailable).
    Does NOT store raw example texts — computed fields only.
    """
    clean = [e.strip() for e in examples if e and e.strip()]
    if not clean:
        return {}

    # Redact PII before any processing
    redacted = _redact_pii(clean)

    stats = _compute_stats(redacted)
    cap_style = _capitalisation_style(redacted)
    hashtags = _common_hashtags(redacted)
    address = _preferred_swimmer_address(clean)  # use pre-redaction for heuristic

    # LLM enrichment (best-effort; falls back to empty if unavailable)
    llm_data = _llm_enrich(redacted)

    profile: dict = {
        **stats,
        "capitalisation_style": cap_style,
        "common_hashtags": hashtags,
        "preferred_swimmer_address": address,
        "forbidden_phrases": llm_data.get("forbidden_phrases", []),
        "opening_archetypes": llm_data.get("opening_archetypes", []),
    }
    return profile


__all__ = ["analyse_examples", "_redact_pii"]
    Returns a voice_profile dict — see ClubProfile.voice_profile for the
    schema. Safe to call without an LLM key — the numeric stats are
    always populated; the qualitative fields fall back to [] when the
    LLM is unreachable.

redact_pii(caption: str) -> str
    Strip obvious personal names from a caption. Exposed for tests and
    for the /organisation route to apply before storing voice_examples.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable, Optional

log = logging.getLogger(__name__)

# Unicode emoji ranges (BMP + supplementary). Covers the common social emoji
# set without needing the optional `emoji` package.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"   # symbols & pictographs, transport, misc symbols
    "\U0001F900-\U0001FAFF"   # supplemental symbols, faces, hands, food
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "☀-➿"           # misc symbols + dingbats (☀ ✨ ✅ etc.)
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
_NAME_ALLOWLIST: frozenset[str] = frozenset({
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
})

# Address-style preferences understood downstream by generate_caption_for_tone.
ADDRESS_OPTIONS: frozenset[str] = frozenset({
    "first_name", "last_name", "surname_only", "nickname",
})


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

    avg_sentence = (
        sum(sentence_lengths) / len(sentence_lengths)
        if sentence_lengths else 0.0
    )
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
    "\"first_name\", \"last_name\", \"surname_only\", \"nickname\". "
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

    user_msg = _QUAL_USER_TEMPLATE.format(
        captions="\n".join(f"- {c}" for c in redacted)
    )
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

    The returned dict always contains every key from the documented
    schema, with sensible defaults when the input is too thin to draw
    conclusions from.
    """
    cleaned = [c.strip() for c in (examples or []) if c and c.strip()]
    redacted = _redact_examples(cleaned)

    stats = _compute_stats(redacted)

    if use_llm is False:
        qual = {
            "characteristic_openers": [],
            "characteristic_closers": [],
            "forbidden_phrases": [],
            "preferred_swimmer_address": "first_name",
        }
    else:
        qual = _qualitative_via_llm(redacted)

    return {**stats, **qual}


__all__ = [
    "analyse_examples",
    "redact_pii",
    "ADDRESS_OPTIONS",
]
