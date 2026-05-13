"""Curated layout-pattern library — shape descriptions only, never image rips.

Each pattern is a dict describing the *layout family* (composition, hierarchy,
typography pairing, treatment) — these are how-to-arrange recipes, not
copyrighted designs. The renderer picks one and instantiates it with the
brand kit + real photos + verified data.
"""
from __future__ import annotations

PATTERNS: list[dict] = [
    {
        "id": "athlete_cutout_surname_bg",
        "label": "Athlete cutout · oversized surname BG",
        "family": "individual_hero",
        "post_angles": ["confirmed_official_pb", "pb_improvement", "first_sub_barrier",
                        "likely_pb", "finalist", "top_of_field", "qualifying_time",
                        "biggest_drop", "fastest_since", "return_to_form"],
        "format_priority": ["feed_portrait", "story", "feed_square"],
        "composition": (
            "Athlete cutout dominates lower-right. "
            "Oversized surname (or first name) sits behind the cutout, partially occluded — "
            "the surname becomes a typographic backdrop. Result chip pinned top-right; "
            "achievement label (e.g. NEW PB) ribbon top-left. Brand corner at bottom-left "
            "with logo + meet name."
        ),
        "typography": {
            "headline_font": "Druk-style condensed or Bebas Neue (free alt)",
            "body_font": "Inter / Space Grotesk",
            "headline_weight": "900 / heavy",
            "body_weight": "500-700",
            "tracking": "tight on headline, normal on body",
        },
        "colour_treatment": (
            "Background: club primary at 100%, gradient towards secondary across the bottom 30%. "
            "Subtle large-format texture (e.g. ripple, halftone) at 8% opacity. "
            "Cutout has rim-light glow in accent or secondary colour."
        ),
        "text_hierarchy": [
            "achievement_label",         # 1st: NEW PB
            "athlete_surname",           # 2nd: oversized BG
            "result_value",              # 3rd: chip
            "event_name",                # 4th
            "athlete_first_name",        # 5th
            "meet_name",                 # 6th: small
            "club_branding",             # 7th: corner
        ],
        "image_treatment": "real cutout, slight contrast lift, subtle drop shadow",
        "why_use_this": (
            "Modern sports IG signature look for individual achievements. "
            "Reads instantly at thumbnail size; surname does the heavy hierarchical work."
        ),
    },
    {
        "id": "medal_card_centre",
        "label": "Medal centre badge · athlete left",
        "family": "medal_card",
        "post_angles": ["medal_gold", "medal_silver", "medal_bronze", "medal_and_pb_combo",
                        "relay_highlight"],
        "format_priority": ["feed_square", "story", "feed_portrait"],
        "composition": (
            "Two-column: left half athlete cutout against gradient. Right half centred "
            "medal badge (large circular emblem). Below the badge, event + result + meet."
        ),
        "typography": {
            "headline_font": "Bebas Neue / Druk-style condensed",
            "body_font": "Inter",
            "headline_weight": "900",
            "body_weight": "500-600",
        },
        "colour_treatment": (
            "Medal-tier tint: gold #C9A227 / silver #C0C0C0 / bronze #CD7F32. "
            "Background gradient: club primary → medal tint at 25% opacity."
        ),
        "text_hierarchy": [
            "medal_label",               # GOLD / SILVER / BRONZE
            "athlete_name",
            "event_name",
            "result_value",
            "meet_name",
        ],
        "image_treatment": "cutout, dramatic side-light, slight desaturation under badge",
        "why_use_this": (
            "Award imagery without faking a podium photo. The medal is graphic, not photographic — "
            "so we don't impersonate a moment that didn't happen on camera."
        ),
    },
    {
        "id": "weekend_numbers_grid",
        "label": "Weekend in numbers · stat grid",
        "family": "weekend_numbers",
        "post_angles": ["weekend_in_numbers", "team_depth", "recap_mention"],
        "format_priority": ["feed_square", "feed_portrait", "story"],
        "composition": (
            "2x2 or 3x2 grid of large stat tiles. Each tile = oversized number + tiny label. "
            "Top strip: meet name + dates. Bottom strip: club brand + sponsor (if any)."
        ),
        "typography": {
            "headline_font": "Druk-style condensed / Anton",
            "body_font": "Inter",
            "headline_weight": "900",
            "body_weight": "500",
        },
        "colour_treatment": (
            "Dark ground (club secondary) with each tile a different accent variant. "
            "Numbers: pure white. Labels: 60% white."
        ),
        "text_hierarchy": [
            "meet_label",
            "stat_value",                # repeated per tile
            "stat_label",                # repeated per tile
            "club_branding",
        ],
        "image_treatment": "no athlete photo (text-led)",
        "why_use_this": (
            "Sponsor-safe, athlete-name-free, repostable by everyone in the club. "
            "Best when athlete photos are missing or for top-of-funnel summary content."
        ),
    },
    {
        "id": "athlete_spotlight_profile",
        "label": "Athlete spotlight · profile + multi-stat",
        "family": "athlete_spotlight",
        "post_angles": ["athlete_spotlight", "multi_pb_weekend"],
        "format_priority": ["feed_portrait", "story", "feed_square"],
        "composition": (
            "Athlete cutout occupies left third. Right two-thirds: name in large type, "
            "then a vertical stack of 3-4 stat rows (event | result | label). "
            "Footer: club + meet."
        ),
        "typography": {
            "headline_font": "Bebas Neue / Druk-style",
            "body_font": "Inter / Space Grotesk",
            "headline_weight": "900",
            "body_weight": "500-700",
        },
        "colour_treatment": "club primary background with secondary accent rules between rows",
        "text_hierarchy": [
            "athlete_name",
            "stat_rows",
            "meet_name",
            "club_branding",
        ],
        "image_treatment": "cutout with subtle vignette",
        "why_use_this": "Best for 'multiple wins this weekend' — packs several achievements with face.",
    },
    {
        "id": "meet_preview_venue",
        "label": "Meet preview · venue hero",
        "family": "meet_preview",
        "post_angles": ["meet_preview"],
        "format_priority": ["feed_portrait", "story", "feed_square"],
        "composition": (
            "Top half: venue photo with deep gradient overlay. "
            "Lower half: meet name (huge), dates, key athletes, club logo."
        ),
        "typography": {
            "headline_font": "Druk-style / Anton",
            "body_font": "Inter",
        },
        "colour_treatment": "venue photo desaturated 30%, gradient ramp from transparent to club primary",
        "text_hierarchy": [
            "meet_name",
            "dates",
            "venue_name",
            "headliners",
            "club_branding",
        ],
        "image_treatment": "venue photo, source attribution shown in caption",
        "why_use_this": "Anchors the audience to the place; pairs naturally with 'whose racing' carousel.",
    },
    {
        "id": "sponsor_branded_strip",
        "label": "Sponsor footer · clean achievement",
        "family": "sponsor_branded",
        "post_angles": ["confirmed_official_pb", "medal_gold", "medal_silver",
                        "medal_bronze", "athlete_spotlight"],
        "format_priority": ["feed_portrait", "feed_square", "story"],
        "composition": (
            "Same composition as athlete_cutout_surname_bg but reserves a clean 12% bottom "
            "strip for sponsor logo + 'Performance supported by' line. "
            "Hierarchy keeps achievement as hero, sponsor secondary."
        ),
        "typography": {
            "headline_font": "Druk-style",
            "body_font": "Inter",
        },
        "colour_treatment": "sponsor strip on neutral white or dark to respect logo clear-space",
        "text_hierarchy": [
            "achievement_label",
            "athlete_surname",
            "result_value",
            "event_name",
            "sponsor_strip",
            "club_branding",
        ],
        "image_treatment": "cutout, sponsor-safe — no clutter behind logo",
        "why_use_this": "Sponsor visibility without burying the athlete or look-cluttering the design.",
    },
    {
        "id": "text_led_recap",
        "label": "Text-led recap · type-driven",
        "family": "text_led_recap",
        "post_angles": ["recap_mention", "weekend_recap"],
        "format_priority": ["feed_square", "feed_portrait", "story"],
        "composition": (
            "Big headline (e.g. WEEKEND RECAP), then 3 short body lines as bullets. "
            "Optional venue thumbnail in a corner. Brand corner."
        ),
        "typography": {
            "headline_font": "Druk / Anton",
            "body_font": "Inter",
        },
        "colour_treatment": "high-contrast: club primary background, white type",
        "text_hierarchy": [
            "headline",
            "body_lines",
            "meet_name",
            "club_branding",
        ],
        "image_treatment": "no photo required",
        "why_use_this": "Reliable fallback when no good athlete or venue image is available.",
    },
    {
        "id": "story_card_simple",
        "label": "Story card · stack-friendly",
        "family": "story_card",
        "post_angles": ["confirmed_official_pb", "medal_gold", "medal_silver", "medal_bronze",
                        "first_sub_barrier", "finalist", "top_of_field"],
        "format_priority": ["story", "feed_portrait"],
        "composition": (
            "1080x1920. Top 22% safe-zone left empty for IG UI. "
            "Athlete cutout fills middle. Achievement label + result chip in middle band. "
            "Bottom 18% reserved for swipe/CTA + brand corner."
        ),
        "typography": {
            "headline_font": "Druk-style",
            "body_font": "Inter",
        },
        "colour_treatment": "club primary gradient, big readable type",
        "text_hierarchy": [
            "achievement_label",
            "athlete_name",
            "result_value",
            "event_name",
        ],
        "image_treatment": "cutout, optimised for thumbs-zone",
        "why_use_this": "Fast story output that respects the safe margins of the IG story UI.",
    },
    {
        "id": "reel_cover_dramatic",
        "label": "Reel cover · dramatic cutout",
        "family": "reel_cover",
        "post_angles": ["confirmed_official_pb", "medal_gold", "first_sub_barrier",
                        "athlete_spotlight"],
        "format_priority": ["story"],
        "composition": (
            "Vertical 1080x1920. Athlete cutout dominates frame, dramatic crop. "
            "Three-word title bottom-third. First-frame readable in 9:16 grid crop."
        ),
        "typography": {
            "headline_font": "Druk-style / Anton",
            "body_font": "Inter",
        },
        "colour_treatment": "high-contrast, often black ground with single accent",
        "text_hierarchy": [
            "headline_short",
            "athlete_name",
        ],
        "image_treatment": "cutout, heavy contrast",
        "why_use_this": "Optimised for IG reels grid crop; first frame must work as cover.",
    },
]


