"""AI-driven creative direction for visual briefs.

This module wraps the provider-agnostic ``ai_core`` interface to ask
Claude / Gemini for a structured creative direction across every axis
the renderer cares about: layout family, palette role, background
style, accent style, typography pair, composition, photo treatment,
decoration strength, headline hook, and mood.

Why this exists
---------------
The legacy ``generator.generate()`` picked a single layout from a
hard-coded post_angle → pattern table, then applied a deterministic
seed permutation. That made every "regenerate" click for the same card
produce visually identical output. Routing the creative direction
through AI gives us:

  * Genuinely fresh hooks every regeneration (the model writes them).
  * Layout choices that match the achievement's emotional weight.
  * A "differ from these recent ones" prompt so the AI actively avoids
    repeating itself when the user is reviewing options.

When no provider is configured the caller falls back to
``generator.random_variation_profile()`` — the function in this module
returns ``None`` and never crashes.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Optional

log = logging.getLogger(__name__)


# Imported lazily inside ai_creative_direction so the module can be
# imported in environments where ai_core / its dependencies aren't
# installed (e.g. minimal CI without anthropic SDK).


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Walk a dotted path through dicts/objects safely."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur if cur is not None else default


def _brand_context(brand_kit) -> str:
    """One-paragraph brand context for the system prompt."""
    if brand_kit is None:
        return ""
    name = _safe_get(brand_kit, "display_name", default="") or ""
    primary = _safe_get(brand_kit, "primary_colour", default="") or ""
    secondary = _safe_get(brand_kit, "secondary_colour", default="") or ""
    accent = _safe_get(brand_kit, "accent_colour", default="") or ""
    bits = []
    if name:
        bits.append(f"Club: {name}.")
    cols = [c for c in (primary, secondary, accent) if c]
    if cols:
        bits.append(
            "Brand palette (DO NOT change the hex values, only their visual role): "
            + ", ".join(cols) + "."
        )
    return " ".join(bits)


def _achievement_summary(content_item: dict) -> str:
    ach = (content_item or {}).get("achievement") or content_item or {}
    swimmer = ach.get("swimmer_name") or ach.get("athlete_name") or ""
    event = ach.get("event_name") or ach.get("event") or ""
    result = (
        ach.get("result_time")
        or ach.get("time")
        or ach.get("result")
        or (ach.get("raw_facts") or {}).get("time_str")
        or ""
    )
    place = ach.get("place") or ach.get("position") or ""
    angle = ach.get("post_angle") or content_item.get("post_angle") or ""
    bits = []
    if swimmer:
        bits.append(swimmer)
    if event:
        bits.append(event)
    if result:
        bits.append(str(result))
    if place:
        bits.append(f"{place} place")
    if angle:
        bits.append(f"(angle: {angle})")
    return " — ".join(bits) if bits else "a strong swim"


# The full set the AI can pick from. Kept in lock-step with the
# generator module's constants so the renderer can honour any choice.
_BACKGROUND_STYLES = (
    "water", "halftone", "diagonal", "radial", "geometric",
    "clean", "stripes", "dots", "duotone", "grain",
)
_ACCENT_STYLES = (
    "brackets", "stripe", "badge", "frame",
    "minimal", "ribbon", "arrow", "underline",
)
_TYPOGRAPHY_PAIRS = (
    "anton-inter", "bebas-grotesk", "druk-inter",
    "bowlby-inter", "archivo-inter", "oswald-inter",
)
_COMPOSITIONS = ("right", "left", "center", "off-center")
_PHOTO_TREATMENTS = (
    "cutout", "vignette", "duotone", "frame", "halftone", "no-photo",
)
_LAYOUT_FAMILIES = (
    "individual_hero", "big_number_hero", "text_led_recap",
    "weekend_numbers", "athlete_spotlight", "story_card",
    "medal_card",
)


def _system_prompt() -> str:
    """The art-director prompt — kept terse and option-bounded so the
    model returns ONE JSON object whose keys we can trust."""
    return (
        "You are the art director for a sports content studio. Your job "
        "is to choose a fresh visual direction for ONE swim achievement "
        "graphic. You will return STRICT JSON only — no prose, no "
        "markdown, no preamble. Pick boldly: this is a content "
        "operations product, not a generic template shop. Each call "
        "should feel different from the last few.\n\n"
        "Output schema (every field required, exact keys, exact "
        "vocabulary from the lists below):\n"
        "{\n"
        '  "layout_family":         one of ' + json.dumps(list(_LAYOUT_FAMILIES)) + ",\n"
        '  "palette_role_index":    integer 0-5 (which colour-role permutation),\n'
        '  "background_style":      one of ' + json.dumps(list(_BACKGROUND_STYLES)) + ",\n"
        '  "accent_style":          one of ' + json.dumps(list(_ACCENT_STYLES)) + ",\n"
        '  "typography_pair":       one of ' + json.dumps(list(_TYPOGRAPHY_PAIRS)) + ",\n"
        '  "composition":           one of ' + json.dumps(list(_COMPOSITIONS)) + ",\n"
        '  "photo_treatment":       one of ' + json.dumps(list(_PHOTO_TREATMENTS)) + ",\n"
        '  "decoration_strength":   float 0.0-1.0,\n'
        '  "hook_phrase":           1-4 word ALL-CAPS headline (no exclamation),\n'
        '  "mood":                  one or two mood words (e.g. "electric, precise"),\n'
        '  "rationale":             one short sentence explaining the pick\n'
        "}\n\n"
        "Hard rules:\n"
        "- Never invent facts (no fake times, fake events).\n"
        "- Never propose a value outside the listed vocabulary.\n"
        "- If a list of recent_signatures is provided, AVOID repeating "
        "  the same combination. Pick a different layout_family OR "
        "  background_style at minimum.\n"
        "- The hook_phrase must be short, punchy, and never use the "
        "  athlete's name (the name appears separately in the layout).\n"
        "- Output JSON ONLY."
    )


def _user_prompt(
    *,
    summary: str,
    brand_ctx: str,
    angle: str,
    default_family: str,
    recent_signatures: list[str],
    recent_hooks: list[str],
) -> str:
    parts = [
        f"Achievement: {summary}",
        f"Suggested default layout family (you can override): {default_family}",
    ]
    if angle:
        parts.append(f"Post angle: {angle}")
    if brand_ctx:
        parts.append(brand_ctx)
    if recent_signatures:
        parts.append(
            "Recent variation signatures for this card (DO NOT repeat — "
            "pick a different combination): "
            + " | ".join(recent_signatures[-5:])
        )
    if recent_hooks:
        parts.append(
            "Recent hooks used for this card (DO NOT reuse, write a "
            "different short phrase): "
            + " | ".join(f'"{h}"' for h in recent_hooks[-5:])
        )
    # Per-call nonce so the provider can't return a cached identical
    # JSON object across two regenerations.
    parts.append(f"Variation nonce (do not echo): {random.randint(10_000, 99_999_999)}")
    parts.append("Return ONE JSON object now.")
    return "\n\n".join(parts)


def _parse_strict_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from ``text``.

    Models occasionally wrap JSON in ```json fences``` despite the
    prompt; this peels them and tolerates trailing text.
    """
    if not text:
        return None
    s = text.strip()
    # Strip code fences.
    if s.startswith("```"):
        # Drop the opening ``` and optional language tag.
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    # Find the outermost {...} block.
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def ai_creative_direction(
    *,
    content_item: dict,
    brand_kit,
    angle: str = "",
    default_family: str = "individual_hero",
    recent_signatures: Optional[list[str]] = None,
    recent_hooks: Optional[list[str]] = None,
) -> Optional[dict]:
    """Ask the configured AI provider for a creative direction.

    Returns the parsed JSON object on success, or ``None`` if no
    provider is configured or the call fails. The caller (the
    ``generator.generate()`` function) treats ``None`` as "skip AI,
    fall back to random/seed-based variation".

    The return shape matches what ``generator._profile_from_ai_direction``
    expects.
    """
    try:
        from mediahub.ai_core import ask, ProviderNotConfigured, ProviderError
    except Exception as e:
        log.debug("ai_director: ai_core import failed: %s", e)
        return None

    summary = _achievement_summary(content_item)
    brand_ctx = _brand_context(brand_kit)
    sys = _system_prompt()
    user = _user_prompt(
        summary=summary,
        brand_ctx=brand_ctx,
        angle=angle,
        default_family=default_family or "individual_hero",
        recent_signatures=recent_signatures or [],
        recent_hooks=recent_hooks or [],
    )
    try:
        out = ask(sys, user, max_tokens=600)
    except ProviderNotConfigured:
        return None
    except ProviderError as e:
        log.warning("ai_director: provider error: %s", str(e)[:200])
        return None
    except Exception as e:
        log.warning("ai_director: unexpected error: %s", str(e)[:200])
        return None
    if not out:
        return None
    obj = _parse_strict_json(out)
    if obj is None:
        log.warning(
            "ai_director: could not parse JSON from provider output: %s",
            (out or "")[:200],
        )
    return obj


