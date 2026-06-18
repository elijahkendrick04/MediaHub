"""Natural-language planner inputs — free text → structured DIRECT signals.

This brings the Free-Text feature's two standout capabilities — LLM
interpretation of plain language, and optional web research — to the
cross-source planner's *direct input* surface (``content_engine.inputs``).

The operator describes, in their own words, what's coming up and what they
want to push ("County Champs at Ponds Forge on the 12th, we're shut the bank
holiday weekend, and I want to get behind our new sponsor"). The model returns
**structured** planner inputs:

  * ``upcoming_events`` — ``[{"name", "date" (ISO), "venue"}]``
  * ``blackout_dates``  — ``["YYYY-MM-DD", ...]``
  * ``goals``           — ``[{"post_type": <enabled slug>, "note"}]``

Boundary (CLAUDE.md): this does **not** touch the deterministic ranker. The
AI only *proposes structured inputs*; the operator reviews and saves them and
the deterministic planner consumes them exactly as if hand-typed. This is the
split ``inputs.py`` already calls out — "no free-text interpretation happens
outside the AI layer, and a goal can never be silently mis-routed by a keyword
heuristic": goals are constrained to the sport's *enabled* post types here, so
the model can target a type but never invent one.

Honest errors only — an unconfigured/failed provider raises
``ProviderNotConfigured`` / ``ProviderError``. There is no heuristic fallback
that would fabricate an event or a date.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Optional

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_EVENTS = 12
MAX_BLACKOUTS = 12
MAX_GOALS = 8


def _iso(value: object) -> Optional[str]:
    """A real ISO ``YYYY-MM-DD`` or ``None`` — mirrors ``inputs._clean_date``."""
    s = str(value or "").strip()[:10]
    if not _ISO_DATE.match(s):
        return None
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def _system_prompt(today: date, goal_choices: list[tuple[str, str]], *, research: bool) -> str:
    if goal_choices:
        lines = "\n".join(f"  - {slug} — {title}" for slug, title in goal_choices)
        goals_clause = (
            "  * goals — a thing the club wants to push, mapped to ONE target\n"
            "    post type from this enabled list (use the slug exactly, never\n"
            f"    invent one):\n{lines}\n"
        )
    else:
        goals_clause = ""
    research_clause = (
        "When a real event is named but you don't know its date or venue, use\n"
        "the `research_web` tool to look it up before answering. Don't guess\n"
        "facts about real events, venues, or dates — research or leave them out.\n\n"
        if research
        else "Don't guess facts about real events, venues or dates — if the note\n"
        "doesn't give a date for an event, leave that event out.\n\n"
    )
    return f"""\
You are MediaHub's planning assistant. Turn ONE free-text note from a sports
club or society into STRUCTURED planner inputs for its content calendar.

Today is {today.isoformat()}. Resolve every relative date ("this weekend",
"next month", "the 12th") to an absolute YYYY-MM-DD using that anchor, always
choosing the next future occurrence.

