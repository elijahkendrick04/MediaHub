"""The single content-generation engine for MediaHub.

Every content type — the four caption stubs (Event Preview, Sponsor Post,
Session Update, Free Text) and, via the achievement adapter, meet recap /
athlete spotlight — produces its draft cards through ``generate_content``.

The flow mirrors the meet-recap pattern the rest of the product already uses:

  1. An **AI Director** (``content_engine.director.plan_content_directions``)
     decides the creative direction for the set — platform mix, the angle/lens
     of each card, and an opening hook — actively avoiding anything in
     ``recent_cards`` so every regenerate is different.
  2. The **writer** turns that direction into real caption cards. For brief-led
     content it speaks through the ``submit_card`` tool (one structured call,
     captions + hashtags). The director's plan and the avoid-history are folded
     into the system prompt so the model honours the direction.

There is no hand-coded template fallback: when no provider is configured the
writer raises ``ProviderNotConfigured`` / ``ProviderError`` and the caller
surfaces an honest error, exactly as the meet-recap caption path does.
"""

from __future__ import annotations

import json
import random
from typing import Optional

from .director import plan_content_directions


# ---------------------------------------------------------------------------
# Brand context — one truth-source for the active organisation
# ---------------------------------------------------------------------------


def load_brand_context() -> dict:
    """Best-effort load of the ACTIVE ClubProfile for brand voice grounding.

    Resolves through ``current_app.active_profile`` (set on the Flask app in
    ``web.create_app`` so every route shares one definition of "which org am
    I"). Falls back to the most-recently-edited profile on disk only when
    there's no Flask request context — e.g. background jobs or unit tests.
    """
    try:
        from mediahub.web.club_profile import list_profiles, load_profile  # type: ignore
    except Exception:
        return {}
    prof = None
    try:
        from flask import current_app

        get_active = getattr(current_app, "active_profile", None)
        if get_active:
            prof = get_active()
    except Exception:
        prof = None
    if prof is None:
        try:
            profiles = list_profiles()
            if not profiles:
                return {}
            best_pid = None
            try:
                from mediahub.web.club_profile import _profiles_dir  # type: ignore

                d = _profiles_dir()
                best = max(
                    profiles,
                    key=lambda p: (d / f"{getattr(p, 'profile_id', '')}.json").stat().st_mtime,
                )
                best_pid = getattr(best, "profile_id", None)
            except Exception:
                first = profiles[0]
                best_pid = (
                    first.get("profile_id")
                    if isinstance(first, dict)
                    else getattr(first, "profile_id", None)
                )
            if not best_pid:
                return {}
            prof = load_profile(best_pid)
        except Exception:
            prof = None
    if not prof:
        return {}
    try:
        from mediahub.brand.palette import effective_palette

        eff = effective_palette(
            manual=getattr(prof, "brand_palette_manual", {}) or {},
            extracted=getattr(prof, "brand_palette_extracted", {}) or {},
        )
    except Exception:
        eff = {}
    return {
        "name": getattr(prof, "display_name", "") or "",
        "short_name": getattr(prof, "short_name", "") or "",
        "org_type": getattr(prof, "org_type", "") or "",
        "tone": getattr(prof, "tone", "") or "",
        "tone_notes": getattr(prof, "tone_notes", "") or "",
        "exemplars": getattr(prof, "exemplar_captions", []) or [],
        "sponsor_name": getattr(prof, "sponsor_name", "") or "",
        "sponsor_rules": getattr(prof, "sponsor_guidelines", "") or "",
        "voice_summary": (getattr(prof, "brand_voice_summary", "") or "")[:600],
        "keywords": list(getattr(prof, "brand_keywords", []) or [])[:8],
        "phrases_to_use": list(getattr(prof, "brand_phrases_to_use", []) or [])[:6],
        "phrases_to_avoid": list(getattr(prof, "brand_phrases_to_avoid", []) or [])[:6],
        "palette": eff,
    }


# ---------------------------------------------------------------------------
# Writer — tool-based, structured cards
# ---------------------------------------------------------------------------

_SUBMIT_CARD_TOOL = [
    {
        "name": "submit_card",
        "description": (
            "Emit one social-media card. Call this once per card in the creative "
            "direction, in order. Each call produces one draft the user reviews."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Instagram | Stories | Twitter | Facebook | LinkedIn | TikTok",
                },
                "caption": {"type": "string", "description": "The caption body, 1-4 short lines."},
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-6 hashtags, no leading #.",
                },
                "notes": {"type": "string", "description": "One-line rationale for this card."},
            },
            "required": ["platform", "caption"],
        },
    }
]


