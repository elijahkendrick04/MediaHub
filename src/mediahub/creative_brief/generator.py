"""Generate a CreativeBrief that drives the renderer.

Inputs:
  - content_item     dict from content_pack
  - evaluation       EvaluationResult from media_requirements
  - brand_kit        BrandKit
  - voice_profile    VoiceProfile or None
  - inspiration_pat  pattern dict from mediahub.inspiration.pattern_library

Output: CreativeBrief dataclass with everything the renderer needs, plus a
human-readable "why this design" explanation.
"""
from __future__ import annotations

import hashlib
import json as _json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mediahub.inspiration.pattern_library import best_pattern_for, get_pattern, patterns_for_post_angle, PATTERNS
from mediahub.media_ai import generate_json, is_available as _llm_available


@dataclass
class CreativeBrief:
    id: str
    content_item_id: str
    profile_id: str
    achievement_summary: str
    objective: str
    primary_hook: str            # the main message/headline
    confidence_label: str        # "NEW PB" / "LIKELY PB" / "GOLD" / etc.
    tone: str                    # e.g. "data_led", "hype", "warm_club"
    layout_template: str         # maps to graphic_renderer/layouts/<template>.html
    inspiration_pattern_id: str
    image_treatment: str
    text_hierarchy: list[str]
    brand_instructions: str
    sponsor_instructions: Optional[str]
    sourced_asset_ids: list[str]
    safety_notes: list[str]
    why_this_design: str
    text_layers: dict[str, str]    # actual text values keyed by layer name
    palette: dict[str, str]        # primary/secondary/accent
    format_priority: list[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(content_item: dict, evaluation, brand_kit, *,
             voice_profile=None, profile_id: str = "",
             meet_name: str = "", venue_name: str = "",
             sponsor: Optional[dict] = None,
             variation_seed: int = 0) -> CreativeBrief:
    """Build a CreativeBrief. Pure function — never reaches network unless
    LLM is available; falls back to deterministic defaults otherwise.

    ``variation_seed`` controls deterministic perturbation of the layout,
    palette role mapping, image treatment, and headline phrasing. ``0``
    keeps the default behaviour. ``1`` keeps the same family but inverts
    colour roles. ``2`` swaps to a different layout family. ``3`` forces a
    text-led / no-photo treatment.
    """

    ach = content_item.get("achievement") or {}
    angle = content_item.get("post_angle") or ach.get("post_angle") or "recap_mention"

    # Pick layout
    fmt_hint = "feed_portrait"
    family_hint = evaluation.suggested_layout if evaluation else None
    pattern = best_pattern_for(angle, format_hint=fmt_hint, prefer_family=family_hint)

    # ---- Variation seed: rotate pattern / image treatment if requested ----
    if variation_seed and variation_seed != 0:
        pattern = _rotate_pattern_for_seed(pattern, angle, variation_seed)

    # Athlete + result vocabulary (sport-agnostic — we read whatever the
    # detectors put in the achievement dict)
    athlete = (
        ach.get("swimmer_name")
        or content_item.get("swimmer_name")
        or ach.get("athlete_name")
        or content_item.get("athlete_name")
        or ""
    )
    surname = athlete.split()[-1] if athlete else ""
    first = athlete.split()[0] if athlete else ""
    event = (
        ach.get("event_name")
        or ach.get("event")
        or content_item.get("event")
        or content_item.get("event_name")
        or ""
    )
    raw_facts = ach.get("raw_facts") or {}
    result = (
        ach.get("result_time")
        or ach.get("time")
        or ach.get("result")
        or ach.get("value")
        or raw_facts.get("time_str")
        or raw_facts.get("time")
        or raw_facts.get("result")
        or content_item.get("result_time")
        or content_item.get("time")
        or ""
    )
    place = (
        ach.get("place")
        or ach.get("position")
        or raw_facts.get("place")
        or raw_facts.get("position")
        or ""
    )

    # Achievement summary
    summary_bits = [evaluation.confidence_label if evaluation else angle]
    if athlete:
        summary_bits.append(athlete)
    if event:
        summary_bits.append(event)
    if result:
        summary_bits.append(str(result))
    summary = " · ".join(b for b in summary_bits if b)

    # Headline / hook
    label = evaluation.confidence_label if evaluation else "STRONG SWIM"
    if angle in ("medal_gold", "medal_silver", "medal_bronze", "medal_and_pb_combo"):
        primary_hook = label
    elif angle == "first_sub_barrier":
        primary_hook = label  # FIRST UNDER (paired with the result)
    else:
        primary_hook = label

    # Tone — read voice profile when possible
    tone = "data_led"
    if voice_profile and hasattr(voice_profile, "tone"):
        tone = getattr(voice_profile, "tone", None) or tone
    if angle in ("first_sub_barrier", "medal_gold", "medal_and_pb_combo"):
        tone = "hype"
    if angle in ("recap_mention", "weekend_recap", "weekend_in_numbers", "team_depth"):
        tone = "warm_club"

    # Build text layers (the renderer reads these directly)
    layers: dict[str, str] = {
        "achievement_label": label,
        "athlete_full_name": athlete,
        "athlete_first_name": first,
        "athlete_surname": surname,
        "event_name": event,
        "result_value": str(result),
        "place": str(place),
        "meet_name": meet_name or content_item.get("meet_name") or "",
        "venue_name": venue_name or "",
        "club_short": (
            getattr(brand_kit, "short_name", None)
            or getattr(brand_kit, "display_name", "")
            or ""
        ),
        "club_full": getattr(brand_kit, "display_name", "") or "",
        "sponsor_label": (sponsor or {}).get("name", "") if sponsor else "",
    }
    # Weekend-in-numbers extra fields
    if angle == "weekend_in_numbers":
        # caller can hand a `numbers` dict
        nums = content_item.get("numbers") or content_item.get("stats") or {}
        for k, v in nums.items():
            layers[f"stat_{k}"] = str(v)

    # Palette
    base_primary = getattr(brand_kit, "primary_colour", "#A30D2D")
    base_secondary = getattr(brand_kit, "secondary_colour", "#000000")
    base_accent = getattr(brand_kit, "accent_colour", None) or "#FFFFFF"
    palette = _apply_palette_seed(base_primary, base_secondary, base_accent, variation_seed)

    # Brand / sponsor instructions
    brand_instr = (
        f"Use {palette['primary']} as the dominant ground colour. "
        f"Use {palette['secondary']} for surfaces and the brand corner. "
        f"Accent {palette['accent']} for chips and rim-light. "
        f"Place the club logo bottom-left in a respectful clear zone. "
        f"Display name: {layers['club_full']}."
    )
    sponsor_instr = None
    if sponsor and sponsor.get("name"):
        sponsor_instr = (
            f"Reserve a clean 12% bottom strip for the sponsor block. "
            f"Sponsor: {sponsor['name']}. Tagline: 'Performance supported by'."
        )

    # Safety notes
    safety: list[str] = []
    if evaluation:
        if evaluation.confidence_tier != "high":
            safety.append(f"hedged_language_{evaluation.confidence_tier}")
        for missing in evaluation.missing_optional:
            safety.append(f"missing_optional_{missing}")
        for asset_role, scored in (evaluation.matched or {}).items():
            top = scored[0] if scored else None
            if top and isinstance(top, dict) and top.get("asset_id") != "_brand_logo_":
                a = top.get("asset", {})
                if a.get("permission_status") in ("needs_approval", "internal_only"):
                    safety.append(f"permission_check_{asset_role}_{a.get('permission_status')}")
                if a.get("safe_for_minors") is False:
                    safety.append(f"minor_consent_pending_{asset_role}")
                if a.get("source_url"):
                    safety.append(f"web_sourced_{asset_role}")
    if athlete:
        safety.append("likeness_preserved_real_photo")

    # Sourced asset ids
    sourced: list[str] = []
    if evaluation:
        for role, scored in (evaluation.matched or {}).items():
            for s in scored[:1]:  # only the chosen one
                aid = s.get("asset_id")
                if aid and aid != "_brand_logo_":
                    sourced.append(aid)

    # Why-this-design — try LLM, otherwise deterministic
    why = _generate_why_this_design(angle, evaluation, pattern, athlete, summary)

    # Objective
    objective_map = {
        "confirmed_official_pb": "Celebrate a confirmed PB and drive athlete repostability.",
        "pb_improvement": "Celebrate a PB improvement and signal momentum.",
        "first_sub_barrier": "Celebrate breaking a milestone barrier in a way that's easy for non-swimmers to understand.",
        "medal_gold": "Recognise a gold-medal finish with on-brand, sponsor-safe layout.",
        "medal_silver": "Recognise a silver-medal finish.",
        "medal_bronze": "Recognise a bronze-medal finish.",
        "medal_and_pb_combo": "Highlight a medal-plus-PB double — combine medal hierarchy with PB drama.",
        "weekend_in_numbers": "Summarise the meet in a sponsor-safe, athlete-name-free recap.",
        "athlete_spotlight": "Profile an athlete with multiple achievements this weekend.",
        "meet_preview": "Build anticipation for an upcoming meet using venue and headliners.",
        "recap_mention": "Mention a strong performance without forcing a hero post.",
    }
    objective = objective_map.get(angle, "Recognise a notable performance.")

    # Headline phrasing tweak per seed
    if variation_seed:
        primary_hook = _phrase_for_seed(primary_hook, label, angle, variation_seed)
        layers["achievement_label"] = primary_hook

    image_treatment = pattern.get("image_treatment", "")
    if variation_seed == 3:
        # Force text-led / no photo
        image_treatment = "no photo, text-led layout"

    return CreativeBrief(
        id="cb_" + uuid.uuid4().hex[:12],
        content_item_id=str(content_item.get("id") or content_item.get("swim_id") or ach.get("swim_id") or ""),
        profile_id=profile_id,
        achievement_summary=summary,
        objective=objective,
        primary_hook=primary_hook,
        confidence_label=label,
        tone=tone,
        layout_template=pattern["family"],
        inspiration_pattern_id=pattern["id"],
        image_treatment=image_treatment,
        text_hierarchy=list(pattern.get("text_hierarchy", [])),
        brand_instructions=brand_instr,
        sponsor_instructions=sponsor_instr,
        sourced_asset_ids=sourced,
        safety_notes=safety,
        why_this_design=why,
        text_layers=layers,
        palette=palette,
        format_priority=list(pattern.get("format_priority", ["feed_portrait", "story", "feed_square"])),
    )


# ---------------------------------------------------------------------------
# Why-this-design — short LLM rationale; safe fallback
# ---------------------------------------------------------------------------

def _generate_why_this_design(angle: str, evaluation, pattern: dict,
                              athlete: str, summary: str) -> str:
    fb_parts: list[str] = []
    fb_parts.append(f"Pattern '{pattern['label']}' fits {angle} ({pattern['why_use_this']}).")
    if evaluation:
        if evaluation.confidence_tier != "high":
            fb_parts.append(f"Confidence is {evaluation.confidence_tier} — wording hedged ('{evaluation.confidence_label}').")
        if evaluation.matched.get("hero_athlete"):
            fb_parts.append(f"Using a real photo of {athlete}.")
        if evaluation.missing_optional:
            fb_parts.append(f"Optional missing ({', '.join(evaluation.missing_optional)}) — design works without.")
    fb = " ".join(fb_parts)

    if not _llm_available():
        return fb

    sys = (
        "You write one short paragraph (max 60 words) explaining why a sports "
        "graphic was designed the way it was. No fluff. No bullet points. "
        "Write in the voice of an art director."
    )
    prompt = (
        f"Achievement: {summary}\n"
        f"Pattern chosen: {pattern['label']} — {pattern['why_use_this']}\n"
        f"Confidence tier: {evaluation.confidence_tier if evaluation else 'unknown'}\n"
        f"Confidence label: {evaluation.confidence_label if evaluation else 'STRONG SWIM'}\n"
        f"Has athlete photo: {bool(evaluation and evaluation.matched.get('hero_athlete'))}\n"
        f"Explain in one short paragraph why this design choice fits."
    )
    from mediahub.media_ai import generate as _gen
    out = _gen(prompt, system=sys, max_tokens=200)
    if out and "fallback" not in out.lower() and len(out) > 30:
        return out.strip()
    return fb


# ---------------------------------------------------------------------------
# Vision-based creative direction (V8.1 Issue 7 §5)
# ---------------------------------------------------------------------------

_VISION_CACHE_DIR = Path("data/cache/vision_briefs")
_VISION_TTL_SECONDS = 24 * 60 * 60  # 24h


def _vision_cache_key(asset_id: str, brand_id: str, photo_path: str) -> str:
    """Stable cache key per (asset, brand, photo content fingerprint).

    The first 64 KB of the photo is mixed in so a re-uploaded photo with
    the same name doesn't return a stale direction.
    """
    h = hashlib.sha256()
    h.update(str(asset_id).encode())
    h.update(b"|")
    h.update(str(brand_id).encode())
    try:
        with open(photo_path, "rb") as f:
            h.update(f.read(65536))
    except Exception:
        h.update(str(photo_path).encode())
    return h.hexdigest()[:24]


def _vision_cache_get(key: str) -> Optional[str]:
    p = _VISION_CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        data = _json.loads(p.read_text("utf-8"))
        if not isinstance(data, dict):
            return None
        if time.time() - float(data.get("ts", 0)) > _VISION_TTL_SECONDS:
            return None
        v = data.get("value")
        return v if isinstance(v, str) and v.strip() else None
    except Exception:
        return None


def _vision_cache_put(key: str, value: str) -> None:
    try:
        _VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_VISION_CACHE_DIR / f"{key}.json").write_text(
            _json.dumps({"ts": time.time(), "value": value}),
            encoding="utf-8",
        )
    except Exception:
        pass