You decide what the note contains. Extract any of:
  * upcoming events the club cares about (name + date + venue if stated)
  * blackout dates — days nothing should be scheduled on (holidays, closures)
{goals_clause}
{research_clause}When you've extracted what you can, call `propose_inputs` exactly once with
the structured object. Include only what the note actually supports; empty
lists are fine. Do not fabricate events, dates, or goals to fill space.
"""


_RESEARCH_TOOL = {
    "name": "research_web",
    "description": (
        "Search the web to confirm an event's date or venue before you record "
        "it. Use whenever the note names a real event/competition without "
        "giving its date. Returns title/url/snippet/domain hits."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The web search query."},
            "reason": {"type": "string", "description": "Why you need this (audit)."},
        },
        "required": ["query"],
    },
}

_PROPOSE_TOOL = {
    "name": "propose_inputs",
    "description": (
        "Record the structured planner inputs extracted from the note. Call "
        "exactly once when you're done."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "upcoming_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "venue": {"type": "string"},
                    },
                    "required": ["name", "date"],
                },
            },
            "blackout_dates": {
                "type": "array",
                "items": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "post_type": {"type": "string", "description": "an enabled slug"},
                        "note": {"type": "string"},
                    },
                    "required": ["post_type"],
                },
            },
            "summary": {
                "type": "string",
                "description": "One line telling the operator what you picked up.",
            },
        },
    },
}


def interpret_planner_inputs(
    text: str,
    *,
    goal_choices: list[tuple[str, str]],
    allow_research: bool = True,
    today: Optional[date] = None,
    max_rounds: int = 4,
) -> dict:
    """Free-text note → structured ``{upcoming_events, goals, blackout_dates}``.

    ``goal_choices`` is the sport's enabled ``(slug, title)`` post types; a
    proposed goal whose slug isn't in that set is dropped (the model can
    target an enabled type but never invent one). Returns additionally a
    human ``summary`` and the ``research`` log it used.

    Raises ``ProviderNotConfigured`` / ``ProviderError`` (no heuristic
    fallback) so an unavailable AI is an honest error, never a fake event.
    """
    from mediahub.ai_core import ProviderError, ask_with_tools

    note = (text or "").strip()
    if not note:
        raise ProviderError("Empty note — nothing for the planner to read.")
    anchor = today or datetime.now(timezone.utc).date()
    valid_slugs = {slug for slug, _ in goal_choices}

    captured: dict = {}
    research: list[dict] = []

    def _tool(name: str, inp: dict) -> str:
        if name == "research_web":
            if not allow_research:
                return json.dumps({"hits": []})
            query = (inp.get("query") or "").strip()
            if not query:
                return "(empty query)"
            try:
                from mediahub.context_engine.research import ResearchClient

                hits = ResearchClient(num_results=4).search(query, num=4)
            except Exception as exc:  # research is best-effort, never fatal
                return f"(search failed: {exc})"
            evidence = [
                {
                    "title": (h.title or "")[:160],
                    "url": h.url,
                    "snippet": (h.snippet or "").strip()[:400],
                    "domain": h.domain,
                }
                for h in hits
                if (h.snippet or "").strip()
            ]
            research.append({"query": query, "hits": evidence})
            return json.dumps({"hits": evidence}, ensure_ascii=False)
        if name == "propose_inputs":
            captured.clear()
            captured.update(inp if isinstance(inp, dict) else {})
            return json.dumps({"ok": True})
        return json.dumps({"error": f"unknown tool: {name}"})

    use_research = allow_research
    tools = [_PROPOSE_TOOL]
    if use_research:
        tools = [_RESEARCH_TOOL, _PROPOSE_TOOL]

    convo = ask_with_tools(
        system=_system_prompt(anchor, goal_choices, research=use_research),
        user=note,
        tools=tools,
        on_tool_call=_tool,
        max_tokens=1200,
        max_rounds=max_rounds,
    )

    # Shape + sanitise the proposal. Authoritative validation still happens on
    # save (``inputs.save_planner_inputs``); this is interpretation-side
    # shaping so the review UI shows clean, in-bounds, future-dated values.
    today_iso = anchor.isoformat()

    events: list[dict] = []
    for raw in (captured.get("upcoming_events") or [])[: MAX_EVENTS * 2]:
        if not isinstance(raw, dict):
            continue
        when = _iso(raw.get("date"))
        name = str(raw.get("name") or "").strip()[:160]
        if not (when and name) or when < today_iso:
            continue  # only real, future-dated, named events feed the planner
        events.append(
            {"name": name, "date": when, "venue": str(raw.get("venue") or "").strip()[:160]}
        )
    events = sorted(events, key=lambda e: e["date"])[:MAX_EVENTS]

    blackouts: list[str] = []
    for raw in (captured.get("blackout_dates") or [])[: MAX_BLACKOUTS * 2]:
        when = _iso(raw)
        if when and when >= today_iso:
            blackouts.append(when)
    blackouts = sorted(set(blackouts))[:MAX_BLACKOUTS]

    goals: list[dict] = []
    for raw in (captured.get("goals") or [])[: MAX_GOALS * 2]:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("post_type") or "").strip()
        if slug not in valid_slugs:
            continue  # target an enabled type or it's dropped — never invented
        goals.append({"post_type": slug, "note": str(raw.get("note") or "").strip()[:240]})
    goals = goals[:MAX_GOALS]

    summary = str(captured.get("summary") or convo.text or "").strip()[:400]

    return {
        "upcoming_events": events,
        "blackout_dates": blackouts,
        "goals": goals,
        "summary": summary,
        "research": research,
        "provider": convo.provider,
    }


__all__ = ["interpret_planner_inputs"]
