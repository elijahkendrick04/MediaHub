"""brand/context.py — single canonical brand briefing for content tools.

Every generator on the site (captions, Turn-Into, weekend recap, athlete
spotlights, motion compositions, etc.) must speak in the organisation's
voice. Rather than each generator duplicating the logic for assembling
that voice from the various ClubProfile fields, they all call:

    brand_context_for_llm(profile) -> str

and prepend the returned string to their LLM system prompt. The returned
prose unifies four sources of brand truth:

  1. Identity fields (display_name, country, governing_body, sponsor)
  2. Captured brand DNA from website / social ingestion
     (brand_voice_summary, brand_phrases_to_use, brand_phrases_to_avoid,
      brand_keywords, brand_palette_extracted)
  3. Voice profile from past captions (sentence length, emoji rate,
     opener/closer style, preferred swimmer address)
  4. AI-interpreted brand guidelines document (voice_attributes,
     tone_dos, tone_donts, prohibited_words, preferred_terminology,
     hashtag_rules, sponsor_mention_rules, key_messages)

This is intentionally string-based, not a structured prompt object —
LLMs absorb natural-language guidance well, and a single function makes
it trivial to add to any new tool.
"""
from __future__ import annotations

from typing import Any


def _get(profile, name: str, default: Any = None) -> Any:
    if profile is None:
        return default
    if isinstance(profile, dict):
        return profile.get(name, default)
    return getattr(profile, name, default)


def _identity_prose(profile) -> str:
    name = (_get(profile, "display_name") or "").strip()
    if not name:
        return ""
    short = (_get(profile, "short_name") or "").strip()
    governing = (_get(profile, "governing_body") or "").strip()
    country = (_get(profile, "country") or "").strip()
    sponsor = (_get(profile, "sponsor_name") or "").strip()
    bits = [f"You are writing for **{name}**"]
    if short and short.lower() != name.lower():
        bits[-1] += f" (also known as {short})"
    if governing or country:
        loc = ", ".join(p for p in (governing, country) if p)
        bits[-1] += f" — affiliated with {loc}"
    bits[-1] += "."
    if sponsor:
        bits.append(f"Primary sponsor: {sponsor}.")
    return " ".join(bits)


def _dna_prose(profile) -> str:
    summary = (_get(profile, "brand_voice_summary") or "").strip()
    keywords = list(_get(profile, "brand_keywords") or [])[:10]
    use = list(_get(profile, "brand_phrases_to_use") or [])[:6]
    avoid = list(_get(profile, "brand_phrases_to_avoid") or [])[:6]
    bits: list[str] = []
    if summary:
        bits.append("About the organisation (from their website / social presence): "
                    + summary)
    if keywords:
        bits.append("Words and themes the organisation uses about itself: "
                    + ", ".join(keywords) + ".")
    if use:
        bits.append("Phrases that sound like them: "
                    + "; ".join(f'"{p}"' for p in use) + ".")
    if avoid:
        bits.append("Phrases that would feel off-brand — never use: "
                    + "; ".join(f'"{p}"' for p in avoid) + ".")
    return " ".join(bits)


def _voice_profile_prose(profile) -> str:
    vp = _get(profile, "voice_profile") or {}
    if not isinstance(vp, dict) or not vp:
        return ""
    bits: list[str] = ["Voice profile (learned from this club's actual past captions):"]
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
                bits.append("This club does NOT use emoji.")
            elif r < 1.0:
                bits.append("Use emoji sparingly — at most one per caption.")
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
        "first_name":   "Address swimmers by first name only.",
        "last_name":    "Use the swimmer's full name with surname.",
        "surname_only": "Use the swimmer's surname only (broadcast style).",
        "nickname":     "Address swimmers familiarly, nickname-style.",
    }
    if isinstance(addr, str) and addr in addr_map:
        bits.append(addr_map[addr])
    openers = vp.get("characteristic_openers") or []
    if openers:
        bits.append("Typical openers: " + ", ".join(f'"{o}"' for o in openers[:4]) + ".")
    closers = vp.get("characteristic_closers") or []
    if closers:
        bits.append("Typical closers: " + ", ".join(f'"{c}"' for c in closers[:4]) + ".")
    forbidden = vp.get("forbidden_phrases") or []
    if forbidden:
        bits.append("Phrases to avoid (learned): "
                    + ", ".join(f'"{p}"' for p in forbidden[:5]) + ".")
    common_hash = vp.get("common_hashtags") or []
    if common_hash:
        bits.append("Hashtags they commonly use: " + ", ".join(common_hash[:6]) + ".")
    return " ".join(bits) if len(bits) > 1 else ""


def _mandatory_rules_prose(profile) -> str:
    """Render the user's verbatim MUST / NEVER / ALWAYS rules at the
    TOP of every system prompt with explicit override framing.

    Previously these were soft-interpreted into tone_dos and got drowned
    out by website-derived voice signals when the LLM weighed competing
    instructions. By stating them first, numbering them, and explicitly
    telling Claude they override anything else in the prompt, we make
    them the highest-priority constraint the model sees.
    """
    rules = list(_get(profile, "brand_guidelines_mandatory_rules") or [])
    rules = [str(r).strip() for r in rules if isinstance(r, str) and str(r).strip()]
    if not rules:
        return ""
    numbered = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(rules[:25]))
    return (
        "=== NON-NEGOTIABLE RULES (from the organisation's uploaded "
        "brand guidelines) ===\n"
        "These rules are MANDATORY. They override every other "
        "instruction in this system prompt, including voice cues "
        "derived from the organisation's website or socials. Follow "
        "them literally. If two instructions conflict, these rules "
        "win:\n"
        f"{numbered}\n"
        "=== END NON-NEGOTIABLE RULES ==="
    )


