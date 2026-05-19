"""link_learners/content_extractor.py — B10. Content extractor learner.

Given raw scraped text (regardless of source — HTML, JSON-LD dump,
oEmbed payload, plain text from a readability gateway), the LLM
extracts the brand-relevant signals tuned to the calling handler's
intent.

The handler hands in:
  - raw_text:       what the fetcher returned, already truncated to a
                    sensible window (≤ 12 KB)
  - platform_intent: a free-form string describing what the handler is
                     looking for, e.g.:
                       "Instagram — bio, recent caption tone, hashtag
                        rhythm, post cadence."
  - url:            for context only

The output matches the dict shape that ``brand.context._dna_prose``
already consumes, so downstream prompt construction needs no further
change. Specifically the keys:

    voice_summary, keywords, phrases_to_use, phrases_to_avoid,
    palette_mentions, typography_hint, sponsor_mentions,
    hashtag_patterns

When the LLM is unavailable a heuristic excerpt + hashtag scan is
returned so the pipeline still produces something useful.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


_LLM_SYSTEM = (
    "You extract brand-intelligence signals from raw scraped text "
    "(websites, social profiles, oEmbed payloads, JSON-LD blocks, "
    "etc.). You are given a platform intent describing what the "
    "calling system wants to know. You return a SINGLE JSON object. "
    "Be factual, terse, and concrete. Where evidence is thin, leave "
    "the field empty rather than guessing. Never invent facts the "
    "text does not support."
)


def _build_prompt(url: str, platform_intent: str, raw_text: str) -> str:
    excerpt = (raw_text or "")[:12_000]
    parts = [
        f"Source URL: {url}",
        f"Platform intent: {platform_intent or '(generic)'}",
        "",
        "Raw scraped text (may contain markup, navigation, boilerplate; "
        "ignore anything that isn't about the organisation):",
        "===== BEGIN =====",
        excerpt,
        "===== END =====",
        "",
        "Return a SINGLE JSON object with EXACTLY these keys:",
        "  voice_summary: string, 30-60 words on how this organisation "
        "talks about itself and what they're about. Empty if unclear.",
        "  keywords: array of 6-12 short keywords this org would use "
        "about itself.",
        "  phrases_to_use: array of 3-6 short phrases that sound like "
        "them (quote directly where possible).",
        "  phrases_to_avoid: array of 3-5 short phrases that would "
        "feel off-brand for them.",
        "  palette_mentions: array of #rrggbb colours mentioned or "
        "implied in the text (lower-case).",
        "  typography_hint: one of \"serif\", \"sans\", \"display\", "
        "\"mono\", or empty.",
        "  sponsor_mentions: array of sponsor / partner brand names "
        "mentioned (up to 5).",
        "  hashtag_patterns: array of hashtag-usage patterns (e.g. "
        "\"always includes #ClubTeam\", \"3 hashtags per post\").",
    ]
    return "\n".join(parts)


_HASHTAG_RE = re.compile(r"#[A-Za-z][A-Za-z0-9_]{1,40}")


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL_RE = re.compile(r"https?://\S+")
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")
_BLOB_RE = re.compile(r"blob:[a-z]+://\S+", re.IGNORECASE)


def _clean_excerpt(raw_text: str, *, cap: int = 280) -> str:
    """Strip markdown noise so the heuristic fallback returns sentences,
    not raw scraped junk. We previously dumped the first 300 chars of
    whatever the fetcher returned — that meant the voice summary stored
    on the profile looked like "# Instagram ![Image 1](blob:...)" and
    masqueraded as a real summary in every downstream caption prompt.
    """
    if not raw_text:
        return ""
    txt = _MD_IMAGE_RE.sub(" ", raw_text)
    txt = _MD_LINK_RE.sub(r"\1", txt)
    txt = _BLOB_RE.sub(" ", txt)
    txt = _URL_RE.sub(" ", txt)
    txt = _MD_HEADING_RE.sub("", txt)
    # Drop low-information boilerplate lines that platform handlers
    # routinely produce ("Title: Instagram", "URL Source: ...").
    drop_prefixes = (
        "title:", "url source:", "markdown content:", "published time:",
        "warning:", "see everyday moments",
    )
    kept_lines = []
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if any(low.startswith(p) for p in drop_prefixes):
            continue
        kept_lines.append(s)
    joined = " ".join(kept_lines)
    joined = _WHITESPACE_RE.sub(" ", joined).strip()
    if not joined:
        return ""
    if len(joined) <= cap:
        return joined
    # Cut at the nearest sentence boundary within the cap so the excerpt
    # doesn't break mid-word.
    head = joined[:cap]
    last_period = head.rfind(". ")
    if last_period >= cap // 2:
        return head[: last_period + 1].strip()
    return head.rstrip() + "…"


def _heuristic(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    if not text:
        return _empty_result()
    # Hashtag scan — works regardless of LLM availability.
    tags = _HASHTAG_RE.findall(text)
    seen: set[str] = set()
    uniq_tags = []
    for t in tags:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        uniq_tags.append(t)
    excerpt = _clean_excerpt(text)
    return {
        "voice_summary": excerpt,
        "keywords": [],
        "phrases_to_use": [],
        "phrases_to_avoid": [],
        "palette_mentions": [],
        "typography_hint": "",
        "sponsor_mentions": [],
        "hashtag_patterns": uniq_tags[:8],
    }


def _empty_result() -> dict:
    return {
        "voice_summary": "",
        "keywords": [],
        "phrases_to_use": [],
        "phrases_to_avoid": [],
        "palette_mentions": [],
        "typography_hint": "",
        "sponsor_mentions": [],
        "hashtag_patterns": [],
    }


def _normalise(raw: object) -> dict:
    out = _empty_result()
    if not isinstance(raw, dict):
        return out

    def _str(v, cap: int) -> str:
        return str(v).strip()[:cap] if isinstance(v, str) and v.strip() else ""

    def _list_str(v, item_cap: int, n_cap: int) -> list[str]:
        if not isinstance(v, list):
            return []
        cleaned = [str(x).strip()[:item_cap] for x in v if str(x).strip()]
        seen: set[str] = set()
        uniq: list[str] = []
        for x in cleaned:
            xl = x.lower()
            if xl in seen:
                continue
            seen.add(xl)
            uniq.append(x)
        return uniq[:n_cap]

    out["voice_summary"] = _str(raw.get("voice_summary"), 800)
    out["keywords"] = _list_str(raw.get("keywords"), 40, 12)
    out["phrases_to_use"] = _list_str(raw.get("phrases_to_use"), 200, 6)
    out["phrases_to_avoid"] = _list_str(raw.get("phrases_to_avoid"), 200, 5)
    palette = raw.get("palette_mentions")
    if isinstance(palette, list):
        valid: list[str] = []
        for h in palette:
            if not isinstance(h, str):
                continue
            c = h.strip().lower()
            if not c.startswith("#"):
                c = "#" + c
            if len(c) == 4:
                c = "#" + "".join(ch * 2 for ch in c[1:])
            if re.match(r"^#[0-9a-f]{6}$", c):
                valid.append(c)
        out["palette_mentions"] = valid[:8]
    typo = raw.get("typography_hint")
    if isinstance(typo, str) and typo.strip().lower() in ("serif", "sans", "display", "mono"):
        out["typography_hint"] = typo.strip().lower()
    out["sponsor_mentions"] = _list_str(raw.get("sponsor_mentions"), 80, 5)
    out["hashtag_patterns"] = _list_str(raw.get("hashtag_patterns"), 80, 8)
    return out


def extract_brand_dna(
    raw_text: str,
    *,
    url: str = "",
    platform_intent: str = "",
) -> dict:
    """Extract structured brand DNA from raw scraped text. Never raises.
    LLM-driven; falls back to a hashtag-scan + excerpt when no LLM is
    configured.
    """
    if not raw_text or not raw_text.strip():
        return _empty_result()
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return _heuristic(raw_text)
    if not is_available():
        return _heuristic(raw_text)
    prompt = _build_prompt(url, platform_intent, raw_text)
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=1_400, fallback={})
    except Exception as e:
        log.debug("content-extractor LLM call failed: %s", e)
        return _heuristic(raw_text)
    out = _normalise(raw)
    # Empty LLM result → fall back to heuristic so the user's data
    # isn't silently dropped.
    has_signal = bool(out["voice_summary"] or out["keywords"]
                       or out["hashtag_patterns"])
    if not has_signal:
        return _heuristic(raw_text)
    return out


__all__ = ["extract_brand_dna"]
