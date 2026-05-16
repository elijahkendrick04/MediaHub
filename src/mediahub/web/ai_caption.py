"""
ai_caption.py — Generate captions via the multi-provider ai_core.

User direction: replace JSON-shaped prompts and hardcoded fallback
templates with natural-language prompts the model can reason about.
Captions are written by Claude / ChatGPT / Gemini (whichever the user
has selected). There is NO heuristic fallback — if no provider is
configured the caller gets ``ClaudeUnavailableError`` and the UI
surfaces a clear "configure a provider" message instead of pretending
to generate a fake caption.

Public API kept for backward compatibility:

  generate_caption_for_tone(ach, club_brand=None, tone="ai", ...)
      → str. Raises ClaudeUnavailableError if no provider can answer.

  generate_ai_caption(ach, club_brand=None)
      → {"caption": str, "tone": str, "fallback": bool,
         "fallback_voice": Optional[str]}.

  KNOWN_AI_TONES = frozenset({"ai","warm-club","hype","data-led"})

The tone is now described to the model in plain English (e.g. "warm,
community-focused, first-name use") instead of being a hardcoded
system-prompt branch. The model decides exactly what that looks like.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Optional


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class ClaudeUnavailableError(RuntimeError):
    """Raised when no provider can produce a caption (kept name for
    backwards compatibility with existing imports in web.py)."""


def call_claude(system: str, user: str, max_tokens: int = 400, **_kwargs) -> str:
    """Thin wrapper kept for tests + back-compat. Delegates to ai_core
    so the active provider (Claude / OpenAI / Gemini) actually runs."""
    from mediahub.ai_core import (
        ask, ProviderNotConfigured, ProviderError,
    )
    try:
        return ask(system, user, max_tokens=max_tokens) or ""
    except ProviderNotConfigured as e:
        raise ClaudeUnavailableError(str(e)) from e
    except ProviderError as e:
        raise ClaudeUnavailableError(str(e)) from e


# A short English description of each tone — given to the model verbatim
# as part of the system prompt. No JSON, no rules-as-code. The model
# interprets these descriptors itself.
_TONE_DESCRIPTORS: dict[str, str] = {
    "ai":         "a balanced sports social-media voice — natural, "
                  "specific, mildly warm, no jargon.",
    "warm-club":  "warm and community-focused: first-name the swimmer, "
                  "celebrate the team, sound like the club family talking.",
    "hype":       "energetic and race-day: high-energy language, "
                  "exclamation marks where genuinely earned, make the "
                  "reader feel the adrenaline.",
    "data-led":   "precise and data-led: lead with numbers and hard "
                  "facts, sponsor-friendly, no fluff — every word earns "
                  "its place.",
}

KNOWN_AI_TONES: frozenset[str] = frozenset(_TONE_DESCRIPTORS.keys())


def _resolve_voice_profile(club_profile) -> Optional[dict]:
    """Return a usable voice_profile dict from a ClubProfile-like object."""
    if club_profile is None:
        return None
    if isinstance(club_profile, dict):
        vp = club_profile.get("voice_profile")
        return vp if isinstance(vp, dict) and vp else None
    vp = getattr(club_profile, "voice_profile", None)
    return vp if isinstance(vp, dict) and vp else None


def _voice_profile_prose(vp: Optional[dict]) -> str:
    """Turn a learned voice_profile dict into natural-language guidance."""
    if not vp:
        return ""
    bits: list[str] = ["Club voice profile — match this style:"]
    avg = vp.get("sentence_length_avg")
    if avg:
        try:
            bits.append(f"Aim for sentences of about {int(round(float(avg)))} words on average.")
        except (TypeError, ValueError):
            pass
    er = vp.get("emoji_rate_per_caption")
    if er is not None:
        try:
            r = float(er)
            if r <= 0.1:
                bits.append("Avoid emoji entirely — use no emoji, this club doesn't use them.")
            elif r < 1.0:
                bits.append("Use emoji sparingly (at most one per caption).")
            else:
                bits.append(f"This club typically uses around {r:.1f} emoji per caption.")
        except (TypeError, ValueError):
            pass
    ha = vp.get("hashtag_count_avg")
    if ha is not None:
        try:
            n = int(round(float(ha)))
            if n <= 0:
                bits.append("Do NOT use hashtags.")
            else:
                bits.append(f"Use about {n} hashtag{'s' if n != 1 else ''}.")
        except (TypeError, ValueError):
            pass
    addr = vp.get("preferred_swimmer_address")
    addr_map = {
        "first_name":   "Address the swimmer by first name only.",
        "last_name":    "Address the swimmer by their full name with surname.",
        "surname_only": "Address the swimmer by surname only (broadcast style).",
        "nickname":     "Address the swimmer in a familiar, nickname-style way.",
    }
    if isinstance(addr, str) and addr in addr_map:
        bits.append(addr_map[addr])
    openers = vp.get("characteristic_openers") or []
    if openers:
        sample = ", ".join(f'"{o}"' for o in openers[:4])
        bits.append(f"Characteristic opener styles to draw from: {sample}.")
    closers = vp.get("characteristic_closers") or []
    if closers:
        sample = ", ".join(f'"{c}"' for c in closers[:4])
        bits.append(f"Characteristic closer styles to draw from: {sample}.")
    forbidden = vp.get("forbidden_phrases") or []
    if forbidden:
        sample = ", ".join(f'"{p}"' for p in forbidden[:5])
        bits.append(f"Phrases to avoid entirely: {sample}.")
    # Strip the header if we didn't add anything substantive (so empty
    # profiles return "").
    if len(bits) <= 1:
        return ""
    return " ".join(bits)


def generate_caption_for_tone(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    voice_profile: Optional[dict] = None,
    club_profile=None,
) -> str:
    """Generate one caption in plain English. Raises ClaudeUnavailableError
    if no provider can answer. NO heuristic fallback — that's intentional;
    a fake caption is worse than an honest error.
    """
    from mediahub.ai_core import narrate_achievement, narrate_brand

    tone_desc = _TONE_DESCRIPTORS.get(tone, _TONE_DESCRIPTORS["ai"])
    resolved_vp = (_resolve_voice_profile(club_profile)
                   or (voice_profile if isinstance(voice_profile, dict) else None))
    vp_prose = _voice_profile_prose(resolved_vp)

    system_parts = [
        "You are a sports social-media writer. Produce ONE caption for a "
        "single swimming achievement.",
        "Tone: " + tone_desc,
        "Keep it specific, human, club-appropriate, ~280 characters max. "
        "Never invent facts. Output ONLY the caption text — no preamble, "
        "no quotes, no markdown.",
    ]
    brand_prose = narrate_brand(club_brand)
    if brand_prose:
        system_parts.append("Brand voice: " + brand_prose)
    if vp_prose:
        system_parts.append("Voice profile from past captions: " + vp_prose)
    system = "\n\n".join(system_parts)

    # User message is a single English paragraph describing the swim — no
    # JSON envelope, no field names. The model writes from this prose.
    user_prose = narrate_achievement(achievement_dict)
    if not user_prose.strip():
        raise ClaudeUnavailableError("not enough detail to generate a caption")
    # Tiny random suffix breaks identical-output caching at the provider's
    # end without leaking into the visible caption (the prompt asks for
    # caption-only output, so the model will not echo the seed).
    nonce = random.randint(10_000, 99_999)
    user_prose = user_prose + f"\n\n[Generate a fresh caption. seed={nonce}]"

    # Route through the local call_claude shim so tests that patch
    # `mediahub.web.ai_caption.call_claude` continue to work, and the
    # production path still goes through ai_core under the hood.
    try:
        text = call_claude(system=system, user=user_prose, max_tokens=400)
    except ClaudeUnavailableError:
        raise
    text = (text or "").strip()
    if not text:
        raise ClaudeUnavailableError("provider returned an empty caption")
    return text


def generate_ai_caption(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
) -> dict:
    """Generate a live AI caption (default tone). Returns an error-bearing
    dict on failure (no template fallback)."""
    try:
        caption = generate_caption_for_tone(achievement_dict, club_brand, tone="ai")
        return {"caption": caption, "tone": "ai",
                "fallback": False, "fallback_voice": None}
    except ClaudeUnavailableError as e:
        return {"caption": "", "tone": "ai",
                "fallback": True, "fallback_voice": None,
                "error": str(e)}


# Back-compat exports — the names are imported elsewhere in web.py.
_SYSTEM_PROMPT = (
    "You are a sports social-media writer producing one caption for a "
    "swimming achievement. Keep it specific, human, club-appropriate, "
    "~280 chars max. Never invent facts. Output only the caption text."
)


def _build_user_message(*_args, **_kwargs) -> str:
    """Kept for back-compat with tests that import it. The new pipeline
    builds prose via narrate_achievement instead."""
    from mediahub.ai_core import narrate_achievement
    a = _args[0] if _args else _kwargs.get("achievement", {}) or {}
    return narrate_achievement(a if isinstance(a, dict) else {})


def _voice_profile_addendum(*_args, **_kwargs) -> str:
    """Kept for back-compat. New pipeline uses _voice_profile_prose."""
    vp = _args[0] if _args else _kwargs.get("voice_profile")
    return _voice_profile_prose(vp if isinstance(vp, dict) else None)


# Test/back-compat alias used by tests/test_voice_imitation.py.
_voice_profile_instructions = _voice_profile_addendum


__all__ = [
    "ClaudeUnavailableError",
    "KNOWN_AI_TONES",
    "generate_ai_caption",
    "generate_caption_for_tone",
    "_SYSTEM_PROMPT",
    "_build_user_message",
    "_voice_profile_addendum",
]
