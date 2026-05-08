"""
Content generator.

Takes Achievement objects + a club brand voice profile and produces caption
variants. The prototype uses templated, voice-conditioned generation — no
LLM call is required for the demo. The interface is shaped so that an LLM
adapter can drop in later (one function, takes the same inputs).
"""

from __future__ import annotations
import json
import random
from typing import Iterable

from .events import event_human, cs_to_str


# ------------------------------------------------------------------
# Voice profiles. In production these would be learned from past posts.
# ------------------------------------------------------------------

DEFAULT_VOICE = {
    "club_short": "the team",
    "exclaim": False,
    "hashtags": ["#swim", "#performance"],
    "tone": "warm-direct",
}

SWANSEA_VOICE = {
    "club_short": "Swansea Uni Swimming",
    "exclaim": True,
    "hashtags": ["#SwanseaUniSwim", "#WeAreSwansea", "#PoolPerformance"],
    "tone": "warm-direct",
}


# ------------------------------------------------------------------
# Templates by achievement type
# ------------------------------------------------------------------
# Each template returns (caption_text, alt_text). We provide 3 variants per
# achievement type so the user has real choice in the approval UI.
# ------------------------------------------------------------------

def _excl(voice):
    return "!" if voice.get("exclaim") else "."


def _hashtags(voice, extra=()):
    tags = list(voice.get("hashtags", [])) + list(extra)
    return " ".join(tags)


def _captions_for(ach: dict, voice: dict) -> list[str]:
    t = ach["type"]
    name = ach["swimmer_name"]
    ev = event_human(ach["event_code"]) if ach["event_code"] != "-" else ""
    e = ach.get("evidence", {}) or {}
    ex = ach["explanation"]
    excl = _excl(voice)

    if t in ("CONFIRMED_PB", "LIKELY_PB"):
        margin = e.get("margin_cs")
        margin_str = cs_to_str(abs(margin)) if margin else None
        time_str = cs_to_str(e.get("time_cs", 0))
        v1 = f"{name} drops a new personal best in the {ev} — {time_str}{excl}"
        if margin_str:
            v1 += f" That's {margin_str} faster than before."
        v2 = (f"PB alert{excl} {name} stops the clock at {time_str} in the {ev}"
              + (f", taking {margin_str} off." if margin_str else "."))
        v3 = f"New best for {name}: {time_str} in the {ev}. Belief, work, result."
        return [v1, v2, v3]

    if t.startswith("MEDAL_"):
        place = e.get("place")
        medal = {1: "gold", 2: "silver", 3: "bronze"}.get(place, "medal")
        v1 = f"{medal.title()} for {name} in the {ev}{excl} {cs_to_str(e.get('time_cs',0))}"
        v2 = (f"{name} on the podium — {medal} in the {ev} ({cs_to_str(e.get('time_cs',0))}){excl}")
        v3 = f"Top three finish for {name} in the {ev}. {medal.title()} secured."
        return [v1, v2, v3]

    if t == "RECORD_BROKEN":
        v1 = (f"CLUB RECORD{excl} {name} sets a new club record in the {ev} — "
              f"{cs_to_str(e.get('new_time_cs',0))}, beating the previous {cs_to_str(e.get('old_record_cs',0))}.")
        v2 = (f"Rewriting the record book — {name} swims {cs_to_str(e.get('new_time_cs',0))} "
              f"in the {ev}, a new {voice.get('club_short','club')} record.")
        v3 = (f"{name} → new club record in the {ev}{excl} "
              f"{cs_to_str(e.get('new_time_cs',0))}.")
        return [v1, v2, v3]

    if t == "QT_HIT":
        v1 = (f"{name} dips under the {e.get('standard','qualifying')} time in the {ev} — "
              f"{cs_to_str(e.get('time_cs',0))}{excl}")
        v2 = (f"Qualified{excl} {name} hits the {e.get('standard','qualifying')} standard "
              f"in the {ev}.")
        v3 = (f"Big swim from {name}: {cs_to_str(e.get('time_cs',0))} in the {ev} — "
              f"under the {e.get('standard','qualifying')} standard.")
        return [v1, v2, v3]

    if t == "BARRIER_BREAK":
        b = cs_to_str(e.get("barrier_cs", 0))
        v1 = f"{name} goes under {b} for the first time in the {ev}{excl}"
        v2 = f"Through the barrier — {name} swims {cs_to_str(e.get('time_cs',0))} in the {ev}, first time under {b}."
        v3 = f"Sub-{b} for {name} in the {ev}. New territory."
        return [v1, v2, v3]

    if t == "BIGGEST_IMPROVEMENT":
        margin = cs_to_str(e.get("margin_cs", 0))
        rank = e.get("rank", 1)
        ord_ = {1: "biggest", 2: "second-biggest", 3: "third-biggest"}.get(rank, "big")
        v1 = f"{ord_.title()} drop of the meet — {name} takes {margin} off in the {ev}."
        v2 = f"Massive improvement from {name}: {margin} faster in the {ev}{excl}"
        v3 = f"Work meets the wall — {name} cuts {margin} in the {ev}."
        return [v1, v2, v3]

    if t == "TEAM_STAT":
        v1 = f"{e.get('pb_count',0)} personal bests across the weekend{excl} Proud of this group."
        v2 = f"By the numbers: {e.get('pb_count',0)} new PBs from {voice.get('club_short','the team')} this meet."
        v3 = f"{e.get('pb_count',0)} swimmers found new personal bests this weekend. Onwards."
        return [v1, v2, v3]

    if t == "FINAL_QUALIFICATION":
        v1 = f"{name} into the final of the {ev}{excl}"
        v2 = f"Final-bound — {name} qualifies for the {ev} final."
        v3 = f"{name} books a final spot in the {ev}."
        return [v1, v2, v3]

    # Fallback
    return [ex, f"Worth celebrating: {ex}", ex]


def captions_for_achievement(ach: dict, voice: dict | None = None) -> dict:
    """Return {variants: [str,str,str], hashtags: str, why: str}."""
    voice = voice or DEFAULT_VOICE
    variants = _captions_for(ach, voice)
    hashtags = _hashtags(voice)
    full = [f"{v}\n\n{hashtags}".strip() for v in variants]
    return {
        "variants": full,
        "why": ach["explanation"],
    }


def weekend_in_numbers(meet_name: str, achievements: list[dict], voice: dict) -> dict:
    pb_count = sum(1 for a in achievements if a["type"] in ("CONFIRMED_PB", "LIKELY_PB"))
    medals = sum(1 for a in achievements if a["type"].startswith("MEDAL_"))
    records = sum(1 for a in achievements if a["type"] == "RECORD_BROKEN")
    qts = sum(1 for a in achievements if a["type"] == "QT_HIT")
    barriers = sum(1 for a in achievements if a["type"] == "BARRIER_BREAK")

    lines = [f"{meet_name} — by the numbers"]
    if pb_count: lines.append(f"• {pb_count} personal bests")
    if medals: lines.append(f"• {medals} medals")
    if records: lines.append(f"• {records} club records")
    if qts: lines.append(f"• {qts} qualifying-time hits")
    if barriers: lines.append(f"• {barriers} barriers broken")
    body = "\n".join(lines) + f"\n\n{_hashtags(voice)}"
    return {"variants": [body], "why": "Aggregate of meet achievements."}
