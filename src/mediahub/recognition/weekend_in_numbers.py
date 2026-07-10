"""
recognition/weekend_in_numbers.py — Auto-generate a "weekend by the numbers" card.

build_weekend_in_numbers(report_dict) -> dict (card-compatible)
"""

from __future__ import annotations


def build_weekend_in_numbers(report: dict) -> dict:
    """
    Generate a single 'meet by the numbers' card from the recognition report dict.

    Includes:
      - n_swimmers, n_swims, n_pbs, n_medals, n_finals
      - top_of_field count
      - biggest drop (swimmer + amount)
      - most PBs by swimmer
      - relay highlights (count + best placement)
    """
    meet_name = report.get("meet_name", "Meet")
    ranked = report.get("ranked_achievements", [])

    # Counts by achievement type
    n_pbs = 0
    n_medals = 0
    n_gold = 0
    n_finals = 0
    n_top_field = 0
    n_relay_medals = 0
    biggest_drop_swimmer = ""
    biggest_drop_event = ""
    biggest_drop_seconds = 0.0
    biggest_drop_pct = 0.0

    # PBs per swimmer
    pb_by_swimmer: dict[str, int] = {}

    for ra in ranked:
        a = ra.get("achievement", {}) if isinstance(ra, dict) else {}
        atype = a.get("type", "")
        swimmer = a.get("swimmer_name", "")
        raw = a.get("raw_facts", {})

        if "pb_confirmed" in atype or "pb_magnitude" in atype or "official_pb" in atype:
            n_pbs += 1
            pb_by_swimmer[swimmer] = pb_by_swimmer.get(swimmer, 0) + 1

        if "medal_gold" == atype:
            n_gold += 1
            n_medals += 1
        elif "medal_silver" == atype or "medal_bronze" == atype:
            n_medals += 1

        if "relay_medal" in atype:
            n_relay_medals += 1

        if "final_appearance" in atype or "heat_to_final" in atype:
            n_finals += 1

        if "top_of_field" in atype:
            n_top_field += 1

        if atype == "biggest_drop_of_meet":
            biggest_drop_swimmer = swimmer
            biggest_drop_event = a.get("event", "")
            biggest_drop_seconds = abs(raw.get("drop_seconds", 0.0))
            biggest_drop_pct = raw.get("drop_pct", 0.0)

    # Most PBs by a single swimmer
    most_pbs_swimmer = ""
    most_pbs_count = 0
    if pb_by_swimmer:
        most_pbs_swimmer = max(pb_by_swimmer, key=lambda k: pb_by_swimmer[k])
        most_pbs_count = pb_by_swimmer[most_pbs_swimmer]

    # Build headline text
    n_swims = report.get("n_swims_analysed", 0)
    # Count the swimmers who COMPETED — distinct across every analysed swim, not
    # just those who earned a ranked achievement. Pairing swimmers-with-a-medal
    # against the all-swims total published an internally inconsistent undercount
    # on the recap graphic (e.g. "17 swimmers · 253 swims" when 33 competed).
    # Prefer the swim traces (one per analysed swim of our club); fall back to the
    # ranked-achievement distinct count only when the report carries no traces.
    swim_traces = report.get("swim_traces") or []
    n_swimmers = len(
        {
            (s.get("swimmer_name") or "").strip()
            for s in swim_traces
            if isinstance(s, dict) and (s.get("swimmer_name") or "").strip()
        }
    )
    if not n_swimmers:
        n_swimmers = len(
            {
                (ra.get("achievement", {}) if isinstance(ra, dict) else {}).get("swimmer_id", "")
                for ra in ranked
                if (ra.get("achievement", {}) if isinstance(ra, dict) else {}).get("swimmer_id")
            }
        )

    lines = []
    lines.append(f"{meet_name} — by the numbers")
    lines.append("")
    lines.append(
        f"{n_swimmers} swimmer{'s' if n_swimmers != 1 else ''} · {n_swims} swim{'s' if n_swims != 1 else ''}"
    )
    if n_pbs or n_medals:
        medal_str = f"{n_medals} medal{'s' if n_medals != 1 else ''}" if n_medals else ""
        pb_str = f"{n_pbs} PB{'s' if n_pbs != 1 else ''}" if n_pbs else ""
        combined = " · ".join(p for p in [pb_str, medal_str] if p)
        if combined:
            lines.append(combined)
    if n_finals:
        lines.append(f"{n_finals} final appearance{'s' if n_finals != 1 else ''}")
    if n_top_field:
        lines.append(f"{n_top_field} top-of-field performance{'s' if n_top_field != 1 else ''}")

    if most_pbs_swimmer and most_pbs_count >= 2:
        lines.append("")
        lines.append(f"Most PBs: {most_pbs_swimmer} ({most_pbs_count})")

    if biggest_drop_swimmer:
        sign_str = f"−{biggest_drop_seconds:.2f}s"
        lines.append(f"Biggest drop: {biggest_drop_swimmer}, {biggest_drop_event}, {sign_str}")

    if n_relay_medals:
        lines.append(f"Relay medals: {n_relay_medals}")

    caption_text = "\n".join(lines)

    # Stats grid for rendering
    stats = [
        {"label": "Swimmers", "value": str(n_swimmers)},
        {"label": "Swims", "value": str(n_swims)},
        {"label": "PBs", "value": str(n_pbs)},
        {"label": "Medals", "value": str(n_medals)},
        {"label": "Finals", "value": str(n_finals)},
    ]
    if n_top_field:
        stats.append({"label": "Top of field", "value": str(n_top_field)})
    if n_relay_medals:
        stats.append({"label": "Relay medals", "value": str(n_relay_medals)})

    highlights = []
    if most_pbs_swimmer and most_pbs_count >= 2:
        highlights.append(f"Most PBs: {most_pbs_swimmer} ({most_pbs_count})")
    if biggest_drop_swimmer:
        highlights.append(
            f"Biggest drop: {biggest_drop_swimmer}, {biggest_drop_event}, −{biggest_drop_seconds:.2f}s"
        )
    if n_gold:
        highlights.append(f"{n_gold} gold medal{'s' if n_gold != 1 else ''}")

    return {
        "card_type": "weekend_in_numbers",
        "post_angle": "weekend_in_numbers",
        "headline": f"{meet_name} — by the numbers",
        "subhead": caption_text,
        "stats": stats,
        "highlights": highlights,
        "caption_text": caption_text,
        "suggested_post_type": "main_feed",
        "quality_band": "strong",
        "safe_to_post": {
            "level": "safe",
            "reason": "Auto-generated aggregate stats, all facts from results file.",
        },
        "active_caption": {
            "headline": f"{meet_name} — by the numbers",
            "body": caption_text,
            "cta": "",
        },
        "swim_id": f"weekend_in_numbers:{meet_name}",
        "swimmer_name": "Team",
        "event": "Meet aggregate",
        "confidence": 0.95,
        "confidence_label": "high",
    }


__all__ = ["build_weekend_in_numbers"]
