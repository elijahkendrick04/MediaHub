"""
apply_brand(card, kit, tone, content_type) → card dict with rendered captions.

Given a V4/V5 card dict and brand settings, this function adds a
'brand_captions' key with rendered captions for all three tones:
  {
    "warm-club": {"headline": "...", "body": "...", "cta": "..."},
    "hype":      {"headline": "...", "body": "...", "cta": "..."},
    "data-led":  {"headline": "...", "body": "...", "cta": "..."},
  }

It also adds 'active_caption' — the rendered captions for the profile's
selected tone — as a convenience.

The function is pure: it returns a new dict and never mutates the input.
"""
from __future__ import annotations

from typing import Optional

from .kit import BrandKit
from .tone import Tone
from .templates import render_template, get_default_templates


def _build_ctx(card: dict, kit: BrandKit) -> dict:
    """
    Extract caption variables from a card dict and brand kit.
    Supports both V4 card dicts and V5 RankedAchievement dicts.
    """
    # V5 RankedAchievement has 'achievement' nested
    ach = card.get("achievement") or card

    swimmer_full = ach.get("swimmer_name", "") or card.get("swimmer_name", "")
    swimmer_short = swimmer_full.split()[0] if swimmer_full else "—"

    # Time formatting — V5 raw_facts uses time_str / time_sec; V4 uses finals_cs.
    rf = ach.get("raw_facts", {}) or {}
    time_str = (
        rf.get("time_str")
        or _cs_to_str(rf.get("finals_cs") or card.get("finals_time_cs"))
        or ach.get("event_time", "")
        or "—"
    )

    # Previous PB — V6 PBDecision attaches as prev_pb_seconds / prev_pb_time;
    # V4 used prev_pb_cs.
    prev_pb_str = (
        rf.get("prev_pb_time")
        or rf.get("prev_pb_str")
        or _cs_to_str(rf.get("prev_pb_cs"))
        or "—"
    )

    # Drop magnitude
    drop_seconds_val = rf.get("drop_seconds") or rf.get("improvement_seconds")
    drop_cs = rf.get("drop_cs")
    if drop_seconds_val:
        drop_seconds = f"{abs(float(drop_seconds_val)):.2f}"
        drop_pretty = f"−{drop_seconds}s"
    elif drop_cs:
        drop_seconds = f"{abs(drop_cs)/100:.2f}"
        drop_pretty = f"−{drop_seconds}s"
    else:
        drop_seconds = "—"
        drop_pretty = "—"

    place_val = ach.get("raw_facts", {}).get("place") or card.get("place", "")
    medal_map = {1: "gold", 2: "silver", 3: "bronze"}
    medal = medal_map.get(int(place_val), "") if str(place_val).isdigit() else ""

    # Event from headline text or raw_facts
    event = ach.get("event") or card.get("event", "—")

    return {
        "swimmer": swimmer_full or "—",
        "swimmer_short": swimmer_short,
        "event": event,
        "course": ach.get("raw_facts", {}).get("course", "") or "—",
        "time": time_str,
        "prev_pb": prev_pb_str,
        "drop_seconds": drop_seconds,
        "drop_pretty": drop_pretty,
        "place": str(place_val) if place_val else "—",
        "medal": medal,
        "meet": ach.get("meet_name", "") or "—",
        "club": kit.short_name or kit.display_name or "—",
        "type": ach.get("type", "") or card.get("card_type", "—"),
    }


def _cs_to_str(cs: Optional[int]) -> str:
    if cs is None:
        return "—"
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def apply_brand(
    card: dict,
    kit: BrandKit,
    tone: Tone,
    content_type: str = "meet_recap",
    caption_templates: Optional[dict] = None,
) -> dict:
    """
    Return a copy of card with 'brand_captions' and 'active_caption' added.

    Parameters
    ----------
    card : dict
        A V4 card dict or V5 RankedAchievement dict.
    kit : BrandKit
        The club's brand kit (for name/colour context).
    tone : Tone
        The profile's selected tone (used to set 'active_caption').
    content_type : str
        "meet_recap" | "athlete_spotlight" (template selection key).
    caption_templates : dict | None
        Overrides from the profile's stored templates dict.
        Structure: {content_type: {tone_str: {slot: template_str}}}
    """
    ctx = _build_ctx(card, kit)
    out = dict(card)

    all_tones = ["warm-club", "hype", "data-led"]
    brand_captions: dict[str, dict[str, str]] = {}

    for t_str in all_tones:
        # Resolve template source: profile override → defaults
        if caption_templates:
            slot_map = (
                caption_templates.get(content_type, {}).get(t_str)
                or get_default_templates(content_type, t_str)
            )
        else:
            slot_map = get_default_templates(content_type, t_str)

        rendered = {
            slot: render_template(tmpl, ctx)
            for slot, tmpl in slot_map.items()
        }

        # Fallback: if a template renders with too many em-dash placeholders,
        # the achievement context didn't have the keys this template needed.
        # Use the achievement's own headline so the user sees something useful.
        ach = card.get("achievement") or card
        ach_headline = ach.get("headline") or ""
        ach_angle = ach.get("angle_hint") or ""
        for slot, txt in list(rendered.items()):
            # Count placeholder occurrences. If > 1, the template wasn't right
            # for this achievement type — substitute the achievement's own copy.
            if txt.count("—") >= 2:
                if slot == "headline" and ach_headline:
                    rendered[slot] = ach_headline
                elif slot == "body" and ach_angle:
                    rendered[slot] = ach_angle
                elif slot == "cta":
                    rendered[slot] = ""

        brand_captions[t_str] = rendered

    out["brand_captions"] = brand_captions
    out["active_caption"] = brand_captions.get(tone.value, brand_captions.get("warm-club", {}))
    return out
