"""
CaptionTemplate dataclass and render_template helper.

A CaptionTemplate holds a string with {placeholder} variables.
Three slots per (content_type × tone): headline, body, cta.

Supported placeholders:
  {swimmer}         full name e.g. "Mathew Bradley"
  {swimmer_short}   first name only e.g. "Mathew"
  {event}           e.g. "100m Butterfly (LC)"
  {course}          "LC" | "SC"
  {time}            formatted time e.g. "57.95"
  {prev_pb}         previous personal best e.g. "59.35"
  {drop_seconds}    absolute drop e.g. "1.40"
  {drop_pretty}     formatted drop e.g. "−1.40s"
  {place}           integer place e.g. "1"
  {medal}           "gold" | "silver" | "bronze" | ""
  {meet}            meet name
  {club}            club short name
  {type}            achievement type slug

Missing keys are replaced with "—" rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass
class CaptionTemplate:
    slot: str  # 'headline' | 'body' | 'cta'
    template: str

    def render(self, ctx: dict) -> str:
        return render_template(self.template, ctx)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CaptionTemplate":
        return cls(slot=d.get("slot", ""), template=d.get("template", ""))


def render_template(template_str: str, ctx: dict) -> str:
    """
    Fill {placeholder} variables from ctx.  Missing keys → "—".
    Never raises on missing keys.
    """

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return str(ctx.get(key, "—"))

    return re.sub(r"\{(\w+)\}", _replace, template_str)


# ---------------------------------------------------------------------------
# Default templates (seeded for meet_recap × all three tones)
# ---------------------------------------------------------------------------


def _default_context_example() -> dict:
    """Return a minimal example context for template preview."""
    return {
        "swimmer": "Mathew Bradley",
        "swimmer_short": "Mathew",
        "event": "100m Butterfly (LC)",
        "course": "LC",
        "time": "57.95",
        "prev_pb": "59.35",
        "drop_seconds": "1.40",
        "drop_pretty": "−1.40s",
        "place": "1",
        "medal": "gold",
        "meet": "Spring Open Meet",
        "club": "Your Club",
        "type": "pb_confirmed",
    }


DEFAULTS: dict[str, dict[str, dict[str, str]]] = {
    # Keyed by content_type → tone → slot → template string
    "meet_recap": {
        "warm-club": {
            "headline": "{swimmer_short} goes {time} in the {event} — a new PB!",
            "body": "{swimmer_short} dropped {drop_pretty} in the {event} at {meet}. Previous best was {prev_pb}. Great swim!",
            "cta": "Huge swim from {swimmer_short} this weekend 🏊",
        },
        "hype": {
            "headline": "{swimmer} GOES {time} IN THE {event} — NEW PB!",
            "body": "{swimmer} smashes a {drop_pretty} PB in the {event}. Previous best: {prev_pb}. {meet}.",
            "cta": "WHAT A WEEKEND. {swimmer} — {drop_pretty} personal best. 🔥",
        },
        "data-led": {
            "headline": "{swimmer}: {event} — {time} (PB, {drop_pretty})",
            "body": "{swimmer} recorded {time} in the {event} at {meet}. Previous personal best: {prev_pb} ({drop_pretty} improvement).",
            "cta": "{swimmer} | {event} | {time} (PB) | {meet}",
        },
    },
    "athlete_spotlight": {
        "warm-club": {
            "headline": "Spotlight: {swimmer_short}'s weekend at {meet}",
            "body": "{swimmer_short} had a standout meet at {meet} with multiple achievements. Check out the full breakdown below.",
            "cta": "What a meet for {swimmer_short}! Full results inside.",
        },
        "hype": {
            "headline": "{swimmer} DOMINATES AT {meet}!",
            "body": "{swimmer} put in a series of huge performances at {meet}. Here's everything they achieved.",
            "cta": "Unstoppable. {swimmer}. {meet}. 💥",
        },
        "data-led": {
            "headline": "Athlete Spotlight: {swimmer} | {meet}",
            "body": "Performance summary for {swimmer} at {meet}. All achievements ranked by impact.",
            "cta": "{swimmer} | {meet} | Performance summary",
        },
    },
}


def get_default_templates(content_type: str, tone: str) -> dict[str, str]:
    """Return {slot: template_str} for the given content_type and tone."""
    ct = DEFAULTS.get(content_type, DEFAULTS.get("meet_recap", {}))
    return dict(ct.get(tone, ct.get("warm-club", {})))