PATTERNS.append({
    "id": "big_number_hero",
    "label": "Hero numeral — time/result as the dominant visual",
    "family": "big_number_hero",
    "post_angles": ["confirmed_official_pb", "pb_improvement", "first_sub_barrier",
                    "likely_pb", "finalist", "top_of_field", "qualifying_time",
                    "biggest_drop", "fastest_since", "gold_medal", "silver_medal",
                    "bronze_medal", "podium_finish"],
    "format_priority": ["feed_portrait", "feed_square", "story"],
    "composition": (
        "The result/time numeral fills ~55% of canvas height, centered. "
        "Event name sits above as a small spaced-caps strip. Athlete name "
        "sits below in Bebas display. Brand corner is centered along the "
        "bottom with logo + club + meet. Two accent-coloured corner brackets "
        "(top-left, bottom-right) frame the composition."
    ),
    "typography": {
        "headline_font": "Anton (heavy condensed) for the numeral",
        "body_font": "Inter / Bebas Neue",
        "headline_weight": "900",
        "body_weight": "600-700",
        "tracking": "very tight on numeral, wide on event caps",
    },
    "colour_treatment": (
        "Background: brand primary gradient with vignette. Numeral in white. "
        "Event subtitle in accent colour. Corner brackets in accent at 35% opacity."
    ),
    "image_treatment": "no photo required — text-led, equally strong with or without an athlete cutout",
    "text_layers": ["event_name", "result_value", "athlete_full_name", "meet_name", "club_full"],
    "why_use_this": (
        "When the result is the headline (PB, qualifying time, gold-medal time), the time itself "
        "deserves to be the visual hero — competitor pattern from Holo/Predis/Blaze. Works "
        "perfectly when no athlete photo is available."
    ),
})