def _brand_facts_block(brand: dict) -> str:
    """Confirmed brand facts (name, palette, keywords, phrases) for the prompt."""
    name = (brand.get("name") or "").strip()
    palette = brand.get("palette") or {}
    palette_bits = []
    for slot in ("primary", "secondary", "accent", "fourth"):
        v = palette.get(slot)
        if isinstance(v, str) and v.startswith("#"):
            palette_bits.append(f"{slot} {v}")
    keywords = [k for k in (brand.get("keywords") or []) if k]
    use_phrases = [p for p in (brand.get("phrases_to_use") or []) if p]
    avoid_phrases = [p for p in (brand.get("phrases_to_avoid") or []) if p]
    lines = []
    if name:
        lines.append(f"Organisation name: {name}")
    if palette_bits:
        lines.append("Confirmed brand palette: " + ", ".join(palette_bits))
    if keywords:
        lines.append("Brand keywords: " + ", ".join(keywords))
    if use_phrases:
        lines.append("Phrases to use: " + "; ".join(use_phrases))
    if avoid_phrases:
        lines.append("Phrases to avoid: " + "; ".join(avoid_phrases))
    return "\n".join(lines)


def _direction_block(directions: list[dict]) -> str:
    if not directions:
        return ""
    lines = []
    for i, d in enumerate(directions, 1):
        lines.append(
            f"Card {i}: platform {d.get('platform', 'Instagram')}; "
            f"angle/lens: {d.get('lens', '') or 'your choice'}; "
            f"opening hook idea: {d.get('hook', '') or '(write your own)'}; "
            f"intent: {d.get('intent', '') or ''}".rstrip()
        )
    return (
        "Creative direction from the art director (one card per line — honour "
        "the platform and angle, but write the caption in your own fresh "
        "words):\n"
        + "\n".join(lines)
        + f"\n\nProduce exactly {len(directions)} card(s), one per direction "
        "above, calling submit_card once per card in order."
    )


def _avoid_block(recent_cards: Optional[list[dict]]) -> str:
    if not recent_cards:
        return ""
    seen = []
    for c in recent_cards[-8:]:
        cap = (c.get("caption") if isinstance(c, dict) else str(c)) or ""
        cap = cap.strip()
        if cap:
            seen.append("- " + cap[:220])
    if not seen:
        return ""
    return (
        "The user has already seen these recent drafts for this brief. Write "
        "something NOTICEABLY DIFFERENT — different openers, structure, angle "
        "and wording. Do not paraphrase them:\n" + "\n".join(seen)
    )


def _build_system_prompt(
    *,
    brand: dict,
    requirements: str,
    directions: list[dict],
    recent_cards: Optional[list[dict]],
    tone: str,
) -> str:
    try:
        from mediahub.ai_core import narrate_brand

        brand_prose = narrate_brand(brand)
    except Exception:
        brand_prose = ""
    base = (
        "You are MediaHub's content engine for sports clubs, societies, teams "
        "and organisations. You generate short, human-sounding social captions "
        "grounded ONLY in the user's input. Never invent facts, names, times, "
        "places or achievements not provided. If the input is thin, write "
        "shorter cards rather than padding.\n\n"
        "Emit each card by calling the `submit_card` tool. Captions: 1-4 short "
        "lines, ~280 characters. Hashtags: 2-6. After your last card write "
        "nothing — the tool calls are the answer."
    )
    # Cliché guardrail parity with the achievement caption path. The brief-led
    # card writer builds its own prompt (it never touches _compose_caption_prompt),
    # so the shared AI-tell ban list and opener bans never reached it. Inject
    # them here so Event Preview / Sponsor Post / Session Update / Free Text
    # cards are held to the same "no machine-written filler" bar.
    try:
        from mediahub.web.ai_caption import (
            _AI_TELL_SYSTEM_INSTRUCTION,
            _SHARED_TONE_BANS,
        )

        base += "\n\n" + _AI_TELL_SYSTEM_INSTRUCTION + " " + _SHARED_TONE_BANS
    except Exception:
        pass
    if brand_prose:
        base += "\n\nBrand voice:\n" + brand_prose

    tone_desc = _tone_descriptor(tone)
    if tone_desc:
        base += "\n\nTone: " + tone_desc

    facts = _brand_facts_block(brand)
    if facts:
        base += "\n\nBrand facts:\n" + facts

    if requirements:
        base += "\n\nThis brief is:\n" + requirements

    direction = _direction_block(directions)
    if direction:
        base += "\n\n" + direction

    avoid = _avoid_block(recent_cards)
    if avoid:
        base += "\n\n" + avoid

    return base


