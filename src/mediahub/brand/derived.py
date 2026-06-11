"""brand/derived.py — derive operating profile from brand context.

The previous hardcoded constants (`_TONE_DESCRIPTORS`, `_DEFAULT_PRIORITIES`,
`_TYPE_PHRASE`, `_PB_PHRASES`, `_MEDAL_PHRASES`, `_ARTEFACT_INTENTS`) were
all making the same shape of decision: *given an organisation's brand,
what should X be?* That decision is judgment, not infrastructure, so the
audit flagged them all for AI replacement.

This module makes the AI replacement viable in production by following
one rule: **derive once, cache on the profile, never per-request.**

When the user saves an organisation:

    derive_operating_profile(profile) -> dict

is called. That dict is persisted on `ClubProfile.brand_operating_profile`.
At request time, callers consult the cache via thin helpers in this
module (`tone_descriptor_for`, `priority_for`, `type_phrase_for`,
`artefact_intent_for`). When the cache is empty (a profile that hasn't
been re-saved since this feature shipped, or one whose derivation
failed because the LLM provider was unreachable), the helpers fall
back to the canonical product defaults that live in their original
modules. These defaults are baseline product values, not local AI
heuristics.

This satisfies the cross-cutting risks identified in the audit:
  • Determinism — same profile always produces the same operating data
    until the user edits the profile.
  • Latency — exactly one LLM call per profile edit, zero per render.
  • Cost — bounded by user edits, not by traffic.
  • Honest failure — when the LLM is unreachable, raise
    ``ClaudeUnavailableError`` so the operator sees a clear "AI
    unavailable" status rather than a silently fabricated profile.
  • Test stability — existing tests that don't touch a profile still
    see the same baseline behaviour they always saw.

The schema returned by `derive_operating_profile()`:

    {
      "tone_prose": {
        "warm-club": "english prose describing how 'warm-club' should
                      feel FOR THIS ORG specifically",
        "hype":      "...",
        "data-led":  "...",
        "ai":        "..."         # the default neutral tone
      },
      "achievement_priorities": {
        "pb_confirmed": 1.6,        # multiplier override
        "medal_gold":   0.9,
        ...
        "_default":     1.0
      },
      "type_phrases": {
        "pb_confirmed": "a personal best",   # how this org would say it
        "medal_gold":   "a gold medal",
        ...
      },
      "artefact_voice": {
        "meet_recap":        "tone-specific intent block for this org",
        "swimmer_spotlight": "...",
        ...
      },
      "derived_at":  "ISO8601",
      "status":      "ok" | "no_context" | "error"
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical inventories
#
# These are the keys the rest of the codebase already knows about. The
# AI is asked to produce values for THESE keys — we don't let it invent
# new tones or achievement types, because that would break every
# downstream consumer. Adding a new key here is a deliberate code
# change, not an LLM call.
# ---------------------------------------------------------------------------

CANONICAL_TONES: tuple[str, ...] = ("ai", "warm-club", "hype", "data-led")

CANONICAL_ACHIEVEMENT_TYPES: tuple[str, ...] = (
    "official_pb_confirmed",
    "pb_confirmed",
    "pb_likely",
    "pb_magnitude_huge",
    "pb_magnitude_big",
    "pb_magnitude_notable",
    "first_sub_barrier",
    "medal_gold",
    "medal_silver",
    "medal_bronze",
    "relay_medal_gold",
    "relay_medal_silver",
    "relay_medal_bronze",
    "qual_hit_in_window",
    "qual_hit_out_of_window",
    "top_of_field_top_3",
    "top_of_field_top_5",
    "top_of_field_top_10",
    "multi_pb_weekend",
    "biggest_drop_candidate",
    "biggest_drop_of_meet",
    "return_to_form",
    "fastest_since",
    "fastest_since_date",
    "heat_to_final_drop",
    "final_appearance",
    "qualifying_time",
)

CANONICAL_ARTEFACTS: tuple[str, ...] = (
    "meet_recap",
    "swimmer_spotlight",
    "data_thread_post",
    "linkedin_long",
    "instagram_long",
    "parent_newsletter",
    "sponsor_thank_you",
    "coach_quote",
    "next_meet_preview",
)


# ---------------------------------------------------------------------------
# Per-platform format constraints
#
# Mechanical, code-controlled rules — NOT AI-derived. These are platform
# product rules (character limits, link behaviour, hashtag conventions)
# that the LLM has no business reinventing every render. The audit's
# separation principle: *creative direction* → AI; *format constraints*
# → code. So tone/intent goes through ``artefact_voice`` (which IS
# AI-derived per org), while these format rules stay fixed.
#
# The constants are referenced by ``platform_format_for(artefact_key)``
# below, which the caption pipeline prepends to its system prompt
# alongside the AI-derived intent and brand context.
# ---------------------------------------------------------------------------

PLATFORM_FORMATS: dict[str, str] = {
    "instagram": (
        "Instagram format rules: keep total length under 2,200 characters; "
        "break into 2-4 short paragraphs separated by blank lines; "
        "hashtags grouped at the very end (not inline); at most 5 hashtags; "
        "no URLs in body (Instagram strips them); no @ mentions of accounts "
        "the user hasn't explicitly listed."
    ),
    "x": (
        "X (Twitter) format rules: STRICT 280-character cap per post — "
        "if you write longer it will be truncated; hashtags may appear "
        "inline; URLs count as 23 characters regardless of length; "
        "do not use line-break-heavy formatting; one or two emoji "
        "maximum unless the voice profile explicitly says no emoji."
    ),
    "linkedin": (
        "LinkedIn format rules: 150-300 words; professional register; "
        "open with a hook line that stands alone; one short paragraph "
        "per idea; hashtags at the end, 3-5 maximum; URLs render with "
        "a preview card so place them on their own line; never use "
        "Twitter-style abbreviation."
    ),
    "tiktok": (
        "TikTok caption format rules: keep under 150 characters so the "
        "full caption is visible on first tap; hashtags integrated at "
        "the end; lead with a hook; this is the caption beneath the "
        "video, not the video script."
    ),
    "facebook": (
        "Facebook format rules: 1-3 short paragraphs; hashtags at the "
        "end and limited to 2-3; URLs render with preview cards; "
        "longer-form than Instagram but shorter than LinkedIn."
    ),
    "email": (
        "Email/newsletter format rules: paragraphs separated by blank "
        "lines; no inline hashtags (they make email look like social "
        "spam); URLs allowed; sign off with a short close; treat this "
        "as something a parent reads on their phone over breakfast."
    ),
    "generic": (
        "Format: standard social-post shape — one or two short "
        "paragraphs, hashtags at the end if any, no platform-specific "
        "tricks."
    ),
}

# Artefact-key → platform mapping. Anything not listed defaults to "generic".
ARTEFACT_PLATFORM: dict[str, str] = {
    "instagram_long": "instagram",
    "data_thread_post": "x",
    "linkedin_long": "linkedin",
    "parent_newsletter": "email",
}


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You configure another AI system that will write social-media "
    "content for a specific sports club, society or team. You will be "
    "given a brand context block describing the organisation. Produce a "
    "single JSON object that captures, FOR THIS ORG SPECIFICALLY: "
    "(1) how each tone should feel, (2) which achievement types matter "
    "more or less to them, (3) the exact noun phrase they would use for "
    "each achievement type, and (4) the per-artefact creative intent. "
    "Be faithful to the brand context — never invent values you can't "
    "ground in the brief. When the brief is silent on something, leave "
    "that key out (the downstream system has sensible defaults)."
)


def _build_prompt(brand_context: str) -> str:
    tones = ", ".join(f'"{t}"' for t in CANONICAL_TONES)
    ach_types = ", ".join(f'"{t}"' for t in CANONICAL_ACHIEVEMENT_TYPES)
    artefacts = ", ".join(f'"{a}"' for a in CANONICAL_ARTEFACTS)
    return (
        "Brand context for this organisation:\n\n"
        "===== BEGIN CONTEXT =====\n"
        f"{brand_context}\n"
        "===== END CONTEXT =====\n\n"
        "Return a SINGLE JSON object with EXACTLY these top-level keys "
        "(no prose, no fences):\n\n"
        f"  tone_prose: object keyed by the tone slugs ({tones}). Each "
        "value is a one-sentence English description of how THAT tone "
        "should feel for THIS organisation specifically. Reflect their "
        "voice, audience, prohibited words, and any guidelines you saw.\n\n"
        f"  achievement_priorities: object keyed by achievement type "
        f"({ach_types}). Each value is a number between 0.3 and 2.0 "
        "expressing how much THIS organisation cares about that type "
        "of moment relative to others. Use 1.0 as neutral. A community "
        'club might boost "first_sub_barrier" and "pb_confirmed"; an '
        'elite team might boost "medal_gold". Also include a '
        '"_default" key (typically 1.0) for types you don\'t have an '
        "opinion on. Only include types where the brief gives you "
        'reason to deviate from 1.0 — silence means "use the default".\n\n'
        f"  type_phrases: object keyed by achievement type. Each value "
        "is the SHORT noun phrase (3-6 words) this org would naturally "
        "use to refer to that achievement when narrating it. E.g. for "
        '"pb_confirmed" a community club might say "a brand-new '
        'personal best" but a data-led elite team might say "a '
        'verified PB". Only include types where the brief gives you '
        'language guidance — silence means "use the default phrase".\n\n'
        f"  artefact_voice: object keyed by artefact type ({artefacts}). "
        "Each value is a 1-2 sentence creative intent: what should this "
        "org's version of that artefact feel like? Lead with the angle, "
        "not the format constraints (the format constraints are handled "
        "elsewhere). Only include artefacts where the brief gives you "
        'an opinion — silence means "use the default intent".\n'
    )


def _call_llm(brand_context: str) -> Optional[dict]:
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return None
    if not is_available():
        return None
    prompt = _build_prompt(brand_context)
    try:
        return generate_json(
            prompt,
            system=_LLM_SYSTEM,
            max_tokens=3_000,
            fallback={},
        )
    except Exception as e:
        log.debug("derived operating-profile LLM call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _norm_str(v, cap: int) -> str:
    return str(v).strip()[:cap] if isinstance(v, str) and v.strip() else ""


def _norm_tone_prose(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, v in raw.items():
        if k in CANONICAL_TONES:
            cleaned = _norm_str(v, 400)
            if cleaned:
                out[k] = cleaned
    return out


def _norm_priorities(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    allowed = set(CANONICAL_ACHIEVEMENT_TYPES) | {"_default"}
    for k, v in raw.items():
        if k not in allowed:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        # Clamp to a sane band so a hallucinated 50× weight can't tank
        # the ranker.
        f = max(0.3, min(2.0, f))
        out[k] = f
    return out


def _norm_type_phrases(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, v in raw.items():
        if k not in CANONICAL_ACHIEVEMENT_TYPES:
            continue
        cleaned = _norm_str(v, 120)
        if cleaned:
            out[k] = cleaned
    return out


def _norm_artefact_voice(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, v in raw.items():
        if k not in CANONICAL_ARTEFACTS:
            continue
        cleaned = _norm_str(v, 500)
        if cleaned:
            out[k] = cleaned
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_operating_profile(profile) -> dict:
    """Run one LLM call to convert a profile's brand context into a
    cached operating profile (tone prose, priority weights, type
    phrases, artefact voice).

    Args:
        profile: a ClubProfile (or dict).

    Returns:
        A dict in the shape documented at the top of this module.
        Returns a ``no_context`` stub (no LLM call) when the profile
        has no brand context yet — that's a routine state, not an
        error.

    Raises:
        ClaudeUnavailableError: when a brand context exists but the
        configured cloud LLM provider is unreachable or returns nothing
        usable. Callers must catch this and surface an honest "AI
        unavailable" status to the operator rather than silently
        proceeding with a fabricated profile.
    """
    empty = {
        "tone_prose": {},
        "achievement_priorities": {},
        "type_phrases": {},
        "artefact_voice": {},
        "derived_at": _now_iso(),
        "status": "no_context",
    }
    try:
        from mediahub.brand.context import brand_context_for_llm
    except Exception:
        return empty
    ctx = brand_context_for_llm(profile)
    if not ctx.strip():
        return empty
    raw = _call_llm(ctx)
    if not raw:
        from mediahub.media_ai.llm import ClaudeUnavailableError

        raise ClaudeUnavailableError(
            "No cloud LLM provider is reachable; cannot derive operating "
            "profile. Configure GEMINI_API_KEY or ANTHROPIC_API_KEY."
        )
    out = {
        "tone_prose": _norm_tone_prose(raw.get("tone_prose")),
        "achievement_priorities": _norm_priorities(raw.get("achievement_priorities")),
        "type_phrases": _norm_type_phrases(raw.get("type_phrases")),
        "artefact_voice": _norm_artefact_voice(raw.get("artefact_voice")),
        "derived_at": _now_iso(),
        "status": "ok",
    }
    if not any(
        (
            out["tone_prose"],
            out["achievement_priorities"],
            out["type_phrases"],
            out["artefact_voice"],
        )
    ):
        from mediahub.media_ai.llm import ClaudeUnavailableError

        raise ClaudeUnavailableError("The LLM returned no usable signal for the operating profile.")
    return out


# ---------------------------------------------------------------------------
# Lookup helpers — used by every downstream consumer
# ---------------------------------------------------------------------------


def _get_op_profile(profile) -> dict:
    if profile is None:
        return {}
    if isinstance(profile, dict):
        op = profile.get("brand_operating_profile") or {}
    else:
        op = getattr(profile, "brand_operating_profile", None) or {}
    return op if isinstance(op, dict) else {}


def tone_descriptor_for(profile, tone_slug: str, default: str) -> str:
    """Return the per-org tone prose for ``tone_slug``, or ``default``
    if the org hasn't been re-derived or didn't get this slug."""
    op = _get_op_profile(profile)
    val = (op.get("tone_prose") or {}).get(tone_slug)
    if isinstance(val, str) and val.strip():
        return val
    return default


def priority_for(profile, ach_type: str, default: float) -> float:
    """Return this org's priority multiplier for ``ach_type``, or
    ``default`` (and ultimately the global default of 1.0)."""
    op = _get_op_profile(profile)
    prio = op.get("achievement_priorities") or {}
    if ach_type in prio:
        try:
            return float(prio[ach_type])
        except (TypeError, ValueError):
            pass
    if "_default" in prio:
        try:
            return float(prio["_default"])
        except (TypeError, ValueError):
            pass
    return default


def type_phrase_for(profile, ach_type: str, default: str) -> str:
    """Return the noun phrase this org would use for ``ach_type``."""
    op = _get_op_profile(profile)
    val = (op.get("type_phrases") or {}).get(ach_type)
    if isinstance(val, str) and val.strip():
        return val
    return default


def artefact_intent_for(profile, artefact_key: str, default: str) -> str:
    """Return the creative intent for ``artefact_key`` as this org would
    voice it."""
    op = _get_op_profile(profile)
    val = (op.get("artefact_voice") or {}).get(artefact_key)
    if isinstance(val, str) and val.strip():
        return val
    return default


def platform_format_for(artefact_key: str) -> str:
    """Return the mechanical platform-format rules for an artefact.

    Unlike the other helpers, this is intentionally NOT profile-aware
    and NOT AI-derived: the format constraints are platform product
    rules (character limits, hashtag conventions, link behaviour) that
    don't change between organisations. Mixing them into the AI-derived
    voice would let the LLM forget about a character cap during a
    "creative" rewrite.

    Returns the rules string or "" when no platform is known.
    """
    platform = ARTEFACT_PLATFORM.get(artefact_key, "generic")
    return PLATFORM_FORMATS.get(platform, PLATFORM_FORMATS["generic"])


__all__ = [
    "CANONICAL_TONES",
    "CANONICAL_ACHIEVEMENT_TYPES",
    "CANONICAL_ARTEFACTS",
    "PLATFORM_FORMATS",
    "ARTEFACT_PLATFORM",
    "derive_operating_profile",
    "tone_descriptor_for",
    "priority_for",
    "type_phrase_for",
    "artefact_intent_for",
    "platform_format_for",
]
