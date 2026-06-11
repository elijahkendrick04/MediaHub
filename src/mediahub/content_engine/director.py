"""The AI Content Director.

Mirrors ``creative_brief.ai_director`` (which directs the *visual* of a meet-
recap graphic) but for *copy*: given a brief and brand, it decides how many
cards to make, which platform each targets, the angle/lens each takes, and an
opening hook — actively avoiding anything the user has already seen so every
"regenerate" yields a genuinely different set.

When no provider is configured (or the call fails / can't be parsed) it returns
a deterministic spread so the engine still produces cards — the honest
"no provider" error is raised later by the writer, not here.
"""

from __future__ import annotations

import json
import logging
import random
from typing import Optional

log = logging.getLogger(__name__)


# Platforms the director may target. Kept as a closed vocabulary so the
# downstream renderer / icons always recognise the value.
_PLATFORMS = ("Instagram", "Stories", "Twitter", "Facebook", "LinkedIn", "TikTok")

# Default lenses used only by the no-provider fallback spread.
_FALLBACK_LENSES = (
    "the headline moment",
    "the numbers",
    "the human story",
    "the team reaction",
    "the milestone",
    "looking ahead",
)


def _brand_line(brand_context: Optional[dict]) -> str:
    if not brand_context:
        return ""
    name = (brand_context.get("name") or "").strip()
    kws = [k for k in (brand_context.get("keywords") or []) if k][:6]
    bits = []
    if name:
        bits.append(f"Organisation: {name}.")
    if kws:
        bits.append("Brand keywords: " + ", ".join(kws) + ".")
    tone_notes = (brand_context.get("tone_notes") or "").strip()
    if tone_notes:
        bits.append("Tone notes: " + tone_notes[:200])
    return " ".join(bits)


def _system_prompt(n_cards: int) -> str:
    return (
        "You are the content director for a sports content studio (clubs, "
        "societies, teams, organisations). Plan a set of social-media cards "
        "for ONE brief. You return STRICT JSON only — no prose, no markdown, "
        "no preamble. Pick boldly and make every card take a DIFFERENT angle "
        "so the set feels varied, not repetitive.\n\n"
        "Output schema (exact keys):\n"
        "{\n"
        '  "cards": [\n'
        "    {\n"
        '      "platform": one of ' + json.dumps(list(_PLATFORMS)) + ",\n"
        '      "lens":     short angle, e.g. "the numbers" / "team reaction" / "the milestone" / "behind the scenes",\n'
        '      "hook":     a 3-8 word opening idea (NOT the full caption),\n'
        '      "intent":   one short sentence on why this card earns its place\n'
        "    }\n"
        f"    ... exactly {n_cards} card(s) ...\n"
        "  ]\n"
        "}\n\n"
        "Hard rules:\n"
        "- Never invent facts (no fake names, times, results, sponsors).\n"
        "- Vary BOTH platform and lens across the set where it makes sense.\n"
        "- If recent cards are shown, AVOID repeating their angles or hooks.\n"
        "- platform values must come from the list exactly.\n"
        "- Output JSON ONLY."
    )


def _user_prompt(
    *,
    content_type: str,
    brief: str,
    brand_line: str,
    requirements: str,
    recent_cards: Optional[list[dict]],
    n_cards: int,
    tone: str,
) -> str:
    parts = [
        f"Content type: {content_type}.",
        f"Plan exactly {n_cards} card(s).",
    ]
    if tone and tone != "ai":
        parts.append(f"Desired tone: {tone}.")
    if requirements:
        parts.append("What this brief is: " + requirements)
    if brand_line:
        parts.append(brand_line)
    parts.append("Brief:\n" + (brief or "").strip())
    if recent_cards:
        seen = []
        for c in recent_cards[-6:]:
            cap = (c.get("caption") if isinstance(c, dict) else str(c)) or ""
            lens = c.get("lens") if isinstance(c, dict) else ""
            label = (lens + ": " if lens else "") + cap.strip()[:160]
            if label.strip():
                seen.append("- " + label)
        if seen:
            parts.append(
                "Recent angles/cards the user has already seen for this brief "
                "(plan DIFFERENT angles + hooks, do not repeat these):\n" + "\n".join(seen)
            )
    parts.append(f"Variation nonce (do not echo): {random.randint(10_000, 99_999_999)}")
    parts.append("Return ONE JSON object now.")
    return "\n\n".join(parts)


def _parse(text: str) -> Optional[list[dict]]:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    cards = obj.get("cards")
    if not isinstance(cards, list) or not cards:
        return None
    out: list[dict] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        platform = str(c.get("platform") or "Instagram").strip()
        if platform not in _PLATFORMS:
            # Snap unknown platforms to the closest sensible default rather
            # than dropping the card.
            platform = "Instagram"
        out.append(
            {
                "platform": platform,
                "lens": str(c.get("lens") or "").strip()[:80],
                "hook": str(c.get("hook") or "").strip()[:80],
                "intent": str(c.get("intent") or "").strip()[:160],
            }
        )
    return out or None


def _fallback_spread(n_cards: int, recent_cards: Optional[list[dict]]) -> list[dict]:
    """Deterministic-but-rotated plan when no AI provider is available.

    Rotates the starting lens by how many recent cards exist so repeated
    regenerates still shuffle, even without a provider.
    """
    plat_default = ("Instagram", "Stories", "Twitter", "Facebook")
    offset = len(recent_cards or []) % len(_FALLBACK_LENSES)
    out = []
    for i in range(n_cards):
        out.append(
            {
                "platform": plat_default[i % len(plat_default)],
                "lens": _FALLBACK_LENSES[(i + offset) % len(_FALLBACK_LENSES)],
                "hook": "",
                "intent": "",
            }
        )
    return out


def plan_content_directions(
    *,
    content_type: str,
    brief: str,
    brand_context: Optional[dict] = None,
    n_cards: int = 3,
    recent_cards: Optional[list[dict]] = None,
    tone: str = "ai",
    requirements: str = "",
) -> list[dict]:
    """Return a list of ``{platform, lens, hook, intent}`` card directions.

    Best-effort: returns a deterministic spread (never an empty list) when no
    provider is configured or the response can't be parsed, so the engine
    always has a plan to write against.
    """
    n_cards = max(1, min(int(n_cards or 3), 6))
    try:
        from mediahub.ai_core import ask, ProviderNotConfigured, ProviderError
    except Exception:
        return _fallback_spread(n_cards, recent_cards)

    sys = _system_prompt(n_cards)
    user = _user_prompt(
        content_type=content_type,
        brief=brief,
        brand_line=_brand_line(brand_context),
        requirements=requirements,
        recent_cards=recent_cards,
        n_cards=n_cards,
        tone=tone,
    )
    try:
        out = ask(sys, user, max_tokens=600)
    except ProviderNotConfigured:
        log.info("content director: no provider — using fallback spread")
        return _fallback_spread(n_cards, recent_cards)
    except ProviderError as e:
        log.warning("content director: provider error: %s", str(e)[:300])
        return _fallback_spread(n_cards, recent_cards)
    except Exception as e:
        log.warning("content director: unexpected error: %s", str(e)[:300])
        return _fallback_spread(n_cards, recent_cards)

    parsed = _parse(out)
    if not parsed:
        log.warning("content director: could not parse plan — using fallback spread")
        return _fallback_spread(n_cards, recent_cards)
    return parsed


__all__ = ["plan_content_directions"]