def ai_fresh_hook(
    *,
    achievement_summary: str,
    confidence_label: str,
    tone: str,
    recent_hooks: Optional[list[str]] = None,
) -> Optional[str]:
    """Ask the AI for ONE short, novel headline hook.

    Used by the captions + spotlights when only the hook needs
    refreshing (not the whole creative direction). Returns ``None`` if
    no provider is configured / the call fails.
    """
    try:
        from mediahub.ai_core import ask, ProviderNotConfigured, ProviderError
    except Exception:
        return None
    avoid = ""
    if recent_hooks:
        avoid = (
            "\nDo NOT reuse any of these recent hooks for this card; "
            "pick something different: "
            + " | ".join(f'"{h}"' for h in recent_hooks[-5:])
        )
    sys = (
        "You write punchy graphic-headline hooks for sports content. "
        "Output ONE hook only, 1-4 words, ALL CAPS, no punctuation at "
        "the end, no athlete name, no quote marks, no preamble. "
        "Match the confidence label and tone."
    )
    user = (
        f"Achievement: {achievement_summary}\n"
        f"Confidence label: {confidence_label}\n"
        f"Tone: {tone}\n"
        f"Nonce (do not echo): {random.randint(10_000, 99_999)}"
        f"{avoid}\n\n"
        "Return ONE hook now (just the words)."
    )
    try:
        out = ask(sys, user, max_tokens=24)
    except (ProviderNotConfigured, ProviderError):
        return None
    except Exception:
        return None
    if not out:
        return None
    # Strip quotes / fences / punctuation flailing.
    hook = out.strip().strip('"').strip("'").strip("`").strip()
    # Take the first line, upper-case it, cap length.
    hook = hook.splitlines()[0].strip().upper()
    if len(hook) < 2 or len(hook) > 60:
        return None
    return hook


__all__ = ["ai_creative_direction", "ai_fresh_hook"]
