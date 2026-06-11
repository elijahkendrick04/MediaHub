"""Parse a free-text photo description into structured tags.

Uses the configured cloud LLM (Gemini / Anthropic) to extract athlete
names, venue, event, asset type and tags from the description the user
typed when uploading a media asset. There is no regex fallback —
without an AI provider configured the function returns an empty result
rather than fabricating tags from keyword matching.
"""

from __future__ import annotations

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


__all__ = ["parse_description"]