def _tone_descriptor(tone: str) -> str:
    if not tone or tone == "ai":
        return ""
    try:
        from mediahub.web.ai_caption import _TONE_DESCRIPTORS

        return _TONE_DESCRIPTORS.get(tone, "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# §8C flag threshold: two captions sharing half their trigram phrasing
# (Jaccard ≥ 0.5) read as rewrites of each other — the set's worst pair is
# surfaced in the returned metrics so the review surface can show it.
_CAPTION_REPEAT_FLAG = 0.5


def generate_content(
    *,
    content_type: str,
    brief: str,
    brand_context: Optional[dict] = None,
    n_cards: int = 3,
    recent_cards: Optional[list[dict]] = None,
    tone: str = "ai",
    requirements: str = "",
) -> dict:
    """Generate a set of platform-ready content cards for one brief.

    Returns ``{"cards": [...], "direction": [...], "metrics": {...}}``.
    ``cards`` is a list of ``{platform, caption, hashtags, notes}`` dicts —
    brief-led cards carry **no** ``confidence`` key: the writer has no
    calibrated score, and a constant would be a fake signal on a review
    surface built around honest confidence displays (only ranker-scored
    cards carry a real value). ``direction`` is the AI Director's plan and
    ``metrics`` the deterministic §8C caption-repetition summary (both for
    explainability / audit).

    Raises ``ai_core.ProviderNotConfigured`` / ``ProviderError`` when no
    provider can answer — there is no template fallback.
    """
    from mediahub.ai_core import ask_with_tools

    brand = brand_context if brand_context is not None else load_brand_context()
    n_cards = max(1, min(int(n_cards or 3), 6))

    # 1. AI Director — plan the set (best-effort; falls back to a spread).
    directions = plan_content_directions(
        content_type=content_type,
        brief=brief,
        brand_context=brand,
        n_cards=n_cards,
        recent_cards=recent_cards,
        tone=tone,
        requirements=requirements,
    )

    # 2. Writer — produce the cards, honouring the plan + avoiding recents.
    cards: list[dict] = []

    def _tool(name, inp):
        if name != "submit_card":
            return json.dumps({"error": f"unknown tool: {name}"})
        platform = (inp.get("platform") or "Instagram").strip()
        caption = (inp.get("caption") or "").strip()
        hashtags = inp.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.split() if h.strip()]
        notes = (inp.get("notes") or "").strip()
        if not caption:
            return json.dumps({"ok": False, "reason": "empty caption — skipped"})
        # No "confidence" key on purpose: the writer produces no calibrated
        # score, so absent means "unscored" — never a constant dressed up as
        # model confidence (ranker-scored cards keep their real value).
        cards.append(
            {
                "platform": platform,
                "caption": caption,
                "hashtags": [
                    str(h).lstrip("#").strip() for h in list(hashtags)[:6] if str(h).strip()
                ],
                "notes": notes,
            }
        )
        return json.dumps({"ok": True, "received": len(cards)})

    system = _build_system_prompt(
        brand=brand,
        requirements=requirements,
        directions=directions,
        recent_cards=recent_cards,
        tone=tone,
    )
    # Per-call nonce so the provider can't return cached identical output
    # across regenerations (the prompt asks for tool calls only, so it never
    # leaks into a caption).
    user = (brief or "").strip() + f"\n\n[Draft fresh cards. seed={random.randint(10_000, 99_999)}]"

    ask_with_tools(
        system=system,
        user=user,
        tools=_SUBMIT_CARD_TOOL,
        on_tool_call=_tool,
        max_tokens=1600,
        max_rounds=8,
    )

    # 3. §8C caption non-repetition — deterministic metric over the set just
    # written (worst-case trigram overlap between any two cards), recorded
    # alongside the cards like the visual pool's pool_metrics. Metric-only,
    # best-effort: a repeated pair above the flag threshold is surfaced for
    # the QA/review surface, never silently gated or censored.
    result: dict = {"cards": cards, "direction": directions}
    try:
        from mediahub.quality.variant_metrics import caption_repetition

        caps = [c["caption"] for c in cards]
        rep = caption_repetition(caps)
        metrics: dict = {"caption_repetition": round(rep, 3)}
        if rep >= _CAPTION_REPEAT_FLAG:
            worst, pair = 0.0, [0, 1]
            for i in range(len(caps)):
                for j in range(i + 1, len(caps)):
                    v = caption_repetition([caps[i], caps[j]])
                    if v > worst:
                        worst, pair = v, [i, j]
            metrics["repeated_pair"] = pair
        result["metrics"] = metrics
    except Exception:
        pass
    return result


def generate_caption(
    achievement_dict: dict,
    club_brand: Optional[dict] = None,
    tone: str = "ai",
    voice_profile: Optional[dict] = None,
    club_profile=None,
    recent_captions: Optional[list[str]] = None,
    *,
    brief_prose: Optional[str] = None,
    direction: Optional[dict] = None,
    requirements: str = "",
) -> str:
    """Single-caption front door for achievement-led content.

    Meet recap, athlete spotlight, sponsor variants and turn-into all produce
    ONE caption for ONE item rather than a set of platform cards. They route
    through here so there is a single engine surface, but the actual writing
    is delegated to the shared ``ai_caption.generate_caption_for_tone``
    primitive — the very same writer the brief-led card path uses. Raises
    ``ClaudeUnavailableError`` when no provider can answer (no fake fallback).
    """
    from mediahub.web.ai_caption import generate_caption_for_tone

    return generate_caption_for_tone(
        achievement_dict,
        club_brand,
        tone=tone,
        voice_profile=voice_profile,
        club_profile=club_profile,
        recent_captions=recent_captions,
        brief_prose=brief_prose,
        direction=direction,
        requirements=requirements,
    )


__all__ = ["generate_content", "generate_caption", "load_brand_context"]
