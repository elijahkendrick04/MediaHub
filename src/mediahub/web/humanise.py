"""
swim_content_v4/humanise.py — V7.4

Maps raw internal identifiers (achievement types, post angles, status codes,
profile slugs, etc.) to friendly human-readable labels.

Usage:
    from mediahub.web.humanise import humanise, format_post_angle

    label = humanise('pb_confirmed')          # → 'Confirmed PB'
    label = format_post_angle('medal_gold')   # → 'Gold medal'
    label = humanise_status('pb_unverified')  # → 'PB not verified'
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Achievement type → friendly label
# ---------------------------------------------------------------------------

_ACHIEVEMENT_LABELS: dict[str, str] = {
    # PB types
    "pb_confirmed": "Confirmed PB",
    "official_pb_confirmed": "Confirmed Official PB",
    "pb_likely": "Likely PB",
    "pb_unverified": "PB (unverified)",
    "pb_magnitude_huge": "Huge PB",
    "pb_magnitude_big": "Big PB",
    "pb_magnitude_notable": "Notable PB",

    # Medal types
    "medal_gold": "Gold medal",
    "medal_silver": "Silver medal",
    "medal_bronze": "Bronze medal",
    "relay_medal_gold": "Gold relay medal",
    "relay_medal_silver": "Silver relay medal",
    "relay_medal_bronze": "Bronze relay medal",

    # Milestone types
    "first_sub_barrier": "First-time barrier break",
    "first_sub_60": "First sub-60 second swim",
    "first_sub_30": "First sub-30 second swim",
    "first_sub_120": "First sub-2 minute swim",
    "first_sub_barrier_60": "First sub-60",
    "first_sub_barrier_30": "First sub-30",

    # Multi-swim types
    "multi_pb_weekend": "Multi-PB weekend",
    "biggest_drop_of_meet": "Biggest time drop of meet",
    "biggest_drop_candidate": "Time drop highlight",
    "heat_to_final_drop": "Heat-to-final improvement",

    # History types
    "return_to_form": "Return to form",
    "fastest_since": "Season best",
    "fastest_since_date": "Season best",

    # Qualification types
    "qualifying_time": "Qualifying time",
    "qual_hit_in_window": "Qualifier hit",
    "qual_hit_out_of_window": "Qualifying time (outside window)",

    # Field / ranking types
    "top_of_field_top_3": "Top-3 finish",
    "top_of_field_top_5": "Top-5 finish",
    "top_of_field_top_10": "Top-10 finish",
    "final_appearance": "Final appearance",
    "standout_field": "Standout swim",

    # Relay
    "relay_pb": "Relay PB",
    "relay_win": "Relay win",

    # Generic
    "notable_swim": "Notable swim",
    "story": "Story swim",
}

# Post angles / card types
_POST_ANGLE_LABELS: dict[str, str] = {
    "confirmed_official_pb": "Confirmed Official PB",
    "pb_confirmed": "Confirmed PB",
    "pb_likely": "Likely PB",
    "pb_magnitude_huge": "Huge PB",
    "medal_gold": "Gold medal",
    "medal_silver": "Silver medal",
    "medal_bronze": "Bronze medal",
    "first_sub_barrier": "Barrier break",
    "multi_pb_weekend": "Multi-PB weekend",
    "biggest_drop_of_meet": "Biggest drop",
    "return_to_form": "Return to form",
    "qualifying_time": "Qualifying time",
    "qual_hit_in_window": "Qualifier",
    "top_of_field_top_3": "Top-3 finish",
    "top_of_field_top_5": "Top-5 finish",
    "relay_win": "Relay win",
    "relay_medal_gold": "Relay gold",
    "heat_to_final_drop": "Heat-to-final improvement",
    "fastest_since_date": "Season best",
    "main_feed": "Social post",
    "story": "Story post",
    "carousel": "Carousel",
    "thread": "Thread",
    "reel_script": "Video script",
    "athlete_spotlight": "Athlete spotlight",
    "session_update": "Session update",
    "event_preview": "Event preview",
    "weekend_preview": "Event preview",  # legacy slug (pre-ADR-0013)
}

# Status / verification codes
_STATUS_LABELS: dict[str, str] = {
    "pb_confirmed": "Confirmed PB",
    "pb_unverified": "PB not verified",
    "pb_likely": "Likely PB",
    "needs_verification": "Needs check",
    "asa_id_verified": "Verified",
    "asa_id_unverified": "Not verified",
    "verified": "Verified",
    "unverified": "Not verified",
    "flagged": "Flagged for review",
    "safe_to_post": "Safe to post",
    "caution": "Post with caution",
    "do_not_post": "Do not post",
    "completed": "Completed",
    "dq": "Disqualified",
    "dns": "Did not start",
    "dnf": "Did not finish",
    "scratch": "Scratched",
    "exhibition": "Exhibition",
}

# Content type labels (canonical post-type slugs first, legacy pre-ADR-0013
# slugs kept so old persisted data still gets a human label)
_CONTENT_TYPE_LABELS: dict[str, str] = {
    "meet_recap": "Meet recap",
    "athlete_spotlight": "Athlete spotlight",
    "event_preview": "Event preview",
    "sponsor_activation": "Sponsor post",
    "weekend_preview": "Event preview",
    "sponsor_post": "Sponsor post",
    "session_update": "Session update",
    "weekly_roundup": "Weekly roundup",
    "milestone_celebration": "Milestone",
    "main_feed": "Main feed post",
    "story": "Story",
    "carousel": "Carousel",
    "thread": "Thread",
    "reel_script": "Video script",
}

# Package / module name patterns to hide
_HIDDEN_PACKAGE_NAMES: set[str] = {
    "swim_content_v4",
    "swim_content_v5",
    "engine_v4",
    "recognition_swim",
    "swim_content",
    "club_platform",
    "swim_content_v3",
}


def humanise(raw: str, fallback: Optional[str] = None) -> str:
    """
    Convert a raw internal identifier to a friendly label.

    Checks achievement labels, post angle labels, status labels, and
    content type labels. Returns the raw string (title-cased) if not found,
    unless fallback is provided.
    """
    if not raw:
        return fallback or "—"
    # Direct lookup in all maps
    for mapping in [_ACHIEVEMENT_LABELS, _POST_ANGLE_LABELS, _STATUS_LABELS, _CONTENT_TYPE_LABELS]:
        if raw in mapping:
            return mapping[raw]
    # Fallback: convert snake_case to Title Case
    return fallback or raw.replace("_", " ").title()


def format_post_angle(angle: str) -> str:
    """Format a post_angle / achievement type as a friendly label."""
    return _POST_ANGLE_LABELS.get(angle, humanise(angle))


def format_achievement_type(atype: str) -> str:
    """Format an achievement type as a friendly label."""
    return _ACHIEVEMENT_LABELS.get(atype, humanise(atype))


def humanise_status(status: str) -> str:
    """Format a status/verification code as a friendly label."""
    return _STATUS_LABELS.get(status, humanise(status))


def humanise_content_type(ctype: str) -> str:
    """Format a content_type identifier as a friendly label."""
    return _CONTENT_TYPE_LABELS.get(ctype, humanise(ctype))


def is_internal_identifier(text: str) -> bool:
    """Return True if text looks like an internal package/module name."""
    return any(pkg in text for pkg in _HIDDEN_PACKAGE_NAMES)


def clean_for_display(text: str) -> str:
    """
    Remove or replace internal identifiers in a string.
    Use for user-visible text only.
    """
    for pkg in _HIDDEN_PACKAGE_NAMES:
        text = text.replace(pkg, "")
    return text.strip(" .:")
