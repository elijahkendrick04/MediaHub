"""Parse a free-text photo description into structured tags.

Uses the LLM when available; falls back to regex/keyword extraction otherwise.
Always returns a dict — never raises.
"""
from __future__ import annotations

import re
from typing import Optional

from mediahub.media_ai import generate_json

# Sport-agnostic — but we accept hints from the engine.
_DEFAULT_SCHEMA_HINT = {
    "athletes": ["names mentioned"],
    "venue": "venue or location, or null",
    "meet": "meet/competition name, or null",
    "event": "event name (e.g. '100m Freestyle'), or null",
    "asset_type": "athlete_headshot|athlete_action|team_photo|venue_photo|logo|sponsor_logo|brand_pattern|exemplar_post|other",
    "tags": ["short keyword tags"],
    "permission_hint": "user_owned|approved_public|needs_approval|unknown",
}


def parse_description(description: str, *, hint: Optional[dict] = None) -> dict:
    """Extract structured fields from a user description.

    Args:
        description: free text the user typed.
        hint: optional dict with keys like profile_athlete_names (list of
              known names — boosts athlete extraction).

    Returns:
        {
          "athletes": [str],
          "venue": str | None,
          "meet": str | None,
          "event": str | None,
          "asset_type": str,
          "tags": [str],
          "permission_hint": str,
        }
    """
    description = (description or "").strip()
    if not description:
        return _empty_result()

    # 1) Try LLM
    schema = dict(_DEFAULT_SCHEMA_HINT)
    if hint and hint.get("profile_athlete_names"):
        names = ", ".join(hint["profile_athlete_names"][:30])
        schema["athletes"] = f"names mentioned (known club roster includes: {names})"
    sys = (
        "You extract structured tags from a user's free-text photo description. "
        "You must NEVER invent names, venues, or events that aren't in the text. "
        "Output strictly the requested JSON object."
    )
    prompt = (
        f"Description: {description}\n\n"
        f"Schema fields and instructions:\n"
        f"{_format_schema(schema)}\n\n"
        f"Return ONLY the JSON."
    )
    fallback = _heuristic_parse(description, hint)
    out = generate_json(prompt, system=sys, fallback=fallback)
    # If LLM returned empty / non-useful, prefer heuristic
    if not out or (not out.get("athletes") and not out.get("venue") and not out.get("event")):
        out = fallback
    return _normalise(out, description, hint)


# ---------------------------------------------------------------------------
# Heuristic parser (used as fallback / when LLM unavailable)
# ---------------------------------------------------------------------------

_VENUE_KEYWORDS = ["pool", "centre", "center", "stadium", "arena", "complex", "aquatic"]
_ASSET_KEYWORDS = {
    "athlete_action": ["racing", "swimming", "starting block", "dive", "underwater", "in the pool", "mid-race"],
    "athlete_headshot": ["headshot", "portrait", "head shot", "selfie"],
    "team_photo": ["team photo", "group photo", "squad", "team shot", "everyone"],
    "venue_photo": ["pool", "venue", "facility", "centre exterior", "aerial"],
    "logo": ["logo", "wordmark", "crest"],
    "sponsor_logo": ["sponsor"],
    "exemplar_post": ["exemplar", "reference", "inspiration", "example post"],
}


def _heuristic_parse(description: str, hint: Optional[dict]) -> dict:
    text = description.strip()
    lower = text.lower()

    # Athletes — title-cased two-token sequences (best heuristic)
    candidate_names = re.findall(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text
    )
    # Filter venue-y phrases
    candidate_names = [
        n for n in candidate_names
        if not any(k in n.lower() for k in _VENUE_KEYWORDS)
    ]
    # If profile roster provided, prefer those
    profile_names = (hint or {}).get("profile_athlete_names") or []
    if profile_names:
        athletes = [n for n in candidate_names if n in profile_names]
        if not athletes:
            # case-insensitive match
            athletes = []
            for n in candidate_names:
                for pn in profile_names:
                    if n.lower() == pn.lower():
                        athletes.append(pn)
                        break
            if not athletes:
                athletes = candidate_names[:3]
    else:
        athletes = candidate_names[:3]

    # Venue — sentence containing venue keyword
    venue = None
    for sent in re.split(r"[.\n;,]", text):
        if any(k in sent.lower() for k in _VENUE_KEYWORDS):
            # Take title-cased phrase
            m = re.search(
                r"((?:[A-Z][\w']+\s+){1,5}(?:Pool|Centre|Center|Stadium|Arena|Complex|Aquatic[^\s]*))",
                sent,
            )
            if m:
                venue = m.group(1).strip()
                break

    # Event — pattern like "100m Freestyle", "200m IM", "50 Free"
    ev_match = re.search(
        r"(\d{2,4})\s*m?\s+(Freestyle|Free|Backstroke|Back|Breaststroke|Breast|Butterfly|Fly|IM|Medley)",
        text, re.I,
    )
    event = None
    if ev_match:
        event = f"{ev_match.group(1)}m {ev_match.group(2).title()}"

    # Asset type
    asset_type = "other"
    for atype, kws in _ASSET_KEYWORDS.items():
        if any(k in lower for k in kws):
            asset_type = atype
            break
    if asset_type == "other" and athletes:
        asset_type = "athlete_action" if any(
            k in lower for k in ("race", "racing", "competition", "meet")
        ) else "athlete_headshot"

    # Tags = lowercased meaningful words (filter stopwords)
    stop = {"the", "and", "for", "with", "from", "this", "that", "a", "of", "in", "on", "at"}
    tags = [
        w.lower() for w in re.findall(r"[A-Za-z][A-Za-z']+", text)
        if w.lower() not in stop and len(w) > 3
    ]
    # dedupe + cap
    seen = set()
    deduped = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    tags = deduped[:12]

    perm = "user_owned" if "ours" in lower or "uploaded" in lower else "unknown"

    return {
        "athletes": athletes,
        "venue": venue,
        "meet": None,
        "event": event,
        "asset_type": asset_type,
        "tags": tags,
        "permission_hint": perm,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_result() -> dict:
    return {
        "athletes": [],
        "venue": None,
        "meet": None,
        "event": None,
        "asset_type": "other",
        "tags": [],
        "permission_hint": "unknown",
    }


def _format_schema(schema: dict) -> str:
    lines = []
    for k, v in schema.items():
        if isinstance(v, list):
            lines.append(f"  {k}: array of strings — {v[0] if v else ''}")
        else:
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _normalise(d: dict, description: str, hint: Optional[dict]) -> dict:
    base = _empty_result()
    if isinstance(d, dict):
        for k in base:
            if k in d:
                base[k] = d[k]
    # Coerce types
    if not isinstance(base["athletes"], list):
        base["athletes"] = [str(base["athletes"])] if base["athletes"] else []
    base["athletes"] = [str(x).strip() for x in base["athletes"] if x]
    if not isinstance(base["tags"], list):
        base["tags"] = []
    base["tags"] = [str(x).strip().lower() for x in base["tags"] if x][:12]
    if base["asset_type"] not in (
        "athlete_headshot", "athlete_action", "team_photo", "venue_photo",
        "logo", "sponsor_logo", "brand_pattern", "exemplar_post", "other"
    ):
        base["asset_type"] = "other"
    return base


__all__ = ["parse_description"]
