"""Free-text chat — provider-agnostic brief builder using ai_core tool-use.

The chat session is driven by whichever LLM the user has picked in
Settings (Claude, ChatGPT, or Gemini). All three are wired through
``mediahub.ai_core`` so the same conversation works on any of them —
native tool-use translates per-provider behind the scenes.

There is no hand-coded "action enum", no JSON envelope parsing, and no
heuristic fallback. The model itself decides when to research, when to
ask, and when to propose a brief by calling the provided tools. If no
provider is configured the chat surfaces a clear error message.
"""

from __future__ import annotations

import json
from typing import Optional

from .session import ChatSession, save_session


_SYSTEM_PROMPT = """\
You are MediaHub's brief-building assistant. You help a sports club or
society turn a free-text idea into a structured brief that the content
generator turns into a branded post.

Talk to the user like a thoughtful editor. Reuse facts they've already
given you — never re-ask. When you want to verify a name, venue, event,
or PB, use the `research_web` tool. Don't guess facts about real people
/ clubs / venues.

When you have enough to build a brief, call the `propose_brief` tool.
The brief object is yours to shape — what you'd hand a designer. After
a brief is proposed and the user pushes back, call `propose_brief`
again with a revised version.

Don't pile questions. Ask the one thing that unblocks you most.
"""


_TOOLS = [
    {
        "name": "research_web",
        "description": (
            "Search the web for evidence about a swimmer, club, venue, "
            "event, or any fact you want to verify before answering. Use "
            "this whenever you'd otherwise have to guess about a "
            "real-world entity. Returns a list of snippets with title, "
            "url, snippet, and domain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The web search query."},
                "reason": {"type": "string", "description": "Why you need this (audit/logging)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "propose_brief",
        "description": (
            "Propose a content brief for the user to accept or decline. "
            "The brief is whatever structured object the content "
            "generators need — headline, body, hashtags, visual concept, "
            "tone, platform, etc. Call this again to revise the brief "
            "after user feedback."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "object", "description": "The brief object."},
                "summary": {
                    "type": "string",
                    "description": "One-line summary of the brief shown to the user.",
                },
            },
            "required": ["brief"],
        },
    },
]


_ONESHOT_SYSTEM = """\
You are MediaHub's brief builder. Turn ONE free-text request from a sports
club or society into a single, ready-to-design content brief for a branded
social graphic. Interpret the request — however short or detailed — and
decide the strongest post.

Return STRICT JSON ONLY (no prose, no markdown fences) with this shape:
{
  "headline": "<short punchy display line, <= 60 chars>",
  "body": "<caption body, 1-3 sentences, human and on-voice>",
  "hashtags": ["<word without #>", ...],
  "platform": "Instagram",
  "visual_concept": "<one line describing the graphic's look/subject>",
  "tone": "<e.g. celebratory, warm, hype, informative>",
  "wants_reel": false,
  "title": "<3-6 word internal label for this draft>"
}

Rules:
- Do NOT invent specific facts about real people, clubs, results, dates or
  scores the user didn't give you. If the request is vague, keep the copy
  general and evocative rather than fabricating details.
- Honour the club's brand voice when provided.
- platform is one of Instagram, Facebook, X, TikTok, LinkedIn.
- wants_reel is true ONLY if the user explicitly asks for a video / reel /
  animation; otherwise false (a still graphic).
"""


def _parse_brief_json(raw: str) -> dict:
    """Tolerant strict-JSON parse of a one-shot brief. Raises ProviderError
    (never returns a fabricated brief) when the model didn't return usable
    JSON — an honest error beats a fake post."""
    from mediahub.ai_core import ProviderError

    s = (raw or "").strip()
    if s.startswith("```"):
        # ```json … ``` or ``` … ```
        inner = s.split("```")
        if len(inner) >= 2:
            s = inner[1]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        s = s[a : b + 1]
    try:
        data = json.loads(s)
    except Exception as e:
        raise ProviderError(f"The brief wasn't valid JSON: {str(e)[:120]}") from e
    if not isinstance(data, dict):
        raise ProviderError("The brief wasn't a JSON object.")
    out = {
        "headline": str(data.get("headline") or "").strip()[:120],
        "body": str(data.get("body") or "").strip(),
        "hashtags": [
            str(h).lstrip("#").strip() for h in (data.get("hashtags") or []) if str(h).strip()
        ][:8],
        "platform": (str(data.get("platform") or "Instagram").strip() or "Instagram"),
        "visual_concept": str(data.get("visual_concept") or "").strip(),
        "tone": str(data.get("tone") or "").strip(),
        "wants_reel": bool(data.get("wants_reel")),
        "title": str(data.get("title") or "").strip()[:80],
    }
    if not (out["headline"] or out["body"]):
        raise ProviderError("The brief had no usable copy.")
    return out


