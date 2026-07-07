"""Parse a photo's metadata into structured tags — text and vision.

Uses the configured cloud LLM (Gemini / Anthropic) to extract athlete
names, venue, event, asset type and tags from the description the user
typed when uploading a media asset (``parse_description``), and — M34
(PHOTOS-2) — to LOOK at the uploaded pixels and tag them against a
closed, roster-anchored vocabulary (``describe_photo_vision``). There
is no regex/heuristic fallback on either surface: without an AI
provider configured, ``parse_description`` returns an empty result and
``describe_photo_vision`` raises ``ClaudeUnavailableError`` so the
caller can stay honest (an "untagged" badge, never a fabricated tag).

AI writes metadata once, at tagging time; the deterministic selector
(``media_library/selector.py``) still makes every actual photo pick.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from mediahub.media_ai import generate_json
from mediahub.media_ai.llm import ClaudeUnavailableError

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
    """Extract structured fields from a user description via the cloud LLM.

    Args:
        description: free text the user typed.
        hint: optional dict with keys like profile_athlete_names (list of
              known names — fed to the model as context to anchor extraction).

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
        Empty result when ``description`` is blank, or when the cloud
        LLM provider is unconfigured / unreachable.
    """
    description = (description or "").strip()
    if not description:
        return _empty_result()

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
    try:
        out = generate_json(prompt, system=sys, fallback={})
    except ClaudeUnavailableError:
        # No cloud LLM configured — return an empty result rather than
        # fabricating tags via regex. The asset still uploads; the user
        # can edit tags manually on the media-library page.
        return _empty_result()
    except Exception:
        return _empty_result()
    if not out or not isinstance(out, dict):
        return _empty_result()
    return _normalise(out, description, hint)


# ---------------------------------------------------------------------------
# M34 (PHOTOS-2) — AI-vision auto-tagging
# ---------------------------------------------------------------------------

# The photo-shaped subset of models.ASSET_TYPES the vision pass may assign.
# Closed vocabulary: the model picks from this list or "other" — it can never
# mint a new type string.
VISION_ASSET_TYPES = (
    "athlete_headshot",
    "athlete_action",
    "team_photo",
    "venue_photo",
    "other",
)

# Closed scene-tag vocabulary. Deterministic consumers (badges, future
# selector boosts) key off these exact strings, so the model may only pick
# from this list — anything else is dropped at parse time.
VISION_SCENE_TAGS = (
    "podium",
    "mid-race",
    "start-block",
    "celebration",
    "team-huddle",
    "crowd",
    "venue",
)


def describe_photo_vision(
    image_path: str,
    *,
    roster: Optional[list[str]] = None,
) -> dict:
    """Look at one uploaded photo and tag it against a closed vocabulary.

    ``roster`` is the ONLY allowed athlete-name list (the profile's known
    athletes and/or the active run's parsed swimmers). The model is told to
    never invent names; anything it returns outside the roster is dropped
    here anyway, so a hallucinated name can never reach the store.

    Returns::

        {
          "athletes": [str],        # subset of roster, canonical casing
          "asset_type": str,        # one of VISION_ASSET_TYPES
          "scene_tags": [str],      # subset of VISION_SCENE_TAGS
          "has_face": bool | None,  # None = the model didn't say
          "confidence": float,      # 0.0–1.0
        }

    Raises ``ClaudeUnavailableError`` when no vision-capable provider is
    configured or every configured provider failed — the caller surfaces
    that honestly (photos stay usable, tiles show an "untagged" badge).
    A provider that answered but produced unparseable output yields the
    empty result with ``confidence`` 0.0 (the provider spoke; an empty
    tag set is the honest reading of an unusable answer).
    """
    from mediahub.media_ai.llm import generate_vision

    roster = [str(n).strip() for n in (roster or []) if str(n).strip()][:60]
    roster_line = (
        "The ONLY athlete names you may output are from this exact list: "
        + "; ".join(roster)
        + ". If you are not confident a listed athlete is in the photo, output an empty list."
        if roster
        else "You have no roster for this club, so 'athletes' MUST be an empty list."
    )
    system = (
        "You tag sports-club photos for a content engine. You must NEVER "
        "invent athlete names, and you must only use the closed vocabularies "
        "given. Output strictly one JSON object, no prose, no fences."
    )
    prompt = (
        "Look at the photo and return a JSON object with exactly these keys:\n"
        f'  "athletes": array of athlete names. {roster_line}\n'
        f'  "asset_type": one of {list(VISION_ASSET_TYPES)}\n'
        f'  "scene_tags": array drawn only from {list(VISION_SCENE_TAGS)}\n'
        '  "has_face": true if one or more human faces are clearly visible, else false\n'
        '  "confidence": your overall confidence in these tags, 0.0-1.0\n'
        "Return ONLY the JSON object."
    )
    raw = generate_vision([str(image_path)], prompt, system=system, max_tokens=512)
    return _normalise_vision(_extract_json_block(raw), roster)


def _extract_json_block(raw: str) -> dict:
    """Defensively pull one JSON object out of a model response."""
    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    for candidate in (text,):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            obj = json.loads(brace.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {}


def empty_vision_result() -> dict:
    return {
        "athletes": [],
        "asset_type": "other",
        "scene_tags": [],
        "has_face": None,
        "confidence": 0.0,
    }


def _normalise_vision(d: dict, roster: list[str]) -> dict:
    out = empty_vision_result()
    if not isinstance(d, dict) or not d:
        return out
    # Athletes: closed to the roster (canonical roster casing wins).
    roster_by_lc = {n.lower(): n for n in roster}
    raw_athletes = d.get("athletes")
    if isinstance(raw_athletes, (list, tuple)):
        seen: set[str] = set()
        for name in raw_athletes:
            key = str(name).strip().lower()
            canonical = roster_by_lc.get(key)
            if canonical and canonical not in seen:
                seen.add(canonical)
                out["athletes"].append(canonical)
    # Asset type: closed vocabulary.
    at = str(d.get("asset_type") or "").strip()
    out["asset_type"] = at if at in VISION_ASSET_TYPES else "other"
    # Scene tags: closed vocabulary, de-duplicated, order preserved.
    raw_tags = d.get("scene_tags")
    if isinstance(raw_tags, (list, tuple)):
        allowed = set(VISION_SCENE_TAGS)
        picked: list[str] = []
        for t in raw_tags:
            tag = str(t).strip().lower()
            if tag in allowed and tag not in picked:
                picked.append(tag)
        out["scene_tags"] = picked
    # has_face: only accept a real boolean signal.
    hf = d.get("has_face")
    if isinstance(hf, bool):
        out["has_face"] = hf
    # Confidence: clamp to [0, 1]; junk → 0.0.
    try:
        conf = float(d.get("confidence"))
        if conf == conf:  # not NaN
            out["confidence"] = min(1.0, max(0.0, conf))
    except (TypeError, ValueError):
        pass
    return out


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
        "athlete_headshot",
        "athlete_action",
        "team_photo",
        "venue_photo",
        "logo",
        "sponsor_logo",
        "brand_pattern",
        "exemplar_post",
        "other",
    ):
        base["asset_type"] = "other"
    return base


__all__ = [
    "parse_description",
    "describe_photo_vision",
    "empty_vision_result",
    "VISION_ASSET_TYPES",
    "VISION_SCENE_TAGS",
]