def _compliance_recheck_prose(profile) -> str:
    """A short reminder at the very END of the system prompt to verify
    compliance before returning. Cheap belt-and-braces against the LLM
    forgetting the top of the prompt after a long block of voice prose.
    Only emitted when there ARE mandatory rules to recheck.
    """
    rules = list(_get(profile, "brand_guidelines_mandatory_rules") or [])
    if not rules:
        return ""
    return (
        "Before returning your final answer, re-read the NON-NEGOTIABLE "
        "RULES block at the top of this prompt and confirm your output "
        "complies with every one of them. If your draft violates any "
        "rule, revise it before answering."
    )


def _guidelines_prose(profile) -> str:
    g = _get(profile, "brand_guidelines") or {}
    if not isinstance(g, dict) or not g:
        return ""
    bits: list[str] = []
    summary = (g.get("summary") or "").strip()
    if summary:
        bits.append("Brand guidelines (from the organisation's uploaded style document): "
                    + summary)
    attrs = g.get("voice_attributes") or []
    if attrs:
        bits.append("Voice should feel: " + ", ".join(attrs) + ".")
    dos = g.get("tone_dos") or []
    if dos:
        bits.append("DO: " + " · ".join(dos) + ".")
    donts = g.get("tone_donts") or []
    if donts:
        bits.append("DO NOT: " + " · ".join(donts) + ".")
    prohibited = g.get("prohibited_words") or []
    if prohibited:
        bits.append("Prohibited words/phrases — never use these even in paraphrase: "
                    + ", ".join(f'"{w}"' for w in prohibited[:15]) + ".")
    pref = g.get("preferred_terminology") or {}
    if isinstance(pref, dict) and pref:
        pairs = ", ".join(f'"{k}" → "{v}"' for k, v in list(pref.items())[:10])
        bits.append("Replace the left term with the right term: " + pairs + ".")
    audience = (g.get("audience") or "").strip()
    if audience:
        bits.append("Audience: " + audience + ".")
    hashtag_rules = (g.get("hashtag_rules") or "").strip()
    if hashtag_rules:
        bits.append("Hashtag rules: " + hashtag_rules)
    sponsor_rules = (g.get("sponsor_mention_rules") or "").strip()
    if sponsor_rules:
        bits.append("Sponsor mention rules: " + sponsor_rules)
    key_msgs = g.get("key_messages") or []
    if key_msgs:
        bits.append("Recurring key messages to weave in where appropriate: "
                    + " · ".join(key_msgs[:5]) + ".")
    return " ".join(bits)


def _logos_prose(profile) -> str:
    """Surface uploaded logo variants so downstream image/motion
    generators (and any LLM-driven asset-picker) know what's available."""
    logos = list(_get(profile, "brand_logos") or [])
    if not logos:
        return ""
    pieces: list[str] = []
    for logo in logos[:8]:
        if not isinstance(logo, dict):
            continue
        label = (logo.get("label") or logo.get("original_filename") or "logo").strip()
        desc = (logo.get("ai_description") or "").strip()
        mime = (logo.get("mime") or "").strip()
        fmt = mime.split("/")[-1] if "/" in mime else (logo.get("original_filename", "").rsplit(".", 1)[-1] if "." in logo.get("original_filename", "") else "")
        bits = [label]
        if fmt:
            bits.append(f"format: {fmt}")
        if desc:
            bits.append(desc)
        pieces.append(" — ".join(bits))
    if not pieces:
        return ""
    intro = (
        f"The organisation has {len(pieces)} logo variant"
        f"{'s' if len(pieces) != 1 else ''} on file. When suggesting "
        "imagery or motion compositions, pick the variant whose "
        "description best matches the context (e.g. dark backgrounds → "
        "the white/mono variant, square crops → the icon variant):"
    )
    return intro + "\n" + "\n".join(f"  · {p}" for p in pieces)


def brand_context_for_llm(profile) -> str:
    """Return a single coherent system-prompt block describing the
    organisation's brand identity, voice, captured DNA, and uploaded
    guidelines. Empty string when nothing is known.

    Every content generator should prepend this to its system prompt:

        system = brand_context_for_llm(profile) + "\\n\\n" + tool_system

    The returned text is plain prose — safe to drop into any LLM
    system message without further escaping.

    Section order:
      1. Non-negotiable mandatory rules from the uploaded guidelines
         (top of prompt, explicit override framing).
      2. Identity (who you're writing for).
      3. Brand guidelines (summary, voice attrs, do/don'ts, prohibited
         words, terminology, hashtag/sponsor rules, key messages).
      4. Captured DNA from website + socials.
      5. Voice profile learned from past captions.
      6. Logo inventory.
      7. Compliance recheck reminder at the very end.

    Guidelines deliberately precede website/social DNA so that the
    uploaded document — the explicit declaration of how the
    organisation wants to be represented — outranks signals scraped
    from the open web when the LLM weighs conflicting cues.
    """
    if profile is None:
        return ""
    sections = [
        _mandatory_rules_prose(profile),
        _identity_prose(profile),
        _guidelines_prose(profile),
        _dna_prose(profile),
        _voice_profile_prose(profile),
        _logos_prose(profile),
        _compliance_recheck_prose(profile),
    ]
    sections = [s for s in sections if s]
    if not sections:
        return ""
    return "\n\n".join(sections)


__all__ = ["brand_context_for_llm"]
