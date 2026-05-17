"""brand/sponsor.py — sponsor-acknowledging caption variants.

Phase 1.2 deliverable: per top-ranked card, produce a sponsor-thanks
caption variant alongside the regular caption, so the user can
deliver a sponsor-branded post without re-prompting from scratch.

The visual side (sponsor-branded result-card graphic) is already
handled by the existing graphic renderer — ``create_visual_for_item``
in ``content_pack_visual.integration`` accepts a ``sponsor_name``
argument and picks up the ``sponsor_branded`` layout family. This
module owns only the caption side: a thin wrapper that feeds the
existing caption pipeline with an explicit "acknowledge the sponsor"
requirement on top of the org's normal brand context.

We deliberately do NOT add "sponsor" as a fifth tone — tones describe
voice, not content angle. Sponsor acknowledgement is an additional
*requirement* over the org's existing tone.
"""
from __future__ import annotations

from typing import Optional


def _get(obj, name: str, default=""):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def sponsor_caption_requirement(profile) -> str:
    """Build the additional-instruction line that asks the caption LLM
    to acknowledge the org's primary sponsor. Returns empty string when
    no sponsor is configured (the caller should then skip the variant
    rather than producing a sponsor-less "sponsor caption")."""
    name = (_get(profile, "sponsor_name") or "").strip()
    if not name:
        return ""
    guidelines = (_get(profile, "sponsor_guidelines") or "").strip()
    bits = [
        f"This caption MUST acknowledge the club's primary sponsor "
        f'"{name}" — either with a sincere thank-you sentence near the '
        "end, an @-mention, or a sponsor-tag at the close. Keep the "
        "acknowledgement specific to this swim or this meet, not "
        "generic gushing. Sponsor acknowledgement is the whole point "
        "of this caption variant, so it should be unmistakable."
    ]
    if guidelines:
        bits.append("Sponsor mention rules from the organisation: " + guidelines)
    return " ".join(bits)


def generate_sponsor_caption(
    achievement_dict: dict,
    *,
    profile,
    tone: Optional[str] = None,
    voice_profile: Optional[dict] = None,
) -> str:
    """Return a sponsor-acknowledging caption for one achievement.

    Goes through the regular caption pipeline so brand context (DNA,
    guidelines, voice profile, derived tone prose) all flow through
    unchanged. The only addition is an explicit "acknowledge sponsor X"
    requirement injected via the ``_extra_instructions`` payload key
    that ``generate_caption_for_tone`` now reads.

    Raises:
        ClaudeUnavailableError: when no LLM provider can answer. The
        caller decides whether to surface that or fall back to "no
        sponsor variant available right now".
        ValueError: when no sponsor is configured on the profile.
    """
    requirement = sponsor_caption_requirement(profile)
    if not requirement:
        raise ValueError(
            "no sponsor configured — set Organisation > Sponsor name "
            "before generating sponsor caption variants"
        )
    from mediahub.web.ai_caption import generate_caption_for_tone

    # Default to the org's preferred tone but let callers override.
    if tone is None:
        tone = (_get(profile, "tone") or _get(profile, "caption_tone")
                or "warm-club")

    enriched = dict(achievement_dict)
    # Layer the sponsor requirement on top of whatever was already on
    # the payload (the Turn-Into path may have set _artefact_intent).
    prev_extra = enriched.get("_extra_instructions") or ""
    enriched["_extra_instructions"] = (
        (prev_extra + " " + requirement).strip()
    )
    return generate_caption_for_tone(
        enriched,
        club_brand={"club_name": _get(profile, "display_name") or ""},
        tone=tone,
        voice_profile=voice_profile,
        club_profile=profile,
    )


__all__ = ["sponsor_caption_requirement", "generate_sponsor_caption"]
