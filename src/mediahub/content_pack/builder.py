"""
content_pack/builder.py — Grouped content pack builder.

build_grouped_pack(run_data, profile_id) -> dict with 8 buckets:
  main_feed, stories, athlete_spotlights, weekend_recap,
  weekend_in_numbers, internal_notes, needs_review, rejected
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

from mediahub.recognition.copy_text import build_caption_text
from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers


# Mapping from achievement type to PostAngle string
_TYPE_TO_ANGLE = {
    "official_pb_confirmed": "confirmed_official_pb",
    "pb_confirmed": "pb_improvement",
    "pb_magnitude_huge": "pb_improvement",
    "pb_magnitude_big": "pb_improvement",
    "pb_magnitude_notable": "pb_improvement",
    "pb_likely": "likely_pb",
    "first_sub_barrier": "first_sub_barrier",
    "medal_gold": "medal_gold",
    "medal_silver": "medal_silver",
    "medal_bronze": "medal_bronze",
    "final_appearance": "finalist",
    "heat_to_final_drop": "heat_to_final_drop",
    "top_of_field_top_3": "top_of_field",
    "top_of_field_top_5": "top_of_field",
    "top_of_field_top_10": "top_of_field",
    "qual_hit_in_window": "qualifying_time",
    "qual_hit_out_of_window": "qualifying_time",
    "biggest_drop_of_meet": "biggest_drop",
    "biggest_drop_candidate": "biggest_drop",
    "fastest_since": "fastest_since",
    "multi_pb_weekend": "multi_pb_weekend",
    "return_to_form": "return_to_form",
    "relay_medal_gold": "relay_highlight",
    "relay_medal_silver": "relay_highlight",
    "relay_medal_bronze": "relay_highlight",
    "relay_strong": "relay_highlight",
}

# Recommender override map: when a swimmer has medal + official_pb, override angle
_OVERRIDE_RULES = [
    ({"medal_gold", "official_pb_confirmed"}, "medal_and_pb_combo"),
    ({"medal_gold", "pb_confirmed"}, "medal_and_pb_combo"),
    ({"medal_silver", "official_pb_confirmed"}, "medal_and_pb_combo"),
    ({"medal_silver", "pb_confirmed"}, "medal_and_pb_combo"),
]


def _enrich_item(ra: dict, wf_states: dict = None) -> dict:
    """Add copy text variants and post_angle to a RankedAchievement dict."""
    item = dict(ra)
    a = item.get("achievement", {}) or {}

    # Determine post angle
    atype = a.get("type", "")
    post_angle = item.get("post_angle") or a.get("post_angle") or _TYPE_TO_ANGLE.get(atype, "recap_mention")
    item["post_angle"] = post_angle

    # Ensure safe_to_post exists
    if not item.get("safe_to_post"):
        conf = a.get("confidence", 0.5)
        if isinstance(conf, (int, float)):
            if conf >= 0.7:
                item["safe_to_post"] = {"level": "safe", "reason": "High confidence evidence."}
            elif conf >= 0.4:
                item["safe_to_post"] = {"level": "needs_review", "reason": "Medium confidence — verify before posting."}
            else:
                item["safe_to_post"] = {"level": "do_not_post", "reason": "Low confidence evidence."}
        else:
            item["safe_to_post"] = {"level": "needs_review", "reason": "Confidence unknown."}

    # Build copy text variants
    item["caption_only"] = build_caption_text(a or item, mode="caption_only")
    item["caption_with_hashtags"] = build_caption_text(a or item, mode="with_hashtags")
    item["caption_full_brief"] = build_caption_text(a or item, mode="full_brief")

    # Workflow state
    if wf_states:
        card_id = a.get("swim_id", "")
        wf = wf_states.get(card_id)
        if wf:
            wf_status = wf.status.value if hasattr(wf, "status") else str(wf)
            item["wf_status"] = wf_status
            sched = getattr(wf, "schedule_status", None)
            item["schedule_status"] = sched.value if sched is not None and hasattr(sched, "value") else "queued"
            item["buffer_update_id"] = getattr(wf, "buffer_update_id", None)
        else:
            item["wf_status"] = "queue"
            item["schedule_status"] = "queued"
    else:
        item["wf_status"] = item.get("wf_status", "queue")
        item["schedule_status"] = item.get("schedule_status", "queued")

    return item


def build_grouped_pack(
    run_data: dict,
    profile_id: str = "",
    runs_dir: Optional[Path] = None,
) -> dict:
    """
    Build a grouped content pack from run data.

    Returns:
    {
      "main_feed": [item, ...],        # ELITE + safe
      "stories": [...],               # STRONG + safe
      "athlete_spotlights": [...],    # swimmers with >=3 achievements
      "weekend_recap": item | None,   # single meet summary card
      "weekend_in_numbers": item | None,  # auto-generated stats card
      "internal_notes": [...],        # NICE band
      "needs_review": [...],          # safe_to_post.level == needs_review
      "rejected": [...],              # NOT_WORTHY or workflow REJECTED
    }

    Workflow state (status + schedule_status + buffer_update_id) is read
    from the sidecar JSON in ``runs_dir`` so the pill the pack template
    paints on reload reflects what the schedule endpoint actually wrote.
    ``runs_dir`` falls back to the web layer's RUNS_DIR (DATA_DIR-derived)
    so single-tenant deployments and test fixtures with a custom DATA_DIR
    both resolve to the right sidecar location.
    """
    # Load workflow states if available. WorkflowStore requires runs_dir;
    # honour an explicit override, otherwise resolve it the same way the
    # rest of the web layer does (DATA_DIR-derived) so a sidecar written
    # by the schedule endpoint is found by this reload path.
    wf_states = {}
    try:
        from mediahub.workflow.store import WorkflowStore
        if runs_dir is None:
            try:
                from mediahub.web.web import RUNS_DIR as _RUNS_DIR
                resolved_runs_dir = Path(_RUNS_DIR)
            except Exception:
                resolved_runs_dir = Path(__file__).resolve().parents[2] / "runs_v4"
        else:
            resolved_runs_dir = Path(runs_dir)
        ws = WorkflowStore(resolved_runs_dir)
        run_id = run_data.get("run_id", "")
        if run_id:
            wf_states = ws.load(run_id)
    except Exception:
        pass

    # Get recognition report for ranked achievements
    rr = run_data.get("recognition_report") or {}
    ranked_achs = rr.get("ranked_achievements") or []

    # Get V4 cards
    cards = run_data.get("cards") or []

    # Build swimmer -> achievement list map for spotlights
    swimmer_achievements: dict[str, list[dict]] = defaultdict(list)

    main_feed: list[dict] = []
    stories: list[dict] = []
    internal_notes: list[dict] = []
    needs_review: list[dict] = []
    rejected: list[dict] = []
    weekend_recap_item = None

    for ra in ranked_achs:
        a = ra.get("achievement", {}) or {}
        band = ra.get("quality_band", "nice")
        swimmer_id = a.get("swimmer_id", "")

        item = _enrich_item(ra, wf_states)
        s2p = item.get("safe_to_post", {})
        s2p_level = s2p.get("level", "needs_review") if isinstance(s2p, dict) else "needs_review"
        wf_status = item.get("wf_status", "queue")

        # Rejected bucket: workflow rejected OR not_worthy band
        if wf_status == "rejected" or band == "not_worthy":
            rejected.append(item)
            continue

        # Route by band and safety
        if band == "elite" and s2p_level == "safe":
            main_feed.append(item)
        elif band == "strong" and s2p_level == "safe":
            stories.append(item)
        elif band in ("elite", "strong") and s2p_level == "needs_review":
            needs_review.append(item)
        elif band in ("elite", "strong") and s2p_level == "do_not_post":
            needs_review.append(item)
        elif band in ("story",) and s2p_level == "safe":
            stories.append(item)
        elif band == "nice":
            internal_notes.append(item)
        else:
            needs_review.append(item)

        # Track per-swimmer for spotlights
        if swimmer_id:
            swimmer_achievements[swimmer_id].append(item)

    # Athlete spotlights: swimmers with >= 3 achievements
    athlete_spotlights: list[dict] = []
    for swimmer_id, items in swimmer_achievements.items():
        if len(items) >= 3:
            # Apply recommender override for angle
            types_in_set = {i.get("achievement", {}).get("type", "") for i in items}
            override_angle = None
            for needed_types, angle in _OVERRIDE_RULES:
                if needed_types.issubset(types_in_set):
                    override_angle = angle
                    break

            swimmer_name = items[0].get("achievement", {}).get("swimmer_name", swimmer_id)
            spotlight = {
                "card_type": "athlete_spotlight",
                "swimmer_id": swimmer_id,
                "swimmer_name": swimmer_name,
                "n_achievements": len(items),
                "achievements": sorted(items, key=lambda x: -x.get("priority", 0)),
                "post_angle": override_angle or "athlete_spotlight",
                "safe_to_post": {"level": "safe", "reason": "Multiple verified achievements for this athlete."},
                "suggested_post_type": "main_feed",
                "quality_band": "elite",
            }
            athlete_spotlights.append(spotlight)

    athlete_spotlights.sort(key=lambda x: -x["n_achievements"])

    # Weekend recap: find from cards or recognition report
    for card in cards:
        ct = card.get("card_type", "") or ""
        if "recap" in ct.lower() or "summary" in ct.lower():
            weekend_recap_item = _enrich_item({
                "achievement": card,
                "quality_band": "strong",
                "priority": 0.7,
                "post_angle": "recap_mention",
            }, wf_states)
            break

    # Weekend-in-numbers card
    win_card = None
    if rr:
        win_card = build_weekend_in_numbers(rr)

    return {
        "main_feed": main_feed,
        "stories": stories,
        "athlete_spotlights": athlete_spotlights,
        "weekend_recap": weekend_recap_item,
        "weekend_in_numbers": win_card,
        "internal_notes": internal_notes,
        "needs_review": needs_review,
        "rejected": rejected,
        # Summary counts
        "_counts": {
            "main_feed": len(main_feed),
            "stories": len(stories),
            "athlete_spotlights": len(athlete_spotlights),
            "weekend_recap": 1 if weekend_recap_item else 0,
            "weekend_in_numbers": 1 if win_card else 0,
            "internal_notes": len(internal_notes),
            "needs_review": len(needs_review),
            "rejected": len(rejected),
        },
    }


__all__ = ["build_grouped_pack"]
