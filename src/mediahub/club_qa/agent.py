"""club_qa/agent.py — bounded tool-loop Q&A over the org's own results data.

The model gets three read-only tools over THIS organisation's persisted
runs and athlete registry, and must answer only from what the tools
return. Grounding is the deterministic ledger (run JSON + the athletes
SQLite registry), never a vector store and never the open web — so a
"when did Ella last PB in 100 Free?" answer is exactly as trustworthy as
the parsed results it cites.

Provider errors propagate (``ProviderNotConfigured`` / ``ProviderError``)
so callers surface an honest "configure a provider" message — there is no
heuristic fallback answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_MAX_RUNS_LISTED = 15
_MAX_ACHIEVEMENTS_SHOWN = 30
_MAX_SWIMS_SHOWN = 40

_SYSTEM_PROMPT = (
    "You are the club's data assistant. Answer the user's question about "
    "the club's own swimming results using ONLY the tools provided.\n\n"
    "Rules:\n"
    "- Every fact in your answer must come from a tool result in this "
    "conversation — never from general knowledge, never guessed.\n"
    "- Name the meet (and the date when known) for each fact you cite.\n"
    "- If the tools cannot answer the question, say plainly that the "
    "club's data doesn't contain the answer. Do not speculate.\n"
    "- Keep the answer short and direct: a sentence or two, or a short "
    "list when the question asks for several results.\n"
    "- British English."
)

_TOOLS: list[dict] = [
    {
        "name": "list_recent_runs",
        "description": (
            "List this organisation's processed meets (runs), newest first: "
            "run_id, meet name, dates, venue and how many ranked moments "
            "each produced. Start here to find which run holds the answer."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_run_details",
        "description": (
            "Full detail of one run: meet name, dates, venue, course, and "
            "every ranked achievement (swimmer, event, time, headline, "
            "achievement type, priority)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run id from list_recent_runs."}
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_athlete_history",
        "description": (
            "One athlete's logged swim history across all meets, newest "
            "first: event, time, date and which meet it came from. Use the "
            "athlete's name as it appears in results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Athlete name, e.g. 'Alice Lee'."}
            },
            "required": ["name"],
        },
    },
]


@dataclass
class QAEnv:
    """Injected data access — keeps the agent testable and org-scoped."""

    runs_dir: Path
    profile_id: str = ""
    athletes_db_path: Optional[Path] = None


@dataclass
class QAAnswer:
    answer: str
    provider: str = ""
    tool_calls: int = 0
    runs_consulted: list[dict] = field(default_factory=list)


def _fmt_cs(time_cs) -> str:
    """Centiseconds → display time ('1:02.34' / '57.95'). '' when unknown."""
    try:
        cs = int(time_cs)
    except (TypeError, ValueError):
        return ""
    if cs <= 0:
        return ""
    minutes, rem = divmod(cs, 6000)
    seconds, hundredths = divmod(rem, 100)
    if minutes:
        return f"{minutes}:{seconds:02d}.{hundredths:02d}"
    return f"{seconds}.{hundredths:02d}"


def _owned_runs(env: QAEnv) -> list[tuple[str, dict]]:
    """(run_id, run_data) for every run this org owns, newest first.

    Ownership is an exact ``profile_id`` match — stricter than the web
    layer's legacy-ownerless allowance, because a Q&A answer must never
    quietly blend another tenant's (or untagged) data into this org's
    facts. Sandbox deployments with no orgs pass ``profile_id=""`` and
    see only unstamped runs, mirroring the single-tenant case.
    """
    out: list[tuple[str, dict]] = []
    runs_dir = Path(env.runs_dir)
    if not runs_dir.exists():
        return out
    for p in runs_dir.glob("*.json"):
        if "__" in p.name:  # workflow/comms sidecars, not runs
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if (data.get("profile_id") or "") != (env.profile_id or ""):
            continue
        run_id = data.get("run_id") or p.stem
        out.append((run_id, data))

    def _sort_key(item: tuple[str, dict]) -> str:
        meet = item[1].get("meet") or {}
        return str(meet.get("start_date") or "") + str(item[1].get("finished_at") or "")

    out.sort(key=_sort_key, reverse=True)
    return out


def _run_line(run_id: str, data: dict) -> str:
    meet = data.get("meet") or {}
    rr = data.get("recognition_report") or {}
    n = len(rr.get("ranked_achievements") or [])
    bits = [f"run_id={run_id}", meet.get("name") or "(unnamed meet)"]
    if meet.get("start_date"):
        bits.append(str(meet["start_date"]))
    if meet.get("venue"):
        bits.append(str(meet["venue"]))
    bits.append(f"{n} ranked moments")
    return " · ".join(bits)


def _tool_list_recent_runs(env: QAEnv) -> str:
    runs = _owned_runs(env)
    if not runs:
        return "No processed runs found for this organisation."
    shown = runs[:_MAX_RUNS_LISTED]
    lines = [f"{len(runs)} run(s) for this organisation (newest first):"]
    lines += [f"- {_run_line(rid, d)}" for rid, d in shown]
    if len(runs) > len(shown):
        lines.append(f"(+{len(runs) - len(shown)} older runs not shown)")
    return "\n".join(lines)


def _tool_get_run_details(env: QAEnv, run_id: str) -> str:
    run_id = (run_id or "").strip()
    if not run_id:
        return "No run_id given."
    data = dict(_owned_runs(env)).get(run_id)
    if data is None:
        return f"No run with id {run_id} for this organisation."
    meet = data.get("meet") or {}
    rr = data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    lines = [f"Meet: {meet.get('name') or '(unnamed meet)'}"]
    for label, key in (("Dates", "start_date"), ("Venue", "venue"), ("Course", "course")):
        if meet.get(key):
            val = str(meet[key])
            if key == "start_date" and meet.get("end_date"):
                val += f" to {meet['end_date']}"
            lines.append(f"{label}: {val}")
    lines.append(f"Ranked achievements ({len(ranked)}):")
    for i, ra in enumerate(ranked[:_MAX_ACHIEVEMENTS_SHOWN], start=1):
        a = ra.get("achievement") or {}
        rf = a.get("raw_facts") or {}
        time_str = rf.get("time_str") or a.get("time") or ""
        bits = [a.get("swimmer_name") or "(unknown)", a.get("event") or ""]
        if time_str:
            bits.append(str(time_str))
        if a.get("headline"):
            bits.append(str(a["headline"]))
        if a.get("type"):
            bits.append(f"[{a['type']}]")
        lines.append(f"#{i} " + " — ".join(b for b in bits if b))
    if len(ranked) > _MAX_ACHIEVEMENTS_SHOWN:
        lines.append(f"(+{len(ranked) - _MAX_ACHIEVEMENTS_SHOWN} more not shown)")
    return "\n".join(lines)


def _tool_get_athlete_history(env: QAEnv, name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "No athlete name given."
    try:
        from mediahub.athletes import athlete_swims, resolve
    except Exception:
        return "The athlete registry is unavailable on this deployment."
    rec = resolve(env.profile_id, name, db_path=env.athletes_db_path)
    if rec is None:
        return f"No athlete named '{name}' in this organisation's registry."
    swims = athlete_swims(env.profile_id, rec.athlete_id, db_path=env.athletes_db_path)
    if not swims:
        return f"{rec.canonical_name} is in the registry but has no logged swims yet."
    meet_names = {rid: (d.get("meet") or {}).get("name") or rid for rid, d in _owned_runs(env)}
    lines = [f"{rec.canonical_name} — {len(swims)} logged swim(s), newest first:"]
    for s in swims[:_MAX_SWIMS_SHOWN]:
        t = _fmt_cs(s.get("time_cs"))
        bits = [str(s.get("event") or "")]
        if t:
            bits.append(t)
        if s.get("swim_date"):
            bits.append(f"on {s['swim_date']}")
        meet = meet_names.get(s.get("run_id") or "")
        if meet:
            bits.append(f"at {meet}")
        lines.append("- " + " · ".join(b for b in bits if b))
    if len(swims) > _MAX_SWIMS_SHOWN:
        lines.append(f"(+{len(swims) - _MAX_SWIMS_SHOWN} older swims not shown)")
    return "\n".join(lines)


def answer_club_question(
    question: str,
    env: QAEnv,
    *,
    max_rounds: int = 6,
    provider: Optional[str] = None,
) -> QAAnswer:
    """Answer one question about the org's own results data.

    Raises ``ProviderNotConfigured`` / ``ProviderError`` from the LLM layer
    — the caller decides how to surface them.
    """
    from mediahub.ai_core import ask_with_tools

    question = (question or "").strip()
    if not question:
        return QAAnswer(answer="No question was asked.")

    consulted: dict[str, str] = {}  # run_id -> meet name

    def _note_run(run_id: str) -> None:
        data = dict(_owned_runs(env)).get(run_id)
        if data is not None:
            consulted[run_id] = (data.get("meet") or {}).get("name") or run_id

    def _tool(name: str, inp: dict) -> str:
        inp = inp or {}
        if name == "list_recent_runs":
            return _tool_list_recent_runs(env)
        if name == "get_run_details":
            run_id = str(inp.get("run_id") or "")
            out = _tool_get_run_details(env, run_id)
            if not out.startswith("No run"):
                _note_run(run_id.strip())
            return out
        if name == "get_athlete_history":
            return _tool_get_athlete_history(env, str(inp.get("name") or ""))
        return json.dumps({"error": f"unknown tool: {name}"})

    convo = ask_with_tools(
        system=_SYSTEM_PROMPT,
        user=question,
        tools=_TOOLS,
        on_tool_call=_tool,
        max_tokens=900,
        max_rounds=max_rounds,
        provider=provider,
    )
    return QAAnswer(
        answer=(convo.text or "").strip(),
        provider=convo.provider,
        tool_calls=len(convo.tool_calls),
        runs_consulted=[{"run_id": rid, "meet_name": mn} for rid, mn in consulted.items()],
    )