def vision_creative_direction(
    photo_path,
    *,
    asset_id: str,
    brand_id: str,
    brand_kit=None,
    achievement_summary: str = "",
) -> Optional[str]:
    """Ask Claude vision for a 2-sentence creative direction string.

    Returns the direction text on success, or ``None`` if no key is
    configured / call failed / image unreadable. Callers must treat None
    as "skip vision step" — the rule-based brief continues to drive output.

    Cached per (asset_id, brand_id, photo content) for 24h to avoid
    repeated API calls on regenerate / format-trio renders.
    """
    if not _llm_available():
        return None
    photo_path = str(photo_path)
    if not Path(photo_path).is_file():
        return None

    cache_key = _vision_cache_key(asset_id or "_", brand_id or "_", photo_path)
    cached = _vision_cache_get(cache_key)
    if cached:
        return cached

    primary = (getattr(brand_kit, "primary_colour", None) or "#0A2540")
    secondary = (getattr(brand_kit, "secondary_colour", None) or "#101820")
    accent = (getattr(brand_kit, "accent_colour", None) or "#FFFFFF")
    club_name = (getattr(brand_kit, "display_name", None) or "")

    sys_prompt = (
        "You are an art director for a sports content studio. Look at the "
        "athlete photo and brand info, then write EXACTLY two short sentences "
        "of creative direction for a social-media graphic celebrating this "
        "performance. Speak about composition, mood, and how the athlete's "
        "posture / gaze / energy should drive the layout. No bullet points, "
        "no headers, no fluff, no quoting hex codes back at me."
    )
    user_prompt = (
        f"Club: {club_name}\n"
        f"Brand colours: primary {primary}, secondary {secondary}, accent {accent}.\n"
        f"Achievement: {achievement_summary or 'a strong swim performance'}.\n"
        f"Now write the two-sentence creative direction."
    )
    try:
        from mediahub.media_ai.llm import generate_vision
        out = generate_vision(
            [photo_path], user_prompt, system=sys_prompt, max_tokens=180,
        )
    except Exception:
        return None
    if not out or len(out.strip()) < 30:
        return None
    out = out.strip()
    if out.startswith(("- ", "• ", "#")):
        out = out.lstrip("-•# ").strip()
    _vision_cache_put(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# Variation helpers (deterministic per seed)
# ---------------------------------------------------------------------------

def _rotate_pattern_for_seed(default_pattern: dict, angle: str, seed: int) -> dict:
    """Pick a different pattern based on ``seed``.

    seed == 1 -> keep the same pattern (palette is what changes elsewhere).
    seed == 2 -> rotate to a *different family* among compatible patterns.
    seed == 3 -> force a text-led / no-photo family (e.g. text_led_recap or
                 weekend_numbers) so the visual is visibly different.
    """
    if seed == 1:
        return default_pattern

    if seed == 3:
        # Strict no-photo families.
        text_led = next((p for p in PATTERNS if p["family"] == "text_led_recap"), None)
        wknd = next((p for p in PATTERNS if p["family"] == "weekend_numbers"), None)
        # If default is already text_led_recap, fall back to weekend_numbers.
        if default_pattern["family"] == "text_led_recap" and wknd:
            return wknd
        if text_led:
            return text_led
        return default_pattern

    # seed == 2 (or any other): pick a different family.
    candidates = patterns_for_post_angle(angle) or list(PATTERNS)
    others = [p for p in candidates if p["family"] != default_pattern["family"]]
    if not others:
        # Fall back to *any* other family in PATTERNS.
        others = [p for p in PATTERNS if p["family"] != default_pattern["family"]]
    if not others:
        return default_pattern
    return others[seed % len(others)]


def _apply_palette_seed(primary: str, secondary: str, accent: str, seed: int) -> dict[str, str]:
    """Permute role assignments based on the seed.

    seed 0 -> identity
    seed 1 -> primary <-> secondary inversion ("inverted colour roles")
    seed 2 -> rotate primary -> accent -> secondary -> primary
    seed 3 -> primary <-> accent
    """
    if not seed:
        return {"primary": primary, "secondary": secondary, "accent": accent}
    if seed == 1:
        return {"primary": secondary, "secondary": primary, "accent": accent}
    if seed == 2:
        return {"primary": accent, "secondary": primary, "accent": secondary}
    if seed == 3:
        return {"primary": accent, "secondary": secondary, "accent": primary}
    # Fallback: identity
    return {"primary": primary, "secondary": secondary, "accent": accent}


def _phrase_for_seed(default_hook: str, label: str, angle: str, seed: int) -> str:
    """Tweak the headline phrasing deterministically."""
    if not seed:
        return default_hook
    label = (label or default_hook or "").upper()
    variants_by_seed = {
        1: {
            "NEW PB": "PERSONAL BEST",
            "LIKELY PB": "LIKELY PERSONAL BEST",
            "GOLD": "FIRST PLACE",
            "SILVER": "SECOND PLACE",
            "BRONZE": "THIRD PLACE",
            "STRONG SWIM": "BIG SWIM",
        },
        2: {
            "NEW PB": "BEST EVER",
            "LIKELY PB": "BEST EVER (PROVISIONAL)",
            "GOLD": "GOLD MEDAL",
            "SILVER": "SILVER MEDAL",
            "BRONZE": "BRONZE MEDAL",
            "STRONG SWIM": "STANDOUT SWIM",
        },
        3: {
            "NEW PB": "PB ALERT",
            "LIKELY PB": "PB CONTENDER",
            "GOLD": "TOP OF THE PODIUM",
            "SILVER": "PODIUM FINISH",
            "BRONZE": "PODIUM FINISH",
            "STRONG SWIM": "NOTABLE PERFORMANCE",
        },
    }
    table = variants_by_seed.get(seed, {})
    return table.get(label, default_hook)


__all__ = ["generate", "CreativeBrief", "vision_creative_direction"]
