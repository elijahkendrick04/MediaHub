"""
ai_caption.py — Generate captions via the multi-provider ai_core.

User direction: replace JSON-shaped prompts and hardcoded fallback
templates with natural-language prompts the model can reason about.
Captions are written by Claude / Gemini (whichever the operator has
configured via env vars). There is NO heuristic fallback — if no provider is
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

import os
import random
import re
import sys
from pathlib import Path
from typing import Optional

from mediahub.web.languages import (
    caption_language_instruction,
    get_language,
    language_setting_for,
    normalise_language_setting,
    primary_language_for,
    secondary_caption_rules,
    split_language_setting,
)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class ClaudeUnavailableError(RuntimeError):
    """Raised when no provider can produce a caption (kept name for
    backwards compatibility with existing imports in web.py)."""


def call_claude(system: str, user: str, max_tokens: int = 400, **_kwargs) -> str:
    """Thin wrapper kept for tests + back-compat. Delegates to ai_core
    so the active provider (Claude / Gemini) actually runs."""
    from mediahub.ai_core import (
        ask,
        ProviderNotConfigured,
        ProviderError,
    )

    try:
        return ask(system, user, max_tokens=max_tokens) or ""
    except ProviderNotConfigured as e:
        raise ClaudeUnavailableError(str(e)) from e
    except ProviderError as e:
        raise ClaudeUnavailableError(str(e)) from e


# Default tone descriptors. These ship as fallbacks for the case where
# the org hasn't had its operating profile derived yet (older profiles,
# new installs, no-LLM environments). When the org HAS been derived,
# brand.derived.tone_descriptor_for() returns the org-specific prose
# instead — see the resolution inside generate_caption_for_tone below.
#
# Adding a new tone slug here is a deliberate code change because every
# downstream consumer that wants to use it needs to know it exists; we
# don't let the LLM invent tones.
_TONE_DESCRIPTORS: dict[str, str] = {
    "ai": "a balanced editorial sports voice — natural and "
    "specific. Vary your opening from caption to caption; "
    "include at least one concrete fact (time, place, "
    "event or venue).",
    "warm-club": "club-family warmth, written first-person plural "
    "(we/our). Speak to the community directly and "
    "mention supporters or coaches naturally. Gentle, "
    "unhurried pace. At most 1 emoji.",
    "hype": "high energy. Short, punchy sentences — no sentence "
    "over 10 words. Present tense. Urgency and "
    "exclamation. Lead with the moment, not the name. "
    "1-2 emoji allowed. NO reflective sentiment.",
    "data-led": "numbers first — open with the time or placing "
    'figure. No subjective adjectives (never "fantastic", '
    '"incredible", "well-deserved", "amazing"). '
    "Sponsor-safe neutral register. No emoji. No "
    "exclamation marks.",
}

KNOWN_AI_TONES: frozenset[str] = frozenset(_TONE_DESCRIPTORS.keys())


# ---------------------------------------------------------------------------
# AI-tell ban list
# ---------------------------------------------------------------------------

AI_TELL_BAN_LIST: frozenset[str] = frozenset(
    {
        "delve",
        "delves",
        "delving",
        "elevate",
        "elevates",
        "elevated",
        "elevating",
        "in the world of",
    }
)

_AI_TELL_SYSTEM_INSTRUCTION: str = (
    "Never use these overworked AI phrases: "
    '"delve", "elevate", "in the world of". '
    "Avoid reflexive exclamation marks — use '!' only when the moment "
    "genuinely warrants it, not as empty emphasis."
)


_COURSE_SUFFIX_RE = re.compile(r"\s*\(\s*(SC|LC)\s*\)\s*$", re.IGNORECASE)

_COURSE_SPELLED = {"SC": "short course", "LC": "long course"}

_NO_COURSE_ABBREV_INSTRUCTION: str = (
    'Never write the abbreviations "(SC)" or "(LC)" — say "short course"/'
    '"long course" only if the distinction genuinely matters, otherwise '
    "omit it."
)

_SHARED_TONE_BANS: str = (
    'Do not open with "Another …" or "What a …"; never use the phrase "testament to".'
)


def _strip_course_suffix(event: str) -> str:
    """Remove a trailing "(SC)" / "(LC)" course marker from an event name.

    MR-5: course jargon like "100m Breaststroke (SC)" leaked into every
    published caption. The abbreviation means nothing to a parent
    scrolling a feed, so it never belongs in prompt-visible event names.
    Case-insensitive; tolerates surrounding whitespace.
    """
    if not event:
        return event
    return _COURSE_SUFFIX_RE.sub("", event).strip()


# Data-minimisation boundary (UK GDPR Art 5(1)(c)): identifiers and
# DOB-adjacent fields a caption never needs MUST NOT leave the platform in
# an LLM payload. Age/age-group stay (captions legitimately say "12-year-old
# PB") — see docs/compliance/DATA_MAP.md flow F1.
_PROMPT_DROP_KEYS = frozenset(
    {
        "asa_id",
        "member_id",
        "dob",
        "date_of_birth",
        "birth_date",
        "yob",
        "year_of_birth",
    }
)


def _sanitise_achievement_for_prompt(a: dict) -> dict:
    """Return a shallow copy of the achievement with course jargon
    removed from the event name and the ``course`` field spelled out
    ("SC" → "short course") so the raw distinction stays available for
    data-led time context without the abbreviation ever reaching the
    LLM's source prose. Also the data-minimisation boundary: registry
    identifiers and DOB-level fields are stripped before the payload
    leaves the platform (top level and inside ``raw_facts``)."""
    if not isinstance(a, dict):
        return a
    out = {k: v for k, v in a.items() if k.lower() not in _PROMPT_DROP_KEYS}
    raw_facts = out.get("raw_facts")
    if isinstance(raw_facts, dict):
        out["raw_facts"] = {
            k: v for k, v in raw_facts.items() if k.lower() not in _PROMPT_DROP_KEYS
        }
    event = (out.get("event") or "").strip()
    if event:
        out["event"] = _strip_course_suffix(event)
    course = (out.get("course") or "").strip()
    if course:
        out["course"] = _COURSE_SPELLED.get(course.upper(), course)
    return out


def _locale_instruction(club_profile) -> str:
    """MR-7: derive a spelling-locale instruction from the club's country.

    UK organisations were getting US spellings ("program") in published
    captions. Returns "" when no country is set.
    """
    if club_profile is None:
        return ""
    if isinstance(club_profile, dict):
        country = (club_profile.get("country") or "").strip()
    else:
        country = (getattr(club_profile, "country", "") or "").strip()
    if not country:
        return ""
    uk_names = {
        "united kingdom",
        "uk",
        "great britain",
        "england",
        "scotland",
        "wales",
        "northern ireland",
    }
    if country.lower() in uk_names:
        return "Write in British English (programme, recognise, centre, organise; metres)."
    return f"Write in the natural English variant for {country}."


def _contains_ai_tell(text: str) -> bool:
    """Return True if text contains any phrase from the ban list."""
    lower = text.lower()
    return any(phrase in lower for phrase in AI_TELL_BAN_LIST)


# ---------------------------------------------------------------------------
# N-gram similarity helpers (no external deps)
# ---------------------------------------------------------------------------


def _word_ngrams(text: str, n: int) -> set[str]:
    """Return the set of word n-grams for text after stripping punctuation."""
    tokens = re.sub(r"[^\w\s]", "", text.lower()).split()
    if not tokens:
        return set()
    if len(tokens) < n:
        return set(tokens)
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _ngram_similarity(a: str, b: str, n: int = 3) -> float:
    """Trigram Jaccard similarity — 0.0 (completely different) to 1.0 (identical)."""
    na, nb = _word_ngrams(a, n), _word_ngrams(b, n)
    if not na or not nb:
        return 0.0
    union = na | nb
    return len(na & nb) / len(union) if union else 0.0


def _is_near_duplicate(candidate: str, reference_list: list[str], threshold: float = 0.55) -> bool:
    """Return True if candidate is too similar to any string in reference_list."""
    return any(_ngram_similarity(candidate, ref) >= threshold for ref in reference_list)


def filter_caption_variants(
    variants: list[str],
    recent_captions: Optional[list[str]] = None,
    *,
    dedupe_threshold: float = 0.55,
) -> list[str]:
    """Shared post-filter for multi-variant caption surfaces.

    Collapses exact and trigram near-duplicates (against ``recent_captions``
    and the variants already kept, order preserved) and drops candidates that
    contain ban-list AI-tells — the same quality gates
    :func:`generate_caption_candidates` applies during generation, packaged
    for callers that already hold a produced list (the live caption route's
    variants). Fail-open: if filtering would empty a non-empty input, the
    first original variant is returned — a slightly stale caption beats none.
    """
    cleaned = [v.strip() for v in (variants or []) if v and v.strip()]
    if not cleaned:
        return []
    recents = [r for r in (recent_captions or []) if r and r.strip()]
    kept: list[str] = []
    for v in cleaned:
        if v in kept:
            continue
        if _contains_ai_tell(v):
            continue
        if _is_near_duplicate(v, recents + kept, threshold=dedupe_threshold):
            continue
        kept.append(v)
    return kept or [cleaned[0]]


# ---------------------------------------------------------------------------
# Platform format specifications for generate_platform_variants
# ---------------------------------------------------------------------------

_PLATFORM_SPECS: dict[str, dict] = {
    "feed": {
        "label": "Instagram/Facebook feed",
        "max_chars": 280,
        "guidance": (
            "casual and warm, emoji welcome, 1–3 hashtags, reads naturally in a feed scroll"
        ),
    },
    "story": {
        "label": "Instagram/TikTok story",
        "max_chars": 100,
        "guidance": (
            "punchy single sentence, no hashtags, fits on a visual card, immediate impact"
        ),
    },
    "x": {
        "label": "X (Twitter)",
        "max_chars": 280,
        "guidance": "snappy, 1–2 hashtags only, link-friendly, punchy opener",
    },
    "linkedin": {
        "label": "LinkedIn",
        "max_chars": 500,
        "guidance": (
            "professional tone, full sentences, no casual emoji, "
            "sponsor-friendly, suitable for a wider audience"
        ),
    },
}


def _resolve_tone_descriptor(club_profile, tone: str) -> str:
    """Return the tone descriptor for this org, falling back to the
    hardcoded default. The derived path lets each org's tone prose
    reflect their brand context (audience, voice, guidelines) rather
    than every org sharing the same generic phrasing."""
    default = _TONE_DESCRIPTORS.get(tone, _TONE_DESCRIPTORS["ai"])
    try:
        from mediahub.brand.derived import tone_descriptor_for
    except Exception:
        return default
    return tone_descriptor_for(club_profile, tone, default)


def _resolve_voice_profile(club_profile) -> Optional[dict]:
    """Return a usable voice_profile dict from a ClubProfile-like object."""
    if club_profile is None:
        return None
    if isinstance(club_profile, dict):
        vp = club_profile.get("voice_profile")
        return vp if isinstance(vp, dict) and vp else None
    vp = getattr(club_profile, "voice_profile", None)
    return vp if isinstance(vp, dict) and vp else None


def _brand_dna_prose(club_profile) -> str:
    """Canonical brand briefing for the caption LLM. Delegates to
    brand.context.brand_context_for_llm so captions and every other
    content tool share one truth-source.
    """
    try:
        from mediahub.brand.context import brand_context_for_llm
    except Exception:
        return ""
    return brand_context_for_llm(club_profile)


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
        "first_name": "Address the swimmer by first name only.",
        "last_name": "Address the swimmer by their full name with surname.",
        "surname_only": "Address the swimmer by surname only (broadcast style).",
        "nickname": "Address the swimmer in a familiar, nickname-style way.",
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


def _llm_pseudonymise_enabled() -> bool:
    """MEDIAHUB_LLM_PSEUDONYMISE=1 — data minimisation toward LLM providers.

    When on, the athlete's name is replaced with a neutral token in the
    prompt and restored in the returned caption, so the cloud provider never
    receives the child's name. Trade-off (documented in .env.example and the
    DPIA): name-style nuance (first-name vs surname address) flattens to the
    full name, and brief-prose callers (the content engine) are not covered
    because the name isn't separable there. Off by default.
    """
    return (os.environ.get("MEDIAHUB_LLM_PSEUDONYMISE") or "").strip() == "1"


_PSEUDONYM_TOKEN = "Athlete A"


def _pseudonymise_prose(prose: str, swimmer_name: str) -> tuple[str, bool]:
    """Replace the swimmer's full name (and bare first name) with the token.

    Returns (new_prose, replaced_anything).
    """
    name = (swimmer_name or "").strip()
    if not name:
        return prose, False
    out = re.sub(re.escape(name), _PSEUDONYM_TOKEN, prose, flags=re.IGNORECASE)
    first = name.split()[0]
    if len(first) >= 3 and first.lower() != _PSEUDONYM_TOKEN.lower():
        out = re.sub(rf"\b{re.escape(first)}\b", _PSEUDONYM_TOKEN, out, flags=re.IGNORECASE)
    return out, out != prose


def _restore_pseudonym(text: str, swimmer_name: str) -> str:
    return re.sub(re.escape(_PSEUDONYM_TOKEN), swimmer_name.strip(), text, flags=re.IGNORECASE)


def generate_caption_for_tone(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    voice_profile: Optional[dict] = None,
    club_profile=None,
    recent_captions: Optional[list[str]] = None,
    *,
    language: Optional[str] = None,
    brief_prose: Optional[str] = None,
    direction: Optional[dict] = None,
    requirements: str = "",
    few_shot_examples: Optional[list[str]] = None,
) -> str:
    """Generate one caption. Raises ClaudeUnavailableError if no provider
    can answer. NO heuristic fallback — that's intentional; a fake caption
    is worse than an honest error.

    The caption is written in the workspace's primary caption language:
    ``language`` (a ``web.languages`` code) when given, otherwise derived
    from ``club_profile.language``. Every caller that passes a
    ``club_profile`` — content engine, turn-into, sponsor variants,
    caption assist, autonomy — honours the workspace language with no
    per-caller wiring, and the same holds for future callers.

    ``recent_captions`` is an optional list of the last few captions the
    user has seen for this card; when provided the system prompt tells
    the AI to write something distinct so clicking "regenerate" never
    returns the same wording twice.

    This is the single caption-writing primitive shared by meet recap and the
    unified ``content_engine``. Achievement-led callers (meet recap, athlete
    spotlight, sponsor variants, turn-into) pass an ``achievement_dict`` and
    the prose is built via ``narrate_achievement``. Brief-led callers (the
    content engine) pass ready-made ``brief_prose`` instead. ``direction`` is
    the AI Director's per-card plan (``{lens, hook, platform}``) and
    ``requirements`` is a one-line description of what the brief is — both are
    folded into the system prompt when present.
    """
    system, user_prose = _compose_caption_prompt(
        achievement_dict,
        club_brand=club_brand,
        tone=tone,
        voice_profile=voice_profile,
        club_profile=club_profile,
        recent_captions=recent_captions,
        language=language,
        brief_prose=brief_prose,
        direction=direction,
        requirements=requirements,
        few_shot_examples=few_shot_examples,
    )
    # Tiny random suffix breaks identical-output caching at the provider's
    # end without leaking into the visible caption (the prompt asks for
    # caption-only output, so the model will not echo the seed).
    nonce = random.randint(10_000, 99_999)
    user_prose = user_prose + f"\n\n[Generate a fresh caption. seed={nonce}]"

    # Data minimisation (MEDIAHUB_LLM_PSEUDONYMISE=1): swap the athlete's
    # name for a neutral token before the prompt leaves the box; restore it
    # in the returned caption. Only achievement-led calls carry a separable
    # name; brief-prose calls go through unchanged (see helper docstring).
    swimmer_name = str((achievement_dict or {}).get("swimmer_name") or "").strip()
    pseudonymised = False
    if _llm_pseudonymise_enabled() and swimmer_name and not brief_prose:
        user_prose, pseudonymised = _pseudonymise_prose(user_prose, swimmer_name)

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
    if pseudonymised:
        text = _restore_pseudonym(text, swimmer_name)
    return text


def _compose_caption_prompt(
    achievement_dict: dict,
    *,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    voice_profile: Optional[dict] = None,
    club_profile=None,
    recent_captions: Optional[list[str]] = None,
    language: Optional[str] = None,
    brief_prose: Optional[str] = None,
    direction: Optional[dict] = None,
    requirements: str = "",
    few_shot_examples: Optional[list[str]] = None,
) -> tuple[str, str]:
    """Build the (system, user) prompt pair shared by the caption-only
    primitive and the W.11/W.13 bundle. Raises ClaudeUnavailableError when
    the source facts are too thin to write from.

    ``language`` is the primary caption language (a ``web.languages``
    code); when None it is derived from ``club_profile.language``, so any
    caller passing a profile writes in the workspace's language without
    extra wiring. Unknown codes fall back to English."""
    from mediahub.ai_core import narrate_achievement, narrate_brand

    primary_language, _ = split_language_setting(
        language if language is not None else language_setting_for(club_profile)
    )
    tone_desc = _resolve_tone_descriptor(club_profile, tone)
    resolved_vp = _resolve_voice_profile(club_profile) or (
        voice_profile if isinstance(voice_profile, dict) else None
    )
    vp_prose = _voice_profile_prose(resolved_vp)

    from mediahub.ai_core.prompt_guard import SYSTEM_GUARD as _SYSTEM_GUARD

    system_parts = [
        "You are a sports social-media writer. Produce ONE caption for a "
        "single swimming achievement.",
        _SYSTEM_GUARD,
        "Tone: " + tone_desc,
        "Keep it specific, human, club-appropriate, ~280 characters max. "
        "Never invent facts. Output ONLY the caption text — no preamble, "
        "no quotes, no markdown.",
        _AI_TELL_SYSTEM_INSTRUCTION,
        _NO_COURSE_ABBREV_INSTRUCTION,
        _SHARED_TONE_BANS,
        # Force genuine variety. The model has a strong attractor toward
        # the same opener / same closer wording on identical inputs;
        # this instruction nudges it off the attractor.
        "When you write, pick a fresh angle and structure: vary your "
        "opener, the order in which facts appear, and the closing beat. "
        "If you've been shown recent captions for this card, write "
        "something noticeably different from each — different opener, "
        "different rhythm, different lens (e.g. swimmer's effort vs. "
        "the team's reaction vs. the numbers vs. the milestone).",
    ]
    # Workspace caption language (W.13, generalised): one registry-driven
    # instruction line makes the model write in the workspace's primary
    # language. English-variant spelling guidance only applies when the
    # output actually IS English.
    language_line = caption_language_instruction(primary_language)
    if language_line:
        system_parts.append(language_line)
    locale_line = _locale_instruction(club_profile) if not language_line else ""
    if locale_line:
        system_parts.append(locale_line)
    if recent_captions:
        recent_block = "\n".join(f"- {c.strip()}" for c in recent_captions[-5:] if c and c.strip())
        if recent_block:
            system_parts.append(
                "Recent captions you wrote for this same card (DO NOT "
                "repeat any of their openers, structure, or closers — "
                "the user wants something different):\n" + recent_block
            )
    brand_prose = narrate_brand(club_brand)
    if brand_prose:
        system_parts.append("Brand voice: " + brand_prose)
    # _brand_dna_prose now delegates to brand.context.brand_context_for_llm,
    # which already weaves identity + captured DNA + voice profile +
    # uploaded brand-guidelines into a single coherent block. We only
    # fall back to the standalone _voice_profile_prose for the legacy
    # path where a free-floating voice_profile dict is passed without
    # any club_profile object.
    dna_prose = _brand_dna_prose(club_profile)
    if dna_prose:
        system_parts.append(dna_prose)
    elif vp_prose:
        system_parts.append("Voice profile from past captions: " + vp_prose)
    # Few-shot voice examples — real captions approved by the club. Injected
    # after the voice-profile block so they reinforce (not override) the
    # abstract voice guidance. Capped at 5; most-recent examples are most
    # representative of the current voice.
    if few_shot_examples:
        capped = [e.strip() for e in few_shot_examples[-5:] if e and e.strip()]
        if capped:
            block = "\n".join(f"- {e}" for e in capped)
            system_parts.append(
                "Voice examples — real captions this club has published "
                "(match their voice and style):\n" + block
            )
    # Per-artefact creative intent (AI-derived per org via brand.derived,
    # falls back to the hardcoded intent) — surfaces here so the LLM
    # actually receives it. This was previously written onto the
    # achievement payload but never read; that bug is fixed here.
    artefact_intent = (achievement_dict or {}).get("_artefact_intent") or ""
    if artefact_intent:
        system_parts.append("Creative intent for this piece: " + artefact_intent)
    # Per-platform mechanical format rules. NOT AI-derived — these are
    # platform product rules (character caps, hashtag conventions, link
    # behaviour) that the LLM has no business reinventing per render.
    artefact_key = (achievement_dict or {}).get("_artefact_key") or ""
    if artefact_key:
        try:
            from mediahub.brand.derived import platform_format_for

            fmt = platform_format_for(artefact_key)
            if fmt:
                system_parts.append(fmt)
        except Exception:
            pass
    # Content-engine grounding: what kind of brief this is, plus the AI
    # Director's per-card plan (platform / angle / hook). Present only when
    # the engine calls this primitive; the meet-recap path leaves them blank.
    if requirements:
        system_parts.append("This brief is: " + requirements)
    if isinstance(direction, dict):
        dbits = []
        platform = (direction.get("platform") or "").strip()
        lens = (direction.get("lens") or "").strip()
        hook = (direction.get("hook") or "").strip()
        if platform:
            dbits.append(f"target platform {platform}")
        if lens:
            dbits.append(f"angle/lens: {lens}")
        if hook:
            dbits.append(f"opening hook idea: {hook}")
        if dbits:
            system_parts.append(
                "Creative direction for THIS card (honour the platform + "
                "angle, but write the caption in your own fresh words): " + "; ".join(dbits) + "."
            )
    # Any caller-supplied extra instructions get appended last so they
    # take precedence over generic guidance. Used by the sponsor-variant
    # generator to inject "acknowledge sponsor X" requirements.
    extra = (achievement_dict or {}).get("_extra_instructions") or ""
    if extra:
        system_parts.append("Additional requirement for this caption: " + extra)
    system = "\n\n".join(system_parts)

    # User message is a single English paragraph describing the source — no
    # JSON envelope, no field names. Brief-led callers (the content engine)
    # hand us ready-made prose; achievement-led callers narrate the swim.
    if brief_prose and brief_prose.strip():
        user_prose = brief_prose.strip()
    else:
        # MR-5: strip "(SC)"/"(LC)" jargon from the event name (and spell
        # out the course field) before the facts are narrated into the
        # prompt. The caller's dict is never mutated.
        # Children's Code backstop at the LLM boundary: legacy runs persisted
        # before the tenant enabled child controls still get the transformed
        # identity (pipeline-time transform covers new runs).
        from mediahub.compliance.child_policy import apply_to_achievement

        _payload = apply_to_achievement(
            club_profile, _sanitise_achievement_for_prompt(achievement_dict)
        )
        user_prose = narrate_achievement(
            _payload,
            profile=club_profile,
        )
    if not user_prose.strip():
        raise ClaudeUnavailableError("not enough detail to generate a caption")
    # Prompt-injection defence (OWASP LLM01): the prose was assembled from
    # uploaded-file fields, so it rides inside data delimiters; detected
    # instruction-shaped text hardens the wrapper and is logged — never
    # silently rewritten (the human reviewing the card stays the decider).
    # Lives HERE so both generate_caption_for_tone and the W.11 bundle
    # inherit the same boundary.
    from mediahub.ai_core.prompt_guard import delimit_untrusted, scan as _injection_scan

    _injection_hits = _injection_scan(user_prose)
    if _injection_hits:
        try:
            from mediahub.compliance.security_log import record_event as _sec_event

            _sec_event(
                "prompt_injection_suspected",
                detail=f"patterns={','.join(_injection_hits)[:200]}",
                outcome="hardened",
            )
        except Exception:
            pass
    user_prose = delimit_untrusted(user_prose, flagged=bool(_injection_hits))
    return system, user_prose


_BUNDLE_ALT_TEXT_RULES = (
    "alt_text: a factual restatement of the result for screen readers — "
    "who, event, time, what made it notable — under 125 characters, plain "
    "prose, no hashtags, no emojis, no editorialising beyond the facts given."
)


def generate_caption_bundle(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    voice_profile: Optional[dict] = None,
    club_profile=None,
    recent_captions: Optional[list[str]] = None,
    *,
    language: Optional[str] = None,
    brief_prose: Optional[str] = None,
    direction: Optional[dict] = None,
    requirements: str = "",
    few_shot_examples: Optional[list[str]] = None,
) -> dict:
    """One LLM call → caption + result-grounded alt text (+ translated
    variant for bilingual workspaces).

    W.11/W.13 (generalised beyond Welsh): the alt text and the
    side-by-side translation ride the SAME provider call as the caption —
    zero added latency or cost. Returns ``{"caption": str, "alt_text":
    str, "caption_secondary": str|None, "secondary_language": str|None}``.

    ``language`` accepts any ``web.languages`` setting: a single code
    ("en", "cy", "ga", "zh", …) writes the caption AND alt text in that
    language; an English-led pair ("en+cy", "en+hi", …) writes the caption
    in English plus a ``caption_secondary`` translation in the paired
    language. The legacy W.13 value "bilingual" still means "en+cy". When
    None, the setting is derived from ``club_profile.language``. Raises
    ClaudeUnavailableError on no provider or a malformed bundle — NO
    heuristic fallback, per the standing AI rule.
    """
    setting = (
        normalise_language_setting(language)
        if language is not None
        else language_setting_for(club_profile)
    )
    primary_language, secondary_language = split_language_setting(setting)
    system, user_prose = _compose_caption_prompt(
        achievement_dict,
        club_brand=club_brand,
        tone=tone,
        voice_profile=voice_profile,
        club_profile=club_profile,
        recent_captions=recent_captions,
        language=primary_language,
        brief_prose=brief_prose,
        direction=direction,
        requirements=requirements,
        few_shot_examples=few_shot_examples,
    )
    keys = ["caption", "alt_text"]
    lang_rules = []
    if secondary_language:
        keys.append("caption_secondary")
        lang_rules.append(secondary_caption_rules(secondary_language))
    contract = (
        "OUTPUT CONTRACT — this overrides any earlier output instruction: "
        "respond with ONLY a JSON object (no markdown fences, no prose) with "
        f"exactly these keys: {', '.join(keys)}. "
        '"caption" follows every rule above. ' + _BUNDLE_ALT_TEXT_RULES
    )
    if lang_rules:
        contract += " " + " ".join(lang_rules)
    system = system + "\n\n" + contract

    nonce = random.randint(10_000, 99_999)
    user_prose = user_prose + f"\n\n[Generate a fresh caption. seed={nonce}]"

    # Data minimisation (MEDIAHUB_LLM_PSEUDONYMISE=1): swap the athlete's
    # name for a neutral token before the prompt leaves the box; restore it
    # in every returned bundle field. Only achievement-led calls carry a
    # separable name; brief-prose calls go through unchanged (see helper
    # docstring).
    swimmer_name = str((achievement_dict or {}).get("swimmer_name") or "").strip()
    pseudonymised = False
    if _llm_pseudonymise_enabled() and swimmer_name and not brief_prose:
        user_prose, pseudonymised = _pseudonymise_prose(user_prose, swimmer_name)

    try:
        text = call_claude(system=system, user=user_prose, max_tokens=700)
    except ClaudeUnavailableError:
        raise
    bundle = _parse_bundle_json(text or "")
    caption = (bundle.get("caption") or "").strip()
    if not caption:
        raise ClaudeUnavailableError("provider returned a malformed caption bundle")
    alt_text = (bundle.get("alt_text") or "").strip()
    # Only read the translation when one was asked for — a spurious
    # caption_secondary key in monolingual mode is a contract violation
    # and must not leak a translation box into the review UI.
    caption_secondary = None
    if secondary_language:
        caption_secondary = (bundle.get("caption_secondary") or "").strip() or None
        if not caption_secondary:
            sec = get_language(secondary_language)
            raise ClaudeUnavailableError(
                f"provider returned no {sec.name if sec else secondary_language} variant"
            )
    if pseudonymised:
        caption = _restore_pseudonym(caption, swimmer_name)
        if alt_text:
            alt_text = _restore_pseudonym(alt_text, swimmer_name)
        if caption_secondary:
            caption_secondary = _restore_pseudonym(caption_secondary, swimmer_name)
    return {
        "caption": caption,
        "alt_text": alt_text,
        "caption_secondary": caption_secondary,
        "secondary_language": secondary_language if caption_secondary else None,
    }


def _parse_bundle_json(text: str) -> dict:
    """Tolerant JSON extraction: strips code fences and trailing prose."""
    import json as _json

    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ClaudeUnavailableError("provider returned a malformed caption bundle")
    try:
        obj = _json.loads(s[start : end + 1])
    except ValueError as e:
        raise ClaudeUnavailableError("provider returned a malformed caption bundle") from e
    if not isinstance(obj, dict):
        raise ClaudeUnavailableError("provider returned a malformed caption bundle")
    return obj


def generate_ai_caption(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
) -> dict:
    """Generate a live AI caption (default tone). Returns an error-bearing
    dict on failure (no template fallback)."""
    try:
        caption = generate_caption_for_tone(achievement_dict, club_brand, tone="ai")
        return {
            "caption": caption,
            "tone": "ai",
            "fallback": False,
            "fallback_voice": None,
        }
    except ClaudeUnavailableError as e:
        return {
            "caption": "",
            "tone": "ai",
            "fallback": True,
            "fallback_voice": None,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Multi-candidate generation with deduplication
# ---------------------------------------------------------------------------


def generate_caption_candidates(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    n: int = 5,
    recent_captions: Optional[list[str]] = None,
    few_shot_examples: Optional[list[str]] = None,
    club_profile=None,
    *,
    brief_prose: Optional[str] = None,
    direction: Optional[dict] = None,
    requirements: str = "",
    dedupe_threshold: float = 0.55,
) -> list[str]:
    """Generate 4–6 caption candidates, dropping near-duplicates and AI-tells.

    Returns up to ``n`` captions (clamped to 4–6), **ranked freshest-first**:
    candidates are ordered by ascending worst-case trigram similarity to the
    ``recent_captions`` and to each other (ties keep generation order), so the
    caption least like anything the user has already seen leads the list.
    Each candidate is checked against the ban list and against already-seen
    captions (``recent_captions`` plus previously accepted candidates) using
    trigram Jaccard similarity. Raises ``ClaudeUnavailableError`` if the
    provider is unavailable.
    """
    target = max(4, min(6, n))
    pool: list[str] = []
    # seen accumulates recent_captions + accepted candidates; the generator
    # is told to avoid them so similarity filtering converges quickly.
    seen: list[str] = list(recent_captions or [])

    for _ in range(target + 2):
        try:
            candidate = generate_caption_for_tone(
                achievement_dict,
                club_brand,
                tone,
                club_profile=club_profile,
                recent_captions=seen,
                brief_prose=brief_prose,
                direction=direction,
                requirements=requirements,
                few_shot_examples=few_shot_examples,
            )
        except ClaudeUnavailableError:
            raise
        if _contains_ai_tell(candidate):
            continue
        if _is_near_duplicate(candidate, seen, threshold=dedupe_threshold):
            continue
        pool.append(candidate)
        seen.append(candidate)
        if len(pool) >= target:
            break

    # Rank: the candidate least similar to everything already seen (the recent
    # captions and its siblings) comes first — deterministic, explainable, and
    # stable on generation order for ties.
    def _staleness(idx_and_caption: tuple[int, str]) -> tuple[float, int]:
        idx, caption = idx_and_caption
        others = (recent_captions or []) + [c for j, c in enumerate(pool) if j != idx]
        worst = max((_ngram_similarity(caption, o) for o in others), default=0.0)
        return (worst, idx)

    return [c for _, c in sorted(enumerate(pool), key=_staleness)]


# ---------------------------------------------------------------------------
# Per-platform variant generation
# ---------------------------------------------------------------------------


def generate_platform_variants(
    base_caption: str,
    club_brand: Optional[dict] = None,
    club_profile=None,
    *,
    platforms: Optional[list[str]] = None,
    few_shot_examples: Optional[list[str]] = None,
) -> dict[str, str]:
    """Produce per-platform variants from one approved caption.

    ``platforms`` selects the output platforms (default: all four —
    feed, story, x, linkedin). Returns a dict mapping platform key to
    variant caption. Raises ``ClaudeUnavailableError`` if no provider is
    available or ``base_caption`` is empty.
    """
    if not base_caption or not base_caption.strip():
        raise ClaudeUnavailableError("base_caption is empty")

    target_platforms = [
        p for p in (platforms or list(_PLATFORM_SPECS.keys())) if p in _PLATFORM_SPECS
    ]
    if not target_platforms:
        return {}

    from mediahub.ai_core import narrate_brand

    # Workspace caption language: platform adaptations must stay in the
    # language the approved caption was written in (bilingual workspaces
    # adapt the English primary, exactly as before).
    language_line = caption_language_instruction(primary_language_for(club_profile))

    results: dict[str, str] = {}
    for platform in target_platforms:
        spec = _PLATFORM_SPECS[platform]
        system_parts = [
            f"You are a sports social-media writer. Adapt the given caption for {spec['label']}.",
            f"Rules: {spec['guidance']}. Maximum {spec['max_chars']} characters.",
            "Keep all factual details exactly as in the original caption. "
            "Output ONLY the adapted caption — no preamble, no quotes, "
            "no markdown.",
            _AI_TELL_SYSTEM_INSTRUCTION,
            _NO_COURSE_ABBREV_INSTRUCTION,
        ]
        if language_line:
            system_parts.append(language_line)
        locale_line = _locale_instruction(club_profile) if not language_line else ""
        if locale_line:
            system_parts.append(locale_line)
        if few_shot_examples:
            capped = [e.strip() for e in few_shot_examples[-5:] if e and e.strip()]
            if capped:
                block = "\n".join(f"- {e}" for e in capped)
                system_parts.append("Voice examples from this club (match their style):\n" + block)
        brand_prose = narrate_brand(club_brand)
        if brand_prose:
            system_parts.append("Brand voice: " + brand_prose)
        dna_prose = _brand_dna_prose(club_profile)
        if dna_prose:
            system_parts.append(dna_prose)

        system = "\n\n".join(system_parts)
        user = f"Original caption:\n{base_caption.strip()}"
        try:
            variant = call_claude(system=system, user=user, max_tokens=300)
        except ClaudeUnavailableError:
            raise
        results[platform] = (variant or "").strip()

    return results


# ---------------------------------------------------------------------------
# Approval-loop hook
# ---------------------------------------------------------------------------


def record_approved_caption(profile_id: str, caption: str) -> None:
    """Append an edited-and-approved caption to the club's few-shot store.

    Call this whenever a user accepts a caption so future generation for
    this club benefits from its real published voice.
    """
    from mediahub.web.caption_examples import append_example

    append_example(profile_id, caption)


__all__ = [
    "ClaudeUnavailableError",
    "KNOWN_AI_TONES",
    "_strip_course_suffix",
    "AI_TELL_BAN_LIST",
    "generate_ai_caption",
    "generate_caption_for_tone",
    "generate_caption_bundle",
    "generate_caption_candidates",
    "generate_platform_variants",
    "filter_caption_variants",
    "record_approved_caption",
]
