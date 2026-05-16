"""Turn MediaHub's structured data into natural English prose for Claude.

The principle is: Claude reasons better about prose than about JSON
blobs. So instead of shipping ``{"swimmer_first": "Hannah", "event":
"100 Free", "time": "1:02.34", "pb": true}`` and asking Claude to
"please parse this and write a caption", we narrate it once into prose
("Hannah just swam 100m Freestyle in 1:02.34 — a personal best") and
pass that as the user message. Same data, much cleaner reasoning.

These helpers are intentionally short and additive. They drop fields
that are empty so the prose stays readable, and they pick natural
English connectives instead of comma-spliced facts.
"""
from __future__ import annotations

from typing import Optional


_PB_PHRASES = {
    "official_pb_confirmed": "an officially-confirmed personal best",
    "pb_confirmed":          "a confirmed personal best",
    "pb_likely":             "a likely personal best",
    "pb_magnitude_huge":     "a huge personal-best improvement",
    "pb_magnitude_big":      "a big personal-best improvement",
    "pb_magnitude_notable":  "a notable personal-best improvement",
    "first_sub_barrier":     "a first-time sub-barrier swim",
}

_MEDAL_PHRASES = {
    "medal_gold":          "a gold medal",
    "medal_silver":        "a silver medal",
    "medal_bronze":        "a bronze medal",
    "relay_medal_gold":    "a gold-medal relay performance",
    "relay_medal_silver":  "a silver-medal relay performance",
    "relay_medal_bronze":  "a bronze-medal relay performance",
}


def _achievement_kind(a: dict) -> str:
    """Pick a human noun phrase for the achievement type, or empty."""
    t = (a.get("type") or "").strip()
    if t in _PB_PHRASES:
        return _PB_PHRASES[t]
    if t in _MEDAL_PHRASES:
        return _MEDAL_PHRASES[t]
    if t.startswith("top_of_field_top_"):
        n = t.rsplit("_", 1)[-1]
        return f"a top-{n} finish" if n.isdigit() else "a top-of-field finish"
    if t.startswith("qual_hit"):
        return "a qualifying-time hit"
    return ""


def narrate_achievement(a: dict, *, meet: Optional[dict] = None) -> str:
    """Build a single-paragraph English description of a single achievement."""
    if not a:
        return ""
    swimmer = (a.get("swimmer_name") or "").strip()
    event = (a.get("event") or "").strip()
    time = (a.get("time") or "").strip()
    place = a.get("place")
    course = (a.get("course") or "").strip()
    age_group = (a.get("age_group") or "").strip()
    club = (a.get("club") or "").strip()
    venue = (a.get("venue") or "").strip()
    pb_delta = a.get("pb_delta_seconds")
    recorded_pb = (a.get("recorded_pb") or "").strip()
    is_pb = bool(a.get("pb") or a.get("is_pb"))
    headline = (a.get("headline") or "").strip()
    kind = _achievement_kind(a)

    parts: list[str] = []
    subject = swimmer or "the swimmer"
    when_where = ""
    if meet:
        mname = (meet.get("name") or "").strip()
        mvenue = (meet.get("venue") or "").strip()
        mlevel = (meet.get("level") or "").strip()
        if mname and mvenue:
            when_where = f" at the {mname} ({mvenue})"
        elif mname:
            when_where = f" at the {mname}"
        elif mvenue:
            when_where = f" at {mvenue}"
        if mlevel:
            when_where += f" — a {mlevel}-level meet"
    elif venue:
        when_where = f" at {venue}"

    # Lead sentence.
    if event and time:
        if course:
            parts.append(f"{subject} swam {event} ({course}) in {time}{when_where}.")
        else:
            parts.append(f"{subject} swam {event} in {time}{when_where}.")
    elif event:
        parts.append(f"{subject} raced {event}{when_where}.")
    elif time:
        parts.append(f"{subject} clocked {time}{when_where}.")

    # Placement.
    if place:
        try:
            p = int(place)
            ord_suffix = {1: "st", 2: "nd", 3: "rd"}.get(p, "th")
            parts.append(f"They finished {p}{ord_suffix}.")
        except (TypeError, ValueError):
            parts.append(f"They finished {place}.")

    # PB context.
    if is_pb and isinstance(pb_delta, (int, float)) and pb_delta > 0:
        parts.append(f"It's a personal best by {pb_delta:.2f} seconds.")
    elif is_pb:
        parts.append("It's a personal best.")
    elif recorded_pb:
        parts.append(f"Their recorded PB for this event is {recorded_pb}.")

    if kind:
        parts.append(f"The recognition engine tagged this as {kind}.")

    if age_group:
        parts.append(f"Age group: {age_group}.")
    if club and not swimmer:
        parts.append(f"Club: {club}.")

    if headline and headline not in " ".join(parts):
        parts.append(f"Headline summary: {headline}.")

    return " ".join(parts).strip()


def narrate_brand(brand: Optional[dict]) -> str:
    """Brief English description of a club's brand voice, for prompts."""
    if not brand:
        return ""
    name = (brand.get("name") or brand.get("display_name") or "").strip()
    short = (brand.get("short_name") or "").strip()
    tone = (brand.get("tone") or "").strip()
    notes = (brand.get("tone_notes") or "").strip()
    sponsor = (brand.get("sponsor_name") or "").strip()
    sponsor_rules = (brand.get("sponsor_guidelines")
                     or brand.get("sponsor_rules") or "").strip()
    exemplars = brand.get("exemplars") or brand.get("exemplar_captions") or []

    bits: list[str] = []
    if name:
        bits.append(f"You're writing for {name}" + (f" ({short})." if short else "."))
    if tone:
        bits.append(f"Their preferred voice is {tone}.")
    if notes:
        bits.append(f"Voice notes: {notes}")
    if exemplars:
        sample = " || ".join(str(e).strip() for e in list(exemplars)[:3] if str(e).strip())
        if sample:
            bits.append(f"Example past captions for style reference: {sample}")
    if sponsor:
        bits.append(f"Sponsor: {sponsor}.")
    if sponsor_rules:
        bits.append(f"Sponsor guidelines: {sponsor_rules}")
    return " ".join(bits).strip()


def narrate_meet(meet: Optional[dict]) -> str:
    """Brief English description of the meet context for prompts."""
    if not meet:
        return ""
    name = (meet.get("name") or "").strip()
    venue = (meet.get("venue") or "").strip()
    course = (meet.get("course") or "").strip()
    level = (meet.get("level") or "").strip()
    gov = (meet.get("governing_body") or "").strip()
    start = (meet.get("start_date") or "").strip()
    end = (meet.get("end_date") or "").strip()
    bits: list[str] = []
    if name:
        bits.append(f"Meet: {name}.")
    if level:
        bits.append(f"Meet level: {level}.")
    if gov:
        bits.append(f"Governing body: {gov}.")
    if venue:
        bits.append(f"Held at {venue}.")
    if start and end and start != end:
        bits.append(f"Dates: {start} to {end}.")
    elif start:
        bits.append(f"Date: {start}.")
    if course:
        bits.append(f"Course: {course}.")
    return " ".join(bits).strip()