def build_brief_from_prompt(prompt: str, *, club_brand: Optional[dict] = None) -> dict:
    """One-shot: a single free-text prompt → a complete content brief.

    Pure AI via ``ai_core.ask`` — interprets whatever the user asked for and
    returns a brief the graphic pipeline can render. Raises
    ``ProviderNotConfigured`` / ``ProviderError`` (no heuristic/templated
    fallback) so an unavailable provider is an honest error, never a fake post.
    """
    from mediahub.ai_core import ask, ProviderError

    text = (prompt or "").strip()
    if not text:
        raise ProviderError("Empty prompt — nothing to brief.")
    system = _ONESHOT_SYSTEM
    if club_brand:
        from mediahub.ai_core import narrate_brand

        brand_prose = narrate_brand(club_brand)
        if brand_prose:
            system = system + "\n\nBrand voice:\n" + brand_prose
    raw = ask(system, text, max_tokens=900)
    return _parse_brief_json(raw)


def _render_history_as_prose(session: ChatSession) -> str:
    """Flatten the chat into a single prose transcript for the user message.

    We send the WHOLE conversation as one natural-language transcript on
    each turn rather than as a multi-message array. This keeps the
    multi-provider abstraction simple — every provider gets the same
    plain-text user message + tools.
    """
    lines: list[str] = []
    for m in session.messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"USER: {content}")
        elif role == "assistant":
            lines.append(f"ASSISTANT: {content}")
        elif role == "system_note":
            lines.append(f"[NOTE: {content}]")
    return "\n\n".join(lines)


def next_assistant_turn(
    session: ChatSession, club_brand: Optional[dict] = None, max_rounds: int = 4
) -> dict:
    """Drive one assistant turn. Mutates and saves the session.

    Returns a dict the UI can render directly:
      {"kind": "message", "text": str}    — plain reply / question
      {"kind": "brief",   "brief": dict,  — model proposed a brief
                           "summary": str}
      {"kind": "error",   "text": str}    — provider error or unconfigured
    """
    from mediahub.ai_core import (
        ask_with_tools,
        ProviderNotConfigured,
        ProviderError,
    )

    system = _SYSTEM_PROMPT
    if club_brand:
        from mediahub.ai_core import narrate_brand

        brand_prose = narrate_brand(club_brand)
        if brand_prose:
            system = system + "\n\nBrand voice:\n" + brand_prose

    transcript = _render_history_as_prose(session)
    if not transcript:
        return {"kind": "error", "text": "No user message yet."}

    def _tool(name: str, inp: dict) -> str:
        if name == "research_web":
            query = (inp.get("query") or "").strip()
            if not query:
                return "(empty query)"
            try:
                from mediahub.context_engine.research import ResearchClient

                client = ResearchClient(num_results=4)
                hits = client.search(query, num=4)
            except Exception as e:
                return f"(search failed: {e})"
            evidence = []
            for h in hits:
                snip = (h.snippet or "").strip()
                if not snip:
                    continue
                evidence.append(
                    {
                        "title": (h.title or "")[:160],
                        "url": h.url,
                        "snippet": snip[:400],
                        "domain": h.domain,
                    }
                )
            session.research_log.append(
                {
                    "query": query,
                    "reason": inp.get("reason", ""),
                    "hits": evidence,
                }
            )
            return json.dumps({"hits": evidence}, ensure_ascii=False)
        if name == "propose_brief":
            brief = inp.get("brief") or {}
            summary = inp.get("summary") or ""
            if isinstance(brief, dict):
                session.pending_brief = brief
                session._chat_pending_summary = summary  # type: ignore[attr-defined]
            return json.dumps({"ok": True})
        return json.dumps({"error": f"unknown tool: {name}"})

    try:
        convo = ask_with_tools(
            system=system,
            user=transcript,
            tools=_TOOLS,
            on_tool_call=_tool,
            max_tokens=1200,
            max_rounds=max_rounds,
        )
    except ProviderNotConfigured as e:
        msg = str(e)
        session.add_assistant_message(msg, meta={"error": "no_provider"})
        save_session(session)
        return {"kind": "error", "text": msg}
    except ProviderError as e:
        msg = f"LLM provider error: {e}"
        session.add_assistant_message(msg, meta={"error": "provider_error"})
        save_session(session)
        return {"kind": "error", "text": msg}

    if session.pending_brief is not None:
        summary = (getattr(session, "_chat_pending_summary", "") or "").strip()
        if not summary:
            summary = convo.text.strip() or "Here's a draft brief — accept or push back."
        session.add_assistant_message(
            summary,
            meta={
                "kind": "brief",
                "brief": session.pending_brief,
                "provider": convo.provider,
            },
        )
        save_session(session)
        return {
            "kind": "brief",
            "brief": session.pending_brief,
            "summary": summary,
            "provider": convo.provider,
        }

    text = convo.text.strip() or "(no reply — try again)"
    session.add_assistant_message(text, meta={"kind": "message", "provider": convo.provider})
    save_session(session)
    return {"kind": "message", "text": text, "provider": convo.provider}
