"""
swim_content_v4/ai_caption.py — Generate a live AI caption for a swim achievement.

Uses Claude Sonnet (via media_ai.llm) with a tight, sport-specific prompt.
Captions are NEVER cached — each call produces a fresh generation.

Graceful degradation: if the LLM is unavailable (no API key, network error,
etc.), falls back to a randomly-picked voice from voice/learned with a banner
message indicating the fallback.

Public API
----------
generate_ai_caption(achievement_dict: dict, club_brand: dict | None = None)
    -> dict with keys:
        caption   : str   — the generated caption text
        tone      : str   — "ai" on success, voice_id on fallback
        fallback  : bool  — True if fell back to a voice
        fallback_voice : str | None — voice display_name used if fallback
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is importable even if called from tests
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

try:
    from mediahub.media_ai.llm import call_claude, ClaudeUnavailableError
    _llm_ok = True
except ImportError:
    _llm_ok = False
    ClaudeUnavailableError = RuntimeError  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Voice helpers (for graceful fallback)
# ---------------------------------------------------------------------------

try:
    from mediahub.voice.learned.store import list_voices
    from mediahub.voice.learned.render import render_caption
    _voice_ok = True
except ImportError:
    _voice_ok = False
    list_voices = None  # type: ignore[assignment]
    render_caption = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a sports social-media writer producing one caption for a swimming achievement. "
    "Keep it specific, human, club-appropriate, ~280 chars max, "
    "no generic filler, never invent facts. "
    "Respond with only the caption text — no preamble, no quotes, no markdown."
)


def _build_user_message(achievement: dict, club_brand: Optional[dict]) -> str:
    """Format the achievement dict as a structured user message."""
    safe = {k: v for k, v in achievement.items() if v not in (None, "", [], {})}
    parts = ["Achievement data (JSON):", json.dumps(safe, ensure_ascii=False)]
    if club_brand:
        safe_brand = {k: v for k, v in club_brand.items() if v not in (None, "", [], {})}
        if safe_brand:
            parts.append("Club/brand context (JSON):")
            parts.append(json.dumps(safe_brand, ensure_ascii=False))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fallback: pick a random voice
# ---------------------------------------------------------------------------

def _voice_fallback(achievement: dict) -> dict:
    """
    Render a caption using a randomly-picked seed voice.

    Returns a dict with caption, tone, fallback=True, and fallback_voice.
    """
    if not _voice_ok or list_voices is None or render_caption is None:
        return {
            "caption": _minimal_caption(achievement),
            "tone": "fallback",
            "fallback": True,
            "fallback_voice": "text fallback",
        }

    voices = list_voices(include_seed=True)
    if not voices:
        return {
            "caption": _minimal_caption(achievement),
            "tone": "fallback",
            "fallback": True,
            "fallback_voice": "text fallback",
        }

    profile = random.choice(voices)
    captions = render_caption(achievement, profile, n_variants=1)
    text = captions[0] if captions else _minimal_caption(achievement)
    return {
        "caption": text,
        "tone": profile.voice_id,
        "fallback": True,
        "fallback_voice": profile.display_name,
    }


def _minimal_caption(achievement: dict) -> str:
    """Absolute last-resort caption from raw achievement fields."""
    name = achievement.get("swimmer_first", "") or achievement.get("swimmer_name", "")
    event = achievement.get("event", "")
    time = achievement.get("time", "")
    parts = [p for p in [name, event, time] if p]
    return "Great swim: " + " — ".join(parts) if parts else "Great swim!"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ai_caption(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
) -> dict:
    """
    Generate a live AI caption for a swim achievement using Claude Sonnet.

    This function NEVER caches its result. Every call triggers a fresh
    LLM generation.

    Parameters
    ----------
    achievement_dict : dict
        Keys typically include: swimmer_first, swimmer_last, swimmer_name,
        event, time, pb, club, meet, place, type, headline.
    club_brand : dict, optional
        Club brand/context hints (tone, name, colours — anything informative).

    Returns
    -------
    dict
        {
            "caption": str,
            "tone": "ai" | voice_id,
            "fallback": bool,
            "fallback_voice": str | None,
        }
    """
    if not _llm_ok:
        result = _voice_fallback(achievement_dict)
        return result

    user_msg = _build_user_message(achievement_dict, club_brand)

    try:
        caption = call_claude(
            system=_SYSTEM_PROMPT,
            user=user_msg,
            max_tokens=400,
        )
        caption = caption.strip()
        return {
            "caption": caption,
            "tone": "ai",
            "fallback": False,
            "fallback_voice": None,
        }
    except ClaudeUnavailableError:
        result = _voice_fallback(achievement_dict)
        return result


__all__ = ["generate_ai_caption"]
