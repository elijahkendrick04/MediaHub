"""
ai_caption.py — Generate live AI captions for achievements, with tone support.

All tones are generated live via the LLM (Gemini free tier or Anthropic).
No results are cached — every call produces a fresh, unique generation.
A random nonce is injected into every prompt to ensure uniqueness.

Supported tones:
  ai          — balanced, sports social media writer (default)
  warm-club   — warm, community-focused, first-name friendly
  hype        — energetic, race-day language, high energy
  data-led    — numbers-first, precise, sponsor-friendly

Public API
----------
generate_ai_caption(achievement_dict, club_brand=None)
    -> dict {caption, tone, fallback, fallback_voice}

generate_caption_for_tone(achievement_dict, club_brand=None, tone="ai")
    -> str  (the caption text; raises ClaudeUnavailableError on hard failure)

_SYSTEM_PROMPT   — default system prompt (used by the legacy route)
_build_user_message(ach, brand) — builds the user message string
KNOWN_AI_TONES  — set of tone keys handled as AI generation
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from mediahub.media_ai.llm import call_claude, ClaudeUnavailableError
    _llm_ok = True
except ImportError:
    _llm_ok = False
    ClaudeUnavailableError = RuntimeError  # type: ignore[assignment,misc]

try:
    from mediahub.voice.learned.store import list_voices
    from mediahub.voice.learned.render import render_caption
    _voice_ok = True
except ImportError:
    _voice_ok = False
    list_voices = None  # type: ignore[assignment]
    render_caption = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Tone-specific system prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a sports social-media writer producing one caption for a swimming achievement. "
    "Keep it specific, human, club-appropriate, ~280 chars max, "
    "no generic filler, never invent facts. "
    "Respond with only the caption text — no preamble, no quotes, no markdown."
)

_TONE_SYSTEM_PROMPTS: dict[str, str] = {
    "ai": _SYSTEM_PROMPT,
    "warm-club": (
        "You are a warm, community-focused sports club writer. "
        "Write one short social caption celebrating this swimming achievement. "
        "Be friendly and inclusive — use the swimmer's first name, celebrate the team spirit, "
        "make it feel like a message from a club family. "
        "~280 chars max. Only the caption — no preamble, no quotes, no markdown."
    ),
    "hype": (
        "You are an energetic, hype-focused sports content creator. "
        "Write one explosive social caption for this swimming achievement. "
        "High energy, race-day language, bold — exclamation marks where they feel earned. "
        "Make the reader feel the adrenaline. "
        "~280 chars max. Only the caption — no preamble, no quotes, no markdown."
    ),
    "data-led": (
        "You are a precise, data-led sports journalist writing for a results-focused audience. "
        "Write one social caption that leads with the numbers and hard facts. "
        "Sponsor-friendly, clean, no fluff — every word must earn its place. "
        "~280 chars max. Only the caption — no preamble, no quotes, no markdown."
    ),
}

# All tone keys this module handles via AI (not voice templates).
# Any tone key NOT in this set falls through to voice rendering in the route.
KNOWN_AI_TONES: frozenset[str] = frozenset(_TONE_SYSTEM_PROMPTS.keys())


_ADDRESS_INSTRUCTIONS: dict[str, str] = {
    "first_name": "Address the swimmer by first name only.",
    "last_name": "Address the swimmer by their full name with surname.",
    "surname_only": "Address the swimmer by surname only (sports-broadcast style).",
    "nickname": "Address the swimmer in a familiar, nickname-style way.",
}


def _voice_profile_addendum(voice_profile: Optional[dict]) -> str:
    """Render a club's voice_profile as system-prompt guidance.

    Returns "" when the profile is empty or missing — callers can safely
    concatenate the result with no extra checks.
    """
    if not voice_profile:
        return ""
    parts: list[str] = ["", "Club voice profile — match this style:"]

    avg_len = voice_profile.get("sentence_length_avg")
    if avg_len:
        try:
            parts.append(
                f"- Aim for sentences of roughly {float(avg_len):.0f} words "
                f"on average."
            )
        except (TypeError, ValueError):
            pass

    hash_avg = voice_profile.get("hashtag_count_avg")
    if hash_avg is not None:
        try:
            n = int(round(float(hash_avg)))
            if n <= 0:
                parts.append("- Do NOT use hashtags.")
            else:
                parts.append(f"- Use about {n} hashtag{'s' if n != 1 else ''}.")
        except (TypeError, ValueError):
            pass

    emoji_rate = voice_profile.get("emoji_rate_per_caption")
    if emoji_rate is not None:
        try:
            r = float(emoji_rate)
            if r <= 0.1:
                parts.append("- Avoid emoji entirely — this club doesn't use them.")
            elif r < 1.0:
                parts.append("- Use emoji sparingly (at most one per caption).")
            else:
                parts.append(
                    f"- This club typically uses around {r:.1f} emoji per caption."
                )
        except (TypeError, ValueError):
            pass

    address = voice_profile.get("preferred_swimmer_address")
    if isinstance(address, str) and address in _ADDRESS_INSTRUCTIONS:
        parts.append(f"- {_ADDRESS_INSTRUCTIONS[address]}")

    openers = voice_profile.get("characteristic_openers") or []
    if openers:
        sample = ", ".join(f'"{o}"' for o in openers[:5])
        parts.append(
            f"- Characteristic opener styles to draw from: {sample}."
        )

    closers = voice_profile.get("characteristic_closers") or []
    if closers:
        sample = ", ".join(f'"{c}"' for c in closers[:5])
        parts.append(
            f"- Characteristic closer styles to draw from: {sample}."
        )

    forbidden = voice_profile.get("forbidden_phrases") or []
    if forbidden:
        sample = ", ".join(f'"{p}"' for p in forbidden[:5])
        parts.append(f"- Phrases to avoid entirely: {sample}.")

    return "\n".join(parts) if len(parts) > 2 else ""


def _build_user_message(achievement: dict, club_brand: Optional[dict],
                        nonce: Optional[int] = None) -> str:
    """Format the achievement dict as a structured user message.

    The optional nonce is appended to guarantee a unique generation even
    when the achievement data is identical to a previous call.
    """
    safe = {k: v for k, v in achievement.items() if v not in (None, "", [], {})}
    parts = ["Achievement data (JSON):", json.dumps(safe, ensure_ascii=False)]
    if club_brand:
        safe_brand = {k: v for k, v in club_brand.items() if v not in (None, "", [], {})}
        if safe_brand:
            parts.append("Club/brand context (JSON):")
            parts.append(json.dumps(safe_brand, ensure_ascii=False))
    if nonce is not None:
        parts.append(f"[generation-nonce: {nonce}]")
    return "\n".join(parts)


def _resolve_voice_profile(club_profile) -> Optional[dict]:
    """Return a usable voice_profile dict from a ClubProfile-like object.

    Tolerates: None, plain dicts (treated as the voice_profile itself),
    or any object exposing a ``voice_profile`` attribute. Returns None
    when nothing usable is present so callers can fall straight through.
    """
    if club_profile is None:
        return None
    if isinstance(club_profile, dict):
        vp = club_profile.get("voice_profile")
        return vp if isinstance(vp, dict) and vp else None
    vp = getattr(club_profile, "voice_profile", None)
    return vp if isinstance(vp, dict) and vp else None


def generate_caption_for_tone(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    club_profile=None,
) -> str:
    """Generate a unique AI caption for the given tone. Returns caption text.

    Always generates fresh — never uses a cache. A random nonce is injected
    so that repeated calls with the same data produce different captions.

    If ``club_profile`` is provided and carries a populated
    ``voice_profile`` dict, the system prompt is extended with that
    club's learned voice fingerprint (openers, hashtag count, swimmer
    address style, phrases to avoid). Profiles with no voice_profile
    are accepted and behave exactly like the old single-arg call.

    Raises ClaudeUnavailableError if no LLM provider is reachable.
    """
    system = _TONE_SYSTEM_PROMPTS.get(tone, _SYSTEM_PROMPT)
    voice_profile = _resolve_voice_profile(club_profile)
    addendum = _voice_profile_addendum(voice_profile)
    if addendum:
        system = system + "\n" + addendum
    nonce = random.randint(10_000, 99_999)
    user_msg = _build_user_message(achievement_dict, club_brand, nonce=nonce)
    return call_claude(system=system, user=user_msg, max_tokens=400).strip()


# ---------------------------------------------------------------------------
# Fallback helpers (voice templates, then minimal text)
# ---------------------------------------------------------------------------

def _voice_fallback(achievement: dict) -> dict:
    if not _voice_ok or list_voices is None or render_caption is None:
        return {"caption": _minimal_caption(achievement),
                "tone": "fallback", "fallback": True, "fallback_voice": "text fallback"}
    voices = list_voices(include_seed=True)
    if not voices:
        return {"caption": _minimal_caption(achievement),
                "tone": "fallback", "fallback": True, "fallback_voice": "text fallback"}
    profile = random.choice(voices)
    captions = render_caption(achievement, profile, n_variants=1)
    text = captions[0] if captions else _minimal_caption(achievement)
    return {"caption": text, "tone": profile.voice_id,
            "fallback": True, "fallback_voice": profile.display_name}


def _minimal_caption(achievement: dict) -> str:
    name = achievement.get("swimmer_first", "") or achievement.get("swimmer_name", "")
    event = achievement.get("event", "")
    time_ = achievement.get("time", "")
    parts = [p for p in [name, event, time_] if p]
    return "Great swim: " + " — ".join(parts) if parts else "Great swim!"


# ---------------------------------------------------------------------------
# Public legacy API (used by the review page route)
# ---------------------------------------------------------------------------

def generate_ai_caption(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
) -> dict:
    """Generate a live AI caption (default tone). Falls back to voice on error."""
    if not _llm_ok:
        return _voice_fallback(achievement_dict)
    try:
        caption = generate_caption_for_tone(achievement_dict, club_brand, tone="ai")
        return {"caption": caption, "tone": "ai", "fallback": False, "fallback_voice": None}
    except ClaudeUnavailableError:
        return _voice_fallback(achievement_dict)


__all__ = [
    "generate_ai_caption",
    "generate_caption_for_tone",
    "KNOWN_AI_TONES",
    "_SYSTEM_PROMPT",
    "_build_user_message",
    "_voice_profile_addendum",
]