def list_patterns() -> list[dict]:
    return [{"id": p["id"], "label": p["label"], "family": p["family"]} for p in PATTERNS]


def get_pattern(pattern_id: str) -> dict | None:
    for p in PATTERNS:
        if p["id"] == pattern_id:
            return p
    return None


def patterns_for_post_angle(post_angle: str) -> list[dict]:
    """Return all patterns that name this post_angle as suitable."""
    return [p for p in PATTERNS if post_angle in p.get("post_angles", [])]


def best_pattern_for(post_angle: str, *, format_hint: str | None = None,
                     prefer_family: str | None = None) -> dict:
    """Pick the single best pattern for the inputs. Falls back to text_led_recap."""
    candidates = patterns_for_post_angle(post_angle)
    if not candidates:
        candidates = [p for p in PATTERNS if p["id"] == "text_led_recap"]
    if prefer_family:
        match = [p for p in candidates if p["family"] == prefer_family]
        if match:
            candidates = match
    if format_hint:
        scored = [(p, p["format_priority"].index(format_hint) if format_hint in p["format_priority"] else 99)
                  for p in candidates]
        scored.sort(key=lambda x: x[1])
        return scored[0][0]
    return candidates[0]


__all__ = [
    "PATTERNS",
    "list_patterns",
    "get_pattern",
    "patterns_for_post_angle",
    "best_pattern_for",
]
